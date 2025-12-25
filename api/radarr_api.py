import requests
from dataclasses import dataclass
from typing import List
from core import db_core

# ===== CONFIG =====
RADARR_URL = "REMOVED"
RADARR_API_KEY = "REMOVED"
PROFILE_ID = 7
ENABLE_SEARCH = False  # True per far partire la ricerca automatica su Radarr
ROOT_FOLDER = "/data/File Sharing/radarr"  # cartella principale di Radarr
# ==================

def _get_config(db: db_core.MediaDB | None = None) -> dict:
    cfg = db.get_service_config("Radarr") if db else {}
    url = cfg.get("radarr_url") or RADARR_URL
    api_key = cfg.get("radarr_api_key") or RADARR_API_KEY
    return {
        "url": url,
        "headers": {"X-Api-Key": api_key},
        "root_folder": cfg.get("radarr_root_folder") or ROOT_FOLDER,
        "profile_id": cfg.get("radarr_profile_id") or PROFILE_ID,
        "enable_search": cfg.get("radarr_enable_search") if cfg.get("radarr_enable_search") is not None else ENABLE_SEARCH
    }

# --- Data object ---
@dataclass
class RadarrMedia:
    title: str
    year: int
    tmdb_id: int | None
    imdb_id: str | None
    root_folder: str
    monitored: bool
    has_file: bool = False

# --- API Functions ---
def radarr_get_client(db: db_core.MediaDB) -> dict:
    return _get_config(db)

def radarr_get_all_movies(db: db_core.MediaDB | None = None) -> List[RadarrMedia]:
    """
    Retrieve all movies currently in Radarr.
    Returns a list of RadarrMedia objects.
    """
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/movie", headers=cfg["headers"])
    if r.status_code != 200:
        print(f"Error fetching movies from Radarr: {r.status_code}")
        return []

    movies = r.json()
    result = []
    for m in movies:
        media = RadarrMedia(
            title=m.get("title"),
            year=m.get("year"),
            tmdb_id=m.get("tmdbId"),
            imdb_id=m.get("imdbId"),
            root_folder=m.get("rootFolderPath"),
            monitored=m.get("monitored", True),
            has_file=m.get("hasFile", False)
        )
        result.append(media)
    return result

def radarr_get_root_folders(db: db_core.MediaDB | None = None) -> list[dict]:
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/rootfolder", headers=cfg["headers"])
    if r.status_code != 200:
        print(f"Error fetching Radarr root folders: {r.status_code}")
        return []
    return [
        {"id": item.get("id"), "path": item.get("path")}
        for item in r.json()
        if item.get("id") is not None
    ]

def radarr_get_quality_profiles(db: db_core.MediaDB | None = None) -> list[dict]:
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/qualityprofile", headers=cfg["headers"])
    if r.status_code != 200:
        print(f"Error fetching Radarr quality profiles: {r.status_code}")
        return []
    return [
        {"id": item.get("id"), "name": item.get("name")}
        for item in r.json()
        if item.get("id") is not None
    ]

def radarr_get_by_title_year(title: str, year: int, db: db_core.MediaDB | None = None) -> RadarrMedia | None:
    """
    Check if a movie exists in Radarr by title/year.
    Returns a RadarrMedia object or None if not found.
    """
    all_movies = radarr_get_all_movies(db)
    for m in all_movies:
        if m.title == title and m.year == year:
            return m
    return None

def radarr_get_by_tmdb(tmdb_id: int, db: db_core.MediaDB | None = None) -> RadarrMedia | None:
    """Retrieve a single movie by TMDb ID."""
    if not tmdb_id:
        return None
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/movie", headers=cfg["headers"], params={"tmdbId": tmdb_id})
    if r.status_code != 200:
        print(f"Error fetching movie by TMDb ID {tmdb_id}: {r.status_code}")
        return None
    data = r.json()
    if not data:
        return None
    m = data[0]
    return RadarrMedia(
        title=m.get("title"),
        year=m.get("year"),
        tmdb_id=m.get("tmdbId"),
        imdb_id=m.get("imdbId"),
        root_folder=m.get("rootFolderPath"),
        monitored=m.get("monitored", True),
        has_file=m.get("hasFile", False)
    )

def radarr_get_by_imdb(imdb_id: str, db: db_core.MediaDB | None = None) -> RadarrMedia | None:
    """Retrieve a single movie by IMDb ID."""
    if not imdb_id:
        return None
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/movie", headers=cfg["headers"], params={"imdbId": imdb_id})
    if r.status_code != 200:
        print(f"Error fetching movie by IMDb ID {imdb_id}: {r.status_code}")
        return None
    data = r.json()
    if not data:
        return None
    m = data[0]
    return RadarrMedia(
        title=m.get("title"),
        year=m.get("year"),
        tmdb_id=m.get("tmdbId"),
        imdb_id=m.get("imdbId"),
        root_folder=m.get("rootFolderPath"),
        monitored=m.get("monitored", True),
        has_file=m.get("hasFile", False)
    )

def radarr_add_movie(
    item: RadarrMedia,
    profile_id: int | None = None,
    enable_search: bool | None = None,
    root_folder: str | None = None,
    db: db_core.MediaDB | None = None
) -> bool:
    """
    Add a RadarrMedia item to Radarr.
    """
    cfg = _get_config(db)
    payload = {
        "title": item.title,
        "year": item.year,
        "tmdbId": int(item.tmdb_id) if item.tmdb_id else None,
        "imdbId": item.imdb_id,
        "qualityProfileId": profile_id if profile_id is not None else cfg["profile_id"],
        "rootFolderPath": root_folder if root_folder is not None else cfg["root_folder"],
        "monitored": item.monitored,
        "addOptions": {"searchForMovie": enable_search if enable_search is not None else cfg["enable_search"]}
    }

    r = requests.post(f"{cfg['url']}/api/v3/movie", headers=cfg["headers"], json=payload)
    if r.status_code == 201:
        print(f"Added to Radarr: {item.title} ({item.year})")
        return True
    else:
        print(f"Error adding {item.title}: {r.status_code} {r.text}")
        return False

def radarr_lookup(title: str, year: int | None = None, db: db_core.MediaDB | None = None) -> list[RadarrMedia]:
    """
    Search Radarr for a movie by title (and optionally year) using the lookup endpoint.
    Returns a list of RadarrMedia objects.
    """
    cfg = _get_config(db)
    params = {"term": title, "apikey": cfg["headers"]["X-Api-Key"]}
    r = requests.get(f"{cfg['url']}/api/v3/movie/lookup", params=params)
    if r.status_code != 200:
        print(f"Error looking up '{title}' on Radarr: {r.status_code}")
        return []

    results = r.json()
    if year:
        results = [m for m in results if m.get("year") == year]

    media_list = []
    for m in results:
        media_list.append(RadarrMedia(
            title=m.get("title"),
            year=m.get("year"),
            tmdb_id=m.get("tmdbId"),
            imdb_id=m.get("imdbId"),
            root_folder=cfg["root_folder"],
            monitored=True,
            has_file=m.get("hasFile", False)
        ))
    return media_list
