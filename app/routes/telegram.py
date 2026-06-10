from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from core import telegram_core


bp = Blueprint("telegram", __name__)


@bp.route("/telegram", methods=["GET"])
def telegram_index():
    tables_available = telegram_core.telegram_tables_available(db)
    channels = telegram_core.list_channels(db) if tables_available else []
    overview = telegram_core.telegram_overview(db) if tables_available else {}
    preview_states = telegram_core.preview_channel_states() if tables_available else {}
    q = (request.args.get("q") or "").strip()
    release_kind = (request.args.get("kind") or "").strip()
    channel_row_id = request.args.get("channel")
    open_preview = (request.args.get("open_preview") or "").strip().lower() in {"1", "true", "yes", "on"}
    selected_channel = None
    selected_channel_id = None
    selected_preview = None
    selected_preview_json = None
    if channel_row_id:
        try:
            selected_channel = telegram_core.get_channel(db, int(channel_row_id))
        except ValueError:
            selected_channel = None
        if selected_channel and selected_channel.get("channel_id"):
            selected_channel_id = selected_channel.get("channel_id")
            selected_preview = telegram_core.get_parse_preview(int(channel_row_id))
            selected_preview_json = telegram_core.preview_to_json_ready(selected_preview)
    releases = (
        telegram_core.search_releases(
            db,
            q=q,
            channel_id=selected_channel_id,
            release_kind=release_kind or None,
            limit=300,
        )
        if tables_available
        else []
    )
    return render_template(
        "telegram_index.html",
        tables_available=tables_available,
        channels=channels,
        overview=overview,
        preview_states=preview_states,
        releases=releases,
        q=q,
        selected_kind=release_kind,
        selected_channel_row_id=str(channel_row_id or ""),
        selected_channel=selected_channel,
        selected_preview=selected_preview,
        selected_preview_json=json.dumps(selected_preview_json, ensure_ascii=False) if selected_preview_json else None,
        open_preview=open_preview,
    )


@bp.route("/telegram/channels", methods=["GET"])
def telegram_channels():
    return redirect(url_for("telegram.telegram_index"))


@bp.route("/telegram/channels/add", methods=["POST"])
def telegram_add_channel():
    ok, result = telegram_core.add_channel(
        db,
        channel_username=request.form.get("channel_username") or "",
        channel_id=request.form.get("channel_id"),
        channel_title=request.form.get("channel_title"),
        refresh_interval_minutes=request.form.get("refresh_interval_minutes") or 60,
        notes=request.form.get("notes"),
        is_enabled=(request.form.get("is_enabled") or "true").strip().lower() in {"1", "true", "yes", "on"},
    )
    flash(
        f"Canale Telegram salvato: {result}" if ok else result,
        "success" if ok else "danger",
    )
    return redirect(url_for("telegram.telegram_channels"))


@bp.route("/telegram/channels/<int:row_id>/update", methods=["POST"])
def telegram_update_channel(row_id: int):
    ok, result = telegram_core.update_channel(
        db,
        row_id=row_id,
        channel_id=request.form.get("channel_id"),
        channel_title=request.form.get("channel_title"),
        refresh_interval_minutes=request.form.get("refresh_interval_minutes") or 60,
        notes=request.form.get("notes"),
        is_enabled=(request.form.get("is_enabled") or "").strip().lower() in {"1", "true", "yes", "on"},
    )
    flash(result, "success" if ok else "danger")
    return redirect(request.referrer or url_for("telegram.telegram_index"))


@bp.route("/telegram/channels/<int:row_id>", methods=["GET"])
def telegram_channel_detail(row_id: int):
    channel = telegram_core.get_channel(db, row_id)
    if not channel:
        flash("Canale Telegram non trovato.", "warning")
        return redirect(url_for("telegram.telegram_channels"))
    releases = telegram_core.list_channel_releases(db, channel.get("channel_id"), limit=300) if channel.get("channel_id") else []
    return render_template(
        "telegram_channel.html",
        channel=channel,
        releases=releases,
    )


