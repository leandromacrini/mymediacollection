from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for, flash

from api import ddunlimited_api as ddu_api
from app.extensions import db
from app.utils import build_ddunlimited_media

bp = Blueprint("ddunlimited", __name__)


@bp.route("/ddunlimited", methods=["GET", "POST"])
def ddunlimited_view():
    search_results = []
    query = request.args.get("q")
    cache_status = ddu_api.get_cache_status()

    if request.method == "POST":
        query = request.form.get("search_query")

    if query:
        wanted_items = db.get_wanted_items(limit=None)
        wanted_by_ddun = {
            item.external_ids.get("ddunlimited")
            for item in wanted_items
            if item.external_ids.get("ddunlimited")
        }

        results = ddu_api.search_lists(query, db)
        for item in results:
            if item.topic_id and str(item.topic_id) in wanted_by_ddun:
                item.source_name = item.source_name or "DDUnlimited"
                item.info = item.info or ""
                item.status = "wanted"
            else:
                item.status = "new"
        search_results = results

        if not search_results:
            flash(f"Nessun risultato trovato per '{query}'", "warning")

    return render_template(
        "ddunlimited.html",
        results=search_results,
        query=query,
        cache_status=cache_status
    )


@bp.route("/ddunlimited/add_wanted", methods=["POST"])
def add_wanted_ddunlimited():
    search_query = request.form.get("search_query")
    detail_url = request.form.get("detail_url")
    topic_id = request.form.get("topic_id")
    if not detail_url or "ddunlimited.net" not in detail_url:
        flash("Link DDU non valido.", "danger")
        return redirect(url_for("ddunlimited.ddunlimited_view", q=search_query) if search_query else url_for("ddunlimited.ddunlimited_view"))

    media = build_ddunlimited_media(request.form)
    media_item_id, inserted = db.add_media(media)
    if topic_id:
        db.add_external_id(media_item_id, "ddunlimited", str(topic_id))
    db.add_external_id(media_item_id, "ddunlimited_link", detail_url)

    flash(
        f"Elemento {'aggiunto ai' if inserted else 'gia nei'} wanted: {media.title}",
        "success" if inserted else "info"
    )
    return redirect(url_for("ddunlimited.ddunlimited_view", q=search_query)) if search_query else redirect(url_for("ddunlimited.ddunlimited_view"))


@bp.route("/api/ddunlimited/sources", methods=["GET"])
def ddunlimited_sources_list():
    sources = db.get_ddunlimited_sources(include_disabled=True)
    return jsonify({"items": sources})


@bp.route("/api/ddunlimited/sources", methods=["POST"])
def ddunlimited_sources_add():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    media_type = (data.get("media_type") or "").strip().lower()
    if not name or not url or media_type not in ("movie", "series"):
        return jsonify({"ok": False, "error": "invalid_data"}), 400
    if db.get_ddunlimited_source_by_url(url):
        return jsonify({"ok": False, "error": "duplicate_url"}), 409
    payload = {
        "name": name,
        "url": url,
        "media_type": media_type,
        "category": (data.get("category") or "").strip() or None,
        "quality": (data.get("quality") or "").strip() or None,
        "language": (data.get("language") or "").strip() or None,
        "enabled": bool(data.get("enabled", True))
    }
    source_id = db.add_ddunlimited_source(payload)
    if not source_id:
        return jsonify({"ok": False, "error": "insert_failed"}), 500
    return jsonify({"ok": True, "id": source_id})


@bp.route("/api/ddunlimited/sources/<int:source_id>", methods=["PUT"])
def ddunlimited_sources_update(source_id: int):
    data = request.get_json(silent=True) or {}
    payload = {}
    for key in ("name", "url", "media_type", "category", "quality", "language", "enabled"):
        if key in data:
            payload[key] = data.get(key)
    if "media_type" in payload:
        mt = (payload.get("media_type") or "").strip().lower()
        if mt not in ("movie", "series"):
            return jsonify({"ok": False, "error": "invalid_media_type"}), 400
        payload["media_type"] = mt
    ok = db.update_ddunlimited_source(source_id, payload)
    return jsonify({"ok": ok})


@bp.route("/api/ddunlimited/sources/<int:source_id>", methods=["DELETE"])
def ddunlimited_sources_delete(source_id: int):
    ok = db.delete_ddunlimited_source(source_id)
    return jsonify({"ok": ok})


@bp.route("/api/ddunlimited/sources/<int:source_id>/test", methods=["POST"])
def ddunlimited_sources_test(source_id: int):
    source = db.get_ddunlimited_source(source_id)
    if not source:
        return jsonify({"ok": False, "error": "not_found"}), 404
    session, cfg = ddu_api._build_session(db)
    try:
        html = ddu_api._fetch_html(source["url"], session)
        source_obj = ddu_api.DDUListSource(
            name=source["name"],
            url=source["url"],
            media_type=source["media_type"],
            category=source.get("category"),
            quality=source.get("quality"),
            language=source.get("language")
        )
        items = ddu_api.parse_list_page(html, source_obj, cfg["base_url"])
        count = len(items)
        db.set_ddunlimited_source_stats(source_id, count)
        return jsonify({"ok": True, "count": count})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/ddunlimited/ed2k", methods=["GET"])
def ddunlimited_ed2k_api():
    detail_url = (request.args.get("url") or "").strip()
    if not detail_url or "ddunlimited.net" not in detail_url:
        abort(400)
    detail = ddu_api.get_release_ed2k(detail_url, db)
    return jsonify(detail)


@bp.route("/api/ddunlimited/cache/status", methods=["GET"])
def ddunlimited_cache_status():
    return jsonify(ddu_api.get_cache_status())


@bp.route("/api/ddunlimited/cache/refresh", methods=["POST"])
def ddunlimited_cache_refresh():
    result = ddu_api.start_refresh(db)
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@bp.route("/api/ddunlimited/cache/progress", methods=["GET"])
def ddunlimited_cache_progress():
    return jsonify(ddu_api.get_refresh_status())


@bp.route("/api/ddunlimited/cache/cancel", methods=["POST"])
def ddunlimited_cache_cancel():
    return jsonify(ddu_api.cancel_refresh())
