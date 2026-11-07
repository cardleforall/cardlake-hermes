"""Telegram buttons: one message per card with its buttons under it, what a tap changes, and when
buttons are left out."""

import asyncio
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from tests.helpers import FakeCtx, load

buttons = load("buttons")
commands = load("commands")
feed_view = load("feed_view")

REMINDER = {"id": "r1", "type": "reminder", "title": "Call mum", "metadata": {"due_date": "2020-01-01"}}
LEARNING = {"id": "l1", "type": "learning", "title": "Sal Khan on AI tutors", "metadata": {}}
WORK = {"id": "w1", "type": "work", "title": "Customer interviews", "metadata": {}}
MORE = [{"id": f"m{i}", "type": "bookmark", "title": f"Bookmark {i}", "metadata": {}} for i in range(8)]
NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


class FakeBot:
    def __init__(self):
        self.keyboards = {}  # message id -> rows

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.keyboards[str(message_id)] = reply_markup


class ButtonsCtx(FakeCtx):
    def __init__(self, surface="telegram", chat_id="42", posted=True, **kwargs):
        super().__init__(**kwargs)
        self.surface, self.chat_id, self.posted = surface, chat_id, posted
        self.posts = []  # [text, ...] as they stand now, indexed by message id - 1

    def session_surface(self):
        return self.surface

    def post_message(self, text):
        if not self.posted:
            return SimpleNamespace(ok=False, message_id=None, _target=None)
        self.posts.append(text)
        message_id = str(len(self.posts))

        def edit(new_text):
            self.posts[int(message_id) - 1] = new_text
        return SimpleNamespace(ok=True, message_id=message_id, edit=edit,
                               _target=SimpleNamespace(chat_id=self.chat_id))


class Harness:
    """Buttons running on a real event loop in another thread, as on the gateway."""

    def __init__(self, ctx, attached=True):
        self.ctx = ctx
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.buttons = buttons.TelegramButtons(ctx, lambda tool, args: commands.call_cardlake(ctx, tool, args))
        if attached:
            self.buttons.bot, self.buttons.loop = FakeBot(), self.loop
            self.buttons.markup = lambda rows: rows

    def feed(self):
        return commands.handle(self.ctx, "feed", self.buttons)

    def keyboard(self, message_id):
        return [[b["text"] for b in row] for row in self.buttons.bot.keyboards.get(str(message_id), [])]

    def tap(self, message_id, data, chat_type="private", chat_id="42"):
        future = asyncio.run_coroutine_threadsafe(
            self.buttons.tap(chat_id, str(message_id), chat_type, data), self.loop)
        return future.result(5)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class SplitTest(unittest.TestCase):
    def test_each_full_card_is_its_own_part_and_the_heading_rides_on_the_first(self):
        parts = feed_view.split_feed([REMINDER, LEARNING, WORK] + MORE, NOW)
        self.assertEqual([card for _, card in parts], [REMINDER, LEARNING, WORK, None])
        self.assertIn("Your Cardlake feed", parts[0][0])
        self.assertIn("Call mum", parts[0][0])
        self.assertNotIn("Your Cardlake feed", parts[1][0])
        self.assertIn("Bookmark 0", parts[3][0])
        self.assertIn("…and 3 more in Cardlake.", parts[3][0])

    def test_every_parts_first_link_is_cardlake_so_telegram_previews_it_not_a_video(self):
        video = {"id": "v", "type": "learning", "title": "A talk", "metadata": {"url": "https://www.youtube.com/watch?v=x"}}
        parts = feed_view.split_feed([REMINDER, WORK, LEARNING, video] + MORE, NOW)
        tail = parts[-1][0]
        self.assertTrue(tail.startswith("**[More in your feed](https://cardlake.app/vault/)**"))
        self.assertLess(tail.index("cardlake.app"), tail.index("youtube.com"))

    def test_no_part_carries_the_link_line(self):
        for text, _ in feed_view.split_feed([REMINDER] + MORE, NOW):
            self.assertNotIn("Open Cardlake:", text)

    def test_a_short_feed_has_no_tail_part(self):
        parts = feed_view.split_feed([REMINDER, WORK], NOW)
        self.assertEqual([card for _, card in parts], [REMINDER, WORK])

    def test_the_single_message_is_unchanged(self):
        text = feed_view.render_feed([REMINDER, LEARNING, WORK] + MORE, NOW)
        self.assertTrue(text.startswith("**[🗂 Your Cardlake feed](https://cardlake.app/vault/)**"))
        self.assertTrue(text.endswith("Open Cardlake: https://cardlake.app/vault/"))

    def test_today_drops_the_reply_hint_when_it_has_buttons(self):
        self.assertIn("Reply", feed_view.render_today([REMINDER], NOW))
        self.assertNotIn("Reply", "".join(t for t, _ in feed_view.split_today([REMINDER], NOW)))


class KeyboardTest(unittest.TestCase):
    def test_reminders_and_learnings_get_done(self):
        for card in (REMINDER, LEARNING):
            rows = buttons.keyboard_rows(card)
            self.assertEqual([[b["text"] for b in r] for r in rows], [["✅ Done", "⏰ Tomorrow", "📅 Next week"]])

    def test_other_cards_only_snooze(self):
        rows = buttons.keyboard_rows(WORK)
        self.assertEqual([[b["text"] for b in r] for r in rows], [["⏰ Tomorrow", "📅 Next week"]])

    def test_the_last_message_links_to_cardlake(self):
        rows = buttons.keyboard_rows(None, last=True)
        self.assertEqual(rows, [[{"text": "🔗 Open Cardlake", "url": "https://cardlake.app/vault/"}]])

    def test_a_used_card_says_what_happened(self):
        rows = buttons.keyboard_rows(REMINDER, "Done")
        self.assertEqual([[b["text"] for b in r] for r in rows], [["✓ Done"]])


class FeedWithButtonsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = ButtonsCtx(feed=[REMINDER, LEARNING, WORK] + MORE)
        self.h = Harness(self.ctx)
        self.reply = self.h.feed()

    def tearDown(self):
        self.h.close()

    def test_one_message_per_card_then_the_rest_with_the_link(self):
        self.assertEqual(self.reply, "")  # already posted; Hermes has nothing to send
        self.assertEqual(len(self.ctx.posts), 4)
        self.assertEqual(self.h.keyboard(1), [["✅ Done", "⏰ Tomorrow", "📅 Next week"]])
        self.assertEqual(self.h.keyboard(3), [["⏰ Tomorrow", "📅 Next week"]])
        self.assertEqual(self.h.keyboard(4), [["🔗 Open Cardlake"]])

    def test_each_button_changes_its_own_card(self):
        self.assertEqual(self.h.tap(1, "clk:d"), "Done: Call mum")
        self.h.tap(2, "clk:d")
        self.h.tap(3, "clk:w")
        self.assertEqual(self.ctx.written(), [
            ("update_reminder", {"id": "r1", "completed": True}),
            ("update_learning", {"id": "l1", "status": "watched"}),
            ("snooze_card", {"card_type": "work", "card_id": "w1", "days": 7}),
        ])

    def test_tomorrow_snoozes_a_day(self):
        self.h.tap(1, "clk:t")
        self.assertEqual(self.ctx.written(), [("snooze_card", {"card_type": "reminder", "card_id": "r1", "days": 1})])

    def test_a_card_is_changed_once_and_its_buttons_say_so(self):
        self.h.tap(1, "clk:d")
        self.assertEqual(self.h.tap(1, "clk:t"), "Already done.")
        self.assertEqual(len(self.ctx.written()), 1)
        self.assertEqual(self.h.keyboard(1), [["✓ Done"]])
        self.assertEqual(self.h.keyboard(2), [["✅ Done", "⏰ Tomorrow", "📅 Next week"]])

    def test_work_items_have_no_done(self):
        self.assertIn("doesn't apply", self.h.tap(3, "clk:d"))
        self.assertEqual(self.ctx.written(), [])

    def test_crafted_taps_change_nothing(self):
        for message_id, data in ((4, "clk:d"), (99, "clk:d"), (1, "clk:x"), (1, "clk:d:2")):
            self.h.tap(message_id, data)
        self.assertEqual(self.ctx.written(), [])

    def test_group_chats_are_refused(self):
        self.assertIn("private chat", self.h.tap(1, "clk:d", chat_type="group"))
        self.assertEqual(self.ctx.written(), [])

    def test_a_failed_update_says_so_and_can_be_retried(self):
        self.ctx.connected = False
        self.assertIn("Couldn't update Cardlake", self.h.tap(1, "clk:d"))
        self.ctx.connected = True
        self.assertEqual(self.h.tap(1, "clk:d"), "Done: Call mum")


class ShortFeedTest(unittest.TestCase):
    def test_the_link_goes_on_the_last_card_when_nothing_follows(self):
        ctx = ButtonsCtx(feed=[REMINDER, WORK])
        h = Harness(ctx)
        try:
            h.feed()
            self.assertEqual(len(ctx.posts), 2)
            self.assertEqual(h.keyboard(2), [["⏰ Tomorrow", "📅 Next week"], ["🔗 Open Cardlake"]])
        finally:
            h.close()


class WhenButtonsAreLeftOutTest(unittest.TestCase):
    def run_feed(self, ctx, attached=True):
        h = Harness(ctx, attached)
        try:
            return h.feed(), h
        finally:
            h.close()

    def test_other_platforms_get_one_plain_message(self):
        ctx = ButtonsCtx(surface="cli", feed=[REMINDER])
        reply, _ = self.run_feed(ctx)
        self.assertIn("Call mum", reply)
        self.assertEqual(ctx.posts, [])

    def test_older_hermes_without_the_telegram_hook_gets_one_plain_message(self):
        ctx = ButtonsCtx(feed=[REMINDER])
        reply, _ = self.run_feed(ctx, attached=False)
        self.assertIn("Open Cardlake: https://cardlake.app/vault/", reply)

    def test_group_chats_get_one_message_without_buttons(self):
        ctx = ButtonsCtx(chat_id="-100123", feed=[REMINDER, WORK] + MORE)
        reply, h = self.run_feed(ctx)
        self.assertEqual(reply, "")
        self.assertEqual(len(ctx.posts), 1)
        self.assertIn("Customer interviews", ctx.posts[0])
        self.assertIn("Open Cardlake: https://cardlake.app/vault/", ctx.posts[0])
        self.assertEqual(h.buttons.bot.keyboards, {})

    def test_a_failed_post_falls_back_to_text(self):
        ctx = ButtonsCtx(posted=False, feed=[REMINDER])
        reply, _ = self.run_feed(ctx)
        self.assertIn("Call mum", reply)

    def test_an_empty_today_is_one_plain_message(self):
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
