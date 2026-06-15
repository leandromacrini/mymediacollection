import os
from contextlib import suppress
from urllib.parse import urlparse

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

DEFAULT_CDP_URL = "http://192.168.1.161:9223"
DEFAULT_LOGIN_URL = "https://192.168.1.161:3021"
DEFAULT_TIMEOUT_SECONDS = 45


class RemoteBrowserError(RuntimeError):
    pass


class RemoteBrowserAuthRequired(RemoteBrowserError):
    pass


def _env_str(name: str, default: str) -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    value = (os.environ.get(name) or "").strip()
    if not value:
        return default
    with suppress(ValueError):
        return max(1, int(value))
    return default


def get_browser_config() -> dict[str, object]:
    cdp_url = _env_str("BROWSER_CDP_URL", _env_str("DDU_BROWSER_CDP_URL", DEFAULT_CDP_URL))
    login_url = _env_str("BROWSER_LOGIN_URL", _env_str("DDU_BROWSER_LOGIN_URL", DEFAULT_LOGIN_URL))
    timeout_seconds = _env_int("BROWSER_TIMEOUT_SECONDS", _env_int("DDU_BROWSER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    return {
        "cdp_url": cdp_url,
        "login_url": login_url,
        "timeout_seconds": timeout_seconds,
    }


def probe_browser(cdp_url: str, timeout_seconds: int) -> dict[str, object]:
    endpoint = cdp_url.rstrip("/") + "/json/version"
    response = requests.get(endpoint, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    return {
        "browser": payload.get("Browser"),
        "protocol_version": payload.get("Protocol-Version"),
        "ws_url": payload.get("webSocketDebuggerUrl"),
    }


def is_login_page(url: str, content: str) -> bool:
    lower_url = (url or "").lower()
    lower_content = (content or "").lower()
    return (
        "mode=login" in lower_url
        or "name=\"login\"" in lower_content
        or "ucp.php?mode=login" in lower_content
        or ("accedi" in lower_content and "password" in lower_content)
        or ("login" in lower_content and "password" in lower_content)
    )


def is_authenticated_page(url: str, content: str, base_host: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.netloc and parsed.netloc != base_host:
        return False
    lower_content = (content or "").lower()
    return (
        "mode=logout" in lower_content
        or "logout" in lower_content
        or "pannello di controllo utente" in lower_content
        or "messaggi privati" in lower_content
        or "benvenuto" in lower_content
    )


def fetch_page(url: str, *, base_url: str, service_name: str, wait_until: str = "domcontentloaded") -> dict[str, object]:
    browser_cfg = get_browser_config()
    timeout_ms = int(browser_cfg["timeout_seconds"]) * 1000
    probe = probe_browser(str(browser_cfg["cdp_url"]), int(browser_cfg["timeout_seconds"]))
    base_host = urlparse(base_url).netloc

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(str(browser_cfg["cdp_url"]), timeout=timeout_ms)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            content = page.content()
            current_url = page.url
            if is_login_page(current_url, content):
                raise RemoteBrowserAuthRequired(f"{service_name} browser session requires login.")
            return {
                "browser": probe.get("browser"),
                "protocol_version": probe.get("protocol_version"),
                "url": current_url,
                "html": content,
                "title": page.title(),
                "ok": is_authenticated_page(current_url, content, base_host) or urlparse(current_url).netloc == base_host,
            }
        finally:
            with suppress(Exception):
                page.close()
            with suppress(Exception):
                browser.close()


def fetch_html(url: str, *, base_url: str, service_name: str, wait_until: str = "domcontentloaded") -> str:
    page_data = fetch_page(url, base_url=base_url, service_name=service_name, wait_until=wait_until)
    return str(page_data["html"])


def get_browser_status(*, base_url: str, check_session: bool = True) -> dict[str, object]:
    browser_cfg = get_browser_config()
    timeout_ms = int(browser_cfg["timeout_seconds"]) * 1000
    status = {
        "ok": False,
        "state": "browser_unavailable",
        "label": "Browser offline",
        "login_url": browser_cfg["login_url"],
        "cdp_url": browser_cfg["cdp_url"],
        "browser": None,
        "protocol_version": None,
        "checked_url": base_url,
        "page_url": None,
        "error": None,
    }

    try:
        probe = probe_browser(str(browser_cfg["cdp_url"]), int(browser_cfg["timeout_seconds"]))
        status["browser"] = probe.get("browser")
        status["protocol_version"] = probe.get("protocol_version")
    except Exception as exc:
        status["error"] = str(exc)
        return status

    if not check_session:
        status["ok"] = True
        status["state"] = "browser_ok"
        status["label"] = "Browser online"
        return status

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(str(browser_cfg["cdp_url"]), timeout=timeout_ms)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            try:
                page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
                content = page.content()
                current_url = page.url
                status["page_url"] = current_url
                base_host = urlparse(base_url).netloc
                if is_login_page(current_url, content):
                    status["state"] = "auth_required"
                    status["label"] = "Login richiesto"
                elif is_authenticated_page(current_url, content, base_host):
                    status["ok"] = True
                    status["state"] = "authenticated"
                    status["label"] = "Connesso"
                else:
                    status["state"] = "session_unknown"
                    status["label"] = "Stato non verificato"
                if status["state"] != "authenticated":
                    status["error"] = status["state"]
            finally:
                with suppress(Exception):
                    page.close()
                with suppress(Exception):
                    browser.close()
    except (PlaywrightError, PlaywrightTimeoutError) as exc:
        status["state"] = "browser_unavailable"
        status["label"] = "Browser offline"
        status["error"] = str(exc)
    return status
