from __future__ import annotations

import re
import json
import base64
import html as html_lib
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup
from psycopg2.extras import RealDictCursor

from core.db_core import MediaDB


_PREVIEW_CACHE: dict[int, dict[str, Any]] = {}


def _normalize_channel_username(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if not text.startswith("@"):
        text = f"@{text}"
    if not re.fullmatch(r"@[A-Za-z0-9_]{3,}$", text):
        return None
    return text


def _normalize_channel_id(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def _normalize_text_title(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9àèéìíîòóùúüçñ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _compact_whitespace(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", (value or "").strip())
    return text or None


def _derive_series_base_from_channel_title(channel_title: str | None) -> tuple[str | None, str | None]:
    display = _compact_whitespace(channel_title)
    if not display:
        return None, None
    cleaned = re.sub(r"\b(episodi|episode|cartoni|anime|completo|completa|channel|canale|hd|full)\b", " ", display, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bita\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[-|]+", " ", cleaned)
    cleaned = _compact_whitespace(cleaned)
    if not cleaned:
        cleaned = display
    return cleaned, _normalize_text_title(cleaned)


def _candidate_group_identity(
    channel_title: str | None,
    release_kind: str | None,
    title_guess_normalized: str | None,
    season_guess: int | None,
    episode_guess: int | None,
) -> tuple[str | None, str | None]:
    normalized_title = (title_guess_normalized or "").strip() or None
    kind = (release_kind or "").strip() or "unknown"
    if kind == "series" and season_guess is not None and episode_guess is not None:
        series_display, series_normalized = _derive_series_base_from_channel_title(channel_title)
        if series_normalized:
            return (
                f"{series_display} - Stagione {season_guess}",
                f"{series_normalized}:season:{season_guess}",
            )
    return None, normalized_title


def _guess_message_metadata_from_text(text_raw: str | None, fallback_label: str) -> dict[str, Any]:
    lines = [line.strip(" -\t\r\n") for line in (text_raw or "").splitlines()]
    lines = [line for line in lines if line]
    first_line = lines[0] if lines else fallback_label
    second_line = lines[1] if len(lines) > 1 else None
    season_guess = None
    episode_guess = None
    year_guess = None
    release_kind = "unknown"

    season_match = re.search(r"\bstagione\s*(\d+)\b|\bs(?:eason)?\s*(\d+)\b", first_line, re.IGNORECASE)
    episode_match = re.search(r"\bepisodio\s*(\d+)\b|\be(?:pisode)?\s*(\d+)\b", first_line, re.IGNORECASE)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", first_line)

    if season_match:
        season_guess = int(next(group for group in season_match.groups() if group))
        release_kind = "series"
    if episode_match:
        episode_guess = int(next(group for group in episode_match.groups() if group))
        release_kind = "series"
    if year_match:
        year_guess = int(year_match.group(1))
        if release_kind == "unknown":
            release_kind = "movie"

    if release_kind == "series" and second_line:
        title_guess = second_line
    else:
        title_guess = first_line or fallback_label

    return {
        "release_kind_guess": release_kind,
        "title_guess": title_guess or fallback_label,
        "title_guess_normalized": _normalize_text_title(title_guess or fallback_label),
        "season_guess": season_guess,
        "episode_guess": episode_guess,
        "year_guess": year_guess,
    }


def _known_channel_state_by_username(db: MediaDB, channel_username: str) -> dict[str, Any] | None:
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                channel_id,
                channel_username,
                channel_title,
                last_scanned_message_id,
                latest_known_message_id
            FROM telegram_channel_state
            WHERE channel_username = %s
            LIMIT 1
            """,
            (channel_username,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _resolve_public_channel_metadata(channel_username: str) -> dict[str, Any] | None:
    username = (channel_username or "").lstrip("@").strip()
    if not username:
        return None
    try:
        response = requests.get(f"https://t.me/s/{username}", timeout=20)
        response.raise_for_status()
    except Exception:
        return None

    html = response.text
    token_match = re.search(r'data-view="([^"]+)"', html)
    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if not token_match:
        return None

    try:
        token = token_match.group(1)
        token += "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        compact_channel_id = int(payload.get("c"))
    except Exception:
        return None

    if compact_channel_id >= 0:
        return None

    resolved_channel_id = -1000000000000 - abs(compact_channel_id)
    return {
        "channel_id": resolved_channel_id,
        "channel_title": title_match.group(1).strip() if title_match else None,
    }


def _ensure_channel_identity(db: MediaDB, row_id: int) -> dict[str, Any] | None:
    channel = get_channel(db, row_id)
    if not channel:
        return None
    if channel.get("channel_id"):
        return channel

    username = channel.get("channel_username")
    if not username:
        return channel

    known_state = _known_channel_state_by_username(db, username)
    if known_state and known_state.get("channel_id"):
        with db.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE telegram_channel
                SET channel_id = %s,
                    channel_title = COALESCE(channel_title, %s),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    int(known_state["channel_id"]),
                    (known_state.get("channel_title") or "").strip() or None,
                    row_id,
                ),
            )
        return get_channel(db, row_id)

    public_metadata = _resolve_public_channel_metadata(username)
    if not public_metadata or not public_metadata.get("channel_id"):
        return channel

    resolved_channel_id = int(public_metadata["channel_id"])
    resolved_title = (public_metadata.get("channel_title") or "").strip() or None
    with db.conn.cursor() as cur:
        cur.execute(
            """
            UPDATE telegram_channel
            SET channel_id = %s,
                channel_title = COALESCE(channel_title, %s),
                updated_at = NOW()
            WHERE id = %s
            """,
            (resolved_channel_id, resolved_title, row_id),
        )
        cur.execute(
            """
            INSERT INTO telegram_channel_state (
                channel_id,
                channel_username,
                channel_title,
                is_active,
                last_scanned_message_id,
                latest_known_message_id,
                updated_at
            )
            VALUES (%s, %s, %s, TRUE, 0, 0, NOW())
            ON CONFLICT (channel_id) DO UPDATE
            SET channel_username = EXCLUDED.channel_username,
                channel_title = COALESCE(EXCLUDED.channel_title, telegram_channel_state.channel_title),
                updated_at = NOW()
            """,
            (resolved_channel_id, username, resolved_title),
        )
    return get_channel(db, row_id)


def _scrape_public_channel_messages(channel_username: str, stop_after_message_id: int = 0, full_scan: bool = False) -> list[dict[str, Any]]:
    username = (channel_username or "").lstrip("@").strip()
    if not username:
        return []

    session = requests.Session()
    next_before: int | None = None
    seen_message_ids: set[int] = set()
    rows: list[dict[str, Any]] = []

    while True:
        url = f"https://t.me/s/{username}"
        if next_before:
            url = f"{url}?before={next_before}"
        response = session.get(url, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        message_nodes = soup.select("div.tgme_widget_message[data-post]")
        if not message_nodes:
            break

        page_ids: list[int] = []
        hit_stop_threshold = False
        for node in message_nodes:
            data_post = node.get("data-post") or ""
            try:
                message_id = int(data_post.rsplit("/", 1)[1])
            except Exception:
                continue
            if message_id in seen_message_ids:
                continue
            seen_message_ids.add(message_id)
            page_ids.append(message_id)

            if stop_after_message_id and message_id <= stop_after_message_id and not full_scan:
                hit_stop_threshold = True
                continue

            text_node = node.select_one(".tgme_widget_message_text")
            text_raw = text_node.get_text("\n", strip=True) if text_node else None
            time_node = node.select_one("time[datetime]")
            message_date = time_node.get("datetime") if time_node else None
            forward_node = node.select_one(".tgme_widget_message_forwarded_from_name")
            forward_title = forward_node.get_text(" ", strip=True) if forward_node else None
            forward_href = forward_node.get("href") if forward_node else None
            forward_username = None
            if forward_href:
                forward_username = f"@{forward_href.rstrip('/').rsplit('/', 1)[-1]}"

            has_video = node.select_one(".tgme_widget_message_video_player") is not None
            has_photo = node.select_one(".tgme_widget_message_photo_wrap") is not None
            has_document = node.select_one(".tgme_widget_message_document_wrap") is not None
            has_media = has_video or has_photo or has_document
            if has_video:
                media_kind = "video"
            elif has_photo:
                media_kind = "photo"
            elif has_document:
                media_kind = "document"
            else:
                media_kind = "text"

            grouped_id = None
            view_token = node.get("data-view")
            if view_token:
                grouped_id = view_token[:48]

            fallback_label = f"{username}-{message_id}"
            guess = _guess_message_metadata_from_text(text_raw, fallback_label)
            rows.append(
                {
                    "message_id": message_id,
                    "message_date": message_date,
                    "media_kind": media_kind,
                    "file_name": None,
                    "file_size": 0,
                    "mime_type": None,
                    "forward_chat_title": html_lib.unescape(forward_title) if forward_title else None,
                    "forward_chat_username": forward_username,
                    "text_raw": html_lib.unescape(text_raw) if text_raw else None,
                    "grouped_id": grouped_id,
                    "reply_to_message_id": None,
                    "has_media": has_media,
                    "has_text": bool(text_raw),
                    "is_video_like": has_video or has_document,
                    "source_ref": f"https://t.me/{username}/{message_id}",
                    **guess,
                }
            )

        if not page_ids:
            break

        oldest_message_id = min(page_ids)
        if stop_after_message_id and oldest_message_id <= stop_after_message_id and not full_scan:
            break
        if len(page_ids) < 20:
            break
        if next_before is not None and oldest_message_id >= next_before:
            break
        next_before = oldest_message_id
        if hit_stop_threshold and not full_scan:
            break

    rows.sort(key=lambda row: int(row["message_id"]))
    return rows


def sync_public_channel_messages(db: MediaDB, row_id: int, mode: str = "incremental") -> dict[str, Any]:
    channel = _ensure_channel_identity(db, row_id) or get_channel(db, row_id)
    if not channel:
        return {"ok": False, "error": "not_found"}
    channel_id = channel.get("channel_id")
    channel_username = channel.get("channel_username")
    if not channel_id or not channel_username:
        return {"ok": False, "error": "missing_channel_id"}

    channel_state = _get_channel_state(db, channel_id) or {}
    stop_after_message_id = 0 if mode == "rebuild" else int(channel_state.get("last_scanned_message_id") or 0)

    try:
        scraped_rows = _scrape_public_channel_messages(
            channel_username,
            stop_after_message_id=stop_after_message_id,
            full_scan=(mode == "rebuild"),
        )
    except Exception as exc:
        with db.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE telegram_channel_state
                SET scan_error = %s,
                    updated_at = NOW()
                WHERE channel_id = %s
                """,
                (str(exc), channel_id),
            )
        return {"ok": False, "error": "import_failed", "details": str(exc)}

    inserted = 0
    updated = 0
    latest_known_message_id = int(channel_state.get("latest_known_message_id") or 0)

    with db.conn.cursor() as cur:
        for row in scraped_rows:
            latest_known_message_id = max(latest_known_message_id, int(row["message_id"]))
            cur.execute(
                """
                INSERT INTO telegram_media_message (
                    channel_id,
                    message_id,
                    message_date,
                    media_kind,
                    file_name,
                    file_size,
                    mime_type,
                    forward_chat_title,
                    forward_chat_username,
                    text_raw,
                    grouped_id,
                    reply_to_message_id,
                    has_media,
                    has_text,
                    is_video_like,
                    release_kind_guess,
                    title_guess,
                    title_guess_normalized,
                    season_guess,
                    episode_guess,
                    year_guess,
                    source_ref,
                    updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (channel_id, message_id) DO UPDATE
                SET message_date = COALESCE(EXCLUDED.message_date, telegram_media_message.message_date),
                    media_kind = EXCLUDED.media_kind,
                    file_name = COALESCE(EXCLUDED.file_name, telegram_media_message.file_name),
                    file_size = COALESCE(EXCLUDED.file_size, telegram_media_message.file_size),
                    mime_type = COALESCE(EXCLUDED.mime_type, telegram_media_message.mime_type),
                    forward_chat_title = COALESCE(EXCLUDED.forward_chat_title, telegram_media_message.forward_chat_title),
                    forward_chat_username = COALESCE(EXCLUDED.forward_chat_username, telegram_media_message.forward_chat_username),
                    text_raw = COALESCE(EXCLUDED.text_raw, telegram_media_message.text_raw),
                    grouped_id = COALESCE(EXCLUDED.grouped_id, telegram_media_message.grouped_id),
                    has_media = EXCLUDED.has_media,
                    has_text = EXCLUDED.has_text,
                    is_video_like = EXCLUDED.is_video_like,
                    release_kind_guess = COALESCE(EXCLUDED.release_kind_guess, telegram_media_message.release_kind_guess),
                    title_guess = COALESCE(EXCLUDED.title_guess, telegram_media_message.title_guess),
                    title_guess_normalized = COALESCE(EXCLUDED.title_guess_normalized, telegram_media_message.title_guess_normalized),
                    season_guess = COALESCE(EXCLUDED.season_guess, telegram_media_message.season_guess),
                    episode_guess = COALESCE(EXCLUDED.episode_guess, telegram_media_message.episode_guess),
                    year_guess = COALESCE(EXCLUDED.year_guess, telegram_media_message.year_guess),
                    source_ref = COALESCE(EXCLUDED.source_ref, telegram_media_message.source_ref),
                    updated_at = NOW()
                RETURNING xmax = 0
                """,
                (
                    int(channel_id),
                    int(row["message_id"]),
                    row["message_date"],
                    row["media_kind"],
                    row["file_name"],
                    int(row["file_size"] or 0),
                    row["mime_type"],
                    row["forward_chat_title"],
                    row["forward_chat_username"],
                    row["text_raw"],
                    row["grouped_id"],
                    row["reply_to_message_id"],
                    bool(row["has_media"]),
                    bool(row["has_text"]),
                    bool(row["is_video_like"]),
                    row["release_kind_guess"],
                    row["title_guess"],
                    row["title_guess_normalized"],
                    row["season_guess"],
                    row["episode_guess"],
                    row["year_guess"],
                    row["source_ref"],
                ),
            )
            inserted_flag = cur.fetchone()[0]
            if inserted_flag:
                inserted += 1
            else:
                updated += 1

        cur.execute(
            """
            INSERT INTO telegram_channel_state (
                channel_id,
                channel_username,
                channel_title,
                is_active,
                last_scanned_message_id,
                latest_known_message_id,
                updated_at
            )
            VALUES (%s, %s, %s, TRUE, %s, %s, NOW())
            ON CONFLICT (channel_id) DO UPDATE
            SET channel_username = EXCLUDED.channel_username,
                channel_title = COALESCE(EXCLUDED.channel_title, telegram_channel_state.channel_title),
                latest_known_message_id = GREATEST(COALESCE(telegram_channel_state.latest_known_message_id, 0), EXCLUDED.latest_known_message_id),
                scan_error = NULL,
                updated_at = NOW()
            """,
            (
                int(channel_id),
                channel_username,
                channel.get("channel_title"),
                int(channel_state.get("last_scanned_message_id") or 0),
                latest_known_message_id,
            ),
        )

    return {
        "ok": True,
        "channel_row_id": row_id,
        "channel_id": int(channel_id),
        "mode": mode,
        "inserted_messages": inserted,
        "updated_messages": updated,
        "latest_known_message_id": latest_known_message_id,
    }


def telegram_tables_available(db: MediaDB) -> bool:
    with db.conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM pg_class
            WHERE relname IN (
                'telegram_channel',
                'telegram_channel_state',
                'telegram_release',
                'telegram_media_message'
            )
            """
        )
        return int(cur.fetchone()[0]) == 4


def list_channels(db: MediaDB) -> list[dict[str, Any]]:
    if not telegram_tables_available(db):
        return []
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH message_stats AS (
                SELECT
                    channel_id,
                    COUNT(*) AS message_count,
                    COUNT(*) FILTER (WHERE is_video_like = TRUE) AS video_like_count,
                    MAX(message_date) AS latest_message_date
                FROM telegram_media_message
                GROUP BY channel_id
            ),
            release_stats AS (
                SELECT
                    channel_id,
                    COUNT(*) AS release_count,
                    COUNT(*) FILTER (WHERE COALESCE(media_count, 0) > 0) AS nonempty_release_count,
                    MAX(updated_at) AS last_release_update
                FROM telegram_release
                GROUP BY channel_id
            )
            SELECT
                c.id,
                c.channel_username,
                c.channel_id,
                c.channel_title,
                c.is_enabled,
                c.refresh_interval_minutes,
                c.notes,
                c.created_at,
                c.updated_at,
                s.is_active,
                s.last_scanned_message_id,
                s.latest_known_message_id,
                s.last_scan_at,
                s.last_full_scan_at,
                s.scan_error,
                COALESCE(ms.message_count, 0) AS message_count,
                COALESCE(ms.video_like_count, 0) AS video_like_count,
                ms.latest_message_date,
                COALESCE(rs.release_count, 0) AS release_count,
                COALESCE(rs.nonempty_release_count, 0) AS nonempty_release_count,
                rs.last_release_update
            FROM telegram_channel c
            LEFT JOIN telegram_channel_state s
                ON s.channel_id = c.channel_id
            LEFT JOIN message_stats ms
                ON ms.channel_id = c.channel_id
            LEFT JOIN release_stats rs
                ON rs.channel_id = c.channel_id
            ORDER BY c.channel_username NULLS LAST, c.id ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def telegram_overview(db: MediaDB) -> dict[str, Any]:
    if not telegram_tables_available(db):
        return {
            "channel_count": 0,
            "release_count": 0,
            "video_like_count": 0,
            "latest_release_at": None,
        }
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM telegram_channel) AS channel_count,
                (SELECT COUNT(*) FROM telegram_release) AS release_count,
                (SELECT COUNT(*) FROM telegram_media_message WHERE is_video_like = TRUE) AS video_like_count,
                (SELECT MAX(published_at) FROM telegram_release) AS latest_release_at
            """
        )
        row = cur.fetchone() or {}
        return dict(row)


def preview_channel_states() -> dict[int, dict[str, Any]]:
    return {
        row_id: {
            "built_at": preview.get("built_at"),
            "summary": preview.get("summary") or {},
        }
        for row_id, preview in _PREVIEW_CACHE.items()
    }


def get_channel(db: MediaDB, row_id: int) -> dict[str, Any] | None:
    if not telegram_tables_available(db):
        return None
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH message_stats AS (
                SELECT
                    channel_id,
                    COUNT(*) AS message_count,
                    COUNT(*) FILTER (WHERE is_video_like = TRUE) AS video_like_count,
                    MAX(message_date) AS latest_message_date
                FROM telegram_media_message
                GROUP BY channel_id
            ),
            release_stats AS (
                SELECT
                    channel_id,
                    COUNT(*) AS release_count,
                    MAX(updated_at) AS last_release_update
                FROM telegram_release
                GROUP BY channel_id
            )
            SELECT
                c.id,
                c.channel_username,
                c.channel_id,
                c.channel_title,
                c.is_enabled,
                c.refresh_interval_minutes,
                c.notes,
                c.created_at,
                c.updated_at,
                s.is_active,
                s.last_scanned_message_id,
                s.latest_known_message_id,
                s.last_scan_at,
                s.last_full_scan_at,
                s.scan_error,
                COALESCE(ms.message_count, 0) AS message_count,
                COALESCE(ms.video_like_count, 0) AS video_like_count,
                ms.latest_message_date,
                COALESCE(rs.release_count, 0) AS release_count,
                rs.last_release_update
            FROM telegram_channel c
            LEFT JOIN telegram_channel_state s
                ON s.channel_id = c.channel_id
            LEFT JOIN message_stats ms
                ON ms.channel_id = c.channel_id
            LEFT JOIN release_stats rs
                ON rs.channel_id = c.channel_id
            WHERE c.id = %s
            LIMIT 1
            """,
            (row_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_channel_releases(db: MediaDB, channel_id: int, limit: int = 250) -> list[dict[str, Any]]:
    if not telegram_tables_available(db):
        return []
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                r.*,
                COUNT(m.message_id) AS linked_messages
            FROM telegram_release r
            LEFT JOIN telegram_media_message m
                ON m.release_id = r.id
            WHERE r.channel_id = %s
            GROUP BY r.id
            ORDER BY r.published_at DESC NULLS LAST, r.first_message_id DESC NULLS LAST
            LIMIT %s
            """,
            (channel_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def search_releases(
    db: MediaDB,
    q: str | None = None,
    channel_id: int | None = None,
    release_kind: str | None = None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    if not telegram_tables_available(db):
        return []

    query = (q or "").strip()
    kind = (release_kind or "").strip()
    params: list[Any] = []
    where: list[str] = []

    if channel_id:
        where.append("r.channel_id = %s")
        params.append(channel_id)

    if kind:
        where.append("COALESCE(r.release_kind, '') = %s")
        params.append(kind)

    if query:
        where.append(
            """
            (
                COALESCE(r.title_display, '') ILIKE %s OR
                COALESCE(r.title_raw, '') ILIKE %s OR
                COALESCE(r.title_normalized, '') ILIKE %s OR
                COALESCE(r.forward_title_dominant, '') ILIKE %s
            )
            """
        )
        like = f"%{query}%"
        params.extend([like, like, like, like])

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                r.*,
                c.id AS channel_row_id,
                c.channel_username,
                c.channel_title,
                COUNT(m.message_id) AS linked_messages
            FROM telegram_release r
            LEFT JOIN telegram_channel c
                ON c.channel_id = r.channel_id
            LEFT JOIN telegram_media_message m
                ON m.release_id = r.id
            {where_sql}
            GROUP BY r.id, c.id, c.channel_username, c.channel_title
            ORDER BY r.published_at DESC NULLS LAST, r.first_message_id DESC NULLS LAST
            LIMIT %s
            """,
            (*params, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def get_release(db: MediaDB, release_id: int) -> dict[str, Any] | None:
    if not telegram_tables_available(db):
        return None
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                r.*,
                c.id AS channel_row_id,
                c.channel_username,
                c.channel_title,
                COUNT(m.message_id) AS linked_messages
            FROM telegram_release r
            LEFT JOIN telegram_channel c
                ON c.channel_id = r.channel_id
            LEFT JOIN telegram_media_message m
                ON m.release_id = r.id
            WHERE r.id = %s
            GROUP BY r.id, c.id, c.channel_username, c.channel_title
            LIMIT 1
            """,
            (release_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_release_messages(db: MediaDB, release_id: int, limit: int = 300) -> list[dict[str, Any]]:
    if not telegram_tables_available(db):
        return []
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                channel_id,
                message_id,
                message_date,
                media_kind,
                file_name,
                file_size,
                mime_type,
                forward_chat_title,
                forward_chat_username,
                text_raw,
                grouped_id,
                reply_to_message_id,
                has_media,
                has_text,
                is_video_like,
                release_kind_guess,
                title_guess,
                title_guess_normalized,
                season_guess,
                episode_guess,
                year_guess,
                source_ref
            FROM telegram_media_message
            WHERE release_id = %s
            ORDER BY message_id ASC
            LIMIT %s
            """,
            (release_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def _channel_messages(db: MediaDB, channel_id: int, limit: int = 5000) -> list[dict[str, Any]]:
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                channel_id,
                message_id,
                release_id,
                message_date,
                media_kind,
                file_name,
                file_size,
                mime_type,
                forward_chat_title,
                forward_chat_username,
                text_raw,
                grouped_id,
                reply_to_message_id,
                has_media,
                has_text,
                is_video_like,
                release_kind_guess,
                title_guess,
                title_guess_normalized,
                season_guess,
                episode_guess,
                year_guess,
                source_ref
            FROM telegram_media_message
            WHERE channel_id = %s
            ORDER BY message_id ASC
            LIMIT %s
            """,
            (channel_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def _current_releases_for_channel(db: MediaDB, channel_id: int) -> list[dict[str, Any]]:
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                r.*,
                COALESCE(ARRAY_AGG(m.message_id ORDER BY m.message_id) FILTER (WHERE m.message_id IS NOT NULL), ARRAY[]::BIGINT[]) AS message_ids,
                COUNT(m.message_id) AS linked_messages
            FROM telegram_release r
            LEFT JOIN telegram_media_message m
                ON m.release_id = r.id
            WHERE r.channel_id = %s
            GROUP BY r.id
            ORDER BY r.published_at DESC NULLS LAST, r.first_message_id DESC NULLS LAST
            """,
            (channel_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def _build_release_candidates(db: MediaDB, channel_id: int) -> list[dict[str, Any]]:
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT channel_title
            FROM telegram_channel
            WHERE channel_id = %s
            LIMIT 1
            """,
            (channel_id,),
        )
        channel_row = cur.fetchone() or {}
        channel_title = channel_row.get("channel_title")

        cur.execute(
            """
            SELECT
                m.channel_id,
                COALESCE(NULLIF(m.release_kind_guess, ''), 'unknown') AS release_kind,
                m.title_guess,
                m.title_guess_normalized,
                m.forward_chat_title,
                m.year_guess,
                m.season_guess,
                m.episode_guess,
                m.message_id,
                m.message_date,
                m.file_size
            FROM telegram_media_message m
            WHERE m.channel_id = %s
              AND m.is_video_like = TRUE
              AND m.title_guess_normalized IS NOT NULL
              AND m.title_guess_normalized <> ''
            ORDER BY m.message_id ASC
            """,
            (channel_id,),
        )
        source_rows = [dict(row) for row in cur.fetchall()]

    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for row in source_rows:
        release_kind = row.get("release_kind") or "unknown"
        title_display_override, group_normalized = _candidate_group_identity(
            channel_title=channel_title,
            release_kind=release_kind,
            title_guess_normalized=row.get("title_guess_normalized"),
            season_guess=row.get("season_guess"),
            episode_guess=row.get("episode_guess"),
        )
        if not group_normalized:
            continue

        key = (int(row["channel_id"]), release_kind, group_normalized)
        bucket = grouped.get(key)
        if not bucket:
            bucket = {
                "channel_id": int(row["channel_id"]),
                "release_kind": release_kind,
                "title_guess_normalized": group_normalized,
                "title_display": title_display_override or row.get("title_guess"),
                "forward_title_dominant": row.get("forward_chat_title"),
                "year_guess": row.get("year_guess"),
                "season_guess": row.get("season_guess"),
                "first_message_id": int(row["message_id"]),
                "last_message_id": int(row["message_id"]),
                "published_at": row.get("message_date"),
                "updated_source_at": row.get("message_date"),
                "media_count": 0,
                "total_size_bytes": 0,
                "message_ids": [],
            }
            grouped[key] = bucket

        bucket["message_ids"].append(int(row["message_id"]))
        bucket["media_count"] += 1
        bucket["total_size_bytes"] += int(row.get("file_size") or 0)
        bucket["last_message_id"] = int(row["message_id"])
        if row.get("message_date") is not None:
            if bucket.get("published_at") is None or row["message_date"] < bucket["published_at"]:
                bucket["published_at"] = row["message_date"]
            if bucket.get("updated_source_at") is None or row["message_date"] > bucket["updated_source_at"]:
                bucket["updated_source_at"] = row["message_date"]
        if not bucket.get("forward_title_dominant") and row.get("forward_chat_title"):
            bucket["forward_title_dominant"] = row.get("forward_chat_title")
        if bucket.get("year_guess") is None and row.get("year_guess") is not None:
            bucket["year_guess"] = row.get("year_guess")
        if bucket.get("season_guess") is None and row.get("season_guess") is not None:
            bucket["season_guess"] = row.get("season_guess")

    rows = list(grouped.values())
    rows.sort(key=lambda row: ((row.get("published_at") is None), row.get("published_at"), row.get("first_message_id")), reverse=True)

    for row in rows:
        row["release_key"] = f"{row['channel_id']}:{row['release_kind']}:{row['title_guess_normalized']}"
        row["title_raw"] = row.get("title_display")
        row["title_normalized"] = row.get("title_guess_normalized")
        row["source_ref"] = f"telegram:{row['channel_id']}:{row['first_message_id']}"
    return rows


def _message_release_key(message: dict[str, Any]) -> str | None:
    _, group_normalized = _candidate_group_identity(
        channel_title=message.get("channel_title"),
        release_kind=message.get("release_kind_guess"),
        title_guess_normalized=message.get("title_guess_normalized"),
        season_guess=message.get("season_guess"),
        episode_guess=message.get("episode_guess"),
    )
    if not group_normalized:
        return None
    release_kind = (message.get("release_kind_guess") or "").strip() or "unknown"
    return f"{int(message['channel_id'])}:{release_kind}:{group_normalized}"


def _get_channel_state(db: MediaDB, channel_id: int) -> dict[str, Any] | None:
    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                channel_id,
                channel_username,
                channel_title,
                is_active,
                last_scanned_message_id,
                latest_known_message_id,
                last_scan_at,
                last_full_scan_at,
                scan_error
            FROM telegram_channel_state
            WHERE channel_id = %s
            LIMIT 1
            """,
            (channel_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def _build_message_assignment_map(
    preview_releases: list[dict[str, Any]],
) -> tuple[dict[int, str], dict[str, dict[str, Any]]]:
    by_message_id: dict[int, str] = {}
    by_preview_id: dict[str, dict[str, Any]] = {}
    for release in preview_releases:
        preview_id = str(release["preview_id"])
        by_preview_id[preview_id] = release
        for message_id in release.get("message_ids") or []:
            by_message_id[int(message_id)] = preview_id
    return by_message_id, by_preview_id


def _attach_context_messages(
    preview_releases: list[dict[str, Any]],
    channel_messages: list[dict[str, Any]],
) -> None:
    by_message_id, by_preview_id = _build_message_assignment_map(preview_releases)

    # First pass: attach non-video messages that clearly belong to a release by group/reply/span.
    for message in channel_messages:
        message_id = int(message["message_id"])
        if message_id in by_message_id:
            continue

        target_preview_id = None
        grouped_id = (message.get("grouped_id") or "").strip()
        reply_to_message_id = message.get("reply_to_message_id")

        if grouped_id:
            for candidate in channel_messages:
                if int(candidate["message_id"]) == message_id:
                    continue
                if (candidate.get("grouped_id") or "").strip() == grouped_id:
                    target_preview_id = by_message_id.get(int(candidate["message_id"]))
                    if target_preview_id:
                        break

        if not target_preview_id and reply_to_message_id is not None:
            target_preview_id = by_message_id.get(int(reply_to_message_id))

        if not target_preview_id:
            for release in preview_releases:
                first_message_id = release.get("first_message_id")
                last_message_id = release.get("last_message_id")
                if first_message_id is None or last_message_id is None:
                    continue
                if int(first_message_id) <= message_id <= int(last_message_id):
                    target_preview_id = str(release["preview_id"])
                    break

        if not target_preview_id:
            continue

        release = by_preview_id.get(target_preview_id)
        if not release:
            continue
        release.setdefault("message_ids", []).append(message_id)
        by_message_id[message_id] = target_preview_id

    # Normalize release message ordering and derived counters after context attachment.
    for release in preview_releases:
        ordered_ids = sorted({int(x) for x in (release.get("message_ids") or [])})
        release["message_ids"] = ordered_ids
        release["linked_messages"] = len(ordered_ids)
        release["first_message_id"] = ordered_ids[0] if ordered_ids else None
        release["last_message_id"] = ordered_ids[-1] if ordered_ids else None

    # Recompute counts from actual linked messages, keeping metadata editable.
    message_lookup = {int(row["message_id"]): row for row in channel_messages}
    for release in preview_releases:
        linked_rows = [message_lookup[mid] for mid in release.get("message_ids") or [] if mid in message_lookup]
        release["media_count"] = sum(1 for row in linked_rows if row.get("has_media"))
        release["photo_count"] = sum(1 for row in linked_rows if row.get("media_kind") == "photo")
        release["total_size_bytes"] = sum(int(row.get("file_size") or 0) for row in linked_rows)
        dated_rows = [row for row in linked_rows if row.get("message_date") is not None]
        if dated_rows:
            release["published_at"] = min(row.get("message_date") for row in dated_rows)
            release["updated_source_at"] = max(row.get("message_date") for row in dated_rows)


def _scope_status_from_messages(
    release_message_ids: list[int],
    scope_message_ids: set[int],
) -> str:
    if not scope_message_ids:
        return "all"
    return "in_scope" if any(int(message_id) in scope_message_ids for message_id in (release_message_ids or [])) else "out_of_scope"


def _coalesce_source(existing_value: Any, preview_value: Any) -> tuple[Any, str]:
    if existing_value not in (None, "", []):
        return existing_value, "db"
    return preview_value, "preview"


def _same_message_ids(a: list[Any] | None, b: list[Any] | None) -> bool:
    return [int(x) for x in (a or [])] == [int(x) for x in (b or [])]


def _match_existing_release(
    candidate: dict[str, Any],
    by_release_key: dict[str, dict[str, Any]],
    by_kind_title: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    release_key = candidate.get("release_key")
    if release_key and release_key in by_release_key:
        return by_release_key[release_key]
    fallback_key = (
        candidate.get("release_kind") or "",
        candidate.get("title_normalized") or "",
    )
    if fallback_key in by_kind_title:
        return by_kind_title[fallback_key]
    return None


def build_parse_preview(db: MediaDB, row_id: int, mode: str = "incremental") -> dict[str, Any]:
    channel = _ensure_channel_identity(db, row_id) or get_channel(db, row_id)
    if not channel:
        return {"ok": False, "error": "not_found"}
    channel_id = channel.get("channel_id")
    if not channel_id:
        return {"ok": False, "error": "missing_channel_id"}

    channel_state = _get_channel_state(db, channel_id) or {}
    existing_releases = _current_releases_for_channel(db, channel_id)
    preview_candidates = _build_release_candidates(db, channel_id)
    channel_messages = _channel_messages(db, channel_id, limit=20000)
    last_scanned_message_id = int(channel_state.get("last_scanned_message_id") or 0)
    latest_message_id = max((int(row["message_id"]) for row in channel_messages), default=0)
    scope_threshold = 0 if mode == "rebuild" else last_scanned_message_id
    scope_message_ids = {int(row["message_id"]) for row in channel_messages if int(row["message_id"]) > scope_threshold}
    by_release_key = {str(row.get("release_key")): row for row in existing_releases if row.get("release_key")}
    by_kind_title = {
        ((row.get("release_kind") or ""), (row.get("title_normalized") or "")): row
        for row in existing_releases
        if row.get("title_normalized")
    }
    matched_existing_ids: set[int] = set()
    preview_releases: list[dict[str, Any]] = []
    summary = {"new": 0, "updated": 0, "unchanged": 0, "removed": 0}

    for index, candidate in enumerate(preview_candidates, start=1):
        existing = _match_existing_release(candidate, by_release_key, by_kind_title)
        if existing and existing.get("id") is not None:
            matched_existing_ids.add(int(existing["id"]))

        title_display, title_source = _coalesce_source(existing.get("title_display") if existing else None, candidate.get("title_display"))
        year_guess, year_source = _coalesce_source(existing.get("year_guess") if existing else None, candidate.get("year_guess"))
        release_kind, release_kind_source = _coalesce_source(existing.get("release_kind") if existing else None, candidate.get("release_kind"))

        if not existing:
            status = "new"
        else:
            same_fields = (
                (existing.get("title_display") or None) == (title_display or None)
                and (existing.get("year_guess") or None) == (year_guess or None)
                and (existing.get("release_kind") or None) == (release_kind or None)
                and _same_message_ids(existing.get("message_ids"), candidate.get("message_ids"))
            )
            status = "unchanged" if same_fields else "updated"

        summary[status] += 1
        preview_releases.append(
            {
                "preview_id": f"preview-{row_id}-{index}",
                "status": status,
                "matched_db_release_id": existing.get("id") if existing else None,
                "title_display": title_display,
                "title_display_source": title_source,
                "title_raw": candidate.get("title_raw"),
                "title_normalized": candidate.get("title_normalized"),
                "release_kind": release_kind,
                "release_kind_source": release_kind_source,
                "forward_title_dominant": candidate.get("forward_title_dominant"),
                "year_guess": year_guess,
                "year_guess_source": year_source,
                "season_guess": candidate.get("season_guess"),
                "first_message_id": candidate.get("first_message_id"),
                "last_message_id": candidate.get("last_message_id"),
                "published_at": candidate.get("published_at"),
                "updated_source_at": candidate.get("updated_source_at"),
                "media_count": candidate.get("media_count") or 0,
                "linked_messages": len(candidate.get("message_ids") or []),
                "total_size_bytes": candidate.get("total_size_bytes") or 0,
                "release_key": candidate.get("release_key"),
                "source_ref": candidate.get("source_ref"),
                "notes": existing.get("notes") if existing else None,
                "message_ids": [int(x) for x in (candidate.get("message_ids") or [])],
            }
        )

    _attach_context_messages(preview_releases, channel_messages)

    summary = {"new": 0, "updated": 0, "unchanged": 0, "removed": 0}
    existing_by_id = {int(row["id"]): row for row in existing_releases if row.get("id") is not None}
    for release in preview_releases:
        existing = existing_by_id.get(int(release["matched_db_release_id"])) if release.get("matched_db_release_id") is not None else None
        if not existing:
            release["status"] = "new"
        else:
            same_fields = (
                (existing.get("title_display") or None) == (release.get("title_display") or None)
                and (existing.get("year_guess") or None) == (release.get("year_guess") or None)
                and (existing.get("release_kind") or None) == (release.get("release_kind") or None)
                and _same_message_ids(existing.get("message_ids"), release.get("message_ids"))
            )
            release["status"] = "unchanged" if same_fields else "updated"
        summary[release["status"]] += 1

    removed_releases: list[dict[str, Any]] = []
    for existing in existing_releases:
        existing_id = existing.get("id")
        if existing_id is None or int(existing_id) in matched_existing_ids:
            continue
        summary["removed"] += 1
        removed_releases.append(
            {
                "id": existing_id,
                "status": "removed",
                "title_display": existing.get("title_display"),
                "title_normalized": existing.get("title_normalized"),
                "release_kind": existing.get("release_kind"),
                "year_guess": existing.get("year_guess"),
                "season_guess": existing.get("season_guess"),
                "linked_messages": existing.get("linked_messages") or 0,
                "media_count": existing.get("media_count") or 0,
                "total_size_bytes": existing.get("total_size_bytes") or 0,
                "published_at": existing.get("published_at"),
            }
        )

    preview_release_by_message_id: dict[int, str] = {}
    current_release_ids = {int(row["id"]) for row in existing_releases if row.get("id") is not None}
    for release in preview_releases:
        for message_id in release.get("message_ids") or []:
            preview_release_by_message_id[int(message_id)] = str(release["preview_id"])

    message_rows: list[dict[str, Any]] = []
    for message in channel_messages:
        message_id = int(message["message_id"])
        current_release_id = int(message["release_id"]) if message.get("release_id") is not None else None
        preview_release_id = preview_release_by_message_id.get(message_id)
        if preview_release_id and current_release_id and current_release_id in current_release_ids:
            status = "existing"
        elif preview_release_id and current_release_id is None:
            status = "newly_assigned"
        elif preview_release_id and current_release_id is not None:
            status = "moved"
        elif current_release_id is None:
            status = "unassigned"
        else:
            status = "removed"
        message_rows.append(
            {
                "message_id": message_id,
                "current_release_id": current_release_id,
                "preview_release_id": preview_release_id,
                "status": status,
                "message_date": message.get("message_date"),
                "media_kind": message.get("media_kind"),
                "file_name": message.get("file_name"),
                "file_size": message.get("file_size"),
                "channel_id": message.get("channel_id"),
                "forward_chat_title": message.get("forward_chat_title"),
                "forward_chat_username": message.get("forward_chat_username"),
                "text_raw": message.get("text_raw"),
                "title_guess": message.get("title_guess"),
                "title_guess_normalized": message.get("title_guess_normalized"),
                "year_guess": message.get("year_guess"),
                "season_guess": message.get("season_guess"),
                "episode_guess": message.get("episode_guess"),
                "reply_to_message_id": message.get("reply_to_message_id"),
                "grouped_id": message.get("grouped_id"),
                "has_media": bool(message.get("has_media")),
                "has_text": bool(message.get("has_text")),
                "is_video_like": bool(message.get("is_video_like")),
                "scope_status": "in_scope" if message_id in scope_message_ids else "out_of_scope",
            }
        )

    for release in preview_releases:
        release["scope_status"] = _scope_status_from_messages(release.get("message_ids") or [], scope_message_ids)
        release["has_scope_changes"] = release["scope_status"] == "in_scope"

    preview = {
        "ok": True,
        "mode": mode,
        "channel_row_id": row_id,
        "channel_id": channel_id,
        "channel_username": channel.get("channel_username"),
        "built_at": datetime.now(timezone.utc),
        "channel_state": {
            "last_scanned_message_id": last_scanned_message_id,
            "latest_message_id": latest_message_id,
            "scope_mode": mode,
        },
        "summary": {
            **summary,
            "current_total": len(existing_releases),
            "preview_total": len(preview_releases),
            "in_scope_messages": len(scope_message_ids),
        },
        "preview_releases": preview_releases,
        "removed_releases": removed_releases,
        "messages": message_rows,
    }
    _PREVIEW_CACHE[row_id] = preview
    return preview


def get_parse_preview(row_id: int) -> dict[str, Any] | None:
    return _PREVIEW_CACHE.get(row_id)


def set_parse_preview(row_id: int, preview: dict[str, Any]) -> None:
    _PREVIEW_CACHE[row_id] = preview


def discard_parse_preview(row_id: int) -> bool:
    return _PREVIEW_CACHE.pop(row_id, None) is not None


def confirm_parse_preview(db: MediaDB, row_id: int) -> dict[str, Any]:
    preview = get_parse_preview(row_id)
    if not preview:
        return {"ok": False, "error": "missing_preview"}

    channel_id = preview.get("channel_id")
    releases = preview.get("preview_releases") or []
    channel_state = preview.get("channel_state") or {}
    if not channel_id:
        return {"ok": False, "error": "missing_channel_id"}

    with db.conn.cursor() as cur:
        cur.execute(
            """
            UPDATE telegram_media_message
            SET release_id = NULL,
                updated_at = NOW()
            WHERE channel_id = %s
            """,
            (channel_id,),
        )

        cur.execute(
            """
            DELETE FROM telegram_release
            WHERE channel_id = %s
            """,
            (channel_id,),
        )

        inserted = 0
        linked = 0
        for release in releases:
            cur.execute(
                """
                INSERT INTO telegram_release (
                    channel_id,
                    release_key,
                    first_message_id,
                    last_message_id,
                    title_raw,
                    title_display,
                    title_normalized,
                    forward_title_dominant,
                    release_kind,
                    year_guess,
                    season_guess,
                    media_count,
                    total_size_bytes,
                    published_at,
                    updated_source_at,
                    source_ref,
                    notes,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    channel_id,
                    release.get("release_key"),
                    release.get("first_message_id"),
                    release.get("last_message_id"),
                    release.get("title_raw"),
                    release.get("title_display"),
                    release.get("title_normalized"),
                    release.get("forward_title_dominant"),
                    release.get("release_kind"),
                    release.get("year_guess"),
                    release.get("season_guess"),
                    release.get("media_count") or 0,
                    release.get("total_size_bytes") or 0,
                    release.get("published_at"),
                    release.get("updated_source_at"),
                    release.get("source_ref"),
                    release.get("notes"),
                ),
            )
            new_release_id = cur.fetchone()[0]
            inserted += 1
            message_ids = [int(x) for x in (release.get("message_ids") or [])]
            if message_ids:
                cur.execute(
                    """
                    UPDATE telegram_media_message
                    SET release_id = %s,
                        updated_at = NOW()
                    WHERE channel_id = %s
                      AND message_id = ANY(%s)
                    """,
                    (new_release_id, channel_id, message_ids),
                )
                linked += cur.rowcount

        latest_message_id = int(channel_state.get("latest_message_id") or 0)
        if latest_message_id:
            cur.execute(
                """
                UPDATE telegram_channel_state
                SET last_scanned_message_id = GREATEST(COALESCE(last_scanned_message_id, 0), %s),
                    latest_known_message_id = GREATEST(COALESCE(latest_known_message_id, 0), %s),
                    last_scan_at = NOW(),
                    last_full_scan_at = CASE
                        WHEN %s = 'rebuild' THEN NOW()
                        ELSE last_full_scan_at
                    END,
                    scan_error = NULL,
                    updated_at = NOW()
                WHERE channel_id = %s
                """,
                (
                    latest_message_id,
                    latest_message_id,
                    preview.get("mode") or "incremental",
                    channel_id,
                ),
            )

    discard_parse_preview(row_id)
    return {
        "ok": True,
        "channel_row_id": row_id,
        "channel_id": channel_id,
        "releases_inserted": inserted,
        "messages_linked": linked,
    }


def preview_to_json_ready(preview: dict[str, Any] | None) -> dict[str, Any] | None:
    if not preview:
        return None

    def _convert(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, dict):
            return {k: _convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_convert(v) for v in value]
        return value

    return _convert(preview)


def coerce_preview_payload(raw_payload: str) -> dict[str, Any]:
    payload = json.loads(raw_payload)
    releases = []
    seen_preview_ids: set[str] = set()
    for row in payload.get("preview_releases") or []:
        preview_id = str(row.get("preview_id") or "").strip()
        if not preview_id or preview_id in seen_preview_ids:
            continue
        seen_preview_ids.add(preview_id)
        releases.append(
            {
                "preview_id": preview_id,
                "title_display": (row.get("title_display") or "").strip() or None,
                "title_raw": (row.get("title_raw") or "").strip() or None,
                "title_normalized": (row.get("title_normalized") or "").strip() or None,
                "release_kind": (row.get("release_kind") or "").strip() or None,
                "forward_title_dominant": (row.get("forward_title_dominant") or "").strip() or None,
                "year_guess": int(row["year_guess"]) if str(row.get("year_guess") or "").strip().isdigit() else None,
                "season_guess": int(row["season_guess"]) if str(row.get("season_guess") or "").strip().isdigit() else None,
                "first_message_id": int(row["first_message_id"]) if row.get("first_message_id") is not None else None,
                "last_message_id": int(row["last_message_id"]) if row.get("last_message_id") is not None else None,
                "media_count": int(row.get("media_count") or 0),
                "linked_messages": int(row.get("linked_messages") or 0),
                "total_size_bytes": int(row.get("total_size_bytes") or 0),
                "release_key": (row.get("release_key") or "").strip() or None,
                "source_ref": (row.get("source_ref") or "").strip() or None,
                "notes": (row.get("notes") or "").strip() or None,
                "message_ids": [int(x) for x in (row.get("message_ids") or [])],
                "published_at": row.get("published_at"),
                "updated_source_at": row.get("updated_source_at"),
            }
        )
    payload["preview_releases"] = releases
    return payload


def add_channel(
    db: MediaDB,
    channel_username: str,
    channel_id: int | str | None = None,
    channel_title: str | None = None,
    refresh_interval_minutes: int = 60,
    notes: str | None = None,
    is_enabled: bool = True,
) -> tuple[bool, str]:
    username = _normalize_channel_username(channel_username)
    if not username:
        return False, "Username canale non valido."
    normalized_channel_id = _normalize_channel_id(channel_id)
    known_state = _known_channel_state_by_username(db, username)
    if normalized_channel_id is None and known_state:
        normalized_channel_id = known_state.get("channel_id")
    if normalized_channel_id is None:
        public_metadata = _resolve_public_channel_metadata(username)
        if public_metadata:
            normalized_channel_id = public_metadata.get("channel_id")
            if not channel_title:
                channel_title = public_metadata.get("channel_title")
    effective_title = (channel_title or "").strip() or None
    if not effective_title and known_state:
        effective_title = (known_state.get("channel_title") or "").strip() or None
    refresh = max(1, int(refresh_interval_minutes or 60))
    with db.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telegram_channel (
                channel_username,
                channel_id,
                channel_title,
                is_enabled,
                refresh_interval_minutes,
                notes,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (channel_username) DO UPDATE
            SET channel_id = COALESCE(EXCLUDED.channel_id, telegram_channel.channel_id),
                channel_title = COALESCE(EXCLUDED.channel_title, telegram_channel.channel_title),
                is_enabled = EXCLUDED.is_enabled,
                refresh_interval_minutes = EXCLUDED.refresh_interval_minutes,
                notes = EXCLUDED.notes,
                updated_at = EXCLUDED.updated_at
            """,
            (
                username,
                normalized_channel_id,
                effective_title,
                bool(is_enabled),
                refresh,
                (notes or "").strip() or None,
            ),
        )
    if normalized_channel_id is not None:
        with db.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO telegram_channel_state (
                    channel_id,
                    channel_username,
                    channel_title,
                    is_active,
                    last_scanned_message_id,
                    latest_known_message_id,
                    updated_at
                )
                VALUES (%s, %s, %s, TRUE, 0, 0, NOW())
                ON CONFLICT (channel_id) DO UPDATE
                SET channel_username = EXCLUDED.channel_username,
                    channel_title = COALESCE(EXCLUDED.channel_title, telegram_channel_state.channel_title),
                    updated_at = NOW()
                """,
                (int(normalized_channel_id), username, effective_title),
            )
        return True, f"{username} (channel_id {normalized_channel_id})"
    return True, f"{username} (channel_id non ancora risolto)"


def update_channel(
    db: MediaDB,
    row_id: int,
    channel_id: int | str | None = None,
    channel_title: str | None = None,
    refresh_interval_minutes: int = 60,
    notes: str | None = None,
    is_enabled: bool = True,
) -> tuple[bool, str]:
    if not telegram_tables_available(db):
        return False, "Tabelle Telegram non disponibili."

    refresh = max(1, int(refresh_interval_minutes or 60))
    normalized_channel_id = _normalize_channel_id(channel_id)
    if normalized_channel_id is None:
        with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT channel_username FROM telegram_channel WHERE id = %s LIMIT 1", (row_id,))
            row = cur.fetchone()
            username = row.get("channel_username") if row else None
        if username:
            public_metadata = _resolve_public_channel_metadata(username)
            if public_metadata:
                normalized_channel_id = public_metadata.get("channel_id")
                if not channel_title:
                    channel_title = public_metadata.get("channel_title")
    with db.conn.cursor() as cur:
        cur.execute(
            """
            UPDATE telegram_channel
            SET channel_id = COALESCE(%s, channel_id),
                channel_title = %s,
                is_enabled = %s,
                refresh_interval_minutes = %s,
                notes = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                normalized_channel_id,
                (channel_title or "").strip() or None,
                bool(is_enabled),
                refresh,
                (notes or "").strip() or None,
                row_id,
            ),
        )
        if cur.rowcount <= 0:
            return False, "Canale Telegram non trovato."
        if normalized_channel_id is not None:
            cur.execute(
                """
                INSERT INTO telegram_channel_state (
                    channel_id,
                    channel_username,
                    channel_title,
                    is_active,
                    last_scanned_message_id,
                    latest_known_message_id,
                    updated_at
                )
                SELECT channel_id, channel_username, channel_title, TRUE, 0, 0, NOW()
                FROM telegram_channel
                WHERE id = %s
                ON CONFLICT (channel_id) DO UPDATE
                SET channel_username = EXCLUDED.channel_username,
                    channel_title = COALESCE(EXCLUDED.channel_title, telegram_channel_state.channel_title),
                    updated_at = NOW()
                """,
                (row_id,),
            )
    return True, "Canale aggiornato."


def delete_channel(db: MediaDB, row_id: int) -> tuple[bool, str]:
    channel = get_channel(db, row_id)
    if not channel:
        return False, "Canale Telegram non trovato."

    channel_id = channel.get("channel_id")
    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM telegram_channel WHERE id = %s", (row_id,))
        if cur.rowcount <= 0:
            return False, "Canale Telegram non trovato."

    discard_parse_preview(row_id)
    return True, f"Canale rimosso: {channel.get('channel_username') or row_id}"


def parse_channel_candidates(db: MediaDB, row_id: int) -> dict[str, Any]:
    channel = _ensure_channel_identity(db, row_id) or get_channel(db, row_id)
    if not channel:
        return {"ok": False, "error": "not_found"}
    channel_id = channel.get("channel_id")
    if not channel_id:
        return {"ok": False, "error": "missing_channel_id"}

    with db.conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE telegram_media_message
            SET release_id = NULL,
                updated_at = NOW()
            WHERE channel_id = %s
            """,
            (channel_id,),
        )
        unlinked = cur.rowcount

        cur.execute(
            """
            DELETE FROM telegram_release
            WHERE channel_id = %s
            """,
            (channel_id,),
        )
        deleted_releases = cur.rowcount

        cur.execute(
            """
            WITH grouped AS (
                SELECT
                    m.channel_id,
                    COALESCE(NULLIF(m.release_kind_guess, ''), 'unknown') AS release_kind,
                    m.title_guess_normalized,
                    MIN(m.title_guess) FILTER (WHERE m.title_guess IS NOT NULL AND m.title_guess <> '') AS title_display,
                    MIN(m.forward_chat_title) FILTER (WHERE m.forward_chat_title IS NOT NULL AND m.forward_chat_title <> '') AS forward_title_dominant,
                    MIN(m.year_guess) FILTER (WHERE m.year_guess IS NOT NULL) AS year_guess,
                    MIN(m.season_guess) FILTER (WHERE m.season_guess IS NOT NULL) AS season_guess,
                    MIN(m.message_id) AS first_message_id,
                    MAX(m.message_id) AS last_message_id,
                    MIN(m.message_date) AS published_at,
                    MAX(m.message_date) AS updated_source_at,
                    COUNT(*) AS media_count,
                    COALESCE(SUM(m.file_size), 0) AS total_size_bytes
                FROM telegram_media_message m
                WHERE m.channel_id = %s
                  AND m.is_video_like = TRUE
                  AND m.title_guess_normalized IS NOT NULL
                  AND m.title_guess_normalized <> ''
                GROUP BY
                    m.channel_id,
                    COALESCE(NULLIF(m.release_kind_guess, ''), 'unknown'),
                    m.title_guess_normalized
            ),
            inserted AS (
                INSERT INTO telegram_release (
                    channel_id,
                    release_key,
                    first_message_id,
                    last_message_id,
                    title_raw,
                    title_display,
                    title_normalized,
                    forward_title_dominant,
                    release_kind,
                    year_guess,
                    season_guess,
                    media_count,
                    total_size_bytes,
                    published_at,
                    updated_source_at,
                    source_ref,
                    updated_at
                )
                SELECT
                    g.channel_id,
                    CONCAT(g.channel_id, ':', g.release_kind, ':', g.title_guess_normalized) AS release_key,
                    g.first_message_id,
                    g.last_message_id,
                    g.title_display,
                    g.title_display,
                    g.title_guess_normalized,
                    g.forward_title_dominant,
                    g.release_kind,
                    g.year_guess,
                    g.season_guess,
                    g.media_count,
                    g.total_size_bytes,
                    g.published_at,
                    g.updated_source_at,
                    CONCAT('telegram:', g.channel_id, ':', g.first_message_id),
                    NOW()
                FROM grouped g
                RETURNING id
            )
            SELECT COUNT(*) AS release_count
            FROM inserted
            """,
            (channel_id,),
        )
        release_count = int((cur.fetchone() or {}).get("release_count") or 0)

        cur.execute(
            """
            WITH release_match AS (
                SELECT
                    m.channel_id,
                    m.message_id,
                    r.id AS release_id
                FROM telegram_media_message m
                JOIN telegram_release r
                  ON r.release_key = CONCAT(
                        m.channel_id, ':',
                        COALESCE(NULLIF(m.release_kind_guess, ''), 'unknown'), ':',
                        m.title_guess_normalized
                  )
                WHERE m.channel_id = %s
                  AND m.is_video_like = TRUE
                  AND m.title_guess_normalized IS NOT NULL
                  AND m.title_guess_normalized <> ''
            )
            UPDATE telegram_media_message AS m
            SET release_id = rm.release_id,
                updated_at = NOW()
            FROM release_match rm
            WHERE m.channel_id = rm.channel_id
              AND m.message_id = rm.message_id
              AND (m.release_id IS DISTINCT FROM rm.release_id)
            """,
            (channel_id,),
        )
        linked_messages = cur.rowcount

    return {
        "ok": True,
        "channel_row_id": row_id,
        "channel_id": channel_id,
        "deleted_releases": deleted_releases,
        "unlinked_messages": unlinked,
        "releases_upserted": release_count,
        "media_linked": linked_messages,
    }
