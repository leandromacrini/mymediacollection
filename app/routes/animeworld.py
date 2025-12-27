from flask import Blueprint, abort, redirect, render_template, request, url_for, flash

from api import animeworld_api as aw_api
from app.extensions import db
from app.utils import build_animeworld_media

bp = Blueprint("animeworld", __name__)

@bp.route("/animeworld", methods=["GET", "POST"])
def animeworld_view():
    search_results = []
    query = request.args.get("q")

    if request.method == "POST":
        query = request.form.get("search_query")

    if query:
        wanted_items = db.get_wanted_items(limit=None)
        wanted_by_aw = {item.external_ids.get("animeworld") for item in wanted_items if item.external_ids.get("animeworld")}
        wanted_by_anilist = {item.external_ids.get("anilist") for item in wanted_items if item.external_ids.get("anilist")}
        wanted_by_mal = {item.external_ids.get("mal") for item in wanted_items if item.external_ids.get("mal")}

        def _normalize_title(value: str) -> str:
            if not value:
                return ""
            cleaned = "".join(ch for ch in value.lower() if ch.isalnum() or ch.isspace()).strip()
            return " ".join(cleaned.split())

        wanted_title_year = set()
        wanted_title_only = set()
        for item in wanted_items:
            title = _normalize_title(item.title or "")
            if title:
                wanted_title_only.add(title)
                if item.year:
                    wanted_title_year.add((title, int(item.year)))
            if item.original_title:
                orig = _normalize_title(item.original_title)
                if orig:
                    wanted_title_only.add(orig)
                    if item.year:
                        wanted_title_year.add((orig, int(item.year)))

        results = aw_api.find(query)
        search_results = [
            aw_api.AWMedia(r)
            for r in results
        ]
        if not search_results:
            flash(f"Nessun risultato trovato per '{query}'")

        for a in search_results:
            exists = str(a.source_id) in wanted_by_aw
            if not exists and a.anilist_id:
                exists = str(a.anilist_id) in wanted_by_anilist
            if not exists and a.mal_id:
                exists = str(a.mal_id) in wanted_by_mal
            if not exists:
                title_key = _normalize_title(a.title or "")
                if title_key:
                    if a.year:
                        exists = (title_key, int(a.year)) in wanted_title_year
                    else:
                        exists = title_key in wanted_title_only
            if not exists and a.original_title:
                orig_key = _normalize_title(a.original_title)
                if orig_key:
                    if a.year:
                        exists = (orig_key, int(a.year)) in wanted_title_year
                    else:
                        exists = orig_key in wanted_title_only
            a.status = "wanted" if exists else "new"

    return render_template("animeworld.html", results=search_results, query=query)


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
    flash(
        f"Anime {'aggiunto ai' if inserted else 'gia nei'} wanted: {media.title}",
        "success" if inserted else "info"
    )

    return redirect(url_for("animeworld.animeworld_view", q=search_query)) if search_query else redirect(url_for("animeworld.animeworld_view"))
