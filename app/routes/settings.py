import os
import requests
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from api import radarr_api
from api import sonarr_api
from app.extensions import db

bp = Blueprint("settings", __name__)

def _build_settings_map(service) -> dict[str, str]:
    return {setting.key: setting.value for setting in service.settings}


def _test_radarr(cfg: dict[str, str]) -> tuple[bool, str]:
    url = (cfg.get("radarr_url") or "").rstrip("/")
    api_key = cfg.get("radarr_api_key") or ""
    if not url or not api_key:
        return False, "Radarr URL o API key mancanti."
    r = requests.get(f"{url}/api/v3/system/status", headers={"X-Api-Key": api_key}, timeout=8)
    return (r.status_code == 200, f"Radarr status: {r.status_code}")


def _test_sonarr(cfg: dict[str, str]) -> tuple[bool, str]:
    url = (cfg.get("sonarr_url") or "").rstrip("/")
    api_key = cfg.get("sonarr_api_key") or ""
    if not url or not api_key:
        return False, "Sonarr URL o API key mancanti."
    r = requests.get(f"{url}/api/v3/system/status", headers={"X-Api-Key": api_key}, timeout=8)
    return (r.status_code == 200, f"Sonarr status: {r.status_code}")


def _test_plex(cfg: dict[str, str]) -> tuple[bool, str]:
    url = (cfg.get("plex_web_url") or "").rstrip("/")
    token = cfg.get("plex_web_token") or ""
    if not url or not token:
        return False, "Plex URL o token mancanti."
    r = requests.get(f"{url}/library/sections", params={"X-Plex-Token": token}, timeout=8)
    return (r.status_code == 200, f"Plex status: {r.status_code}")


def _test_animeworld(cfg: dict[str, str]) -> tuple[bool, str]:
    url = (cfg.get("animeworld_url") or "").rstrip("/")
    if not url:
        return False, "AnimeWorld URL mancante."
    r = requests.get(url, timeout=8)
    return (r.status_code < 400, f"AnimeWorld status: {r.status_code}")


def _test_emule(cfg: dict[str, str]) -> tuple[bool, str]:
    incoming = cfg.get("emule_incoming_dir") or ""
    if not incoming:
        return False, "Cartella incoming mancante."
    if os.path.exists(incoming):
        return True, "Cartella incoming trovata."
    return False, "Cartella incoming non trovata."


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
            cfg = _build_settings_map(service)
            ok = False
            message = "Test non disponibile per questo servizio."
            if service.name == "Radarr":
                ok, message = _test_radarr(cfg)
            elif service.name == "Sonarr":
                ok, message = _test_sonarr(cfg)
            elif service.name == "Plex Web":
                ok, message = _test_plex(cfg)
            elif service.name == "Anime World":
                ok, message = _test_animeworld(cfg)
            elif service.name == "Emule":
                ok, message = _test_emule(cfg)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"ok": ok, "message": message, "category": "success" if ok else "danger"})
            flash(message, "success" if ok else "danger")

        return redirect(url_for("settings.settings_view"))

    return render_template(
        "settings.html",
        services=services,
        radarr_options=radarr_options,
        sonarr_options=sonarr_options
    )
