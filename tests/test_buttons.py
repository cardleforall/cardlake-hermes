"""Telegram buttons: what they show, what a tap changes, and when they're left out."""

import asyncio
import unittest
from types import SimpleNamespace

from tests.helpers import FakeCtx, load

buttons = load("buttons")
commands = load("commands")

REMINDER = {"id": "r1", "type": "reminder", "title": "Call mum", "metadata": {"due_date": "2020-01-01"}}
LEARNING = {"id": "l1", "type": "learning", "title": "Sal Khan on AI tutors", "metadata": {}}
WORK = {"id": "w1", "type": "work", "title": "Customer interviews", "metadata": {}}
FOURTH = {"id": "x4", "type": "reminder", "title": "Not shown in full", "metadata": {}}


class FakeBot:
    def __init__(self):
        self.keyboards = []

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.keyboards.append((chat_id, message_id, reply_markup))


class ButtonsCtx(FakeCtx):
    def __init__(self, surface="telegram", chat_id="42", posted=True, **kwargs):
        super().__init__(**kwargs)
        self.surface, self.chat_id, self.posted = surface, chat_id, posted
        self.posts = []

    def session_surface(self):
        return self.surface

    def post_message(self, text):
        self.posts.append(text)
        return SimpleNamespace(ok=self.posted, message_id="7" if self.posted else None,
                               _target=SimpleNamespace(chat_id=self.chat_id))


class Harness:
    """Buttons running on a real event loop in another thread, as on the gateway."""

    def __init__(self, ctx):
        import threading
        self.ctx = ctx
        self.ran = []
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.buttons = buttons.TelegramButtons(ctx, self._run)
        self.buttons.bot, self.buttons.loop = FakeBot(), self.loop
        self.buttons.markup = lambda rows: rows

    def _run(self, tool, args):
        self.ran.append((tool, args))
        return commands.call_cardlake(self.ctx, tool, args)

    def tap(self, data, chat_type="private", chat_id="42", message_id="7"):
        future = asyncio.run_coroutine_threadsafe(
            self.buttons.tap(chat_id, message_id, chat_type, data), self.loop)
        return future.result(5)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


def texts(rows):
    return [[b["text"] for b in row] for row in rows]


class KeyboardTest(unittest.TestCase):
    def test_a_row_per_full_card_then_the_link(self):
        rows = buttons.keyboard_rows([REMINDER, LEARNING, WORK, FOURTH])
        self.assertEqual(texts(rows), [
            ["✅ Call mum", "⏰ Tomorrow", "📅 Next week"],
            ["✅ Sal Khan on AI tu…", "⏰ Tomorrow", "📅 Next week"],
            ["⏰ Customer intervie…", "📅 Next week"],
            ["🔗 Open Cardlake"],
        ])
        self.assertEqual(rows[-1][0]["url"], "https://cardlake.app/vault/")

    def test_button_data_fits_telegrams_64_byte_limit(self):
        long_id = {"id": "1" * 36, "type": "reminder", "title": "x" * 300}
        for row in buttons.keyboard_rows([long_id]):
            for button in row:
                self.assertLessEqual(len(button.get("callback_data", "").encode()), 64)

    def test_a_finished_card_says_what_happened(self):
        rows = buttons.keyboard_rows([REMINDER, WORK], {0: "Done"})
        self.assertEqual(texts(rows)[0], ["✓ Done: Call mum"])


