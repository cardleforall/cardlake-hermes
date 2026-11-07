"""Which Cardlake the plugin links to: cardlake.app, or a self-hosted copy.

There's nothing extra to set: the address comes from the Cardlake connection Hermes
already has (`hermes mcp add cardlake --url <address>/api/mcp`), so the links in
replies and buttons always open the same Cardlake the cards came from.
CARDLAKE_URL overrides it, for a copy whose web address differs from its API's.
"""

from __future__ import annotations

import os
import re
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


def _hermes_config() -> Mapping:
    from hermes_cli.config import load_config
    return load_config()


def cardlake_address(env: Mapping[str, str] = os.environ,
                     load_config: Callable[[], Mapping] = _hermes_config) -> str:
    """The Cardlake web address, without a trailing slash."""
    return _clean(env.get("CARDLAKE_URL")) or _from_connection(load_config) or DEFAULT


# Read once when Hermes loads the plugin. Changing the connection needs a restart
# anyway, which reloads this too.
ADDRESS = cardlake_address()
