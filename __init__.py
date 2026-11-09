"""Cardlake for Hermes Agent: your Cardlake cards in chat, laid out to suit Telegram."""

from __future__ import annotations

import json
import logging
from collections import OrderedDict

from . import show
from .buttons import TelegramCards
from .address import SERVER_NAME
from .commands import OPEN_LINK, TOOL_PREFIX, call_cardlake, handle, send_with_buttons, today_reply
from .feed_view import with_open_link

logger = logging.getLogger(__name__)

MORNING_TITLE = "Cardlake morning"
TODAY_TOOL = "cardlake_today"
# Never the connection's own name (SERVER_NAME, "cardlake"): Hermes resolves a name to a plugin's
# toolset before an MCP server's alias, so a plugin toolset called "cardlake" hid every Cardlake
# tool from the model, and replies like "done" and forwarded links had nothing to save with.
TOOLSET = "cardlake-plugin"
assert TOOLSET != SERVER_NAME

# Blueprint text goes through str.format, so it holds no literal braces.
MORNING_PROMPT = (
    f"Call the {TODAY_TOOL} tool once. Reply with exactly the text it returns, unchanged: do not add, remove or "
    "reword anything. If it returns [SILENT], reply with only [SILENT] and nothing else. If it returns an error, "
    "reply with one short sentence saying Cardlake couldn't be reached. Do not call any other tool and do not "
    "change any Cardlake card."
)

# Frozen into each new session's instructions. It only shapes how cards look and what short
# replies mean; it never asks Hermes to read past chats or act without the user.
CHAT_GUIDE = f"""When you show Cardlake cards in a reply, lay each one out as a quote block, which Telegram shows as a card:
> 🔔 **Reminder** · ⚠️ overdue 3 days
> **The card's title**
> [example.com](the card's url, if it has one)
Use 🔔 Reminder, 📚 Learning, 💼 Work item, 👪 Family, 🔖 Bookmark, 💬 Misc, 🗂 GitHub issue, 📎 File. Put a blank line between cards. Show at most 3 cards this way and list any others one per line. Never draw boxes or ASCII art. End the reply with: Open Cardlake: {OPEN_LINK}

Cardlake's own tools are named {TOOL_PREFIX}… (list_feed, search_cards, create_learning, create_bookmark, create_reminder, create_talking_point, update_reminder, update_learning, snooze_card). If they aren't in your tool list, find them with tool_search "cardlake"; never look for them in files or the terminal.

When the user answers a Cardlake card or names one with "done", "tomorrow", "next week" or "snooze", find it with search_cards and update it: done marks a reminder completed or a learning watched, tomorrow and snooze snooze it for 1 day, next week for 7. If more than one card matches, ask which. Then confirm in one line.

When the user forwards a link or message, or sends a voice note, and asks for nothing else, save it to Cardlake as one card: a link to an article, video or course as a learning, any other link as a bookmark, something with a date as a reminder, anything else as a Misc card. Then say in one line what you saved. Never delete a card unless the user asks.

When your answer is a set of separate items, such as links or videos you found, findings, options, tasks or a scheduled job's results, show them with the {show.SHOW_TOOL} tool instead of writing them out: the user gets each as a card they can save to Cardlake. Ordinary conversation stays as text."""

# Reading is harmless. Anything else, including tools Cardlake adds later, counts as a change.
_READ_ONLY_TOOLS = frozenset(
    TOOL_PREFIX + name
    for name in ("list_feed", "search_cards", "get_card", "get_account", "get_dashboard_stats", "list_integrations")
)
_BLOCK = {
    "action": "block",
    "message": "The Cardlake morning message only shows cards; it can't change them.",
}

TODAY_SCHEMA = {
    "name": TODAY_TOOL,
    "description": (
        "Today's Cardlake message: the user's reminders that are overdue or due today, laid out as cards, "
        "ready to send as-is. Returns [SILENT] when nothing is overdue or due today. Read-only."
    ),
    "parameters": {"type": "object", "properties": {}},
}


def block_morning_changes(ctx, tool_name: str = "", **_kwargs):
    """The morning job runs unattended, so it may read cards but never change them."""
    if not tool_name.startswith(TOOL_PREFIX) or tool_name in _READ_ONLY_TOOLS:
        return None
    run = ctx.current_cron_execution()
    return _BLOCK if run is not None and run.job_name == MORNING_TITLE else None


