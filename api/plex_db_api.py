import sqlite3
from dataclasses import dataclass
import re

# -------- CONSTANTS --------
MOVIE_MEDIATYPE = 1
SERIES_MEDIATYPE = 2  # show
SEASON_MEDIATYPE = 3
EPISODE_MEDIATYPE = 4

# -------- OBJECTS --------
@dataclass
class PlexMedia:
    title: str
    year: int
    guid: str
    file_path: str


@dataclass
class PlexMovieDetailed:
    guid: str
    title: str
    year: int | None
    ids: dict[str, str | None]
    library_name: str | None


@dataclass
class PlexSeriesDetailed:
    guid: str
    title: str
    year: int | None
    ids: dict[str, str | None]
    season_numbers: list[int]
    episode_codes: list[str]
    special_codes: list[str]
    episode_count: int
    special_count: int
    library_name: str | None

# -------- FUNCTIONS --------
def plex_get_media_by_mediatype(db_path: str, mediatype: int) -> list[PlexMedia]:
    """
    Retrieve media items from Plex DB by media type.

    Args:
        db_path (str): Path to the Plex SQLite database.
        mediatype (int): Media type (1=movie, 2=series, etc.).

    Returns:
        List[PlexMedia]: List of PlexMedia objects.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            mi.title,
            mi.year,
            mi.guid,
            mp.file
        FROM metadata_items mi
        JOIN media_items m ON m.metadata_item_id = mi.id
        JOIN media_parts mp ON mp.media_item_id = m.id
        WHERE mi.metadata_type = ?
    """, (mediatype,))
    rows = cursor.fetchall()
    conn.close()

    return [PlexMedia(title=row[0], year=row[1], guid=row[2], file_path=row[3]) for row in rows]

def plex_get_series(db_path: str) -> list[PlexMedia]:
    """
    Retrieve series (show) items from Plex DB.
    Uses one episode file path as reference for the series when available.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            show.title,
            show.year,
            show.guid,
            MIN(mp.file) AS file_path
        FROM metadata_items show
        LEFT JOIN metadata_items season
            ON season.parent_id = show.id
           AND season.metadata_type = ?
        LEFT JOIN metadata_items episode
            ON (
                episode.parent_id = season.id
                OR episode.parent_id = show.id
            )
           AND episode.metadata_type = ?
        LEFT JOIN media_items m
            ON m.metadata_item_id = episode.id
        LEFT JOIN media_parts mp
            ON mp.media_item_id = m.id
        WHERE show.metadata_type = ?
        GROUP BY show.id, show.title, show.year, show.guid
    """, (SEASON_MEDIATYPE, EPISODE_MEDIATYPE, SERIES_MEDIATYPE))
    rows = cursor.fetchall()
    conn.close()

    return [
        PlexMedia(
            title=row[0],
            year=row[1],
            guid=row[2],
            file_path=row[3] or ""
        )
        for row in rows
    ]

def plex_get_media_by_title_year(db_path: str, title: str, year: int, mediatype: int = MOVIE_MEDIATYPE) -> PlexMedia | None:
    """
    Retrieve a single media item from Plex DB by title, year and media type.

    Args:
        db_path (str): Path to the Plex SQLite database.
        title (str): Title of the media.
        year (int): Release year.
        mediatype (int): Media type (1=movie, 2=series, etc.).

    Returns:
        PlexMedia | None: PlexMedia object if found, else None.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            mi.title,
            mi.year,
            mi.guid,
            mp.file
        FROM metadata_items mi
        JOIN media_items m ON m.metadata_item_id = mi.id
        JOIN media_parts mp ON mp.media_item_id = m.id
        WHERE mi.metadata_type = ?
          AND mi.title = ?
          AND mi.year = ?
        LIMIT 1
    """, (mediatype, title, year))
    row = cursor.fetchone()
    conn.close()

    if row:
        return PlexMedia(title=row[0], year=row[1], guid=row[2], file_path=row[3])
    return None


