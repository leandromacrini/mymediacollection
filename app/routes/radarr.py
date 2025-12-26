from flask import Blueprint, jsonify, render_template, request

from api import radarr_api
from app.extensions import db
from core.db_core import Media

bp = Blueprint("radarr", __name__)


@bp.route("/radarr")
def radarr_view():
    movies = radarr_api.radarr_get_all_movies(db)
    radarr_url = radarr_api.radarr_get_client(db)["url"]
    return render_template("radarr.html", movies=movies, radarr_url=radarr_url)


@bp.route("/api/radarr/options")
def radarr_options():
    roots = radarr_api.radarr_get_root_folders(db)
    profiles = radarr_api.radarr_get_quality_profiles(db)
    return jsonify({"root_folders": roots, "profiles": profiles})


@bp.route("/api/radarr/sync/preview")
def radarr_sync_preview():
    movies = radarr_api.radarr_get_all_movies(db)
    wanted_items = db.get_wanted_items(limit=1000000)
    wanted_by_tmdb = set()
    wanted_by_title_year = set()
    for item in wanted_items:
        tmdb_id = item.external_ids.get("tmdb") or item.external_ids.get("radarr")
        if tmdb_id:
            wanted_by_tmdb.add(str(tmdb_id))
        title_key = (item.title or "").strip().lower()
        wanted_by_title_year.add((title_key, item.year))

    missing = []
    present = []
    for movie in movies:
        tmdb_id = str(movie.tmdb_id) if movie.tmdb_id else None
        title_key = (movie.title or "").strip().lower()
        in_wanted = False
        match_type = None
        if tmdb_id and tmdb_id in wanted_by_tmdb:
            in_wanted = True
            match_type = "tmdb"
        elif (title_key, movie.year) in wanted_by_title_year:
            in_wanted = True
            match_type = "title_year"

        payload = {
            "title": movie.title,
            "year": movie.year,
            "tmdb_id": movie.tmdb_id,
            "imdb_id": movie.imdb_id,
            "match_type": match_type
        }
        if in_wanted:
            present.append(payload)
        else:
            missing.append(payload)

    return jsonify({
        "ok": True,
        "missing": missing,
        "present": present,
        "counts": {
            "missing": len(missing),
            "present": len(present),
            "total": len(movies)
        }
    })


@bp.route("/api/radarr/sync/import", methods=["POST"])
def radarr_sync_import():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "missing_items"}), 400

    imported = 0
    skipped = 0
    errors = 0
    for item in items:
        title = (item.get("title") or "").strip()
        year = item.get("year")
        tmdb_id = item.get("tmdb_id")
        imdb_id = item.get("imdb_id")
        if not title:
            skipped += 1
            continue
        try:
            media = Media(
                id=None,
                title=title,
                year=year,
                media_type="movie",
                category=None,
                source="radarr",
                source_ref=str(tmdb_id) if tmdb_id else None
            )
            media_id, inserted = db.add_media(media)
            if inserted:
                if tmdb_id:
                    db.add_external_id(media_id, "tmdb", str(tmdb_id))
                    db.add_external_id(media_id, "radarr", str(tmdb_id))
                if imdb_id:
                    db.add_external_id(media_id, "imdb", str(imdb_id))
                imported += 1
            else:
                skipped += 1
        except Exception:
            errors += 1

    return jsonify({
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "errors": errors
    })
