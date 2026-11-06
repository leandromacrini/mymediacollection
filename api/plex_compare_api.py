import re
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

from api import plex_db_api


@dataclass
class PlexMovieRecord:
    guid: str
    title: str
    year: int | None
    ids: dict[str, str | None]


@dataclass
class PlexSeriesRecord:
    guid: str
    title: str
    year: int | None
    ids: dict[str, str | None]
    season_numbers: list[int]
    episode_codes: list[str]
    special_codes: list[str]
    episode_count: int
    special_count: int


def compare_databases(legacy_db_path: str, current_db_path: str) -> dict[str, Any]:
    legacy = _load_snapshot(legacy_db_path)
    current = _load_snapshot(current_db_path)
    return build_compare_result(legacy["movies"], legacy["series"], current["movies"], current["series"], legacy_db_path, current_db_path)


def _load_snapshot(db_path: str) -> dict[str, Any]:
    return {
        "movies": [_movie_record_to_dict(item) for item in plex_db_api.plex_get_movies_detailed(db_path)],
        "series": [_series_record_to_dict(item) for item in plex_db_api.plex_get_series_detailed(db_path)],
    }


def build_compare_result(
    legacy_movies: list[dict[str, Any]] | list[PlexMovieRecord],
    legacy_series: list[dict[str, Any]] | list[PlexSeriesRecord],
    current_movies: list[dict[str, Any]] | list[PlexMovieRecord],
    current_series: list[dict[str, Any]] | list[PlexSeriesRecord],
    legacy_db_path: str | None = None,
    current_db_path: str | None = None,
) -> dict[str, Any]:
    legacy_movies_dict = [_movie_record_to_dict(item) if not isinstance(item, dict) else item for item in legacy_movies]
    legacy_series_dict = [_series_record_to_dict(item) if not isinstance(item, dict) else item for item in legacy_series]
    current_movies_dict = [_movie_record_to_dict(item) if not isinstance(item, dict) else item for item in current_movies]
    current_series_dict = [_series_record_to_dict(item) if not isinstance(item, dict) else item for item in current_series]

    movie_rows = _compare_movies(legacy_movies_dict, current_movies_dict)
    series_rows = _compare_series(legacy_series_dict, current_series_dict)
    return {
        "legacy_db_path": legacy_db_path,
        "current_db_path": current_db_path,
        "summary": {
            "legacy_movies": len(legacy_movies_dict),
            "current_movies": len(current_movies_dict),
            "legacy_series": len(legacy_series_dict),
            "current_series": len(current_series_dict),
            "movies_missing_in_current": sum(1 for row in movie_rows if row["status"] == "missing_in_current"),
            "movies_current_only": sum(1 for row in movie_rows if row["status"] == "current_only"),
            "movies_matched": sum(1 for row in movie_rows if row["status"] == "present_in_both"),
            "movies_ambiguous": sum(1 for row in movie_rows if row["status"] == "ambiguous"),
            "series_missing_in_current": sum(1 for row in series_rows if row["status"] == "missing_in_current"),
            "series_current_only": sum(1 for row in series_rows if row["status"] == "current_only"),
            "series_matched_complete": sum(1 for row in series_rows if row["status"] == "present_in_both"),
            "series_matched_incomplete": sum(1 for row in series_rows if row["status"] == "missing_children"),
            "series_ambiguous": sum(1 for row in series_rows if row["status"] == "ambiguous"),
            "series_with_missing_episodes": sum(1 for row in series_rows if row.get("missing_episode_count", 0) > 0),
            "series_with_missing_specials": sum(1 for row in series_rows if row.get("missing_special_count", 0) > 0),
        },
        "library_filters": {
            "legacy": _collect_library_filters(legacy_movies_dict, legacy_series_dict),
            "current": _collect_library_filters(current_movies_dict, current_series_dict),
        },
        "movies": movie_rows,
        "series": series_rows,
    }


def _movie_record_to_dict(record: PlexMovieRecord) -> dict[str, Any]:
    return asdict(record)


