import os
from flask import Flask, abort, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename

from api import plex_db_api
from api import radarr_api
from api import sonarr_api
from api import animeworld_api as aw_api
from core.db_core import MediaDB, Media
from core import dashboard_core


UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"db", "txt"}

def allowed_file(filename):
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

def save_uploaded_file(file):
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    return filepath

app = Flask(__name__)
app.secret_key = "my_media_collection_secret_key"

# --- Initialize DB ---
db = MediaDB()

# --- Utility functions ---
def get_radarr_status(title, year):
    movie = radarr_api.radarr_get_all_movies(db)
    for m in movie:
        if m.title == title and m.year == year:
            return "Present"
    return "Missing"

def get_sonarr_status(title, year):
    series = sonarr_api.sonarr_get_all_series(db)
    for s in series:
        if s.title == title and s.year == year:
            return "Present"
    return "Missing"

def get_emule_status(title):
    # Placeholder function, sostituire con logica reale per Emule
    return "Not Available"

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

# --- Routes ---
@app.route("/")
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

@app.route("/radarr")
def radarr_view():
    movies = radarr_api.radarr_get_all_movies(db)
    radarr_url = radarr_api.radarr_get_client(db)["url"]
    return render_template("radarr.html", movies=movies, radarr_url=radarr_url)

@app.route("/sonarr")
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

@app.route("/pending")
def pending_view():
    items = db.get_pending_items()
    return render_template("pending.html", items=items)

@app.route("/wanted")
def wanted_view():
    wanted_list = db.get_wanted_items(limit=None)
    return render_template("wanted.html", items=wanted_list)

@app.route("/wanted/bulk_delete", methods=["POST"])
def wanted_bulk_delete():
    media_ids = request.form.getlist("media_ids")
    if not media_ids:
        flash("Nessun elemento selezionato.", "warning")
        return redirect(url_for("wanted_view"))

    deleted = 0
    for media_id in media_ids:
        try:
            if db.delete_media_item(int(media_id)):
                deleted += 1
        except ValueError:
            continue

    flash(
        f"Eliminati {deleted} elementi dai wanted.",
        "success" if deleted else "warning"
    )
    return redirect(url_for("wanted_view"))

@app.route("/wanted/<int:media_item_id>/delete", methods=["POST"])
def wanted_delete(media_item_id):
    deleted = db.delete_media_item(media_item_id)
    if deleted:
        flash("Elemento rimosso dai wanted.", "success")
    else:
        flash("Elemento non trovato.", "warning")
    return redirect(url_for("wanted_view"))

