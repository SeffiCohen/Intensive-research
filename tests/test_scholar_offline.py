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
