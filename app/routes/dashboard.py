from flask import Blueprint, render_template

from app.extensions import db
from core import dashboard_core

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    data = dashboard_core.get_dashboard_data(db)
    return render_template(
        "dashboard.html",
        counts=data["counts"],
        downloads=data["downloads"],
        wanted_movies=data["wanted_movies"],
        wanted_series=data["wanted_series"],
        last_imports=data["last_imports"],
    )
