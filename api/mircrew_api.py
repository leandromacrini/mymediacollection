import json
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from api import mircrew_browser

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.abspath((os.environ.get("MMC_CACHE_DIR") or "/data/cache").strip())
_CACHE_FILE = os.path.join(_DATA_DIR, "mircrew_releases.json")
_META_FILE = os.path.join(_DATA_DIR, "mircrew_releases.meta.json")
_CACHE_LOCK = RLock()
_CACHE_ROWS: list[dict[str, Any]] | None = None
_CACHE_MTIME: float | None = None

_REFRESH_LOCK = RLock()
_REFRESH_STATE = {
    "running": False,
    "job_type": None,
    "total_sources": 0,
    "processed_sources": 0,
    "current_source": None,
    "current_source_id": None,
    "current_mode": None,
    "current_page": 0,
    "current_source_total_pages": 0,
    "pages_scanned": 0,
    "current_source_new_items": 0,
    "items_count": 0,
    "started_at": None,
    "updated_at": None,
    "cancelled": False,
    "error": None,
}
_CANCEL_EVENT = Event()
_REFRESH_THREAD: Thread | None = None

_DETAIL_CACHE_LOCK = RLock()
_DETAIL_CACHE: dict[str, dict[str, Any]] = {}

_SIZE_RE = re.compile(r"(\d[\d.,\s]*\d|\d)\s*(TB|GB|MB|KB|B|TIB|GIB|MIB|KIB)\b", re.IGNORECASE)
_STOPWORDS = {
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno",
    "di", "da", "del", "della", "dello", "dei", "degli", "delle",
    "the", "a", "an", "and", "of",
}


class MircrewInvalidSourcePage(RuntimeError):
    pass


class MircrewRefreshCancelled(RuntimeError):
    def __init__(self, result: dict[str, Any] | None = None):
        super().__init__("refresh_cancelled")
        self.result = result or {}


def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


def _detail_cache_ttl_seconds() -> int:
    raw = (os.environ.get("MIRCREW_DETAIL_CACHE_TTL_SECONDS") or "").strip()
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return 86400


def _refresh_max_pages() -> int:
    raw = (os.environ.get("MIRCREW_REFRESH_MAX_PAGES") or "").strip()
    try:
        return max(1, min(5000, int(raw)))
    except (TypeError, ValueError):
        return 500


def _refresh_jump_pages() -> int:
    raw = (os.environ.get("MIRCREW_REFRESH_JUMP_PAGES") or "").strip()
    try:
        return max(2, min(100, int(raw)))
    except (TypeError, ValueError):
        return 15


def _refresh_flush_pages() -> int:
    raw = (os.environ.get("MIRCREW_REFRESH_FLUSH_PAGES") or "").strip()
    default_value = _refresh_jump_pages()
    try:
        return max(1, min(500, int(raw)))
    except (TypeError, ValueError):
        return max(1, default_value)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_title_tokens(text: str) -> tuple[str, set[str]]:
    normalized = _normalize_whitespace(text).lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = _normalize_whitespace(normalized)
    tokens = {token for token in normalized.split() if token and token not in _STOPWORDS}
    return normalized, tokens


def _clean_title(raw_title: str) -> str:
    title = _normalize_whitespace(raw_title)
    if not title:
        return title
    title = re.sub(r"\[[^\]]*\]", " ", title)
    title = re.sub(r"\s+[\-\|]\s+.*$", "", title)
    title = _normalize_whitespace(title)
    return title or _normalize_whitespace(raw_title)


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    if not match:
        return None
    year = _safe_int(match.group(1))
    if year and 1900 <= year <= 2100:
        return year
    return None


def _infer_media_type(title: str) -> str:
    text = (title or "").lower()
    if re.search(r"\bs\d{1,2}e\d{1,3}\b", text):
        return "series"
    if re.search(r"\b(stagione|season|episodio|episode|ep\.?\s*\d+)\b", text):
        return "series"
    return "movie"


def _infer_category(row: dict[str, Any], media_type: str) -> str:
    label = (row.get("category_label") or "").strip().lower()
    if "anim" in label:
        return "anime"
    if "tv" in label or "serie" in label:
        return "tv"
    if "film" in label or "movie" in label:
        return "film"
    return "tv" if media_type == "series" else "film"


