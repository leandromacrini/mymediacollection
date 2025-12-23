import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Media:
    id: Optional[int]
    title: str
    year: Optional[int]
    media_type: str           # movie | series
    category: Optional[str]   # anime | film | tv
    source: str               # animeworld | plex | manual
    source_ref: Optional[str] = None
    original_title: Optional[str] = None
    language: Optional[str] = None

    external_ids: dict[str, str] = field(default_factory=dict)
    status: Optional[str] = None


@dataclass
class MediaStatus:
    id: Optional[int]
    media_item_id: int
    source: str
    external_id: str
    status: str

class ServiceSetting:
    def __init__(self, id: int, service_id: int, key: str, label: str, value: str | None, value_type: str = "string", required: bool = False):
        self.id = id
        self.service_id = service_id
        self.key = key
        self.label = label
        self.value = value
        self.value_type = value_type
        self.required = required

    def update_value(self, db: 'MediaDB', new_value):
        db.set_service_setting(self.id, new_value)
        self.value = new_value

class Service:
    def __init__(self, id: int,  name: str, description: str, enabled: bool, settings: list[ServiceSetting] = []):
        self.id = id
        self.name = name
        self.description = description
        self.enabled = enabled
        self.settings = settings
    
    def load_service_settings(self, db: 'MediaDB'):
            """
            Carica le impostazioni di questo servizio dal DB e popola self.settings
            """
            rows = db.get_service_settings(self.name)
            self.settings = [
                ServiceSetting(
                    id=row["id"],
                    service_id=row["service_id"],
                    key=row["key"],
                    label=row["label"],
                    value=row["value"],
                    value_type=row["value_type"],
                    required=row["required"]
                )
                for row in rows
            ]
    
    def save_service_settings(self, db: 'MediaDB'):
            """
            Salva le impostazioni correnti di questo servizio nel DB
            """
            db.set_service_settings(self.settings)

# ===== CONFIG =====
DB_HOST = os.environ.get("MMC_DB_HOST")
DB_PORT = int(os.environ.get("MMC_DB_PORT", "5432"))
DB_NAME = os.environ.get("MMC_DB_NAME")
DB_USER = os.environ.get("MMC_DB_USER")
DB_PASSWORD = os.environ.get("MMC_DB_PASSWORD")
# ==================