def plex_get_movies_detailed(db_path: str) -> list[PlexMovieDetailed]:
    conn = sqlite3.connect(db_path)
    guid_map = _load_guid_map(conn)
    library_map = _load_library_map(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT
            mi.id,
            mi.guid,
            mi.title,
            mi.year
        FROM metadata_items mi
        WHERE mi.metadata_type = ?
        ORDER BY mi.title COLLATE NOCASE, mi.year
        """,
        (MOVIE_MEDIATYPE,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        PlexMovieDetailed(
            guid=row[1] or "",
            title=row[2] or "",
            year=row[3],
            ids=_merge_guid_ids(_parse_guid_ids(row[1]), guid_map.get(int(row[0]))),
            library_name=library_map.get(int(row[0])),
        )
        for row in rows
    ]


def plex_get_series_detailed(db_path: str) -> list[PlexSeriesDetailed]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    guid_map = _load_guid_map(conn)
    library_map = _load_library_map(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            show.id AS show_id,
            show.guid AS show_guid,
            show.title AS show_title,
            show.year AS show_year,
            season.id AS season_id,
            season."index" AS season_index,
            episode.id AS episode_id,
            episode.guid AS episode_guid,
            episode.title AS episode_title,
            episode."index" AS episode_index
        FROM metadata_items show
        LEFT JOIN metadata_items season
            ON season.parent_id = show.id
           AND season.metadata_type = ?
        LEFT JOIN metadata_items episode
            ON (
                episode.parent_id = season.id
                OR (episode.parent_id = show.id AND season.id IS NULL)
            )
           AND episode.metadata_type = ?
        WHERE show.metadata_type = ?
        ORDER BY show.title COLLATE NOCASE, show.year, season."index", episode."index"
        """,
        (SEASON_MEDIATYPE, EPISODE_MEDIATYPE, SERIES_MEDIATYPE),
    )
    rows = cursor.fetchall()
    conn.close()

    grouped: dict[int, dict] = {}
    for row in rows:
        show_id = int(row["show_id"])
        current = grouped.setdefault(
            show_id,
            {
                "id": show_id,
                "guid": row["show_guid"] or "",
                "title": row["show_title"] or "",
                "year": row["show_year"],
                "ids": _merge_guid_ids(_parse_guid_ids(row["show_guid"]), guid_map.get(show_id)),
                "season_numbers": set(),
                "episode_codes": set(),
                "special_codes": set(),
            },
        )
        season_index = row["season_index"]
        episode_index = row["episode_index"]
        if season_index is not None:
            try:
                current["season_numbers"].add(int(season_index))
            except (TypeError, ValueError):
                pass
        if episode_index is None:
            continue
        try:
            episode_number = int(episode_index)
        except (TypeError, ValueError):
            continue
        try:
            season_number = int(season_index) if season_index is not None else 0
        except (TypeError, ValueError):
            season_number = 0
        code = _format_episode_code(season_number, episode_number)
        if season_number <= 0:
            current["special_codes"].add(code)
        else:
            current["episode_codes"].add(code)

    items: list[PlexSeriesDetailed] = []
    for show in grouped.values():
        special_codes = sorted(show["special_codes"])
        episode_codes = sorted(show["episode_codes"])
        season_numbers = sorted(show["season_numbers"])
        items.append(
            PlexSeriesDetailed(
                guid=show["guid"],
                title=show["title"],
                year=show["year"],
                ids=show["ids"],
                season_numbers=season_numbers,
                episode_codes=episode_codes,
                special_codes=special_codes,
                episode_count=len(episode_codes),
                special_count=len(special_codes),
                library_name=library_map.get(show.get("id")) if show.get("id") is not None else None,
            )
        )
    items.sort(key=lambda item: ((item.title or "").lower(), item.year or 0))
    return items


def _format_episode_code(season_number: int, episode_number: int) -> str:
    if season_number <= 0:
        return f"SP{episode_number:02d}"
    return f"S{season_number:02d}E{episode_number:02d}"


def _load_guid_map(conn: sqlite3.Connection) -> dict[int, dict[str, str | None]]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT metadata_item_id, guid
            FROM guids
            WHERE guid IS NOT NULL AND TRIM(guid) <> ''
            """
        )
    except sqlite3.OperationalError:
        return {}

    guid_map: dict[int, dict[str, str | None]] = {}
    for metadata_item_id, guid in cursor.fetchall():
        try:
            item_id = int(metadata_item_id)
        except (TypeError, ValueError):
            continue
        current = guid_map.setdefault(
            item_id,
            {"imdb": None, "tmdb": None, "tvdb": None},
        )
        current.update(_merge_guid_ids(current, _parse_guid_ids(guid)))
    return guid_map


def _load_library_map(conn: sqlite3.Connection) -> dict[int, str | None]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT mi.id, ls.name
            FROM metadata_items mi
            LEFT JOIN library_sections ls
                ON ls.id = mi.library_section_id
            WHERE mi.id IS NOT NULL
            """
        )
    except sqlite3.OperationalError:
        return {}
    library_map: dict[int, str | None] = {}
    for metadata_item_id, library_name in cursor.fetchall():
        try:
            item_id = int(metadata_item_id)
        except (TypeError, ValueError):
            continue
        value = str(library_name or "").strip() or None
        library_map[item_id] = value
    return library_map


def _merge_guid_ids(
    primary: dict[str, str | None] | None,
    secondary: dict[str, str | None] | None,
) -> dict[str, str | None]:
    merged = {
        "imdb": None,
        "tmdb": None,
        "tvdb": None,
    }
    for source in (secondary or {}, primary or {}):
        for key in merged.keys():
            value = str(source.get(key) or "").strip()
            if value and not merged[key]:
                merged[key] = value.lower() if key == "imdb" else value
    return merged


def _parse_guid_ids(guid: str | None) -> dict[str, str | None]:
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
