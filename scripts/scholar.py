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
  doctor        environment preflight
  cache         stats | clear | path | load-retractions
  venue-sample  fetch recent exemplar papers from a target venue (v2)
  style-profile deterministic style profile from exemplars (v2)
  originality   verbatim-overlap screen of a draft vs a corpus (v2)
  datasets      search | card | splits | fitness | vet — dataset discovery (v2)
  emit-prisma   PRISMA flow diagram (DOT/SVG) from counts (v2)
  readiness     G4 submission-readiness gate over a manuscript (v2)
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
        rh = http.fetch(cache, "https://huggingface.co/api/datasets?limit=1",
                        ttl_class="dataset", fresh=True)
        check("network:huggingface", rh.ok, rh.degraded_reason or f"http {rh.status}")
        cache.close()
    except Exception as e:  # noqa: BLE001
        check("cache", False, str(e))
    # Papers With Code is defunct (302-dead); assert so nobody re-adds it.
    check("paperswithcode", True, "excluded (API defunct — SOTA via HF card paperswithcode_id)")
    if getattr(args, "check_figures", False):
        _check_figure_runtime(check)
    if getattr(args, "check_standards", False):
        _check_standards(check)
    hard_fail = any(not c["ok"] for c in checks if c["check"] in ("python", "cache", "network:openalex"))
    payload = {"ok": not hard_fail, "checks": checks}
    if args.json:
        _write_json(None, payload)
    else:
        for c in checks:
            print(f"[{'ok' if c['ok'] else '!!'}] {c['check']}: {c['detail']}")
        print("doctor:", "ok" if not hard_fail else "PROBLEMS FOUND")
    return 0 if not hard_fail else 1


def _check_figure_runtime(check) -> None:
    """Report which figure-rendering packages are available (all optional)."""
    import importlib.util as _u
    for pkg in ("matplotlib", "numpy", "PIL"):
        present = _u.find_spec(pkg) is not None
        check(f"figure:{pkg}", True,
              "available" if present else f"MISSING — figures default to spec+code+caption; `pip install {pkg}` to render")
    import shutil
    check("figure:graphviz", True,
          "dot available" if shutil.which("dot") else "dot MISSING — PRISMA/schematic render deferred (DOT text still emitted)")


def _check_standards(check) -> None:
    """HEAD-verify each checklist's canonical_source_url is reachable."""
    import ssl as _ssl
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills",
                        "intensive-research", "references", "checklists")
    if not os.path.isdir(base):
        check("standards:bank", False, "checklists dir missing")
        return
    urls = set()
    for fn in os.listdir(base):
        if fn.endswith(".json"):
            for it in json.load(open(os.path.join(base, fn))).get("items", []):
                if it.get("canonical_source_url"):
                    urls.add(it["canonical_source_url"])
    bad = []
    for u in sorted(urls):
        try:
            req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": http._user_agent()})
            with urllib.request.urlopen(req, timeout=20, context=_ssl.create_default_context()) as resp:
                if resp.status >= 400:
                    bad.append(f"{u} ({resp.status})")
        except urllib.error.HTTPError as e:
            if e.code >= 400 and e.code not in (403, 405):  # some publishers block HEAD
                bad.append(f"{u} ({e.code})")
        except Exception:  # noqa: BLE001
            pass  # network flake is not a standards failure
    check("standards:urls", not bad, f"{len(urls)} checklist source URLs; broken: {bad or 'none'}")


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


# ==========================================================================
# v2 — venue style-learning
# ==========================================================================

def cmd_venue_sample(args) -> int:
    cache = http.Cache()
    manifest = {"venue": args.venue, "issn": args.issn, "resolved": None,
                "executed_at": _now(), "exemplars": [], "degraded": []}
    try:
        works, source = [], None
        # 1. Resolve venue via OpenAlex sources.
        sources, err = apis.openalex_sources_search(cache, args.venue, source_type=args.type, fresh=args.fresh)
        if err:
            manifest["degraded"].append(f"openalex-sources: {err}")
        if sources:
            source = sources[0]
            manifest["resolved"] = source
            works, e = apis.openalex_works_by_source(
                cache, source["id"], since=args.since, n=args.n, oa_only=args.oa_only, fresh=args.fresh)
            if e:
                manifest["degraded"].append(f"openalex-works: {e}")
        # 2. Crossref-by-ISSN fallback.
        if not works and (args.issn or (source and source.get("issn_l"))):
            issn = args.issn or source.get("issn_l")
            works, e = apis.crossref_journal_works(cache, issn, n=args.n, fresh=args.fresh)
            if e:
                manifest["degraded"].append(f"crossref-journal: {e}")
        # 3. DBLP venue fallback (CS venues without ISSN).
        if not works:
            works, e = apis.dblp_venue_works(cache, args.venue, n=args.n, fresh=args.fresh)
            if e:
                manifest["degraded"].append(f"dblp-venue: {e}")
        # For each exemplar, try to obtain structured full text (JATS) for style.
        for w in works[:args.n]:
            abstract = w.get("abstract")
            doi = (w.get("ids") or {}).get("doi")
            abstract_source = "openalex" if abstract else None
            # Backfill abstract via Crossref when OpenAlex stripped it (common for
            # closed Springer/Elsevier venues) so the style profile has real signal.
            if not abstract and doi:
                cr, _ = apis.crossref_lookup(cache, doi, fresh=args.fresh)
                if cr and cr.get("abstract"):
                    abstract, abstract_source = cr["abstract"], "crossref"
            ex = {"id": w.get("id"), "title": w.get("title"), "year": w.get("year"),
                  "doi": doi, "abstract": abstract, "abstract_source": abstract_source,
                  "is_oa": w.get("is_oa"), "record_of": "preprint" if (w.get("venue") == "arXiv") else "version-of-record",
                  "fulltext_path": None, "fulltext_source": None, "reference_count": None}
            if args.save and doi:
                jats = _try_jats(cache, w, args.save, args.fresh)
                if jats:
                    ex["fulltext_path"], ex["fulltext_source"] = jats, "europepmc-jats"
            manifest["exemplars"].append(ex)
        manifest["oa_fraction"] = round(
            sum(1 for e in manifest["exemplars"] if e["is_oa"]) / max(1, len(manifest["exemplars"])), 2)
        _write_json(args.out, manifest)
        return 0 if manifest["exemplars"] else 1
    finally:
        cache.close()


