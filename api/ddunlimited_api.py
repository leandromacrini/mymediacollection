import html as html_lib
import json
import os
import re
import unicodedata
from urllib.parse import unquote
from dataclasses import asdict
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process

from core import db_core

# ===== CONFIG =====
DDU_BASE_URL = "https://ddunlimited.net"
REQUEST_TIMEOUT = 10
# ==================

_CACHE_FILE = os.path.join("data", "ddunlimited_cache.json")
_CACHE_LOCK = RLock()
_CACHE = {
    "items": {},
    "updated_at": None,
    "sources": 0
}

_REFRESH_LOCK = RLock()
_REFRESH_STATE = {
    "running": False,
    "total_sources": 0,
    "processed_sources": 0,
    "current_source": None,
    "items_count": 0,
    "started_at": None,
    "updated_at": None,
    "cancelled": False,
    "error": None
}
_CANCEL_EVENT = Event()
_REFRESH_THREAD: Thread | None = None


@dataclass
class DDUListSource:
    name: str
    url: str
    media_type: str
    category: str | None = None
    quality: str | None = None
    language: str | None = None


@dataclass
class DDUItem:
    title: str
    detail_url: str
    topic_id: str | None
    info: str | None = None
    quality: str | None = None
    language: str | None = None
    media_type: str | None = None
    category: str | None = None
    year: int | None = None
    source_name: str | None = None
    status: str | None = None


def _get_config(db: db_core.MediaDB | None = None) -> dict:
    cfg = db.get_service_config("DDUnlimited") if db else {}
    base_url = (cfg.get("ddunlimited_url") or DDU_BASE_URL).rstrip("/")
    username = cfg.get("ddunlimited_username") or ""
    password = cfg.get("ddunlimited_password") or ""
    return {
        "base_url": base_url,
        "username": username,
        "password": password
    }


def ddu_get_sources(db: db_core.MediaDB | None = None) -> list[DDUListSource]:
    if db is None:
        return []
    rows = db.get_ddunlimited_sources(include_disabled=False)
    sources = []
    for row in rows:
        sources.append(DDUListSource(
            name=row.get("name"),
            url=row.get("url"),
            media_type=row.get("media_type"),
            category=row.get("category"),
            quality=row.get("quality"),
            language=row.get("language")
        ))
    return sources


def _build_session(db: db_core.MediaDB | None = None) -> tuple[requests.Session, dict]:
    cfg = _get_config(db)
    session = requests.Session()
    session.headers.update({"User-Agent": "MyMediaCollection/1.0"})
    username = cfg["username"]
    password = cfg["password"]
    if username and password:
        login_url = f"{cfg['base_url']}/ucp.php?mode=login"
        payload = {
            "username": username,
            "password": password,
            "login": "Login"
        }
        try:
            session.post(login_url, data=payload, timeout=REQUEST_TIMEOUT)
        except Exception:
            pass
    return session, cfg


def ddu_test_connection(
    db: db_core.MediaDB | None = None,
    url: str | None = None,
    username: str | None = None,
    password: str | None = None
) -> tuple[bool, str]:
    if url is None:
        cfg = _get_config(db)
        url = cfg["base_url"]
        username = cfg["username"]
        password = cfg["password"]
    if not url:
        return False, "DDUnlimited URL mancante."
    session = requests.Session()
    session.headers.update({"User-Agent": "MyMediaCollection/1.0"})
    if username and password:
        login_url = f"{url.rstrip('/')}/ucp.php?mode=login"
        payload = {
            "username": username,
            "password": password,
            "login": "Login"
        }
        try:
            session.post(login_url, data=payload, timeout=REQUEST_TIMEOUT)
        except Exception:
            pass
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403):
            return False, "DDUnlimited: credenziali non valide."
        return (r.status_code < 400, f"DDUnlimited status: {r.status_code}")
    except Exception as exc:
        return False, f"DDUnlimited error: {exc}"


