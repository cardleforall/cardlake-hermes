"""Reads the user's own Hermes conversations for a period of time."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from .redact import redact_text

# Enough for a real day of chat without sending the model a whole archive.
MAX_TOTAL_CHARS = 60_000
_PAGE = 50
_MAX_SESSIONS = 200
# The briefing's own runs are not conversations with the user.
_EXCLUDED_SOURCES = ["cron"]


@dataclass
class Conversation:
    title: str
    text: str


@dataclass
class ConversationBatch:
    conversations: list[Conversation]
    trimmed: bool = False


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


def period_window(period: str, now: datetime) -> tuple[datetime, datetime]:
    """today = midnight to now, yesterday = that whole day, week = the past 7 days up to now."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return midnight, now
    if period == "yesterday":
        return midnight - timedelta(days=1), midnight
    if period == "week":
        return now - timedelta(days=7), now
    raise ValueError(f"unknown period: {period}")


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = (part.get("text") for part in content if isinstance(part, dict))
        return "\n".join(part for part in parts if isinstance(part, str))
    return ""


def _open_db():
    from hermes_state import SessionDB
    return SessionDB(read_only=True)


def _sessions_active_since(db, start_ts: float) -> list[dict]:
    """Most recently active first, stopping once sessions are older than the window."""
    found: list[dict] = []
    for offset in range(0, _MAX_SESSIONS, _PAGE):
        rows = db.list_sessions_rich(
            exclude_sources=_EXCLUDED_SOURCES, min_message_count=1,
            order_by_last_active=True, limit=_PAGE, offset=offset,
        )
        for row in rows:
            if (row.get("last_active") or row.get("started_at") or 0) < start_ts:
                return found
            found.append(row)
        if len(rows) < _PAGE:
            break
    return found


def _title(row: dict, start_ts: float) -> str:
    title = (row.get("title") or "").strip()
    if title:
        return redact_text(title)
    started = row.get("started_at") or start_ts
    return datetime.fromtimestamp(started).strftime("Untitled conversation from %d %b")


def read_conversations(start: datetime, end: datetime, open_db: Optional[Callable] = None) -> ConversationBatch:
    """Each conversation's user and assistant messages inside the window, with secrets
    already removed. A conversation that began earlier counts only for what was said inside it."""
    start_ts, end_ts = start.timestamp(), end.timestamp()
    db = (open_db or _open_db)()
    try:
        found: list[Conversation] = []
        for row in _sessions_active_since(db, start_ts):
            lines = []
            for message in db.get_messages(row["id"], include_ancestors=True):
                if message.get("role") not in ("user", "assistant"):
                    continue
                if not start_ts <= (message.get("timestamp") or 0) < end_ts:
                    continue
                text = _as_text(message.get("content")).strip()
                if text:
                    lines.append(f"{message['role']}: {redact_text(text)}")
            if lines:
                found.append(Conversation(_title(row, start_ts), "\n".join(lines)))
    finally:
        close = getattr(db, "close", None)
        if close:
            close()
    return _fit_budget(found)


def _fit_budget(found: list[Conversation]) -> ConversationBatch:
    """Keep every conversation in, trimming the longest to their newest part."""
    if sum(len(c.text) for c in found) <= MAX_TOTAL_CHARS:
        return ConversationBatch(found)
    share = MAX_TOTAL_CHARS // len(found)
    spare = sum(share - len(c.text) for c in found if len(c.text) < share)
    long_ones = sum(1 for c in found if len(c.text) >= share)
    allowance = share + spare // max(long_ones, 1)
    for conversation in found:
        if len(conversation.text) > allowance:
            conversation.text = conversation.text[-allowance:]
    return ConversationBatch(found, trimmed=True)
