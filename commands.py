"""The /cardlake slash command."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from . import cards as card_logic
from . import feed_view
from .feed_view import OPEN_LINK, local_now, with_open_link
from .redact import redact, redact_text

logger = logging.getLogger(__name__)

SERVER_NAME = "cardlake"
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
CONNECT_COMMAND = "hermes mcp add cardlake --url https://cardlake.app/api/mcp --auth oauth"
USAGE = (
    "Usage:\n"
    "/cardlake feed: show your feed\n"
    "/cardlake today: what's overdue or due today\n"
    "/cardlake save <text>: save text as a card\n"
    "/cardlake snooze <text>: snooze the card that matches"
)
NOT_CONNECTED = (
    "Cardlake isn't connected, so nothing changed. Run this in a terminal, sign in, then start a new session:\n"
    f"{CONNECT_COMMAND}"
)
_TYPE_LABELS = {
    "reminder": "Reminder", "learning": "Learning", "kanban": "GitHub issue", "work": "Work item",
    "family": "Family", "bookmark": "Bookmark", "talking_point": "Misc", "file": "File",
}
_FEED_SIZE = 20
_TODAY_SCAN = 50  # due and overdue reminders come first in the feed's order
_QUERY_LIMIT = 100  # search_cards refuses longer queries


class CardlakeError(Exception):
    """A Cardlake call failed; the message is safe to show the user."""


class NotConnected(CardlakeError):
    pass


def call_cardlake(ctx, tool: str, args: dict) -> Any:
    """The one way out to Cardlake, so nothing can reach it without passing redaction."""
    raw = ctx.dispatch_tool(f"{TOOL_PREFIX}{tool}", redact(args))
    try:
        reply = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if isinstance(reply, dict) and reply.get("error"):
        message = str(reply["error"])
        lowered = message.lower()
        if "unknown tool" in lowered or "not connected" in lowered or "needs_reauth" in lowered:
            raise NotConnected(NOT_CONNECTED)
        raise CardlakeError(message)
    if not isinstance(reply, dict):
        return reply
    if isinstance(reply.get("structuredContent"), dict):
        return reply["structuredContent"]
    result = reply.get("result", reply)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except ValueError:
            return result
    return result


_MAX_REPLY_TOKENS = 4000  # room for models that think before answering
# Hermes gives side requests 30 seconds unless told otherwise, which slower providers,
# such as ones that run a separate program, can need more than.
_MODEL_TIMEOUT_SECONDS = 180.0


def _json_from_text(text: Any) -> Any:
    """The JSON object in a model reply, allowing for fences or a sentence around it."""
    if not isinstance(text, str):
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def _refused_json_mode(error: Exception) -> bool:
    message = str(error).lower()
    return "response_format" in message or "json" in message


def _ask_model(ctx, instructions: str, prompt: str, schema: dict, purpose: str) -> Any:
    """Ask the user's model for JSON. The schema goes in the prompt rather than to the host:
    the host rejects a whole reply over one stray field (a null date, a fourth card), and
    cards.py already keeps only the valid parts. Models whose provider refuses JSON mode
    get a plain request instead."""
    instructions = f"{instructions}\n\nReply with JSON only, in this shape:\n{json.dumps(schema)}"
    blocks = [{"type": "text", "text": prompt}]
    limits = dict(temperature=0.0, max_tokens=_MAX_REPLY_TOKENS, timeout=_MODEL_TIMEOUT_SECONDS)
    try:
        result = ctx.llm.complete_structured(
            instructions=instructions, input=blocks, json_mode=True, purpose=f"cardlake.{purpose}", **limits,
        )
        return result.parsed if result.parsed is not None else _json_from_text(result.text)
    except Exception as error:
        # Only a refused JSON mode is worth a second try; a slow or broken provider would
        # just make the user wait twice as long for the same failure.
        if not _refused_json_mode(error):
            raise
        logger.warning("Cardlake: provider refused JSON mode, retrying as plain text", exc_info=True)
    result = ctx.llm.complete(
        [{"role": "system", "content": instructions}, {"role": "user", "content": prompt}],
        purpose=f"cardlake.{purpose}.plain", **limits,
    )
    return _json_from_text(result.text)


def _feed(ctx, limit: int) -> list[dict]:
    feed = call_cardlake(ctx, "list_feed", {"limit": limit})
    cards = feed.get("cards", []) if isinstance(feed, dict) else []
    return [c for c in cards if isinstance(c, dict)]


def show_feed(ctx) -> str:
    return feed_view.render_feed(_feed(ctx, _FEED_SIZE), local_now())


def today_message(ctx) -> Optional[str]:
    """What's overdue or due today, or None when nothing is."""
    return feed_view.render_today(_feed(ctx, _TODAY_SCAN), local_now())