def _fetch_html(url: str, session: requests.Session) -> str:
    r = session.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.text


def _extract_topic_id(url: str) -> str | None:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    topic_vals = qs.get("t")
    if topic_vals:
        return str(topic_vals[0])
    return None


def _parse_year(title: str) -> int | None:
    if not title:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _parse_language(text: str | None) -> str | None:
    if not text:
        return None
    upper = text.upper()
    if "ITA" in upper and "ENG" in upper and "JPN" in upper:
        return "ITA-ENG-JPN"
    if "ITA" in upper and "JPN" in upper:
        return "ITA-JPN"
    if "ITA" in upper and "ENG" in upper:
        return "ITA-ENG"
    if "ITALIANO" in upper or "ITA" in upper:
        return "ITA"
    if "INGLESE" in upper or "ENG" in upper:
        return "ENG"
    if "JPN" in upper or "JAP" in upper:
        return "JPN"
    return None


def _parse_quality(text: str | None) -> str | None:
    if not text:
        return None
    patterns = [
        r"\b2160p\b",
        r"\b1080p\b",
        r"\b720p\b",
        r"\b480p\b",
        r"\bBDRIP\b",
        r"\bBLU[-\s]?RAY\b",
        r"\bWEBRIP\b",
        r"\bWEB\b",
        r"\bHD\b",
        r"\bSD\b",
        r"\bMUX\b",
        r"\bRIP\b",
        r"\bFOUND\b",
        r"\bDVD\b",
        r"\bHDTV\b",
        r"\bDVB\b"
    ]
    upper = text.upper()
    for pat in patterns:
        match = re.search(pat, upper)
        if match:
            return match.group(0).replace(" ", "")
    return None