def _to_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def row_created_at(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    raw_ms = _safe_int(row.get("release_posted_at_ms"))
    if raw_ms:
        return datetime.fromtimestamp(raw_ms / 1000, tz=timezone.utc).isoformat()
    return None


def _extract_topic_id(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        values = parse_qs(parsed.query).get("t")
        if values:
            return str(values[0])
    except Exception:
        return None
    return None


def _extract_release_date_info(anchor) -> tuple[str | None, int | None]:
    texts: list[str] = []
    parent = getattr(anchor, "parent", None)
    if parent:
        texts.append(parent.get_text(" ", strip=True))
    row = anchor.find_parent("tr")
    if row:
        texts.append(row.get_text(" ", strip=True))
    texts.append(anchor.get_text(" ", strip=True))
    combined = " | ".join(texts)
    match = re.search(r"(\d{2}/\d{2}/\d{4}\s*,?\s*\d{2}:\d{2})", combined)
    if not match:
        return None, None
    raw = _normalize_whitespace(match.group(1))
    for fmt in ("%d/%m/%Y, %H:%M", "%d/%m/%Y %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return raw, int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return raw, None


def _parse_size_text_to_bytes(size_text: str | None) -> int | None:
    text = _normalize_whitespace(size_text or "")
    if not text:
        return None
    match = _SIZE_RE.search(text)
    if not match:
        return None
    raw_text = (match.group(1) or "").strip()
    unit = (match.group(2) or "").upper()
    if unit == "B":
        digits = re.sub(r"[^\d]", "", raw_text)
        return _safe_int(digits)
    compact = raw_text.replace(" ", "")
    if "," in compact and "." in compact:
        if compact.rfind(",") > compact.rfind("."):
            compact = compact.replace(".", "").replace(",", ".")
        else:
            compact = compact.replace(",", "")
    elif "," in compact:
        compact = compact.replace(",", ".")
    try:
        amount = float(compact)
    except ValueError:
        return None
    multipliers = {
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
        "TIB": 1024**4,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
    }
    mult = multipliers.get(unit)
    if not mult:
        return None
    return int(amount * mult)


def _extract_size_from_context(anchor) -> tuple[str | None, int | None]:
    contexts: list[str] = []
    row = anchor.find_parent("tr")
    if row:
        contexts.append(row.get_text(" ", strip=True))
    parent = getattr(anchor, "parent", None)
    if parent:
        contexts.append(parent.get_text(" ", strip=True))
    for text in contexts:
        match = _SIZE_RE.search(text)
        if match:
            raw = _normalize_whitespace(match.group(0))
            return raw, _parse_size_text_to_bytes(raw)
    return None, None


def _find_next_page_url(doc: BeautifulSoup, page_url: str) -> str | None:
    next_rel = doc.select_one('a[rel="next"]')
    if next_rel and next_rel.get("href"):
        return urljoin(page_url, next_rel.get("href"))
    for link in doc.select(".pagination a, a.button"):
        text = _normalize_whitespace(link.get_text(" ", strip=True)).lower()
        if text in {"next", "successiva", "prossima"} and link.get("href"):
            return urljoin(page_url, link.get("href"))
    return None


def _get_start_offset(page_url: str) -> int:
    try:
        parsed = urlsplit(page_url)
        value = parse_qs(parsed.query).get("start", ["0"])[0]
        return max(0, int(value))
    except Exception:
        return 0


def _build_page_url(base_url: str, start_offset: int) -> str:
    parsed = urlsplit(base_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if start_offset > 0:
        query["start"] = [str(start_offset)]
    else:
        query.pop("start", None)
    encoded_query = urlencode([(key, value) for key, values in query.items() for value in values], doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, encoded_query, parsed.fragment))


def _detect_page_step(doc: BeautifulSoup, page_url: str) -> int:
    starts = {0}
    for link in doc.select('a[href*="start="]'):
        href = link.get("href")
        if not href:
            continue
        full = urljoin(page_url, href)
        starts.add(_get_start_offset(full))
    ordered = sorted(value for value in starts if value >= 0)
    if len(ordered) < 2:
        return 25
    diffs = [ordered[idx] - ordered[idx - 1] for idx in range(1, len(ordered)) if ordered[idx] - ordered[idx - 1] > 0]
    return min(diffs) if diffs else 25


def _detect_total_pages(doc: BeautifulSoup, page_url: str, page_step: int) -> int:
    for node in doc.select(".pagination .sr-only, .pagination, .page-jump"):
        text = _normalize_whitespace(node.get_text(" ", strip=True))
        match = re.search(r"\bpagina\s+\d+\s+di\s+(\d+)\b", text, flags=re.IGNORECASE)
        if match:
            try:
                return max(1, int(match.group(1)))
            except (TypeError, ValueError):
                pass
    starts = {0}
    for link in doc.select('a[href*="start="]'):
        href = link.get("href")
        if not href:
            continue
        full = urljoin(page_url, href)
        starts.add(_get_start_offset(full))
    max_start = max((value for value in starts if value >= 0), default=0)
    step = max(1, page_step)
    return max(1, max_start // step + 1)


def _resolve_next_jump_url(
    base_url: str,
    current_start: int,
    page_step: int,
    jump_pages: int,
    total_pages: int,
    next_page_url: str | None,
) -> tuple[str | None, str]:
    target_start = current_start + page_step * jump_pages
    if total_pages > 0:
        max_start = max(0, (total_pages - 1) * max(1, page_step))
        penultimate_start = max(0, max_start - max(1, page_step))
        if target_start > max_start:
            if current_start < penultimate_start:
                return _build_page_url(base_url, penultimate_start), "jump"
            if current_start == penultimate_start and current_start < max_start:
                return _build_page_url(base_url, max_start), "jump"
            if next_page_url and current_start < max_start:
                return next_page_url, "jump"
            return None, "jump"
    return _build_page_url(base_url, target_start), "jump"


def _validate_list_page_html(html: str, source_name: str | None = None) -> BeautifulSoup:
    doc = BeautifulSoup(html, "html.parser")
    title = _normalize_whitespace(doc.title.get_text(" ", strip=True) if doc.title else "")
    label = source_name or "MirCrew source"
    if title.lower().startswith("informazione"):
        raise MircrewInvalidSourcePage(f"{label}: pagina non valida o obsoleta (MirCrew 'Informazione').")
    full_text = _normalize_whitespace(doc.get_text(" ", strip=True)).lower()
    title_lower = title.lower()
    cloudflare_markers = (
        "just a moment",
        "enable javascript and cookies to continue",
        "challenge-platform",
        "cf-browser-verification",
        "attention required",
    )
    if any(marker in title_lower or marker in full_text for marker in cloudflare_markers):
        raise MircrewInvalidSourcePage(f"{label}: accesso bloccato da Cloudflare/challenge page.")
    return doc


def _extract_release_links(doc: BeautifulSoup, page_url: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    nodes = [*doc.select('a[href*="viewtopic.php?t="]'), *doc.select("a.topictitle")]
    for anchor in nodes:
        href = anchor.get("href")
        if not href:
            continue
        full = urljoin(page_url, href)
        topic_id = _extract_topic_id(full)
        if not topic_id or topic_id in seen:
            continue
        seen.add(topic_id)
        title_hint = _normalize_whitespace(anchor.get_text(" ", strip=True))
        if not title_hint:
            continue
        posted_text, posted_ms = _extract_release_date_info(anchor)
        size_text_raw, size_bytes = _extract_size_from_context(anchor)
        rows.append({
            "release_id": topic_id,
            "release_url": full.split("#")[0],
            "title_hint": title_hint,
            "clean_title": _clean_title(title_hint),
            "category_label": str(source.get("category_label") or "").strip(),
            "category_value": str(source.get("category_value") or "").strip(),
            "release_posted_at_text": posted_text,
            "release_posted_at_ms": posted_ms,
            "size_text_raw": size_text_raw,
            "size_bytes": size_bytes,
            "detail_status": None,
            "first_seen_at": None,
            "last_seen_at": None,
        })
    return rows


def _read_cache_rows() -> list[dict[str, Any]]:
    global _CACHE_ROWS, _CACHE_MTIME
    if not os.path.exists(_CACHE_FILE):
        _CACHE_ROWS = []
        _CACHE_MTIME = None
        logger.info("mircrew cache load skipped path=%s reason=missing_file", _CACHE_FILE)
        return []
    st = os.stat(_CACHE_FILE)
    if _CACHE_ROWS is not None and _CACHE_MTIME == st.st_mtime:
        return _CACHE_ROWS
    logger.info("mircrew cache load start path=%s", _CACHE_FILE)
    with open(_CACHE_FILE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = payload if isinstance(payload, list) else []
    _CACHE_ROWS = rows
    _CACHE_MTIME = st.st_mtime
    logger.info("mircrew cache load done path=%s items=%s", _CACHE_FILE, len(rows))
    return rows


def _write_cache_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    _ensure_data_dir()
    with open(_CACHE_FILE, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False)
    st = os.stat(_CACHE_FILE)
    updated_at = _to_timestamp(st.st_mtime)
    meta = {"count": len(rows), "updated_at": updated_at}
    with open(_META_FILE, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False)
    invalidate_cache()
    return {"count": len(rows), "updated_at": updated_at}


def _merge_rows_into_cache(
    existing_rows: list[dict[str, Any]],
    incoming_rows: dict[str, dict[str, Any]],
    now_iso: str,
) -> list[dict[str, Any]]:
    merged_cache: dict[str, dict[str, Any]] = {
        str(row.get("release_id") or ""): dict(row)
        for row in existing_rows
        if str(row.get("release_id") or "").strip()
    }
    for release_id, row in incoming_rows.items():
        current = merged_cache.get(release_id)
        if current:
            merged_cache[release_id] = _merge_release_row(current, row, now_iso)
        else:
            merged_cache[release_id] = row
    return sorted(
        merged_cache.values(),
        key=lambda item: (-(item.get("release_posted_at_ms") or 0), item.get("release_id") or ""),
    )


def _row_matches_source(row: dict[str, Any], source: dict[str, Any]) -> bool:
    source_value = str(source.get("category_value") or "").strip()
    row_value = str(row.get("category_value") or "").strip()
    if source_value:
        return row_value == source_value
    source_label = str(source.get("category_label") or "").strip().lower()
    row_label = str(row.get("category_label") or "").strip().lower()
    if source_label:
        return row_label == source_label
    return False


def _preserve_existing_source_rows(
    merged: dict[str, dict[str, Any]],
    existing_rows: list[dict[str, Any]],
    source: dict[str, Any],
) -> None:
    for row in existing_rows:
        release_id = str(row.get("release_id") or "").strip()
        if not release_id or release_id in merged:
            continue
        if _row_matches_source(row, source):
            merged[release_id] = dict(row)


def _count_source_rows(rows: list[dict[str, Any]], source: dict[str, Any]) -> int:
    return sum(1 for row in rows if _row_matches_source(row, source))


def enrich_sources_with_cache_counts(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _read_cache_rows()
    items: list[dict[str, Any]] = []
    for source in sources:
        payload = dict(source)
        payload["last_count"] = _count_source_rows(rows, source)
        items.append(payload)
    return items


def _write_refresh_checkpoint(
    existing_rows: list[dict[str, Any]],
    merged_rows: dict[str, dict[str, Any]],
    now_iso: str,
) -> dict[str, Any]:
    rows = _merge_rows_into_cache(existing_rows, merged_rows, now_iso)
    result = _write_cache_rows(rows)
    logger.info("mircrew refresh checkpoint cache_items=%s updated_at=%s", len(rows), result.get("updated_at"))
    return {
        "rows": rows,
        "count": len(rows),
        "updated_at": result.get("updated_at"),
    }


def invalidate_cache() -> None:
    global _CACHE_ROWS, _CACHE_MTIME
    _CACHE_ROWS = None
    _CACHE_MTIME = None


def get_status() -> dict[str, Any]:
    if not os.path.exists(_CACHE_FILE):
        return {
            "exists": False,
            "count": 0,
            "updated_at": None,
            "cache_loaded": _CACHE_ROWS is not None,
            "path": _CACHE_FILE,
            "detail_cache_items": len(_DETAIL_CACHE),
        }
    updated_at = None
    count = 0
    if os.path.exists(_META_FILE):
        try:
            with open(_META_FILE, "r", encoding="utf-8") as handle:
                meta = json.load(handle)
            count = _safe_int(meta.get("count")) or 0
            updated_at = meta.get("updated_at")
        except Exception:
            pass
    if count <= 0 or not updated_at:
        try:
            rows = _read_cache_rows()
            if count <= 0:
                count = len(rows)
            if not updated_at and os.path.exists(_CACHE_FILE):
                updated_at = _to_timestamp(os.stat(_CACHE_FILE).st_mtime)
        except Exception:
            pass
    return {
        "exists": True,
        "count": count,
        "updated_at": updated_at,
        "cache_loaded": _CACHE_ROWS is not None,
        "path": _CACHE_FILE,
        "detail_cache_items": len(_DETAIL_CACHE),
    }


def get_release_by_id(release_id: str) -> dict[str, Any] | None:
    rid = str(release_id or "").strip()
    if not rid:
        return None
    for row in _read_cache_rows():
        if str(row.get("release_id") or "") == rid:
            return row
    return None


def search(query: str, limit: int = 250) -> list[dict[str, Any]]:
    text = _normalize_whitespace(query).lower()
    if not text:
        return []
    _, query_tokens = _normalize_title_tokens(text)
    rows = _read_cache_rows()
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        hay_clean, clean_tokens = _normalize_title_tokens(str(row.get("clean_title") or ""))
        hay_full, full_tokens = _normalize_title_tokens(str(row.get("title_hint") or ""))
        all_tokens = clean_tokens | full_tokens
        if query_tokens and not query_tokens.issubset(all_tokens) and text not in hay_clean and text not in hay_full:
            continue
        score = 0
        if text in hay_clean:
            score += 10
        if text in hay_full:
            score += 6
        overlap = len(query_tokens & all_tokens) if query_tokens else 0
        score += overlap * 3
        score += max(0, 5 - abs(len(hay_clean) - len(text)) // 10)
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -(item[1].get("release_posted_at_ms") or 0), item[1].get("clean_title") or ""))
    return [row for _, row in scored[:limit]]


def build_wanted_payload(row: dict[str, Any]) -> dict[str, Any]:
    title_hint = str(row.get("title_hint") or "")
    clean_title = str(row.get("clean_title") or "") or _clean_title(title_hint)
    media_type = _infer_media_type(title_hint)
    year = _extract_year(title_hint)
    category = _infer_category(row, media_type)
    return {
        "title": clean_title or title_hint,
        "year": year,
        "media_type": media_type,
        "category": category,
        "source": "mircrew",
        "source_ref": row.get("release_url"),
        "original_title": None,
        "language": None,
        "release_id": str(row.get("release_id") or ""),
        "release_url": str(row.get("release_url") or ""),
    }


def get_browser_status(check_session: bool = True) -> dict[str, Any]:
    return mircrew_browser.get_browser_status(check_session=check_session)


def get_refresh_status() -> dict[str, Any]:
    with _REFRESH_LOCK:
        started = _REFRESH_STATE["started_at"]
        updated = _REFRESH_STATE["updated_at"]
        return {
            "running": _REFRESH_STATE["running"],
            "job_type": _REFRESH_STATE["job_type"],
            "total_sources": _REFRESH_STATE["total_sources"],
            "processed_sources": _REFRESH_STATE["processed_sources"],
            "current_source": _REFRESH_STATE["current_source"],
            "current_source_id": _REFRESH_STATE["current_source_id"],
            "current_mode": _REFRESH_STATE["current_mode"],
            "current_page": _REFRESH_STATE["current_page"],
            "current_source_total_pages": _REFRESH_STATE["current_source_total_pages"],
            "pages_scanned": _REFRESH_STATE["pages_scanned"],
            "current_source_new_items": _REFRESH_STATE["current_source_new_items"],
            "items_count": _REFRESH_STATE["items_count"],
            "started_at": started.isoformat() if started else None,
            "updated_at": updated.isoformat() if updated else None,
            "cancelled": _REFRESH_STATE["cancelled"],
            "error": _REFRESH_STATE["error"],
        }


def start_refresh(db) -> dict[str, Any]:
    if db is None:
        return {"ok": False, "error": "missing_db"}
    global _REFRESH_THREAD
    with _REFRESH_LOCK:
        if _REFRESH_STATE["running"]:
            return {"ok": True, **get_refresh_status()}
        _CANCEL_EVENT.clear()
        _REFRESH_STATE.update({
            "running": True,
            "job_type": "full_refresh",
            "total_sources": 0,
            "processed_sources": 0,
            "current_source": None,
            "current_source_id": None,
            "current_mode": None,
            "current_page": 0,
            "current_source_total_pages": 0,
            "pages_scanned": 0,
            "current_source_new_items": 0,
            "items_count": 0,
            "started_at": datetime.now(timezone.utc),
            "updated_at": None,
            "cancelled": False,
            "error": None,
        })

    def _run() -> None:
        sources = db.get_mircrew_sources(include_disabled=False)
        merged: dict[str, dict[str, Any]] = {}
        existing_rows = _read_cache_rows()
        existing = {str(row.get("release_id") or ""): row for row in existing_rows}
        now_iso = datetime.now(timezone.utc).isoformat()
        logger.info("mircrew refresh start sources=%s existing_rows=%s", len(sources), len(existing_rows))
        def _flush_checkpoint() -> dict[str, Any]:
            return _write_refresh_checkpoint(existing_rows, merged, now_iso)
        with _REFRESH_LOCK:
            _REFRESH_STATE["total_sources"] = len(sources)
            _REFRESH_STATE["updated_at"] = datetime.now(timezone.utc)

        for source in sources:
            if _CANCEL_EVENT.is_set():
                checkpoint = _flush_checkpoint()
                logger.warning(
                    "mircrew refresh cancelled processed=%s/%s cache_items=%s",
                    _REFRESH_STATE["processed_sources"],
                    len(sources),
                    checkpoint["count"],
                )
                with _REFRESH_LOCK:
                    _REFRESH_STATE["cancelled"] = True
                    _REFRESH_STATE["running"] = False
                    _REFRESH_STATE["current_mode"] = None
                    _REFRESH_STATE["current_page"] = 0
                    _REFRESH_STATE["current_source_total_pages"] = 0
                    _REFRESH_STATE["updated_at"] = datetime.fromisoformat(checkpoint["updated_at"]) if checkpoint["updated_at"] else datetime.now(timezone.utc)
                    _REFRESH_STATE["items_count"] = checkpoint["count"]
                return
            with _REFRESH_LOCK:
                _REFRESH_STATE["current_source"] = source["name"]
                _REFRESH_STATE["current_source_id"] = source["id"]
                _REFRESH_STATE["current_mode"] = "scan"
                _REFRESH_STATE["current_page"] = 0
                _REFRESH_STATE["current_source_total_pages"] = 0
                _REFRESH_STATE["current_source_new_items"] = 0
                _REFRESH_STATE["updated_at"] = datetime.now(timezone.utc)
            logger.info("mircrew refresh source start id=%s name=%s url=%s", source["id"], source["name"], source["url"])
            try:
                _refresh_source_rows(source, merged, existing, now_iso, checkpoint_callback=_flush_checkpoint)
                _preserve_existing_source_rows(merged, existing_rows, source)
                source_count = _count_source_rows(list(merged.values()), source)
                db.set_mircrew_source_stats(int(source["id"]), source_count)
                logger.info(
                    "mircrew refresh source done id=%s name=%s source_count=%s merged_items=%s",
                    source["id"],
                    source["name"],
                    source_count,
                    len(merged),
                )
            except MircrewRefreshCancelled:
                _preserve_existing_source_rows(merged, existing_rows, source)
                checkpoint = _flush_checkpoint()
                logger.warning(
                    "mircrew refresh cancelled during source id=%s name=%s cache_items=%s",
                    source["id"],
                    source["name"],
                    checkpoint["count"],
                )
                with _REFRESH_LOCK:
                    _REFRESH_STATE["cancelled"] = True
                    _REFRESH_STATE["running"] = False
                    _REFRESH_STATE["current_mode"] = None
                    _REFRESH_STATE["current_page"] = 0
                    _REFRESH_STATE["current_source_total_pages"] = 0
                    _REFRESH_STATE["updated_at"] = datetime.fromisoformat(checkpoint["updated_at"]) if checkpoint["updated_at"] else datetime.now(timezone.utc)
                    _REFRESH_STATE["items_count"] = checkpoint["count"]
                return
            except mircrew_browser.MircrewBrowserAuthRequired as exc:
                logger.error("mircrew refresh auth required source=%s error=%s", source["name"], exc)
                with _REFRESH_LOCK:
                    _REFRESH_STATE["error"] = str(exc)
                    _REFRESH_STATE["running"] = False
                return
            except Exception as exc:
                logger.exception("mircrew refresh source failed id=%s name=%s url=%s", source["id"], source["name"], source["url"])
                with _REFRESH_LOCK:
                    _REFRESH_STATE["error"] = f"{source['name']}: {exc}"
                    _REFRESH_STATE["updated_at"] = datetime.now(timezone.utc)
                    _REFRESH_STATE["running"] = False
                return
            with _REFRESH_LOCK:
                _REFRESH_STATE["processed_sources"] += 1
                _REFRESH_STATE["items_count"] = len(merged)
                _REFRESH_STATE["updated_at"] = datetime.now(timezone.utc)

        checkpoint = _flush_checkpoint()
        logger.info("mircrew refresh done processed=%s/%s cache_items=%s", len(sources), len(sources), checkpoint["count"])
        with _REFRESH_LOCK:
            _REFRESH_STATE["running"] = False
            _REFRESH_STATE["current_source"] = None
            _REFRESH_STATE["current_source_id"] = None
            _REFRESH_STATE["current_mode"] = None
            _REFRESH_STATE["current_page"] = 0
            _REFRESH_STATE["current_source_total_pages"] = 0
            _REFRESH_STATE["updated_at"] = datetime.fromisoformat(checkpoint["updated_at"]) if checkpoint["updated_at"] else None
            _REFRESH_STATE["items_count"] = checkpoint["count"]

    _REFRESH_THREAD = Thread(target=_run, daemon=True)
    _REFRESH_THREAD.start()
    return {"ok": True, **get_refresh_status()}


def cancel_refresh() -> dict[str, Any]:
    _CANCEL_EVENT.set()
    logger.warning("mircrew refresh cancel requested")
    with _REFRESH_LOCK:
        if _REFRESH_STATE["running"]:
            _REFRESH_STATE["cancelled"] = True
    return get_refresh_status()


def start_source_refresh(db, source: dict[str, Any]) -> dict[str, Any]:
    if db is None:
        return {"ok": False, "error": "missing_db"}
    if not source:
        return {"ok": False, "error": "missing_source"}
    global _REFRESH_THREAD
    with _REFRESH_LOCK:
        if _REFRESH_STATE["running"]:
            return {"ok": True, **get_refresh_status()}
        _CANCEL_EVENT.clear()
        _REFRESH_STATE.update({
            "running": True,
            "job_type": "single_source_refresh",
            "total_sources": 1,
            "processed_sources": 0,
            "current_source": source["name"],
            "current_source_id": source["id"],
            "current_mode": "scan",
            "current_page": 0,
            "current_source_total_pages": 0,
            "pages_scanned": 0,
            "current_source_new_items": 0,
            "items_count": 0,
            "started_at": datetime.now(timezone.utc),
            "updated_at": None,
            "cancelled": False,
            "error": None,
        })

    def _run() -> None:
        try:
            logger.info("mircrew single-source refresh start id=%s name=%s url=%s", source["id"], source["name"], source["url"])
            result = refresh_single_source_cache(source, save_progress=True)
            db.set_mircrew_source_stats(int(source["id"]), result["source_count"])
            logger.info(
                "mircrew single-source refresh done id=%s name=%s source_count=%s cache_items=%s",
                source["id"],
                source["name"],
                result["source_count"],
                result["cache_count"],
            )
            with _REFRESH_LOCK:
                _REFRESH_STATE["processed_sources"] = 1
                _REFRESH_STATE["running"] = False
                _REFRESH_STATE["current_mode"] = None
                _REFRESH_STATE["current_page"] = 0
                _REFRESH_STATE["current_source_total_pages"] = 0
                _REFRESH_STATE["updated_at"] = datetime.fromisoformat(result["updated_at"]) if result["updated_at"] else datetime.now(timezone.utc)
                _REFRESH_STATE["items_count"] = result["cache_count"]
        except MircrewRefreshCancelled as exc:
            result = exc.result or {}
            logger.warning("mircrew single-source refresh cancelled id=%s name=%s", source["id"], source["name"])
            with _REFRESH_LOCK:
                _REFRESH_STATE["cancelled"] = True
                _REFRESH_STATE["running"] = False
                _REFRESH_STATE["current_mode"] = None
                _REFRESH_STATE["current_page"] = 0
                _REFRESH_STATE["current_source_total_pages"] = 0
                _REFRESH_STATE["updated_at"] = datetime.fromisoformat(result["updated_at"]) if result.get("updated_at") else datetime.now(timezone.utc)
                _REFRESH_STATE["items_count"] = result.get("cache_count") or _REFRESH_STATE["items_count"]
        except mircrew_browser.MircrewBrowserAuthRequired as exc:
            logger.error("mircrew single-source refresh auth required id=%s name=%s error=%s", source["id"], source["name"], exc)
            with _REFRESH_LOCK:
                _REFRESH_STATE["error"] = str(exc)
                _REFRESH_STATE["running"] = False
                _REFRESH_STATE["updated_at"] = datetime.now(timezone.utc)
        except Exception as exc:
            logger.exception("mircrew single-source refresh failed id=%s name=%s url=%s", source["id"], source["name"], source["url"])
            with _REFRESH_LOCK:
                _REFRESH_STATE["error"] = f"{source['name']}: {exc}"
                _REFRESH_STATE["running"] = False
                _REFRESH_STATE["updated_at"] = datetime.now(timezone.utc)

    _REFRESH_THREAD = Thread(target=_run, daemon=True)
    _REFRESH_THREAD.start()
    return {"ok": True, **get_refresh_status()}


def test_source(source: dict[str, Any]) -> tuple[int, int]:
    merged: dict[str, dict[str, Any]] = {}
    count = _refresh_source_rows(source, merged, {}, datetime.now(timezone.utc).isoformat(), save_progress=False)
    return count, len(merged)


def refresh_single_source_cache(source: dict[str, Any], *, save_progress: bool = False) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    source_rows: dict[str, dict[str, Any]] = {}
    existing_rows = _read_cache_rows()
    existing = {
        str(row.get("release_id") or ""): row
        for row in existing_rows
        if str(row.get("release_id") or "").strip()
    }
    def _flush_checkpoint() -> dict[str, Any]:
        return _write_refresh_checkpoint(existing_rows, source_rows, now_iso)
    cancelled = False
    try:
        count = _refresh_source_rows(
            source,
            source_rows,
            existing,
            now_iso,
            save_progress=save_progress,
            checkpoint_callback=_flush_checkpoint,
        )
    except MircrewRefreshCancelled:
        count = len(source_rows)
        cancelled = True
    unique_count = len(source_rows)

    checkpoint = _flush_checkpoint()
    rows = checkpoint["rows"]
    payload = {
        "count": count,
        "unique_count": unique_count,
        "source_count": _count_source_rows(rows, source),
        "cache_count": checkpoint["count"],
        "updated_at": checkpoint.get("updated_at"),
    }
    if cancelled:
        raise MircrewRefreshCancelled(payload)
    return payload


def get_release_detail(release_id: str | None = None, release_url: str | None = None) -> dict[str, Any]:
    row = None
    rid = str(release_id or "").strip()
    if rid:
        row = get_release_by_id(rid)
    if row is None and release_url:
        row = {"release_id": rid or (_extract_topic_id(release_url) or ""), "release_url": release_url}
    if row is None or not row.get("release_url"):
        raise ValueError("release_not_found")

    release_key = str(row.get("release_id") or _extract_topic_id(str(row.get("release_url") or "")) or "").strip()
    cached = _get_detail_cache(release_key)
    if cached is not None:
        return {
            "ok": True,
            "cache_hit": True,
            "release_id": release_key,
            "release_url": row.get("release_url"),
            "created_at": row_created_at(row),
            **cached,
        }

    detail = _resolve_release_detail(str(row.get("release_url") or ""), release_key)
    _set_detail_cache(release_key, detail)
    return {
        "ok": True,
        "cache_hit": False,
        "release_id": release_key,
        "release_url": row.get("release_url"),
        "created_at": row_created_at(row),
        **detail,
    }


def _refresh_source_rows(
    source: dict[str, Any],
    merged: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
    now_iso: str,
    *,
    save_progress: bool = True,
    checkpoint_callback=None,
) -> int:
    base_url = str(source["url"])
    page_url = base_url
    page_cache: dict[str, dict[str, Any]] = {}
    counted_pages: set[str] = set()
    count = 0
    max_pages = _refresh_max_pages()
    jump_pages = _refresh_jump_pages()
    flush_pages = _refresh_flush_pages()
    source_new_items = 0
    mode = "scan"
    jump_resume_after_start: int | None = None
    last_known_start: int | None = None
    iterations = 0
    max_iterations = max_pages * 4

    while page_url and iterations < max_iterations:
        if _CANCEL_EVENT.is_set():
            raise MircrewRefreshCancelled()
        iterations += 1
        if not page_url:
            break

        cached = page_cache.get(page_url)
        if cached is None:
            logger.info("mircrew refresh page fetch source=%s mode=%s url=%s", source.get("name"), mode, page_url)
            html = mircrew_browser.fetch_html(page_url)
            doc = _validate_list_page_html(html, str(source.get("name") or "MirCrew source"))
            next_page_url = _find_next_page_url(doc, page_url)
            page_rows = _extract_release_links(doc, page_url, source)
            cached = {
                "rows": page_rows,
                "next_page_url": next_page_url,
                "start_offset": _get_start_offset(page_url),
                "page_step": _detect_page_step(doc, page_url),
            }
            cached["total_pages"] = _detect_total_pages(doc, page_url, int(cached["page_step"]))
            page_cache[page_url] = cached
        page_rows = list(cached["rows"])
        current_start = int(cached["start_offset"])
        page_step = int(cached["page_step"])
        total_pages = int(cached.get("total_pages") or 0)
        next_page_url = cached["next_page_url"]

        known_ids_before = set(existing.keys()) | set(merged.keys())
        page_topic_ids = [str(row.get("release_id") or "") for row in page_rows if str(row.get("release_id") or "").strip()]
        page_is_known = bool(page_topic_ids) and all(topic_id in known_ids_before for topic_id in page_topic_ids)
        logger.info(
            "mircrew refresh page parsed source=%s page=%s/%s mode=%s rows=%s known=%s start=%s",
            source.get("name"),
            max(1, current_start // max(1, page_step) + 1),
            total_pages,
            mode,
            len(page_rows),
            page_is_known,
            current_start,
        )

        if page_url not in counted_pages:
            count += len(page_rows)
            counted_pages.add(page_url)
            if checkpoint_callback and len(counted_pages) % flush_pages == 0:
                logger.info(
                    "mircrew refresh checkpoint trigger source=%s pages_scanned=%s flush_pages=%s merged_items=%s",
                    source.get("name"),
                    len(counted_pages),
                    flush_pages,
                    len(merged),
                )
                checkpoint_callback()
        for row in page_rows:
            release_id = str(row.get("release_id") or "")
            if not release_id:
                continue
            current = merged.get(release_id) or existing.get(release_id)
            if current:
                merged[release_id] = _merge_release_row(current, row, now_iso)
            else:
                row["first_seen_at"] = now_iso
                row["last_seen_at"] = now_iso
                merged[release_id] = row
                source_new_items += 1

        if save_progress:
            with _REFRESH_LOCK:
                _REFRESH_STATE["current_mode"] = mode
                _REFRESH_STATE["current_page"] = max(1, current_start // max(1, page_step) + 1)
                _REFRESH_STATE["current_source_total_pages"] = total_pages
                _REFRESH_STATE["pages_scanned"] = len(counted_pages)
                _REFRESH_STATE["current_source_new_items"] = source_new_items
                _REFRESH_STATE["items_count"] = len(merged)
                _REFRESH_STATE["updated_at"] = datetime.now(timezone.utc)

        if jump_resume_after_start is not None and current_start >= jump_resume_after_start:
            jump_resume_after_start = None

        if mode == "scan":
            if jump_resume_after_start is None and page_is_known:
                last_known_start = current_start
                page_url, mode = _resolve_next_jump_url(
                    base_url,
                    current_start,
                    page_step,
                    jump_pages,
                    total_pages,
                    next_page_url,
                )
                logger.info(
                    "mircrew refresh mode change source=%s from=scan to=%s current_start=%s next_url=%s",
                    source.get("name"),
                    mode,
                    current_start,
                    page_url,
                )
            else:
                page_url = next_page_url
            continue

        # jump mode
        if page_is_known:
            last_known_start = current_start
            page_url, mode = _resolve_next_jump_url(
                base_url,
                current_start,
                page_step,
                jump_pages,
                total_pages,
                next_page_url,
            )
            logger.info(
                "mircrew refresh jump continue source=%s current_start=%s next_url=%s",
                source.get("name"),
                current_start,
                page_url,
            )
        else:
            rollback_start = (last_known_start or 0) + page_step
            mode = "scan"
            jump_resume_after_start = current_start
            page_url = _build_page_url(base_url, rollback_start)
            logger.info(
                "mircrew refresh rollback source=%s rollback_start=%s resume_after=%s",
                source.get("name"),
                rollback_start,
                jump_resume_after_start,
            )
    logger.info(
        "mircrew refresh source loop done source=%s counted_pages=%s rows_seen=%s new_items=%s iterations=%s",
        source.get("name"),
        len(counted_pages),
        count,
        source_new_items,
        iterations,
    )
    return count


def _merge_release_row(current: dict[str, Any], incoming: dict[str, Any], now_iso: str) -> dict[str, Any]:
    merged = dict(current)
    merged.update(incoming)
    merged["first_seen_at"] = current.get("first_seen_at") or now_iso
    merged["last_seen_at"] = now_iso

    # Keep previously known detail/list metadata when the new list page does not expose it.
    preserve_if_missing = (
        "size_text_raw",
        "size_bytes",
        "detail_status",
        "detail_updated_at",
        "detail_error",
        "thanks_required",
        "thanks_clicked",
        "magnet_links",
        "torrent_links",
        "magnet_info",
        "release_posted_at_text",
        "release_posted_at_ms",
    )
    for key in preserve_if_missing:
        new_value = incoming.get(key)
        old_value = current.get(key)
        if new_value in (None, "", [], {}):
            if old_value not in (None, "", [], {}):
                merged[key] = old_value
    return merged


def _get_detail_cache(release_id: str) -> dict[str, Any] | None:
    if not release_id:
        return None
    ttl = _detail_cache_ttl_seconds()
    with _DETAIL_CACHE_LOCK:
        payload = _DETAIL_CACHE.get(release_id)
        if not payload:
            return None
        expires_at = payload.get("_expires_at", 0)
        if not isinstance(expires_at, (int, float)) or expires_at < datetime.now(timezone.utc).timestamp():
            _DETAIL_CACHE.pop(release_id, None)
            return None
        result = dict(payload)
        result.pop("_expires_at", None)
        return result


def _set_detail_cache(release_id: str, detail: dict[str, Any]) -> None:
    if not release_id:
        return
    payload = dict(detail)
    payload["_expires_at"] = datetime.now(timezone.utc).timestamp() + _detail_cache_ttl_seconds()
    with _DETAIL_CACHE_LOCK:
        _DETAIL_CACHE[release_id] = payload


def _resolve_release_detail(release_url: str, release_id: str) -> dict[str, Any]:
    html = mircrew_browser.fetch_html(release_url, wait_until="networkidle")
    doc = _validate_list_page_html(html, f"MirCrew release {release_id or release_url}")
    magnets = _extract_magnets(doc, release_url)
    torrents = _extract_torrent_links(doc, release_url)
    swarm = _extract_swarm_stats(doc)
    thanks_url = _find_thanks_url(doc, release_url)
    thanks_clicked = False
    if not magnets and not torrents and thanks_url:
        thanks_html = mircrew_browser.fetch_html(thanks_url, wait_until="networkidle")
        thanks_doc = _validate_list_page_html(thanks_html, f"MirCrew release {release_id or release_url}")
        magnets = _extract_magnets(thanks_doc, release_url)
        torrents = _extract_torrent_links(thanks_doc, release_url)
        doc = thanks_doc
        swarm = _extract_swarm_stats(thanks_doc) or swarm
        thanks_clicked = True
    size_text_raw, size_bytes = _extract_size(doc)
    magnet_infos = [_parse_magnet_info(magnet) for magnet in magnets]
    magnet_infos = [info for info in magnet_infos if info]
    magnet_size_values = [
        int(info["size_bytes"])
        for info in magnet_infos
        if info.get("size_bytes") not in (None, "", 0)
    ]
    final_size_bytes = sum(magnet_size_values) if magnet_size_values else size_bytes
    has_download_links = bool(magnets or torrents)
    return {
        "magnet_links": magnets,
        "torrent_links": torrents,
        "size_text_raw": size_text_raw,
        "size_bytes": final_size_bytes,
        "seeders": swarm.get("seeders"),
        "leechers": swarm.get("leechers"),
        "peers": swarm.get("peers"),
        "thanks_required": bool(thanks_url),
        "thanks_clicked": thanks_clicked,
        "detail_status": "ok" if has_download_links else "incomplete",
        "detail_error": None if has_download_links else "NO_DOWNLOAD_LINKS",
        "detail_updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _extract_magnets(doc: BeautifulSoup, page_url: str) -> list[str]:
    links: list[str] = []
    for anchor in doc.select("a[href]"):
        href = _normalize_whitespace(anchor.get("href") or "")
        if href.lower().startswith("magnet:"):
            links.append(urljoin(page_url, href))
    for node in doc.select("pre code, .codebox code, .codebox, pre"):
        raw = str(node.get_text("\n", strip=True) or "")
        matches = re.findall(r"magnet:\?[^\s\"'<>]+", raw, flags=re.IGNORECASE)
        for match in matches:
            links.append(match.replace("&amp;", "&").strip())
    if not links:
        body_text = doc.get_text(" ", strip=True)
        for match in re.findall(r"magnet:\?[^\s\"'<>]+", body_text, flags=re.IGNORECASE):
            links.append(match.replace("&amp;", "&").strip())
    return list(dict.fromkeys(link for link in links if link))


def _extract_torrent_links(doc: BeautifulSoup, page_url: str) -> list[str]:
    links: list[str] = []
    for anchor in doc.select("a[href]"):
        href = _normalize_whitespace(anchor.get("href") or "")
        if not href or href.lower().startswith("magnet:"):
            continue
        full = urljoin(page_url, href)
        try:
            parsed = urlsplit(full)
        except Exception:
            continue
        path = (parsed.path or "").lower()
        if path.endswith(".torrent"):
            links.append(full)
            continue
        query = parse_qs(parsed.query)
        if any(str(value or "").lower().endswith(".torrent") for values in query.values() for value in values):
            links.append(full)
    return list(dict.fromkeys(link for link in links if link))


def _find_thanks_url(doc: BeautifulSoup, page_url: str) -> str | None:
    node = (
        doc.select_one('a[id^="lnk_thanks_post"]')
        or doc.select_one('a[href*="thanks="]')
        or doc.select_one('a[href*="thank"]')
    )
    if not node or not node.get("href"):
        return None
    return urljoin(page_url, node.get("href"))


def _parse_magnet_info(magnet: str | None) -> dict[str, Any] | None:
    if not magnet:
        return None
    try:
        query = magnet.split("?", 1)[1] if "?" in magnet else ""
        params = parse_qs(query)
        display_name = params.get("dn", [""])[0] or ""
        size_bytes = _safe_int(params.get("xl", [""])[0])
        return {
            "display_name": unquote(display_name),
            "size_bytes": size_bytes if size_bytes and size_bytes > 0 else None,
        }
    except Exception:
        return None


def _extract_swarm_stats(doc: BeautifulSoup) -> dict[str, int | None]:
    node = doc.select_one("#magnetData")
    html = str(node or doc)
    text = node.get_text(" ", strip=True) if node else doc.get_text(" ", strip=True)

    def _match_stat(label: str) -> int | None:
        patterns = (
            rf"{label}\s*:\s*<strong[^>]*>\s*(\d+)\s*</strong>",
            rf"{label}\s*:\s*(\d+)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                value = _safe_int(match.group(1))
                if value is not None:
                    return value
        match = re.search(rf"\b{label}\s*:\s*(\d+)\b", text, flags=re.IGNORECASE)
        return _safe_int(match.group(1)) if match else None

    seeders = _match_stat("Seed")
    leechers = _match_stat("Leech")
    peers = None
    if seeders is not None or leechers is not None:
        peers = (seeders or 0) + (leechers or 0)
    return {
        "seeders": seeders,
        "leechers": leechers,
        "peers": peers,
    }


def _extract_size(doc: BeautifulSoup) -> tuple[str | None, int | None]:
    # MirCrew can include unrelated size strings in thanks/quotes/reply metadata
    # elsewhere in the page. Restrict extraction to the first release post block.
    for selector in (".content", ".postbody", ".entry-content", ".post"):
        nodes = doc.select(selector)
        if not nodes:
            continue
        text = nodes[0].get_text(" ", strip=True)
        strong_patterns = (
            r"Dimensione\s*:\s*[\d.,\s]+\s*bytes\s*\(([^)]+)\)",
            r"File size\s*:\s*([^\n\r]+?\b(?:TB|GB|MB|KB|B|TiB|GiB|MiB|KiB)\b)",
        )
        for pattern in strong_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            raw = _normalize_whitespace(match.group(1))
            parsed = _parse_size_text_to_bytes(raw)
            if parsed:
                return raw, parsed

        for match in _SIZE_RE.finditer(text):
            raw = _normalize_whitespace(match.group(0))
            start = match.start()
            end = match.end()
            context_after = text[end:end + 8].lower()
            context_before = text[max(0, start - 24):start].lower()
            context_window = f"{context_before} {context_after}"
            if "/s" in context_after or "bitrate" in context_window or " kb/s" in context_window or " mb/s" in context_window:
                continue
            parsed = _parse_size_text_to_bytes(raw)
            if parsed:
                return raw, parsed
    return None, None
