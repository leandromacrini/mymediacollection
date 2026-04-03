from flask import Blueprint, jsonify, request

from api import media_resolver_api


bp = Blueprint("media_resolver", __name__)


@bp.route("/api/media-resolver/series", methods=["GET"])
def media_resolver_series():
    tvdbid = (request.args.get("tvdbid") or "").strip()
    result = media_resolver_api.resolve_series(tvdbid)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@bp.route("/api/media-resolver/movie", methods=["GET"])
def media_resolver_movie():
    tmdbid = (request.args.get("tmdbid") or "").strip()
    imdbid = (request.args.get("imdbid") or "").strip()
    result = media_resolver_api.resolve_movie(tmdbid, imdbid)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@bp.route("/api/media-resolver/cache/stats", methods=["GET"])
def media_resolver_cache_stats():
    return jsonify(media_resolver_api.get_cache_stats())


@bp.route("/api/media-resolver/by-title", methods=["GET"])
def media_resolver_by_title():
    q = (request.args.get("q") or "").strip()
    media_type = (request.args.get("type") or "").strip()
    result = media_resolver_api.resolve_by_title(q, media_type)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@bp.route("/api/media-resolver/cache/clear", methods=["POST"])
def media_resolver_cache_clear():
    return jsonify(media_resolver_api.clear_cache())
