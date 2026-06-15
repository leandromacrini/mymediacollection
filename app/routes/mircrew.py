from flask import Blueprint, abort, jsonify, flash, redirect, render_template, request, url_for

from api import mircrew_api
from api import mircrew_browser
from app.extensions import db
from core.db_core import Media

bp = Blueprint("mircrew", __name__)


def _wanted_mircrew_ids() -> set[str]:
    wanted_items = db.get_wanted_items(limit=None)
    return {
        str(item.external_ids.get("mircrew"))
        for item in wanted_items
        if item.external_ids.get("mircrew")
    }


def _format_size(size_bytes) -> str:
    try:
        n = int(size_bytes)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(n)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024 or candidate == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{n:,} B"
    return f"{value:.2f} {unit}"


@bp.route("/mircrew", methods=["GET"])
def mircrew_view():
    query = (request.args.get("q") or "").strip()
    rows = mircrew_api.search(query) if query else []
    wanted_ids = _wanted_mircrew_ids() if rows else set()
    for row in rows:
        inferred = mircrew_api.build_wanted_payload(row)
        row["year"] = inferred.get("year")
        row["media_type"] = inferred.get("media_type")
        row["status"] = "wanted" if str(row.get("release_id") or "") in wanted_ids else "new"
        size_human = _format_size(row.get("size_bytes"))
        row["size_display"] = size_human or (row.get("size_text_raw") or "")
        row["size_tooltip"] = row.get("size_text_raw") or ""

    status = mircrew_api.get_status()
    browser_status = mircrew_api.get_browser_status()
    if query and not rows:
        flash(f"Nessun risultato trovato per '{query}'", "warning")
    return render_template(
        "mircrew.html",
        query=query,
        results=rows,
        status=status,
        browser_status=browser_status,
    )


@bp.route("/mircrew/add_wanted", methods=["POST"])
def mircrew_add_wanted():
    release_id = (request.form.get("release_id") or "").strip()
    query = (request.form.get("search_query") or "").strip()
    row = mircrew_api.get_release_by_id(release_id)
    if not row:
        flash("Release MirCrew non trovata nella cache locale.", "danger")
        return redirect(url_for("mircrew.mircrew_view", q=query) if query else url_for("mircrew.mircrew_view"))

    payload = mircrew_api.build_wanted_payload(row)
    if not payload["title"]:
        flash("Release non valida: titolo mancante.", "danger")
        return redirect(url_for("mircrew.mircrew_view", q=query) if query else url_for("mircrew.mircrew_view"))

    media = Media(
        id=None,
        title=payload["title"],
        year=payload["year"],
        media_type=payload["media_type"],
        category=payload["category"],
        source=payload["source"],
        source_ref=payload["source_ref"],
        original_title=payload["original_title"],
        language=payload["language"],
    )
    media_item_id, inserted = db.add_media(media)
    db.add_external_id(media_item_id, "mircrew", payload["release_id"])
    db.add_external_id(media_item_id, "mircrew_link", payload["release_url"])
    flash(
        f"Elemento {'aggiunto ai' if inserted else 'gia nei'} wanted: {media.title}",
        "success" if inserted else "info",
    )
    return redirect(url_for("mircrew.mircrew_view", q=query) if query else url_for("mircrew.mircrew_view"))


@bp.route("/api/mircrew/browser/status", methods=["GET"])
def mircrew_browser_status():
    return jsonify(mircrew_api.get_browser_status())


@bp.route("/api/mircrew/health", methods=["GET"])
def mircrew_health():
    return jsonify({
        "ok": bool(mircrew_api.get_browser_status().get("ok")),
        "browser": mircrew_api.get_browser_status(),
        "cache": mircrew_api.get_status(),
        "refresh": mircrew_api.get_refresh_status(),
    })


@bp.route("/api/mircrew/sources", methods=["GET"])
def mircrew_sources_list():
    return jsonify({"items": db.get_mircrew_sources(include_disabled=True)})


