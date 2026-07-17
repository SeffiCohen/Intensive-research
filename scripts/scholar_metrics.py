"""scholar_metrics.py — deterministic bibliometric metrics for gap ranking.

Pure-math functions (no network) live at the top so they are offline-testable;
OpenAlex-backed collectors take a cache and honor the degradation contract
(never raise for network conditions — return a value plus a degraded reason).

Metric provenance (formulas follow the originating papers):
  - Burst detection: Kleinberg (2003), "Bursty and Hierarchical Structure in
    Streams" — batched two-state automaton, Viterbi decoded.
  - Rao-Stirling diversity: Stirling (2007) / Rao quadratic entropy over the
    OpenAlex topic hierarchy (topic < subfield < field < domain).
  - Sleeping-beauty coefficient: Ke, Ferrara, Radicchi, Flammini (2015), PNAS.
  - Price index: de Solla Price (1970) — share of references ≤5 years old.
  - HHI: Herfindahl-Hirschman concentration over venues.
  - Composite: weighted geometric mean (multiplicative MCDA), so a near-zero
    core criterion cannot be compensated away — cf. CHNRI-style priority
    scoring where all criteria must clear a bar.
"""
from __future__ import annotations

import json
import math
import urllib.parse

import scholar_http as http

# --------------------------------------------------------------------------
# Pure math — series and growth
# --------------------------------------------------------------------------


def dense_series(year_counts: dict, year_from: int, year_to: int) -> list[tuple[int, int]]:
    """[(year, count)] for every year in [year_from, year_to], zero-filled."""
    out = []
    for y in range(year_from, year_to + 1):
        c = year_counts.get(y, year_counts.get(str(y), 0))
        out.append((y, int(c or 0)))
    return out


def cagr(values: list[int | float]) -> float | None:
    """Smoothed-endpoint compound annual growth rate.

    Endpoints are 2-year means with +1 smoothing so a zero start year does not
    blow up; None when the window is too short.
    """
    n = len(values)
    if n < 3:
        return None
    if n == 3:
        a, b, span = values[0] + 1, values[-1] + 1, 2
    else:
        # 2-year-mean endpoints sit at midpoints 0.5 and n-1.5 → span n-2.
        a = (values[0] + values[1]) / 2 + 1
        b = (values[-2] + values[-1]) / 2 + 1
        span = n - 2
    return (b / a) ** (1 / span) - 1


def log_slope(values: list[int | float]) -> float | None:
    """OLS slope of ln(y+1) per year — growth rate robust to zeros."""
    n = len(values)
    if n < 3:
        return None
    ys = [math.log(v + 1) for v in values]
    xbar = (n - 1) / 2
    ybar = sum(ys) / n
    sxx = sum((i - xbar) ** 2 for i in range(n))
    sxy = sum((i - xbar) * (ys[i] - ybar) for i in range(n))
    return sxy / sxx if sxx else None


def doubling_time(slope: float | None) -> float | None:
    """Years to double under exponential growth at `slope` (ln units/year)."""
    if slope is None or slope <= 0:
        return None
    return math.log(2) / slope


def recency_share(values: list[int | float], k: int = 3) -> float | None:
    """Share of the window's activity that happened in the last k years."""
    total = sum(values)
    if not total:
        return None
    return sum(values[-k:]) / total


def _log_binom(r: int, d: int, p: float) -> float:
    """-ln P(r | d, p) under Binomial(d, p), via lgamma."""
    p = min(max(p, 1e-12), 1 - 1e-12)
    lc = math.lgamma(d + 1) - math.lgamma(r + 1) - math.lgamma(d - r + 1)
    return -(lc + r * math.log(p) + (d - r) * math.log(1 - p))


