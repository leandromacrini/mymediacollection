from flask import Blueprint, render_template

from app.extensions import db

bp = Blueprint("pending", __name__)


@bp.route("/pending")
def pending_view():
    items = db.get_pending_items()
    return render_template("pending.html", items=items)
