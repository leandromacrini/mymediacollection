from difflib import SequenceMatcher
import threading
import time
import uuid

from flask import Blueprint, render_template

from api import radarr_api
from api import plex_db_api
from app.extensions import db
from app.utils import allowed_file, get_uploaded_file, save_uploaded_file
from core.db_core import Media

bp = Blueprint("imports", __name__)
_plex_jobs = {}
_plex_jobs_lock = threading.Lock()


def _normalize_title(title: str) -> str:
    return "".join(ch.lower() for ch in title if ch.isalnum() or ch.isspace()).strip()


def _tmdb_score(query: str, candidate: str) -> float:
    return SequenceMatcher(None, _normalize_title(query), _normalize_title(candidate)).ratio()


def _radarr_find_best(title: str, year: int | None) -> dict | None:
    results = radarr_api.radarr_lookup(title, year, db)
    if not results and year:
        results = radarr_api.radarr_lookup(title, None, db)
    if not results:
        return None

    best = None
    best_score = 0.0
    for item in results:
        candidate_title = item.title or ""
        score = _tmdb_score(title, candidate_title)
        if score > best_score:
            best_score = score
            best = item

    if not best:
        return None

    year_ok = not year or (best.year and abs(best.year - year) <= 1)
    confident = best_score >= 0.9 and year_ok
    return {
        "tmdb_id": best.tmdb_id,
        "tmdb_title": best.title,
        "tmdb_year": best.year,
        "tmdb_score": round(best_score, 3),
        "tmdb_confident": confident
    }


def _wanted_key(title: str, year: int | None) -> tuple[str, int | None]:
    return ((title or "").strip().lower(), year)


def _get_wanted_keys() -> set[tuple[str, int | None]]:
    wanted = db.get_wanted_items(limit=1000000)
    return {_wanted_key(item.title, item.year) for item in wanted if item.title}


def _build_preview(filepath: str) -> dict:
    wanted_keys = _get_wanted_keys()
    movies = []
    excluded = []
    for pm in plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.MOVIE_MEDIATYPE):
        if _wanted_key(pm.title, pm.year) in wanted_keys:
            excluded.append({
                "title": pm.title,
                "year": pm.year,
                "media_type": "movie",
                "reason": "Gia in wanted"
            })
            continue
        match = _radarr_find_best(pm.title, pm.year)
        movies.append({
            "guid": pm.guid,
            "title": pm.title,
            "year": pm.year,
            "file_path": pm.file_path,
            "tmdb_id": match.get("tmdb_id") if match else None,
            "tmdb_title": match.get("tmdb_title") if match else None,
            "tmdb_year": match.get("tmdb_year") if match else None,
            "tmdb_score": match.get("tmdb_score") if match else None,
            "tmdb_confident": match.get("tmdb_confident") if match else False
        })
    series = []
    for pm in plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.SERIES_MEDIATYPE):
        if _wanted_key(pm.title, pm.year) in wanted_keys:
            excluded.append({
                "title": pm.title,
                "year": pm.year,
                "media_type": "series",
                "reason": "Gia in wanted"
            })
            continue
        series.append({
            "guid": pm.guid,
            "title": pm.title,
            "year": pm.year,
            "file_path": pm.file_path
        })
    return {"filepath": filepath, "movies": movies, "series": series, "excluded": excluded}


def _start_preview_job(filepath: str) -> str:
    job_id = uuid.uuid4().hex
    with _plex_jobs_lock:
        _plex_jobs[job_id] = {
            "status": "running",
            "stage": "Caricamento elenco film",
            "processed": 0,
            "total": 0,
            "result": None,
            "error": None,
            "updated_at": time.time()
        }

    def _run_job():
        try:
            with _plex_jobs_lock:
                _plex_jobs[job_id]["stage"] = "Lettura film Plex"
                _plex_jobs[job_id]["updated_at"] = time.time()
            movies_raw = plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.MOVIE_MEDIATYPE)
            wanted_keys = _get_wanted_keys()
            with _plex_jobs_lock:
                _plex_jobs[job_id]["stage"] = "Match TMDB tramite Radarr"
                _plex_jobs[job_id]["total"] = len(movies_raw)
                _plex_jobs[job_id]["processed"] = 0
                _plex_jobs[job_id]["updated_at"] = time.time()
            movies = []
            excluded = []
            for pm in movies_raw:
                if _wanted_key(pm.title, pm.year) in wanted_keys:
                    excluded.append({
                        "title": pm.title,
                        "year": pm.year,
                        "media_type": "movie",
                        "reason": "Gia in wanted"
                    })
                    with _plex_jobs_lock:
                        _plex_jobs[job_id]["processed"] += 1
                        _plex_jobs[job_id]["updated_at"] = time.time()
                    continue
                match = _radarr_find_best(pm.title, pm.year)
                movies.append({
                    "guid": pm.guid,
                    "title": pm.title,
                    "year": pm.year,
                    "file_path": pm.file_path,
                    "tmdb_id": match.get("tmdb_id") if match else None,
                    "tmdb_title": match.get("tmdb_title") if match else None,
                    "tmdb_year": match.get("tmdb_year") if match else None,
                    "tmdb_score": match.get("tmdb_score") if match else None,
                    "tmdb_confident": match.get("tmdb_confident") if match else False
                })
                with _plex_jobs_lock:
                    _plex_jobs[job_id]["processed"] += 1
                    _plex_jobs[job_id]["updated_at"] = time.time()
            with _plex_jobs_lock:
                _plex_jobs[job_id]["stage"] = "Lettura serie Plex"
                _plex_jobs[job_id]["updated_at"] = time.time()
            series = []
            for pm in plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.SERIES_MEDIATYPE):
                if _wanted_key(pm.title, pm.year) in wanted_keys:
                    excluded.append({
                        "title": pm.title,
                        "year": pm.year,
                        "media_type": "series",
                        "reason": "Gia in wanted"
                    })
                    continue
                series.append({
                    "guid": pm.guid,
                    "title": pm.title,
                    "year": pm.year,
                    "file_path": pm.file_path
                })
            with _plex_jobs_lock:
                _plex_jobs[job_id]["status"] = "done"
                _plex_jobs[job_id]["stage"] = "Completato"
                _plex_jobs[job_id]["result"] = {"filepath": filepath, "movies": movies, "series": series, "excluded": excluded}
                _plex_jobs[job_id]["updated_at"] = time.time()
        except Exception as exc:
            with _plex_jobs_lock:
                _plex_jobs[job_id]["status"] = "error"
                _plex_jobs[job_id]["error"] = str(exc)
                _plex_jobs[job_id]["updated_at"] = time.time()

    threading.Thread(target=_run_job, daemon=True).start()
    return job_id

