import sqlite3
from dataclasses import dataclass

# -------- CONSTANTS --------
MOVIE_MEDIATYPE = 1
SERIES_MEDIATYPE = 2  # se in futuro vuoi gestire anche le serie

# -------- OBJECTS --------
@dataclass
class PlexMedia:
    title: str
    year: int
    guid: str
    file_path: str

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