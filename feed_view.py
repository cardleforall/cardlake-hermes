"""Draws Cardlake cards as chat text.

Written as Markdown that Hermes turns into Telegram formatting: each card is a quote
block, which Telegram shows as a tinted panel with a bar down the side. No boxes or
ASCII art, which only line up in a terminal. Collapsible quotes aren't used: Hermes
only converts them when they fit on one line.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

OPEN_LINK = "https://cardlake.app/vault/"
FULL_CARDS = 3  # shown as panels; the rest get one line each
MAX_CARDS = 8   # a chat message isn't the place for the whole feed; the link is

_TYPES = {
    "reminder": ("🔔", "Reminder"),
    "learning": ("📚", "Learning"),
    "work": ("💼", "Work item"),
    "family": ("👪", "Family"),
    "bookmark": ("🔖", "Bookmark"),
    "talking_point": ("💬", "Misc"),
    "kanban": ("🗂", "GitHub issue"),
    "file": ("📎", "File"),
}


def local_now() -> datetime:
    """Now in the user's time zone: the one set in Hermes, else this computer's."""
    name = os.environ.get("HERMES_TIMEZONE", "").strip()
    if not name:
        try:
            from hermes_cli.config import load_config
            name = str(load_config().get("timezone") or "").strip()
        except Exception:
            name = ""
    try:
        return datetime.now(ZoneInfo(name))
    except (ValueError, KeyError, OSError):  # unset or not a real zone
        return datetime.now().astimezone()


def with_open_link(text: str) -> str:
    return f"{text.rstrip()}\n\nOpen Cardlake: {OPEN_LINK}"


def plain(text: Any) -> str:
    """Card text on one line, with nothing Hermes would read as formatting or a link."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace("[", "(").replace("]", ")")
    return re.sub(r"[*_~|`]", "", text)


def kind(card: dict) -> tuple[str, str]:
    return _TYPES.get(card.get("type"), ("🃏", "Card"))


