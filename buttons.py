"""Cards in Telegram with buttons: each card shown in full is its own message, with Done, Tomorrow
and Next week right under it, so there's no doubt which card a button changes.

Hermes sends a reply as one plain message, so these messages are sent by the plugin itself, through
the Telegram bot Hermes hands to plugins, to the chat that ran the command (or, for the morning
message, the chat Hermes delivers it to). Sending them here also lets each message choose its own
link preview and lets Today's checklist be pinned. Anywhere that doesn't work, such as an older
Hermes, another platform, a group chat or a forum topic, the reply goes out as one ordinary message,
exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import feed_view, menu, show
from .address import _hermes_config
from .address import open_link
from .feed_view import plain

logger = logging.getLogger(__name__)

PREFIX = "clk:"
_SEND_TIMEOUT_SECONDS = 60
_MAX_RETRY_WAIT_SECONDS = 10  # Telegram asks a fast sender to wait; longer than this isn't worth it
_MAX_MESSAGES = 300  # older messages' buttons say they're out of date
_PINNED_KEY = "pinned_today"  # chat id -> message id of the Today checklist the plugin pinned

Call = tuple[str, dict]
CREATED = "$created"  # in an Undo step: the id of the card the tap created


# What the buttons do ------------------------------------------------------------------------------

def _due_value(card: dict) -> Optional[str]:
    """The card's due date the way update_reminder takes it, to put back on Undo."""
    raw = str((card.get("metadata") or {}).get("due_date") or "")
    if not raw:
        return None
    try:
        due = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if (due.hour, due.minute, due.second, due.microsecond) == (0, 0, 0, 0):
        return due.date().isoformat()  # an all-day date
    return due.isoformat()


