#!/usr/bin/env python3
"""scholar.py — the retrieval + integrity-gate backbone of Intensive Research.

Stdlib-only. Every network-touching feature degrades per source instead of
aborting; gate decisions are exit codes, never model assertions.

Subcommands:
  search        fan out one query across scholarly APIs, merge + dedup
  lookup        resolve one work by id (doi/arxiv/pmid/openalex)
  verify        verify one reference (id-keyed or title-only)
  verify-batch  verify every entry of a corpus/refs file
  fulltext      resolve open-access full text (JATS XML / PDF download)
  cites / refs  citation-graph expansion via OpenAlex
  dedup         merge searcher shards into a clustered candidate corpus
  ingest        resolve a plain list of DOIs/arXiv ids into papers
  export        corpus -> bibtex | ris | csv | csl-json
  audit-report  deterministic G3 gate over a report's citation markers
  count         total OpenAlex hits for a query (bridge thinness probe)
  topic-trends  trend/burst/diversity profile of a subject (ideation phase 1)
  gap-metrics   deterministic bibliometric metrics for mined gaps
  score-gaps    normalize + weight metrics into ranked GapScores + leaderboard
  doctor        environment preflight
  cache         stats | clear | path | load-retractions
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scholar_apis as apis  # noqa: E402
import scholar_http as http  # noqa: E402
import scholar_metrics as metrics  # noqa: E402
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


def _now() -> str:
    return apis.now_iso()


def _write_json(path: str | None, payload) -> None:
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)


def _ledger_append(path: str | None, entry: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    entry.setdefault("ts", _now())
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _flush_request_counts(ledger: str | None) -> None:
    if ledger and (http.REQUEST_COUNTS["requests"] or http.REQUEST_COUNTS["cache_hits"]):
        _ledger_append(ledger, {"event": "request_counts", **http.REQUEST_COUNTS})


# --------------------------------------------------------------------------
# Dedup / clustering
# --------------------------------------------------------------------------

def _cluster_key(p: dict):
    ids = p.get("ids") or {}
    if ids.get("doi"):
        return ("doi", ids["doi"])
    if ids.get("arxiv"):
        return ("arxiv", ids["arxiv"])
    if ids.get("pmid"):
        return ("pmid", ids["pmid"])
    return None


_RETRACTION_RANK = {"unknown": 0, "none": 0, "correction": 1, "eoc": 2, "withdrawal": 3, "retracted": 4}


def _merge_into(base: dict, extra: dict) -> None:
    for k, v in (extra.get("ids") or {}).items():
        if v and not base["ids"].get(k):
            base["ids"][k] = v
    if len(extra.get("abstract") or "") > len(base.get("abstract") or ""):
        base["abstract"] = extra["abstract"]
        base["abstract_source"] = extra.get("abstract_source")
    for field in ("year", "venue", "type", "oa_pdf_url"):
        if base.get(field) is None and extra.get(field) is not None:
            base[field] = extra[field]
    if extra.get("cited_by_count") is not None:
        base["cited_by_count"] = max(base.get("cited_by_count") or 0, extra["cited_by_count"])
    if extra.get("is_oa"):
        base["is_oa"] = True
    for k, v in (extra.get("urls") or {}).items():
        if v and not (base.get("urls") or {}).get(k):
            base.setdefault("urls", {})[k] = v
    er = (extra.get("retraction") or {})
    if _RETRACTION_RANK.get(er.get("status"), 0) > _RETRACTION_RANK.get(base["retraction"].get("status"), 0):
        base["retraction"] = er
    for s in (extra.get("provenance") or {}).get("source_apis", []):
        if s not in base["provenance"]["source_apis"]:
            base["provenance"]["source_apis"].append(s)
    if not base.get("id") and extra.get("id"):
        base["id"] = extra["id"]


def dedup_papers(papers: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    by_key: dict = {}
    for p in papers:
        if not p.get("title"):
            continue
        key = _cluster_key(p)
        target = by_key.get(key) if key else None
        if target is None:
            # Fuzzy fallback: exact normalized title + year +/-1.
            tnorm = normalize_title(p["title"])
            for c in clusters:
                if normalize_title(c["title"]) == tnorm and title_years_match(c.get("year"), p.get("year")):
                    target = c
                    break
        if target is None:
            q = json.loads(json.dumps(p))  # deep copy
            q["cluster_size"] = 1
            clusters.append(q)
            if key:
                by_key[key] = q
        else:
            _merge_into(target, p)
            target["cluster_size"] = target.get("cluster_size", 1) + 1
            k2 = _cluster_key(target)
            if k2:
                by_key[k2] = target
    for c in clusters:
        ids = c["ids"]
        for k in ("doi", "arxiv", "pmid", "openalex", "dblp", "openreview", "s2"):
            if ids.get(k):
                c["id"] = f"{k}:{ids[k]}"
                break
    return clusters


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

def cmd_search(args) -> int:
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in apis.SEARCH_ADAPTERS]
    if unknown:
        http.eprint(f"unknown sources: {unknown}; valid: {sorted(apis.SEARCH_ADAPTERS)}")
        return 2

    per_source: dict = {}
    all_papers: list = []

    def run_one(source: str):
        cache = http.Cache()
        try:
            fn = apis.SEARCH_ADAPTERS[source]
            papers, degraded = fn(cache, args.query, limit=args.limit,
                                  year_from=args.year_from, year_to=args.year_to,
                                  fresh=args.fresh)
            return source, papers, degraded
        finally:
            cache.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sources), 8)) as ex:
        for source, papers, degraded in ex.map(run_one, sources):
            per_source[source] = {
                "count": len(papers),
                "status": "degraded" if degraded else "ok",
                **({"error": degraded} if degraded else {}),
            }
            all_papers.extend(papers)
            _ledger_append(args.ledger, {
                "event": "search", "source": source, "query": args.query,
                "hits": len(papers), "status": per_source[source]["status"],
            })

    unique = dedup_papers(all_papers)
    envelope = {
        "query": args.query,
        "executed_at": _now(),
        "per_source": per_source,
        "dedup": {"input": len(all_papers), "unique": len(unique)},
        "papers": unique,
    }
    _flush_request_counts(args.ledger)
    _write_json(args.out, envelope)
    return 0


# --------------------------------------------------------------------------
# lookup / ingest
# --------------------------------------------------------------------------

def _lookup_one(cache, *, doi=None, arxiv=None, pmid=None, openalex=None, fresh=False):
    """Best-effort merged record for one identifier."""
    found = []
    if doi:
        for fn in (lambda: apis.crossref_lookup(cache, doi, fresh=fresh),
                   lambda: apis.openalex_lookup(cache, doi=doi, fresh=fresh)):
            p, _ = fn()
            if p:
                found.append(p)
    if arxiv:
        p, _ = apis.arxiv_lookup(cache, arxiv, fresh=fresh)
        if p:
            found.append(p)
    if pmid:
        papers, _ = apis.pubmed_summaries(cache, [pmid], f"lookup:{pmid}", fresh=fresh)
        found.extend(papers)
    if openalex:
        p, _ = apis.openalex_lookup(cache, openalex_id=openalex, fresh=fresh)
        if p:
            found.append(p)
    if not found:
        return None
    merged = dedup_papers(found)
    return merged[0] if merged else None


def cmd_lookup(args) -> int:
    cache = http.Cache()
    try:
        p = _lookup_one(cache, doi=args.doi, arxiv=args.arxiv, pmid=args.pmid,
                        openalex=args.openalex, fresh=args.fresh)
        if p is None:
            _write_json(args.out, {"found": False})
            return 1
        _write_json(args.out, {"found": True, "paper": p})
        return 0
    finally:
        cache.close()


def cmd_ingest(args) -> int:
    with open(args.infile, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    cache = http.Cache()
    papers, misses = [], []
    try:
        for ln in lines:
            doi = normalize_doi(ln) if ("/" in ln or ln.lower().startswith("doi")) else None
            arxiv = None if doi else normalize_arxiv(ln)
            p = _lookup_one(cache, doi=doi, arxiv=arxiv, fresh=args.fresh)
            if p:
                p["provenance"]["query"] = f"ingest:{ln}"
                papers.append(p)
            else:
                misses.append(ln)
    finally:
        cache.close()
    _write_json(args.out, {
        "executed_at": _now(),
        "ingested": len(papers),
        "misses": misses,
        "papers": dedup_papers(papers),
    })
    return 0


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def _independent_count(agreed: list[str]) -> int:
    """Count independent confirmations, collapsing index ancestry
    (OpenAlex ingests Crossref/arXiv/PubMed — agreement between an index and
    its ancestor is one confirmation, not two)."""
    agreed_set = set(agreed)
    count = 0
    for idx in agreed_set:
        ancestors = apis.INDEX_ANCESTRY.get(idx, set())
        if ancestors & agreed_set:
            continue  # collapsed into its ancestor's confirmation
        count += 1
    return count


def check_retraction(cache, doi: str | None, fresh=False) -> dict:
    """Layered retraction check: local Retraction Watch DB, then Crossref
    update-to relations. Returns the canonical retraction block."""
    if not doi:
        return {"status": "unknown", "source": None, "checked_at": _now()}
    d = normalize_doi(doi)
    local = cache.retraction_lookup(d)
    if local and local["status"] not in (None, "none", "unknown"):
        return {"status": local["status"], "source": "retractionwatch",
                "notice_doi": local.get("notice_doi"), "checked_at": _now()}
    status, notice, degraded = apis.crossref_updates(cache, d, fresh=fresh)
    if status:
        return {"status": status, "source": "crossref", "notice_doi": notice, "checked_at": _now()}
    if degraded and not local:
        return {"status": "unknown", "source": f"degraded: {degraded}", "checked_at": _now()}
    return {"status": "none", "source": "retractionwatch+crossref", "checked_at": _now()}


def verify_reference(cache, *, doi=None, arxiv=None, pmid=None, title=None,
                     year=None, fresh=False) -> dict:
    """Verification semantics (G1b):
    - ID-keyed lookup resolving in ONE authoritative index (with exact
      normalized-title cross-check when a title is supplied) => verified.
    - Title-only: exact-normalized-title match required; generic titles
      without a corroborating ID => unresolvable; >=2 INDEPENDENT indexes
      => verified, 1 => single_index, 0 => unresolvable.
    - not_found ONLY on ID-keyed non-resolution.
    - degraded when every consulted index was unusable.
    """
    checked = []
    agreed = []
    resolved: dict | None = None
    degraded_reasons = []
    title_mismatch = False

    def consider(idx: str, paper, err):
        nonlocal resolved, title_mismatch
        checked.append(idx)
        if err:
            degraded_reasons.append(f"{idx}: {err}")
            return
        if paper is None:
            return
        if title and paper.get("title"):
            if notice_title(paper["title"]) and not notice_title(title):
                return  # notice-relation veto
            if not exact_normalized_title(title, paper["title"]) and similarity(title, paper["title"]) < 0.70:
                title_mismatch = True
                return
        agreed.append(idx)
        if resolved is None:
            resolved = paper

    id_keyed = bool(doi or arxiv or pmid)
    if doi:
        p, e = apis.crossref_lookup(cache, doi, fresh=fresh)
        consider("crossref", p, e)
        p, e = apis.openalex_lookup(cache, doi=doi, fresh=fresh)
        consider("openalex", p, e)
        found, e = apis.opencitations_meta(cache, doi, fresh=fresh)
        if e:
            degraded_reasons.append(f"opencitations: {e}")
        elif found:
            checked.append("opencitations")
            agreed.append("opencitations")
        if apis._s2_enabled():
            p, e = apis.s2_lookup(cache, f"DOI:{normalize_doi(doi)}", fresh=fresh)
            consider("s2", p, e)
    if arxiv:
        p, e = apis.arxiv_lookup(cache, arxiv, fresh=fresh)
        consider("arxiv", p, e)
        if not doi:
            p, e = apis.openalex_lookup(cache, doi=f"10.48550/arxiv.{normalize_arxiv(arxiv)}", fresh=fresh)
            consider("openalex", p, e)
    if pmid and not doi:
        papers, e = apis.pubmed_summaries(cache, [str(pmid)], f"verify:{pmid}", fresh=fresh)
        consider("pubmed", papers[0] if papers else None, e)

    if not id_keyed and title:
        # Title-only path.
        if generic_title(title):
            return _verdict("unresolvable", checked, agreed, resolved,
                            reason="generic title without corroborating id",
                            degraded=degraded_reasons)
        for idx, fn in (("openalex", apis.openalex_search), ("crossref", apis.crossref_search)):
            papers, e = fn(cache, title, limit=5, fresh=fresh)
            if e:
                degraded_reasons.append(f"{idx}: {e}")
                checked.append(idx)
                continue
            checked.append(idx)
            hit = None
            for p in papers:
                if notice_title(p.get("title") or ""):
                    continue
                if exact_normalized_title(title, p.get("title") or "") and title_years_match(year, p.get("year")):
                    hit = p
                    break
            if hit:
                agreed.append(idx)
                if resolved is None:
                    resolved = hit

    if id_keyed:
        if agreed:
            status = "verified"
        elif checked and len(degraded_reasons) >= len(set(checked)):
            status = "degraded"
        elif title_mismatch:
            status = "unresolvable"
        else:
            status = "not_found"
    else:
        independent = _independent_count(agreed)
        if independent >= 2:
            status = "verified"
        elif len(agreed) >= 1:
            status = "single_index"
        elif degraded_reasons and not checked:
            status = "degraded"
        elif degraded_reasons and len(degraded_reasons) >= len(set(checked)):
            status = "degraded"
        else:
            status = "unresolvable"

    verdict = _verdict(status, checked, agreed, resolved, degraded=degraded_reasons)
    resolved_doi = (resolved or {}).get("ids", {}).get("doi") or normalize_doi(doi)
    verdict["retraction"] = check_retraction(cache, resolved_doi, fresh=fresh)
    return verdict


def _verdict(status, checked, agreed, resolved, reason=None, degraded=None) -> dict:
    v = {
        "status": status,
        "indexes_checked": sorted(set(checked)),
        "indexes_agreed": sorted(set(agreed)),
        "independent_count": _independent_count(agreed),
        "checked_at": _now(),
    }
    if reason:
        v["reason"] = reason
    if degraded:
        v["degraded_sources"] = degraded
    if resolved:
        v["resolved"] = {
            "id": resolved.get("id"),
            "ids": resolved.get("ids"),
            "title": resolved.get("title"),
            "year": resolved.get("year"),
        }
    return v


def cmd_verify(args) -> int:
    cache = http.Cache()
    try:
        _maybe_load_retractions(cache, quiet=True)
        v = verify_reference(cache, doi=args.doi, arxiv=args.arxiv, pmid=args.pmid,
                             title=args.title, year=args.year, fresh=args.fresh)
        _write_json(args.out, v)
        return 0 if v["status"] in ("verified", "single_index") else 1
    finally:
        cache.close()


def _iter_batch_entries(path: str):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".jsonl"):
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    data = json.loads(text)
    if isinstance(data, dict) and "papers" in data:
        return data["papers"]
    if isinstance(data, list):
        return data
    raise ValueError("expected a JSON list, a {papers:[...]} envelope, or JSONL")


def cmd_verify_batch(args) -> int:
    entries = _iter_batch_entries(args.infile)
    cache = http.Cache()
    counts: dict = {}
    try:
        _maybe_load_retractions(cache, quiet=True)
        # Fast path: batch-resolve all DOIs against OpenAlex first (50/request).
        dois = [((e.get("ids") or {}).get("doi") or e.get("doi")) for e in entries]
        dois = [d for d in dois if d]
        batch, _ = apis.openalex_batch_doi(cache, dois, fresh=args.fresh)
        for e in entries:
            ids = e.get("ids") or {}
            doi = ids.get("doi") or e.get("doi")
            arxiv = ids.get("arxiv") or e.get("arxiv")
            pmid = ids.get("pmid") or e.get("pmid")
            title = e.get("title")
            v = verify_reference(cache, doi=doi, arxiv=arxiv, pmid=pmid,
                                 title=title, year=e.get("year"), fresh=args.fresh)
            if doi and batch.get(normalize_doi(doi)) and "openalex" not in v["indexes_agreed"]:
                v["indexes_agreed"] = sorted(set(v["indexes_agreed"]) | {"openalex"})
                v["independent_count"] = _independent_count(v["indexes_agreed"])
            e["verification"] = v
            e["retraction"] = v.get("retraction", e.get("retraction"))
            counts[v["status"]] = counts.get(v["status"], 0) + 1
            retr = (v.get("retraction") or {}).get("status")
            if retr and retr not in ("none", "unknown"):
                counts[f"retraction:{retr}"] = counts.get(f"retraction:{retr}", 0) + 1
    finally:
        cache.close()
    payload = {"executed_at": _now(), "counts": counts, "papers": entries}
    _write_json(args.out or args.infile, payload)
    bad = sum(n for k, n in counts.items() if k in ("not_found",) or k.startswith("retraction:retracted"))
    if args.strict and bad:
        return 1
    return 0


# --------------------------------------------------------------------------
# fulltext
# --------------------------------------------------------------------------

def _download(url: str, dest: str) -> tuple[bool, str | None]:
    """Direct download for OA full texts. Deliberately NOT host-allowlisted
    (publisher PDFs live on arbitrary hosts) but https-only and size-capped."""
    if urllib.parse.urlsplit(url).scheme != "https":
        return False, "non-https refused"
    import ssl
    req = urllib.request.Request(url, headers={"User-Agent": http._user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl.create_default_context()) as resp:
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            size = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 100 * (1 << 20):
                        return False, "exceeds 100MB cap"
                    f.write(chunk)
        return True, None
    except Exception as e:  # noqa: BLE001 — degrade, never crash the waterfall
        return False, str(e)


def cmd_fulltext(args) -> int:
    cache = http.Cache()
    result = {"doi": args.doi, "pmid": args.pmid, "mode": "abstract-only", "path": None,
              "license": None, "degraded": []}
    try:
        paper = _lookup_one(cache, doi=args.doi, pmid=args.pmid, fresh=args.fresh)
        ids = dict((paper or {}).get("ids", {}))
        # arXiv DOIs are DataCite (Crossref 404s), so derive the arXiv id from
        # the DOI directly rather than relying on a metadata lookup.
        if not ids.get("arxiv") and args.doi:
            nd = normalize_doi(args.doi) or ""
            if nd.startswith("10.48550/arxiv."):
                ids["arxiv"] = normalize_arxiv(nd.split("10.48550/arxiv.", 1)[1])
        # 1) Europe PMC JATS XML (PMC OA subset).
        epmc = (paper or {}).get("epmc") or {}
        src_id = None
        if ids.get("pmcid"):
            src_id = ("PMC", ids["pmcid"])
        elif epmc.get("source") and epmc.get("id"):
            src_id = (epmc["source"], epmc["id"])
        else:
            probe = None
            if args.doi:
                probe = f'DOI:"{normalize_doi(args.doi)}"'
            elif args.pmid:
                probe = f"EXT_ID:{args.pmid} AND SRC:MED"
            if probe:
                papers, e = apis.europepmc_search(cache, probe, limit=1, fresh=args.fresh)
                if e:
                    result["degraded"].append(f"europepmc: {e}")
                elif papers:
                    ep = papers[0].get("epmc") or {}
                    if ep.get("source") and ep.get("id"):
                        src_id = (ep["source"], ep["id"])
                    ids.setdefault("pmcid", papers[0]["ids"].get("pmcid"))
        if src_id:
            xml_text, e = apis.europepmc_fulltext_xml(cache, src_id[0], src_id[1], fresh=args.fresh)
            if e:
                result["degraded"].append(f"epmc-xml: {e}")
            elif xml_text:
                result["mode"] = "xml"
                if args.save:
                    dest = os.path.join(args.save, f"{(ids.get('pmcid') or src_id[1])}.xml")
                    os.makedirs(args.save, exist_ok=True)
                    with open(dest, "w", encoding="utf-8") as f:
                        f.write(xml_text)
                    result["path"] = dest
                else:
                    result["xml_chars"] = len(xml_text)
                _write_json(args.out, result)
                return 0
        # 2) arXiv PDF.
        if ids.get("arxiv"):
            url = f"https://arxiv.org/pdf/{ids['arxiv']}"
            if args.save:
                dest = os.path.join(args.save, f"arxiv-{ids['arxiv'].replace('/', '_')}.pdf")
                ok, e = _download(url, dest)
                if ok:
                    result.update({"mode": "pdf-download", "path": dest, "license": "arXiv"})
                    _write_json(args.out, result)
                    return 0
                result["degraded"].append(f"arxiv-pdf: {e}")
            else:
                result.update({"mode": "pdf-download", "url": url, "license": "arXiv"})
                _write_json(args.out, result)
                return 0
        # 3) Unpaywall best OA location.
        if args.doi:
            oa, e = apis.unpaywall_oa(cache, args.doi, fresh=args.fresh)
            if e:
                result["degraded"].append(f"unpaywall: {e}")
            elif oa and oa.get("pdf_url"):
                result["license"] = oa.get("license")
                if args.save:
                    safe = re.sub(r"[^A-Za-z0-9._-]", "_", normalize_doi(args.doi) or "paper")
                    dest = os.path.join(args.save, f"{safe}.pdf")
                    ok, de = _download(oa["pdf_url"], dest)
                    if ok:
                        result.update({"mode": "pdf-download", "path": dest})
                        _write_json(args.out, result)
                        return 0
                    result["degraded"].append(f"oa-pdf: {de}")
                else:
                    result.update({"mode": "pdf-download", "url": oa["pdf_url"]})
                    _write_json(args.out, result)
                    return 0
        _write_json(args.out, result)
        return 1
    finally:
        cache.close()


# --------------------------------------------------------------------------
# cites / refs
# --------------------------------------------------------------------------

def _resolve_openalex_id(cache, args) -> str | None:
    if args.openalex:
        return args.openalex
    if args.doi:
        p, _ = apis.openalex_lookup(cache, doi=args.doi)
        if p:
            return p["ids"].get("openalex")
    return None


def cmd_cites(args) -> int:
    cache = http.Cache()
    try:
        oid = _resolve_openalex_id(cache, args)
        if not oid:
            http.eprint("could not resolve an OpenAlex id")
            return 1
        papers, degraded = apis.openalex_cites(cache, oid, limit=args.limit, fresh=args.fresh)
        _write_json(args.out, {"of": oid, "count": len(papers),
                               **({"degraded": degraded} if degraded else {}),
                               "papers": papers})
        return 0
    finally:
        cache.close()


def cmd_refs(args) -> int:
    cache = http.Cache()
    try:
        oid = _resolve_openalex_id(cache, args)
        if not oid:
            http.eprint("could not resolve an OpenAlex id")
            return 1
        papers, degraded = apis.openalex_refs(cache, oid, fresh=args.fresh)
        _write_json(args.out, {"of": oid, "count": len(papers),
                               **({"degraded": degraded} if degraded else {}),
                               "papers": papers})
        return 0
    finally:
        cache.close()


# --------------------------------------------------------------------------
# dedup (shards -> candidates)
# --------------------------------------------------------------------------

def cmd_dedup(args) -> int:
    all_papers = []
    for path in args.infiles:
        try:
            all_papers.extend(_iter_batch_entries(path))
        except (OSError, ValueError, json.JSONDecodeError) as e:
            http.eprint(f"skipping {path}: {e}")
    unique = dedup_papers(all_papers)
    _write_json(args.out, {
        "executed_at": _now(),
        "dedup": {"input": len(all_papers), "unique": len(unique)},
        "papers": unique,
    })
    return 0


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def _bibtex_key(p: dict, seen: set) -> str:
    first = (p.get("authors") or ["anon"])[0] or "anon"
    last = first.split()[-1].lower() if first.split() else "anon"
    last = re.sub(r"[^a-z0-9]", "", last) or "anon"
    word = next((w.lower() for w in re.findall(r"[A-Za-z]{4,}", p.get("title") or "")), "work")
    base = f"{last}{p.get('year') or 'nd'}{word}"
    key, i = base, 2
    while key in seen:
        key, i = f"{base}{i}", i + 1
    seen.add(key)
    return key


def _bibtex_escape(s: str) -> str:
    return s.replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")


def cmd_export(args) -> int:
    papers = _iter_batch_entries(args.infile)
    fmt = args.format
    out_lines: list[str] = []
    if fmt == "csl-json":
        csl = []
        for p in papers:
            csl.append({
                "id": p.get("id"),
                "type": "article-journal" if (p.get("type") or "").startswith(("journal", "article")) else "document",
                "title": p.get("title"),
                "author": [{"literal": a} for a in p.get("authors") or []],
                "issued": {"date-parts": [[p["year"]]]} if p.get("year") else None,
                "container-title": p.get("venue"),
                "DOI": (p.get("ids") or {}).get("doi"),
                "URL": (p.get("urls") or {}).get("landing"),
            })
        text = json.dumps([{k: v for k, v in e.items() if v is not None} for e in csl],
                          indent=1, ensure_ascii=False)
    elif fmt == "bibtex":
        seen: set = set()
        for p in papers:
            entry_type = "article" if (p.get("type") or "").startswith(("journal", "article")) else "misc"
            fields = {
                "title": _bibtex_escape(p.get("title") or ""),
                "author": " and ".join(p.get("authors") or []),
                "year": str(p.get("year") or ""),
                "journal": _bibtex_escape(p.get("venue") or ""),
                "doi": (p.get("ids") or {}).get("doi") or "",
                "url": (p.get("urls") or {}).get("landing") or "",
                "eprint": (p.get("ids") or {}).get("arxiv") or "",
            }
            body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
            out_lines.append(f"@{entry_type}{{{_bibtex_key(p, seen)},\n{body}\n}}\n")
        text = "\n".join(out_lines)
    elif fmt == "ris":
        for p in papers:
            out_lines.append("TY  - JOUR" if (p.get("type") or "").startswith(("journal", "article")) else "TY  - GEN")
            out_lines.append(f"TI  - {p.get('title') or ''}")
            for a in p.get("authors") or []:
                out_lines.append(f"AU  - {a}")
            if p.get("year"):
                out_lines.append(f"PY  - {p['year']}")
            if p.get("venue"):
                out_lines.append(f"JO  - {p['venue']}")
            doi = (p.get("ids") or {}).get("doi")
            if doi:
                out_lines.append(f"DO  - {doi}")
            url = (p.get("urls") or {}).get("landing")
            if url:
                out_lines.append(f"UR  - {url}")
            out_lines.append("ER  - \n")
        text = "\n".join(out_lines)
    elif fmt == "csv":
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["id", "doi", "title", "authors", "year", "venue", "type",
                    "cited_by_count", "is_oa", "verification", "retraction"])
        for p in papers:
            w.writerow([
                p.get("id"), (p.get("ids") or {}).get("doi"), p.get("title"),
                "; ".join(p.get("authors") or []), p.get("year"), p.get("venue"),
                p.get("type"), p.get("cited_by_count"), p.get("is_oa"),
                (p.get("verification") or {}).get("status"),
                (p.get("retraction") or {}).get("status"),
            ])
        text = buf.getvalue()
    else:
        http.eprint(f"unknown format {fmt}")
        return 2
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


# --------------------------------------------------------------------------
# audit-report (G3 gate)
# --------------------------------------------------------------------------

_MARKER = re.compile(r"\[@([^\]\s{}]+)\](?:\{anchor=([^}]*)\})?")
_DEICTIC = re.compile(
    r"\b(recently|last year|this year|the latest|in recent (?:months|years)|"
    r"to date|currently|as of (?:now|today))\b", re.IGNORECASE)
_YEAR_NEAR = re.compile(r"\((\d{4})[a-z]?\)|,\s*(\d{4})[a-z]?\)")


def _corpus_index(papers: list[dict]) -> dict:
    idx = {}
    for p in papers:
        if p.get("id"):
            idx[p["id"]] = p
        for k, v in (p.get("ids") or {}).items():
            if v:
                idx[f"{k}:{v}"] = p
    return idx


def cmd_audit_report(args) -> int:
    with open(args.report, encoding="utf-8") as f:
        lines = f.readlines()
    papers = _iter_batch_entries(args.corpus)
    index = _corpus_index(papers)
    cache = http.Cache()
    citations = []
    deictic_flags = []
    year_mismatches = []
    fresh_retraction: dict = {}
    try:
        _maybe_load_retractions(cache, quiet=True)
        for lineno, line in enumerate(lines, 1):
            for m in _DEICTIC.finditer(line):
                deictic_flags.append({"line": lineno, "phrase": m.group(0)})
            for m in _MARKER.finditer(line):
                cid, anchor_raw = m.group(1), m.group(2)
                paper = index.get(cid)
                in_corpus = paper is not None
                vstatus = ((paper or {}).get("verification") or {}).get("status", "unverified")
                doi = ((paper or {}).get("ids") or {}).get("doi")
                if doi:
                    if doi not in fresh_retraction:
                        fresh_retraction[doi] = check_retraction(cache, doi)
                    retr = fresh_retraction[doi]["status"]
                else:
                    retr = ((paper or {}).get("retraction") or {}).get("status", "unknown")
                anchor_type = "none"
                if anchor_raw:
                    for prefix, name in (("quote:", "quote"), ("page:", "page"), ("section:", "section")):
                        if anchor_raw.strip().startswith(prefix):
                            anchor_type = name
                            break
                    else:
                        anchor_type = "none" if anchor_raw.strip() == "none" else "malformed"
                # Temporal: in-text year near the marker vs corpus year.
                if paper and paper.get("year"):
                    for ym in _YEAR_NEAR.finditer(line[max(0, m.start() - 80): m.start()]):
                        y = int(ym.group(1) or ym.group(2))
                        if abs(y - paper["year"]) > 1:
                            year_mismatches.append({"line": lineno, "corpus_id": cid,
                                                    "in_text_year": y, "corpus_year": paper["year"]})
                citations.append({
                    "line": lineno, "corpus_id": cid, "in_corpus": in_corpus,
                    "verification_status": vstatus if in_corpus else None,
                    "retraction_status": retr if in_corpus else None,
                    "anchor": anchor_type,
                })
    finally:
        cache.close()

    uncited = [c for c in citations if not c["in_corpus"]]
    unverified = [c for c in citations if c["in_corpus"] and c["verification_status"] not in ("verified", "single_index")]
    retracted = [c for c in citations if c["in_corpus"] and c["retraction_status"] in ("retracted", "withdrawal")]
    flagged = [c for c in citations if c["in_corpus"] and c["retraction_status"] in ("correction", "eoc")]
    report = {
        "report": args.report,
        "corpus": args.corpus,
        "executed_at": _now(),
        "summary": {
            "total_markers": len(citations),
            "unique_ids": len({c["corpus_id"] for c in citations}),
            "not_in_corpus": len(uncited),
            "unverified": len(unverified),
            "retracted": len(retracted),
            "correction_or_eoc": len(flagged),
            "anchored": sum(1 for c in citations if c["anchor"] in ("quote", "page", "section")),
        },
        "failures": {
            "not_in_corpus": uncited[:50],
            "unverified": unverified[:50],
            "retracted": retracted[:50],
        },
        "warnings": {
            "correction_or_eoc": flagged[:50],
            "year_mismatches": year_mismatches[:50],
            "deictic_phrases": deictic_flags[:50],
        },
        "gate": "fail" if (uncited or unverified or retracted) else "pass",
    }
    _write_json(args.out, report)
    return 1 if report["gate"] == "fail" else 0


# --------------------------------------------------------------------------
# doctor / cache
# --------------------------------------------------------------------------

def cmd_doctor(args) -> int:
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("python", sys.version_info >= (3, 9), f"{sys.version.split()[0]}")
    check("IR_MAILTO", bool(http.mailto()),
          http.mailto() or "unset — polite pools throttled; Unpaywall DISABLED")
    check("NCBI_API_KEY", True, "set (10 rps)" if os.environ.get("NCBI_API_KEY") else "unset (3 rps — fine)")
    check("S2_API_KEY", True, "set — Semantic Scholar enabled" if os.environ.get("S2_API_KEY") else "unset — S2 disabled (optional)")
    try:
        cache = http.Cache()
        check("cache", True, cache.stats()["path"])
        rw = cache.meta_get("retractionwatch_loaded_at")
        check("retraction_db", bool(rw), rw or "not loaded — run: scholar.py cache load-retractions")
        r = http.fetch(cache, "https://api.openalex.org/works?per-page=1"
                       + (f"&mailto={urllib.parse.quote(http.mailto())}" if http.mailto() else ""),
                       ttl_class="search", fresh=True)
        check("network:openalex", r.ok, r.degraded_reason or f"http {r.status}")
        cache.close()
    except Exception as e:  # noqa: BLE001
        check("cache", False, str(e))
    hard_fail = any(not c["ok"] for c in checks if c["check"] in ("python", "cache", "network:openalex"))
    payload = {"ok": not hard_fail, "checks": checks}
    if args.json:
        _write_json(None, payload)
    else:
        for c in checks:
            print(f"[{'ok' if c['ok'] else '!!'}] {c['check']}: {c['detail']}")
        print("doctor:", "ok" if not hard_fail else "PROBLEMS FOUND")
    return 0 if not hard_fail else 1


def _maybe_load_retractions(cache, quiet=False) -> None:
    """Ensure the Retraction Watch DB is present-ish; never blocks the caller
    on failure."""
    if not apis.retraction_watch_stale(cache):
        return
    if os.environ.get("IR_SKIP_RETRACTIONWATCH") == "1":
        return
    if not quiet:
        http.eprint("loading Retraction Watch database (first run / stale)...")
    n, err = apis.load_retraction_watch(cache)
    if err and not quiet:
        http.eprint(f"warning: {err}")
    elif not quiet:
        http.eprint(f"loaded {n} retraction records")


def cmd_cache(args) -> int:
    cache = http.Cache()
    try:
        if args.action == "stats":
            _write_json(None, cache.stats())
        elif args.action == "path":
            print(cache.path)
        elif args.action == "clear":
            cache.clear()
            print("http cache cleared")
        elif args.action == "load-retractions":
            n, err = apis.load_retraction_watch(cache)
            if err:
                http.eprint(err)
                return 1
            print(f"loaded {n} retraction records")
        return 0
    finally:
        cache.close()


# --------------------------------------------------------------------------
# Ideation: topic trends, gap metrics, gap scoring
# --------------------------------------------------------------------------

def _default_window(args) -> tuple[int, int]:
    year_to = args.year_to or int(time.strftime("%Y", time.gmtime()))
    year_from = args.year_from or year_to - 11
    return year_from, year_to


def cmd_count(args) -> int:
    """Total OpenAlex hit count for a query — the cheap thinness probe."""
    cache = http.Cache()
    try:
        extra = f"publication_year:{args.year_from}-{args.year_to}" \
            if args.year_from and args.year_to else None
        n, degraded = metrics.openalex_count(cache, args.query, extra_filter=extra,
                                             fresh=args.fresh)
        _write_json(args.out, {"query": args.query, "count": n,
                               **({"degraded": degraded} if degraded else {})})
        return 0 if n is not None else 1
    finally:
        cache.close()


def cmd_topic_trends(args) -> int:
    cache = http.Cache()
    try:
        year_from, year_to = _default_window(args)
        base, base_degraded = metrics.base_yearly(cache, year_from, year_to,
                                                  fresh=args.fresh)
        profile = metrics.query_profile(cache, args.query, year_from, year_to,
                                        base_series=base if not base_degraded else None,
                                        fresh=args.fresh)
        topics, _ = metrics.openalex_topic_shares(
            cache, args.query,
            extra_filter=f"publication_year:{year_from}-{year_to}", fresh=args.fresh)
        matched, _ = metrics.openalex_topics_lookup(cache, args.query, fresh=args.fresh)
        _ledger_append(args.ledger, {"event": "topic-trends", "query": args.query,
                                     "total_works": profile.get("total_works")})
        _flush_request_counts(args.ledger)
        _write_json(args.out, {
            "query": args.query,
            "executed_at": _now(),
            "profile": profile,
            "diversity": {
                "rao_stirling": metrics.rao_stirling(topics) if topics else None,
                "top_topics": [{"id": t["id"], "name": t["name"], "share": t["share"]}
                               for t in topics[:10]],
            },
            "matched_topics": matched,
        })
        return 0
    finally:
        cache.close()


def _load_gaps(path: str) -> list[dict]:
    data = metrics.load_json(path)
    gaps = data.get("gaps") if isinstance(data, dict) else data
    return [g for g in (gaps or []) if isinstance(g, dict)]


def cmd_gap_metrics(args) -> int:
    cache = http.Cache()
    try:
        gaps = _load_gaps(args.gaps)
        if not gaps:
            http.eprint(f"no gaps found in {args.gaps}")
            return 2
        year_from, year_to = _default_window(args)
        corpus_by_id = {}
        if args.corpus:
            for p in (metrics.load_json(args.corpus).get("papers") or []):
                if p.get("id"):
                    corpus_by_id[p["id"]] = p
        base, base_degraded = metrics.base_yearly(cache, year_from, year_to,
                                                  fresh=args.fresh)
        out = []
        for gap in gaps:
            m = metrics.compute_gap_metrics(
                cache, gap, year_from, year_to,
                base_series=base if not base_degraded else None,
                corpus_by_id=corpus_by_id, fresh=args.fresh)
            out.append(m)
            _ledger_append(args.ledger, {"event": "gap-metrics", "gap_id": m["gap_id"],
                                         "total_works": m["crowding"]["total_works"]})
        _flush_request_counts(args.ledger)
        _write_json(args.out, {"executed_at": _now(), "window": [year_from, year_to],
                               "gap_count": len(out),
                               **({"base_degraded": base_degraded} if base_degraded else {}),
                               "metrics": out})
        return 0
    finally:
        cache.close()


def _as_gap_map(path: str | None) -> dict:
    """Accept {gid: {...}} or {"gaps": {gid: {...}}} or [{"gap_id": ...}]."""
    if not path:
        return {}
    data = metrics.load_json(path)
    if isinstance(data, dict) and isinstance(data.get("gaps"), (dict, list)):
        data = data["gaps"]
    if isinstance(data, list):
        return {g.get("gap_id"): g for g in data if isinstance(g, dict)}
    return data if isinstance(data, dict) else {}


_SCORE_COLUMNS = ("novelty", "importance", "answerability", "actionability",
                  "momentum", "headroom", "corroboration", "bridge",
                  "review_deficit", "accessibility")


def _leaderboard_md(ranked: list[dict], weights: dict, window) -> str:
    lines = [
        "# Ranked research gaps",
        "",
        f"Window {window[0]}–{window[1]}. GapScore = 100 × weighted geometric mean of "
        "the sub-scores (a near-zero core criterion cannot be compensated away). "
        "Quantitative sub-scores are normalized **across this gap set** — they are "
        "relative, not absolute. `rank range` shows rank stability under ±25% "
        "one-at-a-time weight perturbation.",
        "",
        "Weights: " + ", ".join(f"{k} {v:.2f}" for k, v in weights.items()) + ".",
        "",
        "| # | Gap | Type | GapScore | Rank range | Panel agreement | Survival |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, g in enumerate(ranked, 1):
        rng = (f"{g.get('rank_min')}–{g.get('rank_max')}"
               if g.get("rank_min") is not None else "—")
        agree = g.get("panel_agreement")
        statement = (g.get("statement") or "")[:100]
        lines.append(f"| {i} | **{g['gap_id']}** {statement} | {g.get('type') or '—'} | "
                     f"{g['gap_score']} | {rng} | "
                     f"{agree if agree is not None else '—'} | {g['survival']} |")
    lines += ["", "## Scorecards", ""]
    for i, g in enumerate(ranked, 1):
        lines.append(f"### {i}. {g['gap_id']} — GapScore {g['gap_score']}")
        lines.append("")
        if g.get("statement"):
            lines.append(f"> {g['statement']}")
            lines.append("")
        subs = g.get("sub_scores") or {}
        cells = " | ".join(f"{subs[c]:.2f}" if subs.get(c) is not None else "—"
                           for c in _SCORE_COLUMNS)
        lines.append("| " + " | ".join(_SCORE_COLUMNS) + " |")
        lines.append("|" + "---|" * len(_SCORE_COLUMNS))
        lines.append("| " + cells + " |")
        lines.append("")
    excluded = [g for g in ranked if g.get("excluded")]
    if excluded:
        lines.append("## Refuted (excluded from ranking)")
        lines.append("")
        for g in excluded:
            lines.append(f"- **{g['gap_id']}** — {g.get('statement') or ''}")
        lines.append("")
    return "\n".join(lines) + "\n"


def cmd_score_gaps(args) -> int:
    data = metrics.load_json(args.metrics)
    metrics_list = data.get("metrics") or []
    if not metrics_list:
        http.eprint(f"no metrics found in {args.metrics}")
        return 2
    rubric = _as_gap_map(args.rubric)
    survival = _as_gap_map(args.survival)
    weights = metrics.load_json(args.weights) if args.weights else None
    if args.require_survival:
        missing = [m["gap_id"] for m in metrics_list
                   if not (survival.get(m["gap_id"]) or {}).get("verdict")]
        if missing:
            http.eprint(f"survival gate FAIL: no skeptic verdict for {missing}")
            return 1
    scored = metrics.composite_scores(metrics_list, rubric, survival, weights)

    by_id = {m["gap_id"]: m for m in metrics_list}
    rows = []
    for gid, res in scored["gaps"].items():
        m = by_id.get(gid) or {}
        rows.append({"gap_id": gid, "type": m.get("type"),
                     "statement": m.get("statement"), **res})
    active = sorted([r for r in rows if not r["excluded"]],
                    key=lambda r: (-r["gap_score"], r["gap_id"]))
    ranked = active + [r for r in rows if r["excluded"]]
    envelope = {"executed_at": _now(), "window": data.get("window"),
                "weights": scored["weights"], "ranked": ranked}
    _write_json(args.out, envelope)
    if args.leaderboard:
        os.makedirs(os.path.dirname(os.path.abspath(args.leaderboard)), exist_ok=True)
        with open(args.leaderboard, "w", encoding="utf-8") as f:
            f.write(_leaderboard_md(ranked, scored["weights"],
                                    data.get("window") or ["?", "?"]))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scholar.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--out", help="write JSON here instead of stdout")
        p.add_argument("--fresh", action="store_true", help="bypass the HTTP cache")

    p = sub.add_parser("search", help="multi-source search, merged + deduped")
    p.add_argument("query")
    p.add_argument("--sources", default=",".join(apis.DEFAULT_SEARCH_SOURCES))
    p.add_argument("--limit", type=int, default=25, help="per-source result cap")
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    p.add_argument("--ledger", help="append per-source query+hit JSONL lines here")
    common(p)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("lookup", help="resolve one work by identifier")
    p.add_argument("--doi")
    p.add_argument("--arxiv")
    p.add_argument("--pmid")
    p.add_argument("--openalex")
    common(p)
    p.set_defaults(fn=cmd_lookup)

    p = sub.add_parser("verify", help="verify one reference")
    p.add_argument("--doi")
    p.add_argument("--arxiv")
    p.add_argument("--pmid")
    p.add_argument("--title")
    p.add_argument("--year", type=int)
    common(p)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("verify-batch", help="verify every corpus/refs entry")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--strict", action="store_true",
                   help="exit 1 on any not_found or retracted entry")
    common(p)
    p.set_defaults(fn=cmd_verify_batch)

    p = sub.add_parser("fulltext", help="resolve OA full text (XML/PDF)")
    p.add_argument("--doi")
    p.add_argument("--pmid")
    p.add_argument("--save", help="directory to save the XML/PDF into")
    common(p)
    p.set_defaults(fn=cmd_fulltext)

    for name, fn in (("cites", cmd_cites), ("refs", cmd_refs)):
        p = sub.add_parser(name, help=f"citation graph: {name}")
        p.add_argument("--doi")
        p.add_argument("--openalex")
        if name == "cites":
            p.add_argument("--limit", type=int, default=50)
        common(p)
        p.set_defaults(fn=fn)

    p = sub.add_parser("dedup", help="merge searcher shards")
    p.add_argument("--in", dest="infiles", nargs="+", required=True)
    common(p)
    p.set_defaults(fn=cmd_dedup)

    p = sub.add_parser("ingest", help="resolve a file of DOIs/arXiv ids (one per line)")
    p.add_argument("--in", dest="infile", required=True)
    common(p)
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("export", help="corpus -> bibtex|ris|csv|csl-json")
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--format", required=True, choices=["bibtex", "ris", "csv", "csl-json"])
    p.add_argument("--out")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("audit-report", help="G3 gate: verify a report's citation markers")
    p.add_argument("report")
    p.add_argument("--corpus", required=True)
    common(p)
    p.set_defaults(fn=cmd_audit_report)

    p = sub.add_parser("count", help="total OpenAlex hits for a query (thinness probe)")
    p.add_argument("query")
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    common(p)
    p.set_defaults(fn=cmd_count)

    p = sub.add_parser("topic-trends", help="trend/burst/diversity profile of a subject")
    p.add_argument("query")
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    p.add_argument("--ledger", help="append trend events here (JSONL)")
    common(p)
    p.set_defaults(fn=cmd_topic_trends)

    p = sub.add_parser("gap-metrics", help="deterministic bibliometrics for mined gaps")
    p.add_argument("--gaps", required=True, help="gaps.json from the gap-mining phase")
    p.add_argument("--corpus", help="corpus.json to join supporting-paper metadata")
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    p.add_argument("--ledger", help="append per-gap events here (JSONL)")
    common(p)
    p.set_defaults(fn=cmd_gap_metrics)

    p = sub.add_parser("score-gaps", help="rank gaps: normalize, weight, leaderboard")
    p.add_argument("--metrics", required=True, help="gap-metrics.json")
    p.add_argument("--rubric", help="judge-panel scores per gap (1-5 axes)")
    p.add_argument("--survival", help="gap-skeptic verdicts per gap")
    p.add_argument("--require-survival", action="store_true",
                   help="G4 gate: exit 1 if any gap lacks a skeptic verdict")
    p.add_argument("--weights", help="JSON weight overrides")
    p.add_argument("--leaderboard", help="write a markdown leaderboard here")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_score_gaps)

    p = sub.add_parser("doctor", help="environment preflight")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("cache", help="cache maintenance")
    p.add_argument("action", choices=["stats", "clear", "path", "load-retractions"])
    p.set_defaults(fn=cmd_cache)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