class TapTest(unittest.TestCase):
    def setUp(self):
        self.ctx = ButtonsCtx(feed=[REMINDER, LEARNING, WORK])
        self.h = Harness(self.ctx)
        self.assertTrue(self.h.buttons.send("feed text", [REMINDER, LEARNING, WORK]))

    def tearDown(self):
        self.h.close()

    def test_done_completes_a_reminder(self):
        self.assertEqual(self.h.tap("clk:d:0"), "Done: Call mum")
        self.assertEqual(self.ctx.written(), [("update_reminder", {"id": "r1", "completed": True})])

    def test_done_marks_a_learning_watched(self):
        self.h.tap("clk:d:1")
        self.assertEqual(self.ctx.written(), [("update_learning", {"id": "l1", "status": "watched"})])

    def test_tomorrow_and_next_week_snooze(self):
        self.h.tap("clk:t:2")
        self.h.tap("clk:w:0")
        self.assertEqual(self.ctx.written(), [
            ("snooze_card", {"card_type": "work", "card_id": "w1", "days": 1}),
            ("snooze_card", {"card_type": "reminder", "card_id": "r1", "days": 7}),
        ])

    def test_a_card_is_changed_once_and_the_buttons_update(self):
        self.h.tap("clk:d:0")
        self.assertEqual(self.h.tap("clk:t:0"), "Already done.")
        self.assertEqual(len(self.ctx.written()), 1)
        self.assertEqual(len(self.h.buttons.bot.keyboards), 2)  # added, then updated

    def test_work_items_have_no_done(self):
        self.assertIn("doesn't apply", self.h.tap("clk:d:2"))
        self.assertEqual(self.ctx.written(), [])

    def test_crafted_taps_cant_reach_other_cards_or_messages(self):
        for data in ("clk:d:9", "clk:d:r1", "clk:x:0"):
            self.h.tap(data)
        self.h.tap("clk:d:0", message_id="999")
        self.assertEqual(self.ctx.written(), [])

    def test_group_chats_are_refused(self):
        self.assertIn("private chat", self.h.tap("clk:d:0", chat_type="group"))
        self.assertEqual(self.ctx.written(), [])

    def test_a_failed_update_says_so_and_can_be_retried(self):
        self.ctx.connected = False
        self.assertIn("Couldn't update Cardlake", self.h.tap("clk:d:0"))
        self.ctx.connected = True
        self.assertEqual(self.h.tap("clk:d:0"), "Done: Call mum")


class WhenButtonsAreLeftOutTest(unittest.TestCase):
    def run_feed(self, ctx, attach=True):
        h = Harness(ctx)
        if not attach:
            h.buttons.bot = h.buttons.markup = None
        try:
            return commands.handle(ctx, "feed", h.buttons), h
        finally:
            h.close()

    def test_telegram_posts_the_feed_itself_with_buttons(self):
        ctx = ButtonsCtx(feed=[REMINDER])
        reply, h = self.run_feed(ctx)
        self.assertEqual(reply, "")  # already posted; Hermes has nothing to send
        self.assertIn("Call mum", ctx.posts[0])
        self.assertEqual(len(h.buttons.bot.keyboards), 1)

    def test_other_platforms_get_plain_text(self):
        ctx = ButtonsCtx(surface="cli", feed=[REMINDER])
        reply, _ = self.run_feed(ctx)
        self.assertIn("Call mum", reply)
        self.assertEqual(ctx.posts, [])

    def test_older_hermes_without_the_telegram_hook_gets_plain_text(self):
        ctx = ButtonsCtx(feed=[REMINDER])
        reply, _ = self.run_feed(ctx, attach=False)
        self.assertIn("Call mum", reply)

    def test_group_chats_get_the_text_without_buttons(self):
        ctx = ButtonsCtx(chat_id="-100123", feed=[REMINDER])
        reply, h = self.run_feed(ctx)
        self.assertEqual(reply, "")
        self.assertEqual(len(ctx.posts), 1)
        self.assertEqual(h.buttons.bot.keyboards, [])

    def test_a_failed_post_falls_back_to_text(self):
        ctx = ButtonsCtx(posted=False, feed=[REMINDER])
        reply, _ = self.run_feed(ctx)
        self.assertIn("Call mum", reply)

    def test_an_empty_today_has_no_buttons(self):
        ctx = ButtonsCtx(feed=[WORK])
        h = Harness(ctx)
        try:
            reply = commands.handle(ctx, "today", h.buttons)
        finally:
            h.close()
        self.assertIn("Nothing is overdue", reply)
        self.assertEqual(ctx.posts, [])


if __name__ == "__main__":
    unittest.main()
