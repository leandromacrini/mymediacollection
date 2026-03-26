from flask import Blueprint, flash, redirect, render_template, request, url_for

from api import mircrew_api
from app.extensions import db
from core.db_core import Media

bp = Blueprint("mircrew", __name__)


def _wanted_mircrew_ids() -> set[str]:
    wanted_items = db.get_wanted_items(limit=None)
    return {
        str(item.external_ids.get("mircrew"))
        for item in wanted_items
        if item.external_ids.get("mircrew")
    }


def _format_size(size_bytes) -> str:
    try:
        n = int(size_bytes)
    except (TypeError, ValueError):
        return ""

    if n <= 0:
        return ""

    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(n)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024 or candidate == units[-1]:
            break
        value /= 1024

    if unit == "B":
        return f"{n:,} B"
    return f"{value:.2f} {unit}"


@bp.route("/mircrew", methods=["GET"])
def mircrew_view():
    query = (request.args.get("q") or "").strip()
    rows = mircrew_api.search(query) if query else []

    wanted_ids = _wanted_mircrew_ids() if rows else set()
    for row in rows:
        inferred = mircrew_api.build_wanted_payload(row)
        row["year"] = inferred.get("year")
        row["media_type"] = inferred.get("media_type")
        row["status"] = "wanted" if str(row.get("release_id") or "") in wanted_ids else "new"

        size_human = _format_size(row.get("size_bytes"))
        row["size_display"] = size_human or (row.get("size_text_raw") or "")
        row["size_tooltip"] = row.get("size_text_raw") or ""

    status = mircrew_api.get_status()
    if query and not rows:
        flash(f"Nessun risultato trovato per '{query}'", "warning")

    return render_template(
        "mircrew.html",
        query=query,
        results=rows,
        status=status,
    )


@bp.route("/mircrew/import_json", methods=["POST"])
def mircrew_import_json():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Seleziona un file JSON da importare.", "danger")
        return redirect(url_for("mircrew.mircrew_view"))

    if not file.filename.lower().endswith(".json"):
        flash("Formato non valido: carica un file .json", "danger")
        return redirect(url_for("mircrew.mircrew_view"))

    try:
        info = mircrew_api.save_imported_json(file)
        flash(
            f"Import MirCrew completato: {info['count']} release (cache RAM invalidata).",
            "success",
        )
    except ValueError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("mircrew.mircrew_view"))


@bp.route("/mircrew/add_wanted", methods=["POST"])
def mircrew_add_wanted():
    release_id = (request.form.get("release_id") or "").strip()
    query = (request.form.get("search_query") or "").strip()

    row = mircrew_api.get_release_by_id(release_id)
    if not row:
        flash("Release MirCrew non trovata nella cache importata.", "danger")
        return redirect(url_for("mircrew.mircrew_view", q=query) if query else url_for("mircrew.mircrew_view"))

    payload = mircrew_api.build_wanted_payload(row)
    if not payload["title"]:
        flash("Release non valida: titolo mancante.", "danger")
        return redirect(url_for("mircrew.mircrew_view", q=query) if query else url_for("mircrew.mircrew_view"))

    media = Media(
        id=None,
        title=payload["title"],
        year=payload["year"],
        media_type=payload["media_type"],
        category=payload["category"],
        source=payload["source"],
        source_ref=payload["source_ref"],
        original_title=payload["original_title"],
        language=payload["language"],
    )

    media_item_id, inserted = db.add_media(media)
    db.add_external_id(media_item_id, "mircrew", payload["release_id"])
    db.add_external_id(media_item_id, "mircrew_link", payload["release_url"])

    flash(
        f"Elemento {'aggiunto ai' if inserted else 'gia nei'} wanted: {media.title}",
        "success" if inserted else "info",
    )
    return redirect(url_for("mircrew.mircrew_view", q=query) if query else url_for("mircrew.mircrew_view"))