def _due(card: dict, now: datetime) -> Optional[tuple[date, bool]]:
    """(due day in the user's time zone, whether it has passed) for an unfinished reminder."""
    meta = card.get("metadata") or {}
    if card.get("type") != "reminder" or meta.get("completed") or not meta.get("due_date"):
        return None
    try:
        due = datetime.fromisoformat(str(meta["due_date"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if (due.hour, due.minute, due.second, due.microsecond) == (0, 0, 0, 0):
        # Cardlake stores a date with no time as midnight UTC: it means that whole day, wherever you are.
        return due.date(), due.date() < now.date()
    return due.astimezone(now.tzinfo).date(), due < now


def status(card: dict, now: datetime) -> str:
    """'overdue 41 days', 'due today', 'due 12 Nov', or '' when there's no date to show."""
    due = _due(card, now)
    if due is None:
        return ""
    day, passed = due
    late = (now.date() - day).days
    if passed and late > 0:
        return f"⚠️ overdue {late} day{'' if late == 1 else 's'}"
    if passed:
        return "⚠️ overdue"
    if day == now.date():
        return "📅 due today"
    return f"due {day.day} {day:%b}"


def is_overdue(card: dict, now: datetime) -> bool:
    due = _due(card, now)
    return due is not None and due[1]


def is_due_today(card: dict, now: datetime) -> bool:
    due = _due(card, now)
    return due is not None and due[0] == now.date() and not due[1]


def _link(card: dict) -> str:
    url = str((card.get("metadata") or {}).get("url") or "").strip()
    if not re.match(r"https?://[^\s()]+$", url):
        return ""
    host = urlparse(url).hostname or ""
    host = host[4:] if host.startswith("www.") else host
    return f"[{host}]({url})" if host else ""


def panel(card: dict, now: datetime) -> str:
    emoji, label = kind(card)
    top = f"{emoji} **{label}**"
    # A bare pin, not "📌 pinned": on a phone the longer status line wraps.
    extras = [x for x in (status(card, now), "📌" if card.get("pinned_at") else "") if x]
    if extras:
        top += " · " + " · ".join(extras)
    lines = [f"> {top}", f"> **{plain(card.get('title')) or 'Untitled'}**"]
    link = _link(card)
    if link:
        lines.append(f"> {link}")
    return "\n".join(lines)


def line(card: dict, now: datetime) -> str:
    emoji, _ = kind(card)
    parts = [f"{emoji} {plain(card.get('title')) or 'Untitled'}"]
    if status(card, now):
        parts.append(status(card, now))
    if _link(card):
        parts.append(_link(card))
    return "- " + " · ".join(parts)


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _head(heading: str, summary: str) -> str:
    # Telegram previews the first link in a message. Linking the heading makes that Cardlake,
    # not whichever video or article happens to be the first card. Hermes can only turn
    # previews off for every message it sends, so this keeps the choice to this plugin.
    head = f"**[{heading}]({OPEN_LINK})**"
    return f"{head} · {summary}" if summary else head


def split(cards: list[dict], now: datetime, heading: str, summary: str = "", hint: str = "",
          lead: str = "") -> list[tuple[str, Optional[dict]]]:
    """The message in parts, for Telegram buttons: (text, the card it shows) for each card shown in
    full, the heading riding on the first, then (text, None) for the rest. No link line: in
    Telegram that's a button."""
    shown = cards[:MAX_CARDS]
    head = _head(heading, summary)
    parts: list[tuple[str, Optional[dict]]] = [(panel(card, now), card) for card in shown[:FULL_CARDS]]
    if parts:
        parts[0] = (f"{head}\n\n{parts[0][0]}", parts[0][1])
    tail = []
    rest = shown[FULL_CARDS:]
    if rest:
        tail.append("\n".join(line(card, now) for card in rest))
    if len(cards) > len(shown):
        tail.append(f"…and {len(cards) - len(shown)} more in Cardlake.")
    if hint:
        tail.append(f"*{hint}*")
    if not parts:
        tail.insert(0, head)
    elif tail and lead:
        # Its own message, so its first link is the one Telegram previews: make that Cardlake too,
        # not a video from the list.
        tail.insert(0, f"**[{lead}]({OPEN_LINK})**")
    if tail:
        parts.append(("\n\n".join(tail), None))
    return parts


def render(cards: list[dict], now: datetime, heading: str, summary: str = "", hint: str = "") -> str:
    """A heading, the first cards as panels, the rest as single lines, and the link."""
    return with_open_link("\n\n".join(text for text, _ in split(cards, now, heading, summary, hint)))


def by_urgency(cards: list[dict], now: datetime) -> list[dict]:
    """Overdue, then due today, then pinned, then the rest, each in the feed's own order, so the
    cards shown in full are the ones that need you. Cardlake puts pinned cards first, which left an
    overdue reminder as a one-line entry under three pinned panels."""
    def rank(card: dict) -> int:
        if is_overdue(card, now):
            return 0
        if is_due_today(card, now):
            return 1
        return 2 if card.get("pinned_at") else 3
    return sorted(cards, key=rank)


_TAIL_LEAD = "More in your feed"


def _feed_args(cards: list[dict], now: datetime) -> tuple:
    overdue = sum(is_overdue(c, now) for c in cards)
    summary = _count(len(cards), "card") + (f", {overdue} overdue" if overdue else "")
    return by_urgency(cards, now), now, "🗂 Your Cardlake feed", summary


def render_feed(cards: list[dict], now: datetime) -> str:
    if not cards:
        return with_open_link("Your Cardlake feed is empty.")
    return render(*_feed_args(cards, now))


def split_feed(cards: list[dict], now: datetime) -> list[tuple[str, Optional[dict]]]:
    return split(*_feed_args(cards, now), lead=_TAIL_LEAD) if cards else []


def today_cards(cards: list[dict], now: datetime) -> list[dict]:
    """Reminders that are overdue or due today, overdue first."""
    overdue = [c for c in cards if is_overdue(c, now)]
    today = [c for c in cards if is_due_today(c, now)]
    return overdue + today


_TODAY_HINT = 'Reply "done", "tomorrow" or "next week" with a card\'s name to update it.'


def _today_args(cards: list[dict], now: datetime) -> Optional[tuple]:
    due = today_cards(cards, now)
    if not due:
        return None
    overdue = sum(is_overdue(c, now) for c in due)
    bits = [f"{overdue} overdue" if overdue else "", f"{len(due) - overdue} due today" if len(due) > overdue else ""]
    return due, now, f"☀️ Today in Cardlake, {now:%a} {now.day} {now:%b}", ", ".join(b for b in bits if b)


def render_today(cards: list[dict], now: datetime) -> Optional[str]:
    """Today's message, or None when nothing is overdue or due today."""
    args = _today_args(cards, now)
    return render(*args, hint=_TODAY_HINT) if args else None


def split_today(cards: list[dict], now: datetime) -> list[tuple[str, Optional[dict]]]:
    """With buttons under each card, the reply-to-update hint isn't needed."""
    args = _today_args(cards, now)
    return split(*args, lead=_TAIL_LEAD) if args else []