def _series_record_to_dict(record: PlexSeriesRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["season_count"] = len(record.season_numbers)
    return payload


def _compare_movies(legacy_items: list[dict[str, Any]], current_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched_current: set[str] = set()
    rows: list[dict[str, Any]] = []
    for legacy in sorted(legacy_items, key=lambda item: (_normalize_title(item["title"]), item.get("year") or 0)):
        candidates, method = _find_candidates(legacy, current_items, matched_current)
        if len(candidates) == 1:
            current = candidates[0]
            matched_current.add(current["guid"])
            rows.append({
                "status": "present_in_both",
                "match_method": method,
                "legacy": legacy,
                "current": current,
            })
        elif len(candidates) > 1:
            rows.append({
                "status": "ambiguous",
                "match_method": method,
                "legacy": legacy,
                "current": None,
                "candidates": candidates,
            })
        else:
            rows.append({
                "status": "missing_in_current",
                "match_method": None,
                "legacy": legacy,
                "current": None,
            })
    for current in sorted(current_items, key=lambda item: (_normalize_title(item["title"]), item.get("year") or 0)):
        if current["guid"] in matched_current:
            continue
        rows.append({
            "status": "current_only",
            "match_method": None,
            "legacy": None,
                "current": current,
        })
    return sorted(rows, key=_row_sort_key)


def _compare_series(legacy_items: list[dict[str, Any]], current_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched_current: set[str] = set()
    rows: list[dict[str, Any]] = []
    for legacy in sorted(legacy_items, key=lambda item: (_normalize_title(item["title"]), item.get("year") or 0)):
        candidates, method = _find_candidates(legacy, current_items, matched_current)
        if len(candidates) == 1:
            current = candidates[0]
            matched_current.add(current["guid"])
            diff = _series_diff(legacy, current)
            rows.append({
                "status": "missing_children" if diff["has_missing_children"] else "present_in_both",
                "match_method": method,
                "legacy": legacy,
                "current": current,
                **diff,
            })
        elif len(candidates) > 1:
            rows.append({
                "status": "ambiguous",
                "match_method": method,
                "legacy": legacy,
                "current": None,
                "candidates": candidates,
                "missing_seasons": [],
                "missing_episodes": [],
                "missing_specials": [],
                "extra_seasons": [],
                "extra_episodes": [],
                "extra_specials": [],
                "missing_episode_count": 0,
                "missing_special_count": 0,
                "extra_episode_count": 0,
                "extra_special_count": 0,
            })
        else:
            rows.append({
                "status": "missing_in_current",
                "match_method": None,
                "legacy": legacy,
                "current": None,
                "missing_seasons": list(legacy.get("season_numbers") or []),
                "missing_episodes": list(legacy.get("episode_codes") or []),
                "missing_specials": list(legacy.get("special_codes") or []),
                "extra_seasons": [],
                "extra_episodes": [],
                "extra_specials": [],
                "missing_episode_count": len(legacy.get("episode_codes") or []),
                "missing_special_count": len(legacy.get("special_codes") or []),
                "extra_episode_count": 0,
                "extra_special_count": 0,
                "has_missing_children": True,
            })
    for current in sorted(current_items, key=lambda item: (_normalize_title(item["title"]), item.get("year") or 0)):
        if current["guid"] in matched_current:
            continue
        rows.append({
            "status": "current_only",
            "match_method": None,
            "legacy": None,
            "current": current,
            "missing_seasons": [],
            "missing_episodes": [],
            "missing_specials": [],
            "extra_seasons": list(current.get("season_numbers") or []),
            "extra_episodes": list(current.get("episode_codes") or []),
            "extra_specials": list(current.get("special_codes") or []),
            "missing_episode_count": 0,
            "missing_special_count": 0,
            "extra_episode_count": len(current.get("episode_codes") or []),
                "extra_special_count": len(current.get("special_codes") or []),
                "has_missing_children": False,
        })
    return sorted(rows, key=_row_sort_key)


def _find_candidates(
    legacy_item: dict[str, Any],
    current_items: list[dict[str, Any]],
    matched_current: set[str],
) -> tuple[list[dict[str, Any]], str | None]:
    strong_candidates = [
        current
        for current in current_items
        if current["guid"] not in matched_current and _shares_strong_id(legacy_item, current)
    ]
    if strong_candidates:
        return strong_candidates, "strong_id"
    fallback_candidates = [
        current
        for current in current_items
        if current["guid"] not in matched_current and _same_title_year(legacy_item, current)
    ]
    if fallback_candidates:
        return fallback_candidates, "title_year"
    return [], None


def _shares_strong_id(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_ids = left.get("ids") or {}
    right_ids = right.get("ids") or {}
    for key in ("imdb", "tmdb", "tvdb"):
        left_value = str(left_ids.get(key) or "").strip().lower()
        right_value = str(right_ids.get(key) or "").strip().lower()
        if left_value and right_value and left_value == right_value:
            return True
    return False


def _same_title_year(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _normalize_title(left.get("title")) == _normalize_title(right.get("title")) and left.get("year") == right.get("year")


def _series_diff(legacy: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    legacy_seasons = set(legacy.get("season_numbers") or [])
    current_seasons = set(current.get("season_numbers") or [])
    legacy_episodes = set(legacy.get("episode_codes") or [])
    current_episodes = set(current.get("episode_codes") or [])
    legacy_specials = set(legacy.get("special_codes") or [])
    current_specials = set(current.get("special_codes") or [])

    missing_seasons = sorted(legacy_seasons - current_seasons)
    extra_seasons = sorted(current_seasons - legacy_seasons)
    missing_episodes = sorted(legacy_episodes - current_episodes)
    extra_episodes = sorted(current_episodes - legacy_episodes)
    missing_specials = sorted(legacy_specials - current_specials)
    extra_specials = sorted(current_specials - legacy_specials)
    has_missing_children = bool(missing_seasons or missing_episodes or missing_specials)

    return {
        "missing_seasons": missing_seasons,
        "extra_seasons": extra_seasons,
        "missing_episodes": missing_episodes,
        "extra_episodes": extra_episodes,
        "missing_specials": missing_specials,
        "extra_specials": extra_specials,
        "missing_episode_count": len(missing_episodes),
        "missing_special_count": len(missing_specials),
        "extra_episode_count": len(extra_episodes),
        "extra_special_count": len(extra_specials),
        "has_missing_children": has_missing_children,
    }


def _normalize_title(title: str | None) -> str:
    return "".join(ch.lower() for ch in str(title or "") if ch.isalnum() or ch.isspace()).strip()


def _collect_library_filters(*collections: list[dict[str, Any]]) -> list[str]:
    values: set[str] = set()
    for items in collections:
        for item in items:
            value = str(item.get("library_name") or "").strip()
            if value:
                values.add(value)
    return sorted(values, key=lambda item: item.lower())


def _row_sort_key(row: dict[str, Any]) -> tuple[str, int, str]:
    legacy = row.get("legacy") or {}
    current = row.get("current") or {}
    raw_title = legacy.get("title") or current.get("title") or ""
    raw_year = legacy.get("year") or current.get("year") or 0
    status_order = {
        "missing_in_current": 0,
        "ambiguous": 1,
        "present_in_both": 2,
        "missing_children": 2,
        "current_only": 3,
    }
    return (
        _normalize_title(raw_title),
        int(raw_year or 0),
        f"{status_order.get(row.get('status'), 9)}:{raw_title.lower()}",
    )


def parse_guid_ids(guid: str | None) -> dict[str, str | None]:
    raw = str(guid or "").strip()
    result = {
        "imdb": None,
        "tmdb": None,
        "tvdb": None,
    }
    if not raw:
        return result
    patterns = {
        "imdb": [
            r"(?:imdb://|com\.plexapp\.agents\.imdb://)(tt\d+)",
            r"(tt\d+)",
        ],
        "tmdb": [
            r"(?:tmdb://|themoviedb://|com\.plexapp\.agents\.themoviedb://)(\d+)",
        ],
        "tvdb": [
            r"(?:tvdb://|thetvdb://|com\.plexapp\.agents\.thetvdb://)(\d+)",
        ],
    }
    for key, key_patterns in patterns.items():
        for pattern in key_patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if match:
                value = match.group(1)
                result[key] = value.lower() if key == "imdb" else value
                break
    return result


def load_movies_from_db(db_path: str) -> list[PlexMovieRecord]:
    return plex_db_api.plex_get_movies_detailed(db_path)


def load_series_from_db(db_path: str) -> list[PlexSeriesRecord]:
    return plex_db_api.plex_get_series_detailed(db_path)
