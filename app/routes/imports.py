from flask import Blueprint, render_template

from api import plex_db_api
from app.extensions import db
from app.utils import allowed_file, get_uploaded_file, save_uploaded_file
from core.db_core import Media

bp = Blueprint("imports", __name__)


@bp.route("/imports", methods=["GET"])
def imports_page():
    return render_template("imports.html")


@bp.route("/import/plex", methods=["GET", "POST"])
def import_plex():
    report = {"imported": [], "skipped": [], "errors": []}

    from flask import request
    if request.method == "POST":
        file, error_response = get_uploaded_file()
        if error_response:
            return error_response

        if file and allowed_file(file.filename):
            filepath = save_uploaded_file(file)

            plex_items = plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.MOVIE_MEDIATYPE)
            for pm in plex_items:
                try:
                    item = Media(
                        title=pm.title,
                        year=pm.year,
                        media_type="movie",
                        category=None,
                        source="plex db",
                        source_ref=pm.file_path
                    )
                    result = db.add_media(item)
                    if result:
                        report["imported"].append(pm)
                    else:
                        report["skipped"].append(pm)
                except Exception as e:
                    report["errors"].append(f"{pm.title}: {str(e)}")

            return render_template("import_plex.html", report=report)

    return render_template("import_plex.html", report=report)


@bp.route("/import/text", methods=["GET", "POST"])
def import_text():
    report = {"imported": [], "skipped": [], "errors": []}

    from flask import request
    if request.method == "POST":
        file, error_response = get_uploaded_file()
        if error_response:
            return error_response

        if file and file.filename.lower().endswith(".txt"):
            filepath = save_uploaded_file(file)

            with open(filepath, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            for line in lines:
                try:
                    if "(" in line and ")" in line:
                        title = line[:line.rfind("(")].strip()
                        year = int(line[line.rfind("(")+1:line.rfind(")")].strip())
                    else:
                        title = line
                        year = None

                    item = Media(
                        title=title,
                        year=year,
                        media_type="movie",
                        category=None,
                        source="text",
                        source_ref=filepath
                    )
                    media_id, inserted = db.add_media(item)
                    if inserted:
                        report["imported"].append(title)
                    else:
                        report["skipped"].append(title)

                except Exception as e:
                    report["errors"].append(f"{line}: {str(e)}")

            return render_template("import_text.html", report=report)

    return render_template("import_text.html", report=report)
