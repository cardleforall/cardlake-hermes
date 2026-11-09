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
from typing import Any, NamedTuple, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .address import ADDRESS

OPEN_LINK = f"{ADDRESS}/vault/"
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


def back(card: dict, now: datetime) -> str:
    """When a snoozed card comes back: 'back later today', 'back tomorrow', 'back 14 Nov', or ''."""
    # list_feed calls it remind_later_until; a snooze's own result calls it snoozed_until.
    raw = str(card.get("remind_later_until") or card.get("snoozed_until") or "")
    try:
        until = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if until <= now:
        return ""  # an old snooze that has run out: the card is already back in the feed
    day = until.astimezone(now.tzinfo).date()
    if day == now.date():
        return "⏰ back later today"
    if (day - now.date()).days == 1:
        return "⏰ back tomorrow"
    return f"⏰ back {day.day} {day:%b}"


def panel(card: dict, now: datetime) -> str:
    emoji, label = kind(card)
    top = f"{emoji} **{label}**"
    # A bare pin, not "📌 pinned": on a phone the longer status line wraps.
    extras = [x for x in (status(card, now), back(card, now), "📌" if card.get("pinned_at") else "") if x]
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
    for extra in (status(card, now), back(card, now)):
        if extra:
            parts.append(extra)
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
          lead: str = "", full: int = FULL_CARDS, head_on_first: bool = True,
          more: bool = False) -> list[tuple[str, Optional[dict]]]:
    """The message in parts, for Telegram buttons: (text, the card it shows) for each card shown in
    full, the heading riding on the first, then (text, None) for the rest. No link line: in
    Telegram that's a button. `more`: Cardlake has cards beyond these, so the count isn't known."""
    shown = cards[:max(MAX_CARDS, full)]
    head = _head(heading, summary)
    parts: list[tuple[str, Optional[dict]]] = [(panel(card, now), card) for card in shown[:full]]
    if parts and head_on_first:
        parts[0] = (f"{head}\n\n{parts[0][0]}", parts[0][1])
    tail = []
    rest = shown[full:]
    if rest:
        tail.append("\n".join(line(card, now) for card in rest))
    if more:
        tail.append("…and more in Cardlake.")
    elif len(cards) > len(shown):
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


def render(cards: list[dict], now: datetime, heading: str, summary: str = "", hint: str = "",
           full: int = FULL_CARDS, more: bool = False) -> str:
    """A heading, the first cards as panels, the rest as single lines, and the link."""
    parts = split(cards, now, heading, summary, hint, full=full, more=more)
    return with_open_link("\n\n".join(text for text, _ in parts))


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


class FeedFilter(NamedTuple):
    """One view of the feed: what to ask Cardlake for and how to title it."""
    words: tuple
    args: dict  # list_feed arguments
    heading: str
    noun: str  # "learnings", as in "3 learnings"
    snoozed: bool = False


FILTERS = (
    FeedFilter(("reminders", "reminder"), {"types": ["reminder"]}, "🔔 Your reminders", "reminder"),
    FeedFilter(("learning", "learnings"), {"types": ["learning"]}, "📚 Your learnings", "learning"),
    FeedFilter(("work", "work items", "work item"), {"types": ["work"]}, "💼 Your work items", "work item"),
    FeedFilter(("family",), {"types": ["family"]}, "👪 Family", "family card"),
    FeedFilter(("bookmarks", "bookmark"), {"types": ["bookmark"]}, "🔖 Your bookmarks", "bookmark"),
    FeedFilter(("misc",), {"types": ["talking_point"]}, "💬 Your Misc cards", "Misc card"),
    FeedFilter(("github", "github issues", "issues", "issue"), {"types": ["kanban"]}, "🗂 Your GitHub issues",
               "GitHub issue"),
    FeedFilter(("files", "file"), {"types": ["file"]}, "📎 Your files", "file"),
    FeedFilter(("favorites", "favourites", "favorite", "favourite", "liked"), {"liked_only": True},
               "♥ Your favorites", "favorite"),
    FeedFilter(("snoozed",), {"view": "snoozed"}, "⏰ Snoozed", "snoozed card", snoozed=True),
)
FILTER_NAMES = ", ".join(f.words[0] for f in FILTERS)


def find_filter(word: str) -> Optional[FeedFilter]:
    word = " ".join(word.lower().split())
    return next((f for f in FILTERS if word in f.words), None)


def _feed_args(cards: list[dict], now: datetime, flt: Optional[FeedFilter] = None, more: bool = False) -> tuple:
    overdue = sum(is_overdue(c, now) for c in cards)
    # "cards", not the filter's noun: the heading already says what kind ("Your learnings · 6 cards").
    # Cardlake sends a page, not a total: with more after it, "20+ cards", not a wrong "20 cards".
    count = f"{len(cards)}+ cards" if more else _count(len(cards), "card")
    summary = count + (f", {overdue} overdue" if overdue and not (flt and flt.snoozed) else "")
    if flt and flt.snoozed:
        # Cardlake already lists these by when they come back. Marked, so their buttons bring them back.
        return [dict(c, _snoozed=True) for c in cards], now, flt.heading, summary
    return by_urgency(cards, now), now, flt.heading if flt else "🗂 Your Cardlake feed", summary


