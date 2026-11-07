"""Telegram buttons under the feed: Done, Tomorrow and Next week for the cards shown in full.

Hermes sends a command's reply as plain text, so a reply with buttons is posted by the plugin
itself (ctx.post_message, which only ever reaches the chat that ran the command) and then given
its keyboard. Anywhere that doesn't work, such as an older Hermes, another platform or a group
chat, the reply goes out as ordinary text, exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Optional

from .feed_view import FULL_CARDS, OPEN_LINK, plain

logger = logging.getLogger(__name__)

PREFIX = "clk:"
_SEND_TIMEOUT_SECONDS = 15
_MAX_MESSAGES = 50  # older messages' buttons say the list is out of date
_LABEL_CHARS = 18

# What each button does: (Cardlake tool, its arguments, what the user is told).
_ACTIONS: dict[str, Callable[[dict], tuple[str, dict, str]]] = {
    "t": lambda c: ("snooze_card", {"card_type": c["type"], "card_id": c["id"], "days": 1}, "Snoozed until tomorrow"),
    "w": lambda c: ("snooze_card", {"card_type": c["type"], "card_id": c["id"], "days": 7}, "Snoozed for a week"),
}


def _done(card: dict) -> Optional[tuple[str, dict, str]]:
    """Only reminders and learnings have a 'done'."""
    if card.get("type") == "reminder":
        return "update_reminder", {"id": card["id"], "completed": True}, "Done"
    if card.get("type") == "learning":
        return "update_learning", {"id": card["id"], "status": "watched"}, "Marked as watched"
    return None


def action_for(card: dict, code: str) -> Optional[tuple[str, dict, str]]:
    if code == "d":
        return _done(card)
    make = _ACTIONS.get(code)
    return make(card) if make else None


def _short(card: dict) -> str:
    title = plain(card.get("title")) or "Untitled"
    return title if len(title) <= _LABEL_CHARS else title[: _LABEL_CHARS - 1].rstrip() + "…"


def keyboard_rows(cards: list[dict], finished: Optional[dict[int, str]] = None) -> list[list[dict]]:
    """Rows of {"text", "callback_data" | "url"}: one row per card shown in full, then the link.
    A card that was already acted on keeps a single row saying what happened."""
    finished = finished or {}
    rows = []
    for i, card in enumerate(cards[:FULL_CARDS]):
        if not card.get("id") or not card.get("type"):
            continue
        if i in finished:
            rows.append([{"text": f"✓ {finished[i]}: {_short(card)}", "callback_data": f"{PREFIX}n"}])
            continue
        # The first button carries the card's name, so each row says which card it's for.
        if _done(card):
            row = [{"text": f"✅ {_short(card)}", "callback_data": f"{PREFIX}d:{i}"},
                   {"text": "⏰ Tomorrow", "callback_data": f"{PREFIX}t:{i}"}]
        else:
            row = [{"text": f"⏰ {_short(card)}", "callback_data": f"{PREFIX}t:{i}"}]
        row.append({"text": "📅 Next week", "callback_data": f"{PREFIX}w:{i}"})
        rows.append(row)
    rows.append([{"text": "🔗 Open Cardlake", "url": OPEN_LINK}])
    return rows


def _private_chat(chat_id: Any) -> bool:
    """Telegram gives private chats positive ids and groups negative ones. Buttons only go to private
    chats, where the only person who can tap them is the one who ran the command."""
    try:
        return int(chat_id) > 0
    except (TypeError, ValueError):
        return False


class TelegramButtons:
    def __init__(self, ctx, run_tool: Callable[[str, dict], Any]):
        """run_tool(tool, args) calls Cardlake (with redaction) and raises on failure."""
        self.ctx = ctx
        self.run_tool = run_tool
        self.bot = None
        self.markup: Optional[Callable[[list], Any]] = None  # rows of dicts -> Telegram keyboard
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        # (chat id, message id) -> {"cards": [...], "finished": {index: what happened}}
        self.messages: "OrderedDict[tuple[str, str], dict]" = OrderedDict()

    # Wiring -------------------------------------------------------------------------------------

    def attach(self, native, adapter=None) -> None:
        """Hermes calls this when Telegram connects, with python-telegram-bot's Application."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import CallbackQueryHandler
        self.markup = lambda rows: InlineKeyboardMarkup([[InlineKeyboardButton(**b) for b in row] for row in rows])
        self.bot = native.bot
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        # Scoped to our prefix: Hermes' own buttons keep working.
        native.add_handler(CallbackQueryHandler(self.on_tap, pattern=f"^{PREFIX}"))

    def ready(self) -> bool:
        if self.bot is None or self.markup is None or self.loop is None or self.loop.is_closed():
            return False
        try:
            return self.ctx.session_surface() == "telegram"
        except Exception:
            return False

    # Sending ------------------------------------------------------------------------------------

    def send(self, text: str, cards: list[dict]) -> bool:
        """Post text with its buttons; False when it couldn't, so the caller sends plain text."""
        if not cards or not self.ready():
            return False
        handle = self.ctx.post_message(text)
        chat_id = getattr(getattr(handle, "_target", None), "chat_id", None)
        if not getattr(handle, "ok", False) or not handle.message_id or not _private_chat(chat_id):
            if getattr(handle, "ok", False):
                return True  # the text is out already; just without buttons
            return False
        key = (str(chat_id), str(handle.message_id))
        self.messages[key] = {"cards": list(cards[:FULL_CARDS]), "finished": {}}
        while len(self.messages) > _MAX_MESSAGES:
            self.messages.popitem(last=False)
        try:
            asyncio.run_coroutine_threadsafe(self._set_keyboard(key), self.loop).result(_SEND_TIMEOUT_SECONDS)
        except Exception:
            logger.warning("Cardlake: couldn't add buttons to the feed", exc_info=True)
        return True

    async def _set_keyboard(self, key: tuple[str, str]) -> None:
        state = self.messages[key]
        await self.bot.edit_message_reply_markup(
            chat_id=int(key[0]), message_id=int(key[1]),
            reply_markup=self.markup(keyboard_rows(state["cards"], state["finished"])))

    # Taps ---------------------------------------------------------------------------------------

    async def on_tap(self, update, _context=None) -> None:
        query = update.callback_query
        if query is None or not query.data or query.message is None:
            return
        reply = await self.tap(str(query.message.chat_id), str(query.message.message_id),
                               getattr(query.message.chat, "type", ""), query.data)
        try:
            await query.answer(text=reply or None)
        except Exception:
            logger.debug("Cardlake: couldn't answer a button tap", exc_info=True)

    async def tap(self, chat_id: str, message_id: str, chat_type: str, data: str) -> str:
        """Do what the button says; returns the short note Telegram shows."""
        if data == f"{PREFIX}n":
            return ""
        if chat_type != "private":
            return "Cardlake buttons only work in your private chat with Hermes."
        state = self.messages.get((chat_id, message_id))
        code, _, index = data[len(PREFIX):].partition(":")
        # Only cards this message showed can be changed: a crafted tap can't reach any other card.
        if state is None or not index.isdigit() or int(index) >= len(state["cards"]):
            return "This list is out of date. Run /cardlake feed again."
        i = int(index)
        if i in state["finished"]:
            return f"Already {state['finished'][i].lower()}."
        card = state["cards"][i]
        action = action_for(card, code)
        if action is None:
            return "That button doesn't apply to this card."
        tool, args, said = action
        try:
            await asyncio.to_thread(self.run_tool, tool, args)
        except Exception as exc:
            logger.warning("Cardlake: button %s failed", tool, exc_info=True)
            return f"Couldn't update Cardlake: {exc}"[:190]
        state["finished"][i] = said
        try:
            await self._set_keyboard((chat_id, message_id))
        except Exception:
            logger.debug("Cardlake: couldn't refresh the buttons", exc_info=True)
        return f"{said}: {plain(card.get('title')) or 'Untitled'}"[:190]
