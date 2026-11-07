"""Removes passwords, API keys and tokens from text.

This runs in code, not as an instruction to a model, so a model that ignores
its instructions still can't send a secret to Cardlake. It leans towards
removing too much: a lost commit hash on a card costs far less than a live key.
"""

from __future__ import annotations

import re
from typing import Any

REMOVED = "[removed]"

_NAMES = (
    r"pass(?:word|wd|phrase|code)?|pwd|secret(?:[ _-]?key)?|client[ _-]?secret|"
    r"api[ _-]?key|apikey|access[ _-]?key|private[ _-]?key|secret[ _-]?access[ _-]?key|"
    r"(?:access|auth|bearer|refresh|id|session|csrf|bot|personal[ _-]access)[ _-]?token|"
    r"token|auth|authorization|credentials?|cookie|session[ _-]?id"
)

# Whole shapes that are secrets wherever they appear.
_SHAPES = [
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"),  # JWT
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),  # OpenAI, Anthropic, OpenRouter
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),  # GitHub
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),  # GitLab
    re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{10,}"),  # Slack
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),  # AWS
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),  # Google
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"),  # Stripe
    re.compile(r"\bwhsec_[A-Za-z0-9+/=]{10,}"),  # webhook signing
    re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),  # SendGrid
    re.compile(r"\b(?:npm|hf|pypi|dop_v1|nous)[_-][A-Za-z0-9_-]{20,}"),  # npm, Hugging Face, PyPI, DigitalOcean
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),  # Telegram bot
    re.compile(r"\bhttps://hooks\.slack\.com/services/\S+"),
]

_BEARER = re.compile(r"\b(Bearer|Basic|Token)(\s+)[A-Za-z0-9._~+/=-]{8,}")
_URL_LOGIN = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s/:@]*:[^\s/@]+@", re.I)
# name=value, name: value, "name": "value". A quoted value may hold spaces.
_VALUE = r"""(?P<value>"[^"\n]*"|'[^'\n]*'|`[^`\n]*`|[^\s"'`,;&)\]}]+)"""
_NAMED = re.compile(
    r"""(?P<name>(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*(?:%s)(?:[_-][A-Za-z0-9]+)*)
        (?P<sep>["']?\s*(?:=>|:=|=|:)\s*)""" % _NAMES + _VALUE,
    re.I | re.X,
)
# "my password is hunter2". Only for words that hold one value: "the cookie is stale" is
# just a sentence, and "to" only after a password, or "add auth to the dashboard" would go.
_SPOKEN = re.compile(
    r"""(?P<name>\b(?:pass(?:word|wd|phrase|code)|pwd|secret|api[ _-]?key|apikey|token))
        (?P<sep>\s+(?:is|was)\s+)""" + _VALUE + r"""|
        (?P<name2>\b(?:pass(?:word|wd|phrase|code)|pwd))(?P<sep2>\s+to\s+)(?P<value2>\S+)""",
    re.I | re.X,
)
# Bare long random-looking runs: hex keys, and base64-like strings mixing cases and digits.
_LONG_HEX = re.compile(r"\b[a-fA-F0-9]{32,}\b")
_LONG_RANDOM = re.compile(r"(?<![A-Za-z0-9_/+=-])[A-Za-z0-9_/+=-]{40,}(?![A-Za-z0-9_/+=-])")

# "the password is broken" / "token: limit" are ordinary English, not secrets.
_PLAIN_WORDS = frozenset(
    "a an and are as at be been being broken by can changed correct could did does empty expired for from good "
    "has have here in incorrect invalid is it length limit limits missing needed new no not of old on or our "
    "ready required reset rotated same set should still that the their them there this to too updated use used "
    "using valid was what when where which will with wrong you your".split()
)


def _looks_random(run: str) -> bool:
    return bool(re.search(r"[a-z]", run) and re.search(r"[A-Z]", run) and re.search(r"\d", run))


def _named(match: re.Match) -> str:
    groups = match.groupdict()
    value = groups["value"] or groups.get("value2") or ""
    if value.strip("\"'`").lower().rstrip(".!?") in _PLAIN_WORDS:
        return match.group(0)
    return f"{groups['name'] or groups['name2']}{groups['sep'] or groups['sep2']}{REMOVED}"


def redact_text(text: str) -> str:
    """Return *text* with anything that looks like a secret replaced."""
    if not text:
        return text
    for shape in _SHAPES:
        text = shape.sub(REMOVED, text)
    text = _URL_LOGIN.sub(lambda m: f"{m.group(1)}{REMOVED}@", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}{m.group(2)}{REMOVED}", text)
    text = _NAMED.sub(_named, text)
    text = _SPOKEN.sub(_named, text)
    text = _LONG_HEX.sub(REMOVED, text)
    return _LONG_RANDOM.sub(lambda m: REMOVED if _looks_random(m.group(0)) else m.group(0), text)


def redact(value: Any) -> Any:
    """Redact every string inside a tool's arguments, keeping the structure."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value
