# MirCrew API

API HTTP esposta da MMC per usare MirCrew come backend centralizzato.

Base URL locale tipico:

```text
http://<mmc-host>:5000
```

## Note operative

- Gli endpoint MirCrew dipendono dal browser remoto Chromium/CDP condiviso con DDU.
- La cache liste e persistita su file JSON locale.
- Il dettaglio release viene risolto on demand via browser e tenuto solo in RAM con TTL.
- Se la sessione browser non e valida, gli endpoint operativi possono rispondere con:
  - `409 auth_required`

## Configurazione browser condivisa

Variabili `env` usate oggi:

```text
BROWSER_CDP_URL=http://<browser-host>:9223
BROWSER_LOGIN_URL=https://<browser-host>:3021
BROWSER_TIMEOUT_SECONDS=15
MIRCREW_BASE_URL=https://mircrew-releases.org
MIRCREW_DETAIL_CACHE_TTL_SECONDS=86400
MIRCREW_REFRESH_MAX_PAGES=200
```

Note:

- `BROWSER_LOGIN_URL` oggi apre la GUI remota del browser.
- Non forza ancora automaticamente la navigazione alla pagina login MirCrew.

## Health

### `GET /api/mircrew/health`

Ritorna stato browser, cache e refresh.

Esempio risposta:

```json
{
  "ok": false,
  "browser": {
    "ok": false,
    "state": "session_unknown",
    "label": "Stato non verificato"
  },
  "cache": {
    "exists": true,
    "count": 47156,
    "updated_at": "2026-02-25T19:24:13"
  },
  "refresh": {
    "running": false,
    "processed_sources": 0,
    "total_sources": 0
  }
}
```

## Browser status

### `GET /api/mircrew/browser/status`

Ritorna solo lo stato del browser/sessione MirCrew.

Stati principali:

- `authenticated`
- `auth_required`
- `browser_unavailable`
- `session_unknown`

## Sources / Liste

### `GET /api/mircrew/sources`

Elenco liste configurate.

Esempio risposta:

```json
{
  "items": [
    {
      "id": 1,
      "name": "Serie TV A-Z",
      "url": "https://mircrew-releases.org/forum/forumdisplay.php?fid=12",
      "category_label": "Serie TV",
      "category_value": "tv",
      "enabled": true,
      "last_count": 1234
    }
  ]
}
```

### `POST /api/mircrew/sources`

Crea una nuova lista.

Payload:

```json
{
  "name": "Serie TV A-Z",
  "url": "https://mircrew-releases.org/forum/forumdisplay.php?fid=12",
  "category_label": "Serie TV",
  "category_value": "tv",
  "enabled": true
}
```

Errori tipici:

- `400 invalid_data`
- `409 duplicate_url`

### `PUT /api/mircrew/sources/<id>`

Aggiorna una lista esistente.

### `DELETE /api/mircrew/sources/<id>`

Elimina una lista.

### `POST /api/mircrew/sources/<id>/test`

Testa una lista via browser autenticato.

Esempio risposta:

```json
{
  "ok": true,
  "count": 220,
  "unique_count": 220
}
```

Errori tipici:

- `404 not_found`
- `409 auth_required`
- `422 invalid_source_page`

## Cache

### `GET /api/mircrew/cache/status`

Stato cache corrente.

Esempio risposta:

```json
{
  "exists": true,
  "count": 47156,
  "updated_at": "2026-02-25T19:24:13",
  "cache_loaded": false,
  "path": "/app/data/mircrew_releases.json",
  "detail_cache_items": 0
}
```

### `POST /api/mircrew/cache/refresh`

Avvia refresh cache in background leggendo tutte le `mircrew_sources` attive.

### `GET /api/mircrew/cache/progress`

Stato avanzamento refresh.

Campi principali:

- `running`
- `total_sources`
- `processed_sources`
- `current_source`
- `items_count`
- `cancelled`
- `error`

### `POST /api/mircrew/cache/cancel`

Annulla refresh in corso.

## Search

### `GET /api/mircrew/search?q=<query>&limit=<n>`

Cerca nella cache locale MirCrew.

Parametri:

- `q`: obbligatorio
- `limit`: opzionale, default `50`, max `500`

Esempio:

```text
GET /api/mircrew/search?q=clarence&limit=20
```

Esempio risposta:

```json
{
  "ok": true,
  "query": "clarence",
  "count": 2,
  "items": [
    {
      "release_id": "123456",
      "release_url": "https://mircrew-releases.org/forum/viewtopic.php?t=123456",
      "title_hint": "Clarence - Stagione 1",
      "clean_title": "Clarence",
      "status": "new"
    }
  ]
}
```

## Release lookup

### `GET /api/mircrew/release?release_id=<id>`

### `GET /api/mircrew/release?url=<release_url>`

Ritorna i dettagli della release, risolti on demand via browser remoto.

Esempio risposta:

```json
{
  "ok": true,
  "cache_hit": false,
  "release_id": "123456",
  "release_url": "https://mircrew-releases.org/forum/viewtopic.php?t=123456",
  "magnet_links": [
    "magnet:?xt=urn:btih:..."
  ],
  "torrent_links": [],
  "size_text_raw": "12.4 GB",
  "size_bytes": 12400000000,
  "thanks_required": true,
  "thanks_clicked": true,
  "detail_status": "ok",
  "detail_error": null,
  "detail_updated_at": "2026-06-11T10:00:00+00:00"
}
```

Errori tipici:

- `404 release_not_found`
- `409 auth_required`
- `422 invalid_source_page`

## Flusso consigliato per client esterni

Per un client esterno che usa MirCrew via MMC:

1. `GET /api/mircrew/health`
2. `GET /api/mircrew/search?q=...`
3. `GET /api/mircrew/release?release_id=...`

In caso di `auth_required`, il client deve fermarsi e lasciare che l’utente ripristini la sessione dal browser remoto MMC.
