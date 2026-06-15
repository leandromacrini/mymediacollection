import os

from api import remote_browser


class MircrewBrowserError(remote_browser.RemoteBrowserError):
    pass


class MircrewBrowserAuthRequired(remote_browser.RemoteBrowserAuthRequired):
    pass


def fetch_page(url: str, wait_until: str = "domcontentloaded") -> dict[str, object]:
    try:
        return remote_browser.fetch_page(url, base_url=_base_url(), service_name="MirCrew", wait_until=wait_until)
    except remote_browser.RemoteBrowserAuthRequired as exc:
        raise MircrewBrowserAuthRequired(str(exc)) from exc


def fetch_html(url: str, wait_until: str = "domcontentloaded") -> str:
    try:
        return remote_browser.fetch_html(url, base_url=_base_url(), service_name="MirCrew", wait_until=wait_until)
    except remote_browser.RemoteBrowserAuthRequired as exc:
        raise MircrewBrowserAuthRequired(str(exc)) from exc


def get_browser_status(check_session: bool = True) -> dict[str, object]:
    return remote_browser.get_browser_status(base_url=_base_url(), check_session=check_session)


def _base_url() -> str:
    return (os.environ.get("MIRCREW_BASE_URL") or "https://mircrew-releases.org").strip().rstrip("/")
