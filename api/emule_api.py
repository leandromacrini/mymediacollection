import requests
from core import db_core

# ===== CONFIG =====
EMULE_URL = ""
EMULE_PASSWORD = ""
REQUEST_TIMEOUT = 8
# ==================


def _get_config(db: db_core.MediaDB | None = None) -> dict:
    cfg = db.get_service_config("Emule") if db else {}
    url = (cfg.get("emule_url") or EMULE_URL).rstrip("/")
    password = cfg.get("emule_password") or EMULE_PASSWORD
    return {
        "url": url,
        "password": password
    }


def emule_get_client(db: db_core.MediaDB) -> dict:
    return _get_config(db)


def emule_test_connection(
    db: db_core.MediaDB | None = None,
    url: str | None = None,
    password: str | None = None
) -> tuple[bool, str]:
    if url is None:
        cfg = _get_config(db)
        url = cfg["url"]
        password = cfg["password"]
    if not url:
        return False, "Emule WebUI URL mancante."
    try:
        auth = ("", password) if password else None
        r = requests.get(url, auth=auth, timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403):
            return False, "Emule WebUI: credenziali non valide."
        return (r.status_code < 400, f"Emule WebUI status: {r.status_code}")
    except Exception as exc:
        return False, f"Emule WebUI error: {exc}"


def emule_add_ed2k(
    ed2k_link: str,
    db: db_core.MediaDB | None = None,
    url: str | None = None,
    password: str | None = None
) -> tuple[bool, str]:
    if not ed2k_link:
        return False, "ed2k link mancante."
    if url is None:
        cfg = _get_config(db)
        url = cfg["url"]
        password = cfg["password"]
    if not url:
        return False, "Emule WebUI URL mancante."
    try:
        auth = ("", password) if password else None
        r = requests.get(
            url,
            params={"ed2k": ed2k_link},
            auth=auth,
            timeout=REQUEST_TIMEOUT
        )
        return (r.status_code < 400, f"Emule WebUI status: {r.status_code}")
    except Exception as exc:
        return False, f"Emule WebUI error: {exc}"