def parse_list_page(html: str, source: DDUListSource, base_url: str) -> list[DDUItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[DDUItem] = []
    seen_topics = set()

    for anchor in soup.find_all("a", href=True, class_="postlink-local"):
        href = anchor.get("href") or ""
        if href.startswith("#"):
            continue
        if "viewtopic.php" not in href or "t=" not in href:
            continue
        title = (anchor.get_text() or "").strip()
        if not title or len(title) < 3:
            continue
        if title.lower().startswith("lista"):
            continue

        detail_url = urljoin(base_url + "/", href)
        topic_id = _extract_topic_id(detail_url)
        if topic_id and topic_id in seen_topics:
            continue
        if topic_id:
            seen_topics.add(topic_id)

        info_text = None
        sibling_span = anchor.find_next_sibling("span")
        if sibling_span:
            info_text = sibling_span.get_text(" ", strip=True)
        quality = source.quality or _parse_quality(info_text)
        language = source.language or _parse_language(info_text)
        year = _parse_year(title)

        items.append(DDUItem(
            title=title,
            detail_url=detail_url,
            topic_id=topic_id,
            info=info_text,
            quality=quality,
            language=language,
            media_type=source.media_type,
            category=source.category,
            year=year,
            source_name=source.name
        ))

    return items


def search_lists(query: str, db: db_core.MediaDB | None = None, max_results: int = 200) -> list[DDUItem]:
    return search_cache(query, max_results=max_results)


def _merge_item(existing: DDUItem, incoming: DDUItem) -> DDUItem:
    if incoming.info and incoming.info not in (existing.info or ""):
        if existing.info:
            existing.info = f"{existing.info} | {incoming.info}"
        else:
            existing.info = incoming.info
    if not existing.quality and incoming.quality:
        existing.quality = incoming.quality
    if not existing.language and incoming.language:
        existing.language = incoming.language
    if not existing.year and incoming.year:
        existing.year = incoming.year
    if incoming.source_name and incoming.source_name not in (existing.source_name or ""):
        if existing.source_name:
            existing.source_name = f"{existing.source_name}, {incoming.source_name}"
        else:
            existing.source_name = incoming.source_name
    return existing

def start_refresh(db: db_core.MediaDB | None = None) -> dict:
    if db is None:
        return {"ok": False, "error": "missing_db"}
    global _REFRESH_THREAD
    with _REFRESH_LOCK:
        if _REFRESH_STATE["running"]:
            return {"ok": True, **get_refresh_status()}
        _CANCEL_EVENT.clear()
        _REFRESH_STATE.update({
            "running": True,
            "total_sources": 0,
            "processed_sources": 0,
            "current_source": None,
            "items_count": 0,
            "started_at": datetime.now(timezone.utc),
            "updated_at": None,
            "cancelled": False,
            "error": None
        })

    def _run():
        session, cfg = _build_session(db)
        merged: dict[str, DDUItem] = {}
        sources = ddu_get_sources(db)
        with _REFRESH_LOCK:
            _REFRESH_STATE["total_sources"] = len(sources)
        for source in sources:
            if _CANCEL_EVENT.is_set():
                with _REFRESH_LOCK:
                    _REFRESH_STATE["cancelled"] = True
                    _REFRESH_STATE["running"] = False
                return
            with _REFRESH_LOCK:
                _REFRESH_STATE["current_source"] = source.name
            try:
                html = _fetch_html(source.url, session)
            except Exception:
                with _REFRESH_LOCK:
                    _REFRESH_STATE["processed_sources"] += 1
                continue
            items = parse_list_page(html, source, cfg["base_url"])
            for item in items:
                key = item.detail_url or (item.topic_id or "")
                if not key:
                    continue
                existing = merged.get(key)
                if not existing:
                    merged[key] = item
                else:
                    merged[key] = _merge_item(existing, item)
            with _REFRESH_LOCK:
                _REFRESH_STATE["processed_sources"] += 1
                _REFRESH_STATE["items_count"] = len(merged)
        if _CANCEL_EVENT.is_set():
            with _REFRESH_LOCK:
                _REFRESH_STATE["cancelled"] = True
                _REFRESH_STATE["running"] = False
            return
        with _CACHE_LOCK:
            _CACHE["items"] = merged
            _CACHE["sources"] = len(sources)
            _CACHE["updated_at"] = datetime.now(timezone.utc)
            _save_cache_to_disk()
        with _REFRESH_LOCK:
            _REFRESH_STATE["running"] = False
            _REFRESH_STATE["updated_at"] = _CACHE["updated_at"]
            _REFRESH_STATE["items_count"] = len(merged)

    _REFRESH_THREAD = Thread(target=_run, daemon=True)
    _REFRESH_THREAD.start()
    return {"ok": True, **get_refresh_status()}


def cancel_refresh() -> dict:
    _CANCEL_EVENT.set()
    with _REFRESH_LOCK:
        if _REFRESH_STATE["running"]:
            _REFRESH_STATE["cancelled"] = True
        return get_refresh_status()


def get_refresh_status() -> dict:
    with _REFRESH_LOCK:
        started = _REFRESH_STATE["started_at"]
        updated = _REFRESH_STATE["updated_at"]
        return {
            "running": _REFRESH_STATE["running"],
            "total_sources": _REFRESH_STATE["total_sources"],
            "processed_sources": _REFRESH_STATE["processed_sources"],
            "current_source": _REFRESH_STATE["current_source"],
            "items_count": _REFRESH_STATE["items_count"],
            "started_at": started.isoformat() if started else None,
            "updated_at": updated.isoformat() if updated else None,
            "cancelled": _REFRESH_STATE["cancelled"],
            "error": _REFRESH_STATE["error"]
        }


def get_cache_status() -> dict:
    _load_cache_from_disk()
    with _CACHE_LOCK:
        updated = _CACHE["updated_at"]
        return {
            "count": len(_CACHE["items"]),
            "sources": _CACHE["sources"],
            "updated_at": updated.isoformat() if updated else None
        }


def search_cache(query: str, max_results: int = 200) -> list[DDUItem]:
    if not query:
        return []
    _load_cache_from_disk()
    def _normalize(value: str) -> str:
        if not value:
            return ""
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value.lower() if ch.isalnum() or ch.isspace())
        return " ".join(value.split())

    normalized_query = _normalize(query)
    stopwords = {
        "il", "lo", "la", "i", "gli", "le", "un", "una", "uno",
        "di", "da", "del", "della", "dello", "dei", "degli", "delle",
        "the", "a", "an", "and", "of"
    }
    query_tokens = [t for t in normalized_query.split() if t and t not in stopwords]
    with _CACHE_LOCK:
        items = list(_CACHE["items"].values())
    candidates = []
    filtered_items = []
    for item in items:
        base = _normalize(item.title or "")
        if item.info:
            base = f"{base} {_normalize(item.info[:200])}"
        if query_tokens and not all(token in base for token in query_tokens):
            continue
        candidates.append(base)
        filtered_items.append(item)

    if not candidates:
        return []

    matches = process.extract(
        normalized_query,
        candidates,
        scorer=fuzz.token_set_ratio,
        limit=max_results
    )
    results = []
    for _, score, idx in matches:
        if score < 78:
            continue
        results.append(filtered_items[idx])
    return results