@bp.route("/imports", methods=["GET"])
def imports_page():
    return render_template("imports.html")


@bp.route("/import/plex", methods=["GET", "POST"])
def import_plex():
    report = {"imported": [], "skipped": [], "errors": []}
    preview = None
    selected = set()

    from flask import request
    job_id = request.args.get("job_id")
    if request.method == "GET" and job_id:
        with _plex_jobs_lock:
            job = _plex_jobs.get(job_id)
        if job and job.get("status") == "done":
            preview = job.get("result")
    if request.method == "POST":
        action = request.form.get("action") or "preview"
        if action == "preview":
            file, error_response = get_uploaded_file()
            if error_response:
                return error_response

            if file and allowed_file(file.filename):
                filepath = save_uploaded_file(file)
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    job_id = _start_preview_job(filepath)
                    from flask import jsonify
                    return jsonify({"ok": True, "job_id": job_id})
                preview = _build_preview(filepath)
        elif action == "import":
            filepath = request.form.get("filepath")
            selected = set(request.form.getlist("plex_guid"))
            tmdb_map = {}
            for item in request.form.getlist("tmdb_match"):
                parts = item.split("|")
                if len(parts) >= 3:
                    guid, tmdb_id, confident = parts[0], parts[1], parts[2]
                    if tmdb_id and confident == "1":
                        tmdb_map[guid] = tmdb_id
            if not filepath:
                report["errors"].append("Percorso file Plex non valido.")
            elif not selected:
                report["errors"].append("Nessun elemento selezionato per l'import.")
            else:
                all_items = {}
                for pm in plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.MOVIE_MEDIATYPE):
                    all_items[pm.guid] = ("movie", pm)
                for pm in plex_db_api.plex_get_media_by_mediatype(filepath, plex_db_api.SERIES_MEDIATYPE):
                    all_items[pm.guid] = ("series", pm)

                for guid in selected:
                    media_type, pm = all_items.get(guid, (None, None))
                    if not pm:
                        report["skipped"].append(guid)
                        continue
                    try:
                        item = Media(
                            id=None,
                            title=pm.title,
                            year=pm.year,
                            media_type=media_type,
                            category=None,
                            source="plex db",
                            source_ref=pm.file_path
                        )
                        media_id, inserted = db.add_media(item)
                        if inserted:
                            if media_type == "movie":
                                tmdb_id = tmdb_map.get(guid)
                                if not tmdb_id:
                                    match = _radarr_find_best(pm.title, pm.year)
                                    if match and match.get("tmdb_confident"):
                                        tmdb_id = match.get("tmdb_id")
                                if tmdb_id:
                                    db.add_external_id(media_id, "tmdb", str(tmdb_id))
                            report["imported"].append(pm)
                        else:
                            report["skipped"].append(pm)
                    except Exception as e:
                        report["errors"].append(f"{pm.title}: {str(e)}")

    return render_template("import_plex.html", report=report, preview=preview, selected=selected)


@bp.route("/import/plex/status")
def import_plex_status():
    from flask import jsonify, request
    job_id = request.args.get("job_id")
    if not job_id:
        return jsonify({"ok": False, "error": "missing_job_id"}), 400
    with _plex_jobs_lock:
        job = _plex_jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({
        "ok": True,
        "status": job.get("status"),
        "stage": job.get("stage"),
        "processed": job.get("processed"),
        "total": job.get("total"),
        "error": job.get("error")
    })


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
