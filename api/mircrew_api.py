import json
import os
import re
from datetime import datetime
from typing import Any

_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
_CACHE_FILE = os.path.join(_DATA_DIR, "mircrew_releases.json")
_META_FILE = os.path.join(_DATA_DIR, "mircrew_releases.meta.json")

_cache_rows: list[dict[str, Any]] | None = None
_cache_mtime: float | None = None


def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _clean_title(raw_title: str) -> str:
    title = _normalize_whitespace(raw_title)
    if not title:
        return title

    title = re.sub(r"\[[^\]]*\]", " ", title)
    title = re.sub(r"\([^)]*(?:1080p|720p|2160p|x264|x265|h\.265|h264|web-dl|bluray|bdrip|dvdrip|webrip|ac3|aac|dts|ita|eng|sub)[^)]*\)", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:1080p|720p|2160p|x264|x265|h\.265|h264|web-dl|bluray|bdrip|dvdrip|webrip|ac3|aac|dts|ita|eng|sub-?ita)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+[\-\|]\s+.*$", "", title)
    title = _normalize_whitespace(title)
    return title or _normalize_whitespace(raw_title)


def _extract_year(text: str) -> int | None:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    if not m:
        return None
    year = _safe_int(m.group(1))
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
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")


def _normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    rid = str(raw.get("release_id") or "").strip()
    release_url = str(raw.get("release_url") or "").strip()
    title_hint = _normalize_whitespace(str(raw.get("title_hint") or ""))
    clean_title = _clean_title(title_hint)

    return {
        "release_id": rid,
        "release_url": release_url,
        "title_hint": title_hint,
        "clean_title": clean_title,
        "category_label": str(raw.get("category_label") or "").strip(),
        "category_value": str(raw.get("category_value") or "").strip(),
        "size_bytes": _safe_int(raw.get("size_bytes")),
        "size_text_raw": str(raw.get("size_text_raw") or "").strip() or None,
        "detail_status": str(raw.get("detail_status") or "").strip() or None,
    }


def _write_meta(count: int, updated_at: str | None) -> None:
    meta = {"count": count, "updated_at": updated_at}
    with open(_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def _read_meta() -> dict[str, Any]:
    if not os.path.exists(_META_FILE):
        return {"count": 0, "updated_at": None}
    try:
        with open(_META_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {
                    "count": _safe_int(data.get("count")) or 0,
                    "updated_at": data.get("updated_at"),
                }
    except Exception:  # noqa: BLE001
        pass
    return {"count": 0, "updated_at": None}


def save_imported_json(file_storage) -> dict[str, Any]:
    _ensure_data_dir()

    try:
        payload = json.load(file_storage.stream)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"JSON non valido: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError("Formato non valido: attesa una lista JSON")

    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        row = _normalize_row(item)
        if not row["release_id"] or not row["release_url"]:
            continue
        normalized.append(row)

    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False)

    st = os.stat(_CACHE_FILE)
    updated_at = _to_timestamp(st.st_mtime)
    _write_meta(len(normalized), updated_at)
    invalidate_cache()

    return {
        "count": len(normalized),
        "path": _CACHE_FILE,
        "updated_at": updated_at,
    }


def _load_cache() -> list[dict[str, Any]]:
    global _cache_rows, _cache_mtime

    if not os.path.exists(_CACHE_FILE):
        _cache_rows = []
        _cache_mtime = None
        return _cache_rows

    st = os.stat(_CACHE_FILE)
    if _cache_rows is not None and _cache_mtime == st.st_mtime:
        return _cache_rows

    with open(_CACHE_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    rows = payload if isinstance(payload, list) else []
    _cache_rows = rows
    _cache_mtime = st.st_mtime
    return rows


def invalidate_cache() -> None:
    global _cache_rows, _cache_mtime
    _cache_rows = None
    _cache_mtime = None


def get_status() -> dict[str, Any]:
    if not os.path.exists(_CACHE_FILE):
        return {
            "exists": False,
            "count": 0,
            "updated_at": None,
            "cache_loaded": _cache_rows is not None,
            "path": _CACHE_FILE,
        }

    meta = _read_meta()
    return {
        "exists": True,
        "count": meta.get("count", 0),
        "updated_at": meta.get("updated_at"),
        "cache_loaded": _cache_rows is not None,
        "path": _CACHE_FILE,
    }


def search(query: str, limit: int = 250) -> list[dict[str, Any]]:
    text = _normalize_whitespace(query).lower()
    if not text:
        return []

    terms = [t for t in text.split(" ") if t]
    rows = _load_cache()

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        hay_clean = (row.get("clean_title") or "").lower()
        hay_full = (row.get("title_hint") or "").lower()

        if not all(term in hay_full or term in hay_clean for term in terms):
            continue

        score = 0
        if text in hay_clean:
            score += 4
        if text in hay_full:
            score += 2
        score += max(0, 5 - abs(len(hay_clean) - len(text)) // 10)
        scored.append((score, row))

    scored.sort(key=lambda x: (-x[0], (x[1].get("clean_title") or "")))
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


def get_release_by_id(release_id: str) -> dict[str, Any] | None:
    rid = str(release_id or "").strip()
    if not rid:
        return None
    for row in _load_cache():
        if str(row.get("release_id") or "") == rid:
            return row
    return None
