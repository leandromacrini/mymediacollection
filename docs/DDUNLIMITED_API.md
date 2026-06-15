# DDUnlimited API

API HTTP esposta da MMC per usare DDUnlimited come backend centralizzato.

Base URL locale tipico:

```text
http://<mmc-host>:5000
```

## Note operative

- Gli endpoint DDU dipendono dalla sessione browser remota Chromium/CDP.
- Il browser remoto e condiviso anche con MirCrew.
- Se la sessione non e valida, gli endpoint operativi possono rispondere con:
  - `409 auth_required`
- Gli endpoint di gestione liste e cache restano compatibili con la UI MMC.

Documentazione correlata:

- [MIRCREW_API.md](/d:/ownCloud/Backup%20RAID/Software/My%20Media%20Collection/docs/MIRCREW_API.md)

## Health

### `GET /api/ddunlimited/health`

Ritorna stato browser, cache e refresh.

Esempio risposta:

```json
{
  "ok": true,
  "browser": {
    "ok": true,
    "state": "authenticated",
    "label": "Connesso"
  },
  "cache": {
    "count": 0,
    "sources": 66,
    "updated_at": null
  },
  "refresh": {
    "running": false,
    "processed_sources": 0,
    "total_sources": 0
  }
}
```

## Browser status

### `GET /api/ddunlimited/browser/status`

Ritorna solo lo stato del browser/sessione DDU.

Stati principali:

- `authenticated`
- `auth_required`
- `browser_unavailable`
- `session_unknown`

## Search

### `GET /api/ddunlimited/search?q=<query>&limit=<n>`

Cerca nella cache locale DDU.

Parametri:

- `q`: obbligatorio
- `limit`: opzionale, default `50`, max `500`

Esempio:

```text
GET /api/ddunlimited/search?q=words%20worth&limit=10
```

Esempio risposta:

```json
{
  "ok": true,
  "query": "words worth",
  "count": 1,
  "items": [
    {
      "title": "Words Worth: Profezie perverse (1999) [COMPLETA] [V.M. 18]",
      "detail_url": "https://ddunlimited.net/viewtopic.php?t=3939674",
      "topic_id": "3939674",
      "status": "new"
    }
  ]
}
```

## Release lookup

### `GET /api/ddunlimited/release?url=<detail_url>`

### `GET /api/ddunlimited/release?topic_id=<topic_id>`

Ritorna i link ed2k di una release.

È preferibile usare `topic_id` quando il client conserva l’identificativo DDU.

Esempio:

```text
GET /api/ddunlimited/release?topic_id=3939674
```

Esempio risposta:

```json
{
  "ok": true,
  "detail_url": "https://ddunlimited.net/viewtopic.php?t=3939674",
  "topic_id": "3939674",
  "ed2k_items": [
    {
      "name": "WORDS WORTH - PROFEZIE PERVERSE - 01 ... .mkv",
      "size": "433810195",
      "link": "ed2k://|file|..."
    }
  ],
  "ed2k_stats": {
    "count": 5,
    "total_bytes": 2414075299
  }
}
```

## Cache

### `GET /api/ddunlimited/cache/status`

Stato cache corrente.

### `POST /api/ddunlimited/cache/refresh`

Avvia refresh cache in background.

### `GET /api/ddunlimited/cache/progress`

Stato avanzamento refresh.

### `POST /api/ddunlimited/cache/cancel`

Annulla refresh in corso.

## Liste / Sources

### `GET /api/ddunlimited/sources`

Elenco liste configurate.

### `POST /api/ddunlimited/sources`

Crea una nuova lista.

### `PUT /api/ddunlimited/sources/<id>`

Aggiorna una lista.

### `DELETE /api/ddunlimited/sources/<id>`

Elimina una lista.

### `POST /api/ddunlimited/sources/<id>/test`

Testa una lista via browser autenticato.

Errori tipici:

- `auth_required`
- `invalid_source_page`

## Compatibilità consigliata per client esterni

Per un client come `amule-ddu-client`, il flusso consigliato è:

1. `GET /api/ddunlimited/health`
2. `GET /api/ddunlimited/search?q=...`
3. `GET /api/ddunlimited/release?topic_id=...`

In caso di `auth_required`, il client deve fermarsi e lasciare che l’utente rilanci il login dal browser remoto MMC.
