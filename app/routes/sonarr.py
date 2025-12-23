from flask import Blueprint, render_template

from api import sonarr_api
from app.extensions import db

bp = Blueprint("sonarr", __name__)


@bp.route("/sonarr")
def sonarr_view():
    series = sonarr_api.sonarr_get_all_series(db)
    sonarr_url = sonarr_api.sonarr_get_client(db)["url"]
    total_monitored = sum(1 for s in series if s.monitored)
    total_unmonitored = len(series) - total_monitored
    return render_template(
        "sonarr.html",
        series=series,
        total_monitored=total_monitored,
        total_unmonitored=total_unmonitored,
        sonarr_url=sonarr_url
    )