def show_today(ctx) -> str:
    return today_message(ctx) or with_open_link("Nothing is overdue or due today.")


def _describe(card: dict) -> str:
    return f"{_TYPE_LABELS.get(card.get('type'), 'Card')}: {card.get('title') or 'Untitled'}"


def save(ctx, text: str) -> str:
    if not text:
        return "Usage: /cardlake save <text>"
    text = redact_text(text)
    # Check the connection first: no point paying for a model call that can't be saved.
    call_cardlake(ctx, "list_feed", {"limit": 1})
    try:
        parsed = _ask_model(ctx, card_logic.SAVE_INSTRUCTIONS, card_logic.save_prompt(text, local_now()),
                            card_logic.SAVE_SCHEMA, "save")
    except Exception:
        logger.warning("Cardlake: model call failed, saving as Misc", exc_info=True)
        parsed = None
    card = card_logic.parse_saved(parsed, text)
    tool, args, kind = card_logic.to_tool_call(card)
    call_cardlake(ctx, tool, args)
    return f"Saved. {kind}: {redact_text(card.title)}"


def _is_finished(card: dict) -> bool:
    """Search also returns finished cards, which Cardlake can't snooze."""
    meta = card.get("metadata") or {}
    return bool(
        (card.get("type") == "reminder" and meta.get("completed"))
        or (card.get("type") == "learning" and meta.get("status") in ("watched", "skimmed"))
        or (card.get("type") == "kanban" and meta.get("status") == "done")
    )


def snooze(ctx, text: str) -> str:
    if not text:
        return "Usage: /cardlake snooze <text>"
    found = call_cardlake(ctx, "search_cards", {"query": text[:_QUERY_LIMIT], "limit": _FEED_SIZE})
    matches = [c for c in (found.get("cards", []) if isinstance(found, dict) else []) if not _is_finished(c)]
    if not matches:
        return f'No card in your feed matches "{redact_text(text)}", so nothing was snoozed.'
    card: Optional[dict] = matches[0] if len(matches) == 1 else _choose(ctx, matches)
    if card is None:
        listed = "\n".join(f"- {_describe(c)}" for c in matches)
        return f"More than one card matches, so nothing was snoozed:\n{listed}\nRun it again with more of the title."
    call_cardlake(ctx, "snooze_card", {"card_type": card["type"], "card_id": card["id"]})
    return f"Snoozed until tomorrow. {_describe(card)}"


def _choose(ctx, matches: list[dict]) -> Optional[dict]:
    choices = [{"value": str(i), "label": _describe(c)} for i, c in enumerate(matches)]
    picked = ctx.ask_choice("Which card should I snooze?", choices)
    return matches[int(picked)] if picked is not None else None


def handle(ctx, raw_args: str) -> str:
    verb, _, rest = (raw_args or "").strip().partition(" ")
    verb, rest = verb.lower(), rest.strip()
    try:
        if verb == "feed" and not rest:
            return show_feed(ctx)
        if verb == "today" and not rest:
            return show_today(ctx)
        if verb == "save":
            return with_open_link(save(ctx, rest))
        if verb == "snooze":
            return with_open_link(snooze(ctx, rest))
    except CardlakeError as exc:
        return str(exc)
    except Exception:
        logger.warning("Cardlake: /cardlake %s failed", verb, exc_info=True)
        return "Something went wrong talking to Cardlake. See `hermes logs` for details."
    return USAGE
