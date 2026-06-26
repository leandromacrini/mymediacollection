import os
import logging
from flask import Flask

from app.extensions import db
from app.routes import animeworld, dashboard, ddunlimited, imports, media_resolver, mircrew, plex, radarr, settings, sonarr, telegram, wanted


def _configure_logging(app: Flask) -> None:
    level_name = (os.environ.get("MMC_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    gunicorn_logger = logging.getLogger("gunicorn.error")
    root_logger = logging.getLogger()

    if gunicorn_logger.handlers:
        root_logger.handlers = list(gunicorn_logger.handlers)
    elif not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        )

    root_logger.setLevel(level)
    app.logger.handlers = root_logger.handlers
    app.logger.setLevel(level)
    app.logger.propagate = False


def create_app() -> Flask:
    base_dir = os.path.dirname(__file__)
    template_dir = os.path.abspath(os.path.join(base_dir, "..", "templates"))
    static_dir = os.path.abspath(os.path.join(base_dir, "..", "static"))
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = os.environ.get("MMC_SECRET_KEY", "my_media_collection_secret_key")
    app.json.ensure_ascii = False
    _configure_logging(app)

    app.register_blueprint(dashboard.bp)
    app.register_blueprint(radarr.bp)
    app.register_blueprint(sonarr.bp)
    app.register_blueprint(wanted.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(imports.bp)
    app.register_blueprint(animeworld.bp)
    app.register_blueprint(ddunlimited.bp)
    app.register_blueprint(media_resolver.bp)
    app.register_blueprint(mircrew.bp)
    app.register_blueprint(plex.bp)
    app.register_blueprint(telegram.bp)

    return app
