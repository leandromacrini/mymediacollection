-- ===============================================
-- PostgreSQL schema for media management
-- Designed for integration with Radarr / Sonarr / Plex / eMule
-- ===============================================

-- Create a dedicated database
CREATE DATABASE my_media_collection
    WITH 
    OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'C'
    LC_CTYPE = 'C'
    TEMPLATE = template0;

-- Create a dedicated user
CREATE USER mmc_user WITH PASSWORD 'CHANGE_ME';

-- Grant all privileges on the database to the user
GRANT ALL PRIVILEGES ON DATABASE my_media_collection TO mmc_user;

-- 1) Main table for media items
CREATE TABLE IF NOT EXISTS media_items (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    year INT,
    media_type TEXT NOT NULL,         -- movie | series | ova | special
    category TEXT,                    -- anime | film | tv | documentary
    original_title TEXT,
    language TEXT,
    source TEXT NOT NULL,             -- plex | animeworld | text | manual | future
    source_ref TEXT,                  -- plex path, text line, etc
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_media_items_title_year 
    ON media_items(title, year);

-- 2) Table for original media files
CREATE TABLE IF NOT EXISTS media_files (
    id SERIAL PRIMARY KEY,
    media_item_id INT NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    original_path TEXT NOT NULL,
    basename TEXT,
    extension TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    UNIQUE(original_path)
);

-- 3) External IDs (Radarr/Sonarr/TMDB/IMDB)
CREATE TABLE IF NOT EXISTS external_ids (
    id SERIAL PRIMARY KEY,
    media_item_id INT NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    source TEXT NOT NULL,             -- radarr | sonarr | tmdb | imdb | anilist
    external_id TEXT NOT NULL
);