def kleinberg_burst(rel: list[int], base: list[int], s: float = 2.0,
                    gamma: float = 1.0) -> dict:
    """Kleinberg's batched two-state burst automaton over yearly counts.

    rel[t] = topic hits in year t, base[t] = all works that year (denominator,
    so database growth is not read as a burst). State 0 emits at the overall
    rate p0 = R/D, state 1 at p1 = s*p0; entering the burst state costs
    gamma*ln(T). Returns total burst weight (sum of per-year cost savings
    inside bursts), the burst years, and whether the final year is bursting.
    """
    pairs = [(r, d) for r, d in zip(rel, base) if d > 0]
    T = len(pairs)
    empty = {"burst_weight": 0.0, "burst_years_idx": [], "bursting_now": False}
    if T < 3:
        return empty
    R = sum(r for r, _ in pairs)
    D = sum(d for _, d in pairs)
    if not R or not D:
        return empty
    p0 = R / D
    p1 = min(1 - 1e-9, s * p0)
    if p1 <= p0:
        return empty
    trans = gamma * math.log(T)
    # Viterbi over states {0, 1}.
    cost = [_log_binom(pairs[0][0], pairs[0][1], p0),
            _log_binom(pairs[0][0], pairs[0][1], p1) + trans]
    back: list[tuple[int, int]] = []
    for t in range(1, T):
        r, d = pairs[t]
        e0, e1 = _log_binom(r, d, p0), _log_binom(r, d, p1)
        stay0, from1 = cost[0], cost[1]  # moving down is free
        c0 = min(stay0, from1) + e0
        b0 = 0 if stay0 <= from1 else 1
        up, stay1 = cost[0] + trans, cost[1]
        c1 = min(up, stay1) + e1
        b1 = 0 if up < stay1 else 1
        cost = [c0, c1]
        back.append((b0, b1))
    state = 0 if cost[0] <= cost[1] else 1
    states = [state]
    for t in range(T - 2, -1, -1):
        state = back[t][state]
        states.append(state)
    states.reverse()
    weight = 0.0
    burst_idx = []
    for t, st in enumerate(states):
        if st == 1:
            r, d = pairs[t]
            weight += max(0.0, _log_binom(r, d, p0) - _log_binom(r, d, p1))
            burst_idx.append(t)
    return {"burst_weight": round(weight, 3), "burst_years_idx": burst_idx,
            "bursting_now": bool(states and states[-1] == 1)}


# --------------------------------------------------------------------------
# Pure math — diversity, concentration, overlap, dormancy
# --------------------------------------------------------------------------


def rao_stirling(topics: list[dict]) -> float | None:
    """Rao-Stirling diversity over OpenAlex topic shares.

    topics: [{"id", "share", "subfield", "field", "domain"}]. Pairwise
    distance from the hierarchy: same subfield 0.25, same field 0.5, same
    domain 0.75, different domains 1.0. Scaled by 2 so the value lives in
    [0, 1) (a single topic → 0).
    """
    tot = sum(t.get("share") or 0 for t in topics)
    if tot <= 0 or len(topics) < 2:
        return 0.0 if topics else None
    ps = [(t, (t.get("share") or 0) / tot) for t in topics]
    rs = 0.0
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            a, b = ps[i][0], ps[j][0]
            if a.get("subfield") and a.get("subfield") == b.get("subfield"):
                d = 0.25
            elif a.get("field") and a.get("field") == b.get("field"):
                d = 0.5
            elif a.get("domain") and a.get("domain") == b.get("domain"):
                d = 0.75
            else:
                d = 1.0
            rs += d * ps[i][1] * ps[j][1]
    return round(2 * rs, 4)


def hhi(counts: list[int | float]) -> float | None:
    """Herfindahl-Hirschman index of concentration; 1/n (dispersed) → 1."""
    total = sum(counts)
    if not total:
        return None
    return round(sum((c / total) ** 2 for c in counts), 4)


