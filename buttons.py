"""Telegram buttons: each card shown in full is its own message, with Done, Tomorrow and Next week
right under it, so there's no doubt which card a button changes.

Hermes sends a command's reply as plain text, so these messages are posted by the plugin itself
(ctx.post_message, which only ever reaches the chat that ran the command) and then given their
buttons. Anywhere that doesn't work, such as an older Hermes, another platform or a group chat,
the reply goes out as one ordinary message, exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Optional

from .feed_view import OPEN_LINK, plain

logger = logging.getLogger(__name__)

PREFIX = "clk:"
_SEND_TIMEOUT_SECONDS = 15
_MAX_MESSAGES = 150  # older messages' buttons say they're out of date

# What each button does: (Cardlake tool, its arguments, what the user is told).
_ACTIONS: dict[str, Callable[[dict], tuple[str, dict, str]]] = {
    "t": lambda c: ("snooze_card", {"card_type": c["type"], "card_id": c["id"], "days": 1}, "Snoozed until tomorrow"),
    "w": lambda c: ("snooze_card", {"card_type": c["type"], "card_id": c["id"], "days": 7}, "Snoozed for a week"),
}
_OPEN_ROW = [{"text": "🔗 Open Cardlake", "url": OPEN_LINK}]


def _done(card: dict) -> Optional[tuple[str, dict, str]]:
    """Only reminders and learnings have a 'done'."""
    if card.get("type") == "reminder":
        return "update_reminder", {"id": card["id"], "completed": True}, "Done"
    if card.get("type") == "learning":
        return "update_learning", {"id": card["id"], "status": "watched"}, "Marked as watched"
    return None


def action_for(card: dict, code: str) -> Optional[tuple[str, dict, str]]:
    if not card.get("id") or not card.get("type"):
        return None
    if code == "d":
        return _done(card)
    make = _ACTIONS.get(code)
    return make(card) if make else None


def keyboard_rows(card: Optional[dict], result: Optional[str] = None, last: bool = False) -> list[list[dict]]:
    """Rows of {"text", "callback_data" | "url"} for one message: the card's actions (or, once one
    was used, what happened), and on the last message the link to Cardlake."""
    rows = []
    if card is not None and card.get("id") and card.get("type"):
        if result:
            rows.append([{"text": f"✓ {result}", "callback_data": f"{PREFIX}n"}])
        else:
            row = [{"text": "✅ Done", "callback_data": f"{PREFIX}d"}] if _done(card) else []
            row += [{"text": "⏰ Tomorrow", "callback_data": f"{PREFIX}t"},
                    {"text": "📅 Next week", "callback_data": f"{PREFIX}w"}]
            rows.append(row)
    if last:
        rows.append(_OPEN_ROW)
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
        # (chat id, message id) -> {"card": the card it shows or None, "result": what a tap did, "last": bool}
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

    def send(self, whole: str, parts: list[tuple[str, Optional[dict]]]) -> bool:
        """Post the parts, each with its buttons. False when nothing was posted, so the caller sends
        `whole` as plain text instead. In a group chat the first post becomes `whole`, unbuttoned."""
        if not parts or not self.ready():
            return False
        first = self.ctx.post_message(parts[0][0])
        if not getattr(first, "ok", False) or not first.message_id:
            return False
        chat_id = getattr(getattr(first, "_target", None), "chat_id", None)
        if not _private_chat(chat_id):
            first.edit(whole)
            return True
        for i, (text, card) in enumerate(parts):
            handle = first if i == 0 else self.ctx.post_message(text)
            if not getattr(handle, "ok", False) or not handle.message_id:
                logger.warning("Cardlake: stopped posting the feed after %d of %d messages", i, len(parts))
                break
            key = (str(chat_id), str(handle.message_id))
            self.messages[key] = {"card": card, "result": None, "last": i == len(parts) - 1}
            while len(self.messages) > _MAX_MESSAGES:
                self.messages.popitem(last=False)
            try:
                asyncio.run_coroutine_threadsafe(self._set_keyboard(key), self.loop).result(_SEND_TIMEOUT_SECONDS)
            except Exception:
                logger.warning("Cardlake: couldn't add buttons to a card", exc_info=True)
        return True

    async def _set_keyboard(self, key: tuple[str, str]) -> None:
        state = self.messages[key]
        rows = keyboard_rows(state["card"], state["result"], state["last"])
        if rows:
            await self.bot.edit_message_reply_markup(
                chat_id=int(key[0]), message_id=int(key[1]), reply_markup=self.markup(rows))

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
        # A tap only reaches the card its own message shows: crafted button data can't name another.
        state = self.messages.get((chat_id, message_id))
        if state is None or state["card"] is None:
            return "These buttons are out of date. Run /cardlake feed again."
        if state["result"]:
            return f"Already {state['result'].lower()}."
        card = state["card"]
        action = action_for(card, data[len(PREFIX):])
        if action is None:
            return "That button doesn't apply to this card."
        tool, args, said = action
        try:
            await asyncio.to_thread(self.run_tool, tool, args)
        except Exception as exc:
            logger.warning("Cardlake: button %s failed", tool, exc_info=True)
            return f"Couldn't update Cardlake: {exc}"[:190]
        state["result"] = said
        try:
            await self._set_keyboard((chat_id, message_id))
        except Exception:
            logger.debug("Cardlake: couldn't refresh the buttons", exc_info=True)
        return f"{said}: {plain(card.get('title')) or 'Untitled'}"[:190]
