from flask import Blueprint, jsonify, render_template, request

from api import sonarr_api
from app.extensions import db
from core.db_core import Media

bp = Blueprint("sonarr", __name__)


@bp.route("/sonarr")
def sonarr_view():
    sonarr_url = sonarr_api.sonarr_get_client(db)["url"]
    return render_template(
        "sonarr.html",
        sonarr_url=sonarr_url
    )


@bp.route("/api/sonarr/list")
def sonarr_list():
    series = sonarr_api.sonarr_get_all_series(db)
    monitored = 0
    unmonitored = 0
    items = []
    for s in series:
        if s.monitored:
            monitored += 1
        else:
            unmonitored += 1
        items.append({
            "title": s.title,
            "year": s.year,
            "tvdb_id": s.tvdb_id,
            "monitored": s.monitored,
            "slug": s.slug
        })
    return jsonify({
        "ok": True,
        "items": items,
        "counts": {
            "total": len(items),
            "monitored": monitored,
            "unmonitored": unmonitored
        }
    })


@bp.route("/api/sonarr/sync/preview")
def sonarr_sync_preview():
    series = sonarr_api.sonarr_get_all_series(db)
    wanted_items = db.get_wanted_items(limit=1000000)
    wanted_by_tvdb = set()
    wanted_by_title_year = set()
    for item in wanted_items:
        tvdb_id = item.external_ids.get("tvdb") or item.external_ids.get("sonarr")
        if tvdb_id:
            wanted_by_tvdb.add(str(tvdb_id))
        title_key = (item.title or "").strip().lower()
        wanted_by_title_year.add((title_key, item.year))

    missing = []
    present = []
    for s in series:
        tvdb_id = str(s.tvdb_id) if s.tvdb_id else None
        title_key = (s.title or "").strip().lower()
        in_wanted = False
        match_type = None
        if tvdb_id and tvdb_id in wanted_by_tvdb:
            in_wanted = True
            match_type = "tvdb"
        elif (title_key, s.year) in wanted_by_title_year:
            in_wanted = True
            match_type = "title_year"

        payload = {
            "title": s.title,
            "year": s.year,
            "tvdb_id": s.tvdb_id,
            "imdb_id": s.imdb_id,
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
            "total": len(series)
        }
    })


@bp.route("/api/sonarr/sync/import", methods=["POST"])
def sonarr_sync_import():
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
        tvdb_id = item.get("tvdb_id")
        imdb_id = item.get("imdb_id")
        if not title:
            skipped += 1
            continue
        try:
            media = Media(
                id=None,
                title=title,
                year=year,
                media_type="series",
                category=None,
                source="sonarr",
                source_ref=str(tvdb_id) if tvdb_id else None
            )
            media_id, inserted = db.add_media(media)
            if inserted:
                if tvdb_id:
                    db.add_external_id(media_id, "tvdb", str(tvdb_id))
                    db.add_external_id(media_id, "sonarr", str(tvdb_id))
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