def overlap_stats(n_a: int, n_b: int, n_ab: int, n_total: int) -> dict:
    """Co-occurrence structure of two concepts (Swanson-style bridge signal).

    bridge_opportunity is high when both sides are substantial literatures but
    the intersection is nearly empty — the classic undiscovered-public-
    knowledge configuration.
    """
    union = n_a + n_b - n_ab
    jaccard = n_ab / union if union else None
    containment = n_ab / min(n_a, n_b) if min(n_a, n_b) else None
    npmi = None
    if n_total and n_a and n_b and n_ab:
        pa, pb, pab = n_a / n_total, n_b / n_total, n_ab / n_total
        denom = -math.log(pab)
        if denom > 0:
            npmi = round(math.log(pab / (pa * pb)) / denom, 4)
    if min(n_a, n_b) == 0 or not n_total:
        # An empty side means the probe phrase matched nothing — the bridge is
        # unmeasurable, not maximally open. None keeps it out of normalization.
        opportunity = None
    else:
        size = math.log1p(min(n_a, n_b)) / math.log1p(max(n_total, 2))
        opportunity = round((1 - (containment or 0.0)) * size, 4)
    return {
        "n_a": n_a, "n_b": n_b, "n_ab": n_ab,
        "jaccard": round(jaccard, 5) if jaccard is not None else None,
        "containment": round(containment, 4) if containment is not None else None,
        "npmi": npmi,
        "bridge_opportunity": opportunity,
        # A tiny side means the probe phrase barely matches the literature —
        # downstream judges should trust corpus evidence over these numbers.
        "weak_side": bool(min(n_a, n_b) < 25),
    }


def sleeping_beauty(citations_by_year: list[tuple[int, int]]) -> float | None:
    """Ke et al. (2015) beauty coefficient B from a (year, citations) series.

    B sums, from publication to the citation peak, the gap between the
    straight line joining (0, c0) and (t_m, c_max) and the actual curve,
    normalized by max(1, c_t). B = 0 for a monotone rise peaking immediately.
    """
    if not citations_by_year:
        return None
    series = sorted(citations_by_year)
    c = [v for _, v in series]
    tm = max(range(len(c)), key=lambda i: c[i])
    if tm == 0:
        return 0.0
    c0, cm = c[0], c[tm]
    b = 0.0
    for t in range(tm + 1):
        line = (cm - c0) / tm * t + c0
        b += (line - c[t]) / max(1, c[t])
    return round(b, 3)


def price_index(ref_years: list[int], pub_year: int, horizon: int = 5) -> float | None:
    """Share of references at most `horizon` years old at publication."""
    known = [y for y in ref_years if y]
    if not known:
        return None
    recent = sum(1 for y in known if pub_year - y <= horizon)
    return round(recent / len(known), 4)


# --------------------------------------------------------------------------
# Pure math — normalization and aggregation
# --------------------------------------------------------------------------


def minmax(values: list[float | None]) -> list[float | None]:
    """Min-max to [0,1] over the observed set; a constant set maps to 0.5."""
    obs = [v for v in values if v is not None]
    if not obs:
        return list(values)
    lo, hi = min(obs), max(obs)
    if hi == lo:
        return [0.5 if v is not None else None for v in values]
    return [round((v - lo) / (hi - lo), 4) if v is not None else None for v in values]


def squash(x: float, mid: float, scale: float) -> float:
    """Logistic squash of an unbounded value to (0,1)."""
    return 1 / (1 + math.exp(-(x - mid) / max(scale, 1e-9)))


def weighted_geometric(scores: dict, weights: dict, eps: float = 0.05) -> float | None:
    """Weighted geometric mean over [0,1] sub-scores.

    Missing sub-scores are dropped and their weight renormalized over what
    remains; present scores are floored at eps so a single zero cannot
    annihilate the product (it still hurts, multiplicatively).
    """
    used = {k: w for k, w in weights.items() if w > 0 and scores.get(k) is not None}
    wsum = sum(used.values())
    if not wsum:
        return None
    acc = sum(w * math.log(max(eps, min(1.0, scores[k]))) for k, w in used.items())
    return round(math.exp(acc / wsum), 4)


