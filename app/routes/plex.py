from flask import Blueprint, jsonify, render_template

from api import plex_web_api
from app.extensions import db

bp = Blueprint("plex", __name__)


@bp.route("/plex")
def plex_view():
    items = plex_web_api.plex_get_media_items(db)
    return render_template("plex.html", items=items)


@bp.route("/api/plex/media/<rating_key>")
def plex_media_details(rating_key):
    details = plex_web_api.plex_get_media_details(rating_key, db)
    if not details:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "details": details})
