from flask import Blueprint, flash, redirect, render_template, request, url_for

from api import radarr_api
from api import sonarr_api
from app.extensions import db

bp = Blueprint("settings", __name__)


@bp.route("/settings", methods=["GET", "POST"])
def settings_view():
    services = db.get_services()
    radarr_options = {"root_folders": [], "profiles": []}
    sonarr_options = {"root_folders": [], "profiles": []}

    try:
        radarr_options["root_folders"] = radarr_api.radarr_get_root_folders(db)
        radarr_options["profiles"] = radarr_api.radarr_get_quality_profiles(db)
    except Exception as exc:
        print(f"Error loading Radarr settings options: {exc}")

    try:
        sonarr_options["root_folders"] = sonarr_api.sonarr_get_root_folders(db)
        sonarr_options["profiles"] = sonarr_api.sonarr_get_quality_profiles(db)
    except Exception as exc:
        print(f"Error loading Sonarr settings options: {exc}")

    if request.method == "POST":
        service_id = int(request.form.get("service_id"))
        action = request.form.get("action")

        service = next((s for s in services if s.id == service_id), None)
        if not service:
            flash("Servizio non trovato", "danger")
            return redirect(url_for("settings.settings_view"))

        for setting in service.settings:
            form_key = f"setting_{setting.key}"
            if form_key in request.form:
                setting.value = request.form[form_key]

        if action == "save":
            service.save_service_settings(db)
            flash(f"Impostazioni di {service.name} salvate con successo", "success")
        elif action == "test":
            flash("Test non ancora implementato", "danger")

        return redirect(url_for("settings.settings_view"))

    return render_template(
        "settings.html",
        services=services,
        radarr_options=radarr_options,
        sonarr_options=sonarr_options
    )