class MediaDB:
    """Core class to interact with PostgreSQL database for media management."""

    def __init__(self):
        missing = [
            name for name, value in {
                "MMC_DB_HOST": DB_HOST,
                "MMC_DB_NAME": DB_NAME,
                "MMC_DB_USER": DB_USER,
                "MMC_DB_PASSWORD": DB_PASSWORD
            }.items()
            if not value
        ]
        if missing:
            missing_list = ", ".join(missing)
            raise RuntimeError(f"Missing DB settings: {missing_list}")
        self.conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        self.conn.autocommit = True

    def close(self):
        """Close the database connection."""
        self.conn.close()

    def add_media(self, media: Media) -> tuple[int, bool]:
        """
        Inserisce un media se non esiste.
        Ritorna (media_id, inserted)
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO media_items (title, year, media_type, category, source, source_ref, original_title, language)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (title, year) DO NOTHING
                RETURNING id
            """, (
                media.title,
                media.year,
                media.media_type,
                media.category,
                media.source,
                media.source_ref,
                media.original_title,
                media.language
            ))

            row = cur.fetchone()
            if row:
                media_id = row[0]
                inserted = True
            else:
                cur.execute("""
                    SELECT id FROM media_items
                    WHERE title=%s AND year=%s
                """, (media.title, media.year))
                media_id = cur.fetchone()[0]
                inserted = False

        return media_id, inserted

    def add_external_id(self, media_item_id: int, source: str, external_id: str):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO external_ids (media_item_id, source, external_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (source, external_id) DO NOTHING
            """, (media_item_id, source, external_id))

    def mark_as_wanted(self, media_item_id: int):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO processing_state (media_item_id, status)
                VALUES (%s, 'pending')
                ON CONFLICT (media_item_id)
                DO UPDATE SET status='pending', updated_at=now()
            """, (media_item_id,))

    def delete_media_item(self, media_item_id: int) -> bool:
        with self.conn.cursor() as cur:
            cur.execute("""
                DELETE FROM media_items
                WHERE id = %s
            """, (media_item_id,))
            return cur.rowcount > 0

    def get_pending_items(self):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT mi.*, ps.status, ps.last_step, ps.message
                FROM media_items mi
                LEFT JOIN processing_state ps ON ps.media_item_id = mi.id
                WHERE ps.status='pending' OR ps.status IS NULL
            """)
            return cur.fetchall()
    
    def get_wanted_items(self, media_type:str | None = None, limit:int = 5) -> list[Media]:
        query = """
            SELECT
                mi.*,
                ps.status,
                ei.source AS ext_source,
                ei.external_id
            FROM media_items mi
            LEFT JOIN processing_state ps ON ps.media_item_id = mi.id
            LEFT JOIN external_ids ei ON ei.media_item_id = mi.id
        """
        params = []
        if media_type:
            query += "WHERE mi.media_type = %s\n"
            params.append(media_type)
        
        query += " ORDER BY mi.created_at DESC\n"

        if limit>0:
            query += " LIMIT %s"
            params.append(limit)

        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        items: dict[int, Media] = {}

        for r in rows:
            mid = r["id"]
            if mid not in items:
                items[mid] = Media(
                    id=mid,
                    title=r["title"],
                    year=r["year"],
                    media_type=r["media_type"],
                    category=r["category"],
                    source=r["source"],
                    source_ref=r["source_ref"],
                    original_title=r.get("original_title"),
                    language=r.get("language"),
                    status=r["status"]
                )

            if r["ext_source"]:
                items[mid].external_ids[r["ext_source"]] = r["external_id"]

        return list(items.values())
    
    def get_media_status(self, source: Optional[str] = None) -> list[MediaStatus]:
        query = """
            SELECT
                ps.media_item_id,
                ei.source,
                ei.external_id,
                ps.status
            FROM external_ids ei
            JOIN processing_state ps ON ps.media_item_id = ei.media_item_id
        """
        params = []
        if source:
            query += " WHERE ei.source = %s"
            params.append(source)

        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            MediaStatus(
                media_item_id=row[0],
                source=row[1],
                external_id=row[2],
                status=row[3]
            )
            for row in rows
        ]


    def mark_as_processed(self, title, year, status="processed"):
        """
        Mark a media item as processed.

        Args:
            title (str): Title of the media.
            year (int): Release year.
            status (str, optional): Status to set ('processed', 'error').
        """
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE media_items
                SET status=%s
                WHERE title=%s AND year=%s
            """, (status, title, year))

    def search_media_by_title_year(self, title, year):
        """
        Search for a media item by title and year.

        Returns:
            dict or None: Media item if found.
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM media_items
                WHERE title=%s AND year=%s
            """, (title, year))
            return cur.fetchone()
    
    def count_media(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM media_items")
            return cur.fetchone()[0]
    
    def count_present(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT mi.id)
                FROM media_items mi
                JOIN external_ids ei ON ei.media_item_id = mi.id
                WHERE ei.source IN ('radarr', 'sonarr')
            """)
            return cur.fetchone()[0]
    
    def count_missing(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM media_items mi
                LEFT JOIN external_ids ei
                    ON ei.media_item_id = mi.id
                    AND ei.source IN ('radarr', 'sonarr')
                WHERE ei.id IS NULL
            """)
            return cur.fetchone()[0]
    
    def count_downloading(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM downloads
                WHERE status IN ('queued', 'downloading')
            """)
            return cur.fetchone()[0]
        
    def count_failed(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM processing_state
                WHERE status = 'failed'
            """)
            return cur.fetchone()[0]
    
    def get_active_downloads(self, limit=10):
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT mi.title, mi.year, d.status, s.name, d.updated_at
                FROM downloads d
                JOIN media_items mi ON mi.id = d.media_item_id
                JOIN sources s ON s.id = d.source_id
                WHERE d.status IN ('queued', 'downloading')
                ORDER BY d.updated_at DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()

    
    def get_wanted_items(self, media_type: str | None = None, limit: int = 5) -> list[Media]:
        query = """
            SELECT
                mi.*,
                ps.status,
                ei.source AS ext_source,
                ei.external_id
            FROM media_items mi
            LEFT JOIN processing_state ps ON ps.media_item_id = mi.id
            LEFT JOIN external_ids ei ON ei.media_item_id = mi.id
        """
        params = []

        if media_type:
            query += " WHERE mi.media_type = %s\n"   # nota lo spazio prima di WHERE
            params.append(media_type)

        query += " ORDER BY mi.created_at DESC\n"
        query += " LIMIT %s"
        params.append(limit)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:  # <-- QUESTO
            cur.execute(query, params)
            rows = cur.fetchall()

        items: dict[int, Media] = {}

        for r in rows:  
            mid = r["id"]
            if mid not in items:
                items[mid] = Media(
                    id=mid,
                    title=r["title"],
                    year=r["year"],
                    media_type=r["media_type"],
                    category=r["category"],
                    source=r["source"],
                    source_ref=r["source_ref"],
                    original_title=r.get("original_title"),
                    language=r.get("language"),
                    status=r["status"]
                )

            if r["ext_source"]:
                items[mid].external_ids[r["ext_source"]] = r["external_id"]

        return list(items.values())


    def get_last_imports(self, limit=5):
        return self.get_wanted_items(limit=limit)

    def get_media_item(self, media_item_id: int) -> Media | None:
        query = """
            SELECT
                mi.*,
                ps.status,
                ei.source AS ext_source,
                ei.external_id
            FROM media_items mi
            LEFT JOIN processing_state ps ON ps.media_item_id = mi.id
            LEFT JOIN external_ids ei ON ei.media_item_id = mi.id
            WHERE mi.id = %s
        """

        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (media_item_id,))
            rows = cur.fetchall()

        if not rows:
            return None

        item = Media(
            id=rows[0]["id"],
            title=rows[0]["title"],
            year=rows[0]["year"],
            media_type=rows[0]["media_type"],
            category=rows[0]["category"],
            source=rows[0]["source"],
            source_ref=rows[0]["source_ref"],
            original_title=rows[0].get("original_title"),
            language=rows[0].get("language"),
            status=rows[0]["status"]
        )

        for r in rows:
            if r.get("ext_source"):
                item.external_ids[r["ext_source"]] = r["external_id"]

        return item
        
    def get_services(self) -> 'list[Service]':
            """
            Load all services with their settings from the database
            and return them as a list of Service objects.
            """
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT s.id AS service_id, s.name AS service_name, s.description AS service_desc, s.enabled AS service_enabled,
                        ss.id AS setting_id, ss.key AS setting_key, ss.label, ss.value, ss.value_type, ss.required
                    FROM services s
                    LEFT JOIN service_settings ss ON ss.service_id = s.id
                    ORDER BY s.name, ss.id
                """)
                rows = cur.fetchall()

            services_dict = {}
            for r in rows:
                setting_obj = None
                if r["setting_id"] is not None:
                    setting_obj = ServiceSetting(
                        id=r["setting_id"],
                        service_id=r["service_id"],
                        key=r["setting_key"],
                        label=r["label"],
                        value=r["value"],
                        value_type=r["value_type"],
                        required=r["required"]
                    )
                if r["service_id"] not in services_dict:
                    services_dict[r["service_id"]] = Service(
                        id=r["service_id"],
                        name=r["service_name"],
                        description=r["service_desc"],
                        enabled=r["service_enabled"],
                        settings=[setting_obj] if setting_obj else []
                    )
                elif setting_obj:
                    services_dict[r["service_id"]].settings.append(setting_obj)

            return list(services_dict.values())
    
    def getMediaStatus(self, source: str | None = None) -> list[MediaStatus]:
        """
        Recupera lo stato dei media per una o tutte le sorgenti.

        :param source: nome sorgente (es. 'animeworld') o None per tutte
        :return: lista di MediaStatus
        """
        query = """
            SELECT
                ps.media_item_id,
                ei.source,
                ei.external_id,
                ps.status
            FROM external_ids ei
            JOIN processing_state ps ON ps.media_item_id = ei.media_item_id
        """

        params = []
        if source:
            query += " WHERE ei.source = %s"
            params.append(source)

        with self.conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            MediaStatus(
                id=i,
                media_item_id=row[0],
                source=row[1],
                external_id=row[2],
                status=row[3]
            )
            for i, row in enumerate(rows)
        ]

        
    def get_service_settings(self, service_name):
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT  ss.id, ss.service_id, ss.key, ss.label, ss.value, ss.value_type, ss.required
                FROM service_settings ss
                JOIN services s ON s.id = ss.service_id
                WHERE s.name = %s
                ORDER BY ss.key
            """, (service_name,))
            return cur.fetchall()

    def get_service_config(self, service_name: str) -> dict[str, object]:
        rows = self.get_service_settings(service_name)
        config: dict[str, object] = {}
        for row in rows:
            value = row["value"]
            value_type = row.get("value_type") or "string"
            if value is not None:
                if value_type in ("int", "integer"):
                    try:
                        value = int(value)
                    except ValueError:
                        pass
                elif value_type in ("bool", "boolean"):
                    value = str(value).strip().lower() in ("1", "true", "yes", "on")
            config[row["key"]] = value
        return config
        
    def set_service_settings(self, settings: 'list[ServiceSetting]'):
        with self.conn.cursor() as cur:
            for setting in settings:
                cur.execute("""
                    UPDATE service_settings
                    SET value=%s
                    WHERE id=%s
                """, (setting.value, setting.id))
        self.conn.commit()
