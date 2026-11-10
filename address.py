"""Which Cardlake the plugin links to: cardlake.app, or a self-hosted copy.

There's nothing extra to set: the address comes from the Cardlake connection Hermes
already has (`hermes mcp add cardlake --url <address>/api/mcp`), so the links in
replies and buttons always open the same Cardlake the cards came from.
CARDLAKE_URL overrides it, for a copy whose web address differs from its API's.

It's read when a link is made, not once at start: Hermes reconnects to a changed
connection by itself, without a restart, and the links have to follow it.
"""

from __future__ import annotations

import os
import re
import time
from typing import Callable, Mapping, Optional

DEFAULT = "https://cardlake.app"
SERVER_NAME = "cardlake"
_MCP_PATH = "/api/mcp"
# Strict on purpose: the address goes into Markdown links and Telegram buttons, so
# nothing that could close a link or add formatting (spaces, brackets, quotes) gets in.
_SAFE = re.compile(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~\-/]*)?")


def _clean(url: object) -> Optional[str]:
    url = str(url or "").strip().rstrip("/")
    return url if _SAFE.fullmatch(url) else None


def _from_connection(load_config: Callable[[], Mapping]) -> Optional[str]:
    try:
        server = (load_config().get("mcp_servers") or {}).get(SERVER_NAME) or {}
        url = _clean(server.get("url"))
    except Exception:  # no Hermes config (tests, older Hermes): fall back to the default
        return None
    if url and url.endswith(_MCP_PATH):
        url = url[: -len(_MCP_PATH)]
    return url or None


# The Hermes home (profile folder) this plugin was loaded for. Hermes points its config reader
# at that home while it loads plugins, but commands, buttons and hooks run later, outside that,
# where the reader would fall back to the default home: a gateway serving another profile would
# then see a different config, without this profile's Cardlake connection or time zone.
_home: Optional[object] = None


def remember_home() -> None:
    """Called from register(), while Hermes has the plugin's own home in place."""
    global _home
    try:
        from hermes_constants import get_hermes_home
        _home = get_hermes_home()
    except Exception:  # an older Hermes, or none (tests): read the default home
        _home = None


def _hermes_config() -> Mapping:
    """Hermes' config for the home this plugin was loaded for."""
    from hermes_cli.config import load_config
    if _home is None:
        return load_config()
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    token = set_hermes_home_override(_home)
    try:
        return load_config()
    finally:
        reset_hermes_home_override(token)


def cardlake_address(env: Mapping[str, str] = os.environ,
                     load_config: Callable[[], Mapping] = _hermes_config) -> str:
    """The Cardlake web address, without a trailing slash."""
    return _clean(env.get("CARDLAKE_URL")) or _from_connection(load_config) or DEFAULT


_REREAD_SECONDS = 30.0  # Hermes notices a changed connection within about a minute
_cache: dict = {"address": None, "at": 0.0}


def current(env: Mapping[str, str] = None, load_config: Callable[[], Mapping] = None,
            clock: Callable[[], float] = time.monotonic) -> str:
    """The Cardlake address now, re-read from Hermes' config at most every 30 seconds."""
    now = clock()
    if _cache["address"] and now - _cache["at"] < _REREAD_SECONDS:
        return _cache["address"]
    address = cardlake_address(os.environ if env is None else env, load_config or _hermes_config)
    _cache.update(address=address, at=now)
    return address


def open_link() -> str:
    """Where "Open Cardlake" goes: the feed page of the current Cardlake."""
    return f"{current()}/vault/"
