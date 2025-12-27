from core import db_core

def get_dashboard_data(db: db_core.MediaDB):
    return {
        "counts": {
            "total": db.count_media(),
            "present": db.count_present(),
            "missing": db.count_missing()
        },
        "wanted_movies": db.get_wanted_items(media_type="movie",limit=None)[:5],
        "wanted_series": db.get_wanted_items(media_type="series", limit=None)[:5],
        "last_imports": db.get_last_imports(limit=None)[:5]
    }