@app.route("/api/wanted/<int:media_item_id>/lookup/tmdb")
def wanted_lookup_tmdb(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "movie":
        return json_items([])

    query = request.args.get("q") or item.title
    results = radarr_api.radarr_lookup(query, item.year, db)
    items = [
        {
            "title": r.title,
            "year": r.year,
            "external_id": r.tmdb_id,
            "imdb_id": r.imdb_id
        }
        for r in results
        if r.tmdb_id
    ]
    return json_items(items)

@app.route("/api/wanted/<int:media_item_id>/lookup/tvdb")
def wanted_lookup_tvdb(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.media_type != "series":
        return json_items([])

    lookup_title = request.args.get("q") or get_lookup_title(item)
    results = sonarr_api.sonarr_lookup(lookup_title, db)
    items = [
        {
            "title": r.title,
            "year": r.year,
            "external_id": r.tvdb_id,
            "imdb_id": r.imdb_id,
            "slug": r.slug,
            "link": f"https://thetvdb.com/series/{r.slug}" if r.slug else None
        }
        for r in results
        if r.tvdb_id
    ]
    return json_items(items)

@app.route("/api/wanted/<int:media_item_id>/lookup/anilist")
def wanted_lookup_anilist(media_item_id):
    item = db.get_media_item(media_item_id)
    if not item or item.category != "anime":
        return json_items([])

    lookup_title = request.args.get("q") or get_lookup_title(item)
    results = [aw_api.AWMedia(r) for r in aw_api.find(lookup_title)]
    items = [
        {
            "title": r.title,
            "year": r.year,
            "external_id": r.anilist_id,
            "link": r.link
        }
        for r in results
        if r.anilist_id
    ]
    return json_items(items)

@app.route("/api/wanted/<int:media_item_id>/external", methods=["POST"])
def wanted_set_external(media_item_id):
    data = request.get_json(silent=True) or {}
    source = data.get("source")
    external_id = data.get("external_id")
    link = data.get("link")
    if not source or not external_id:
        return jsonify({"ok": False, "error": "missing_parameters"}), 400

    db.add_external_id(media_item_id, source, str(external_id))
    if source == "anilist":
        db.add_external_id(media_item_id, "anilist_link", f"https://anilist.co/anime/{external_id}")
    if source == "tvdb" and link:
        db.add_external_id(media_item_id, "tvdb_link", link)

    return jsonify({"ok": True})

@app.route("/settings", methods=["GET", "POST"])
def settings_view():
    services = db.get_services()  # carica tutti i servizi come oggetti Service

    if request.method == "POST":
        service_id = int(request.form.get("service_id"))
        action = request.form.get("action")  # "save" o "test"

        # Trova il servizio corrispondente
        service = next((s for s in services if s.id == service_id), None)
        if not service:
            flash("Servizio non trovato", "danger")
            return redirect(url_for("settings_view"))

        # Aggiorna i valori delle impostazioni dal form
        for setting in service.settings:
            form_key = f"setting_{setting.key}"
            if form_key in request.form:
                setting.value = request.form[form_key]

        if action == "save":
            service.save_service_settings(db)
            flash(f"Impostazioni di {service.name} salvate con successo", "success")
        elif action == "test":
            flash(f"Test non ancora implementato", "danger")

        return redirect(url_for("settings_view"))

    return render_template("settings.html", services=services)

# --- Import routes ---
@app.route("/imports", methods=["GET"])
def imports_page():
    return render_template("imports.html")

# --- Plex import route ---
@app.route("/import/plex", methods=["GET", "POST"])
def import_plex():
    report = {"imported": [], "skipped": [], "errors": []}

    if request.method == "POST":
        file, error_response = get_uploaded_file()
        if error_response:
            return error_response

        if file and allowed_file(file.filename):
            filepath = save_uploaded_file(file)

            # Process Plex DB
            plex_items = plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.MOVIE_MEDIATYPE)
            db = MediaDB()
            for pm in plex_items:
                try:
                    # qui usiamo il tuo oggetto Media se lo hai già creato
                    item = Media(
                        title=pm.title,
                        year=pm.year,
                        media_type="movie",       # perché stiamo importando film
                        category=None,            # opzionale, puoi mettere "film" se vuoi
                        source="plex db",
                        source_ref=pm.file_path,
                        tmdb_id=None,
                        imdb_id=None
                    )
                    result = db.add_media_item(item)
                    if result:
                        report["imported"].append(pm)
                    else:
                        report["skipped"].append(pm)
                except Exception as e:
                    report["errors"].append(f"{pm.title}: {str(e)}")
            db.close()
            return render_template("import_plex.html", report=report)

    return render_template("import_plex.html", report=report)

# --- Text import route ---
@app.route("/import/text", methods=["GET", "POST"])
def import_text():
    report = {"imported": [], "skipped": [], "errors": []}

    if request.method == "POST":
        file, error_response = get_uploaded_file()
        if error_response:
            return error_response

        if file and file.filename.lower().endswith(".txt"):
            filepath = save_uploaded_file(file)

            # Leggi il file di testo
            with open(filepath, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            db = MediaDB()
            for line in lines:
                try:
                    # supponiamo che la linea sia "Titolo (Anno)"
                    if "(" in line and ")" in line:
                        title = line[:line.rfind("(")].strip()
                        year = int(line[line.rfind("(")+1:line.rfind(")")].strip())
                    else:
                        title = line
                        year = None

                    result = db.add_media_item(title, year, "movie", "text", source_ref=filepath)
                    if result:
                        report["imported"].append(title)
                    else:
                        report["skipped"].append(title)

                except Exception as e:
                    report["errors"].append(f"{line}: {str(e)}")
            db.close()
            return render_template("import_text.html", report=report)

    return render_template("import_text.html", report=report)

# lista globale dei download in corso (può essere sostituita da una tabella DB se vuoi persistenza)
animeworld_downloads = []

@app.route("/animeworld", methods=["GET", "POST"])
def animeworld_view():
    search_results = []
    query = request.args.get("q")

    if request.method == "POST":
        query = request.form.get("search_query")

    if query:
        # ricerca su AnimeWorld
        results = aw_api.find(query)
        search_results = [
            aw_api.AWMedia(r)
            for r in results
        ]
        if not search_results:
            flash(f"Nessun risultato trovato per '{query}'")

        # aggiungo info di status
        status_map = aw_api.get_animeworld_status_map(db)

        for a in search_results:
            a.status = status_map.get(str(a.source_id)) or "new"

    return render_template("animeworld.html", results=search_results, downloads=animeworld_downloads, query=query)

@app.route("/animeworld/add_wanted", methods=["POST"])
def add_wanted_anime_route():
    anime_id = request.form["anime_id"]
    anime_link = request.form["anime_link"]
    search_query = request.form.get("search_query")
    anilist_id = request.form.get("anilist_id")

    if not anime_link.startswith("https://www.animeworld"):
        abort(400)

    media = build_animeworld_media(request.form)

    media_item_id, inserted = db.add_media(media)
    db.add_external_id(media_item_id, "animeworld", str(anime_id))
    if anilist_id:
        db.add_external_id(media_item_id, "anilist", str(anilist_id))
        db.add_external_id(media_item_id, "anilist_link", f"https://anilist.co/anime/{anilist_id}")
    db.mark_as_wanted(media_item_id)

    flash(
        f"Anime {'aggiunto ai' if inserted else 'gia nei'} wanted: {media.title}",
        "success" if inserted else "info"
    )

    return redirect(url_for("animeworld_view", q=search_query)) if search_query else redirect(url_for("animeworld_view"))


# --- Run app ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
