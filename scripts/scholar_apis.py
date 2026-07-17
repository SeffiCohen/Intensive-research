#!/usr/bin/env python3
"""API adapters for scholar.py — every adapter normalizes to the canonical
paper schema and reports degradation instead of raising.

Canonical paper dict:
{
  "id": "<doi:...|arxiv:...|pmid:...|openalex:...>",
  "ids": {"doi","arxiv","openalex","pmid","pmcid","dblp","s2","openreview"},
  "title", "authors": [...], "year", "venue", "type",
  "abstract", "abstract_source",
  "cited_by_count", "is_oa", "oa_pdf_url", "urls": {"landing","pdf"},
  "retraction": {"status": "none|retracted|correction|eoc|withdrawal|unknown",
                  "source", "checked_at"},
  "provenance": {"source_apis": [...], "query", "retrieved_at"},
  "verification": {"status": "unverified"}
}
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import scholar_http as http
from scholar_match import normalize_arxiv, normalize_doi

# Which indexes ingest which upstream sources. Agreement between an index and
# one of its ancestors is NOT independent confirmation.
INDEX_ANCESTRY = {
    "openalex": {"crossref", "arxiv", "pubmed", "europepmc"},
    "europepmc": {"pubmed"},
    "s2": {"crossref", "arxiv", "pubmed"},
}

SEARCH_SOURCES = ("openalex", "crossref", "arxiv", "europepmc", "pubmed", "dblp", "openreview", "s2")
DEFAULT_SEARCH_SOURCES = ("openalex", "crossref", "arxiv", "europepmc", "dblp")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _paper(source_api: str, query: str, **fields) -> dict:
    ids = fields.pop("ids", {})
    for k in ("doi", "arxiv", "openalex", "pmid", "pmcid", "dblp", "s2", "openreview"):
        ids.setdefault(k, None)
    ids["doi"] = normalize_doi(ids["doi"])
    ids["arxiv"] = normalize_arxiv(ids["arxiv"])
    pid = None
    for k in ("doi", "arxiv", "pmid", "openalex", "dblp", "openreview", "s2"):
        if ids.get(k):
            pid = f"{k}:{ids[k]}"
            break
    p = {
        "id": pid,
        "ids": ids,
        "title": (fields.pop("title", "") or "").strip(),
        "authors": fields.pop("authors", []),
        "year": fields.pop("year", None),
        "venue": fields.pop("venue", None),
        "type": fields.pop("type", None),
        "abstract": fields.pop("abstract", None),
        "abstract_source": fields.pop("abstract_source", None),
        "cited_by_count": fields.pop("cited_by_count", None),
        "is_oa": fields.pop("is_oa", None),
        "oa_pdf_url": fields.pop("oa_pdf_url", None),
        "urls": fields.pop("urls", {}),
        "retraction": fields.pop("retraction", {"status": "unknown", "source": None, "checked_at": None}),
        "provenance": {"source_apis": [source_api], "query": query, "retrieved_at": now_iso()},
        "verification": {"status": "unverified"},
    }
    if p["abstract"] and not p["abstract_source"]:
        p["abstract_source"] = source_api
    p.update(fields)
    return p


def _strip_jats(text: str | None) -> str | None:
    if not text:
        return None
    out = re.sub(r"<[^>]+>", " ", text)
    out = " ".join(out.split())
    return out or None


# --------------------------------------------------------------------------
# OpenAlex (primary)
# --------------------------------------------------------------------------

def _openalex_abstract(inv) -> str | None:
    if not isinstance(inv, dict) or not inv:
        return None
    slots: dict[int, str] = {}
    for word, positions in inv.items():
        for pos in positions:
            slots[pos] = word
    return " ".join(slots[i] for i in sorted(slots)) or None


def _openalex_normalize(work: dict, query: str) -> dict:
    ids = work.get("ids") or {}
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    best_oa = work.get("best_oa_location") or {}
    oa = work.get("open_access") or {}
    is_retracted = bool(work.get("is_retracted"))
    return _paper(
        "openalex", query,
        ids={
            "doi": ids.get("doi"),
            "openalex": (ids.get("openalex") or "").rsplit("/", 1)[-1] or None,
            "pmid": (ids.get("pmid") or "").rsplit("/", 1)[-1] or None,
            "pmcid": (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None,
            "arxiv": ids.get("doi") if ids.get("doi", "").startswith("https://doi.org/10.48550/arxiv.") else None,
        },
        title=work.get("display_name") or work.get("title") or "",
        authors=[a.get("author", {}).get("display_name") for a in work.get("authorships", []) if a.get("author")],
        year=work.get("publication_year"),
        venue=src.get("display_name"),
        type=work.get("type"),
        abstract=_openalex_abstract(work.get("abstract_inverted_index")),
        cited_by_count=work.get("cited_by_count"),
        is_oa=oa.get("is_oa"),
        oa_pdf_url=best_oa.get("pdf_url"),
        urls={"landing": ids.get("doi") or work.get("id"), "pdf": best_oa.get("pdf_url")},
        retraction={"status": "retracted", "source": "openalex", "checked_at": now_iso()} if is_retracted
        else {"status": "unknown", "source": None, "checked_at": None},
        referenced_works=[w.rsplit("/", 1)[-1] for w in work.get("referenced_works", [])[:200]],
    )


def openalex_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    params = {"search": query, "per-page": min(limit, 200)}
    filters = []
    if year_from and year_to:
        filters.append(f"publication_year:{year_from}-{year_to}")
    elif year_from:
        filters.append(f"publication_year:>{year_from - 1}")
    elif year_to:
        filters.append(f"publication_year:<{year_to + 1}")
    if filters:
        params["filter"] = ",".join(filters)
    if http.mailto():
        params["mailto"] = http.mailto()
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    data = r.json() or {}
    return [_openalex_normalize(w, query) for w in data.get("results", [])[:limit]], None


def openalex_lookup(cache, *, doi=None, openalex_id=None, fresh=False):
    if doi:
        url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(normalize_doi(doi) or '', safe='')}"
    elif openalex_id:
        url = f"https://api.openalex.org/works/{urllib.parse.quote(openalex_id, safe='')}"
    else:
        return None, "no id"
    if http.mailto():
        url += "?" + urllib.parse.urlencode({"mailto": http.mailto()})
    r = http.fetch(cache, url, ttl_class="id_lookup", fresh=fresh)
    if r.status == 404:
        return None, None
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    work = r.json()
    return (_openalex_normalize(work, f"lookup:{doi or openalex_id}") if work else None), None


def openalex_batch_doi(cache, dois, fresh=False):
    """Batch DOI lookup, 50 per request. Returns {doi: paper|None}, degraded."""
    out: dict = {}
    degraded = None
    clean = [d for d in (normalize_doi(x) for x in dois) if d]
    for i in range(0, len(clean), 50):
        chunk = clean[i : i + 50]
        flt = "doi:" + "|".join(chunk)
        params = {"filter": flt, "per-page": 50}
        if http.mailto():
            params["mailto"] = http.mailto()
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        r = http.fetch(cache, url, ttl_class="id_lookup", fresh=fresh)
        if not r.ok:
            degraded = r.degraded_reason or f"http {r.status}"
            continue
        found = {}
        for w in (r.json() or {}).get("results", []):
            p = _openalex_normalize(w, "batch-doi")
            if p["ids"]["doi"]:
                found[p["ids"]["doi"]] = p
        for d in chunk:
            out[d] = found.get(d)
    return out, degraded


def openalex_cites(cache, openalex_id, limit=50, fresh=False):
    params = {"filter": f"cites:{openalex_id}", "per-page": min(limit, 200)}
    if http.mailto():
        params["mailto"] = http.mailto()
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    return [_openalex_normalize(w, f"cites:{openalex_id}") for w in (r.json() or {}).get("results", [])[:limit]], None


def openalex_refs(cache, openalex_id, fresh=False):
    work, err = openalex_lookup(cache, openalex_id=openalex_id, fresh=fresh)
    if not work:
        return [], err or "not found"
    ref_ids = work.get("referenced_works") or []
    out = []
    for i in range(0, len(ref_ids), 50):
        chunk = ref_ids[i : i + 50]
        params = {"filter": "openalex_id:" + "|".join(chunk), "per-page": 50}
        if http.mailto():
            params["mailto"] = http.mailto()
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        r = http.fetch(cache, url, ttl_class="metadata", fresh=fresh)
        if r.ok:
            out.extend(_openalex_normalize(w, f"refs:{openalex_id}") for w in (r.json() or {}).get("results", []))
    return out, None


# --------------------------------------------------------------------------
# Crossref
# --------------------------------------------------------------------------

_CROSSREF_RETRACTION_TYPES = {
    "retraction": "retracted",
    "retracted": "retracted",
    "removal": "withdrawal",
    "withdrawal": "withdrawal",
    "correction": "correction",
    "erratum": "correction",
    "corrigendum": "correction",
    "expression_of_concern": "eoc",
    "expression-of-concern": "eoc",
}


def _crossref_normalize(item: dict, query: str) -> dict:
    date_parts = (item.get("published") or item.get("issued") or {}).get("date-parts") or [[None]]
    year = date_parts[0][0] if date_parts and date_parts[0] else None
    authors = []
    for a in item.get("author", []) or []:
        name = " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name")
        if name:
            authors.append(name)
    return _paper(
        "crossref", query,
        ids={"doi": item.get("DOI")},
        title=(item.get("title") or [""])[0],
        authors=authors,
        year=year,
        venue=(item.get("container-title") or [None])[0],
        type=item.get("type"),
        abstract=_strip_jats(item.get("abstract")),
        cited_by_count=item.get("is-referenced-by-count"),
        urls={"landing": item.get("URL")},
    )


def crossref_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    params = {"query.bibliographic": query, "rows": min(limit, 100)}
    filters = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if year_to:
        filters.append(f"until-pub-date:{year_to}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    if http.mailto():
        params["mailto"] = http.mailto()
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    items = ((r.json() or {}).get("message") or {}).get("items", [])
    return [_crossref_normalize(i, query) for i in items[:limit]], None


def crossref_lookup(cache, doi, fresh=False):
    d = normalize_doi(doi)
    url = f"https://api.crossref.org/works/{urllib.parse.quote(d or '', safe='')}"
    r = http.fetch(cache, url, ttl_class="id_lookup", fresh=fresh)
    if r.status == 404:
        return None, None
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    msg = (r.json() or {}).get("message")
    return (_crossref_normalize(msg, f"lookup:{d}") if msg else None), None


def crossref_updates(cache, doi, fresh=False):
    """Find update notices (retractions/corrections/EoC) targeting a DOI.
    Returns (status|None, notice_doi|None, degraded_reason|None)."""
    d = normalize_doi(doi)
    params = {"filter": f"updates:{d}", "rows": 10}
    if http.mailto():
        params["mailto"] = http.mailto()
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    # 48h TTL class: a stale cache must not mask a fresh retraction.
    r = http.fetch(cache, url, ttl_class="retraction", fresh=fresh)
    if not r.ok:
        return None, None, r.degraded_reason or f"http {r.status}"
    items = ((r.json() or {}).get("message") or {}).get("items", [])
    worst = None
    notice = None
    rank = {"retracted": 3, "withdrawal": 3, "eoc": 2, "correction": 1}
    for item in items:
        for upd in item.get("update-to", []) or []:
            if normalize_doi(upd.get("DOI")) != d:
                continue
            status = _CROSSREF_RETRACTION_TYPES.get((upd.get("type") or "").lower())
            if status and (worst is None or rank[status] > rank.get(worst, 0)):
                worst = status
                notice = normalize_doi(item.get("DOI"))
    return worst, notice, None


# --------------------------------------------------------------------------
# arXiv
# --------------------------------------------------------------------------

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def arxiv_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": min(limit * 2 if (year_from or year_to) else limit, 100),
    }
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", accept="application/atom+xml", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    papers = []
    try:
        root = ET.fromstring(r.body.decode("utf-8", "replace"))
    except ET.ParseError:
        return [], "atom parse error"
    for entry in root.findall(f"{_ATOM}entry"):
        raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        published = entry.findtext(f"{_ATOM}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        if year_from and year and year < year_from:
            continue
        if year_to and year and year > year_to:
            continue
        pdf = None
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf = link.get("href")
        doi = entry.findtext(f"{_ARXIV_NS}doi")
        arxiv_id = normalize_arxiv(raw_id)
        papers.append(_paper(
            "arxiv", query,
            ids={"arxiv": arxiv_id, "doi": doi or (f"10.48550/arxiv.{arxiv_id}" if arxiv_id else None)},
            title=" ".join((entry.findtext(f"{_ATOM}title") or "").split()),
            authors=[a.findtext(f"{_ATOM}name") for a in entry.findall(f"{_ATOM}author")],
            year=year,
            venue="arXiv",
            type="preprint",
            abstract=" ".join((entry.findtext(f"{_ATOM}summary") or "").split()) or None,
            is_oa=True,
            oa_pdf_url=pdf,
            urls={"landing": raw_id, "pdf": pdf},
        ))
        if len(papers) >= limit:
            break
    return papers, None


def arxiv_lookup(cache, arxiv_id, fresh=False):
    aid = normalize_arxiv(arxiv_id)
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"id_list": aid, "max_results": 1})
    r = http.fetch(cache, url, ttl_class="id_lookup", accept="application/atom+xml", fresh=fresh)
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    try:
        root = ET.fromstring(r.body.decode("utf-8", "replace"))
        entries = root.findall(f"{_ATOM}entry")
        # arXiv reports a miss as an entry whose id contains 'api/errors'.
        for entry in entries:
            if "api/errors" in (entry.findtext(f"{_ATOM}id") or ""):
                return None, None
        if not entries:
            return None, None
    except ET.ParseError:
        return None, "atom parse error"
    entry = entries[0]
    raw_id = (entry.findtext(f"{_ATOM}id") or "").strip()
    published = entry.findtext(f"{_ATOM}published") or ""
    year = int(published[:4]) if published[:4].isdigit() else None
    pdf = None
    for link in entry.findall(f"{_ATOM}link"):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf = link.get("href")
    doi = entry.findtext(f"{_ARXIV_NS}doi")
    return _paper(
        "arxiv", f"lookup:{aid}",
        ids={"arxiv": normalize_arxiv(raw_id), "doi": doi or f"10.48550/arxiv.{aid}"},
        title=" ".join((entry.findtext(f"{_ATOM}title") or "").split()),
        authors=[a.findtext(f"{_ATOM}name") for a in entry.findall(f"{_ATOM}author")],
        year=year, venue="arXiv", type="preprint",
        abstract=" ".join((entry.findtext(f"{_ATOM}summary") or "").split()) or None,
        is_oa=True, oa_pdf_url=pdf, urls={"landing": raw_id, "pdf": pdf},
    ), None


# --------------------------------------------------------------------------
# Europe PMC
# --------------------------------------------------------------------------

def _europepmc_normalize(res: dict, query: str) -> dict:
    ft = res.get("fullTextUrlList", {}).get("fullTextUrl", [])
    pdf = next((u.get("url") for u in ft if u.get("documentStyle") == "pdf"), None)
    pubtypes = [pt for pt in (res.get("pubTypeList") or {}).get("pubType", []) if isinstance(pt, str)]
    retracted = any("retracted publication" in pt.lower() for pt in pubtypes)
    return _paper(
        "europepmc", query,
        ids={"doi": res.get("doi"), "pmid": res.get("pmid"), "pmcid": res.get("pmcid")},
        title=res.get("title") or "",
        authors=[a.strip() for a in (res.get("authorString") or "").rstrip(".").split(",") if a.strip()],
        year=int(res["pubYear"]) if str(res.get("pubYear", "")).isdigit() else None,
        venue=(res.get("journalInfo") or {}).get("journal", {}).get("title"),
        type=None,
        abstract=res.get("abstractText") and _strip_jats(res.get("abstractText")),
        cited_by_count=res.get("citedByCount"),
        is_oa=res.get("isOpenAccess") == "Y",
        oa_pdf_url=pdf,
        urls={"landing": f"https://europepmc.org/article/{res.get('source')}/{res.get('id')}", "pdf": pdf},
        retraction={"status": "retracted", "source": "europepmc", "checked_at": now_iso()} if retracted
        else {"status": "unknown", "source": None, "checked_at": None},
        epmc={"source": res.get("source"), "id": res.get("id"), "inEPMC": res.get("inEPMC")},
    )


def europepmc_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    q = query
    if year_from or year_to:
        q = f"({query}) AND (PUB_YEAR:[{year_from or 1800} TO {year_to or 2100}])"
    params = {"query": q, "format": "json", "pageSize": min(limit, 100), "resultType": "core"}
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    results = ((r.json() or {}).get("resultList") or {}).get("result", [])
    return [_europepmc_normalize(x, query) for x in results[:limit]], None


def europepmc_fulltext_xml(cache, source: str, ext_id: str, fresh=False):
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{urllib.parse.quote(source)}/{urllib.parse.quote(ext_id)}/fullTextXML"
    r = http.fetch(cache, url, ttl_class="fulltext", accept="application/xml", fresh=fresh)
    if r.status == 404:
        return None, None
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    return r.body.decode("utf-8", "replace"), None


# --------------------------------------------------------------------------
# PubMed E-utilities
# --------------------------------------------------------------------------

def _eutils_params(extra: dict) -> dict:
    p = dict(extra)
    key = os.environ.get("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    if http.mailto():
        p["email"] = http.mailto()
        p["tool"] = "intensive-research"
    return p


def pubmed_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    params = _eutils_params({"db": "pubmed", "term": query, "retmode": "json", "retmax": min(limit, 100)})
    if year_from or year_to:
        params.update({"datetype": "pdat", "mindate": str(year_from or 1800), "maxdate": str(year_to or 2100)})
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    ids = ((r.json() or {}).get("esearchresult") or {}).get("idlist", [])
    if not ids:
        return [], None
    return pubmed_summaries(cache, ids, query, fresh=fresh)


def pubmed_summaries(cache, pmids, query, fresh=False):
    params = _eutils_params({"db": "pubmed", "id": ",".join(pmids), "retmode": "json"})
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="metadata", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    result = (r.json() or {}).get("result", {})
    papers = []
    for pmid in pmids:
        doc = result.get(pmid)
        if not isinstance(doc, dict):
            continue
        doi = next((aid.get("value") for aid in doc.get("articleids", []) if aid.get("idtype") == "doi"), None)
        pubdate = doc.get("pubdate", "")
        year = int(pubdate[:4]) if pubdate[:4].isdigit() else None
        pubtypes = [t.lower() for t in doc.get("pubtype", [])]
        retracted = "retracted publication" in pubtypes
        papers.append(_paper(
            "pubmed", query,
            ids={"pmid": pmid, "doi": doi},
            title=doc.get("title") or "",
            authors=[a.get("name") for a in doc.get("authors", []) if a.get("name")],
            year=year,
            venue=doc.get("fulljournalname") or doc.get("source"),
            type=None,
            cited_by_count=None,
            urls={"landing": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"},
            retraction={"status": "retracted", "source": "pubmed", "checked_at": now_iso()} if retracted
            else {"status": "unknown", "source": None, "checked_at": None},
        ))
    return papers, None


def pubmed_abstracts(cache, pmids, fresh=False):
    """Fetch abstracts for PMIDs in one efetch call. Returns {pmid: abstract}."""
    params = _eutils_params({"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract", "retmode": "xml"})
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="metadata", accept="application/xml", fresh=fresh)
    if not r.ok:
        return {}, r.degraded_reason or f"http {r.status}"
    out = {}
    try:
        root = ET.fromstring(r.body.decode("utf-8", "replace"))
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext(".//PMID")
            parts = [" ".join(t.itertext()).strip() for t in art.findall(".//Abstract/AbstractText")]
            if pmid and parts:
                out[pmid] = " ".join(" ".join(parts).split())
    except ET.ParseError:
        return {}, "xml parse error"
    return out, None


# --------------------------------------------------------------------------
# DBLP
# --------------------------------------------------------------------------

def dblp_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    params = {"q": query, "format": "json", "h": min(limit * 2 if (year_from or year_to) else limit, 100)}
    url = "https://dblp.org/search/publ/api?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    hits = ((((r.json() or {}).get("result") or {}).get("hits")) or {}).get("hit", [])
    papers = []
    for h in hits:
        info = h.get("info", {})
        year = int(info["year"]) if str(info.get("year", "")).isdigit() else None
        if year_from and year and year < year_from:
            continue
        if year_to and year and year > year_to:
            continue
        raw_authors = ((info.get("authors") or {}).get("author")) or []
        if isinstance(raw_authors, dict):
            raw_authors = [raw_authors]
        authors = [a.get("text") if isinstance(a, dict) else str(a) for a in raw_authors]
        papers.append(_paper(
            "dblp", query,
            ids={"doi": info.get("doi"), "dblp": info.get("key")},
            title=(info.get("title") or "").rstrip("."),
            authors=authors,
            year=year,
            venue=info.get("venue"),
            type=info.get("type"),
            urls={"landing": info.get("ee") or info.get("url")},
        ))
        if len(papers) >= limit:
            break
    return papers, None


# --------------------------------------------------------------------------
# OpenReview
# --------------------------------------------------------------------------

def _or_value(content: dict, key: str):
    v = content.get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def openreview_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    params = {"term": query, "limit": min(limit * 2 if (year_from or year_to) else limit, 50)}
    url = "https://api2.openreview.net/notes/search?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    papers = []
    for note in (r.json() or {}).get("notes", []):
        content = note.get("content", {})
        title = _or_value(content, "title")
        if not title:
            continue
        cdate = note.get("cdate") or note.get("pdate")
        year = time.gmtime(cdate / 1000).tm_year if isinstance(cdate, (int, float)) else None
        if year_from and year and year < year_from:
            continue
        if year_to and year and year > year_to:
            continue
        papers.append(_paper(
            "openreview", query,
            ids={"openreview": note.get("id")},
            title=title,
            authors=_or_value(content, "authors") or [],
            year=year,
            venue=_or_value(content, "venue") or note.get("domain"),
            type="conference-paper",
            abstract=_or_value(content, "abstract"),
            urls={"landing": f"https://openreview.net/forum?id={note.get('forum') or note.get('id')}"},
        ))
        if len(papers) >= limit:
            break
    return papers, None


# --------------------------------------------------------------------------
# Unpaywall (OA resolution; requires IR_MAILTO)
# --------------------------------------------------------------------------

def unpaywall_oa(cache, doi, fresh=False):
    m = http.mailto()
    if not m:
        return None, "IR_MAILTO required for Unpaywall"
    d = normalize_doi(doi)
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(d or '', safe='/')}?" + urllib.parse.urlencode({"email": m})
    r = http.fetch(cache, url, ttl_class="metadata", fresh=fresh)
    if r.status == 404:
        return None, None
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    data = r.json() or {}
    best = data.get("best_oa_location") or {}
    return {
        "is_oa": data.get("is_oa"),
        "oa_status": data.get("oa_status"),
        "pdf_url": best.get("url_for_pdf") or best.get("url"),
        "license": best.get("license"),
        "version": best.get("version"),
        "journal_is_in_doaj": data.get("journal_is_in_doaj"),
    }, None


# --------------------------------------------------------------------------
# Semantic Scholar (optional — S2_API_KEY only, third vote)
# --------------------------------------------------------------------------

_S2_FIELDS = "title,abstract,year,authors,venue,citationCount,externalIds,openAccessPdf,publicationTypes"


def _s2_enabled() -> bool:
    return bool(os.environ.get("S2_API_KEY"))


def _s2_headers() -> dict:
    return {"x-api-key": os.environ["S2_API_KEY"]}


def _s2_normalize(p: dict, query: str) -> dict:
    ext = p.get("externalIds") or {}
    oa = p.get("openAccessPdf") or {}
    return _paper(
        "s2", query,
        ids={"doi": ext.get("DOI"), "arxiv": ext.get("ArXiv"), "pmid": str(ext["PubMed"]) if ext.get("PubMed") else None, "s2": p.get("paperId")},
        title=p.get("title") or "",
        authors=[a.get("name") for a in p.get("authors", []) if a.get("name")],
        year=p.get("year"),
        venue=p.get("venue") or None,
        type=(p.get("publicationTypes") or [None])[0],
        abstract=p.get("abstract"),
        cited_by_count=p.get("citationCount"),
        oa_pdf_url=oa.get("url"),
        urls={"landing": f"https://www.semanticscholar.org/paper/{p.get('paperId')}", "pdf": oa.get("url")},
    )


def s2_search(cache, query, limit=25, year_from=None, year_to=None, fresh=False):
    if not _s2_enabled():
        return [], "S2_API_KEY not set (optional source)"
    params = {"query": query, "limit": min(limit, 100), "fields": _S2_FIELDS}
    if year_from or year_to:
        params["year"] = f"{year_from or ''}-{year_to or ''}"
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", headers=_s2_headers(), fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    return [_s2_normalize(p, query) for p in (r.json() or {}).get("data", [])[:limit]], None


def s2_lookup(cache, ext_id, fresh=False):
    """ext_id like 'DOI:10.x/y' or 'ARXIV:2101.00001'."""
    if not _s2_enabled():
        return None, "S2_API_KEY not set (optional source)"
    url = f"https://api.semanticscholar.org/graph/v1/paper/{urllib.parse.quote(ext_id, safe=':/')}?" + urllib.parse.urlencode({"fields": _S2_FIELDS})
    r = http.fetch(cache, url, ttl_class="id_lookup", headers=_s2_headers(), fresh=fresh)
    if r.status == 404:
        return None, None
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    data = r.json()
    return (_s2_normalize(data, f"lookup:{ext_id}") if data else None), None


# --------------------------------------------------------------------------
# OpenCitations (independent citation-edge confirmation)
# --------------------------------------------------------------------------

def opencitations_meta(cache, doi, fresh=False):
    """Independent existence check via OpenCitations Meta. Returns
    (found: bool|None, degraded_reason|None) — None means source degraded."""
    d = normalize_doi(doi)
    url = f"https://opencitations.net/meta/api/v1/metadata/doi:{urllib.parse.quote(d or '', safe='/.:')}"
    r = http.fetch(cache, url, ttl_class="id_lookup", fresh=fresh)
    if r.status == 404:
        return False, None
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    data = r.json()
    if isinstance(data, list):
        return len(data) > 0, None
    return None, "unexpected body"


# --------------------------------------------------------------------------
# DOAJ (venue-quality lane)
# --------------------------------------------------------------------------

def doaj_journal(cache, issn, fresh=False):
    url = f"https://doaj.org/api/search/journals/issn:{urllib.parse.quote(issn)}?pageSize=1"
    r = http.fetch(cache, url, ttl_class="metadata", fresh=fresh)
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    return ((r.json() or {}).get("total", 0) > 0), None


# --------------------------------------------------------------------------
# bioRxiv/medRxiv (preprint -> published resolution)
# --------------------------------------------------------------------------

def biorxiv_published_version(cache, doi, fresh=False):
    """If `doi` is a bioRxiv/medRxiv preprint, return the published DOI."""
    d = normalize_doi(doi)
    for server in ("biorxiv", "medrxiv"):
        url = f"https://api.biorxiv.org/details/{server}/{urllib.parse.quote(d or '', safe='/.')}"
        r = http.fetch(cache, url, ttl_class="metadata", fresh=fresh)
        if not r.ok:
            continue
        for rec in (r.json() or {}).get("collection", []):
            pub = rec.get("published")
            if pub and pub not in ("NA", ""):
                return normalize_doi(pub), None
    return None, None


# --------------------------------------------------------------------------
# Retraction Watch bulk load (via Crossref Labs)
# --------------------------------------------------------------------------

_RW_NATURE = {
    "retraction": "retracted",
    "correction": "correction",
    "expression of concern": "eoc",
    "reinstatement": "none",
    "withdrawal": "withdrawal",
}


def load_retraction_watch(cache, url="https://api.labs.crossref.org/data/retractionwatch") -> tuple[int, str | None]:
    """Stream the Retraction Watch CSV into the local retractions table.
    Large download (~tens of MB) — bypasses the HTTP body cache."""
    import ssl as _ssl
    import urllib.request as _rq

    m = http.mailto()
    full = url + ("?" + urllib.parse.urlencode({"mailto": m}) if m else "")
    req = _rq.Request(full, headers={"User-Agent": http._user_agent()})
    rows = []
    try:
        with _rq.urlopen(req, timeout=300, context=_ssl.create_default_context()) as resp:
            text = io.TextIOWrapper(resp, encoding="utf-8", errors="replace", newline="")
            reader = csv.DictReader(text)
            for rec in reader:
                doi = normalize_doi(rec.get("OriginalPaperDOI"))
                if not doi:
                    continue
                nature = (rec.get("RetractionNature") or "").strip().lower()
                status = _RW_NATURE.get(nature, "retracted" if nature else "unknown")
                rows.append((
                    doi, status,
                    normalize_doi(rec.get("RetractionDOI")),
                    (rec.get("RetractionDate") or "").strip(),
                    (rec.get("Reason") or "").strip()[:500],
                ))
    except Exception as e:  # noqa: BLE001 — bulk load is best-effort
        return 0, f"retraction watch download failed: {e}"
    n = cache.retraction_bulk_upsert(rows)
    cache.meta_set("retractionwatch_loaded_at", now_iso())
    return n, None


def retraction_watch_stale(cache, max_age_days=7) -> bool:
    loaded = cache.meta_get("retractionwatch_loaded_at")
    if not loaded:
        return True
    try:
        t = time.mktime(time.strptime(loaded, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return True
    return (time.time() - t) > max_age_days * 86400


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

SEARCH_ADAPTERS = {
    "openalex": openalex_search,
    "crossref": crossref_search,
    "arxiv": arxiv_search,
    "europepmc": europepmc_search,
    "pubmed": pubmed_search,
    "dblp": dblp_search,
    "openreview": openreview_search,
    "s2": s2_search,
}


# ==========================================================================
# v2 — Venue style-learning helpers (reuse existing hosts; no allowlist change)
# ==========================================================================

def openalex_sources_search(cache, name, source_type=None, fresh=False):
    """Resolve a venue name to OpenAlex source records, ranked by works_count."""
    params = {"search": name, "per-page": 10, "sort": "works_count:desc"}
    if source_type:
        params["filter"] = f"type:{source_type}"
    if http.mailto():
        params["mailto"] = http.mailto()
    url = "https://api.openalex.org/sources?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="metadata", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    out = []
    for s in (r.json() or {}).get("results", []):
        out.append({
            "id": (s.get("id") or "").rsplit("/", 1)[-1] or None,
            "display_name": s.get("display_name"),
            "issn_l": s.get("issn_l"),
            "type": s.get("type"),
            "publisher": s.get("host_organization_name"),
            "works_count": s.get("works_count"),
            "is_oa": s.get("is_oa"),
        })
    return out, None


def openalex_works_by_source(cache, source_id, since=None, n=5, oa_only=False, fresh=False):
    """Newest works from a specific OpenAlex source (venue)."""
    filters = [f"primary_location.source.id:{source_id}"]
    if since:
        filters.append(f"from_publication_date:{since}")
    if oa_only:
        filters.append("is_oa:true")
    params = {"filter": ",".join(filters), "sort": "publication_date:desc", "per-page": min(n, 50)}
    if http.mailto():
        params["mailto"] = http.mailto()
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    return [_openalex_normalize(w, f"venue:{source_id}") for w in (r.json() or {}).get("results", [])[:n]], None


def crossref_journal_works(cache, issn, n=5, fresh=False):
    """Newest works from a journal by ISSN (Crossref fallback when no OpenAlex source)."""
    params = {"sort": "published", "order": "desc", "rows": min(n, 50)}
    if http.mailto():
        params["mailto"] = http.mailto()
    url = f"https://api.crossref.org/journals/{urllib.parse.quote(issn)}/works?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    items = ((r.json() or {}).get("message") or {}).get("items", [])
    return [_crossref_normalize(i, f"venue-issn:{issn}") for i in items[:n]], None


def dblp_venue_works(cache, venue, n=5, fresh=False):
    """CS-venue works via DBLP (fallback for venues without an ISSN)."""
    return dblp_search(cache, f"venue:{venue}:", limit=n, fresh=fresh)


# ==========================================================================
# v2 — Dataset discovery adapters
# ==========================================================================

_LICENSE_NC = re.compile(r"\b(nc|non-?commercial|cc[- ]?by[- ]?nc)\b", re.IGNORECASE)
_LICENSE_ND = re.compile(r"\b(nd|no-?deriv|cc[- ]?by[- ]?nd)\b", re.IGNORECASE)
_LICENSE_SA = re.compile(r"\b(sa|share-?alike)\b", re.IGNORECASE)
_OPEN_LICENSE = re.compile(
    r"\b(cc[- ]?by(?![- ]?n)|cc0|mit|apache|bsd|public domain|odbl|odc-by|gpl|lgpl)\b",
    re.IGNORECASE)


def _license_block(spdx=None, name=None, uri=None):
    text = " ".join(str(x) for x in (spdx, name, uri) if x)
    if not text.strip():
        return {"spdx_id": spdx, "name": name, "uri": uri, "is_open": None,
                "noncommercial": None, "sharealike": None}
    return {
        "spdx_id": spdx, "name": name, "uri": uri,
        "is_open": bool(_OPEN_LICENSE.search(text)) and not _LICENSE_NC.search(text),
        "noncommercial": bool(_LICENSE_NC.search(text)),
        "sharealike": bool(_LICENSE_SA.search(text)),
        "noderivatives": bool(_LICENSE_ND.search(text)),
    }


def _dataset(source, query, **f):
    """Normalize an adapter hit to the canonical DATASET-RECORD. Every field
    nullable; a missing field is explicit null, never fabricated."""
    ids = f.pop("ids", {})
    rec = {
        "record_id": f.pop("record_id", None) or f"{source}:{f.get('native_id')}",
        "source": source,
        "native_id": f.pop("native_id", None),
        "mirrors": f.pop("mirrors", []),
        "title": f.pop("title", None),
        "creators": f.pop("creators", []),
        "year": f.pop("year", None),
        "doi": normalize_doi(f.pop("doi", None)),
        "conceptdoi": normalize_doi(f.pop("conceptdoi", None)),
        "url": f.pop("url", None),
        "description": (f.pop("description", None) or None),
        "task_categories": f.pop("task_categories", []),
        "modalities": f.pop("modalities", []),
        "languages": f.pop("languages", []),
        "domain": f.pop("domain", None),
        "license": f.pop("license", None) or _license_block(),
        "access": f.pop("access", None) or {"right": None, "gated": None,
                                            "requires_dua": None, "requires_login": None},
        "size": f.pop("size", None) or {"num_instances": None, "num_features": None,
                                        "num_bytes": None, "size_category": None},
        "splits": f.pop("splits", []),
        "features": f.pop("features", []),
        "default_target": f.pop("default_target", None),
        "formats": f.pop("formats", []),
        "download_urls": f.pop("download_urls", []),   # recorded, NEVER fetched
        "checksums": f.pop("checksums", []),
        "provenance": f.pop("provenance", {}),
        "citations": f.pop("citations", {"count": None, "source": None}),
        "popularity": f.pop("popularity", {"downloads": None, "likes": None}),
        "datasheet": f.pop("datasheet", {"croissant": None, "datasheet_url": None,
                                         "has_ethics_statement": None, "has_biases_statement": None}),
        "integrity": f.pop("integrity", {"known_leakage_flag": None,
                                         "known_contamination_flag": None,
                                         "deprecation_flag": None, "disabled": None}),
        "paperswithcode_id": f.pop("paperswithcode_id", None),
        "last_modified": f.pop("last_modified", None),
        "retrieved_at": now_iso(),
        "provenance_query": query,
        "degraded_reason": f.pop("degraded_reason", None),
    }
    rec.update(f)
    return rec


def _hf_tag_values(tags, prefix):
    out = []
    for t in tags or []:
        if isinstance(t, str) and t.startswith(prefix):
            out.append(t[len(prefix):])
    return out


def adapter_hf_datasets(cache, query, limit=25, fresh=False):
    params = {"search": query, "limit": min(limit, 100), "full": "true", "sort": "downloads"}
    url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="dataset", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    out = []
    for d in (r.json() or [])[:limit]:
        tags = d.get("tags", [])
        card = d.get("cardData") or {}
        lic = card.get("license") or (_hf_tag_values(tags, "license:") or [None])[0]
        out.append(_dataset(
            "hf", query,
            native_id=d.get("id"), record_id=f"hf:{d.get('id')}",
            title=d.get("id"), url=f"https://huggingface.co/datasets/{d.get('id')}",
            task_categories=(card.get("task_categories") or _hf_tag_values(tags, "task_categories:")),
            modalities=_hf_tag_values(tags, "modality:") or card.get("modalities", []),
            languages=(card.get("language") if isinstance(card.get("language"), list) else _hf_tag_values(tags, "language:")),
            license=_license_block(spdx=lic, name=lic),
            access={"right": "gated" if d.get("gated") else "open",
                    "gated": bool(d.get("gated")), "requires_dua": bool(d.get("gated")),
                    "requires_login": bool(d.get("private"))},
            size={"num_instances": None, "num_features": None, "num_bytes": None,
                  "size_category": (_hf_tag_values(tags, "size_categories:") or [None])[0]},
            popularity={"downloads": d.get("downloads"), "likes": d.get("likes")},
            paperswithcode_id=card.get("paperswithcode_id"),
            datasheet={"croissant": f"https://huggingface.co/api/datasets/{d.get('id')}/croissant",
                       "datasheet_url": f"https://huggingface.co/datasets/{d.get('id')}",
                       "has_ethics_statement": None, "has_biases_statement": None},
            last_modified=d.get("lastModified"),
            arxiv_ids=_hf_tag_values(tags, "arxiv:"),
        ))
    return out, None


def hf_dataset_card(cache, dataset_id, fresh=False):
    url = f"https://huggingface.co/api/datasets/{urllib.parse.quote(dataset_id, safe='/')}"
    r = http.fetch(cache, url, ttl_class="id_lookup", fresh=fresh)
    if r.status == 404:
        return None, None
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    return r.json(), None


def hf_dataset_splits(cache, dataset_id, fresh=False):
    url = "https://datasets-server.huggingface.co/splits?" + urllib.parse.urlencode({"dataset": dataset_id})
    r = http.fetch(cache, url, ttl_class="dataset", fresh=fresh)
    if not r.ok:
        return None, r.degraded_reason or f"http {r.status}"
    data = r.json() or {}
    splits = [{"name": s.get("split"), "config": s.get("config")} for s in data.get("splits", [])]
    return {"splits": splits, "pending": data.get("pending"), "failed": data.get("failed")}, None


def adapter_datacite(cache, query, limit=25, fresh=False):
    # page[size] must be percent-encoded.
    q = urllib.parse.urlencode({"query": query, "resource-type-id": "dataset"})
    url = f"https://api.datacite.org/dois?{q}&page%5Bsize%5D={min(limit, 100)}"
    r = http.fetch(cache, url, ttl_class="dataset", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    out = []
    for d in (r.json() or {}).get("data", [])[:limit]:
        a = d.get("attributes", {})
        rights = a.get("rightsList") or []
        spdx = next((x.get("rightsIdentifier") for x in rights if x.get("rightsIdentifier")), None)
        rname = next((x.get("rights") for x in rights if x.get("rights")), None)
        ruri = next((x.get("rightsUri") for x in rights if x.get("rightsUri")), None)
        titles = a.get("titles") or []
        out.append(_dataset(
            "datacite", query,
            native_id=d.get("id"), record_id=f"datacite:{d.get('id')}",
            doi=a.get("doi") or d.get("id"),
            title=(titles[0].get("title") if titles else None),
            creators=[c.get("name") for c in a.get("creators", []) if c.get("name")],
            year=a.get("publicationYear"),
            url=a.get("url"),
            description=next((x.get("description") for x in (a.get("descriptions") or []) if x.get("description")), None),
            license=_license_block(spdx=spdx, name=rname, uri=ruri),
            citations={"count": (a.get("citationCount")), "source": "datacite"},
            provenance={"publisher": a.get("publisher"), "funding": [f.get("funderName") for f in a.get("fundingReferences", [])]},
        ))
    return out, None


def adapter_zenodo(cache, query, limit=25, fresh=False):
    url = "https://zenodo.org/api/records?" + urllib.parse.urlencode(
        {"q": query, "type": "dataset", "size": min(limit, 100)})
    r = http.fetch(cache, url, ttl_class="dataset", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    out = []
    for h in ((r.json() or {}).get("hits") or {}).get("hits", [])[:limit]:
        m = h.get("metadata", {})
        lic = (m.get("license") or {})
        lic_id = lic.get("id") if isinstance(lic, dict) else lic
        files = h.get("files", [])
        out.append(_dataset(
            "zenodo", query,
            native_id=str(h.get("id")), record_id=f"zenodo:{h.get('id')}",
            doi=h.get("doi") or m.get("doi"), conceptdoi=h.get("conceptdoi"),
            title=m.get("title"),
            creators=[c.get("name") for c in m.get("creators", []) if c.get("name")],
            year=(m.get("publication_date") or "")[:4] or None,
            url=(h.get("links") or {}).get("self_html") or (h.get("links") or {}).get("html"),
            description=_strip_jats(m.get("description")),
            license=_license_block(spdx=lic_id, name=lic_id),
            access={"right": m.get("access_right"), "gated": m.get("access_right") not in ("open", None),
                    "requires_dua": m.get("access_right") == "restricted", "requires_login": None},
            size={"num_instances": None, "num_features": None,
                  "num_bytes": sum(fi.get("size", 0) for fi in files) or None, "size_category": None},
            download_urls=[(fi.get("links") or {}).get("self") for fi in files],
            checksums=[fi.get("checksum") for fi in files],
        ))
    return out, None


def adapter_openml(cache, query, limit=25, fresh=False):
    # OpenML's classic data_name filter is exact-match, so it is useless for
    # keyword discovery. Fetch a capped list once (cached) and substring-filter
    # by name client-side — the same approach used for UCI.
    url = "https://www.openml.org/api/v1/json/data/list/limit/1000"
    r = http.fetch(cache, url, ttl_class="dataset", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    body = r.json() or {}
    rows = ((body.get("data") or {}).get("dataset")) or []
    ql = query.lower()
    terms = [t for t in ql.split() if t]
    filtered = [d for d in rows if all(t in (d.get("name") or "").lower() for t in terms)] if terms else rows
    out = []
    for d in filtered[:limit]:
        quals = {q.get("name"): q.get("value") for q in d.get("quality", [])}
        out.append(_dataset(
            "openml", query,
            native_id=str(d.get("did")), record_id=f"openml:{d.get('did')}",
            title=d.get("name"), url=f"https://www.openml.org/d/{d.get('did')}",
            license=_license_block(name=d.get("licence")),
            access={"right": "open", "gated": False, "requires_dua": False, "requires_login": False},
            formats=[d.get("format")] if d.get("format") else [],
            size={"num_instances": _to_int(quals.get("NumberOfInstances")),
                  "num_features": _to_int(quals.get("NumberOfFeatures")),
                  "num_bytes": None, "size_category": None},
            default_target=d.get("target_feature") or None,
            integrity={"known_leakage_flag": None, "known_contamination_flag": None,
                       "deprecation_flag": d.get("status") == "deactivated",
                       "disabled": d.get("status") == "deactivated"},
        ))
    return out, None


def adapter_uci(cache, query, limit=25, fresh=False):
    url = "https://archive.ics.uci.edu/api/datasets/list"
    r = http.fetch(cache, url, ttl_class="dataset", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    data = r.json() or {}
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return [], "unexpected uci body"
    ql = query.lower()
    out = []
    for d in items:
        name = d.get("name") or d.get("Name") or ""
        if ql and ql not in name.lower():
            continue
        did = d.get("id") or d.get("ID")
        out.append(_dataset(
            "uci", query,
            native_id=str(did), record_id=f"uci:{did}",
            title=name, url=f"https://archive.ics.uci.edu/dataset/{did}",
            task_categories=[d.get("Task")] if d.get("Task") else [],
            size={"num_instances": _to_int(d.get("numInstances") or d.get("Instances")),
                  "num_features": _to_int(d.get("numFeatures") or d.get("Features")),
                  "num_bytes": None, "size_category": None},
            license=_license_block(name="UCI (see landing page)"),
            access={"right": "open", "gated": False, "requires_dua": False, "requires_login": False},
        ))
        if len(out) >= limit:
            break
    return out, None


def adapter_ncbi_gds(cache, query, limit=25, fresh=False):
    return _ncbi_dataset(cache, query, "gds", limit, fresh)


def adapter_ncbi_sra(cache, query, limit=25, fresh=False):
    return _ncbi_dataset(cache, query, "sra", limit, fresh)


def _ncbi_dataset(cache, query, db, limit, fresh):
    params = _eutils_params({"db": db, "term": query, "retmode": "json", "retmax": min(limit, 50)})
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(params)
    r = http.fetch(cache, url, ttl_class="search", fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    ids = ((r.json() or {}).get("esearchresult") or {}).get("idlist", [])
    if not ids:
        return [], None
    sp = _eutils_params({"db": db, "id": ",".join(ids), "retmode": "json"})
    surl = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode(sp)
    sr = http.fetch(cache, surl, ttl_class="metadata", fresh=fresh)
    result = (sr.json() or {}).get("result", {}) if sr.ok else {}
    out = []
    for uid in ids:
        doc = result.get(uid) or {}
        out.append(_dataset(
            db, query,
            native_id=uid, record_id=f"{db}:{uid}",
            title=doc.get("title") or f"{db.upper()} {uid}",
            url=f"https://www.ncbi.nlm.nih.gov/{'gds' if db == 'gds' else 'sra'}/{uid}",
            domain="biomedical",
            modalities=["genomic"],
            description=doc.get("summary"),
            access={"right": "open", "gated": False, "requires_dua": None, "requires_login": False},
        ))
    return out, None


def adapter_openneuro(cache, query, limit=25, fresh=False):
    body = json.dumps({
        "query": "query($q:String!){datasets(first:%d){edges{node{id latestSnapshot{tag description{Name}}}}}}" % min(limit, 25),
        "variables": {"q": query},
    }).encode()
    r = http.fetch(cache, "https://openneuro.org/crn/graphql", ttl_class="dataset",
                   method="POST", data=body, headers={"Content-Type": "application/json"}, fresh=fresh)
    if not r.ok:
        return [], r.degraded_reason or f"http {r.status}"
    edges = (((r.json() or {}).get("data") or {}).get("datasets") or {}).get("edges", [])
    out = []
    for e in edges[:limit]:
        node = e.get("node", {})
        desc = (node.get("latestSnapshot") or {}).get("description") or {}
        out.append(_dataset(
            "openneuro", query,
            native_id=node.get("id"), record_id=f"openneuro:{node.get('id')}",
            title=desc.get("Name") or node.get("id"),
            url=f"https://openneuro.org/datasets/{node.get('id')}",
            domain="neuroimaging", modalities=["mri"],
            access={"right": "open", "gated": False, "requires_dua": None, "requires_login": False},
        ))
    return out, None


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


DATASET_SOURCES = ("hf", "openml", "datacite", "zenodo", "uci", "geo", "sra", "openneuro")
DEFAULT_DATASET_SOURCES = ("hf", "openml", "datacite", "zenodo", "uci")
DATASET_ADAPTERS = {
    "hf": adapter_hf_datasets,
    "openml": adapter_openml,
    "datacite": adapter_datacite,
    "zenodo": adapter_zenodo,
    "uci": adapter_uci,
    "geo": adapter_ncbi_gds,
    "sra": adapter_ncbi_sra,
    "openneuro": adapter_openneuro,
}


def collapse_dataset_mirrors(records):
    """Collapse the same dataset across mirrors (shared DOI/conceptdoi or exact
    normalized title+creator) into one record with a mirrors[] list. Distinct
    from paper INDEX_ANCESTRY."""
    from scholar_match import exact_normalized_title
    clusters = []
    for rec in records:
        key_doi = rec.get("conceptdoi") or rec.get("doi")
        target = None
        for c in clusters:
            ckey = c.get("conceptdoi") or c.get("doi")
            if key_doi and ckey and normalize_doi(key_doi) == normalize_doi(ckey):
                target = c
                break
            if (rec.get("title") and c.get("title")
                    and exact_normalized_title(rec["title"], c["title"])
                    and set(rec.get("creators") or []) & set(c.get("creators") or [])):
                target = c
                break
        if target is None:
            rec.setdefault("mirrors", [])
            clusters.append(rec)
        else:
            target["mirrors"].append({"source": rec["source"], "id": rec.get("native_id"), "doi": rec.get("doi")})
            for k in ("doi", "conceptdoi", "description", "paperswithcode_id"):
                if not target.get(k) and rec.get(k):
                    target[k] = rec[k]
            if (rec.get("citations") or {}).get("count") and not (target.get("citations") or {}).get("count"):
                target["citations"] = rec["citations"]
    return clusters
