from flask import Blueprint, jsonify, render_template

from app.extensions import db
from core import dashboard_core
from api import radarr_api, sonarr_api

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    return render_template("dashboard.html")


@bp.route("/api/dashboard/data")
def dashboard_data():
    data = dashboard_core.get_dashboard_data(db)
    radarr_movies = radarr_api.radarr_get_all_movies(db)
    radarr_total = len(radarr_movies)
    radarr_monitored = sum(1 for m in radarr_movies if m.monitored)
    radarr_downloaded = sum(1 for m in radarr_movies if m.has_file)

    sonarr_series = sonarr_api.sonarr_get_series_stats(db)
    sonarr_total = len(sonarr_series)
    sonarr_monitored = sum(1 for s in sonarr_series if s.get("monitored", True))
    sonarr_downloaded = 0
    for s in sonarr_series:
        stats = s.get("statistics") or {}
        episode_count = stats.get("episodeCount")
        if episode_count is None:
            episode_count = stats.get("totalEpisodeCount")
        episode_file_count = stats.get("episodeFileCount") or 0
        if episode_count and episode_file_count >= episode_count:
            sonarr_downloaded += 1

    wanted_sources = db.count_media_by_source(["animeworld", "ddunlimited", "plex", "text"])

    def serialize_media(item):
        return {
            "title": item.title,
            "year": item.year,
            "source": item.source,
            "created_at": item.created_at.isoformat() if item.created_at else None
        }

    payload = {
        "counts": data["counts"],
        "radarr_info": {
            "total": radarr_total,
            "monitored": radarr_monitored,
            "downloaded": radarr_downloaded
        },
        "sonarr_info": {
            "total": sonarr_total,
            "monitored": sonarr_monitored,
            "downloaded": sonarr_downloaded
        },
        "wanted_sources": {
            "animeworld": wanted_sources.get("animeworld", 0),
            "ddunlimited": wanted_sources.get("ddunlimited", 0),
            "plex": wanted_sources.get("plex", 0),
            "text": wanted_sources.get("text", 0)
        },
        "last_imports": [serialize_media(item) for item in data["last_imports"]],
        "wanted_movies": [{"title": item.title, "year": item.year} for item in data["wanted_movies"]],
        "wanted_series": [{"title": item.title, "year": item.year} for item in data["wanted_series"]]
    }
    return jsonify(payload)
