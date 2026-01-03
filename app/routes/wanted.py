import os
import re

from flask import Blueprint, jsonify, redirect, render_template, request, url_for, flash

from api import animeworld_api as aw_api
from api import radarr_api
from api import sonarr_api
from app.extensions import db
from app.utils import get_lookup_title, json_items
from core.db_core import Media

bp = Blueprint("wanted", __name__)


@bp.route("/wanted")
def wanted_view():
    radarr_cfg = db.get_service_config("Radarr")
    radarr_url = radarr_api.radarr_get_client(db)["url"]
    return render_template(
        "wanted.html",
        radarr_url=radarr_url,
        radarr_defaults={
            "root_folder": radarr_cfg.get("radarr_root_folder"),
            "profile_id": radarr_cfg.get("radarr_profile_id"),
            "enable_search": radarr_cfg.get("radarr_enable_search")
        }
    )


@bp.route("/api/wanted/content")
def wanted_content():
    wanted_list = db.get_wanted_items(limit=None)
    radarr_url = radarr_api.radarr_get_client(db)["url"]
    radarr_movies = radarr_api.radarr_get_all_movies(db)
    radarr_tmdb = {str(m.tmdb_id) for m in radarr_movies if m.tmdb_id}
    radarr_downloaded = {str(m.tmdb_id) for m in radarr_movies if m.tmdb_id and m.has_file}
    radarr_root_map = {str(m.tmdb_id): (m.root_folder or "") for m in radarr_movies if m.tmdb_id}
    sonarr_url = sonarr_api.sonarr_get_client(db)["url"]
    sonarr_series = sonarr_api.sonarr_get_all_series(db)
    sonarr_tvdb = {str(s.tvdb_id) for s in sonarr_series if s.tvdb_id}
    sonarr_slug_map = {str(s.tvdb_id): s.slug for s in sonarr_series if s.tvdb_id and s.slug}
    sonarr_root_map = {str(s.tvdb_id): (s.root_folder or "") for s in sonarr_series if s.tvdb_id}
    sonarr_series_stats = sonarr_api.sonarr_get_series_stats(db)
    sonarr_downloaded = set()
    sonarr_progress = {}
    for s in sonarr_series_stats:
        tvdb_id = s.get("tvdbId")
        stats = s.get("statistics") or {}
        episode_count = stats.get("episodeCount")
        if episode_count is None:
            episode_count = stats.get("totalEpisodeCount")
        episode_file_count = stats.get("episodeFileCount") or 0
        if tvdb_id:
            sonarr_progress[str(tvdb_id)] = {
                "downloaded": int(episode_file_count),
                "total": episode_count if episode_count is not None else None,
            }
        if tvdb_id and episode_count and episode_file_count >= episode_count:
            sonarr_downloaded.add(str(tvdb_id))
    import_paths = {}
    for item in wanted_list:
        if item.source != "plex db" or not item.source_ref:
            continue
        ref = item.source_ref.replace("/", "\\")
        match = re.search(r"\\media\\([^\\]+)", ref, re.IGNORECASE)
        if match:
            import_paths[item.id] = match.group(1)

    radarr_cfg = db.get_service_config("Radarr")
    sonarr_cfg = db.get_service_config("Sonarr")
    return render_template(
        "partials/wanted_content.html",
        items=wanted_list,
        radarr_tmdb=radarr_tmdb,
        radarr_downloaded=radarr_downloaded,
        radarr_root_map=radarr_root_map,
        sonarr_url=sonarr_url,
        sonarr_tvdb=sonarr_tvdb,
        sonarr_slug_map=sonarr_slug_map,
        sonarr_downloaded=sonarr_downloaded,
        sonarr_progress=sonarr_progress,
        sonarr_root_map=sonarr_root_map,
        import_paths=import_paths,
        radarr_url=radarr_url,
        radarr_defaults={
            "root_folder": radarr_cfg.get("radarr_root_folder"),
            "profile_id": radarr_cfg.get("radarr_profile_id"),
            "enable_search": radarr_cfg.get("radarr_enable_search")
        },
        sonarr_defaults={
            "root_folder": sonarr_cfg.get("sonarr_root_folder"),
            "profile_id": sonarr_cfg.get("sonarr_profile_id"),
            "enable_search": sonarr_cfg.get("sonarr_enable_search")
        }
    )


