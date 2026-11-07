"""The /cardlake slash command."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from . import cards as card_logic
from .conversations import local_now, period_window, read_conversations
from .redact import redact, redact_text

logger = logging.getLogger(__name__)

SERVER_NAME = "cardlake"
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
CONNECT_COMMAND = "hermes mcp add cardlake --url https://cardlake.app/api/mcp --auth oauth"
USAGE = (
    "Usage:\n"
    "/cardlake today | yesterday | week: add up to 3 cards from that period's conversations\n"
    "/cardlake feed: show your feed\n"
    "/cardlake save <text>: save text as a card\n"
    "/cardlake snooze <text>: snooze the card that matches"
)
NOT_CONNECTED = (
    "Cardlake isn't connected, so nothing changed. Run this in a terminal, sign in, then start a new session:\n"
    f"{CONNECT_COMMAND}"
)
_PERIOD_LABELS = {"today": "today's", "yesterday": "yesterday's", "week": "the past week's"}
_TYPE_LABELS = {
    "reminder": "Reminder", "learning": "Learning", "kanban": "GitHub issue", "work": "Work item",
    "family": "Family", "bookmark": "Bookmark", "talking_point": "Misc", "file": "File",
}
_FEED_SIZE = 10
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


def _ask_model(ctx, instructions: str, prompt: str, schema: dict, purpose: str) -> Any:
    result = ctx.llm.complete_structured(
        instructions=instructions, input=[{"type": "text", "text": prompt}], json_schema=schema,
        temperature=0.0, max_tokens=1000, purpose=f"cardlake.{purpose}",
    )
    return result.parsed


def _already_added(ctx, title: str) -> bool:
    """Running /cardlake today twice shouldn't add the same card twice."""
    found = call_cardlake(ctx, "search_cards", {"query": title[:_QUERY_LIMIT], "limit": 10})
    cards = found.get("cards", []) if isinstance(found, dict) else []
    return any(str(card.get("title", "")).strip().casefold() == redact_text(title).strip().casefold() for card in cards)


def add_from_period(ctx, period: str) -> str:
    label = _PERIOD_LABELS[period]
    now = local_now()
    start, end = period_window(period, now)
    try:
        batch = read_conversations(start, end)
    except Exception:
        logger.warning("Cardlake: couldn't read conversations", exc_info=True)
        return "Couldn't read your Hermes conversations, so nothing was added."
    if not batch.conversations:
        return f"No Hermes conversations in {label} window, so nothing was added."

    # Check the connection first: no point paying for a model call that can't be saved.
    call_cardlake(ctx, "list_feed", {"limit": 1})
    try:
        parsed = _ask_model(
            ctx, card_logic.PICK_INSTRUCTIONS, card_logic.pick_prompt(batch.conversations, now),
            card_logic.PICK_SCHEMA, f"pick.{period}",
        )
    except Exception:
        logger.warning("Cardlake: model call failed", exc_info=True)
        return "Couldn't reach your model to read the conversations, so nothing was added."
    picked = card_logic.parse_picked(parsed, batch.conversations)
    if not picked:
        return f"Nothing useful in {label} conversations, so nothing was added."
    return _add_cards(ctx, picked, label, batch.trimmed)


def _add_cards(ctx, picked: list[card_logic.Card], label: str, trimmed: bool) -> str:
    added, skipped, failed = [], [], []
    for card in picked:
        tool, args, kind = card_logic.to_tool_call(card)
        title = redact_text(card.title)
        line = f'{kind}: {title} (from "{card.source}")'
        try:
            if _already_added(ctx, card.title):
                skipped.append(title)
                continue
            call_cardlake(ctx, tool, args)
            added.append(line)
        except NotConnected:
            raise
        except CardlakeError as exc:
            failed.append(f"{title}: {exc}")

    sections = []
    if added:
        sections.append(f"Added {len(added)} from {label} conversations:\n" + "\n".join(f"- {x}" for x in added))
    if skipped:
        sections.append("Already in Cardlake, so not added again:\n" + "\n".join(f"- {x}" for x in skipped))
    if failed:
        sections.append("Couldn't add:\n" + "\n".join(f"- {x}" for x in failed))
    if trimmed:
        sections.append("That was a lot of conversation, so I only read the most recent part of the longest ones.")
    return "\n\n".join(sections)


def show_feed(ctx) -> str:
    feed = call_cardlake(ctx, "list_feed", {"limit": _FEED_SIZE})
    cards = feed.get("cards", []) if isinstance(feed, dict) else []
    if not cards:
        return "Your Cardlake feed is empty."
    return "Your Cardlake feed:\n" + "\n".join(f"- {_describe(card)}" for card in cards)


def _describe(card: dict) -> str:
    return f"{_TYPE_LABELS.get(card.get('type'), 'Card')}: {card.get('title') or 'Untitled'}"


def save(ctx, text: str) -> str:
    if not text:
        return "Usage: /cardlake save <text>"
    text = redact_text(text)
    # Check the connection first, as in add_from_period.
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
        if verb in _PERIOD_LABELS and not rest:
            return add_from_period(ctx, verb)
        if verb == "feed" and not rest:
            return show_feed(ctx)
        if verb == "save":
            return save(ctx, rest)
        if verb == "snooze":
            return snooze(ctx, rest)
    except CardlakeError as exc:
        return str(exc)
    except Exception:
        logger.warning("Cardlake: /cardlake %s failed", verb, exc_info=True)
        return "Something went wrong talking to Cardlake. See `hermes logs` for details."
    return USAGE