def _days_left(card: dict) -> int:
    """Whole days until a snoozed card was due back (at least 1), to snooze it again on Undo."""
    try:
        raw = card.get("remind_later_until") or card.get("snoozed_until") or ""
        until = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return 1
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    seconds = (until - datetime.now(timezone.utc)).total_seconds()
    return min(365, max(1, -int(-seconds // 86400)))  # rounded up


def _keep_pin(card: dict) -> list[Call]:
    """Snoozing or finishing a card unpins it in Cardlake, so Undo pins it again."""
    ref = {"card_type": card["type"], "card_id": card["id"]}
    return [("pin_card", ref)] if card.get("pinned_at") else []


def action_for(card: dict, code: str) -> Optional[tuple[Call, str, list[Call]]]:
    """(the change, what the user is told, how to undo it), or None when the button doesn't apply."""
    if not card.get("id") or not card.get("type"):
        return None
    if card.get("_shown"):
        # Something Hermes showed, not yet in Cardlake: save it, or make it tomorrow's reminder.
        # Undo deletes what the tap created ("$created" is filled in with its id).
        if code == "s":
            create, args, delete, saved_as = show.save_call(card)
            return (create, args), f"Saved as {saved_as}", [(delete, {"id": CREATED})]
        if code == "r":
            create, args = show.remind_call(card)
            return (create, args), "Reminder for tomorrow", [("delete_reminder", {"id": CREATED})]
        return None
    ref = {"card_type": card["type"], "card_id": card["id"]}
    if card.get("_snoozed"):
        # In the snoozed list the only button is Bring back; Undo snoozes it again until its day.
        if code != "b":
            return None
        return ("unsnooze_card", ref), "Back in your feed", [("snooze_card", {**ref, "days": _days_left(card)})]
    if code in ("t", "w"):
        days = 1 if code == "t" else 7
        said = "Snoozed until tomorrow" if days == 1 else "Snoozed for a week"
        return ("snooze_card", {**ref, "days": days}), said, [("unsnooze_card", ref)] + _keep_pin(card)
    if code == "d" and card["type"] == "reminder":
        meta = card.get("metadata") or {}
        restore = {"id": card["id"], "completed": False}
        if _due_value(card):
            restore["due_date"] = _due_value(card)
        undo: list[Call] = [("update_reminder", restore)]
        if meta.get("recurrence") not in (None, "", "none"):
            undo.append(("unsnooze_card", ref))  # a repeating reminder moves on and is snoozed
        return ("update_reminder", {"id": card["id"], "completed": True}), "Done", undo + _keep_pin(card)
    if code == "d" and card["type"] == "learning":
        before = (card.get("metadata") or {}).get("status") or "saved"
        undo = [("update_learning", {"id": card["id"], "status": before})] + _keep_pin(card)
        return ("update_learning", {"id": card["id"], "status": "watched"}), "Marked as watched", undo
    return None


def _fill_created(undo: list[Call], result: Any) -> list[Call]:
    """Put the new card's id into the Undo steps; with no id there's nothing safe to undo."""
    if not any(CREATED in args.values() for _, args in undo):
        return undo
    new_id = show.created_id(result)
    if not new_id:
        return []
    return [(tool, {k: (new_id if v == CREATED else v) for k, v in args.items()}) for tool, args in undo]


def has_done(card: dict) -> bool:
    return action_for(card, "d") is not None


def _open_row() -> list[dict]:
    return [{"text": "🔗 Open Cardlake", "url": open_link()}]


def keyboard_rows(card: Optional[dict], result: Optional[str] = None, last: bool = False,
                  can_undo: bool = True) -> list[list[dict]]:
    """Rows of {"text", "callback_data" | "url"} for one message: the card's actions, or once one was
    used, what happened and Undo; on the last message, the link to Cardlake."""
    rows = []
    if card is not None and card.get("id") and card.get("type"):
        if result:
            row = [{"text": f"✓ {result}", "callback_data": f"{PREFIX}n"}]
            if can_undo:
                row.append({"text": "↩ Undo", "callback_data": f"{PREFIX}u"})
            rows.append(row)
        elif card.get("_shown"):
            rows.append([{"text": "💾 Save to Cardlake", "callback_data": f"{PREFIX}s"},
                         {"text": "⏰ Remind me", "callback_data": f"{PREFIX}r"}])
        elif card.get("_snoozed"):
            rows.append([{"text": "↩ Bring back", "callback_data": f"{PREFIX}b"}])
        else:
            row = [{"text": "✅ Done", "callback_data": f"{PREFIX}d"}] if has_done(card) else []
            row += [{"text": "⏰ Tomorrow", "callback_data": f"{PREFIX}t"},
                    {"text": "📅 Next week", "callback_data": f"{PREFIX}w"}]
            rows.append(row)
    if last:
        rows.append(_open_row())
    return rows


def _private_chat(chat_id: Any) -> bool:
    """Telegram gives private chats positive ids and groups negative ones. Buttons only go to private
    chats, where the only person who can tap them is the one they were sent to."""
    try:
        return int(chat_id) > 0
    except (TypeError, ValueError):
        return False


def _session_env(name: str) -> str:
    from gateway.session_context import get_session_env
    return get_session_env(name, "") or ""


def _formatting_refused(error: Exception) -> bool:
    """Telegram refused the message's formatting (a Bad Request), as opposed to a network error,
    where the message may have arrived and sending it again would show it twice."""
    return type(error).__name__ == "BadRequest" or "can't parse entities" in str(error).lower()


def _retry_wait(error: Exception) -> Optional[float]:
    """Seconds Telegram asked us to wait before sending again (RetryAfter), or None."""
    wait = getattr(error, "retry_after", None)
    seconds = getattr(wait, "total_seconds", lambda: wait)()
    return float(seconds) if isinstance(seconds, (int, float)) and seconds <= _MAX_RETRY_WAIT_SECONDS else None


def _plain_text(markdown: str) -> str:
    """The message without Markdown, for when Telegram refuses the formatted version."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", markdown)
    return text.replace("**", "").replace("> ", "")


# The sender -------------------------------------------------------------------------------------

class TelegramCards:
    def __init__(self, ctx, run_tool: Callable[[str, dict], Any], session_env: Callable[[str], str] = _session_env,
                 load_config: Callable[[], Any] = _hermes_config):
        """run_tool(tool, args) calls Cardlake (with redaction) and raises on failure."""
        self.ctx = ctx
        self.run_tool = run_tool
        self.session_env = session_env
        self.bot = None
        self.format: Optional[Callable[[str], str]] = None  # Hermes' Markdown -> Telegram formatting
        self.markup: Optional[Callable[[list], Any]] = None  # rows of dicts -> Telegram keyboard
        self.preview: Optional[Callable[[str], Any]] = None  # url ('' for none) -> link preview options
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        # (chat id, message id) -> {"card", "result", "undo", "last", "batch"}
        self.messages: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
        # Today checklists: batch id -> {"chat", "message", "cards", "results", "now"}
        self.batches: dict[int, dict] = {}
        self._next_batch = 0
        self.load_config = load_config
        self._menu_task: Optional[asyncio.Task] = None

    # Wiring -------------------------------------------------------------------------------------

    def attach(self, native, adapter=None) -> None:
        """Hermes calls this when Telegram connects, with python-telegram-bot's Application."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
        from telegram.ext import CallbackQueryHandler
        self.markup = lambda rows: InlineKeyboardMarkup([[InlineKeyboardButton(**b) for b in row] for row in rows])
        self.preview = lambda url: (LinkPreviewOptions(url=url, prefer_large_media=True) if url
                                    else LinkPreviewOptions(is_disabled=True))
        self.format = getattr(adapter, "format_message", None)
        self.bot = native.bot
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        # Scoped to our prefix: Hermes' own buttons keep working.
        native.add_handler(CallbackQueryHandler(self.on_tap, pattern=f"^{PREFIX}"))
        try:
            self._keep_in_menu(native.bot)
        except Exception:
            logger.debug("Cardlake: couldn't start the command menu check", exc_info=True)

    def _keep_in_menu(self, bot) -> None:
        """Puts /cardlake in Telegram's / menu after each connect (see menu.py)."""
        if self.loop is None or menu.menu_is_users(self.load_config):
            return
        from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeDefault
        if self._menu_task is not None:
            self._menu_task.cancel()
        scopes = [BotCommandScopeDefault(), BotCommandScopeAllPrivateChats(), BotCommandScopeAllGroupChats()]
        self._menu_task = self.loop.create_task(
            menu.keep_in_menu(bot, scopes, lambda: BotCommand(menu.COMMAND, menu.DESCRIPTION)))

    def chat(self) -> Optional[str]:
        """The private Telegram chat this reply goes to, or None to send plain text instead."""
        if None in (self.bot, self.markup, self.format, self.preview, self.loop) or self.loop.is_closed():
            return None
        try:
            if self.session_env("HERMES_SESSION_PLATFORM") == "telegram":
                chat, thread = self.session_env("HERMES_SESSION_CHAT_ID"), self.session_env("HERMES_SESSION_THREAD_ID")
            elif self.session_env("HERMES_CRON_AUTO_DELIVER_PLATFORM") == "telegram":
                chat = self.session_env("HERMES_CRON_AUTO_DELIVER_CHAT_ID")
                thread = self.session_env("HERMES_CRON_AUTO_DELIVER_THREAD_ID")
            else:
                return None
        except Exception:
            logger.debug("Cardlake: couldn't tell which chat this is", exc_info=True)
            return None
        # Forum topics need Hermes' own routing; one plain message gets that right.
        return str(chat) if _private_chat(chat) and not thread else None

    # Sending ------------------------------------------------------------------------------------

    def send(self, parts: list[tuple[str, Optional[dict]]], today: Optional[tuple[list[dict], datetime]] = None) -> bool:
        """Send the parts, each card with its buttons; with `today`, a pinned checklist goes first.
        False when nothing could be sent here, so the caller sends one plain message instead."""
        chat = self.chat()
        if not parts or chat is None:
            return False
        future = asyncio.run_coroutine_threadsafe(self._send(chat, parts, today), self.loop)
        try:
            return future.result(_SEND_TIMEOUT_SECONDS)
        except Exception:
            # Stop it, or it could carry on sending cards after the plain reply went out too.
            future.cancel()
            logger.warning("Cardlake: sending cards to Telegram failed", exc_info=True)
            return False

    async def _send(self, chat: str, parts, today) -> bool:
        batch = None
        if today is not None:
            cards, now = today
            batch = self._new_batch(chat, cards, now)
            text = feed_view.checklist(cards, now, {})
            try:
                batch["message"] = await self._post(chat, text, [])
            except Exception:
                logger.warning("Cardlake: couldn't send Today's checklist", exc_info=True)
                return False
            await self._pin(chat, batch["message"])
        sent = 0
        for i, (text, card) in enumerate(parts):
            last = i == len(parts) - 1
            try:
                message = await self._post(chat, text, keyboard_rows(card, last=last),
                                            feed_view.video_url(card) if card else "")
            except Exception:
                logger.warning("Cardlake: stopped after %d of %d messages", i, len(parts), exc_info=True)
                break
            sent += 1
            self._remember((chat, str(message)), {"card": card, "result": None, "undo": [], "last": last,
                                                  "batch": batch["id"] if batch else None})
        return sent > 0 or batch is not None

    async def _post(self, chat: str, text: str, rows: list, video: str = "") -> int:
        markup = self.markup(rows) if rows else None
        formatted = dict(text=self.format(text), parse_mode="MarkdownV2")
        try:
            message = await self._send_once(chat, formatted, markup, video)
        except Exception as error:
            if not _formatting_refused(error):
                raise
            logger.warning("Cardlake: Telegram refused the formatting, sending plain text", exc_info=True)
            message = await self._send_once(chat, dict(text=_plain_text(text)), markup, video)
        return message.message_id

    async def _send_once(self, chat: str, content: dict, markup, video: str):
        """One message, waiting once if Telegram says we're sending too fast (a long Today can be
        seven messages in a row)."""
        send = lambda: self.bot.send_message(chat_id=int(chat), reply_markup=markup,
                                             link_preview_options=self.preview(video), **content)
        try:
            return await send()
        except Exception as error:
            wait = _retry_wait(error)
            if wait is None:
                raise
            await asyncio.sleep(wait)
            return await send()

    async def _edit(self, chat: str, message: int, text: str) -> None:
        try:
            await self.bot.edit_message_text(chat_id=int(chat), message_id=int(message), text=self.format(text),
                                             parse_mode="MarkdownV2", link_preview_options=self.preview(""))
        except Exception:
            logger.debug("Cardlake: couldn't update Today's checklist", exc_info=True)

    async def _pin(self, chat: str, message: int) -> None:
        """Pin today's checklist in place of yesterday's (only ever one the plugin pinned itself)."""
        pinned = dict(self._state_get(_PINNED_KEY) or {})
        try:
            previous = pinned.get(chat)
            if previous:
                try:
                    await self.bot.unpin_chat_message(chat_id=int(chat), message_id=int(previous))
                except Exception:
                    logger.debug("Cardlake: yesterday's checklist was already unpinned", exc_info=True)
            await self.bot.pin_chat_message(chat_id=int(chat), message_id=int(message), disable_notification=True)
        except Exception:
            logger.warning("Cardlake: couldn't pin Today's checklist", exc_info=True)
            return
        pinned[chat] = int(message)
        self._state_set(_PINNED_KEY, pinned)

    def _state_get(self, key: str):
        try:
            return self.ctx.state.get(key)
        except Exception:
            return None

    def _state_set(self, key: str, value) -> None:
        try:
            self.ctx.state.set(key, value)
        except Exception:
            logger.debug("Cardlake: couldn't save %s", key, exc_info=True)

    def _new_batch(self, chat: str, cards: list[dict], now: datetime) -> dict:
        self._next_batch += 1
        batch = {"id": self._next_batch, "chat": chat, "message": None, "cards": list(cards), "results": {}, "now": now}
        self.batches[batch["id"]] = batch
        for old in sorted(self.batches)[:-20]:  # keep the last few days' worth
            self.batches.pop(old, None)
        return batch

    def _remember(self, key: tuple[str, str], state: dict) -> None:
        self.messages[key] = state
        while len(self.messages) > _MAX_MESSAGES:
            self.messages.popitem(last=False)

    async def _set_keyboard(self, key: tuple[str, str]) -> None:
        state = self.messages[key]
        rows = keyboard_rows(state["card"], state["result"], state["last"], bool(state["undo"]))
        await self.bot.edit_message_reply_markup(
            chat_id=int(key[0]), message_id=int(key[1]), reply_markup=self.markup(rows) if rows else None)

    async def _update_checklist(self, state: dict) -> None:
        batch = self.batches.get(state.get("batch"))
        if not batch or not batch["message"]:
            return
        card_id = str(state["card"]["id"])
        if state["result"]:
            batch["results"][card_id] = state["result"]
        else:
            batch["results"].pop(card_id, None)
        await self._edit(batch["chat"], batch["message"], feed_view.checklist(batch["cards"], batch["now"], batch["results"]))

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
        code = data[len(PREFIX):]
        if code == "n":
            return ""
        if chat_type != "private":
            return "Cardlake buttons only work in your private chat with Hermes."
        # A tap only reaches the card its own message shows: crafted button data can't name another.
        key = (chat_id, message_id)
        state = self.messages.get(key)
        if state is None or state["card"] is None:
            return "These buttons are out of date. Run /cardlake feed again."
        card = state["card"]
        title = plain(card.get("title")) or "Untitled"
        # A second tap while the first is still talking to Cardlake would do it twice: two saved
        # cards, of which Undo only removes one.
        if state.get("busy"):
            return "Still working on the last tap…"
        state["busy"] = True
        try:
            return await self._tap(key, state, card, title, code)
        finally:
            state["busy"] = False

    async def _tap(self, key, state: dict, card: dict, title: str, code: str) -> str:
        if code == "u":
            return await self._undo(key, state, title)
        if state["result"]:
            return f"Already {state['result'].lower()}."
        action = action_for(card, code)
        if action is None:
            return "That button doesn't apply to this card."
        (tool, args), said, undo = action
        try:
            result = await asyncio.to_thread(self.run_tool, tool, args)
        except Exception as exc:
            logger.warning("Cardlake: button %s failed", tool, exc_info=True)
            return f"Couldn't update Cardlake: {exc}"[:190]
        state["result"], state["undo"] = said, _fill_created(undo, result)
        await self._after_change(key, state)
        return f"{said}: {title}"[:190]

    async def _undo(self, key, state: dict, title: str) -> str:
        if not state["result"]:
            return "Nothing to undo."
        for tool, args in state["undo"]:
            try:
                await asyncio.to_thread(self.run_tool, tool, args)
            except Exception as exc:
                logger.warning("Cardlake: undo step %s failed", tool, exc_info=True)
                return f"Couldn't fully undo: {exc}"[:190]
        state["result"], state["undo"] = None, []
        await self._after_change(key, state)
        return f"Undone: {title}"[:190]

    async def _after_change(self, key, state: dict) -> None:
        try:
            await self._set_keyboard(key)
        except Exception:
            logger.debug("Cardlake: couldn't refresh the buttons", exc_info=True)
        await self._update_checklist(state)