def extract_ed2k_links(html: str) -> list[str]:
    links = []
    raw_html = html_lib.unescape(html)
    soup = BeautifulSoup(raw_html, "html.parser")
    content_nodes = soup.select(".postbody .content")
    content = None
    for node in content_nodes:
        node_html = str(node)
        if "ed2k://|file|" in node_html or "filearray" in node_html:
            content = node_html
            break
    if content is None and content_nodes:
        content = str(content_nodes[0])
    if content is None:
        content = raw_html
    html = html_lib.unescape(content).replace("\r", "").replace("\n", "")

    href_pattern = r"""href=(['"])(ed2k://\|file\|.*?\|/)\1"""
    href_matches = re.findall(href_pattern, html, flags=re.IGNORECASE)

    filearray_pattern = r"""filearray\d+\[\d+\]\s*=\s*(['"])(ed2k://\|file\|.*?\|/)\1"""
    filearray_matches = re.findall(filearray_pattern, html, flags=re.IGNORECASE)

    loose_pattern = r"""ed2k://\|file\|[^|<>"]+\|\d+\|[0-9A-Fa-f]+\|[^"<>]*?\|/"""
    loose_matches = re.findall(loose_pattern, html, flags=re.IGNORECASE)

    if raw_html and "filearray" in raw_html and len(filearray_matches) < 5:
        fallback_html = raw_html.replace("\r", "").replace("\n", "")
        filearray_matches = re.findall(filearray_pattern, fallback_html, flags=re.IGNORECASE)

    ordered_links = []
    if filearray_matches:
        ordered_links.extend(filearray_matches)
        ordered_links.extend(href_matches)
        ordered_links.extend(loose_matches)
    else:
        ordered_links.extend(href_matches)
        ordered_links.extend(loose_matches)
        if raw_html and "ed2k://|file|" in raw_html and not ordered_links:
            fallback_html = raw_html.replace("\r", "").replace("\n", "")
            ordered_links.extend(re.findall(href_pattern, fallback_html, flags=re.IGNORECASE))
            ordered_links.extend(re.findall(loose_pattern, fallback_html, flags=re.IGNORECASE))
    links.extend(ordered_links)

    cleaned = []
    seen = set()
    for link in links:
        if isinstance(link, tuple):
            link = link[1]
        link = link.replace("\n", "").replace("\r", "")
        link = re.sub(r"\\s+", "", link)
        if not link.startswith("ed2k://|file|"):
            continue
        if "|/" not in link:
            continue
        if "<" in link or ">" in link:
            continue
        dedupe_key = link
        parts = link.split("|")
        if len(parts) >= 5 and parts[1] == "file" and parts[4]:
            dedupe_key = parts[4].lower()
        if link and dedupe_key not in seen:
            seen.add(dedupe_key)
            cleaned.append(link)
    return cleaned


