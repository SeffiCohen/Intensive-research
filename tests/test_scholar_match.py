"""Offline unit tests for scholar_match.py (no network)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from scholar_match import (  # noqa: E402
    exact_normalized_title,
    generic_title,
    normalize_arxiv,
    normalize_doi,
    normalize_title,
    notice_title,
    similarity,
    title_years_match,
)


def test_normalize_title_basic():
    assert normalize_title("Attention Is All You Need!") == "attention is all you need"
    assert normalize_title("  A:  B--C  ") == "a b c"


def test_dotted_acronym_matches():
    assert exact_normalized_title("R.A.G. for QA", "RAG for QA")


def test_spaced_initials_not_collapsed():
    assert exact_normalized_title("D.H. Lawrence", "D. H. Lawrence")


def test_similarity_threshold_behavior():
    assert similarity("Attention is all you need", "Attention Is All You Need!") == 1.0
    assert similarity("Attention is all you need", "Graph neural networks survey") < 0.70


def test_generic_title_exact_membership_only():
    assert generic_title("Editorial")
    assert generic_title("  case report ")
    assert not generic_title("Case Report of a Rare Tumor")


def test_notice_title_veto():
    assert notice_title("Retraction: Ileal-lymphoid-nodular hyperplasia")
    assert notice_title("Erratum to: Deep learning")
    assert notice_title("Expression of Concern: Something")
    assert not notice_title("Deep learning for retraction detection")


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1000/ABC.") == "10.1000/abc"
    assert normalize_doi("doi:10.1000/xyz") == "10.1000/xyz"
    assert normalize_doi(None) is None


def test_normalize_arxiv():
    assert normalize_arxiv("arXiv:1706.03762v5") == "1706.03762"
    assert normalize_arxiv("https://arxiv.org/abs/1706.03762") == "1706.03762"
    assert normalize_arxiv("https://arxiv.org/pdf/1706.03762.pdf") == "1706.03762"


def test_title_years_match():
    assert title_years_match(2020, 2021)
    assert not title_years_match(2020, 2022)
    assert title_years_match(None, 2022)
