from flask import Blueprint, abort, redirect, render_template, request, url_for, flash

from api import animeworld_api as aw_api
from app.extensions import db
from app.utils import build_animeworld_media

bp = Blueprint("animeworld", __name__)

animeworld_downloads = []


@bp.route("/animeworld", methods=["GET", "POST"])
def animeworld_view():
    search_results = []
    query = request.args.get("q")

    if request.method == "POST":
        query = request.form.get("search_query")

    if query:
        results = aw_api.find(query)
        search_results = [
            aw_api.AWMedia(r)
            for r in results
        ]
        if not search_results:
            flash(f"Nessun risultato trovato per '{query}'")

        status_map = aw_api.get_animeworld_status_map(db)

        for a in search_results:
            a.status = status_map.get(str(a.source_id)) or "new"

    return render_template("animeworld.html", results=search_results, downloads=animeworld_downloads, query=query)


@bp.route("/animeworld/add_wanted", methods=["POST"])
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

    return redirect(url_for("animeworld.animeworld_view", q=search_query)) if search_query else redirect(url_for("animeworld.animeworld_view"))
