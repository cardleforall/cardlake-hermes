"""cardlake_show_cards: lets Hermes show its own results (links it found, research findings, a job's
report, options) as cards, each with Save to Cardlake and Remind me tomorrow.

Nothing reaches Cardlake unless the user taps a button: Hermes only chooses what the cards say.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from typing import Any, Optional

from . import feed_view
from .feed_view import MAX_CARDS, OPEN_LINK, plain, with_open_link

logger = logging.getLogger(__name__)

SHOW_TOOL = "cardlake_show_cards"
KINDS = {  # kind -> emoji, label, Cardlake create tool, delete tool (for Undo), what it's saved as
    "learning": ("📚", "Learning", "create_learning", "delete_learning", "Learning"),
    "link": ("🔖", "Link", "create_bookmark", "delete_bookmark", "Bookmark"),
    "task": ("💼", "Task", "create_work_item", "delete_work_item", "Work item"),
    "reminder": ("🔔", "Reminder", "create_reminder", "delete_reminder", "Reminder"),
    "note": ("💬", "Note", "create_talking_point", "delete_talking_point", "Misc card"),
}
_MAX_LINES = 3
_LINE_CHARS = 160
_TITLE_CHARS = 120

SHOW_SCHEMA = {
    "name": SHOW_TOOL,
    "description": (
        "Show results to the user as cards in Telegram, each with 'Save to Cardlake' and 'Remind me tomorrow' "
        "buttons. Use it when your answer is a set of separate items: links or videos you found, findings, "
        "options, tasks, or a scheduled job's results. One card per item, at most 8. Nothing is saved unless the "
        "user taps a button. If it returns shown > 0 the user already sees the cards: don't repeat them, reply "
        "in one short line at most. If it returns text, put that text in your reply instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "heading": {"type": "string", "description": "A short heading for the set, e.g. 'Three videos on AI tutors'."},
            "cards": {
                "type": "array", "minItems": 1, "maxItems": MAX_CARDS,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "The item in a few words."},
                        "kind": {"type": "string", "enum": list(KINDS),
                                 "description": "learning: a video, article or course to learn from; link: any other "
                                                "page; task: something to do; reminder: something to do on a date; "
                                                "note: anything else."},
                        "lines": {"type": "array", "items": {"type": "string"}, "maxItems": _MAX_LINES,
                                  "description": "Up to 3 short lines: the key facts, numbers or why it matters."},
                        "status": {"type": "string", "description": "Optional short status, e.g. '⚠️ 2 GB used'."},
                        "url": {"type": "string", "description": "The item's link, if it has one."},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["cards"],
    },
}


def _clip(text: Any, limit: int) -> str:
    text = plain(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def clean(args: dict) -> tuple[str, list[dict]]:
    """The heading and cards as the plugin will show them: plain text, capped, links checked."""
    heading = _clip((args or {}).get("heading") or "", 80)
    cards = []
    for raw in list((args or {}).get("cards") or [])[:MAX_CARDS]:
        if not isinstance(raw, dict) or not plain(raw.get("title")):
            continue
        url = str(raw.get("url") or "").strip()
        url = url if re.match(r"https?://[^\s()]+$", url) else ""
        kind = raw.get("kind") if raw.get("kind") in KINDS else ("link" if url else "note")
        lines = [_clip(line, _LINE_CHARS) for line in list(raw.get("lines") or [])[:_MAX_LINES] if plain(line)]
        cards.append({
            "_shown": True, "id": f"shown-{len(cards)}", "type": "learning" if kind == "learning" else kind,
            "kind": kind, "title": _clip(raw.get("title"), _TITLE_CHARS), "lines": lines,
            "status": _clip(raw.get("status") or "", 40),
            "metadata": {"url": url},
        })
    return heading, cards


def panel(card: dict) -> str:
    emoji, label = KINDS[card["kind"]][:2]
    top = f"{emoji} **{label}**" + (f" · {card['status']}" if card["status"] else "")
    lines = [f"> {top}", f"> **{card['title']}**"] + [f"> {line}" for line in card["lines"]]
    url = card["metadata"]["url"]
    if url:
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", url))
        lines.append(f"> [{host}]({url})")
    return "\n".join(lines)


def parts(heading: str, cards: list[dict]) -> list[tuple[str, Optional[dict]]]:
    """One message per card, the heading riding on the first (as plain bold: it isn't a Cardlake view)."""
    out = [(panel(card), card) for card in cards]
    if out and heading:
        out[0] = (f"**{heading}**\n\n{out[0][0]}", out[0][1])
    return out


def as_text(heading: str, cards: list[dict]) -> str:
    """For anywhere without Telegram buttons: the same cards in one message."""
    return with_open_link("\n\n".join(text for text, _ in parts(heading, cards)))


def save_call(card: dict) -> tuple[str, dict, str, str]:
    """(create tool, its arguments, delete tool for Undo, what it was saved as)."""
    _, _, create, delete, saved_as = KINDS[card["kind"]]
    title, url, notes = card["title"], card["metadata"]["url"], "\n".join(card["lines"])
    if card["kind"] == "learning":
        args = {"title": title, "status": "saved", "category": "others", **({"url": url} if url else {}),
                **({"notes": notes} if notes else {})}
    elif card["kind"] == "link":
        args = {"title": title, **({"url": url} if url else {}), **({"notes": notes} if notes else {})}
    elif card["kind"] in ("task", "reminder"):
        args = {"title": _with_url(title, url)}
    else:
        args = {"section_title": title, "content": "\n".join(x for x in (notes, url) if x) or title}
    return create, args, delete, saved_as


def remind_call(card: dict) -> tuple[str, dict]:
    tomorrow = (feed_view.local_now() + timedelta(days=1)).date().isoformat()
    return "create_reminder", {"title": _with_url(card["title"], card["metadata"]["url"]), "due_date": tomorrow}


def _with_url(title: str, url: str) -> str:
    """Reminders and work items have no link field, so the link rides in the title."""
    return f"{title} ({url})"[:200] if url and len(title) + len(url) + 3 <= 200 else title


def created_id(result: Any) -> Optional[str]:
    if isinstance(result, dict):
        for value in (result.get("id"), (result.get("card") or {}).get("id")):
            if value:
                return str(value)
    return None


def show_tool(buttons, args: dict) -> str:
    """The tool Hermes calls. Never raises: a tool handler must always answer."""
    try:
        heading, cards = clean(args)
        if not cards:
            return json.dumps({"error": "No cards to show: each card needs a title."})
        if buttons is not None and buttons.send(parts(heading, cards)):
            return json.dumps({"shown": len(cards), "note": "The user sees these as cards with buttons. Don't repeat "
                                                            "them; reply in one short line at most."})
        return json.dumps({"shown": 0, "text": as_text(heading, cards),
                           "note": "Cards with buttons aren't available here: put this text in your reply."})
    except Exception as exc:
        logger.warning("Cardlake: showing cards failed", exc_info=True)
        return json.dumps({"error": f"Couldn't show the cards: {exc}"})
