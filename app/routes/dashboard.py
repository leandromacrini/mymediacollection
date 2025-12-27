from flask import Blueprint, render_template

from app.extensions import db
from core import dashboard_core
from api import radarr_api, sonarr_api

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    data = dashboard_core.get_dashboard_data(db)
    radarr_movies = radarr_api.radarr_get_all_movies(db)
    radarr_total = len(radarr_movies)
    radarr_monitored = sum(1 for m in radarr_movies if m.monitored)
    radarr_downloaded = sum(1 for m in radarr_movies if m.has_file)

    sonarr_series = sonarr_api.sonarr_get_all_series(db)
    sonarr_total = len(sonarr_series)
    sonarr_monitored = sum(1 for s in sonarr_series if s.monitored)
    sonarr_unmonitored = max(0, sonarr_total - sonarr_monitored)
    return render_template(
        "dashboard.html",
        counts=data["counts"],
        wanted_movies=data["wanted_movies"],
        wanted_series=data["wanted_series"],
        last_imports=data["last_imports"],
        radarr_info={
            "total": radarr_total,
            "monitored": radarr_monitored,
            "downloaded": radarr_downloaded
        },
        sonarr_info={
            "total": sonarr_total,
            "monitored": sonarr_monitored,
            "unmonitored": sonarr_unmonitored
        },
    )
