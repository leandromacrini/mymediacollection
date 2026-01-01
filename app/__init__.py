import os
from flask import Flask

from app.extensions import db
from app.routes import animeworld, dashboard, ddunlimited, imports, plex, radarr, settings, sonarr, wanted


def create_app() -> Flask:
    base_dir = os.path.dirname(__file__)
    template_dir = os.path.abspath(os.path.join(base_dir, "..", "templates"))
    static_dir = os.path.abspath(os.path.join(base_dir, "..", "static"))
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = os.environ.get("MMC_SECRET_KEY", "my_media_collection_secret_key")

    app.register_blueprint(dashboard.bp)
    app.register_blueprint(radarr.bp)
    app.register_blueprint(sonarr.bp)
    app.register_blueprint(wanted.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(imports.bp)
    app.register_blueprint(animeworld.bp)
    app.register_blueprint(ddunlimited.bp)
    app.register_blueprint(plex.bp)

    return app
