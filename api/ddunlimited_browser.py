import os

from api import remote_browser
from core import db_core


class DDUBrowserError(remote_browser.RemoteBrowserError):
    pass


class DDUBrowserAuthRequired(remote_browser.RemoteBrowserAuthRequired):
    pass


def fetch_page(
    url: str,
    db: db_core.MediaDB | None = None,
    wait_until: str = "domcontentloaded",
) -> dict[str, object]:
    try:
        return remote_browser.fetch_page(url, base_url=_base_url(db), service_name="DDUnlimited", wait_until=wait_until)
    except remote_browser.RemoteBrowserAuthRequired as exc:
        raise DDUBrowserAuthRequired(str(exc)) from exc


def fetch_html(url: str, db: db_core.MediaDB | None = None, wait_until: str = "domcontentloaded") -> str:
    try:
        return remote_browser.fetch_html(url, base_url=_base_url(db), service_name="DDUnlimited", wait_until=wait_until)
    except remote_browser.RemoteBrowserAuthRequired as exc:
        raise DDUBrowserAuthRequired(str(exc)) from exc


def get_browser_status(db: db_core.MediaDB | None = None, check_session: bool = True) -> dict[str, object]:
    return remote_browser.get_browser_status(base_url=_base_url(db), check_session=check_session)


def _base_url(db: db_core.MediaDB | None = None) -> str:
    if db:
        cfg = db.get_service_config("DDUnlimited")
        value = str(cfg.get("ddunlimited_url") or "").strip()
        if value:
            return value.rstrip("/")
    return (os.environ.get("DDU_BASE_URL") or "https://ddunlimited.net").strip().rstrip("/")
