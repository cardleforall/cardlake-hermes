"""Planted secrets must never survive. Built from parts so no scanner mistakes them for real ones."""

import unittest

from .helpers import load

redact = load("redact")

A36 = "a1B2c3D4e5" * 3 + "F6g7H8"
PLANTED = {
    "OpenAI key": "sk-" + "proj-" + A36,
    "Anthropic key": "sk-" + "ant-api03-" + A36,
    "GitHub token": "gh" + "p_" + A36,
    "GitHub fine-grained": "github" + "_pat_" + A36,
    "GitLab token": "gl" + "pat-" + A36[:20],
    "Slack token": "xo" + "xb-123456789012-" + A36[:20],
    "AWS key": "AK" + "IA" + "ABCDEFGHIJ123456",
    "Google key": "AI" + "za" + A36,
    "Stripe key": "sk" + "_live_" + A36,
    "JWT": "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abc123DEF456",
    "Telegram bot": "123456789:" + "AA" + A36[:33],
    "long hex": "deadbeef" * 5,
    "random run": A36 + A36,
}
PHRASES = [
    ("password=hunter2secret", "hunter2secret"),
    ("my password is hunter2secret", "hunter2secret"),
    ("change the password to hunter2secret", "hunter2secret"),
    ("PASSWORD: 'correct horse battery'", "correct horse battery"),
    ('{"api_key": "abc123xyz"}', "abc123xyz"),
    ("DB_PASSWORD=s3cr3t!", "s3cr3t!"),
    ("export STRIPE_API_KEY=abc123xyz", "abc123xyz"),
    ("client_secret: abc123xyz", "abc123xyz"),
    ("access_token=abc123xyz&user=me", "abc123xyz"),
    ("Authorization: Bearer abc123xyz456", "abc123xyz456"),
    ("curl -H 'Bearer abc123xyz456'", "abc123xyz456"),
    ("postgres://admin:s3cr3t@db.example.com/app", "s3cr3t"),
    ("https://example.com/cb?token=abc123xyz", "abc123xyz"),
]


class RedactionTest(unittest.TestCase):
    def test_known_key_shapes_are_removed(self):
        for name, secret in PLANTED.items():
            with self.subTest(name):
                self.assertNotIn(secret, redact.redact_text(f"use {secret} here please"))

    def test_named_secrets_are_removed(self):
        for text, secret in PHRASES:
            with self.subTest(text):
                self.assertNotIn(secret, redact.redact_text(text))

    def test_private_key_block_is_removed(self):
        block = "-----BEGIN RSA " + "PRIVATE KEY-----\nabc\ndef\n-----END RSA " + "PRIVATE KEY-----"
        cleaned = redact.redact_text(f"key:\n{block}\nthanks")
        self.assertNotIn("abc", cleaned)
        self.assertIn("thanks", cleaned)

    def test_ordinary_text_is_left_alone(self):
        for text in (
            "Call the dentist on Friday",
            "The password is wrong",
            "Reset the password for the staging site",
            "We hit the token limit again",
            "Read https://example.com/guides/how-to-write-good-commit-messages",
            "Add auth to the dashboard",
            "The cookie is stale",
            "Session id was missing from the log",
            "Decide what the token budget is",
        ):
            with self.subTest(text):
                self.assertEqual(redact.redact_text(text), text)

    def test_nested_arguments_are_redacted_and_keep_their_shape(self):
        secret = PLANTED["GitHub token"]
        cleaned = redact.redact({"title": secret, "items": [{"text": secret, "completed": False}], "days": 2})
        self.assertNotIn(secret, str(cleaned))
        self.assertEqual(cleaned["days"], 2)
        self.assertIs(cleaned["items"][0]["completed"], False)


if __name__ == "__main__":
    unittest.main()