@bp.route("/wanted/bulk_delete", methods=["POST"])
def wanted_bulk_delete():
    media_ids = request.form.getlist("media_ids[]")
    if not media_ids:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "no_selection"}), 400
        flash("Nessun elemento selezionato.", "warning")
        return redirect(url_for("wanted.wanted_view"))

    deleted = 0
    for media_id in media_ids:
        try:
            if db.delete_media_item(int(media_id)):
                deleted += 1
        except ValueError:
            continue

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "deleted": deleted})

    flash(
        f"Eliminati {deleted} elementi dai wanted.",
        "success" if deleted else "warning"
    )
    return redirect(url_for("wanted.wanted_view"))


@bp.route("/wanted/<int:media_item_id>/delete", methods=["POST"])
def wanted_delete(media_item_id):
    deleted = db.delete_media_item(media_item_id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "deleted": bool(deleted)})
    if deleted:
        flash("Elemento rimosso dai wanted.", "success")
    else:
        flash("Elemento non trovato.", "warning")
    return redirect(url_for("wanted.wanted_view"))


@bp.route("/api/wanted/<int:media_item_id>/lookup/tmdb")
def wanted_lookup_tmdb(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "movie":
        return json_items([])

    raw_query = request.args.get("q")
    imdb_query = (raw_query or "").strip()
    if imdb_query and imdb_query.lower().startswith("tt") and imdb_query[2:].isdigit():
        imdb_match = radarr_api.radarr_lookup_by_imdb(imdb_query, db)
        if imdb_match and imdb_match.tmdb_id:
            return json_items([{
                "title": imdb_match.title,
                "year": imdb_match.year,
                "external_id": imdb_match.tmdb_id,
                "imdb_id": imdb_match.imdb_id
            }])
    tmdb_query = (raw_query or "").strip()
    tmdb_id = None
    tmdb_slug = None
    is_explicit_tmdb = False
    if tmdb_query:
        import re
        slug_match = re.match(r"^(\d+)-(.+)", tmdb_query)
        if slug_match:
            tmdb_id = slug_match.group(1)
            tmdb_slug = slug_match.group(2)
            is_explicit_tmdb = True
        else:
            url_match = re.search(r"/movie/(\d+)", tmdb_query)
            if url_match:
                tmdb_id = url_match.group(1)
                is_explicit_tmdb = True
                slug_part = re.search(rf"/movie/{tmdb_id}-([A-Za-z0-9-]+)", tmdb_query)
                if slug_part:
                    tmdb_slug = slug_part.group(1)
    if tmdb_id and tmdb_id.isdigit() and is_explicit_tmdb:
        display_title = None
        if tmdb_slug:
            display_title = tmdb_slug.replace("-", " ").strip()
        if not display_title:
            display_title = item.title
        return json_items([{
            "title": display_title,
            "year": item.year,
            "external_id": int(tmdb_id),
            "imdb_id": None
        }])
    if tmdb_id and tmdb_id.isdigit():
        tmdb_match = radarr_api.radarr_lookup_by_tmdb(int(tmdb_id), db)
        if tmdb_match and tmdb_match.tmdb_id:
            return json_items([{
                "title": tmdb_match.title,
                "year": tmdb_match.year,
                "external_id": tmdb_match.tmdb_id,
                "imdb_id": tmdb_match.imdb_id
            }])
        return json_items([])

    def normalize_query(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.replace(":", " ").replace("-", " ")
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned or None

    candidates = []
    for value in [raw_query, item.title, item.original_title]:
        if value and value not in candidates:
            candidates.append(value)
        normalized = normalize_query(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    results = []
    seen_tmdb = set()
    for query in candidates:
        lookup = radarr_api.radarr_lookup(query, item.year, db)
        if not lookup and item.year:
            lookup = radarr_api.radarr_lookup(query, None, db)
        for r in lookup:
            if r.tmdb_id and r.tmdb_id not in seen_tmdb:
                results.append(r)
                seen_tmdb.add(r.tmdb_id)

    items = [
        {
            "title": r.title,
            "year": r.year,
            "external_id": r.tmdb_id,
            "imdb_id": r.imdb_id
        }
        for r in results
        if r.tmdb_id
    ]
    return json_items(items)


@bp.route("/api/wanted/<int:media_item_id>/lookup/tvdb")
def wanted_lookup_tvdb(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "series":
        return json_items([])

    lookup_title = request.args.get("q") or get_lookup_title(item)
    results = sonarr_api.sonarr_lookup(lookup_title, db)
    items = [
        {
            "title": r.title,
            "year": r.year,
            "external_id": r.tvdb_id,
            "imdb_id": r.imdb_id,
            "slug": r.slug,
            "link": f"https://thetvdb.com/series/{r.slug}" if r.slug else None
        }
        for r in results
        if r.tvdb_id
    ]
    return json_items(items)


@bp.route("/api/wanted/<int:media_item_id>/lookup/anilist")
def wanted_lookup_anilist(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.category != "anime":
        return json_items([])

    lookup_title = request.args.get("q") or get_lookup_title(item)
    results = [aw_api.AWMedia(r) for r in aw_api.find(lookup_title)]
    items = [
        {
            "title": r.title,
            "year": r.year,
            "external_id": r.anilist_id,
            "link": r.link
        }
        for r in results
        if r.anilist_id
    ]
    return json_items(items)


@bp.route("/api/wanted/<int:media_item_id>/external", methods=["POST"])
def wanted_set_external(media_item_id):
    data = request.get_json(silent=True) or {}
    source = data.get("source")
    external_id = data.get("external_id")
    link = data.get("link")
    if not source or not external_id:
        return jsonify({"ok": False, "error": "missing_parameters"}), 400
    item = db.get_media_item(media_item_id)
    if not item:
        return jsonify({"ok": False, "error": "not_found"}), 404

    db.add_external_id(media_item_id, source, str(external_id))
    if source == "anilist":
        db.add_external_id(media_item_id, "anilist_link", f"https://anilist.co/anime/{external_id}")
    if source == "tvdb" and link:
        db.add_external_id(media_item_id, "tvdb_link", link)

    in_radarr = False
    in_sonarr = False
    if source == "tmdb" and item.media_type == "movie":
        try:
            tmdb_val = int(external_id)
        except (TypeError, ValueError):
            tmdb_val = None
        if tmdb_val:
            existing = radarr_api.radarr_get_by_tmdb(tmdb_val, db)
            if existing:
                db.add_external_id(media_item_id, "radarr", str(tmdb_val))
                in_radarr = True
    if source == "tvdb" and item.media_type == "series":
        try:
            tvdb_val = int(external_id)
        except (TypeError, ValueError):
            tvdb_val = None
        if tvdb_val:
            existing = sonarr_api.sonarr_get_by_tvdb(tvdb_val, db)
            if existing:
                db.add_external_id(media_item_id, "sonarr", str(tvdb_val))
                in_sonarr = True

    return jsonify({"ok": True, "in_radarr": in_radarr, "in_sonarr": in_sonarr})


@bp.route("/api/wanted/<int:media_item_id>/radarr/add", methods=["POST"])
def wanted_add_radarr(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "movie":
        return jsonify({"ok": False, "error": "invalid_item"}), 400

    tmdb_id = item.external_ids.get("tmdb")
    if not tmdb_id:
        return jsonify({"ok": False, "error": "missing_tmdb"}), 400

    data = request.get_json(silent=True) or {}
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    enable_search = data.get("enable_search")
    if not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_options"}), 400

    existing = radarr_api.radarr_get_by_tmdb(int(tmdb_id), db)
    if existing:
        db.add_external_id(media_item_id, "radarr", str(tmdb_id))
        return jsonify({"ok": True, "status": "exists"})

    radarr_item = radarr_api.RadarrMedia(
        title=item.title,
        year=item.year,
        tmdb_id=int(tmdb_id),
        imdb_id=item.external_ids.get("imdb"),
        root_folder=root_folder,
        monitored=True
    )
    added = radarr_api.radarr_add_movie(
        radarr_item,
        profile_id=int(profile_id),
        root_folder=root_folder,
        enable_search=bool(enable_search),
        db=db
    )
    if added:
        db.add_external_id(media_item_id, "radarr", str(tmdb_id))
        return jsonify({"ok": True, "status": "added"})
    return jsonify({"ok": False, "error": "radarr_add_failed"}), 500


@bp.route("/api/wanted/<int:media_item_id>/radarr/update", methods=["POST"])
def wanted_update_radarr(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "movie":
        return jsonify({"ok": False, "error": "invalid_item"}), 400

    tmdb_id = item.external_ids.get("tmdb")
    if not tmdb_id:
        return jsonify({"ok": False, "error": "missing_tmdb"}), 400

    data = request.get_json(silent=True) or {}
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    enable_search = data.get("enable_search")
    if not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_options"}), 400

    movie = radarr_api.radarr_get_by_tmdb_raw(int(tmdb_id), db)
    if not movie:
        return jsonify({"ok": False, "error": "not_in_radarr"}), 400

    movie["rootFolderPath"] = root_folder
    movie["qualityProfileId"] = int(profile_id)
    current_path = movie.get("path") or ""
    folder_name = os.path.basename(os.path.normpath(current_path)) if current_path else ""
    if folder_name:
        movie["path"] = os.path.join(root_folder, folder_name)
    ok = radarr_api.radarr_update_movie(movie, db, move_files=True)
    if not ok:
        return jsonify({"ok": False, "error": "radarr_update_failed"}), 500

    if enable_search:
        radarr_api.radarr_trigger_movie_search(int(movie.get("id")), db)

    return jsonify({"ok": True, "status": "updated"})


@bp.route("/api/wanted/<int:media_item_id>/sonarr/add", methods=["POST"])
def wanted_add_sonarr(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "series":
        return jsonify({"ok": False, "error": "invalid_item"}), 400

    tvdb_id = item.external_ids.get("tvdb")
    if not tvdb_id:
        return jsonify({"ok": False, "error": "missing_tvdb"}), 400

    data = request.get_json(silent=True) or {}
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    monitor_specials = data.get("monitor_specials")
    enable_search = data.get("enable_search")
    if not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_options"}), 400

    existing = sonarr_api.sonarr_get_by_tvdb(int(tvdb_id), db)
    if existing:
        db.add_external_id(media_item_id, "sonarr", str(tvdb_id))
        return jsonify({"ok": True, "status": "exists"})

    sonarr_item = sonarr_api.sonarr_lookup_by_tvdb(int(tvdb_id), db)
    if not sonarr_item:
        sonarr_item = sonarr_api.SonarrMedia(
            title=item.title,
            year=item.year,
            tvdb_id=int(tvdb_id),
            imdb_id=item.external_ids.get("imdb"),
            root_folder=root_folder,            
            monitored=True
        )
    added = sonarr_api.sonarr_add_series(
        sonarr_item,
        profile_id=int(profile_id),
        root_folder=root_folder,
        enable_search=bool(enable_search),
        monitor_specials=bool(monitor_specials),
        db=db
    )
    if added:
        db.add_external_id(media_item_id, "sonarr", str(tvdb_id))
        return jsonify({"ok": True, "status": "added"})
    return jsonify({"ok": False, "error": "sonarr_add_failed"}), 500


@bp.route("/api/wanted/<int:media_item_id>/sonarr/update", methods=["POST"])
def wanted_update_sonarr(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "series":
        return jsonify({"ok": False, "error": "invalid_item"}), 400

    tvdb_id = item.external_ids.get("tvdb")
    if not tvdb_id:
        return jsonify({"ok": False, "error": "missing_tvdb"}), 400

    data = request.get_json(silent=True) or {}
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    monitor_specials_raw = data.get("monitor_specials")
    enable_search = data.get("enable_search")
    if not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_options"}), 400

    series = sonarr_api.sonarr_get_by_tvdb_raw(int(tvdb_id), db)
    if not series:
        return jsonify({"ok": False, "error": "not_in_sonarr"}), 400

    series["rootFolderPath"] = root_folder
    series["qualityProfileId"] = int(profile_id)
    current_path = series.get("path") or ""
    folder_name = os.path.basename(os.path.normpath(current_path)) if current_path else ""
    if folder_name:
        series["path"] = os.path.join(root_folder, folder_name)
    ok = sonarr_api.sonarr_update_series(series, db, move_files=True)
    if not ok:
        return jsonify({"ok": False, "error": "sonarr_update_failed"}), 500

    series_id = series.get("id")
    monitor_specials = str(monitor_specials_raw).strip().lower() in ("1", "true", "yes", "on")
    if monitor_specials and series_id:
        sonarr_api.sonarr_set_monitor_all_seasons(series_id, db)
        sonarr_api.sonarr_monitor_specials_episodes(series_id, db)
    if enable_search and series_id:
        sonarr_api.sonarr_trigger_series_search(series_id, db)

    return jsonify({"ok": True, "status": "updated"})


@bp.route("/api/wanted/radarr/bulk_add", methods=["POST"])
def wanted_bulk_add_radarr():
    data = request.get_json(silent=True) or {}
    media_ids = data.get("media_ids") or []
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    enable_search = data.get("enable_search")
    if not media_ids or not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_parameters"}), 400

    radarr_movies = radarr_api.radarr_get_all_movies(db)
    existing_tmdb = {str(m.tmdb_id) for m in radarr_movies if m.tmdb_id}

    added = 0
    skipped = 0
    errors = 0
    added_ids = []
    skipped_ids = []
    error_ids = []
    for media_id in media_ids:
        try:
            media_id = int(media_id)
        except (TypeError, ValueError):
            skipped += 1
            continue

        item = db.get_media_item(media_id)
        if not item or item.media_type != "movie":
            skipped += 1
            continue

        tmdb_id = item.external_ids.get("tmdb")
        if not tmdb_id:
            skipped += 1
            continue

        if str(tmdb_id) in existing_tmdb:
            db.add_external_id(media_id, "radarr", str(tmdb_id))
            skipped += 1
            skipped_ids.append(media_id)
            continue

        radarr_item = radarr_api.RadarrMedia(
            title=item.title,
            year=item.year,
            tmdb_id=int(tmdb_id),
            imdb_id=item.external_ids.get("imdb"),
            root_folder=root_folder,
            monitored=True
        )
        ok = radarr_api.radarr_add_movie(
            radarr_item,
            profile_id=int(profile_id),
            root_folder=root_folder,
            enable_search=bool(enable_search),
            db=db
        )
        if ok:
            db.add_external_id(media_id, "radarr", str(tmdb_id))
            existing_tmdb.add(str(tmdb_id))
            added += 1
            added_ids.append(media_id)
        else:
            errors += 1
            error_ids.append(media_id)

    return jsonify({
        "ok": True,
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "added_ids": added_ids,
        "skipped_ids": skipped_ids,
        "error_ids": error_ids
    })


@bp.route("/api/wanted/radarr/bulk_update", methods=["POST"])
def wanted_bulk_update_radarr():
    data = request.get_json(silent=True) or {}
    media_ids = data.get("media_ids") or []
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    enable_search = data.get("enable_search")
    if not media_ids or not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_parameters"}), 400

    updated = 0
    skipped = 0
    errors = 0
    updated_ids = []
    skipped_ids = []
    error_ids = []
    for media_id in media_ids:
        try:
            media_id = int(media_id)
        except (TypeError, ValueError):
            skipped += 1
            continue

        item = db.get_media_item(media_id)
        if not item or item.media_type != "movie":
            skipped += 1
            skipped_ids.append(media_id)
            continue

        tmdb_id = item.external_ids.get("tmdb")
        if not tmdb_id:
            skipped += 1
            skipped_ids.append(media_id)
            continue

        movie = radarr_api.radarr_get_by_tmdb_raw(int(tmdb_id), db)
        if not movie:
            skipped += 1
            skipped_ids.append(media_id)
            continue

        movie["rootFolderPath"] = root_folder
        movie["qualityProfileId"] = int(profile_id)
        current_path = movie.get("path") or ""
        folder_name = os.path.basename(os.path.normpath(current_path)) if current_path else ""
        if folder_name:
            movie["path"] = os.path.join(root_folder, folder_name)
        ok = radarr_api.radarr_update_movie(movie, db, move_files=True)
        if ok:
            updated += 1
            updated_ids.append(media_id)
            if enable_search:
                radarr_api.radarr_trigger_movie_search(int(movie.get("id")), db)
        else:
            errors += 1
            error_ids.append(media_id)

    return jsonify({
        "ok": True,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "updated_ids": updated_ids,
        "skipped_ids": skipped_ids,
        "error_ids": error_ids
    })


@bp.route("/api/wanted/sonarr/bulk_add", methods=["POST"])
def wanted_bulk_add_sonarr():
    data = request.get_json(silent=True) or {}
    media_ids = data.get("media_ids") or []
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    enable_search = data.get("enable_search")
    monitor_specials_raw = data.get("monitor_specials")
    monitor_specials = str(monitor_specials_raw).strip().lower() in ("1", "true", "yes", "on")
    if not media_ids or not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_parameters"}), 400

    sonarr_series = sonarr_api.sonarr_get_all_series(db)
    existing_tvdb = {str(s.tvdb_id) for s in sonarr_series if s.tvdb_id}

    added = 0
    skipped = 0
    errors = 0
    added_ids = []
    skipped_ids = []
    error_ids = []
    for media_id in media_ids:
        try:
            media_id = int(media_id)
        except (TypeError, ValueError):
            skipped += 1
            continue

        item = db.get_media_item(media_id)
        if not item or item.media_type != "series":
            skipped += 1
            continue

        tvdb_id = item.external_ids.get("tvdb")
        if not tvdb_id:
            skipped += 1
            continue

        if str(tvdb_id) in existing_tvdb:
            db.add_external_id(media_id, "sonarr", str(tvdb_id))
            skipped += 1
            skipped_ids.append(media_id)
            continue

        sonarr_item = sonarr_api.sonarr_lookup_by_tvdb(int(tvdb_id), db)
        if not sonarr_item:
            sonarr_item = sonarr_api.SonarrMedia(
                title=item.title,
                year=item.year,
                tvdb_id=int(tvdb_id),
                imdb_id=item.external_ids.get("imdb"),
                root_folder=root_folder,
                monitored=True
            )
        ok = sonarr_api.sonarr_add_series(
            sonarr_item,
            profile_id=int(profile_id),
            root_folder=root_folder,
            enable_search=bool(enable_search),
            monitor_specials=bool(monitor_specials),
            db=db
        )
        if ok:
            db.add_external_id(media_id, "sonarr", str(tvdb_id))
            existing_tvdb.add(str(tvdb_id))
            added += 1
            added_ids.append(media_id)
        else:
            errors += 1
            error_ids.append(media_id)

    return jsonify({
        "ok": True,
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "added_ids": added_ids,
        "skipped_ids": skipped_ids,
        "error_ids": error_ids
    })


@bp.route("/api/wanted/sonarr/bulk_update", methods=["POST"])
def wanted_bulk_update_sonarr():
    data = request.get_json(silent=True) or {}
    media_ids = data.get("media_ids") or []
    root_folder = data.get("root_folder")
    profile_id = data.get("profile_id")
    enable_search = data.get("enable_search")
    monitor_specials_raw = data.get("monitor_specials")
    monitor_specials = str(monitor_specials_raw).strip().lower() in ("1", "true", "yes", "on")
    if not media_ids or not root_folder or not profile_id:
        return jsonify({"ok": False, "error": "missing_parameters"}), 400

    updated = 0
    skipped = 0
    errors = 0
    updated_ids = []
    skipped_ids = []
    error_ids = []
    for media_id in media_ids:
        try:
            media_id = int(media_id)
        except (TypeError, ValueError):
            skipped += 1
            continue

        item = db.get_media_item(media_id)
        if not item or item.media_type != "series":
            skipped += 1
            skipped_ids.append(media_id)
            continue

        tvdb_id = item.external_ids.get("tvdb")
        if not tvdb_id:
            skipped += 1
            skipped_ids.append(media_id)
            continue

        series = sonarr_api.sonarr_get_by_tvdb_raw(int(tvdb_id), db)
        if not series:
            skipped += 1
            skipped_ids.append(media_id)
            continue

        series["rootFolderPath"] = root_folder
        series["qualityProfileId"] = int(profile_id)
        current_path = series.get("path") or ""
        folder_name = os.path.basename(os.path.normpath(current_path)) if current_path else ""
        if folder_name:
            series["path"] = os.path.join(root_folder, folder_name)
        ok = sonarr_api.sonarr_update_series(series, db, move_files=True)
        if ok:
            updated += 1
            updated_ids.append(media_id)
            series_id = series.get("id")
            if monitor_specials and series_id:
                sonarr_api.sonarr_set_monitor_all_seasons(series_id, db)
                sonarr_api.sonarr_monitor_specials_episodes(series_id, db)
            if enable_search and series_id:
                sonarr_api.sonarr_trigger_series_search(series_id, db)
        else:
            errors += 1
            error_ids.append(media_id)

    return jsonify({
        "ok": True,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "updated_ids": updated_ids,
        "skipped_ids": skipped_ids,
        "error_ids": error_ids
    })


def _merge_required_external(item: Media) -> tuple[str, str] | tuple[None, None]:
    if item.media_type == "movie":
        return "tmdb", item.external_ids.get("tmdb")
    if item.category == "anime":
        return "tvdb", item.external_ids.get("tvdb")
    return "tvdb", item.external_ids.get("tvdb")


@bp.route("/api/wanted/merge/preview", methods=["POST"])
def wanted_merge_preview():
    data = request.get_json(silent=True) or {}
    media_ids = data.get("media_ids") or []
    if not media_ids:
        return jsonify({"ok": False, "error": "missing_media_ids"}), 400

    items = []
    excluded = []
    for raw_id in media_ids:
        try:
            media_id = int(raw_id)
        except (TypeError, ValueError):
            excluded.append({"id": raw_id, "reason": "invalid_id"})
            continue
        item = db.get_media_item(media_id)
        if not item:
            excluded.append({"id": media_id, "reason": "not_found"})
            continue
        source, external_id = _merge_required_external(item)
        if not external_id:
            excluded.append({
                "id": item.id,
                "title": item.title,
                "reason": f"missing_{source}"
            })
            continue
        items.append({
            "id": item.id,
            "title": item.title,
            "year": item.year,
            "media_type": item.media_type,
            "category": item.category,
            "source": source,
            "external_id": str(external_id)
        })

    groups: dict[tuple[str, str], list[dict]] = {}
    for item in items:
        key = (item["source"], item["external_id"])
        groups.setdefault(key, []).append(item)

    merge_groups = []
    singletons = []
    for (source, external_id), group_items in groups.items():
        group_items.sort(key=lambda x: x["id"])
        if len(group_items) > 1:
            merge_groups.append({
                "source": source,
                "external_id": external_id,
                "keep_id": group_items[0]["id"],
                "items": group_items
            })
        else:
            singletons.append(group_items[0])

    return jsonify({
        "ok": True,
        "merge_groups": merge_groups,
        "singletons": singletons,
        "excluded": excluded
    })


@bp.route("/api/wanted/merge/commit", methods=["POST"])
def wanted_merge_commit():
    data = request.get_json(silent=True) or {}
    groups = data.get("groups") or []
    if not groups:
        return jsonify({"ok": False, "error": "missing_groups"}), 400

    merged = 0
    for group in groups:
        keep_id = group.get("keep_id")
        merge_ids = group.get("merge_ids") or []
        if not keep_id or not merge_ids:
            continue
        merged += db.merge_media_items(int(keep_id), [int(mid) for mid in merge_ids])

    return jsonify({"ok": True, "merged": merged})


def _normalize_lookup_title(value: str | None, year: int | None = None) -> str | None:
    if not value:
        return None
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}", " ", value)
    if year:
        try:
            text = re.sub(rf"\b{int(year)}\b", " ", text)
        except (TypeError, ValueError):
            pass
    text = re.sub(r"[\"'&,.:;!?/\\\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _build_lookup_queries(item: Media) -> list[str]:
    candidates: list[str] = []
    for title in [item.title, item.original_title]:
        if not title:
            continue
        candidates.append(title)
        cleaned = _normalize_lookup_title(title, item.year)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    normalized = _normalize_lookup_title(item.title, item.year)
    if normalized and normalized not in candidates:
        candidates.append(normalized)
    return candidates[:5]


def _dedupe_candidates(results: list[dict], key_name: str) -> list[dict]:
    seen = set()
    deduped = []
    for item in results:
        key = item.get(key_name)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


@bp.route("/api/wanted/bulk_lookup/tvdb", methods=["POST"])
def wanted_bulk_lookup_tvdb():
    data = request.get_json(silent=True) or {}
    media_ids = data.get("media_ids") or []
    if not media_ids:
        return jsonify({"ok": False, "error": "missing_media_ids"}), 400

    items = []
    skipped = []
    for raw_id in media_ids:
        try:
            media_id = int(raw_id)
        except (TypeError, ValueError):
            skipped.append({"id": raw_id, "reason": "invalid_id"})
            continue
        media = db.get_media_item(media_id)
        if not media:
            skipped.append({"id": media_id, "reason": "not_found"})
            continue
        if media.media_type != "series":
            skipped.append({"id": media_id, "reason": "not_series"})
            continue
        if media.external_ids.get("tvdb"):
            skipped.append({"id": media_id, "reason": "has_tvdb"})
            continue

        queries = _build_lookup_queries(media)
        candidates: list[dict] = []
        used_query = None
        for query in queries:
            lookup = sonarr_api.sonarr_lookup(query, db)
            if lookup and used_query is None:
                used_query = query
            for result in lookup:
                if not result.tvdb_id:
                    continue
                link = f"https://thetvdb.com/series/{result.slug}" if result.slug else None
                candidates.append({
                    "external_id": str(result.tvdb_id),
                    "title": result.title,
                    "year": result.year,
                    "link": link
                })
        candidates = _dedupe_candidates(candidates, "external_id")[:5]
        items.append({
            "media_id": media.id,
            "title": media.title,
            "year": media.year,
            "media_type": media.media_type,
            "query": used_query or (queries[0] if queries else ""),
            "candidates": candidates
        })

    return jsonify({"ok": True, "source": "tvdb", "items": items, "skipped": skipped})


@bp.route("/api/wanted/bulk_lookup/tmdb", methods=["POST"])
def wanted_bulk_lookup_tmdb():
    data = request.get_json(silent=True) or {}
    media_ids = data.get("media_ids") or []
    if not media_ids:
        return jsonify({"ok": False, "error": "missing_media_ids"}), 400

    items = []
    skipped = []
    for raw_id in media_ids:
        try:
            media_id = int(raw_id)
        except (TypeError, ValueError):
            skipped.append({"id": raw_id, "reason": "invalid_id"})
            continue
        media = db.get_media_item(media_id)
        if not media:
            skipped.append({"id": media_id, "reason": "not_found"})
            continue
        if media.media_type != "movie":
            skipped.append({"id": media_id, "reason": "not_movie"})
            continue
        if media.external_ids.get("tmdb"):
            skipped.append({"id": media_id, "reason": "has_tmdb"})
            continue

        queries = _build_lookup_queries(media)
        candidates: list[dict] = []
        used_query = None
        for query in queries:
            lookup = radarr_api.radarr_lookup(query, media.year, db)
            if not lookup and media.year:
                lookup = radarr_api.radarr_lookup(query, None, db)
            if lookup and used_query is None:
                used_query = query
            for result in lookup:
                if not result.tmdb_id:
                    continue
                link = f"https://www.themoviedb.org/movie/{result.tmdb_id}"
                candidates.append({
                    "external_id": str(result.tmdb_id),
                    "title": result.title,
                    "year": result.year,
                    "link": link
                })
        candidates = _dedupe_candidates(candidates, "external_id")[:5]
        items.append({
            "media_id": media.id,
            "title": media.title,
            "year": media.year,
            "media_type": media.media_type,
            "query": used_query or (queries[0] if queries else ""),
            "candidates": candidates
        })

    return jsonify({"ok": True, "source": "tmdb", "items": items, "skipped": skipped})


@bp.route("/api/wanted/bulk_external", methods=["POST"])
def wanted_bulk_external():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not items:
        return jsonify({"ok": False, "error": "missing_items"}), 400

    updated = 0
    skipped = 0
    errors = 0
    updated_items = []
    for payload in items:
        media_id = payload.get("media_id")
        source = payload.get("source")
        external_id = payload.get("external_id")
        link = payload.get("link")
        try:
            media_id = int(media_id)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not source or not external_id:
            skipped += 1
            continue

        item = db.get_media_item(media_id)
        if not item:
            skipped += 1
            continue

        if source == "tmdb" and item.media_type != "movie":
            skipped += 1
            continue
        if source == "tvdb" and item.media_type != "series":
            skipped += 1
            continue
        if item.external_ids.get(source):
            skipped += 1
            continue

        try:
            db.add_external_id(media_id, source, str(external_id))
            if source == "tvdb" and link:
                db.add_external_id(media_id, "tvdb_link", link)
        except Exception:
            errors += 1
            continue

        in_radarr = False
        in_sonarr = False
        if source == "tmdb" and item.media_type == "movie":
            try:
                tmdb_val = int(external_id)
            except (TypeError, ValueError):
                tmdb_val = None
            if tmdb_val:
                existing = radarr_api.radarr_get_by_tmdb(tmdb_val, db)
                if existing:
                    db.add_external_id(media_id, "radarr", str(tmdb_val))
                    in_radarr = True
        if source == "tvdb" and item.media_type == "series":
            try:
                tvdb_val = int(external_id)
            except (TypeError, ValueError):
                tvdb_val = None
            if tvdb_val:
                existing = sonarr_api.sonarr_get_by_tvdb(tvdb_val, db)
                if existing:
                    db.add_external_id(media_id, "sonarr", str(tvdb_val))
                    in_sonarr = True

        updated += 1
        updated_items.append({
            "media_id": media_id,
            "source": source,
            "external_id": str(external_id),
            "link": link,
            "in_radarr": in_radarr,
            "in_sonarr": in_sonarr
        })

    return jsonify({
        "ok": True,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "items": updated_items
    })
