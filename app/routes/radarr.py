from flask import Blueprint, jsonify, render_template

from api import radarr_api
from app.extensions import db

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
