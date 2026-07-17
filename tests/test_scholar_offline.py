"""Offline tests for normalizers, dedup, independence counting, and the
audit-report gate — canned data, no network."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import scholar_apis as apis  # noqa: E402
import scholar  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def test_openalex_abstract_reconstruction():
    inv = {"hello": [0], "world": [1]}
    assert apis._openalex_abstract(inv) == "hello world"
    assert apis._openalex_abstract(None) is None


def test_openalex_normalize_retraction_flag():
    work = {"display_name": "X", "is_retracted": True, "ids": {"doi": "https://doi.org/10.1/a"},
            "publication_year": 2020, "authorships": [], "referenced_works": []}
    p = apis._openalex_normalize(work, "q")
    assert p["retraction"]["status"] == "retracted"
    assert p["ids"]["doi"] == "10.1/a"


def test_crossref_normalize():
    item = {"DOI": "10.1/b", "title": ["T"], "author": [{"given": "A", "family": "B"}],
            "published": {"date-parts": [[2019, 1]]}, "container-title": ["V"],
            "is-referenced-by-count": 7, "type": "journal-article",
            "abstract": "<jats:p>Hi there</jats:p>"}
    p = apis._crossref_normalize(item, "q")
    assert p["year"] == 2019 and p["authors"] == ["A B"]
    assert p["abstract"] == "Hi there"
    assert p["cited_by_count"] == 7


def test_dedup_merges_across_sources():
    a = apis._paper("openalex", "q", ids={"doi": "10.1/x"}, title="Same Paper", year=2020,
                    abstract="long abstract here")
    b = apis._paper("crossref", "q", ids={"doi": "10.1/X"}, title="Same paper!", year=2020,
                    cited_by_count=5)
    c = apis._paper("dblp", "q", ids={}, title="Same Paper", year=2021)  # title+year±1 merge
    merged = scholar.dedup_papers([a, b, c])
    assert len(merged) == 1
    m = merged[0]
    assert m["cluster_size"] == 3
    assert set(m["provenance"]["source_apis"]) == {"openalex", "crossref", "dblp"}
    assert m["abstract"] == "long abstract here"


def test_independent_count_ancestry():
    assert scholar._independent_count(["openalex", "crossref"]) == 1  # ancestry collapse
    assert scholar._independent_count(["crossref", "arxiv"]) == 2
    assert scholar._independent_count(["openalex", "crossref", "opencitations"]) == 2
    assert scholar._independent_count([]) == 0


def test_retraction_rank_merge():
    a = apis._paper("openalex", "q", ids={"doi": "10.1/r"}, title="R", year=2020)
    b = apis._paper("pubmed", "q", ids={"doi": "10.1/r"}, title="R", year=2020,
                    retraction={"status": "retracted", "source": "pubmed", "checked_at": "t"})
    m = scholar.dedup_papers([a, b])
    assert m[0]["retraction"]["status"] == "retracted"


def _run_audit(report_text, corpus):
    with tempfile.TemporaryDirectory() as td:
        rp = os.path.join(td, "report.md")
        cp = os.path.join(td, "corpus.json")
        op = os.path.join(td, "gate.json")
        open(rp, "w").write(report_text)
        json.dump({"papers": corpus}, open(cp, "w"))
        env = dict(os.environ, IR_SKIP_RETRACTIONWATCH="1",
                   IR_CACHE_DIR=os.path.join(td, "cache"))
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scholar.py"),
                            "audit-report", rp, "--corpus", cp, "--out", op],
                           capture_output=True, text=True, env=env, timeout=120)
        return r.returncode, json.load(open(op))


GOOD = {"id": "doi:10.1/g", "ids": {"doi": "10.1/g"}, "title": "G", "year": 2020,
        "verification": {"status": "verified"}, "retraction": {"status": "none"}}


def test_audit_report_pass():
    code, rep = _run_audit('Fine [@doi:10.1/g]{anchor=quote:"ok"}.', [GOOD])
    assert code == 0 and rep["gate"] == "pass"


def test_audit_report_fails_on_uncited():
    code, rep = _run_audit("Bad [@doi:10.9/none]{anchor=none}.", [GOOD])
    assert code == 1 and rep["summary"]["not_in_corpus"] == 1


def test_audit_report_fails_on_unverified():
    unv = dict(GOOD, id="doi:10.1/u", ids={"doi": "10.1/u"},
               verification={"status": "unresolvable"})
    code, rep = _run_audit("Bad [@doi:10.1/u]{anchor=none}.", [unv])
    assert code == 1 and rep["summary"]["unverified"] == 1


def test_audit_report_flags_deictic_and_year():
    code, rep = _run_audit("Recently shown (2011) [@doi:10.1/g]{anchor=none}.", [GOOD])
    assert rep["warnings"]["deictic_phrases"]
    assert rep["warnings"]["year_mismatches"]


def test_export_bibtex_and_ris(tmp_path=None):
    with tempfile.TemporaryDirectory() as td:
        cp = os.path.join(td, "corpus.json")
        json.dump({"papers": [dict(GOOD, authors=["Ada Lovelace"], venue="J",
                                   type="journal-article")]}, open(cp, "w"))
        for fmt, needle in (("bibtex", "@article{"), ("ris", "TY  - JOUR"),
                            ("csv", "doi"), ("csl-json", "article-journal")):
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "scholar.py"),
                                "export", "--in", cp, "--format", fmt],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0 and needle in r.stdout, (fmt, r.stdout[:200])


# ---- v2: datasets, style, originality, readiness, prisma ----

def test_dataset_normalize_license_and_access():
    hf = apis.adapter_hf_datasets.__wrapped__ if hasattr(apis.adapter_hf_datasets, "__wrapped__") else None
    # _dataset + _license_block directly (no network)
    rec = apis._dataset("hf", "q", native_id="x/y", title="X",
                        license=apis._license_block(spdx="cc-by-nc-4.0", name="cc-by-nc-4.0"),
                        modalities=["image"])
    assert rec["license"]["noncommercial"] is True
    assert rec["license"]["is_open"] is False
    rec2 = apis._dataset("hf", "q", native_id="a", title="A",
                         license=apis._license_block(spdx="mit"))
    assert rec2["license"]["is_open"] is True and rec2["license"]["noncommercial"] is False
    rec3 = apis._dataset("dc", "q", native_id="b", title="B")  # no license
    assert rec3["license"]["is_open"] is None  # unknown, not fabricated


def test_dataset_mirror_collapse():
    a = apis._dataset("hf", "q", native_id="cv", title="Common Voice", creators=["Mozilla"], doi="10.1/cv")
    b = apis._dataset("zenodo", "q", native_id="99", title="Common Voice", creators=["Mozilla"], doi="10.1/cv")
    out = apis.collapse_dataset_mirrors([a, b])
    assert len(out) == 1 and len(out[0]["mirrors"]) == 1


def test_dataset_not_paper_clustered():
    rec = apis._dataset("hf", "q", native_id="x", title="X")
    assert scholar._cluster_key(rec) is None  # dataset records never enter paper dedup


def _fitness(rec, spec):
    return scholar._dataset_fitness_one(rec, spec)


def test_fitness_license_veto():
    rec = apis._dataset("hf", "q", native_id="x", title="X", modalities=["text"],
                        task_categories=["text-classification"],
                        license=apis._license_block(spdx="cc-by-nc-4.0", name="cc-by-nc-4.0"),
                        access={"right": "open"}, size={"num_instances": 50000})
    v = _fitness(rec, {"task": "text-classification", "modality": "text",
                       "usage": {"commercial": True}})
    assert v["verdict"] == "unfit" and "license_usage_rights" in v["gates_triggered"]


def test_fitness_unknown_license_conditional():
    rec = apis._dataset("dc", "q", native_id="x", title="X", modalities=["text"])
    v = _fitness(rec, {"task": "text", "modality": "text", "usage": {"commercial": True}})
    assert v["verdict"] in ("conditional",) and v["review_flags"]


def test_fitness_pii_forces_ethics_gate():
    # A face dataset with no ethics statement -> ethics gate veto regardless of spec.
    rec = apis._dataset("hf", "q", native_id="faces", title="Celebrity faces",
                        modalities=["face"], license=apis._license_block(spdx="mit"),
                        access={"right": "open"})
    v = _fitness(rec, {"task": "classification", "modality": "face",
                       "ethics_constraints": {"human_subjects": False}})
    assert v["verdict"] == "unfit" and "ethics_consent_pii" in v["gates_triggered"]


def _run(*args, **kw):
    env = dict(os.environ, IR_SKIP_RETRACTIONWATCH="1")
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "scholar.py"), *args],
                          capture_output=True, text=True, env=env, timeout=120, **kw)


def test_emit_prisma_counts_in_dot():
    with tempfile.TemporaryDirectory() as td:
        cp = os.path.join(td, "c.json")
        json.dump({"identified": {"a": 100, "b": 40}, "duplicates_removed": 30,
                   "included": 60}, open(cp, "w"))
        r = _run("emit-prisma", "--counts", cp, "--format", "dot")
        assert r.returncode == 0 and "n=140" in r.stdout and "n=60" in r.stdout


def test_originality_flags_verbatim_and_passes_clean():
    with tempfile.TemporaryDirectory() as td:
        srcdir = os.path.join(td, "src")
        os.makedirs(srcdir)
        open(os.path.join(srcdir, "s.txt"), "w").write(
            "the transformer architecture uses self attention to process sequences in parallel")
        bad = os.path.join(td, "bad.md")
        open(bad, "w").write("Intro. the transformer architecture uses self attention to process sequences in parallel here.")
        ok = os.path.join(td, "ok.md")
        open(ok, "w").write("We propose an entirely different mechanism for modeling ordered data.")
        rb = _run("originality", "--draft", bad, "--against", srcdir, "--max-verbatim-words", "6",
                  "--out", os.path.join(td, "b.json"))
        ro = _run("originality", "--draft", ok, "--against", srcdir, "--max-verbatim-words", "6",
                  "--out", os.path.join(td, "o.json"))
        assert rb.returncode == 1 and ro.returncode == 0


def test_readiness_pass_and_fail():
    with tempfile.TemporaryDirectory() as td:
        bad = os.path.join(td, "bad.md")
        open(bad, "w").write("# Abstract\nHi.\n## Results\nWe found p<0.05.\n## References\n[1]")
        rb = _run("readiness", "--manuscript", bad, "--checklist-set", "frontmatter",
                  "--out", os.path.join(td, "rb.json"))
        assert rb.returncode == 1
        rep = json.load(open(os.path.join(td, "rb.json")))
        assert rep["summary"]["orphan_p_values"] >= 1


def test_readiness_proposal_blocks_results():
    with tempfile.TemporaryDirectory() as td:
        m = os.path.join(td, "m.md")
        open(m, "w").write("# Abstract\nPlan.\n## Results\nWe achieved 95% accuracy.\n")
        r = _run("readiness", "--manuscript", m, "--checklist-set", "frontmatter",
                 "--run-mode", "proposal", "--out", os.path.join(td, "r.json"))
        assert r.returncode == 1
        rep = json.load(open(os.path.join(td, "r.json")))
        assert rep["summary"]["proposal_violations"] >= 1


def test_style_profile_no_long_strings():
    # A profile-shaped object with a leaked sentence must be caught.
    leaked = {"terminology": {"shared_domain_terms": ["this is a long leaked sentence from source"]}}
    assert scholar._profile_has_long_strings(leaked)
    clean = {"terminology": {"shared_domain_terms": ["neural", "attention"]},
             "sentences": {"mean_len_words": 20}}
    assert scholar._profile_has_long_strings(clean) is None
