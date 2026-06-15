from dataclasses import asdict

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for, flash

from api import ddunlimited_api as ddu_api
from api import ddunlimited_browser
from app.extensions import db
from app.utils import build_ddunlimited_media

bp = Blueprint("ddunlimited", __name__)


def _item_to_dict(item):
    payload = asdict(item)
    payload["topic_id"] = str(payload["topic_id"]) if payload.get("topic_id") is not None else None
    return payload


@bp.route("/ddunlimited", methods=["GET", "POST"])
def ddunlimited_view():
    search_results = []
    query = request.args.get("q")
    cache_status = ddu_api.get_cache_status()
    browser_status = ddunlimited_browser.get_browser_status(db)

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
        cache_status=cache_status,
        browser_status=browser_status
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
    cfg = ddu_api._get_config(db)
    try:
        html = ddu_api._fetch_html(source["url"], db=db)
        ddu_api._validate_list_page_html(html, source["name"])
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
    except ddunlimited_browser.DDUBrowserAuthRequired as exc:
        return jsonify({"ok": False, "error": "auth_required", "message": str(exc)}), 409
    except ddu_api.DDUInvalidSourcePage as exc:
        return jsonify({"ok": False, "error": "invalid_source_page", "message": str(exc)}), 422
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/ddunlimited/ed2k", methods=["GET"])
def ddunlimited_ed2k_api():
    detail_url = (request.args.get("url") or "").strip()
    if not detail_url or "ddunlimited.net" not in detail_url:
        abort(400)
    try:
        detail = ddu_api.get_release_ed2k(detail_url, db)
        return jsonify(detail)
    except ddunlimited_browser.DDUBrowserAuthRequired as exc:
        return jsonify({"ok": False, "error": "auth_required", "message": str(exc)}), 409
    except ddu_api.DDUInvalidSourcePage as exc:
        return jsonify({"ok": False, "error": "invalid_source_page", "message": str(exc)}), 422


@bp.route("/api/ddunlimited/search", methods=["GET"])
def ddunlimited_search_api():
    query = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", type=int) or 50
    limit = max(1, min(limit, 500))
    if not query:
        return jsonify({"ok": False, "error": "missing_query", "message": "Parametro q mancante."}), 400

    wanted_items = db.get_wanted_items(limit=None)
    wanted_by_ddun = {
        item.external_ids.get("ddunlimited")
        for item in wanted_items
        if item.external_ids.get("ddunlimited")
    }

    results = ddu_api.search_cache(query, max_results=limit)
    items = []
    for item in results:
        if item.topic_id and str(item.topic_id) in wanted_by_ddun:
            item.status = "wanted"
        elif item.status is None:
            item.status = "new"
        items.append(_item_to_dict(item))
    return jsonify({
        "ok": True,
        "query": query,
        "count": len(items),
        "items": items,
    })


@bp.route("/api/ddunlimited/release", methods=["GET"])
def ddunlimited_release_api():
    detail_url = (request.args.get("url") or "").strip()
    topic_id = (request.args.get("topic_id") or "").strip()
    if not detail_url and not topic_id:
        return jsonify({
            "ok": False,
            "error": "missing_identifier",
            "message": "Serve url o topic_id."
        }), 400

    if not detail_url:
        cfg = ddu_api._get_config(db)
        detail_url = f"{cfg['base_url']}/viewtopic.php?t={topic_id}"

    try:
        detail = ddu_api.get_release_ed2k(detail_url, db)
        detail["ok"] = True
        detail["detail_url"] = detail_url
        detail["topic_id"] = topic_id or ddu_api._extract_topic_id(detail_url)
        return jsonify(detail)
    except ddunlimited_browser.DDUBrowserAuthRequired as exc:
        return jsonify({"ok": False, "error": "auth_required", "message": str(exc)}), 409
    except ddu_api.DDUInvalidSourcePage as exc:
        return jsonify({"ok": False, "error": "invalid_source_page", "message": str(exc)}), 422


@bp.route("/api/ddunlimited/health", methods=["GET"])
def ddunlimited_health_api():
    browser_status = ddunlimited_browser.get_browser_status(db)
    cache_status = ddu_api.get_cache_status()
    refresh_status = ddu_api.get_refresh_status()
    return jsonify({
        "ok": bool(browser_status.get("ok")),
        "browser": browser_status,
        "cache": cache_status,
        "refresh": refresh_status,
    })


@bp.route("/api/ddunlimited/cache/status", methods=["GET"])
def ddunlimited_cache_status():
    return jsonify(ddu_api.get_cache_status())


@bp.route("/api/ddunlimited/browser/status", methods=["GET"])
def ddunlimited_browser_status():
    return jsonify(ddunlimited_browser.get_browser_status(db))


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
