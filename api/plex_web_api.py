import requests
from urllib.parse import quote
from dataclasses import dataclass
from core import db_core

PLEX_WEB_URL = ""
PLEX_WEB_TOKEN = ""


def _get_config(db: db_core.MediaDB | None = None) -> dict:
    cfg = db.get_service_config("Plex Web") if db else {}
    return {
        "url": (cfg.get("plex_web_url") or PLEX_WEB_URL or "").rstrip("/"),
        "token": cfg.get("plex_web_token") or PLEX_WEB_TOKEN
    }


def _plex_request(path: str, db: db_core.MediaDB | None = None, params: dict | None = None) -> dict | None:
    cfg = _get_config(db)
    if not cfg["url"] or not cfg["token"]:
        return None
    url = f"{cfg['url']}{path}"
    req_params = params.copy() if params else {}
    req_params["X-Plex-Token"] = cfg["token"]
    headers = {"Accept": "application/json"}
    r = requests.get(url, headers=headers, params=req_params)
    if r.status_code != 200:
        print(f"Error calling Plex API {path}: {r.status_code}")
        return None
    return r.json()


@dataclass
class PlexMedia:
    title: str
    year: int | None
    media_type: str
    library: str
    rating_key: str


def plex_get_media_items(db: db_core.MediaDB | None = None) -> list[PlexMedia]:
    data = _plex_request("/library/sections", db)
    if not data:
        return []
    container = data.get("MediaContainer") or {}
    sections = container.get("Directory") or []
    items: list[PlexMedia] = []
    for section in sections:
        section_type = section.get("type")
        if section_type not in ("movie", "show"):
            continue
        section_key = section.get("key")
        section_title = section.get("title") or "Plex"
        if not section_key:
            continue
        section_data = _plex_request(f"/library/sections/{section_key}/all", db)
        if not section_data:
            continue
        meta = section_data.get("MediaContainer", {}).get("Metadata") or []
        for m in meta:
            rating_key = m.get("ratingKey")
            if not rating_key:
                continue
            items.append(PlexMedia(
                title=m.get("title") or "",
                year=m.get("year"),
                media_type=m.get("type") or section_type,
                library=section_title,
                rating_key=str(rating_key)
            ))
    return items


def plex_get_media_details(rating_key: str, db: db_core.MediaDB | None = None) -> dict | None:
    if not rating_key:
        return None
    data = _plex_request(f"/library/metadata/{rating_key}", db)
    if not data:
        return None
    meta = data.get("MediaContainer", {}).get("Metadata") or []
    if not meta:
        return None
    item = meta[0]
    genres = [g.get("tag") for g in item.get("Genre", []) if g.get("tag")]
    cfg = _get_config(db)
    thumb = item.get("thumb")
    art = item.get("art")
    def _image_url(path: str | None) -> str | None:
        if not path or not cfg["url"] or not cfg["token"]:
            return None
        if path.startswith("http://") or path.startswith("https://"):
            base = path
        else:
            base = f"{cfg['url']}{path}"
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}X-Plex-Token={cfg['token']}"

    return {
        "title": item.get("title"),
        "original_title": item.get("originalTitle"),
        "summary": item.get("summary"),
        "year": item.get("year"),
        "type": item.get("type"),
        "studio": item.get("studio"),
        "content_rating": item.get("contentRating"),
        "duration": item.get("duration"),
        "added_at": item.get("addedAt"),
        "updated_at": item.get("updatedAt"),
        "rating": item.get("rating"),
        "audience_rating": item.get("audienceRating"),
        "view_count": item.get("viewCount"),
        "last_viewed_at": item.get("lastViewedAt"),
        "genres": genres,
        "thumb": thumb,
        "art": art,
        "poster_url": _image_url(thumb),
        "backdrop_url": _image_url(art)
    }