def _try_jats(cache, paper, save_dir, fresh):
    """Best-effort EuropePMC JATS XML for one paper (structured text for style)."""
    doi = (paper.get("ids") or {}).get("doi")
    if not doi:
        return None
    papers, e = apis.europepmc_search(cache, f'DOI:"{normalize_doi(doi)}"', limit=1, fresh=fresh)
    if e or not papers:
        return None
    ep = papers[0].get("epmc") or {}
    if not (ep.get("source") and ep.get("id")):
        return None
    xml_text, e = apis.europepmc_fulltext_xml(cache, ep["source"], ep["id"], fresh=fresh)
    if e or not xml_text:
        return None
    os.makedirs(save_dir, exist_ok=True)
    dest = os.path.join(save_dir, f"{ep['id']}.xml")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(xml_text)
    return dest


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_HEDGES = frozenset("may might could suggest suggests suggested appear appears likely possibly "
                    "perhaps potential potentially seem seems relatively somewhat arguably".split())
_BOOSTERS = frozenset("clearly obviously certainly definitely undoubtedly evidently "
                      "substantially markedly dramatically significantly strongly".split())
_STOPWORDS = frozenset(
    "the a an and or of to in for on with by is are was were be been being this that these those "
    "we our it its as at from we results method methods using used based our their which have has "
    "not can will more most than then also into such between both each other more paper study".split())


def _sentences(text):
    return [s for s in _SENT_SPLIT.split(text or "") if s.strip()]


