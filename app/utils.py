import os
from flask import flash, jsonify, redirect, request
from werkzeug.utils import secure_filename

from core.db_core import Media

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"db", "txt"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_lookup_title(item: Media) -> str:
    return item.original_title or item.title


def json_items(items):
    return jsonify({"items": items})


def get_uploaded_file():
    if "file" not in request.files:
        flash("No file part")
        return None, redirect(request.url)
    file = request.files["file"]
    if file.filename == "":
        flash("No selected file")
        return None, redirect(request.url)
    return file, None


def save_uploaded_file(file) -> str:
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    return filepath


def build_animeworld_media(form) -> Media:
    original_title = form.get("original_title")
    language = form.get("language")
    return Media(
        id=None,
        title=form["title"],
        year=int(form["year"]),
        media_type="series" if int(form["episodes"]) > 1 else "movie",
        category="anime",
        source="animeworld",
        source_ref=form["anime_link"],
        original_title=original_title if original_title else None,
        language=language if language else None
    )


def build_ddunlimited_media(form) -> Media:
    original_title = form.get("original_title")
    language = form.get("language")
    year_raw = form.get("year")
    try:
        year = int(year_raw) if year_raw else None
    except ValueError:
        year = None
    return Media(
        id=None,
        title=form["title"],
        year=year,
        media_type=form.get("media_type") or "movie",
        category=form.get("category"),
        source="ddunlimited",
        source_ref=form.get("detail_url"),
        original_title=original_title if original_title else None,
        language=language if language else None
    )
