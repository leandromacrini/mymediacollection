import logging
import os
import re
import subprocess
import time
from copy import deepcopy
from typing import Any


logger = logging.getLogger(__name__)

_CACHE: dict[str, dict[str, Any]] = {}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _settings() -> dict[str, Any]:
    return {
        "filebot_path": (os.getenv("FILEBOT_PATH") or "filebot").strip(),
        "filebot_lang": (os.getenv("FILEBOT_LANG") or "it").strip() or "it",
        "filebot_timeout": max(1, _env_int("FILEBOT_TIMEOUT", 4)),
        "filebot_cache_ttl_seconds": max(0, _env_int("FILEBOT_CACHE_TTL_SECONDS", 7 * 24 * 60 * 60)),
        "filebot_empty_cache_ttl_seconds": max(0, _env_int("FILEBOT_EMPTY_CACHE_TTL_SECONDS", 60)),
        "filebot_cache_max": max(0, _env_int("FILEBOT_CACHE_MAX", 1000)),
    }


def _is_meaningful_title(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if set(text) <= {"?"}:
        return False
    if not re.sub(r"[\W_]+", "", text, flags=re.UNICODE):
        return False
    return True


def _parse_aliases(raw: str | None) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    aliases: list[str] = []
    for token in text.split(","):
        alias = token.strip().strip("'\"")
        if not _is_meaningful_title(alias):
            continue
        aliases.append(alias)
    return aliases


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value).strip()
        if not _is_meaningful_title(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str | None, str | None, str | None] | tuple[str, str | None]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        title = item.get("title")
        if not _is_meaningful_title(title):
            continue
        year = str(item.get("year")).strip() if item.get("year") else None
        ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        tvdbid = str(ids.get("tvdbid")).strip() if ids.get("tvdbid") else None
        tmdbid = str(ids.get("tmdbid")).strip() if ids.get("tmdbid") else None
        imdbid = str(ids.get("imdbid")).strip().lower() if ids.get("imdbid") else None
        key = (
            (tvdbid, tmdbid, imdbid)
            if any((tvdbid, tmdbid, imdbid))
            else (str(title).strip().casefold(), year)
        )
        if key in seen:
            continue
        seen.add(key)
        aliases = item.get("aliases")
        alias_values = aliases if isinstance(aliases, list) else []
        alias_values = _dedupe_strings([str(alias) for alias in alias_values if alias is not None])
        alias_values = [alias for alias in alias_values if alias.casefold() != str(title).strip().casefold()]
        deduped.append(
            {
                "title": str(title).strip(),
                "year": year,
                "aliases": alias_values,
                "ids": {
                    "tvdbid": tvdbid,
                    "tmdbid": tmdbid,
                    "imdbid": imdbid,
                },
            }
        )
    return deduped


def _cache_get(key: str, ttl: int, empty_ttl: int) -> tuple[list[dict[str, Any]] | None, bool]:
    now = time.time()
    cached = _CACHE.get(key)
    if not cached:
        return None, False
    age = now - float(cached.get("ts", 0))
    if ttl > 0 and age > ttl:
        return None, False
    items = cached.get("items")
    if not isinstance(items, list):
        return None, False
    if not items and empty_ttl > 0 and age >= empty_ttl:
        return None, False
    return list(items), True


def _cache_set(key: str, items: list[dict[str, Any]], limit: int) -> None:
    _CACHE[key] = {"ts": time.time(), "items": deepcopy(items)}
    if limit <= 0 or len(_CACHE) <= limit:
        return
    ordered = sorted(_CACHE.items(), key=lambda item: item[1].get("ts", 0))
    for old_key, _ in ordered[: max(len(_CACHE) - limit, 0)]:
        _CACHE.pop(old_key, None)