def _jats_sections(xml_text):
    """Return [(title, text)] top-level sections from a JATS body."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    body = root.find(".//{*}body") or root.find(".//body")
    if body is None:
        return []
    out = []
    for sec in body.findall("{*}sec") or body.findall("sec"):
        title_el = sec.find("{*}title") or sec.find("title")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        text = " ".join(" ".join(sec.itertext()).split())
        out.append((title, text))
    return out


def cmd_style_profile(args) -> int:
    manifest = json.load(open(args.manifest, encoding="utf-8"))
    exemplars = manifest.get("exemplars", [])
    texts, sec_titles, all_sentences, ref_counts = [], [], [], []
    fulltext_used = 0
    for ex in exemplars:
        txt = ex.get("abstract") or ""
        if ex.get("fulltext_path") and os.path.exists(ex["fulltext_path"]):
            xml = open(ex["fulltext_path"], encoding="utf-8").read()
            secs = _jats_sections(xml)
            if secs:
                fulltext_used += 1
                sec_titles.append([t.lower() for t, _ in secs if t])
                txt = " ".join(t for _, t in secs)
        texts.append(txt)
        all_sentences.extend(_sentences(txt))
        if ex.get("reference_count"):
            ref_counts.append(ex["reference_count"])

    sent_lens = [len(_WORD.findall(s)) for s in all_sentences if s.strip()]
    words = [w.lower() for t in texts for w in _WORD.findall(t)]
    n_words = max(1, len(words))
    hedge_n = sum(1 for w in words if w in _HEDGES)
    boost_n = sum(1 for w in words if w in _BOOSTERS)
    # Terminology: content unigrams present in >=2 exemplars (generic-vocab guard).
    from collections import Counter
    per_ex_terms = []
    for t in texts:
        per_ex_terms.append(set(w.lower() for w in _WORD.findall(t)
                                if w.lower() not in _STOPWORDS and len(w) > 3))
    term_doc_freq = Counter()
    for s in per_ex_terms:
        term_doc_freq.update(s)
    shared_terms = [t for t, c in term_doc_freq.most_common(60) if c >= 2][:25]

    n_full = fulltext_used
    confidence = "high" if n_full >= 5 else ("med" if n_full >= 3 else "low")
    # Common section sequence (from full-text exemplars only).
    common_sections = []
    if sec_titles:
        seq_counter = Counter()
        for seq in sec_titles:
            seq_counter.update(seq)
        common_sections = [s for s, c in seq_counter.most_common(12)]

    profile = {
        "venue": {"name": manifest.get("venue"),
                  "openalex_source_id": (manifest.get("resolved") or {}).get("id"),
                  "issn_l": (manifest.get("resolved") or {}).get("issn_l"),
                  "type": (manifest.get("resolved") or {}).get("type"),
                  "publisher": (manifest.get("resolved") or {}).get("publisher")},
        "sample": {"n": len(exemplars), "n_fulltext": n_full,
                   "oa_fraction": manifest.get("oa_fraction"),
                   "confidence": confidence,
                   "coverage_note": f"{n_full}/{len(exemplars)} exemplars had structured full text; "
                                    "remaining features derived from abstracts + metadata"},
        "structure": {"common_section_titles": common_sections,
                      "structure_confidence": "jats" if sec_titles else "heuristic"},
        "sentences": {"mean_len_words": round(sum(sent_lens) / max(1, len(sent_lens)), 1) if sent_lens else None,
                      "n_sentences": len(sent_lens),
                      "provenance": "fulltext" if n_full else "abstract-only"},
        "voice_hedging": {"hedges_per_1000": round(1000 * hedge_n / n_words, 2),
                          "boosters_per_1000": round(1000 * boost_n / n_words, 2),
                          "note": "DESCRIPTIVE/ADVISORY ONLY — never a writer optimization target"},
        "terminology": {"shared_domain_terms": shared_terms,
                        "note": "unigrams in >=2 exemplars, stoplisted; generic vocabulary only"},
        "reference_style": {"median_ref_count": (sorted(ref_counts)[len(ref_counts) // 2]
                                                 if ref_counts else None)},
        "provenance": {"generated_at": _now(),
                       "exemplar_ids": [e.get("id") for e in exemplars],
                       "exemplar_dois": [e.get("doi") for e in exemplars],
                       "record_of": [e.get("record_of") for e in exemplars],
                       "guardrail": "structure + statistics only; contains no exemplar sentences"},
    }
    # Guardrail assertion: no long free-text strings leaked from source.
    leaked = _profile_has_long_strings(profile)
    profile["provenance"]["leak_check"] = "clean" if not leaked else f"WARNING: {leaked}"
    _write_json(args.out, profile)
    return 0 if confidence != "low" else 3  # advisory low-confidence signal


def _profile_has_long_strings(obj, limit_words=6):
    """Assert no field carries a >limit_words free-text run (plagiarism guard)."""
    def walk(o):
        if isinstance(o, str):
            if len(o.split()) > limit_words and " " in o and not o.startswith("http"):
                # Allow the known descriptive notes.
                if "ONLY" in o or "derived from" in o or "contains no" in o or "stoplisted" in o:
                    return None
                return o[:60]
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ("note", "coverage_note", "guardrail", "leak_check"):
                    continue
                hit = walk(v)
                if hit:
                    return hit
        elif isinstance(o, list):
            for v in o:
                hit = walk(v)
                if hit:
                    return hit
        return None
    return walk(obj)


def _tokens(text):
    return [w.lower() for w in _WORD.findall(text or "")]


def cmd_originality(args) -> int:
    draft = open(args.draft, encoding="utf-8").read()
    # Strip fenced quotes so legitimately quoted material is not flagged.
    draft_unquoted = re.sub(r'"[^"]*"', " ", draft)
    draft_unquoted = re.sub(r"^>.*$", " ", draft_unquoted, flags=re.M)
    draft_toks = _tokens(draft_unquoted)
    k = args.max_verbatim_words + 1

    sources_text, n_avail, n_total = [], 0, 0
    targets = []
    if os.path.isdir(args.against):
        targets = [os.path.join(args.against, f) for f in os.listdir(args.against)]
    elif args.against.endswith(".json"):
        man = json.load(open(args.against, encoding="utf-8"))
        for ex in man.get("exemplars", man.get("papers", [])):
            n_total += 1
            if ex.get("fulltext_path") and os.path.exists(ex["fulltext_path"]):
                sources_text.append(open(ex["fulltext_path"], encoding="utf-8").read())
                n_avail += 1
            elif ex.get("abstract"):
                sources_text.append(ex["abstract"])
                n_avail += 1
    for t in targets:
        if os.path.isfile(t):
            try:
                sources_text.append(open(t, encoding="utf-8").read())
                n_avail += 1
                n_total += 1
            except (OSError, UnicodeDecodeError):
                pass

    source_kgrams = set()
    for st in sources_text:
        toks = _tokens(st)
        for i in range(len(toks) - k + 1):
            source_kgrams.add(" ".join(toks[i:i + k]))

    flagged = []
    i = 0
    while i <= len(draft_toks) - k:
        gram = " ".join(draft_toks[i:i + k])
        if gram in source_kgrams:
            flagged.append(gram)
            i += k
        else:
            i += 1

    report = {
        "draft": args.draft, "against": args.against,
        "executed_at": _now(),
        "screen_type": "OA-corpus verbatim screen (NOT plagiarism clearance)",
        "coverage": {"n_sources_with_text": n_avail, "n_sources_total": n_total},
        "max_verbatim_words": args.max_verbatim_words,
        "flagged_spans": flagged[:50],
        "n_flagged": len(flagged),
        "gate": "fail" if flagged else "pass",
    }
    _write_json(args.out, report)
    return 1 if flagged else 0


# ==========================================================================
# v2 — dataset discovery + fitness (G-D)
# ==========================================================================

_PII_LEXICON = re.compile(
    r"\b(name|email|e-mail|dob|date.of.birth|ssn|social.security|address|phone|"
    r"patient|mrn|diagnosis|demographic|race|ethnicity|gender|geolocation|gps|ip.address)\b",
    re.IGNORECASE)
_ETHICS_KEYWORDS = re.compile(
    r"\b(consent|irb|ethics|institutional review|gdpr|hipaa|de-?identif|anonymiz|"
    r"data use agreement|dua)\b", re.IGNORECASE)
_SENSITIVE_MODALITIES = {"face", "facial", "medical", "clinical", "biometric",
                         "speech", "audio-speaker", "location-trace", "genomic", "mri", "eeg"}


def _dataset_pii_signal(rec):
    """Detect human-subjects/PII exposure from dataset CONTENT (amendment 5).
    Returns (triggered: bool, reasons: [str])."""
    reasons = []
    mods = {str(m).lower() for m in (rec.get("modalities") or [])}
    dom = (rec.get("domain") or "").lower()
    if mods & _SENSITIVE_MODALITIES or dom in ("biomedical", "clinical", "medical"):
        reasons.append(f"sensitive modality/domain: {sorted(mods & _SENSITIVE_MODALITIES) or dom}")
    feat_blob = " ".join(str(x) for x in (rec.get("features") or []))
    if _PII_LEXICON.search(feat_blob):
        reasons.append("PII-like feature names")
    card_blob = " ".join(str(rec.get(k) or "") for k in ("title", "description"))
    if _PII_LEXICON.search(card_blob):
        reasons.append("PII terms in card text")
    return (bool(reasons), reasons)


def _dataset_ethics_present(rec):
    blob = " ".join(str(rec.get(k) or "") for k in ("description",)) + " " + \
        json.dumps(rec.get("datasheet") or {})
    return bool(_ETHICS_KEYWORDS.search(blob)) or bool((rec.get("datasheet") or {}).get("has_ethics_statement"))


def _dataset_fitness_one(rec, spec):
    """Deterministic, explainable fitness. Gates 1/4/7 veto; others weighted."""
    crit = []
    gates_triggered = []

    def add(cid, name, score, evidence, gate=False, veto=False):
        crit.append({"id": cid, "name": name, "score": score, "evidence": evidence,
                     "gate": gate, "veto": veto})
        if gate and veto:
            gates_triggered.append(name)

    # Gate 1 — task/modality match.
    want_mod = {str(m).lower() for m in (spec.get("modality") and [spec["modality"]] or [])}
    have_mod = {str(m).lower() for m in (rec.get("modalities") or [])}
    have_task = {str(t).lower() for t in (rec.get("task_categories") or [])}
    want_task = (spec.get("task") or "").lower()
    mod_ok = (not want_mod) or (want_mod & have_mod) or not have_mod
    task_ok = (not want_task) or any(want_task in t for t in have_task) or not have_task
    veto1 = bool(want_mod and have_mod and not (want_mod & have_mod))
    add(1, "task_modality_match", 0 if veto1 else 100,
        f"want mod={want_mod or 'any'} task={want_task or 'any'}; have mod={have_mod} task={sorted(have_task)[:3]}",
        gate=True, veto=veto1)

    # 2 — size adequacy.
    n = (rec.get("size") or {}).get("num_instances")
    min_size = spec.get("min_size")
    if n is None:
        add(2, "size_adequacy", 50, "size unknown (null)")
    elif min_size and n < min_size:
        add(2, "size_adequacy", 25, f"{n} < required {min_size}")
    else:
        add(2, "size_adequacy", 100, f"{n} instances")

    # 3 — splits.
    splits = rec.get("splits") or []
    add(3, "splits", 100 if splits else 40,
        f"{[s.get('name') for s in splits]}" if splits else "no split metadata")

    # Gate 4 — license vs usage (unknown -> conditional, not veto).
    lic = rec.get("license") or {}
    usage = spec.get("usage") or {}
    nc = lic.get("noncommercial")
    nd = lic.get("noderivatives")
    veto4 = False
    if lic.get("is_open") is None and not lic.get("spdx_id") and not lic.get("name"):
        add(4, "license_usage_rights", 50, "license unknown/absent -> conditional (review needed)", gate=True)
    elif nc and usage.get("commercial"):
        veto4 = True
        add(4, "license_usage_rights", 0, "NonCommercial license vs commercial usage", gate=True, veto=True)
    elif nd and usage.get("derivatives"):
        veto4 = True
        add(4, "license_usage_rights", 0, "NoDerivatives license vs derivative usage", gate=True, veto=True)
    else:
        add(4, "license_usage_rights", 100, f"license={lic.get('spdx_id') or lic.get('name')} open={lic.get('is_open')}", gate=True)

    # 5 — provenance / citations.
    cites = (rec.get("citations") or {}).get("count")
    add(5, "provenance_citations", 100 if cites else 60,
        f"citations={cites}; creators={len(rec.get('creators') or [])}")

    # 6 — leakage/contamination (signal-and-flag; absent -> unverified).
    integ = rec.get("integrity") or {}
    if integ.get("known_leakage_flag") or integ.get("known_contamination_flag"):
        add(6, "leakage_contamination", 0, "known leakage/contamination flag")
    else:
        add(6, "leakage_contamination", 70, "no known-issue flag (unverified, not certified clean)")

    # Gate 7 — ethics / PII (keys off dataset CONTENT).
    pii, reasons = _dataset_pii_signal(rec)
    ethics_present = _dataset_ethics_present(rec)
    if pii and not ethics_present:
        add(7, "ethics_consent_pii", 0,
            f"human-subjects/PII signal ({'; '.join(reasons)}) with NO ethics/consent statement",
            gate=True, veto=True)
    elif pii and ethics_present:
        add(7, "ethics_consent_pii", 60,
            f"human-subjects/PII signal ({'; '.join(reasons)}); ethics statement present but UNVERIFIED", gate=True)
    else:
        add(7, "ethics_consent_pii", 100, "no human-subjects/PII signal detected", gate=True)

    # 8 — format/accessibility.
    right = (rec.get("access") or {}).get("right")
    add(8, "format_accessibility", 100 if right == "open" else (50 if right in ("gated", None) else 20),
        f"access={right}; formats={rec.get('formats')}")

    # 9 — datasheet availability.
    ds = rec.get("datasheet") or {}
    add(9, "datasheet_availability", 100 if (ds.get("croissant") or ds.get("datasheet_url")) else 40,
        "datasheet/croissant present" if (ds.get("croissant") or ds.get("datasheet_url")) else "no datasheet")

    weights = {2: 20, 3: 15, 5: 15, 6: 15, 8: 15, 9: 20}
    wsum = sum(weights.values())
    agg = round(sum(c["score"] * weights[c["id"]] for c in crit if c["id"] in weights) / wsum, 1)

    any_veto = bool(gates_triggered)
    license_unknown = any(c["id"] == 4 and c["score"] == 50 for c in crit)
    ethics_unverified = any(c["id"] == 7 and c["score"] == 60 for c in crit)
    if any_veto:
        verdict = "unfit"
    elif license_unknown or ethics_unverified:
        verdict = "conditional"
    else:
        verdict = "fit"

    return {"record_id": rec.get("record_id"), "title": rec.get("title"),
            "verdict": verdict, "aggregate_score": agg,
            "criteria": crit, "gates_triggered": gates_triggered,
            "review_flags": ([f"license unknown ({rec.get('source')} metadata sparse)"] if license_unknown else [])
                            + (["ethics statement present but unverified"] if ethics_unverified else [])}


def cmd_datasets(args) -> int:
    cache = http.Cache()
    try:
        if args.verb == "search":
            sources = [s.strip() for s in (args.sources or ",".join(apis.DEFAULT_DATASET_SOURCES)).split(",") if s.strip()]
            if "all" in sources:
                sources = list(apis.DATASET_SOURCES)
            unknown = [s for s in sources if s not in apis.DATASET_ADAPTERS]
            if unknown:
                http.eprint(f"unknown dataset sources: {unknown}; valid: {sorted(apis.DATASET_ADAPTERS)}")
                return 2
            per_source, all_recs = {}, []
            import concurrent.futures as _cf

            def run(source):
                c = http.Cache()
                try:
                    recs, err = apis.DATASET_ADAPTERS[source](c, args.q, limit=args.limit, fresh=args.fresh)
                    return source, recs, err
                finally:
                    c.close()
            with _cf.ThreadPoolExecutor(max_workers=min(len(sources), 6)) as ex:
                for source, recs, err in ex.map(run, sources):
                    per_source[source] = {"count": len(recs), "status": "degraded" if err else "ok",
                                          **({"error": err} if err else {})}
                    all_recs.extend(recs)
            collapsed = apis.collapse_dataset_mirrors(all_recs)
            _write_json(args.out, {"query": args.q, "executed_at": _now(),
                                   "per_source": per_source,
                                   "collapse": {"input": len(all_recs), "unique": len(collapsed)},
                                   "datasets": collapsed})
            return 0
        if args.verb == "card":
            source, _, native = args.target.partition(":")
            if source == "hf":
                card, err = apis.hf_dataset_card(cache, native, fresh=args.fresh)
                _write_json(args.out, {"card": card, "degraded": err})
                return 0 if card else 1
            http.eprint(f"card fetch not implemented for source {source}")
            return 2
        if args.verb == "splits":
            splits, err = apis.hf_dataset_splits(cache, args.target, fresh=args.fresh)
            _write_json(args.out, {"splits": splits, "degraded": err})
            return 0 if splits else 1
        if args.verb in ("fitness", "vet"):
            recs = _iter_dataset_records(args.candidates) if args.verb == "fitness" else None
            spec = json.load(open(args.spec, encoding="utf-8")) if args.spec else {}
            if args.verb == "vet":
                source, _, native = args.target.partition(":")
                one, err = (apis.hf_dataset_card(cache, native, fresh=args.fresh) if source == "hf" else (None, None))
                http.eprint("vet: use fitness with a candidates file for full scoring")
                return 0
            results = [_dataset_fitness_one(r, spec) for r in recs]
            counts = {}
            for r in results:
                counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
            _write_json(args.out, {"executed_at": _now(), "spec": spec, "counts": counts, "results": results})
            if args.gate:
                # G-D: fit passes; conditional needs sign-off; unfit blocks.
                if any(r["verdict"] == "unfit" for r in results):
                    return 1
                if any(r["verdict"] == "conditional" for r in results) and not args.signoff:
                    http.eprint("G-D: conditional datasets require --signoff (recorded human sign-off)")
                    return 1
            return 0
        return 2
    finally:
        cache.close()


def _iter_dataset_records(path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict) and "datasets" in data:
        return data["datasets"]
    if isinstance(data, list):
        return data
    raise ValueError("expected a datasets envelope or a list")


# ==========================================================================
# v2 — PRISMA-as-figure (deterministic DOT/SVG)
# ==========================================================================

def cmd_emit_prisma(args) -> int:
    counts = json.load(open(args.counts, encoding="utf-8")) if args.counts else {}
    identified = counts.get("identified", {})
    total_id = sum(identified.values()) if isinstance(identified, dict) else (identified or 0)
    dups = counts.get("duplicates_removed", 0)
    screened = counts.get("screened", total_id - dups)
    excluded_screen = counts.get("excluded_screening", {})
    n_excl_screen = sum(excluded_screen.values()) if isinstance(excluded_screen, dict) else (excluded_screen or 0)
    eligible = counts.get("eligible", screened - n_excl_screen)
    excluded_ft = counts.get("excluded_fulltext", {})
    n_excl_ft = sum(excluded_ft.values()) if isinstance(excluded_ft, dict) else (excluded_ft or 0)
    included = counts.get("included", eligible - n_excl_ft)

    def esc(s):
        return str(s).replace('"', '\\"')

    if args.format == "dot":
        lines = ["digraph PRISMA {", '  rankdir=TB; node [shape=box, fontname="Helvetica"];',
                 f'  id [label="Records identified (n={total_id})"];',
                 f'  dup [label="Duplicates removed (n={dups})"];',
                 f'  scr [label="Records screened (n={screened})"];',
                 f'  exs [label="Excluded at screening (n={n_excl_screen})", shape=box, style=dashed];',
                 f'  elig [label="Assessed for eligibility (n={eligible})"];',
                 f'  exf [label="Excluded at full text (n={n_excl_ft})", shape=box, style=dashed];',
                 f'  inc [label="Studies included (n={included})", style=bold];',
                 "  id -> dup -> scr -> elig -> inc;",
                 "  scr -> exs; elig -> exf;", "}"]
        text = "\n".join(lines)
    else:  # svg — hand-rolled stdlib
        rows = [("Records identified", total_id), ("Duplicates removed", dups),
                ("Records screened", screened), ("Excluded at screening", n_excl_screen),
                ("Assessed for eligibility", eligible), ("Excluded at full text", n_excl_ft),
                ("Studies included", included)]
        h = 60 * len(rows) + 20
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="360" height="{h}" font-family="Helvetica">']
        for i, (label, n) in enumerate(rows):
            y = 20 + i * 60
            parts.append(f'<rect x="20" y="{y}" width="320" height="40" fill="#eef" stroke="#334"/>'
                         f'<text x="30" y="{y + 25}" font-size="13">{esc(label)}: n={n}</text>')
            if i < len(rows) - 1:
                parts.append(f'<line x1="180" y1="{y + 40}" x2="180" y2="{y + 60}" stroke="#334"/>')
        parts.append("</svg>")
        text = "\n".join(parts)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"wrote {args.out} ({args.format})")
    else:
        print(text)
    return 0


# ==========================================================================
# v2 — submission-readiness gate (G4)
# ==========================================================================

_PVALUE = re.compile(r"\bp\s*[<>=]\s*0?\.\d+|\bp\s*=\s*\.?\d", re.IGNORECASE)
_CI = re.compile(r"(95%\s*ci|confidence interval|\bci\b|±|\[[-\d.]+,\s*[-\d.]+\])", re.IGNORECASE)
_EFFECT = re.compile(r"\b(cohen's d|odds ratio|\bor\b|risk ratio|\brr\b|hazard ratio|\bhr\b|"
                     r"effect size|mean difference|correlation|r\s*=|β\s*=|beta\s*=)\b", re.IGNORECASE)
_PAST_RESULT = re.compile(
    r"\b(we (found|observed|showed|demonstrated|achieved|obtained|report)|"
    r"results (show|showed|demonstrate|indicate)|our (experiments?|model) (achieved|obtained|outperform))",
    re.IGNORECASE)
_RESULTS_HEADING = re.compile(r"^#{1,3}\s*(results|findings|experiments?)\b", re.IGNORECASE | re.M)


def _structural_check(check_id, text):
    checks = {
        "has_data_availability": r"data availability|data are available|data can be found|available at (https?://|doi)",
        "has_code_availability": r"code (is )?available|source code|github\.com|zenodo",
        "has_funding": r"funding|funded by|grant (no|number)|financial support",
        "has_coi": r"conflict of interest|competing interests|no conflicts|declare no",
        "has_ethics": r"ethics|irb|institutional review|informed consent|approved by",
        "has_limitations": r"^#{1,4}.*limitation|limitations of|a limitation",
        "has_methods": r"^#{1,4}\s*(methods|materials and methods|methodology)",
        "has_abstract": r"^#{1,4}\s*abstract|^\*\*abstract",
        "has_references": r"^#{1,4}\s*(references|bibliography)",
    }
    pat = checks.get(check_id)
    if not pat:
        return None
    return bool(re.search(pat, text, re.IGNORECASE | re.M))


def cmd_readiness(args) -> int:
    text = open(args.manuscript, encoding="utf-8").read()
    checklists = _load_checklists(args.checklists_dir, args.checklist_set)
    items_report, must_fail = [], []
    for item in checklists:
        auto = item.get("auto_detectable")
        present = None
        if auto == "regex" and item.get("pattern"):
            present = bool(re.search(item["pattern"], text, re.IGNORECASE | re.M))
        elif auto == "structural" and item.get("check"):
            present = _structural_check(item["check"], text)
        status = "present" if present else ("missing" if present is False else "adequacy-deferred")
        # llm-judge items: reconcile against reviewer .done shards if provided.
        adequacy = None
        if auto == "llm-judge" and args.adequacy_shards:
            shard = os.path.join(args.adequacy_shards, f"{item['id']}.done")
            if os.path.exists(shard):
                adequacy = open(shard, encoding="utf-8").read().strip().lower()
                status = "adequate" if adequacy.startswith("adequate") else "inadequate"
        rec = {"id": item["id"], "section": item.get("section"), "severity": item.get("severity"),
               "auto_detectable": auto, "status": status,
               "requirement": item.get("requirement_text"), "source": item.get("canonical_source_url")}
        items_report.append(rec)
        if item.get("severity") == "must":
            if auto in ("regex", "structural") and present is False:
                must_fail.append(item["id"])
            elif auto == "llm-judge" and args.adequacy_shards and status == "inadequate":
                must_fail.append(item["id"])

    # Statistical completeness: orphan p-values (p-value with no nearby CI/effect).
    orphan_p = []
    for m in _PVALUE.finditer(text):
        window = text[max(0, m.start() - 200): m.end() + 200]
        if not (_CI.search(window) or _EFFECT.search(window)):
            orphan_p.append(text[max(0, m.start() - 30): m.end() + 10].strip())

    # Reproducibility TOP-style classification.
    repro = {"data_availability": bool(_structural_check("has_data_availability", text)),
             "code_availability": bool(_structural_check("has_code_availability", text))}

    # run_mode = proposal: no populated Results section, no past-tense result claims.
    proposal_violations = []
    if args.run_mode == "proposal":
        if _RESULTS_HEADING.search(text):
            proposal_violations.append("populated Results/Findings section present in proposal mode")
        for m in _PAST_RESULT.finditer(text):
            proposal_violations.append("past-tense results claim: " + text[m.start():m.start() + 60].strip())

    # Figure-manifest sync.
    figure_fail = []
    if args.figure_manifest and os.path.exists(args.figure_manifest):
        manifest = json.load(open(args.figure_manifest, encoding="utf-8"))
        by_id = {f["id"]: f for f in (manifest if isinstance(manifest, list) else manifest.get("figures", []))}
        for m in re.finditer(r"!\[[^\]]*\]\(figures/([^)\s]+)", text):
            fid = m.group(1).split(".")[0].split("/")[-1]
            f = by_id.get(fid)
            if not f:
                figure_fail.append(f"embedded figure {fid} not in manifest")
            elif f.get("render_status") in ("deferred", "needs_human") or f.get("critic_verdict") == "revise":
                figure_fail.append(f"figure {fid} embedded but render_status={f.get('render_status')} critic={f.get('critic_verdict')}")

    gate_fail = bool(must_fail or orphan_p or proposal_violations or figure_fail)
    report = {
        "manuscript": args.manuscript, "checklist_set": args.checklist_set, "run_mode": args.run_mode,
        "executed_at": _now(),
        "summary": {"items_total": len(items_report),
                    "must_missing": len(must_fail),
                    "orphan_p_values": len(orphan_p),
                    "proposal_violations": len(proposal_violations),
                    "figure_failures": len(figure_fail),
                    "reproducibility": repro},
        "must_fail_items": must_fail,
        "orphan_p_values": orphan_p[:20],
        "proposal_violations": proposal_violations[:20],
        "figure_failures": figure_fail[:20],
        "items": items_report,
        "gate": "fail" if gate_fail else "pass",
        "note": "Exit code covers regex/structural/deterministic checks; llm-judge adequacy is "
                "reconciled via reviewer .done shards (pass --adequacy-shards).",
    }
    _write_json(args.out, report)
    return 1 if gate_fail else 0


def _load_checklists(checklists_dir, checklist_set):
    base = checklists_dir or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "skills",
        "intensive-research", "references", "checklists")
    items = []
    sets = checklist_set.split(",")
    for name in sets:
        path = os.path.join(base, f"{name.strip()}.json")
        if os.path.exists(path):
            data = json.load(open(path, encoding="utf-8"))
            for it in data.get("items", []):
                it.setdefault("checklist", name.strip())
                items.append(it)
    return items


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

    p = sub.add_parser("doctor", help="environment preflight")
    p.add_argument("--json", action="store_true")
    p.add_argument("--check-figures", action="store_true", help="report figure-rendering runtime")
    p.add_argument("--check-standards", action="store_true", help="HEAD-verify checklist source URLs")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("cache", help="cache maintenance")
    p.add_argument("action", choices=["stats", "clear", "path", "load-retractions"])
    p.set_defaults(fn=cmd_cache)

    # --- v2: venue style-learning ---
    p = sub.add_parser("venue-sample", help="fetch recent exemplar papers from a venue")
    p.add_argument("--venue", required=True)
    p.add_argument("--issn")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--since", default="2023-01-01")
    p.add_argument("--type", choices=["journal", "conference", "repository"])
    p.add_argument("--oa-only", action="store_true")
    p.add_argument("--save", help="dir to save exemplar JATS full text into")
    common(p)
    p.set_defaults(fn=cmd_venue_sample)

    p = sub.add_parser("style-profile", help="compute a deterministic style profile from exemplars")
    p.add_argument("--manifest", required=True)
    common(p)
    p.set_defaults(fn=cmd_style_profile)

    p = sub.add_parser("originality", help="verbatim-overlap screen of a draft vs a corpus")
    p.add_argument("--draft", required=True)
    p.add_argument("--against", required=True, help="exemplar manifest JSON or a directory of text files")
    p.add_argument("--max-verbatim-words", type=int, default=12)
    common(p)
    p.set_defaults(fn=cmd_originality)

    # --- v2: datasets (nested verbs) ---
    p = sub.add_parser("datasets", help="dataset discovery + vetting")
    dsub = p.add_subparsers(dest="verb", required=True)
    d = dsub.add_parser("search")
    d.add_argument("--q", required=True)
    d.add_argument("--sources", help="comma list or 'all' (default hf,openml,datacite,zenodo,uci)")
    d.add_argument("--limit", type=int, default=25)
    common(d)
    d = dsub.add_parser("card")
    d.add_argument("target", help="<source>:<id>, e.g. hf:stanfordnlp/imdb")
    common(d)
    d = dsub.add_parser("splits")
    d.add_argument("target", help="HF dataset id")
    common(d)
    d = dsub.add_parser("fitness")
    d.add_argument("--candidates", required=True)
    d.add_argument("--spec", required=True)
    d.add_argument("--gate", action="store_true", help="G-D: exit nonzero on unfit/unsigned-conditional")
    d.add_argument("--signoff", action="store_true", help="recorded human sign-off for conditional datasets")
    common(d)
    d = dsub.add_parser("vet")
    d.add_argument("target")
    d.add_argument("--spec")
    common(d)
    p.set_defaults(fn=cmd_datasets)

    # --- v2: PRISMA figure ---
    p = sub.add_parser("emit-prisma", help="emit a PRISMA flow diagram (DOT/SVG) from counts")
    p.add_argument("--counts", required=True, help="prisma-counts.json")
    p.add_argument("--ledger", help="search-ledger.jsonl (optional, for identification totals)")
    p.add_argument("--format", choices=["dot", "svg"], default="dot")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_emit_prisma)

    # --- v2: submission-readiness gate (G4) ---
    p = sub.add_parser("readiness", help="G4: submission-readiness gate over a manuscript")
    p.add_argument("--manuscript", required=True)
    p.add_argument("--checklist-set", required=True, help="comma list of checklist ids (e.g. prisma-2020,strobe)")
    p.add_argument("--checklists-dir")
    p.add_argument("--run-mode", choices=["proposal", "empirical"], default="empirical")
    p.add_argument("--figure-manifest")
    p.add_argument("--adequacy-shards", help="dir of reviewer <item>.done adequacy verdicts")
    p.add_argument("--corpus")
    common(p)
    p.set_defaults(fn=cmd_readiness)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
