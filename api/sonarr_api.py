import requests
import time
from dataclasses import dataclass
from typing import List, Optional
from core import db_core

# ===== CONFIG =====
SONARR_URL = "REMOVED"
SONARR_API_KEY = "REMOVED"
PROFILE_ID = 1           # Quality profile
ENABLE_SEARCH = False     # True per far partire la ricerca automatica su Sonarr
ROOT_FOLDER = "/data/File Sharing/sonarr"
REQUEST_TIMEOUT = 8
# ==================

def _get_config(db: db_core.MediaDB | None = None) -> dict:
    cfg = db.get_service_config("Sonarr") if db else {}
    url = cfg.get("sonarr_url") or SONARR_URL
    api_key = cfg.get("sonarr_api_key") or SONARR_API_KEY
    return {
        "url": url,
        "headers": {"X-Api-Key": api_key},
        "root_folder": cfg.get("sonarr_root_folder") or ROOT_FOLDER,
        "profile_id": cfg.get("sonarr_profile_id") or PROFILE_ID,
        "enable_search": cfg.get("sonarr_enable_search") if cfg.get("sonarr_enable_search") is not None else ENABLE_SEARCH
    }

def sonarr_get_client(db: db_core.MediaDB) -> dict:
    return _get_config(db)

# --- Data object ---
@dataclass
class SonarrMedia:
    title: str
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    root_folder: str = ROOT_FOLDER
    monitored: bool = True
    slug: str = None
    seasons: list[dict] | None = None

# --- API Functions ---
def sonarr_get_all_series(db: db_core.MediaDB | None = None) -> List[SonarrMedia]:
    """
    Retrieve all series currently in Sonarr.
    Returns a list of SonarrMedia objects.
    """
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/series", headers=cfg["headers"], timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        print(f"Error fetching series from Sonarr: {r.status_code}")
        return []

    series_list = r.json()
    result = []
    for s in series_list:
        media = SonarrMedia(
            title=s.get("title"),
            year=s.get("year"),
            tvdb_id=s.get("tvdbId"),
            imdb_id=s.get("imdbId"),
            root_folder=s.get("rootFolderPath", cfg["root_folder"]),
            monitored=s.get("monitored", True),
            slug=s.get("titleSlug", None),
            seasons=s.get("seasons")
        )
        result.append(media)
    return result

def sonarr_get_root_folders(db: db_core.MediaDB | None = None) -> list[dict]:
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/rootfolder", headers=cfg["headers"], timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        print(f"Error fetching Sonarr root folders: {r.status_code}")
        return []
    return [
        {"id": item.get("id"), "path": item.get("path")}
        for item in r.json()
        if item.get("id") is not None
    ]

def sonarr_get_quality_profiles(db: db_core.MediaDB | None = None) -> list[dict]:
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/qualityprofile", headers=cfg["headers"], timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        print(f"Error fetching Sonarr quality profiles: {r.status_code}")
        return []
    return [
        {"id": item.get("id"), "name": item.get("name")}
        for item in r.json()
        if item.get("id") is not None
    ]

def sonarr_get_by_title(title: str, db: db_core.MediaDB | None = None) -> Optional[SonarrMedia]:
    """
    Check if a series exists in Sonarr by title.
    Returns a SonarrMedia object or None if not found.
    """
    all_series = sonarr_get_all_series(db)
    for s in all_series:
        if s.title == title:
            return s
    return None

def sonarr_get_by_tvdb(tvdb_id: int, db: db_core.MediaDB | None = None) -> SonarrMedia | None:
    if not tvdb_id:
        return None
    cfg = _get_config(db)
    r = requests.get(
        f"{cfg['url']}/api/v3/series",
        headers=cfg["headers"],
        params={"tvdbId": tvdb_id},
        timeout=REQUEST_TIMEOUT
    )
    if r.status_code != 200:
        print(f"Error fetching series by TVDB ID {tvdb_id}: {r.status_code}")
        return None
    data = r.json()
    if not data:
        return None
    s = data[0]
    return SonarrMedia(
        title=s.get("title"),
        tvdb_id=s.get("tvdbId"),
        imdb_id=s.get("imdbId"),
        year=s.get("year"),
        root_folder=s.get("rootFolderPath"),
        monitored=s.get("monitored", True),
        slug=s.get("titleSlug"),
        seasons=s.get("seasons")
    )