def rank_sensitivity(per_gap_scores: dict, weights: dict, perturb: float = 0.25) -> dict:
    """One-at-a-time weight perturbation → rank range per gap.

    per_gap_scores: {gap_id: {metric: score01}}. Returns
    {gap_id: {"rank": r, "rank_min": .., "rank_max": ..}} — a wide range means
    the ranking is a weight artifact, not a signal.
    """
    def ranks(w):
        comp = {g: weighted_geometric(s, w) or 0.0 for g, s in per_gap_scores.items()}
        ordered = sorted(comp, key=lambda g: (-comp[g], g))
        return {g: i + 1 for i, g in enumerate(ordered)}

    base = ranks(weights)
    lo = {g: r for g, r in base.items()}
    hi = {g: r for g, r in base.items()}
    for key in weights:
        if weights[key] <= 0:
            continue
        for factor in (1 - perturb, 1 + perturb):
            w2 = dict(weights)
            w2[key] = weights[key] * factor
            for g, r in ranks(w2).items():
                lo[g] = min(lo[g], r)
                hi[g] = max(hi[g], r)
    return {g: {"rank": base[g], "rank_min": lo[g], "rank_max": hi[g]} for g in base}


# --------------------------------------------------------------------------
# OpenAlex collectors (degradation contract: return (value, degraded_reason))
# --------------------------------------------------------------------------

_OPENALEX = "https://api.openalex.org/works"


def _oa_url(params: dict) -> str:
    if http.mailto():
        params = dict(params, mailto=http.mailto())
    return _OPENALEX + "?" + urllib.parse.urlencode(params)


