"""Keeps /cardlake in Telegram's / menu.

Hermes fills the menu with its own commands first and stops at 60, so plugin commands usually
don't make it in, and nothing in the plugin API asks for a place. Typing /cardlake still works,
but people look for it in the menu. So once Telegram connects, the plugin reads the menu Hermes
set and adds /cardlake to it if it's missing. Telegram takes up to 100 commands; Hermes stops at
60 only to stay well inside the size limit, and one more entry doesn't change that.

Hermes builds its menu in the background after connecting and again on every reconnect, so the
check runs a few times after each connect. Someone who has set up their own Telegram menu in
Hermes (platforms.telegram.extra.command_menu) chose what goes in it, so then it's left alone.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Iterable, Mapping

logger = logging.getLogger(__name__)

COMMAND = "cardlake"
DESCRIPTION = "Your Cardlake cards: feed, today, save or snooze"
_TELEGRAM_MAX = 100
# Seconds after connecting: Hermes' own menu usually lands within the first few.
CHECKS = (5, 30, 120)


def menu_is_users(load_config: Callable[[], Mapping]) -> bool:
    """True when the user set up Hermes' Telegram menu themselves."""
    try:
        node: Any = load_config() or {}
    except Exception:
        return False
    for key in ("platforms", "telegram", "extra", "command_menu"):
        node = node.get(key) if isinstance(node, Mapping) else None
    return bool(node)


async def add_if_missing(bot, scopes: Iterable[Any], make_command: Callable[[], Any]) -> bool:
    """Adds /cardlake to each scope's menu that lacks it, keeping everything else in order.
    True when a menu changed."""
    changed = False
    for scope in scopes:
        current = list(await bot.get_my_commands(scope=scope))
        if any(getattr(c, "command", None) == COMMAND for c in current):
            continue
        await bot.set_my_commands(current[:_TELEGRAM_MAX - 1] + [make_command()], scope=scope)
        changed = True
    return changed


async def keep_in_menu(bot, scopes: Iterable[Any], make_command: Callable[[], Any],
                       checks: Iterable[float] = None, sleep=asyncio.sleep) -> None:
    """Runs add_if_missing at each of `checks` seconds after connecting. Never raises: a menu
    that can't be changed only means /cardlake has to be typed."""
    scopes, waited = list(scopes), 0.0
    for at in CHECKS if checks is None else checks:
        await sleep(max(0.0, at - waited))
        waited = at
        try:
            if await add_if_missing(bot, scopes, make_command):
                logger.info("Cardlake: added /%s to Telegram's command menu", COMMAND)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Cardlake: couldn't check Telegram's command menu", exc_info=True)