def sonarr_get_by_imdb(imdb_id: str, db: db_core.MediaDB | None = None) -> SonarrMedia | None:
    if not imdb_id:
        return None
    cfg = _get_config(db)
    r = requests.get(
        f"{cfg['url']}/api/v3/series",
        headers=cfg["headers"],
        params={"imdbId": imdb_id},
        timeout=REQUEST_TIMEOUT
    )
    if r.status_code != 200:
        print(f"Error fetching series by IMDb ID {imdb_id}: {r.status_code}")
        return None
    data = r.json()
    if not data:
        return None
    s = data[0]
    return SonarrMedia(
        title=s.get("title"),
        tvdb_id=s.get("tvdbId"),
        imdb_id=s.get("imdbId"),
        year=s.get("year"),
        root_folder=s.get("rootFolderPath"),
        monitored=s.get("monitored", True),
        slug=s.get("titleSlug"),
        seasons=s.get("seasons")
    )

def sonarr_lookup_by_tvdb(tvdb_id: int, db: db_core.MediaDB | None = None) -> SonarrMedia | None:
    if not tvdb_id:
        return None
    cfg = _get_config(db)
    params = {"term": f"tvdb:{tvdb_id}", "apikey": cfg["headers"]["X-Api-Key"]}
    r = requests.get(f"{cfg['url']}/api/v3/series/lookup", params=params, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        print(f"Error looking up TVDB ID {tvdb_id} on Sonarr: {r.status_code}")
        return None
    data = r.json()
    if not data:
        return None
    s = data[0]
    return SonarrMedia(
        title=s.get("title"),
        tvdb_id=s.get("tvdbId"),
        imdb_id=s.get("imdbId"),
        year=s.get("year"),
        root_folder=cfg["root_folder"],
        monitored=True,
        slug=s.get("titleSlug"),
        seasons=s.get("seasons")
    )

def sonarr_get_by_id(series_id: int, db: db_core.MediaDB | None = None) -> dict | None:
    if not series_id:
        return None
    cfg = _get_config(db)
    r = requests.get(f"{cfg['url']}/api/v3/series/{series_id}", headers=cfg["headers"], timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        print(f"Error fetching series by ID {series_id}: {r.status_code}")
        return None
    return r.json()

def sonarr_set_monitor_all_seasons(series_id: int, db: db_core.MediaDB | None = None) -> bool:
    series = sonarr_get_by_id(series_id, db)
    if not series:
        return False
    seasons = series.get("seasons") or []
    if not any(season.get("seasonNumber") == 0 for season in seasons):
        seasons.append({"seasonNumber": 0, "monitored": True})
    for season in seasons:
        season["monitored"] = True
    series["seasons"] = seasons
    cfg = _get_config(db)
    r = requests.put(
        f"{cfg['url']}/api/v3/series/{series_id}",
        headers=cfg["headers"],
        json=series,
        timeout=REQUEST_TIMEOUT
    )
    if r.status_code != 202:
        print(f"Error monitoring seasons for series {series_id}: {r.status_code} {r.text}")
        return False
    return True

def sonarr_get_episodes(series_id: int, db: db_core.MediaDB | None = None) -> list[dict]:
    if not series_id:
        return []
    cfg = _get_config(db)
    r = requests.get(
        f"{cfg['url']}/api/v3/episode",
        headers=cfg["headers"],
        params={"seriesId": series_id},
        timeout=REQUEST_TIMEOUT
    )
    if r.status_code != 200:
        print(f"Error fetching episodes for series {series_id}: {r.status_code} {r.text}")
        return []
    return r.json()

def sonarr_set_episode_monitor(episode_ids: list[int], monitored: bool, db: db_core.MediaDB | None = None) -> bool:
    if not episode_ids:
        return True
    cfg = _get_config(db)
    r = requests.put(
        f"{cfg['url']}/api/v3/episode/monitor",
        headers=cfg["headers"],
        json={"episodeIds": episode_ids, "monitored": monitored},
        timeout=REQUEST_TIMEOUT
    )
    if r.status_code != 202:
        print(f"Error monitoring episodes {episode_ids[:5]}...: {r.status_code} {r.text}")
        return False
    return True

def sonarr_monitor_specials_episodes(series_id: int, db: db_core.MediaDB | None = None) -> bool:
    episodes = sonarr_get_episodes(series_id, db)
    specials = [e.get("id") for e in episodes if e.get("seasonNumber") == 0 and e.get("id")]
    if not specials:
        return False
    return sonarr_set_episode_monitor(specials, True, db)

def sonarr_add_series(
    item: SonarrMedia,
    profile_id: int | None = None,
    enable_search: bool | None = None,
    root_folder: str | None = None,
    monitor_specials: bool | None = None,
    db: db_core.MediaDB | None = None
) -> bool:
    """
    Add a SonarrMedia item to Sonarr.
    """
    cfg = _get_config(db)
    payload = {
        "title": item.title,
        "qualityProfileId": profile_id if profile_id is not None else cfg["profile_id"],
        "titleSlug": item.slug or item.title.replace(" ", "-").lower(),
        "rootFolderPath": root_folder if root_folder is not None else cfg["root_folder"],
        "monitored": item.monitored,
        "addOptions": {"searchForMissingEpisodes": enable_search if enable_search is not None else cfg["enable_search"]}
    }
    if monitor_specials:
        payload["addOptions"]["monitor"] = "all"
        seasons = []
        if item.seasons:
            for season in item.seasons:
                updated = dict(season)
                updated["monitored"] = True
                seasons.append(updated)
        if not any(s.get("seasonNumber") == 0 for s in seasons):
            seasons.append({"seasonNumber": 0, "monitored": True})
        if seasons:
            payload["seasons"] = seasons

    if item.tvdb_id:
        payload["tvdbId"] = item.tvdb_id
    if item.imdb_id:
        payload["imdbId"] = item.imdb_id

    print(f"Sonarr add payload (monitor_specials={monitor_specials}): {payload}")
    r = requests.post(
        f"{cfg['url']}/api/v3/series",
        headers=cfg["headers"],
        json=payload,
        timeout=REQUEST_TIMEOUT
    )
    if r.status_code == 201:
        print(f"Added to Sonarr: {item.title}")
        if monitor_specials:
            try:
                series_id = r.json().get("id")
            except ValueError:
                series_id = None
            if series_id:
                for attempt in range(3):
                    if sonarr_set_monitor_all_seasons(series_id, db):
                        break
                    print(f"Warning: retrying monitor specials for series {series_id} (attempt {attempt + 1})")
                    time.sleep(2)
                for attempt in range(4):
                    if sonarr_monitor_specials_episodes(series_id, db):
                        break
                    print(f"Warning: retrying monitor specials episodes for series {series_id} (attempt {attempt + 1})")
                    time.sleep(2)
                for attempt in range(3):
                    if sonarr_set_monitor_all_seasons(series_id, db):
                        break
                    print(f"Warning: retrying monitor seasons after specials for series {series_id} (attempt {attempt + 1})")
                    time.sleep(2)
            else:
                print(f"Warning: missing series id for {item.title}, cannot monitor specials")
        return True
    else:
        print(f"Error adding {item.title}: {r.status_code} {r.text}")
        return False

def sonarr_lookup(title: str, db: db_core.MediaDB | None = None) -> list[SonarrMedia]:
    """
    Search Sonarr for a series by title using the lookup endpoint.
    Returns a list of SonarrMedia objects.
    """
    cfg = _get_config(db)
    params = {"term": title, "apikey": cfg["headers"]["X-Api-Key"]}
    r = requests.get(f"{cfg['url']}/api/v3/series/lookup", params=params, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        print(f"Error looking up '{title}' on Sonarr: {r.status_code}")
        return []

    results = r.json()
    media_list = []
    for s in results:
        media_list.append(SonarrMedia(
            title=s.get("title"),
            tvdb_id=s.get("tvdbId"),
            imdb_id=s.get("imdbId"),
            year=s.get("year"),
            root_folder=cfg["root_folder"],
            monitored=True,
            slug=s.get("titleSlug"),
            seasons=s.get("seasons")
        ))
    return media_list
