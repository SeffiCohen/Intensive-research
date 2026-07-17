"""Live API smoke tests. Skipped unless IR_LIVE_TESTS=1 (network + rate limits).

Run once per release: IR_LIVE_TESTS=1 python3 -m pytest tests/test_scholar_live.py -v
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("IR_LIVE_TESTS") != "1",
                                reason="live tests need IR_LIVE_TESTS=1")

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def _scholar(*args, timeout=300):
    env = dict(os.environ, IR_SKIP_RETRACTIONWATCH="1")
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "scholar.py"), *args],
                          capture_output=True, text=True, env=env, timeout=timeout)


def test_search_multi_source():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "s.json")
        r = _scholar("search", "transformer attention", "--sources",
                     "openalex,crossref,dblp", "--limit", "3", "--out", out)
        assert r.returncode == 0, r.stderr
        d = json.load(open(out))
        assert d["dedup"]["unique"] >= 3
        assert all(v["status"] in ("ok", "degraded") for v in d["per_source"].values())
        assert sum(1 for v in d["per_source"].values() if v["status"] == "ok") >= 2


def test_verify_real_doi():
    r = _scholar("verify", "--doi", "10.48550/arXiv.1706.03762",
                 "--title", "Attention Is All You Need")
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(r.stdout)
    assert d["status"] == "verified"


def test_verify_fake_title_unresolvable():
    r = _scholar("verify", "--title",
                 "Quantum Blockchain Neural Transformers for Cold Fusion 2029")
    d = json.loads(r.stdout)
    assert d["status"] in ("unresolvable", "degraded")


def test_verify_retracted_wakefield():
    r = _scholar("verify", "--doi", "10.1016/S0140-6736(97)11096-0")
    d = json.loads(r.stdout)
    assert d["retraction"]["status"] == "retracted"


def test_fulltext_arxiv():
    r = _scholar("fulltext", "--doi", "10.48550/arXiv.1706.03762")
    d = json.loads(r.stdout)
    assert d["mode"] == "pdf-download"


def test_doctor_runs():
    r = _scholar("doctor", "--json")
    d = json.loads(r.stdout)
    assert any(c["check"] == "network:openalex" for c in d["checks"])
