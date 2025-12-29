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