def _empty(flt: Optional[FeedFilter]) -> str:
    if flt is None:
        return "Your Cardlake feed is empty."
    if flt.snoozed:
        return "Nothing is snoozed."
    return f"No {flt.noun}s in your feed."


def render_feed(cards: list[dict], now: datetime, flt: Optional[FeedFilter] = None, more: bool = False) -> str:
    if not cards:
        return with_open_link(_empty(flt))
    return render(*_feed_args(cards, now, flt, more), more=more)


def split_feed(cards: list[dict], now: datetime, flt: Optional[FeedFilter] = None,
               more: bool = False) -> list[tuple[str, Optional[dict]]]:
    lead = f"More {flt.noun}s" if flt else _TAIL_LEAD
    return split(*_feed_args(cards, now, flt, more), lead=lead, more=more) if cards else []


def today_cards(cards: list[dict], now: datetime) -> list[dict]:
    """Reminders that are overdue or due today, overdue first."""
    overdue = [c for c in cards if is_overdue(c, now)]
    today = [c for c in cards if is_due_today(c, now)]
    return overdue + today


_TODAY_HINT = 'Reply "done", "tomorrow" or "next week" with a card\'s name to update it.'
TODAY_FULL = 5  # everything in Today needs you, so more of it gets buttons than the feed's 3


def today_heading(now: datetime) -> str:
    return f"☀️ Today in Cardlake, {now:%a} {now.day} {now:%b}"


def _today_summary(due: list[dict], now: datetime) -> str:
    overdue = sum(is_overdue(c, now) for c in due)
    bits = [f"{overdue} overdue" if overdue else "", f"{len(due) - overdue} due today" if len(due) > overdue else ""]
    return ", ".join(b for b in bits if b)


def render_today(cards: list[dict], now: datetime) -> Optional[str]:
    """Today's message, or None when nothing is overdue or due today."""
    due = today_cards(cards, now)
    if not due:
        return None
    return render(due, now, today_heading(now), _today_summary(due, now), hint=_TODAY_HINT)


def split_today(cards: list[dict], now: datetime) -> list[tuple[str, Optional[dict]]]:
    """Today's cards in parts. The heading goes on the checklist (see checklist()), and with buttons
    under each card the reply-to-update hint isn't needed."""
    due = today_cards(cards, now)
    return split(due, now, today_heading(now), lead=_TAIL_LEAD, full=TODAY_FULL, head_on_first=False) if due else []


# Marks for the pinned checklist, by what a button did (see buttons.py).
_DONE_MARKS = {"Done": "✅", "Marked as watched": "✅", "Snoozed until tomorrow": "⏰", "Snoozed for a week": "📅"}


def checklist(cards: list[dict], now: datetime, results: dict[str, str]) -> str:
    """The pinned Today message: one line per card, ticked off as buttons are used, then 'All clear'."""
    lines = []
    for card in cards[:MAX_CARDS]:
        title = plain(card.get("title")) or "Untitled"
        result = results.get(str(card.get("id")))
        if result:
            lines.append(f"{_DONE_MARKS.get(result, '✓')} {title} · {result.lower()}")
        else:
            lines.append(f"⬜ {title}")
    if len(cards) > MAX_CARDS:
        lines.append(f"…and {len(cards) - MAX_CARDS} more in Cardlake.")
    still_open = [card for card in cards if not results.get(str(card.get("id")))]
    open_count = len(still_open)
    # Counts what's left, so the pinned line shrinks as you go.
    summary = (_today_summary(still_open, now) + (" left" if len(still_open) < len(cards) else "")
               if open_count else "all clear ✓")
    body = "\n".join(lines)
    if not open_count:
        body += "\n\n**Nothing left for today.** 🎉"
    return f"{_head(today_heading(now), summary)}\n\n{body}"


DEAL_SIZE = 5


def deal(cards: list[dict], now: datetime, pick=None) -> list[dict]:
    """Five cards to look at again, like the app's Deal me 5: cards that aren't already shouting for
    attention (overdue, due today or pinned) and aren't finished. pick(population, k) chooses; random
    by default."""
    import random
    pool = [c for c in cards if not (is_overdue(c, now) or is_due_today(c, now) or c.get("pinned_at"))]
    pick = pick or random.sample
    return pick(pool, min(DEAL_SIZE, len(pool)))


_DEAL_HEADING = "🃏 Deal me 5"
_DEAL_SUMMARY = "cards to look at again"


def render_deal(dealt: list[dict], now: datetime) -> str:
    if not dealt:
        return with_open_link("Nothing to deal: everything in your feed is due, pinned or done.")
    return render(dealt, now, _DEAL_HEADING, _DEAL_SUMMARY, full=DEAL_SIZE)


def split_deal(dealt: list[dict], now: datetime) -> list[tuple[str, Optional[dict]]]:
    return split(dealt, now, _DEAL_HEADING, _DEAL_SUMMARY, full=DEAL_SIZE) if dealt else []


def video_url(card: dict) -> str:
    """The link a learning card's own message previews (a talk or course), or ''. Other cards'
    links stay unpreviewed so a feed doesn't turn into a wall of article thumbnails."""
    if card.get("type") != "learning":
        return ""
    url = str((card.get("metadata") or {}).get("url") or "").strip()
    return url if re.match(r"https?://[^\s()]+$", url) else ""