-- 4) Matching decisions
CREATE TABLE IF NOT EXISTS matches (
    id SERIAL PRIMARY KEY,
    media_item_id INT NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
    matched_title TEXT,
    matched_year INT,
    matched_tmdb_id TEXT,
    confidence NUMERIC(3,2) DEFAULT 1.0,   -- 1.0 automatic, <1 manual
    chosen_by TEXT,                        -- auto | user
    chosen_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Useful indexes
CREATE INDEX IF NOT EXISTS idx_external_ids_media ON external_ids(media_item_id);

-- Dashboard indexes
CREATE INDEX IF NOT EXISTS idx_media_items_created_at
ON media_items(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_media_items_media_type
ON media_items(media_type);

CREATE INDEX IF NOT EXISTS idx_external_ids_lookup
ON external_ids(source, external_id);

CREATE INDEX IF NOT EXISTS idx_media_items_title_year_notnull
ON media_items(title, year)
WHERE year IS NOT NULL;

-- Services
CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,        -- radarr, sonarr, plex, animeworld, emule
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE
);

CREATE TABLE service_settings (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    key TEXT NOT NULL,             -- es: base_url, api_key
    label TEXT NOT NULL,           -- testo leggibile in GUI
    value TEXT,
    value_type TEXT NOT NULL DEFAULT 'string', -- string, int, bool, password
    required BOOLEAN DEFAULT FALSE,
    UNIQUE(service_id, key)
);

-- 1️⃣ Radarr
INSERT INTO services (name, description, enabled)
VALUES 
('Radarr', 'Gestione film e import Radarr', TRUE)
ON CONFLICT (name) DO NOTHING;

-- 2️⃣ Sonarr
INSERT INTO services (name, description, enabled)
VALUES 
('Sonarr', 'Gestione serie TV e import Sonarr', TRUE)
ON CONFLICT (name) DO NOTHING;

-- 3️⃣ Plex Web
INSERT INTO services (name, description, enabled)
VALUES 
('Plex Web', 'Import media da Plex database', TRUE)
ON CONFLICT (name) DO NOTHING;

-- 4️⃣ Anime World
INSERT INTO services (name, description, enabled)
VALUES 
('Anime World', 'Import media da Anime World', TRUE)
ON CONFLICT (name) DO NOTHING;

-- 5️⃣ DDUnlimited
INSERT INTO services (name, description, enabled)
VALUES 
('DDUnlimited', 'Ricerca liste e segnalazioni DDUnlimited', TRUE)
ON CONFLICT (name) DO NOTHING;

-- 6️⃣ Emule
INSERT INTO services (name, description, enabled)
VALUES 
('Emule', 'Monitoraggio download Emule', TRUE)
ON CONFLICT (name) DO NOTHING;

-- ===============================================
-- INSERT IMPOSTAZIONI PER OGNI SERVIZIO
-- ===============================================

-- Radarr
INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'radarr_url', 'Radarr URL', 'REMOVED', 'string', TRUE FROM services WHERE name='Radarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'radarr_api_key', 'Radarr API Key', 'CHANGE_ME', 'string', TRUE FROM services WHERE name='Radarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'radarr_root_folder', 'Radarr Root Folder', '', 'string', FALSE FROM services WHERE name='Radarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'radarr_profile_id', 'Radarr Quality Profile', '', 'int', FALSE FROM services WHERE name='Radarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'radarr_enable_search', 'Radarr Enable Search', 'false', 'boolean', FALSE FROM services WHERE name='Radarr'
ON CONFLICT (service_id, key) DO NOTHING;

-- Sonarr
INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'sonarr_url', 'Sonarr URL', 'REMOVED', 'string', TRUE FROM services WHERE name='Sonarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'sonarr_api_key', 'Sonarr API Key', 'CHANGE_ME', 'string', TRUE FROM services WHERE name='Sonarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'sonarr_root_folder', 'Sonarr Root Folder', '', 'string', FALSE FROM services WHERE name='Sonarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'sonarr_profile_id', 'Sonarr Quality Profile', '', 'int', FALSE FROM services WHERE name='Sonarr'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'sonarr_enable_search', 'Sonarr Enable Search', 'false', 'boolean', FALSE FROM services WHERE name='Sonarr'
ON CONFLICT (service_id, key) DO NOTHING;

-- Plex Web
INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'plex_db_path', 'Percorso Plex DB', '', 'string', TRUE FROM services WHERE name='Plex Web'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'plex_web_url', 'URL Plex Web', '', 'string', FALSE FROM services WHERE name='Plex Web'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'plex_web_token', 'Plex Token', '', 'password', FALSE FROM services WHERE name='Plex Web'
ON CONFLICT (service_id, key) DO NOTHING;

-- Anime World
INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'animeworld_url', 'Anime World URL', '', 'string', TRUE FROM services WHERE name='Anime World'
ON CONFLICT (service_id, key) DO NOTHING;

-- DDUnlimited
INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'ddunlimited_url', 'DDUnlimited URL', 'https://ddunlimited.net', 'string', TRUE FROM services WHERE name='DDUnlimited'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'ddunlimited_username', 'DDUnlimited Username', '', 'string', FALSE FROM services WHERE name='DDUnlimited'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'ddunlimited_password', 'DDUnlimited Password', '', 'password', FALSE FROM services WHERE name='DDUnlimited'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'ddunlimited_refresh_days', 'DDUnlimited Refresh (days)', '90', 'int', FALSE FROM services WHERE name='DDUnlimited'
ON CONFLICT (service_id, key) DO NOTHING;

-- Emule
INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'emule_incoming_dir', 'Cartella Emule Incoming', '', 'string', TRUE FROM services WHERE name='Emule'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'emule_url', 'Emule WebUI URL', '', 'string', FALSE FROM services WHERE name='Emule'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'emule_password', 'Emule WebUI Password', '', 'password', FALSE FROM services WHERE name='Emule'
ON CONFLICT (service_id, key) DO NOTHING;

INSERT INTO service_settings (service_id, key, label, value, value_type, required)
SELECT id, 'emule_enabled', 'Abilita Emule', 'true', 'boolean', TRUE FROM services WHERE name='Emule'
ON CONFLICT (service_id, key) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_service_settings_service
ON service_settings(service_id);

-- DDUnlimited list sources
CREATE TABLE IF NOT EXISTS ddunlimited_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,     -- movie | series
    category TEXT,                -- anime | film | tv
    quality TEXT,
    language TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    last_count INTEGER DEFAULT 0,
    last_checked TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ddunlimited_sources_enabled
ON ddunlimited_sources(enabled);

INSERT INTO ddunlimited_sources (name, url, media_type, category, quality, enabled)
VALUES
('Serie TV HD', 'https://ddunlimited.net/viewtopic.php?t=3747331', 'series', 'tv', 'HD', TRUE),
('Movie HD', 'https://ddunlimited.net/viewtopic.php?t=3747498', 'movie', 'film', 'HD', TRUE),
('Serie TV A-Z', 'https://ddunlimited.net/viewtopic.php?t=61463', 'series', 'tv', NULL, TRUE),
('Movie A', 'https://ddunlimited.net/viewtopic.php?f=1988&t=3941486', 'movie', 'film', NULL, TRUE)
ON CONFLICT (url) DO NOTHING;

-- MirCrew list sources
CREATE TABLE IF NOT EXISTS mircrew_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    category_label TEXT,
    category_value TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    last_count INTEGER DEFAULT 0,
    last_checked TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mircrew_sources_enabled
ON mircrew_sources(enabled);

-- ===============================================
-- Telegram
-- ===============================================

CREATE TABLE IF NOT EXISTS telegram_channel (
    id BIGSERIAL PRIMARY KEY,
    channel_username TEXT NOT NULL UNIQUE,
    channel_id BIGINT UNIQUE,
    channel_title TEXT,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    refresh_interval_minutes INTEGER NOT NULL DEFAULT 60,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS telegram_channel_state (
    channel_id BIGINT PRIMARY KEY,
    channel_username TEXT,
    channel_title TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_scanned_message_id BIGINT NOT NULL DEFAULT 0,
    latest_known_message_id BIGINT,
    last_scan_at TIMESTAMPTZ,
    last_full_scan_at TIMESTAMPTZ,
    scan_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS telegram_release (
    id BIGSERIAL PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    release_key TEXT UNIQUE,
    first_message_id BIGINT,
    last_message_id BIGINT,
    parent_message_id BIGINT,
    header_message_id BIGINT,
    title_raw TEXT,
    title_display TEXT,
    title_normalized TEXT,
    forward_title_dominant TEXT,
    release_kind TEXT,
    year_guess INTEGER,
    season_guess INTEGER,
    poster_message_id BIGINT,
    photo_count INTEGER NOT NULL DEFAULT 0,
    media_count INTEGER NOT NULL DEFAULT 0,
    total_size_bytes BIGINT NOT NULL DEFAULT 0,
    published_at TIMESTAMPTZ,
    updated_source_at TIMESTAMPTZ,
    source_ref TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS telegram_media_message (
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    release_id BIGINT,
    message_date TIMESTAMPTZ,
    media_kind TEXT,
    file_name TEXT,
    file_size BIGINT,
    mime_type TEXT,
    forward_chat_title TEXT,
    forward_chat_username TEXT,
    text_raw TEXT,
    grouped_id TEXT,
    reply_to_message_id BIGINT,
    has_media BOOLEAN NOT NULL DEFAULT FALSE,
    has_text BOOLEAN NOT NULL DEFAULT FALSE,
    is_video_like BOOLEAN NOT NULL DEFAULT FALSE,
    release_kind_guess TEXT,
    title_guess TEXT,
    title_guess_normalized TEXT,
    season_guess INTEGER,
    episode_guess INTEGER,
    year_guess INTEGER,
    source_ref TEXT,
    payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel_id, message_id)
);

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS release_key TEXT;

ALTER TABLE telegram_channel
ADD COLUMN IF NOT EXISTS channel_id BIGINT UNIQUE;

ALTER TABLE telegram_channel
ADD COLUMN IF NOT EXISTS channel_title TEXT;

ALTER TABLE telegram_channel
ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE telegram_channel
ADD COLUMN IF NOT EXISTS refresh_interval_minutes INTEGER NOT NULL DEFAULT 60;

ALTER TABLE telegram_channel
ADD COLUMN IF NOT EXISTS notes TEXT;

ALTER TABLE telegram_channel_state
ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE telegram_channel_state
ADD COLUMN IF NOT EXISTS latest_known_message_id BIGINT;

ALTER TABLE telegram_channel_state
ADD COLUMN IF NOT EXISTS scan_error TEXT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS parent_message_id BIGINT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS header_message_id BIGINT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS title_display TEXT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS title_normalized TEXT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS forward_title_dominant TEXT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS release_kind TEXT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS year_guess INTEGER;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS season_guess INTEGER;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS poster_message_id BIGINT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS photo_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS media_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS total_size_bytes BIGINT NOT NULL DEFAULT 0;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS updated_source_at TIMESTAMPTZ;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS source_ref TEXT;

ALTER TABLE telegram_release
ADD COLUMN IF NOT EXISTS notes TEXT;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS text_raw TEXT;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS grouped_id TEXT;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS has_media BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS has_text BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS is_video_like BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS release_kind_guess TEXT;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS title_guess TEXT;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS title_guess_normalized TEXT;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS season_guess INTEGER;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS episode_guess INTEGER;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS year_guess INTEGER;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS source_ref TEXT;

ALTER TABLE telegram_media_message
ADD COLUMN IF NOT EXISTS payload_json JSONB;

CREATE INDEX IF NOT EXISTS idx_telegram_channel_enabled
ON telegram_channel (is_enabled);

CREATE INDEX IF NOT EXISTS idx_telegram_channel_username
ON telegram_channel (channel_username);

CREATE INDEX IF NOT EXISTS idx_telegram_channel_state_username
ON telegram_channel_state (channel_username);

CREATE INDEX IF NOT EXISTS idx_telegram_release_channel_published
ON telegram_release (channel_id, published_at DESC);

DROP INDEX IF EXISTS uq_telegram_release_release_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_telegram_release_release_key'
    ) THEN
        ALTER TABLE telegram_release
        ADD CONSTRAINT uq_telegram_release_release_key UNIQUE (release_key);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_telegram_release_title_normalized
ON telegram_release (title_normalized);

CREATE INDEX IF NOT EXISTS idx_telegram_release_forward_title
ON telegram_release (forward_title_dominant);

CREATE INDEX IF NOT EXISTS idx_telegram_media_release
ON telegram_media_message (release_id);

CREATE INDEX IF NOT EXISTS idx_telegram_media_message_date
ON telegram_media_message (channel_id, message_date DESC);

CREATE INDEX IF NOT EXISTS idx_telegram_media_title_guess_normalized
ON telegram_media_message (title_guess_normalized);

CREATE INDEX IF NOT EXISTS idx_telegram_media_forward_title
ON telegram_media_message (forward_chat_title);

CREATE INDEX IF NOT EXISTS idx_telegram_media_video_like
ON telegram_media_message (is_video_like);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_telegram_release_channel_state'
    ) THEN
        ALTER TABLE telegram_release
        ADD CONSTRAINT fk_telegram_release_channel_state
        FOREIGN KEY (channel_id) REFERENCES telegram_channel_state(channel_id)
        ON DELETE CASCADE;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_telegram_media_channel_state'
    ) THEN
        ALTER TABLE telegram_media_message
        ADD CONSTRAINT fk_telegram_media_channel_state
        FOREIGN KEY (channel_id) REFERENCES telegram_channel_state(channel_id)
        ON DELETE CASCADE;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_telegram_media_release'
    ) THEN
        ALTER TABLE telegram_media_message
        ADD CONSTRAINT fk_telegram_media_release
        FOREIGN KEY (release_id) REFERENCES telegram_release(id)
        ON DELETE SET NULL;
    END IF;
END
$$;