def openalex_group_by(cache, group_by: str, search: str | None = None,
                      extra_filter: str | None = None, fresh: bool = False):
    """One aggregation call: [{key, key_display_name, count}], degraded."""
    params = {"group_by": group_by, "per-page": 200}
    if search:
        params["search"] = search
    if extra_filter:
        params["filter"] = extra_filter
    r = http.fetch(cache, _oa_url(params), ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    return (r.json() or {}).get("group_by", []) or [], None


def openalex_count(cache, search: str | None = None,
                   extra_filter: str | None = None, fresh: bool = False):
    """meta.count for a query — one cheap call."""
    params = {"per-page": 1}
    if search:
        params["search"] = search
    if extra_filter:
        params["filter"] = extra_filter
    r = http.fetch(cache, _oa_url(params), ttl_class="search", fresh=fresh)
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    return ((r.json() or {}).get("meta") or {}).get("count"), None


def openalex_yearly(cache, search: str | None, year_from: int, year_to: int,
                    extra_filter: str | None = None, fresh: bool = False):
    """Zero-filled yearly publication counts for a query, plus degraded."""
    flt = f"publication_year:{year_from}-{year_to}"
    if extra_filter:
        flt += "," + extra_filter
    groups, degraded = openalex_group_by(cache, "publication_year", search=search,
                                         extra_filter=flt, fresh=fresh)
    counts = {}
    for g in groups:
        try:
            counts[int(g.get("key"))] = g.get("count", 0)
        except (TypeError, ValueError):
            continue
    return dense_series(counts, year_from, year_to), degraded


def openalex_topic_shares(cache, search: str, extra_filter: str | None = None,
                          fresh: bool = False):
    """Topic distribution of a query's neighborhood via one sampled call.

    Fetches the top 100 works by relevance with only their topics selected and
    aggregates score-weighted topic shares (with subfield/field/domain ids for
    Rao-Stirling distances).
    """
    params = {"search": search, "per-page": 100, "select": "id,topics"}
    if extra_filter:
        params["filter"] = extra_filter
    r = http.fetch(cache, _oa_url(params), ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    agg: dict[str, dict] = {}
    for w in (r.json() or {}).get("results", []) or []:
        for t in (w.get("topics") or [])[:3]:
            tid = (t.get("id") or "").rsplit("/", 1)[-1]
            if not tid:
                continue
            entry = agg.setdefault(tid, {
                "id": tid,
                "name": t.get("display_name"),
                "share": 0.0,
                "subfield": ((t.get("subfield") or {}).get("id") or "").rsplit("/", 1)[-1] or None,
                "field": ((t.get("field") or {}).get("id") or "").rsplit("/", 1)[-1] or None,
                "domain": ((t.get("domain") or {}).get("id") or "").rsplit("/", 1)[-1] or None,
            })
            entry["share"] += float(t.get("score") or 0.0)
    topics = sorted(agg.values(), key=lambda t: -t["share"])
    for t in topics:
        t["share"] = round(t["share"], 3)
    return topics[:25], None


def query_profile(cache, query: str, year_from: int, year_to: int,
                  base_series: list[tuple[int, int]] | None = None,
                  fresh: bool = False) -> dict:
    """Full deterministic trend profile for one probe query (~5 API calls)."""
    degraded: list[str] = []

    def note(reason):
        if reason:
            degraded.append(reason)

    series, d = openalex_yearly(cache, query, year_from, year_to, fresh=fresh)
    note(d)
    values = [c for _, c in series]
    total = sum(values)

    burst = {}
    if base_series and len(base_series) == len(series):
        burst = kleinberg_burst(values, [c for _, c in base_series])

    venues, d = openalex_group_by(cache, "primary_location.source.id", search=query,
                                  extra_filter=f"publication_year:{year_from}-{year_to}",
                                  fresh=fresh)
    note(d)
    venue_counts = [g.get("count", 0) for g in venues[:25]]

    oa_groups, d = openalex_group_by(cache, "open_access.is_oa", search=query,
                                     extra_filter=f"publication_year:{year_from}-{year_to}",
                                     fresh=fresh)
    note(d)
    # Boolean group_by keys arrive as "1"/"0" (display name "true"/"false").
    oa_true = sum(g.get("count", 0) for g in oa_groups
                  if str(g.get("key")).lower() in ("1", "true")
                  or str(g.get("key_display_name")).lower() == "true")
    oa_all = sum(g.get("count", 0) for g in oa_groups)

    recent_from = max(year_from, year_to - 2)
    reviews, d = openalex_count(cache, query,
                                extra_filter=f"publication_year:{recent_from}-{year_to},type:review",
                                fresh=fresh)
    note(d)
    recent_total = sum(values[-(year_to - recent_from + 1):])

    slope = log_slope(values)
    return {
        "query": query,
        "window": [year_from, year_to],
        "series": series,
        "total_works": total,
        "cagr": round(cagr(values), 4) if cagr(values) is not None else None,
        "log_slope": round(slope, 4) if slope is not None else None,
        "doubling_time_years": round(doubling_time(slope), 1) if doubling_time(slope) else None,
        "recency_share_3y": round(recency_share(values), 4) if recency_share(values) is not None else None,
        "burst": burst,
        "venue_hhi": hhi(venue_counts),
        "venue_effective_n": round(1 / hhi(venue_counts), 1) if hhi(venue_counts) else None,
        "oa_share": round(oa_true / oa_all, 4) if oa_all else None,
        "recent_reviews": reviews,
        "recent_primary_per_review": (
            round(max(0, (recent_total or 0) - (reviews or 0)) / (1 + (reviews or 0)), 2)
            if recent_total is not None else None),
        "degraded": degraded or None,
    }


def base_yearly(cache, year_from: int, year_to: int, fresh: bool = False):
    """All-of-OpenAlex yearly counts — the burst-detection denominator."""
    return openalex_yearly(cache, None, year_from, year_to, fresh=fresh)


def openalex_topics_lookup(cache, query: str, limit: int = 8, fresh: bool = False):
    """Map a free-text subject onto OpenAlex curated topics (/topics search).

    Topic search is exact-ish; a compound subject ("X in Y") often matches
    nothing, so on an empty result retry once with the trailing word dropped.
    """
    results, q = [], query.strip()
    for attempt in (q, " ".join(q.split()[:-1])):
        if not attempt:
            break
        params = {"search": attempt, "per-page": min(limit, 25)}
        if http.mailto():
            params["mailto"] = http.mailto()
        url = "https://api.openalex.org/topics?" + urllib.parse.urlencode(params)
        r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
        if not r.ok:
            return [], r.degraded_reason or f"http {r.status}"
        results = (r.json() or {}).get("results", [])
        if results:
            break
    out = []
    for t in results[:limit]:
        out.append({
            "id": (t.get("id") or "").rsplit("/", 1)[-1],
            "name": t.get("display_name"),
            "description": t.get("description"),
            "keywords": (t.get("keywords") or [])[:12],
            "works_count": t.get("works_count"),
            "cited_by_count": t.get("cited_by_count"),
            "subfield": (t.get("subfield") or {}).get("display_name"),
            "field": (t.get("field") or {}).get("display_name"),
            "domain": (t.get("domain") or {}).get("display_name"),
        })
    return out, None


# --------------------------------------------------------------------------
# Gap metric assembly
# --------------------------------------------------------------------------

MAX_PROBE_QUERIES = 3


def compute_gap_metrics(cache, gap: dict, year_from: int, year_to: int,
                        base_series, corpus_by_id: dict | None = None,
                        fresh: bool = False) -> dict:
    """All deterministic metrics for one mined gap (see gaps.json schema)."""
    queries = [q for q in (gap.get("queries") or []) if q][:MAX_PROBE_QUERIES]
    profiles = [query_profile(cache, q, year_from, year_to, base_series, fresh=fresh)
                for q in queries]

    def mean_of(key):
        vals = [p[key] for p in profiles if p.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    bridge = None
    br = gap.get("bridge") or {}
    if br.get("a") and br.get("b"):
        window = f"publication_year:{year_from}-{year_to}"
        n_total, _ = openalex_count(cache, None, extra_filter=window, fresh=fresh)

        def side_count(term):
            # Exact phrase first; a compound side that phrase-matches nothing
            # falls back to unquoted AND-token search. Returns the count and
            # the form that produced it, so the intersection query matches.
            n, _ = openalex_count(cache, f'"{term}"', extra_filter=window, fresh=fresh)
            if n:
                return n, f'"{term}"'
            n, _ = openalex_count(cache, term, extra_filter=window, fresh=fresh)
            return n, term

        n_a, form_a = side_count(br["a"])
        n_b, form_b = side_count(br["b"])
        n_ab, _ = openalex_count(cache, f"({form_a}) AND ({form_b})",
                                 extra_filter=window, fresh=fresh)
        if None not in (n_a, n_b, n_ab):
            bridge = overlap_stats(n_a, n_b, n_ab, n_total or 0)

    diversity = None
    if queries:
        topics, _ = openalex_topic_shares(
            cache, queries[0], extra_filter=f"publication_year:{year_from}-{year_to}",
            fresh=fresh)
        if topics:
            diversity = {"rao_stirling": rao_stirling(topics),
                         "top_topics": [{"id": t["id"], "name": t["name"],
                                         "share": t["share"]} for t in topics[:8]]}

    supporting = gap.get("supporting") or []
    sup_years, sup_cites = [], []
    for s in supporting:
        p = (corpus_by_id or {}).get(s.get("id")) or {}
        if p.get("year"):
            sup_years.append(p["year"])
        if p.get("cited_by_count") is not None:
            sup_cites.append(p["cited_by_count"])
    recent_support = sum(1 for y in sup_years if y >= year_to - 4)
    corroboration = {
        "n_supporting": len({s.get("id") for s in supporting if s.get("id")}),
        "years_span": (max(sup_years) - min(sup_years)) if sup_years else None,
        "recent_share": round(recent_support / len(sup_years), 3) if sup_years else None,
        "mean_cited_by": round(sum(sup_cites) / len(sup_cites), 1) if sup_cites else None,
    }

    return {
        "gap_id": gap.get("gap_id"),
        "type": gap.get("type"),
        "statement": gap.get("statement"),
        "window": [year_from, year_to],
        "probe_profiles": profiles,
        "momentum": {
            "cagr": mean_of("cagr"),
            "log_slope": mean_of("log_slope"),
            "recency_share_3y": mean_of("recency_share_3y"),
            "burst_weight": max((p.get("burst", {}).get("burst_weight", 0) or 0)
                                for p in profiles) if profiles else None,
            "bursting_now": any(p.get("burst", {}).get("bursting_now") for p in profiles),
        },
        "crowding": {
            "total_works": (round(sum(p["total_works"] for p in profiles) / len(profiles))
                            if profiles else None),
            "venue_hhi": mean_of("venue_hhi"),
        },
        "accessibility": {"oa_share": mean_of("oa_share")},
        "review_deficit": {"recent_primary_per_review": mean_of("recent_primary_per_review")},
        "bridge": bridge,
        "diversity": diversity,
        "corroboration": corroboration,
    }


# --------------------------------------------------------------------------
# Scoring — cross-gap normalization + composite
# --------------------------------------------------------------------------

# Default weights. Quantitative axes (0.50) come from the bibliometric
# signals; qualitative axes (0.50) from the judge-panel rubric (CHNRI-derived:
# novelty, importance, answerability, actionability). Override with a JSON
# file via score-gaps --weights.
DEFAULT_WEIGHTS = {
    "momentum": 0.10,
    "headroom": 0.08,
    "corroboration": 0.15,
    "bridge": 0.07,
    "review_deficit": 0.05,
    "accessibility": 0.05,
    "novelty": 0.15,
    "importance": 0.15,
    "answerability": 0.12,
    "actionability": 0.08,
}

SURVIVAL_MULTIPLIER = {"survived": 1.0, "contested": 0.6, "refuted": 0.0}


def quantitative_scores(metrics_list: list[dict]) -> dict:
    """Cross-gap min-max normalization of raw metrics → 0-1 sub-scores.

    Returns {gap_id: {axis: score01|None}}. Normalization spans the gap set:
    scores mean "relative to the other candidate gaps in this run".
    """
    def col(fn):
        return [fn(m) for m in metrics_list]

    cagr_n = minmax(col(lambda m: m["momentum"]["cagr"]))
    burst_n = minmax(col(lambda m: m["momentum"]["burst_weight"]))
    rec_n = minmax(col(lambda m: m["momentum"]["recency_share_3y"]))
    crowd_n = minmax(col(lambda m: math.log1p(m["crowding"]["total_works"])
                         if m["crowding"]["total_works"] is not None else None))
    hhi_n = minmax(col(lambda m: m["crowding"]["venue_hhi"]))
    bridge_n = minmax(col(lambda m: (m.get("bridge") or {}).get("bridge_opportunity")))
    rev_n = minmax(col(lambda m: math.log1p(m["review_deficit"]["recent_primary_per_review"])
                       if m["review_deficit"]["recent_primary_per_review"] is not None else None))

    sup_raw = []
    for m in metrics_list:
        c = m["corroboration"]
        if not c["n_supporting"]:
            sup_raw.append(0.0)
        else:
            recent = c["recent_share"] if c["recent_share"] is not None else 0.5
            sup_raw.append(math.sqrt(c["n_supporting"]) * (0.5 + 0.5 * recent))
    sup_n = minmax(sup_raw)

    out = {}
    for i, m in enumerate(metrics_list):
        mom_parts = [(cagr_n[i], 0.4), (burst_n[i], 0.35), (rec_n[i], 0.25)]
        mom_obs = [(v, w) for v, w in mom_parts if v is not None]
        momentum = (round(sum(v * w for v, w in mom_obs) / sum(w for _, w in mom_obs), 4)
                    if mom_obs else None)
        headroom = round(1 - crowd_n[i], 4) if crowd_n[i] is not None else None
        oa = m["accessibility"]["oa_share"]
        openness = 1 - hhi_n[i] if hhi_n[i] is not None else None
        if oa is not None and openness is not None:
            access = round(0.6 * oa + 0.4 * openness, 4)
        else:
            access = oa if oa is not None else openness
        out[m["gap_id"]] = {
            "momentum": momentum,
            "headroom": headroom,
            "corroboration": sup_n[i],
            "bridge": bridge_n[i],
            "review_deficit": rev_n[i],
            "accessibility": access,
        }
    return out


def rubric_to_scores(rubric_entry: dict) -> dict:
    """Panel scores on 1-5 anchors → 0-1 sub-scores.

    A list value is a judge panel — the median is taken here, in code, so no
    agent ever averages its own panel.
    """
    out = {}
    for axis in ("novelty", "importance", "answerability", "actionability"):
        v = rubric_entry.get(axis)
        if isinstance(v, (list, tuple)):
            vals = sorted(float(x) for x in v if x is not None)
            if not vals:
                out[axis] = None
                continue
            mid = len(vals) // 2
            v = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        out[axis] = round((float(v) - 1) / 4, 4) if v is not None else None
    return out


def panel_agreement(rubric_entry: dict) -> float | None:
    """CHNRI-AEA-inspired agreement across a judge panel, in [0,1].

    For each axis scored by ≥2 judges, disagreement is the score spread over
    the 1-5 range; agreement = 1 − mean spread. None without panel lists.
    A low value flags a rank built on judges who did not agree."""
    spreads = []
    for axis in ("novelty", "importance", "answerability", "actionability"):
        v = rubric_entry.get(axis)
        if isinstance(v, (list, tuple)):
            vals = [float(x) for x in v if x is not None]
            if len(vals) >= 2:
                spreads.append((max(vals) - min(vals)) / 4)
    if not spreads:
        return None
    return round(1 - sum(spreads) / len(spreads), 3)


def composite_scores(metrics_list: list[dict], rubric: dict, survival: dict,
                     weights: dict | None = None) -> dict:
    """Full scoring pass: sub-scores, composite, survival, rank sensitivity."""
    weights = dict(weights or DEFAULT_WEIGHTS)
    quant = quantitative_scores(metrics_list)
    per_gap: dict[str, dict] = {}
    for m in metrics_list:
        gid = m["gap_id"]
        scores = dict(quant[gid])
        scores.update(rubric_to_scores(rubric.get(gid) or {}))
        per_gap[gid] = scores

    survivors = {g: s for g, s in per_gap.items()
                 if SURVIVAL_MULTIPLIER.get((survival.get(g) or {}).get("verdict",
                                            "survived"), 1.0) > 0}
    sens = rank_sensitivity(survivors, weights) if survivors else {}

    results = {}
    for gid, scores in per_gap.items():
        verdict = (survival.get(gid) or {}).get("verdict", "survived")
        mult = SURVIVAL_MULTIPLIER.get(verdict, 1.0)
        raw = weighted_geometric(scores, weights)
        results[gid] = {
            "sub_scores": scores,
            "survival": verdict,
            "gap_score": round(100 * (raw or 0) * mult, 1),
            "excluded": mult == 0,
            "panel_agreement": panel_agreement(rubric.get(gid) or {}),
            **(sens.get(gid) or {}),
        }
    return {"weights": weights, "gaps": results}


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