def _normalize_imdbid(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text.startswith("tt") and text[2:].isdigit():
        return text
    if text.isdigit():
        return f"tt{text}"
    return None


def _normalize_numeric_id(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or not text.isdigit():
        return None
    return text


def _build_item(
    title: str,
    year: str | None,
    aliases: list[str],
    tvdbid: str | None = None,
    tmdbid: str | None = None,
    imdbid: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "year": year or None,
        "aliases": aliases,
        "ids": {
            "tvdbid": _normalize_numeric_id(tvdbid),
            "tmdbid": _normalize_numeric_id(tmdbid),
            "imdbid": _normalize_imdbid(imdbid),
        },
    }


def _parse_series_line(parts: list[str]) -> dict[str, Any] | None:
    title = parts[0].strip() if parts else ""
    year = parts[1].strip() if len(parts) > 1 else ""
    alias_raw = parts[2].strip() if len(parts) > 2 else ""
    tvdbid = parts[3].strip() if len(parts) > 3 else ""
    imdbid = parts[4].strip() if len(parts) > 4 else ""
    if not _is_meaningful_title(title):
        return None
    return _build_item(
        title=title,
        year=year or None,
        aliases=_parse_aliases(alias_raw),
        tvdbid=tvdbid,
        imdbid=imdbid,
    )


def _parse_movie_line(parts: list[str]) -> dict[str, Any] | None:
    title = parts[0].strip() if parts else ""
    year = parts[1].strip() if len(parts) > 1 else ""
    alias_raw = parts[2].strip() if len(parts) > 2 else ""
    tmdbid = parts[3].strip() if len(parts) > 3 else ""
    imdbid = parts[4].strip() if len(parts) > 4 else ""
    if not _is_meaningful_title(title):
        return None
    return _build_item(
        title=title,
        year=year or None,
        aliases=_parse_aliases(alias_raw),
        tmdbid=tmdbid,
        imdbid=imdbid,
    )


def _run_filebot(cmd: list[str], lookup_key: str, media_type: str) -> list[dict[str, Any]]:
    cfg = _settings()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg["filebot_timeout"],
            check=False,
        )
    except FileNotFoundError:
        logger.warning("media_resolver filebot missing path=%s", cfg["filebot_path"])
        return []
    except subprocess.TimeoutExpired:
        logger.warning("media_resolver filebot timeout key=%s timeout=%s", lookup_key, cfg["filebot_timeout"])
        return []
    except Exception as exc:
        logger.warning("media_resolver filebot failed key=%s error=%s", lookup_key, exc)
        return []

    if result.returncode != 0:
        logger.warning(
            "media_resolver filebot nonzero key=%s code=%s stderr=%s",
            lookup_key,
            result.returncode,
            (result.stderr or "").strip(),
        )
        return []

    items: list[dict[str, Any]] = []
    for line in (result.stdout or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = raw.split("\t")
        item = _parse_movie_line(parts) if media_type == "movie" else _parse_series_line(parts)
        if item:
            items.append(item)

    deduped = _dedupe_items(items)
    logger.info("media_resolver filebot ok key=%s items=%d", lookup_key, len(deduped))
    return deduped


def resolve_series(tvdbid: str | None) -> dict[str, Any]:
    tvdb = (tvdbid or "").strip()
    if not tvdb:
        return {"ok": False, "error": "missing_tvdbid"}
    cfg = _settings()
    key = f"series:tvdb:{tvdb}:lang:{cfg['filebot_lang']}"
    items, cache_hit = _cache_get(key, cfg["filebot_cache_ttl_seconds"], cfg["filebot_empty_cache_ttl_seconds"])
    if items is None:
        cmd = [
            cfg["filebot_path"],
            "-list",
            "--db",
            "TheTVDB",
            "--q",
            tvdb,
            "--lang",
            cfg["filebot_lang"],
            "--format",
            "{n}\t{y}\t{alias}\t{id}\t{imdbid}",
        ]
        items = _run_filebot(cmd, key, "series")
        _cache_set(key, items, cfg["filebot_cache_max"])
    return {
        "ok": True,
        "items": items,
        "meta": {
            "provider": "filebot",
            "media_type": "series",
            "lookup": {"tvdbid": tvdb},
            "cache_hit": cache_hit,
            "lang_used": cfg["filebot_lang"],
        },
    }


def resolve_movie(tmdbid: str | None, imdbid: str | None) -> dict[str, Any]:
    cfg = _settings()
    tmdb = (tmdbid or "").strip()
    imdb = (imdbid or "").strip().lower()
    if imdb and not imdb.startswith("tt") and imdb.isdigit():
        imdb = f"tt{imdb}"
    if tmdb:
        query = tmdb
        cache_key = f"movie:tmdb:{tmdb}:lang:{cfg['filebot_lang']}"
    elif imdb:
        query = imdb
        cache_key = f"movie:imdb:{imdb}:lang:{cfg['filebot_lang']}"
    else:
        return {"ok": False, "error": "missing_tmdbid_or_imdbid"}

    items, cache_hit = _cache_get(
        cache_key,
        cfg["filebot_cache_ttl_seconds"],
        cfg["filebot_empty_cache_ttl_seconds"],
    )
    if items is None:
        cmd = [
            cfg["filebot_path"],
            "-list",
            "--db",
            "TheMovieDB",
            "--q",
            query,
            "--lang",
            cfg["filebot_lang"],
            "--format",
            "{n}\t{y}\t{alias}\t{tmdbid}\t{imdbid}",
        ]
        items = _run_filebot(cmd, cache_key, "movie")
        _cache_set(cache_key, items, cfg["filebot_cache_max"])

    return {
        "ok": True,
        "items": items,
        "meta": {
            "provider": "filebot",
            "media_type": "movie",
            "lookup": {"tmdbid": tmdb or None, "imdbid": imdb or None},
            "cache_hit": cache_hit,
            "lang_used": cfg["filebot_lang"],
        },
    }


def resolve_by_title(query: str | None, media_type: str | None) -> dict[str, Any]:
    q = " ".join((query or "").split()).strip()
    kind = (media_type or "").strip().lower()
    if not q:
        return {"ok": False, "error": "missing_query"}
    if kind not in {"series", "movie", "anime", "tv"}:
        return {"ok": False, "error": "invalid_type"}

    cfg = _settings()
    db_name = "TheMovieDB" if kind == "movie" else "TheTVDB"
    normalized_kind = "movie" if kind == "movie" else "series"
    cache_key = f"title:{normalized_kind}:{q.casefold()}:lang:{cfg['filebot_lang']}"
    items, cache_hit = _cache_get(
        cache_key,
        cfg["filebot_cache_ttl_seconds"],
        cfg["filebot_empty_cache_ttl_seconds"],
    )
    if items is None:
        cmd = [
            cfg["filebot_path"],
            "-list",
            "--db",
            db_name,
            "--q",
            q,
            "--lang",
            cfg["filebot_lang"],
            "--format",
            "{n}\t{y}\t{alias}\t{tmdbid}\t{imdbid}" if normalized_kind == "movie" else "{n}\t{y}\t{alias}\t{id}\t{imdbid}",
        ]
        items = _run_filebot(cmd, cache_key, normalized_kind)
        _cache_set(cache_key, items, cfg["filebot_cache_max"])

    return {
        "ok": True,
        "items": items,
        "meta": {
            "provider": "filebot",
            "media_type": normalized_kind,
            "lookup": {"q": q, "type": kind},
            "cache_hit": cache_hit,
            "lang_used": cfg["filebot_lang"],
        },
    }


def get_cache_stats() -> dict[str, Any]:
    now = time.time()
    samples: list[dict[str, Any]] = []
    for key, entry in sorted(_CACHE.items(), key=lambda item: item[1].get("ts", 0), reverse=True)[:20]:
        items = entry.get("items")
        item_count = len(items) if isinstance(items, list) else 0
        age_seconds = int(max(now - float(entry.get("ts", 0)), 0))
        samples.append({"key": key, "item_count": item_count, "age_seconds": age_seconds})
    return {"count": len(_CACHE), "items": samples}


def clear_cache() -> dict[str, Any]:
    count = len(_CACHE)
    _CACHE.clear()
    return {"ok": True, "cleared": count}
