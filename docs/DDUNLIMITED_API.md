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

## Sorgenti forum filtrate e ricostruzione cache

Sono supportate sia le liste manuali `viewtopic.php` sia i forum `viewforum.php`.
Il parser forum usa le righe ordinarie `li.row a.topictitle`, escludendo annunci,
annunci globali e topic fissati. I parametri originali (compresi `cf[...]` e
`cfr[...]`) vengono riapplicati a ogni offset di paginazione: i link DDU osservati
non li conservano. I topic sono deduplicati per ID, anche tra sorgenti.

Verifica HTML autenticato del 6 novembre 2026: il filtro
`https://ddunlimited.net/viewforum.php?f=1584&cf[1]=21&cfr[1]=21`
contiene il topic 3971855 nella prima pagina (23 release ordinarie); la seconda
pagina contiene 25 release. La vecchia lista `viewtopic.php?t=3747498#T`
produce 1414 release. Non e stata eseguita la scansione completa delle 57 pagine.

Per aggiornare:

1. Modificare la sorgente esistente con l'URL forum filtrato, oppure aggiungerne
   una nuova e disabilitare la vecchia per evitare sovrapposizioni inutili.
2. Impostare media_type, category, qualita e lingua desiderati. Per Anime Movie
   mantenere **media_type=movie e category=movie**: EmuleDDU interpreta anime
   come serie. I valori espliciti della sorgente prevalgono sui metadati estratti.
3. Verificare la sessione nel browser remoto prima della lettura. Il pulsante di
   test della singola sorgente esegue ora tutte le sue pagine e ne aggiorna la cache.
4. Per ricostruire tutte le sorgenti abilitate usare Ricarica cache, solo quando
   desiderato. Il progresso mostra pagine lette, release uniche della sorgente e
   totale consolidato; il riepilogo finale include sorgenti, pagine e release.

Il refresh completo sostituisce la cache soltanto dopo il successo di tutte le
sorgenti. Errori HTTP, redirect inattesi, challenge, login, pagine ripetute,
paginazione incompleta o annullamento conservano la cache precedente. La scrittura
JSON usa un file temporaneo e sostituzione atomica. Schema cache e campi delle
risposte release/ricerca restano invariati; il progresso aggiunge `pages_read`,
`source_pages` e `source_items`.

Conflitti tra sorgenti: category/media_type mantengono la precedenza del primo
item incontrato, come prima; ogni conflitto viene segnalato nel log con topic,
valori e sorgenti. Non viene applicata alcuna conversione automatica da anime a
movie. Nel refresh singolo gli item condivisi con altre sorgenti vengono mantenuti:
la precedenza dei loro metadati resta invariata. Per eliminare associazioni obsolete
tra sorgenti o applicare una riclassificazione condivisa, ricostruire l'intera cache.

Test locali: `python -m unittest discover -s tests -v`.
