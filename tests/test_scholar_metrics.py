"""Offline tests for scholar_metrics — pure math, normalization, scoring,
and the score-gaps CLI. Canned data, no network."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import scholar  # noqa: E402
import scholar_metrics as sm  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def test_dense_series_zero_fills_and_accepts_string_keys():
    s = sm.dense_series({2020: 3, "2022": 5}, 2019, 2022)
    assert s == [(2019, 0), (2020, 3), (2021, 0), (2022, 5)]


def test_cagr_doubling_series():
    values = [10, 20, 40, 80, 160]  # doubles yearly
    g = sm.cagr(values)
    assert 0.8 < g < 1.2  # ~100%/yr; smoothed endpoints, effective span n-2
    assert sm.cagr([1, 2]) is None
    assert sm.cagr([1, 2, 4]) is not None


def test_log_slope_and_doubling_time():
    values = [10, 20, 40, 80, 160]
    slope = sm.log_slope(values)
    dt = sm.doubling_time(slope)
    assert 0.9 < dt < 1.2  # doubling yearly
    assert sm.doubling_time(-0.1) is None
    assert sm.doubling_time(None) is None


def test_recency_share():
    assert sm.recency_share([1, 1, 1, 1, 3, 3], k=2) == 6 / 10
    assert sm.recency_share([0, 0]) is None


def test_kleinberg_burst_detects_recent_surge():
    base = [1000] * 10
    flat = [10] * 10
    surge = [10] * 7 + [60, 80, 100]
    assert sm.kleinberg_burst(flat, base)["burst_weight"] == 0.0
    b = sm.kleinberg_burst(surge, base)
    assert b["burst_weight"] > 0
    assert b["bursting_now"] is True
    assert b["burst_years_idx"][-1] == 9


def test_kleinberg_burst_ignores_database_growth():
    # Topic grows exactly with the database: no burst.
    base = [100 * (2 ** i) for i in range(8)]
    rel = [10 * (2 ** i) for i in range(8)]
    assert sm.kleinberg_burst(rel, base)["burst_weight"] == 0.0


def test_rao_stirling_hierarchy_distances():
    assert sm.rao_stirling([]) is None
    assert sm.rao_stirling([{"share": 1.0, "subfield": "s1", "field": "f1", "domain": "d1"}]) == 0.0
    two_domains = [
        {"share": 0.5, "subfield": "s1", "field": "f1", "domain": "d1"},
        {"share": 0.5, "subfield": "s2", "field": "f2", "domain": "d2"},
    ]
    assert sm.rao_stirling(two_domains) == 0.5  # 2 * (1.0 * .5 * .5)
    same_subfield = [
        {"share": 0.5, "subfield": "s1", "field": "f1", "domain": "d1"},
        {"share": 0.5, "subfield": "s1", "field": "f1", "domain": "d1"},
    ]
    assert sm.rao_stirling(same_subfield) == 0.125  # 2 * (0.25 * .5 * .5)


def test_hhi():
    assert sm.hhi([25, 25, 25, 25]) == 0.25
    assert sm.hhi([]) is None
    assert sm.hhi([10]) == 1.0


def test_overlap_stats_bridge_configuration():
    # Two big literatures, tiny intersection: high bridge opportunity.
    sparse = sm.overlap_stats(5000, 4000, 5, 1_000_000)
    dense = sm.overlap_stats(5000, 4000, 3500, 1_000_000)
    assert sparse["bridge_opportunity"] > dense["bridge_opportunity"]
    assert sparse["jaccard"] < 0.001
    assert dense["containment"] == 3500 / 4000
    assert -1 <= sparse["npmi"] <= 1


def test_overlap_stats_zero_intersection():
    s = sm.overlap_stats(100, 50, 0, 10_000)
    assert s["jaccard"] == 0.0 and s["containment"] == 0.0 and s["npmi"] is None
    assert s["bridge_opportunity"] > 0


def test_overlap_stats_empty_side_is_unmeasurable_not_open():
    s = sm.overlap_stats(4037, 0, 0, 1_000_000)
    assert s["bridge_opportunity"] is None  # probe matched nothing ≠ open field
    assert sm.overlap_stats(10, 10, 5, 0)["bridge_opportunity"] is None


def test_sleeping_beauty():
    # Dormant then spike: line from (0,0) to (4,10) vs flat zeros.
    series = [(2000, 0), (2001, 0), (2002, 0), (2003, 0), (2004, 10)]
    assert sm.sleeping_beauty(series) == 15.0
    assert sm.sleeping_beauty([(2000, 5), (2001, 3)]) == 0.0  # peak at t=0
    assert sm.sleeping_beauty([]) is None


def test_price_index():
    assert sm.price_index([2019, 2020, 2010, 2000], 2021) == 0.5
    assert sm.price_index([], 2021) is None


def test_minmax_handles_none_and_constant():
    assert sm.minmax([1.0, None, 3.0]) == [0.0, None, 1.0]
    assert sm.minmax([2.0, 2.0]) == [0.5, 0.5]
    assert sm.minmax([None, None]) == [None, None]


def test_weighted_geometric_drops_missing_and_floors_zero():
    w = {"a": 0.5, "b": 0.5}
    assert sm.weighted_geometric({"a": 0.64, "b": None}, w) == 0.64
    # eps floor: zero hurts but does not annihilate
    v = sm.weighted_geometric({"a": 1.0, "b": 0.0}, w)
    assert 0 < v < 0.3
    assert sm.weighted_geometric({}, w) is None


def test_rank_sensitivity_stable_when_order_is_clear():
    gaps = {
        "G1": {"a": 0.9, "b": 0.9},
        "G2": {"a": 0.2, "b": 0.2},
    }
    sens = sm.rank_sensitivity(gaps, {"a": 0.5, "b": 0.5})
    assert sens["G1"] == {"rank": 1, "rank_min": 1, "rank_max": 1}
    assert sens["G2"]["rank"] == 2


def test_panel_agreement_from_score_spread():
    full = {"novelty": [4, 4, 4], "importance": [3, 3, 3],
            "answerability": [5, 5, 5], "actionability": [2, 2, 2]}
    split = {"novelty": [1, 5], "importance": [1, 5],
             "answerability": [1, 5], "actionability": [1, 5]}
    assert sm.panel_agreement(full) == 1.0
    assert sm.panel_agreement(split) == 0.0
    assert sm.panel_agreement({"novelty": 4}) is None  # no panel, no agreement
    assert sm.panel_agreement({"novelty": [4, 3]}) == 0.75


def test_rubric_panel_lists_take_median_in_code():
    scores = sm.rubric_to_scores({"novelty": [5, 3, 4], "importance": [2, 4],
                                  "answerability": 3, "actionability": None})
    assert scores["novelty"] == 0.75       # median 4 → (4-1)/4
    assert scores["importance"] == 0.5     # even panel → mean of middle two = 3
    assert scores["answerability"] == 0.5
    assert scores["actionability"] is None
    assert sm.rubric_to_scores({"novelty": []})["novelty"] is None


def _metric_stub(gid, total_works, cagr_v, n_supporting, bridge_opp=None):
    return {
        "gap_id": gid, "type": "knowledge", "statement": f"gap {gid}",
        "window": [2014, 2025],
        "probe_profiles": [],
        "momentum": {"cagr": cagr_v, "log_slope": None, "recency_share_3y": 0.4,
                     "burst_weight": 1.0 if cagr_v and cagr_v > 0.2 else 0.0,
                     "bursting_now": False},
        "crowding": {"total_works": total_works, "venue_hhi": 0.1},
        "accessibility": {"oa_share": 0.5},
        "review_deficit": {"recent_primary_per_review": 10.0},
        "bridge": ({"bridge_opportunity": bridge_opp} if bridge_opp is not None else None),
        "diversity": None,
        "corroboration": {"n_supporting": n_supporting, "years_span": 3,
                          "recent_share": 1.0, "mean_cited_by": 10},
    }


def test_composite_scores_ranks_hot_uncrowded_corroborated_gap_first():
    metrics_list = [
        _metric_stub("G1", total_works=200, cagr_v=0.5, n_supporting=8, bridge_opp=0.8),
        _metric_stub("G2", total_works=90_000, cagr_v=0.01, n_supporting=1, bridge_opp=0.1),
    ]
    rubric = {"G1": {"novelty": 4, "importance": 4, "answerability": 4, "actionability": 4},
              "G2": {"novelty": 2, "importance": 3, "answerability": 3, "actionability": 3}}
    out = sm.composite_scores(metrics_list, rubric, survival={})
    assert out["gaps"]["G1"]["gap_score"] > out["gaps"]["G2"]["gap_score"]
    assert out["gaps"]["G1"]["survival"] == "survived"


def test_composite_scores_refuted_gap_excluded():
    metrics_list = [_metric_stub("G1", 200, 0.5, 5), _metric_stub("G2", 300, 0.4, 4)]
    rubric = {g: {"novelty": 4, "importance": 4, "answerability": 4, "actionability": 4}
              for g in ("G1", "G2")}
    out = sm.composite_scores(metrics_list, rubric,
                              survival={"G2": {"verdict": "refuted"}})
    assert out["gaps"]["G2"]["excluded"] is True
    assert out["gaps"]["G2"]["gap_score"] == 0.0
    assert out["gaps"]["G1"]["excluded"] is False


def test_composite_scores_contested_gap_discounted():
    metrics_list = [_metric_stub("G1", 200, 0.5, 5)]
    rubric = {"G1": {"novelty": 4, "importance": 4, "answerability": 4, "actionability": 4}}
    full = sm.composite_scores(metrics_list, rubric, survival={})
    disc = sm.composite_scores(metrics_list, rubric,
                               survival={"G1": {"verdict": "contested"}})
    assert disc["gaps"]["G1"]["gap_score"] < full["gaps"]["G1"]["gap_score"]


def _write_score_inputs(td, with_survival_for=("G1", "G2", "G3")):
    mp = os.path.join(td, "gap-metrics.json")
    rp = os.path.join(td, "rubric.json")
    sp = os.path.join(td, "survival.json")
    json.dump({"window": [2014, 2025], "metrics": [
        _metric_stub("G1", 200, 0.5, 8, 0.7),
        _metric_stub("G2", 50_000, 0.02, 1, 0.1),
        _metric_stub("G3", 500, 0.3, 4, 0.4),
    ]}, open(mp, "w"))
    json.dump({"gaps": {
        "G1": {"novelty": 5, "importance": 4, "answerability": 4, "actionability": 4},
        "G2": {"novelty": 2, "importance": 3, "answerability": 4, "actionability": 3},
        "G3": {"novelty": 3, "importance": 4, "answerability": 3, "actionability": 4},
    }}, open(rp, "w"))
    verdicts = {"G1": {"verdict": "survived"}, "G2": {"verdict": "survived"},
                "G3": {"verdict": "refuted", "reason": "already answered"}}
    json.dump({"gaps": {g: v for g, v in verdicts.items() if g in with_survival_for}},
              open(sp, "w"))
    return mp, rp, sp


def test_score_gaps_cli_writes_ranked_json_and_leaderboard():
    with tempfile.TemporaryDirectory() as td:
        mp, rp, sp = _write_score_inputs(td)
        op = os.path.join(td, "scores.json")
        lp = os.path.join(td, "leaderboard.md")
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scholar.py"),
                            "score-gaps", "--metrics", mp, "--rubric", rp,
                            "--survival", sp, "--out", op, "--leaderboard", lp],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        scores = json.load(open(op))
        ranked = scores["ranked"]
        assert ranked[0]["gap_id"] == "G1"
        assert ranked[-1]["gap_id"] == "G3" and ranked[-1]["excluded"]
        assert "rank_min" in ranked[0]
        md = open(lp).read()
        assert "Ranked research gaps" in md and "G1" in md
        assert "Refuted (excluded from ranking)" in md


def test_score_gaps_survival_gate_blocks_missing_verdicts():
    with tempfile.TemporaryDirectory() as td:
        mp, rp, sp = _write_score_inputs(td, with_survival_for=("G1",))
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scholar.py"),
                            "score-gaps", "--metrics", mp, "--rubric", rp,
                            "--survival", sp, "--require-survival",
                            "--out", os.path.join(td, "s.json")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 1
        assert "G2" in r.stderr and "G3" in r.stderr


def test_as_gap_map_accepts_three_shapes():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "x.json")
        json.dump({"G1": {"novelty": 4}}, open(p, "w"))
        assert scholar._as_gap_map(p)["G1"]["novelty"] == 4
        json.dump({"gaps": {"G1": {"novelty": 3}}}, open(p, "w"))
        assert scholar._as_gap_map(p)["G1"]["novelty"] == 3
        json.dump([{"gap_id": "G1", "novelty": 2}], open(p, "w"))
        assert scholar._as_gap_map(p)["G1"]["novelty"] == 2
    assert scholar._as_gap_map(None) == {}


def test_openalex_normalize_carries_topics_and_fwci():
    import scholar_apis as apis
    work = {"display_name": "X", "ids": {"doi": "https://doi.org/10.1/t"},
            "publication_year": 2024, "authorships": [], "referenced_works": [],
            "fwci": 2.5,
            "topics": [{"id": "https://openalex.org/T1", "display_name": "T",
                        "score": 0.9,
                        "subfield": {"id": "https://openalex.org/subfields/11"},
                        "field": {"id": "https://openalex.org/fields/1"},
                        "domain": {"id": "https://openalex.org/domains/3"}}]}
    p = apis._openalex_normalize(work, "q")
    assert p["fwci"] == 2.5
    assert p["topics"][0] == {"id": "T1", "name": "T", "score": 0.9,
                              "subfield": "11", "field": "1", "domain": "3"}