@bp.route("/api/mircrew/sources", methods=["POST"])
def mircrew_sources_add():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    if not name or not url:
        return jsonify({"ok": False, "error": "invalid_data"}), 400
    if db.get_mircrew_source_by_url(url):
        return jsonify({"ok": False, "error": "duplicate_url"}), 409
    source_id = db.add_mircrew_source({
        "name": name,
        "url": url,
        "category_label": (data.get("category_label") or "").strip() or None,
        "category_value": (data.get("category_value") or "").strip() or None,
        "enabled": bool(data.get("enabled", True)),
    })
    if not source_id:
        return jsonify({"ok": False, "error": "insert_failed"}), 500
    return jsonify({"ok": True, "id": source_id})


@bp.route("/api/mircrew/sources/<int:source_id>", methods=["PUT"])
def mircrew_sources_update(source_id: int):
    data = request.get_json(silent=True) or {}
    payload = {}
    for key in ("name", "url", "category_label", "category_value", "enabled"):
        if key in data:
            payload[key] = data.get(key)
    ok = db.update_mircrew_source(source_id, payload)
    return jsonify({"ok": ok})


@bp.route("/api/mircrew/sources/<int:source_id>", methods=["DELETE"])
def mircrew_sources_delete(source_id: int):
    return jsonify({"ok": db.delete_mircrew_source(source_id)})


@bp.route("/api/mircrew/sources/<int:source_id>/test", methods=["POST"])
def mircrew_sources_test(source_id: int):
    source = db.get_mircrew_source(source_id)
    if not source:
        return jsonify({"ok": False, "error": "not_found"}), 404
    try:
        result = mircrew_api.start_source_refresh(db, source)
        status = 200 if result.get("ok") else 500
        return jsonify(result), status
    except mircrew_browser.MircrewBrowserAuthRequired as exc:
        return jsonify({"ok": False, "error": "auth_required", "message": str(exc)}), 409
    except mircrew_api.MircrewInvalidSourcePage as exc:
        return jsonify({"ok": False, "error": "invalid_source_page", "message": str(exc)}), 422
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/mircrew/cache/status", methods=["GET"])
def mircrew_cache_status():
    return jsonify(mircrew_api.get_status())


@bp.route("/api/mircrew/cache/refresh", methods=["POST"])
def mircrew_cache_refresh():
    result = mircrew_api.start_refresh(db)
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@bp.route("/api/mircrew/cache/progress", methods=["GET"])
def mircrew_cache_progress():
    return jsonify(mircrew_api.get_refresh_status())


@bp.route("/api/mircrew/cache/cancel", methods=["POST"])
def mircrew_cache_cancel():
    return jsonify(mircrew_api.cancel_refresh())


@bp.route("/api/mircrew/search", methods=["GET"])
def mircrew_search_api():
    query = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", type=int) or 50
    limit = max(1, min(limit, 500))
    if not query:
        return jsonify({"ok": False, "error": "missing_query", "message": "Parametro q mancante."}), 400
    rows = mircrew_api.search(query, limit=limit)
    wanted_ids = _wanted_mircrew_ids()
    items = []
    for row in rows:
        payload = dict(row)
        payload["status"] = "wanted" if str(row.get("release_id") or "") in wanted_ids else "new"
        items.append(payload)
    return jsonify({"ok": True, "query": query, "count": len(items), "items": items})


@bp.route("/api/mircrew/release", methods=["GET"])
def mircrew_release_api():
    release_id = (request.args.get("release_id") or "").strip()
    release_url = (request.args.get("url") or "").strip()
    if not release_id and not release_url:
        abort(400)
    try:
        return jsonify(mircrew_api.get_release_detail(release_id=release_id, release_url=release_url))
    except mircrew_browser.MircrewBrowserAuthRequired as exc:
        return jsonify({"ok": False, "error": "auth_required", "message": str(exc)}), 409
    except mircrew_api.MircrewInvalidSourcePage as exc:
        return jsonify({"ok": False, "error": "invalid_source_page", "message": str(exc)}), 422
    except ValueError:
        return jsonify({"ok": False, "error": "release_not_found"}), 404