@bp.route("/telegram/channels/<int:row_id>/parse", methods=["POST"])
def telegram_channel_parse(row_id: int):
    sync = telegram_core.sync_public_channel_messages(db, row_id, mode="incremental")
    if not sync.get("ok"):
        error = sync.get("error")
        if error == "missing_channel_id":
            flash("Il canale non ha ancora channel_id Telegram.", "warning")
        else:
            flash("Import raw Telegram non riuscito.", "danger")
        return redirect(url_for("telegram.telegram_index", channel=row_id))

    preview = telegram_core.build_parse_preview(db, row_id, mode="incremental")
    if preview.get("ok"):
        summary = preview.get("summary") or {}
        flash(
            (
                "Parse incrementale pronto: "
                f"raw +{sync.get('inserted_messages', 0)} / upd {sync.get('updated_messages', 0)} | "
                f"{summary.get('preview_total', 0)} release, "
                f"new {summary.get('new', 0)}, "
                f"updated {summary.get('updated', 0)}, "
                f"removed {summary.get('removed', 0)}."
            ),
            "success",
        )
    else:
        error = preview.get("error")
        if error == "missing_channel_id":
            flash("Il canale non ha ancora channel_id Telegram: importa prima messaggi reali.", "warning")
        else:
            flash("Parse Telegram non riuscito.", "danger")
    return redirect(url_for("telegram.telegram_index", channel=row_id, open_preview=1))


@bp.route("/telegram/channels/<int:row_id>/preview-rebuild", methods=["POST"])
def telegram_channel_preview_rebuild(row_id: int):
    sync = telegram_core.sync_public_channel_messages(db, row_id, mode="rebuild")
    if not sync.get("ok"):
        error = sync.get("error")
        if error == "missing_channel_id":
            flash("Il canale non ha ancora channel_id Telegram.", "warning")
        else:
            flash("Import raw Telegram non riuscito.", "danger")
        return redirect(url_for("telegram.telegram_index", channel=row_id))

    preview = telegram_core.build_parse_preview(db, row_id, mode="rebuild")
    if preview.get("ok"):
        summary = preview.get("summary") or {}
        flash(
            (
                "Anteprima rebuild pronta: "
                f"raw +{sync.get('inserted_messages', 0)} / upd {sync.get('updated_messages', 0)} | "
                f"{summary.get('preview_total', 0)} release, "
                f"new {summary.get('new', 0)}, "
                f"updated {summary.get('updated', 0)}, "
                f"removed {summary.get('removed', 0)}."
            ),
            "success",
        )
    else:
        error = preview.get("error")
        if error == "missing_channel_id":
            flash("Il canale non ha ancora channel_id Telegram: importa prima messaggi reali.", "warning")
        else:
            flash("Anteprima rebuild non riuscita.", "danger")
    return redirect(url_for("telegram.telegram_index", channel=row_id, open_preview=1))


@bp.route("/telegram/channels/<int:row_id>/preview-confirm", methods=["POST"])
def telegram_channel_preview_confirm(row_id: int):
    preview_payload = request.form.get("preview_payload")
    if preview_payload:
        try:
            preview = telegram_core.coerce_preview_payload(preview_payload)
            preview.setdefault("channel_row_id", row_id)
            cached = telegram_core.get_parse_preview(row_id) or {}
            preview["channel_id"] = cached.get("channel_id")
            preview["channel_username"] = cached.get("channel_username")
            preview["summary"] = cached.get("summary")
            preview["built_at"] = cached.get("built_at")
            preview["mode"] = cached.get("mode")
            preview["channel_state"] = cached.get("channel_state")
            telegram_core.set_parse_preview(row_id, preview)
        except Exception:
            flash("Payload preview non valido.", "danger")
            return redirect(url_for("telegram.telegram_index", channel=row_id))

    result = telegram_core.confirm_parse_preview(db, row_id)
    if result.get("ok"):
        flash(
            (
                "Anteprima confermata: "
                f"{result.get('releases_inserted', 0)} release scritte, "
                f"{result.get('messages_linked', 0)} messaggi collegati."
            ),
            "success",
        )
    else:
        flash("Nessuna anteprima disponibile da confermare.", "warning")
    return redirect(url_for("telegram.telegram_index", channel=row_id))


@bp.route("/telegram/channels/<int:row_id>/preview-discard", methods=["POST"])
def telegram_channel_preview_discard(row_id: int):
    removed = telegram_core.discard_parse_preview(row_id)
    flash("Anteprima scartata." if removed else "Nessuna anteprima da scartare.", "info" if removed else "warning")
    return redirect(url_for("telegram.telegram_index", channel=row_id))


@bp.route("/telegram/channels/<int:row_id>/delete", methods=["POST"])
def telegram_channel_delete(row_id: int):
    ok, result = telegram_core.delete_channel(db, row_id)
    flash(result, "success" if ok else "danger")
    return redirect(url_for("telegram.telegram_channels"))


@bp.route("/telegram/releases/<int:release_id>", methods=["GET"])
def telegram_release_detail(release_id: int):
    release = telegram_core.get_release(db, release_id)
    if not release:
        flash("Release Telegram non trovata.", "warning")
        return redirect(url_for("telegram.telegram_index"))
    messages = telegram_core.get_release_messages(db, release_id, limit=400)
    return render_template(
        "telegram_release.html",
        release=release,
        messages=messages,
    )