def _parse_ed2k_link(link: str) -> dict:
    # ed2k://|file|NAME|SIZE|HASH|/
    name = link
    size = None
    parts = link.split("|")
    if len(parts) >= 5 and parts[1] == "file":
        name = unquote(parts[2]) if parts[2] else name
        size = parts[3] or None
    else:
        match = re.search(r"ed2k://\\|file\\|(.*?)\\|(\\d+)\\|", link, flags=re.IGNORECASE)
        if match:
            name = unquote(match.group(1)) if match.group(1) else name
            size = match.group(2) or None
    return {
        "link": link,
        "name": name,
        "size": size
    }


def _get_ed2k_stats(items: list[dict]) -> dict:
    total_bytes = 0
    for item in items:
        try:
            total_bytes += int(item.get("size") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "count": len(items),
        "total_bytes": total_bytes
    }


def _extract_detail_lines(info_text: str | None, max_lines: int = 6) -> list[str]:
    if not info_text:
        return []
    keywords = [
        "2160p", "1080p", "720p", "480p", "x264", "x265", "hevc", "avc",
        "ac3", "e-ac3", "dts", "aac", "flac", "mp3", "opus",
        "web", "webrip", "bluray", "blu-ray", "bdrip", "dvd", "hdtv", "mux",
        "ita", "eng", "jpn", "sub"
    ]
    lines = [line.strip() for line in info_text.splitlines() if line.strip()]
    matches = []
    for line in lines:
        lower = line.lower()
        if any(key in lower for key in keywords) and len(line) <= 160:
            matches.append(line)
        if len(matches) >= max_lines:
            break
    if matches:
        return matches
    short_lines = [line for line in lines if len(line) <= 140]
    return short_lines[:max_lines]


def _save_cache_to_disk() -> None:
    with _CACHE_LOCK:
        items = [asdict(item) for item in _CACHE["items"].values()]
        payload = {
            "updated_at": _CACHE["updated_at"].isoformat() if _CACHE["updated_at"] else None,
            "sources": _CACHE["sources"],
            "items": items
        }
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True)
    except OSError:
        pass


def _load_cache_from_disk() -> None:
    with _CACHE_LOCK:
        if _CACHE["items"] or _CACHE["updated_at"]:
            return
    if not os.path.exists(_CACHE_FILE):
        return
    print(f"DDU cache load start: {_CACHE_FILE}")
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        print("DDU cache load failed.")
        return
    items = {}
    for raw in payload.get("items", []):
        try:
            item = DDUItem(**raw)
        except TypeError:
            continue
        key = item.detail_url or (item.topic_id or "")
        if key:
            items[key] = item
    updated_at = payload.get("updated_at")
    try:
        updated_dt = datetime.fromisoformat(updated_at) if updated_at else None
    except ValueError:
        updated_dt = None
    with _CACHE_LOCK:
        if not _CACHE["items"] and not _CACHE["updated_at"]:
            _CACHE["items"] = items
            _CACHE["sources"] = payload.get("sources", 0)
            _CACHE["updated_at"] = updated_dt
    print(f"DDU cache load done: {len(items)} items")


def get_release_ed2k(detail_url: str, db: db_core.MediaDB | None = None) -> dict:
    session, cfg = _build_session(db)
    html = _fetch_html(detail_url, session)
    ed2k_links = extract_ed2k_links(html)
    parsed_links = [_parse_ed2k_link(link) for link in ed2k_links]
    stats = _get_ed2k_stats(parsed_links)
    return {
        "ed2k_links": ed2k_links,
        "ed2k_items": parsed_links,
        "ed2k_stats": stats,
        "base_url": cfg["base_url"]
    }