def today_tool(ctx, args: dict, buttons=None, **_kwargs) -> str:
    """Laid out here rather than by the model, so the message looks the same every morning. In
    Telegram the plugin sends it itself, as cards with buttons under a pinned checklist, and the job
    then has nothing left to say."""
    try:
        reply = today_reply(ctx)
        if reply is None or send_with_buttons(buttons, reply):
            return json.dumps({"text": "[SILENT]"})
        return json.dumps({"text": reply.text})
    except Exception as exc:  # a tool handler must answer, never raise
        logger.warning("Cardlake: today's message failed", exc_info=True)
        return json.dumps({"error": f"Cardlake couldn't be reached: {exc}"})


# Conversations whose next reply follows a Cardlake tool call, so only those replies get the link.
# Keyed by conversation, not turn: the reply hook's turn id isn't promised to match the tool hook's.
# Bounded, because a turn that never produces a reply (an interrupt) is never removed.
_TURNS_USING_CARDLAKE: "OrderedDict[str, None]" = OrderedDict()
_MAX_TRACKED_TURNS = 200


def _turn_key(session_id: str = "", **_kwargs) -> str:
    return session_id or ""


def note_cardlake_use(tool_name: str = "", **kwargs) -> None:
    if not (tool_name.startswith(TOOL_PREFIX) or tool_name == TODAY_TOOL):
        return
    _TURNS_USING_CARDLAKE[_turn_key(**kwargs)] = None
    while len(_TURNS_USING_CARDLAKE) > _MAX_TRACKED_TURNS:
        _TURNS_USING_CARDLAKE.popitem(last=False)


def add_open_link(response_text: str = "", **kwargs):
    """Cardlake is visual and a chat reply isn't, so a reply about cards ends with the way to see them.
    Append-only, so a streamed reply just gains a last line."""
    if _TURNS_USING_CARDLAKE.pop(_turn_key(**kwargs), "missing") == "missing":
        return None
    if OPEN_LINK in response_text or response_text.strip() == "[SILENT]":
        return None
    return with_open_link(response_text)


def _optional(what: str, register_fn) -> None:
    """Hermes turns off the whole plugin if register() raises, and older Hermes versions lack some
    of these features. So each extra is skipped on its own and the commands still load."""
    try:
        register_fn()
    except Exception:
        logger.warning("Cardlake: skipped %s; this Hermes version may not support it", what, exc_info=True)


def register(ctx) -> None:
    buttons = TelegramCards(ctx, lambda tool, args: call_cardlake(ctx, tool, args))
    ctx.register_command(
        "cardlake", lambda raw_args: handle(ctx, raw_args, buttons),
        description="See your Cardlake feed and what's due, get five cards to look at again, save a card, or snooze one",
        args_hint="feed [filter]|today|deal|save <text>|snooze <text>",
    )
    # The guard comes before the morning job that it protects, and the job is skipped if the guard is.
    try:
        ctx.register_hook("pre_tool_call", lambda **kwargs: block_morning_changes(ctx, **kwargs))
    except Exception:
        logger.warning("Cardlake: skipped the morning message, its guard couldn't be added", exc_info=True)
        guarded = False
    else:
        guarded = True
    _optional("the open-Cardlake link", lambda: (
        ctx.register_hook("post_tool_call", note_cardlake_use),
        ctx.register_hook("transform_llm_output", add_open_link),
    ))
    _optional("Telegram buttons", lambda: ctx.register_telegram_handler(buttons.attach))
    _optional("the show-cards tool", lambda: ctx.register_tool(
        name=show.SHOW_TOOL, toolset=TOOLSET, schema=show.SHOW_SCHEMA,
        handler=lambda args, **kwargs: show.show_tool(buttons, args),
        description=show.SHOW_SCHEMA["description"], emoji="🃏",
    ))
    _optional("the chat guide", lambda: ctx.register_system_prompt_section("cardlake", CHAT_GUIDE))
    if guarded:
        _optional("the morning message", lambda: _register_morning(ctx, buttons))


def _register_morning(ctx, buttons=None) -> None:
    ctx.register_tool(
        name=TODAY_TOOL, toolset=TOOLSET, schema=TODAY_SCHEMA,
        handler=lambda args, **kwargs: today_tool(ctx, args, buttons, **kwargs),
        description=TODAY_SCHEMA["description"], emoji="☀️",
    )
    ctx.register_automation_blueprint(
        "morning",
        title=MORNING_TITLE,
        description="Each morning, your reminders that are overdue or due today, as cards. Sends nothing when "
                    "nothing is due, and never changes cards.",
        category="daily",
        schedule_template="{minute} {hour} * * *",
        prompt_template=MORNING_PROMPT,
        slots=[
            {"name": "time", "type": "time", "label": "What time?", "default": "08:00"},
            {"name": "deliver", "type": "text", "label": "Where to send it?", "default": "telegram",
             "help": "telegram sends to your Telegram home channel; or use any connected platform name."},
        ],
        deliver_default="telegram",
        tags=["cardlake", "reminders"],
    )
