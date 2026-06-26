import os
import re
from typing import Any

from rapidfuzz import fuzz

from api import ddunlimited_api, ddunlimited_browser, media_resolver_api, mircrew_api, mircrew_browser


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _detail_limit() -> int:
    return max(0, min(50, _env_int("EXTENDED_SEARCH_DETAIL_MAX", 10)))


def _normalize(text: str | None) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def _split_categories(value: str | None) -> set[str]:
    if not value:
        return set()
    return {token.strip().lower() for token in str(value).split(",") if token.strip()}


def _extract_year(text: str | None) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _build_resolver_context(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind == "movie":
        tmdbid = (params.get("tmdbid") or "").strip()
        imdbid = (params.get("imdbid") or "").strip()
        if tmdbid or imdbid:
            result = media_resolver_api.resolve_movie(tmdbid, imdbid)
            return {
                "resolver_used": "movie_by_id",
                "result": result,
            }
        q = (params.get("q") or "").strip()
        if q:
            result = media_resolver_api.resolve_by_title(q, "movie")
            return {
                "resolver_used": "movie_by_title",
                "result": result,
            }
        return {"resolver_used": "none", "result": {"ok": False, "items": []}}

    tvdbid = (params.get("tvdbid") or "").strip()
    if tvdbid:
        result = media_resolver_api.resolve_series(tvdbid)
        return {
            "resolver_used": "series_by_id",
            "result": result,
        }
    q = (params.get("q") or "").strip()
    if q:
        result = media_resolver_api.resolve_by_title(q, "series")
        return {
            "resolver_used": "series_by_title",
            "result": result,
        }
    return {"resolver_used": "none", "result": {"ok": False, "items": []}}


def _resolver_items(context: dict[str, Any]) -> list[dict[str, Any]]:
    result = context.get("result") if isinstance(context, dict) else None
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _search_terms(params: dict[str, Any], resolver_items: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    direct_q = (params.get("q") or "").strip()
    if direct_q:
        terms.append(direct_q)
    for item in resolver_items:
        title = str(item.get("title") or "").strip()
        if title:
            terms.append(title)
        for alias in item.get("aliases") or []:
            alias_text = str(alias or "").strip()
            if alias_text:
                terms.append(alias_text)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(term)
    return deduped


def _resolved_ids_map(resolver_items: list[dict[str, Any]]) -> dict[str, str | None]:
    ids = {"tvdbid": None, "tmdbid": None, "imdbid": None}
    for item in resolver_items:
        raw_ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        for key in ids:
            if ids[key] is None and raw_ids.get(key):
                ids[key] = str(raw_ids.get(key))
    return ids


def _resolved_year(resolver_items: list[dict[str, Any]], params: dict[str, Any]) -> int | None:
    try:
        if params.get("year"):
            return int(params.get("year"))
    except (TypeError, ValueError):
        pass
    for item in resolver_items:
        year = _extract_year(item.get("year"))
        if year:
            return year
    return None


def _match_score(title: str, aliases: list[str], expected_year: int | None) -> dict[str, Any]:
    best_score = 0
    matched_alias = None
    normalized_title = _normalize(title)
    for alias in aliases:
        alias_text = str(alias or "").strip()
        if not alias_text:
            continue
        score = int(round(fuzz.token_set_ratio(normalized_title, _normalize(alias_text))))
        if score > best_score:
            best_score = score
            matched_alias = alias_text
    candidate_year = _extract_year(title)
    year_match = expected_year is None or candidate_year is None or candidate_year == expected_year
    if expected_year and candidate_year:
        if candidate_year == expected_year:
            best_score += 4
        else:
            best_score -= 10
    return {
        "score": max(best_score, 0),
        "matched_alias": matched_alias,
        "matched_year": str(candidate_year) if candidate_year else None,
        "year_match": year_match,
    }


def _is_id_match(kind: str, score: int, year_match: bool, has_resolver: bool) -> bool:
    if not has_resolver:
        return False
    threshold = 90 if kind == "movie" else 84
    if score < threshold:
        return False
    return year_match or kind == "tv"


def _mircrew_category_match(row: dict[str, Any], categories: set[str]) -> bool:
    if not categories:
        return True
    values = {
        str(row.get("category_label") or "").strip().lower(),
        str(row.get("category_value") or "").strip().lower(),
    }
    return any(value in categories for value in values if value)


def _ddu_category_match(item: Any, categories: set[str]) -> bool:
    if not categories:
        return True
    values = {
        str(getattr(item, "category", "") or "").strip().lower(),
        str(getattr(item, "media_type", "") or "").strip().lower(),
        str(getattr(item, "source_name", "") or "").strip().lower(),
    }
    return any(value in categories for value in values if value)


def _mircrew_candidates(params: dict[str, Any], resolver_context: dict[str, Any], resolver_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolver_items = _resolver_items(resolver_context)
    terms = _search_terms(params, resolver_items)
    merged: dict[str, dict[str, Any]] = {}
    for term in terms:
        for row in mircrew_api.search(term, limit=250):
            release_id = str(row.get("release_id") or "").strip()
            if release_id and release_id not in merged:
                merged[release_id] = dict(row)
    categories = _split_categories(params.get("categories"))
    rows = [row for row in merged.values() if _mircrew_category_match(row, categories)]
    return _build_mircrew_response(params, resolver_context, resolver_items, rows)


def _build_mircrew_response(
    params: dict[str, Any],
    resolver_context: dict[str, Any],
    resolver_items: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ids = _resolved_ids_map(resolver_items)
    aliases = _search_terms(params, resolver_items)
    expected_year = _resolved_year(resolver_items, params)
    has_resolver = bool(resolver_items)
    items: list[dict[str, Any]] = []
    for row in rows:
        match = _match_score(str(row.get("clean_title") or row.get("title_hint") or ""), aliases, expected_year)
        id_match = _is_id_match(params["kind"], match["score"], bool(match["year_match"]), has_resolver)
        items.append({
            "release_id": str(row.get("release_id") or ""),
            "release_url": row.get("release_url"),
            "title_hint": row.get("title_hint"),
            "clean_title": row.get("clean_title"),
            "category_label": row.get("category_label"),
            "category_value": row.get("category_value"),
            "created_at": mircrew_api.row_created_at(row),
            "size_bytes": row.get("size_bytes"),
            "size_source": "list" if row.get("size_bytes") else None,
            "size_confidence": "medium" if row.get("size_bytes") else "low",
            "magnet_links": [],
            "torrent_links": [],
            "seeders": None,
            "leechers": None,
            "peers": None,
            "detail_status": row.get("detail_status"),
            "detail_enriched": False,
            "match": {
                "id_match": id_match,
                "score": match["score"],
                "matched_title": resolver_items[0]["title"] if resolver_items else params.get("q"),
                "matched_alias": match["matched_alias"],
                "matched_year": match["matched_year"] or (str(expected_year) if expected_year else None),
            },
            "resolved_ids": ids,
            "_sort_created_at": row.get("release_posted_at_ms") or 0,
        })
    items.sort(key=lambda item: (-int(item["match"]["score"]), -(item.get("_sort_created_at") or 0), str(item.get("title_hint") or "")))
    _enrich_mircrew_details(items)
    for item in items:
        item.pop("_sort_created_at", None)
    return items


def _enrich_mircrew_details(items: list[dict[str, Any]]) -> int:
    enriched = 0
    remaining = _detail_limit()
    for item in items:
        if not item["match"]["id_match"] or remaining <= 0:
            continue
        try:
            detail = mircrew_api.get_release_detail(release_id=item["release_id"])
        except mircrew_browser.MircrewBrowserAuthRequired:
            item["detail_status"] = "auth_required"
            item["detail_enriched"] = False
            continue
        except Exception:
            item["detail_status"] = "detail_error"
            item["detail_enriched"] = False
            continue
        item["created_at"] = detail.get("created_at") or item.get("created_at")
        item["magnet_links"] = detail.get("magnet_links") or []
        item["torrent_links"] = detail.get("torrent_links") or []
        item["seeders"] = detail.get("seeders")
        item["leechers"] = detail.get("leechers")
        item["peers"] = detail.get("peers")
        item["detail_status"] = detail.get("detail_status")
        item["detail_enriched"] = True
        size_bytes = detail.get("size_bytes")
        if size_bytes:
            item["size_bytes"] = size_bytes
            item["size_source"] = "detail"
            item["size_confidence"] = "high"
        enriched += 1
        remaining -= 1
    return enriched


def _ddu_candidates(params: dict[str, Any], resolver_context: dict[str, Any], resolver_items: list[dict[str, Any]], db) -> list[dict[str, Any]]:
    terms = _search_terms(params, resolver_items)
    merged: dict[str, Any] = {}
    for term in terms:
        for item in ddunlimited_api.search_cache(term, max_results=250):
            key = ddunlimited_api.normalize_detail_url(item.detail_url) or str(item.topic_id or "")
            if key and key not in merged:
                merged[key] = item
    categories = _split_categories(params.get("categories"))
    items = [item for item in merged.values() if _ddu_category_match(item, categories)]
    return _build_ddu_response(params, resolver_context, resolver_items, items, db)


def _build_ddu_response(
    params: dict[str, Any],
    resolver_context: dict[str, Any],
    resolver_items: list[dict[str, Any]],
    candidates: list[Any],
    db,
) -> list[dict[str, Any]]:
    ids = _resolved_ids_map(resolver_items)
    aliases = _search_terms(params, resolver_items)
    expected_year = _resolved_year(resolver_items, params)
    has_resolver = bool(resolver_items)
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        title = str(getattr(candidate, "title", "") or "")
        match = _match_score(title, aliases, expected_year)
        id_match = _is_id_match(params["kind"], match["score"], bool(match["year_match"]), has_resolver)
        items.append({
            "release_id": str(getattr(candidate, "topic_id", "") or ""),
            "release_url": getattr(candidate, "detail_url", None),
            "title_hint": title,
            "clean_title": title,
            "category_label": getattr(candidate, "category", None),
            "category_value": getattr(candidate, "category", None),
            "created_at": getattr(candidate, "created_at", None),
            "size_bytes": None,
            "size_source": None,
            "size_confidence": "low",
            "ed2k_items": [],
            "detail_status": None,
            "detail_enriched": False,
            "match": {
                "id_match": id_match,
                "score": match["score"],
                "matched_title": resolver_items[0]["title"] if resolver_items else params.get("q"),
                "matched_alias": match["matched_alias"],
                "matched_year": match["matched_year"] or (str(expected_year) if expected_year else None),
            },
            "resolved_ids": ids,
        })
    items.sort(key=lambda item: (-int(item["match"]["score"]), str(item.get("title_hint") or "")))
    _enrich_ddu_details(items, db)
    return items


def _enrich_ddu_details(items: list[dict[str, Any]], db) -> int:
    enriched = 0
    remaining = _detail_limit()
    for item in items:
        if not item["match"]["id_match"] or remaining <= 0:
            continue
        try:
            detail = ddunlimited_api.get_release_ed2k(item["release_url"], db)
        except ddunlimited_browser.DDUBrowserAuthRequired:
            item["detail_status"] = "auth_required"
            item["detail_enriched"] = False
            continue
        except Exception:
            item["detail_status"] = "detail_error"
            item["detail_enriched"] = False
            continue
        item["created_at"] = detail.get("created_at") or item.get("created_at")
        item["ed2k_items"] = detail.get("ed2k_items") or []
        item["detail_status"] = "ok" if item["ed2k_items"] else "incomplete"
        item["detail_enriched"] = True
        total_bytes = ((detail.get("ed2k_stats") or {}).get("total_bytes")) or None
        if total_bytes:
            item["size_bytes"] = total_bytes
            item["size_source"] = "detail"
            item["size_confidence"] = "high"
        enriched += 1
        remaining -= 1
    return enriched


def _page(items: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    offset = max(0, int(params.get("offset") or 0))
    limit = max(1, min(int(params.get("limit") or 50), 500))
    return items[offset: offset + limit]


def _query_payload(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": params["kind"],
        "q": params.get("q"),
        "tmdbid": params.get("tmdbid"),
        "imdbid": params.get("imdbid"),
        "tvdbid": params.get("tvdbid"),
        "season": params.get("season"),
        "ep": params.get("ep"),
        "year": params.get("year"),
    }


def mircrew_extended_search(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    params = dict(params)
    params["kind"] = kind
    resolver_context = _build_resolver_context(kind, params)
    resolver_items = _resolver_items(resolver_context)
    items = _mircrew_candidates(params, resolver_context, resolver_items)
    total = len(items)
    paged = _page(items, params)
    detail_enriched_count = sum(1 for item in items if item.get("detail_enriched"))
    return {
        "ok": True,
        "query": _query_payload(params),
        "meta": {
            "backend": "mircrew",
            "resolver_used": resolver_context.get("resolver_used"),
            "detail_enriched_count": detail_enriched_count,
            "total_found_before_paging": total,
        },
        "items": paged,
    }


def ddunlimited_extended_search(kind: str, params: dict[str, Any], db) -> dict[str, Any]:
    params = dict(params)
    params["kind"] = kind
    resolver_context = _build_resolver_context(kind, params)
    resolver_items = _resolver_items(resolver_context)
    items = _ddu_candidates(params, resolver_context, resolver_items, db)
    total = len(items)
    paged = _page(items, params)
    detail_enriched_count = sum(1 for item in items if item.get("detail_enriched"))
    return {
        "ok": True,
        "query": _query_payload(params),
        "meta": {
            "backend": "ddunlimited",
            "resolver_used": resolver_context.get("resolver_used"),
            "detail_enriched_count": detail_enriched_count,
            "total_found_before_paging": total,
        },
        "items": paged,
    }
