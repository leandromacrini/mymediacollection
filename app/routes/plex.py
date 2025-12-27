from flask import Blueprint, jsonify, render_template

from api import plex_web_api, radarr_api, sonarr_api
from app.extensions import db

bp = Blueprint("plex", __name__)


@bp.route("/plex")
def plex_view():
    plex_cfg = plex_web_api._get_config(db)
    return render_template("plex.html", plex_url=plex_cfg.get("url") or "")


@bp.route("/api/plex/media/<rating_key>")
def plex_media_details(rating_key):
    details = plex_web_api.plex_get_media_details(rating_key, db)
    if not details:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "details": details})


@bp.route("/api/plex/media")
def plex_media_list():
    items = plex_web_api.plex_get_media_items(db)
    machine_id = plex_web_api.plex_get_machine_identifier(db)
    radarr_movies = radarr_api.radarr_get_all_movies(db)
    radarr_tmdb = {str(m.tmdb_id) for m in radarr_movies if m.tmdb_id}
    radarr_titles = {((m.title or "").strip().lower(), m.year) for m in radarr_movies if m.title}

    sonarr_series = sonarr_api.sonarr_get_all_series(db)
    sonarr_tvdb = {str(s.tvdb_id) for s in sonarr_series if s.tvdb_id}
    sonarr_titles = {((s.title or "").strip().lower(), s.year) for s in sonarr_series if s.title}

    wanted_items = db.get_wanted_items(limit=1000000)
    wanted_tmdb = set()
    wanted_titles = set()
    for item in wanted_items:
        tmdb_id = item.external_ids.get("tmdb") or item.external_ids.get("radarr")
        if tmdb_id:
            wanted_tmdb.add(str(tmdb_id))
        wanted_titles.add(((item.title or "").strip().lower(), item.year))

    payload = []
    movies = 0
    series = 0
    for m in items:
        in_radarr = False
        if m.tmdb_id and m.tmdb_id in radarr_tmdb:
            in_radarr = True
        elif ((m.title or "").strip().lower(), m.year) in radarr_titles:
            in_radarr = True

        in_sonarr = False
        if m.tvdb_id and m.tvdb_id in sonarr_tvdb:
            in_sonarr = True
        elif ((m.title or "").strip().lower(), m.year) in sonarr_titles:
            in_sonarr = True

        in_wanted = False
        if m.tmdb_id and m.tmdb_id in wanted_tmdb:
            in_wanted = True
        elif ((m.title or "").strip().lower(), m.year) in wanted_titles:
            in_wanted = True

        if m.media_type == "movie":
            movies += 1
        if m.media_type == "show":
            series += 1

        payload.append({
            "title": m.title,
            "year": m.year,
            "media_type": m.media_type,
            "library": m.library,
            "rating_key": m.rating_key,
            "machine_identifier": machine_id,
            "in_radarr": in_radarr,
            "in_sonarr": in_sonarr,
            "in_wanted": in_wanted
        })

    return jsonify({
        "ok": True,
        "items": payload,
        "machine_identifier": machine_id,
        "counts": {
            "total": len(payload),
            "movies": movies,
            "series": series
        }
    })
