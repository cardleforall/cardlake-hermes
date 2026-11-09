"""Cards in Telegram: one message per card with its buttons, Undo, the pinned Today checklist, Deal
me 5, video previews on learning cards, the morning message, and when all of it is left out."""

import asyncio
import json
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from tests.helpers import FakeCtx, load

plugin = load()
buttons = load("buttons")
commands = load("commands")
feed_view = load("feed_view")

REMINDER = {"id": "r1", "type": "reminder", "title": "Call mum",
            "metadata": {"due_date": "2020-01-01T00:00:00.000Z", "recurrence": "weekly"}}
PINNED = {"id": "p1", "type": "reminder", "title": "Send the pilot proposal", "pinned_at": "2026-10-24",
          "metadata": {"due_date": "2026-10-28T04:30:00.000Z"}}
LEARNING = {"id": "l1", "type": "learning", "title": "Sal Khan on AI tutors",
            "metadata": {"url": "https://www.youtube.com/watch?v=abc", "status": "saved"}}
WORK = {"id": "w1", "type": "work", "title": "Customer interviews", "metadata": {}}
BOOKMARK = {"id": "b1", "type": "bookmark", "title": "An article", "metadata": {"url": "https://example.com/a"}}
MORE = [{"id": f"m{i}", "type": "bookmark", "title": f"Bookmark {i}", "metadata": {}} for i in range(8)]
NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


class FakeBot:
    """Records what the plugin sends to Telegram."""

    def __init__(self, refuse_markdown=False):
        self.sent = {}  # message id -> {"text", "rows", "preview", "parse_mode"}
        self.pinned, self.unpinned = [], []
        self.refuse_markdown = refuse_markdown

    async def send_message(self, chat_id, text, reply_markup=None, link_preview_options=None, parse_mode=None):
        if parse_mode and self.refuse_markdown:
            raise RuntimeError("Bad Request: can't parse entities")
        message_id = len(self.sent) + 1
        self.sent[message_id] = {"chat": chat_id, "text": text, "rows": reply_markup,
                                 "preview": link_preview_options, "parse_mode": parse_mode}
        return SimpleNamespace(message_id=message_id)

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        self.sent[int(message_id)]["rows"] = reply_markup

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.sent[int(message_id)]["text"] = text

    async def pin_chat_message(self, chat_id, message_id, disable_notification=False):
        self.pinned.append((chat_id, message_id, disable_notification))

    async def unpin_chat_message(self, chat_id, message_id):
        self.unpinned.append((chat_id, message_id))


class FakeState:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return json.loads(json.dumps(self.data.get(key, default)))

    def set(self, key, value):
        self.data[key] = json.loads(json.dumps(value))


TELEGRAM_DM = {"HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "42"}
MORNING_JOB = {"HERMES_SESSION_PLATFORM": "", "HERMES_CRON_AUTO_DELIVER_PLATFORM": "telegram",
               "HERMES_CRON_AUTO_DELIVER_CHAT_ID": "42"}


class Harness:
    """The plugin's Telegram side on a real event loop in another thread, as on the gateway."""

    def __init__(self, feed=(), env=TELEGRAM_DM, attached=True, bot=None):
        self.ctx = FakeCtx(feed=list(feed))
        self.ctx.state = FakeState()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.cards = buttons.TelegramCards(self.ctx, lambda tool, args: commands.call_cardlake(self.ctx, tool, args),
                                           session_env=lambda name: env.get(name, ""))
        self.bot = bot or FakeBot()
        if attached:
            self.cards.bot, self.cards.loop = self.bot, self.loop
            self.cards.markup = lambda rows: rows
            self.cards.preview = lambda url: {"url": url} if url else {"disabled": True}
            self.cards.format = lambda text: f"<{text}>"

    def run(self, verb):
        return commands.handle(self.ctx, verb, self.cards)

    def text(self, message_id):
        return self.bot.sent[message_id]["text"]

    def keyboard(self, message_id):
        return [[b["text"] for b in row] for row in self.bot.sent[message_id]["rows"] or []]

    def tap(self, message_id, data, chat_type="private", chat_id="42"):
        future = asyncio.run_coroutine_threadsafe(
            self.cards.tap(chat_id, str(message_id), chat_type, data), self.loop)
        return future.result(5)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class HarnessTest(unittest.TestCase):
    feed = ()
    env = TELEGRAM_DM

    def setUp(self):
        self.h = Harness(self.feed, self.env)

    def tearDown(self):
        self.h.close()


# Layout -------------------------------------------------------------------------------------------

class SplitTest(unittest.TestCase):
    def test_each_full_card_is_its_own_part_and_the_heading_rides_on_the_first(self):
        parts = feed_view.split_feed([REMINDER, LEARNING, WORK] + MORE, NOW)
        self.assertEqual([card for _, card in parts], [REMINDER, LEARNING, WORK, None])
        self.assertIn("Your Cardlake feed", parts[0][0])
        self.assertNotIn("Your Cardlake feed", parts[1][0])
        self.assertIn("…and 3 more in Cardlake.", parts[3][0])

    def test_the_rest_of_the_feed_starts_with_a_cardlake_link(self):
        video = dict(LEARNING, id="v")
        tail = feed_view.split_feed([REMINDER, WORK, PINNED, video] + MORE, NOW)[-1][0]
        self.assertTrue(tail.startswith("**[More in your feed](https://cardlake.app/vault/)**"))

    def test_no_part_carries_the_link_line(self):
        for text, _ in feed_view.split_feed([REMINDER] + MORE, NOW):
            self.assertNotIn("Open Cardlake:", text)

    def test_the_single_message_is_unchanged(self):
        text = feed_view.render_feed([REMINDER, LEARNING, WORK] + MORE, NOW)
        self.assertTrue(text.startswith("**[🗂 Your Cardlake feed](https://cardlake.app/vault/)**"))
        self.assertTrue(text.endswith("Open Cardlake: https://cardlake.app/vault/"))

    def test_today_gives_up_to_five_cards_buttons_and_leaves_the_heading_to_the_checklist(self):
        due = [dict(REMINDER, id=f"r{i}", title=f"Due {i}") for i in range(6)]
        parts = feed_view.split_today(due, NOW)
        self.assertEqual(sum(1 for _, card in parts if card), 5)
        self.assertNotIn("Today in Cardlake", parts[0][0])
        self.assertNotIn("Reply", "".join(t for t, _ in parts))
        self.assertIn("Reply", feed_view.render_today(due, NOW))

    def test_only_learning_cards_preview_their_link(self):
        self.assertEqual(feed_view.video_url(LEARNING), "https://www.youtube.com/watch?v=abc")
        self.assertEqual(feed_view.video_url(BOOKMARK), "")
        self.assertEqual(feed_view.video_url(dict(LEARNING, metadata={"url": "javascript:alert(1)"})), "")


class ChecklistTest(unittest.TestCase):
    def test_lists_each_card_and_ticks_it_off(self):
        text = feed_view.checklist([PINNED, REMINDER], NOW, {"r1": "Done"})
        self.assertIn("☀️ Today in Cardlake, Sat 7 Nov", text)
        self.assertIn("⬜ Send the pilot proposal", text)
        self.assertIn("✅ Call mum · done", text)
        self.assertNotIn("Nothing left", text)

    def test_the_heading_counts_only_whats_left(self):
        due_today = dict(REMINDER, id="r2", title="Due today", metadata={"due_date": "2026-11-07"})
        self.assertIn("2 overdue, 1 due today", feed_view.checklist([PINNED, REMINDER, due_today], NOW, {}))
        self.assertIn("1 overdue, 1 due today left", feed_view.checklist([PINNED, REMINDER, due_today], NOW, {"r1": "Done"}))

    def test_says_all_clear_when_every_card_is_handled(self):
        text = feed_view.checklist([PINNED, REMINDER], NOW, {"r1": "Done", "p1": "Snoozed for a week"})
        self.assertIn("all clear ✓", text)
        self.assertIn("📅 Send the pilot proposal · snoozed for a week", text)
        self.assertIn("Nothing left for today.", text)


class DealTest(unittest.TestCase):
    def test_deals_five_cards_that_arent_already_asking_for_attention(self):
        cards = [REMINDER, PINNED, LEARNING, WORK, BOOKMARK] + MORE
        dealt = feed_view.deal(cards, NOW, pick=lambda pool, k: pool[:k])
        self.assertEqual(len(dealt), 5)
        self.assertNotIn(REMINDER, dealt)  # overdue
        self.assertNotIn(PINNED, dealt)

    def test_deals_fewer_when_the_feed_is_small_and_says_so_when_empty(self):
        self.assertEqual(feed_view.deal([WORK], NOW), [WORK])
        self.assertIn("Nothing to deal", feed_view.render_deal([], NOW))

    def test_every_dealt_card_gets_its_own_message(self):
        parts = feed_view.split_deal([LEARNING, WORK, BOOKMARK] + MORE[:2], NOW)
        self.assertEqual(len(parts), 5)
        self.assertIn("Deal me 5", parts[0][0])


# Buttons ------------------------------------------------------------------------------------------

class KeyboardTest(unittest.TestCase):
    def rows(self, *args, **kwargs):
        return [[b["text"] for b in r] for r in buttons.keyboard_rows(*args, **kwargs)]

    def test_reminders_and_learnings_get_done(self):
        for card in (REMINDER, LEARNING):
            self.assertEqual(self.rows(card), [["✅ Done", "⏰ Tomorrow", "📅 Next week"]])

    def test_other_cards_only_snooze(self):
        self.assertEqual(self.rows(WORK), [["⏰ Tomorrow", "📅 Next week"]])

    def test_a_used_card_says_what_happened_and_offers_undo(self):
        self.assertEqual(self.rows(REMINDER, "Done"), [["✓ Done", "↩ Undo"]])

    def test_the_last_message_links_to_cardlake(self):
        self.assertEqual(buttons.keyboard_rows(None, last=True),
                         [[{"text": "🔗 Open Cardlake", "url": "https://cardlake.app/vault/"}]])

    def test_button_data_fits_telegrams_limit(self):
        for row in buttons.keyboard_rows(REMINDER, last=True) + buttons.keyboard_rows(REMINDER, "Done"):
            for button in row:
                self.assertLessEqual(len(button.get("callback_data", "").encode()), 64)


class UndoPlanTest(unittest.TestCase):
    def test_undoing_a_snooze_brings_the_card_back_and_pins_it_again(self):
        (tool, args), said, undo = buttons.action_for(PINNED, "w")
        self.assertEqual((tool, args["days"], said), ("snooze_card", 7, "Snoozed for a week"))
        self.assertEqual(undo, [("unsnooze_card", {"card_type": "reminder", "card_id": "p1"}),
                                ("pin_card", {"card_type": "reminder", "card_id": "p1"})])

    def test_undoing_done_restores_the_reminder_and_its_date(self):
        _, _, undo = buttons.action_for(PINNED, "d")
        self.assertEqual(undo[0], ("update_reminder", {"id": "p1", "completed": False,
                                                       "due_date": "2026-10-28T04:30:00+00:00"}))

    def test_undoing_done_on_a_repeating_reminder_brings_it_back_from_its_next_date(self):
        _, _, undo = buttons.action_for(REMINDER, "d")
        self.assertEqual(undo, [("update_reminder", {"id": "r1", "completed": False, "due_date": "2020-01-01"}),
                                ("unsnooze_card", {"card_type": "reminder", "card_id": "r1"})])

    def test_undoing_watched_puts_the_learning_back_as_it_was(self):
        _, said, undo = buttons.action_for(LEARNING, "d")
        self.assertEqual(said, "Marked as watched")
        self.assertEqual(undo, [("update_learning", {"id": "l1", "status": "saved"})])


class FeedWithButtonsTest(HarnessTest):
    feed = [LEARNING, WORK, BOOKMARK] + MORE

    def setUp(self):
        super().setUp()
        self.reply = self.h.run("feed")

    def test_one_formatted_message_per_card_then_the_rest_with_the_link(self):
        self.assertEqual(self.reply, "")  # already sent; Hermes has nothing to send
        self.assertEqual(len(self.h.bot.sent), 4)
        self.assertTrue(self.h.text(1).startswith("<**[🗂 Your Cardlake feed]"))
        self.assertEqual(self.h.bot.sent[1]["parse_mode"], "MarkdownV2")
        self.assertEqual(self.h.keyboard(1), [["✅ Done", "⏰ Tomorrow", "📅 Next week"]])
        self.assertEqual(self.h.keyboard(2), [["⏰ Tomorrow", "📅 Next week"]])
        self.assertEqual(self.h.keyboard(4), [["🔗 Open Cardlake"]])
        self.assertEqual(self.h.bot.pinned, [])  # only Today is pinned

    def test_a_learning_card_previews_its_video_and_nothing_else_previews(self):
        self.assertEqual(self.h.bot.sent[1]["preview"], {"url": "https://www.youtube.com/watch?v=abc"})
        for message_id in (2, 3, 4):
            self.assertEqual(self.h.bot.sent[message_id]["preview"], {"disabled": True})

    def test_each_button_changes_its_own_card(self):
        self.assertEqual(self.h.tap(1, "clk:d"), "Marked as watched: Sal Khan on AI tutors")
        self.h.tap(2, "clk:w")
        self.h.tap(3, "clk:t")
        self.assertEqual(self.h.ctx.written(), [
            ("update_learning", {"id": "l1", "status": "watched"}),
            ("snooze_card", {"card_type": "work", "card_id": "w1", "days": 7}),
            ("snooze_card", {"card_type": "bookmark", "card_id": "b1", "days": 1}),
        ])

    def test_a_card_is_changed_once_and_its_buttons_say_so(self):
        self.h.tap(2, "clk:t")
        self.assertEqual(self.h.tap(2, "clk:w"), "Already snoozed until tomorrow.")
        self.assertEqual(len(self.h.ctx.written()), 1)
        self.assertEqual(self.h.keyboard(2), [["✓ Snoozed until tomorrow", "↩ Undo"]])

    def test_undo_reverses_the_change_and_brings_the_buttons_back(self):
        self.h.tap(2, "clk:w")
        self.assertEqual(self.h.tap(2, "clk:u"), "Undone: Customer interviews")
        self.assertEqual(self.h.ctx.written()[-1], ("unsnooze_card", {"card_type": "work", "card_id": "w1"}))
        self.assertEqual(self.h.keyboard(2), [["⏰ Tomorrow", "📅 Next week"]])
        self.assertEqual(self.h.tap(2, "clk:u"), "Nothing to undo.")

    def test_work_items_have_no_done(self):
        self.assertIn("doesn't apply", self.h.tap(2, "clk:d"))
        self.assertEqual(self.h.ctx.written(), [])

    def test_crafted_taps_change_nothing(self):
        for message_id, data in ((4, "clk:d"), (99, "clk:d"), (1, "clk:x"), (1, "clk:d:2"), (4, "clk:u")):
            self.h.tap(message_id, data)
        self.assertEqual(self.h.ctx.written(), [])

    def test_group_chats_are_refused(self):
        self.assertIn("private chat", self.h.tap(1, "clk:d", chat_type="group"))
        self.assertEqual(self.h.ctx.written(), [])

    def test_a_failed_update_says_so_and_can_be_retried(self):
        self.h.ctx.connected = False
        self.assertIn("Couldn't update Cardlake", self.h.tap(2, "clk:t"))
        self.h.ctx.connected = True
        self.assertEqual(self.h.tap(2, "clk:t"), "Snoozed until tomorrow: Customer interviews")


class TodayWithButtonsTest(HarnessTest):
    feed = [PINNED, REMINDER, WORK]

    def setUp(self):
        super().setUp()
        self.reply = self.h.run("today")

    def test_a_pinned_checklist_comes_first_then_each_card(self):
        self.assertEqual(self.reply, "")
        self.assertIn("Today in Cardlake", self.h.text(1))
        self.assertIn("⬜ Send the pilot proposal", self.h.text(1))
        self.assertIn("⬜ Call mum", self.h.text(1))
        self.assertEqual(self.h.bot.pinned, [(42, 1, True)])
        self.assertIn("Send the pilot proposal", self.h.text(2))
        self.assertEqual(self.h.keyboard(3), [["✅ Done", "⏰ Tomorrow", "📅 Next week"], ["🔗 Open Cardlake"]])
        self.assertEqual(len(self.h.bot.sent), 3)  # the work item isn't due

    def test_taps_tick_the_checklist_off_until_all_clear_and_undo_unticks(self):
        self.h.tap(3, "clk:d")
        self.assertIn("✅ Call mum · done", self.h.text(1))
        self.h.tap(2, "clk:w")
        self.assertIn("Nothing left for today.", self.h.text(1))
        self.h.tap(3, "clk:u")
        self.assertIn("⬜ Call mum", self.h.text(1))
        self.assertNotIn("Nothing left", self.h.text(1))

    def test_the_next_today_replaces_the_pin(self):
        self.h.run("today")
        self.assertEqual(self.h.bot.unpinned, [(42, 1)])
        self.assertEqual(self.h.bot.pinned[-1], (42, 4, True))
        self.assertEqual(self.h.ctx.state.get("pinned_today"), {"42": 4})


class DealWithButtonsTest(HarnessTest):
    feed = [REMINDER, LEARNING, WORK, BOOKMARK] + MORE

    def test_deal_sends_five_cards_each_with_buttons(self):
        self.assertEqual(self.h.run("deal"), "")
        self.assertEqual(len(self.h.bot.sent), 5)
        self.assertIn("Deal me 5", self.h.text(1))
        self.assertNotIn("Call mum", "".join(m["text"] for m in self.h.bot.sent.values()))
        self.assertEqual(self.h.keyboard(5)[-1], ["🔗 Open Cardlake"])


class MorningWithButtonsTest(HarnessTest):
    feed = [PINNED, REMINDER]
    env = MORNING_JOB

    def test_the_morning_job_sends_the_cards_itself_and_stays_silent(self):
        result = json.loads(plugin.today_tool(self.h.ctx, {}, self.h.cards))
        self.assertEqual(result, {"text": "[SILENT]"})
        self.assertIn("Today in Cardlake", self.h.text(1))
        self.assertEqual(len(self.h.bot.sent), 3)
        self.assertEqual(self.h.bot.pinned, [(42, 1, True)])

    def test_the_morning_job_never_changes_a_card_by_itself(self):
        plugin.today_tool(self.h.ctx, {}, self.h.cards)
        self.assertEqual(self.h.ctx.written(), [])


class MorningWithoutButtonsTest(unittest.TestCase):
    def test_elsewhere_the_morning_job_returns_the_text(self):
        h = Harness([PINNED], env={"HERMES_CRON_AUTO_DELIVER_PLATFORM": "signal"})
        try:
            result = json.loads(plugin.today_tool(h.ctx, {}, h.cards))
        finally:
            h.close()
        self.assertIn("Send the pilot proposal", result["text"])
        self.assertEqual(h.bot.sent, {})

    def test_nothing_due_stays_silent(self):
        h = Harness([WORK], env=MORNING_JOB)
        try:
            self.assertEqual(json.loads(plugin.today_tool(h.ctx, {}, h.cards)), {"text": "[SILENT]"})
        finally:
            h.close()
        self.assertEqual(h.bot.sent, {})


SNOOZED = dict(PINNED, pinned_at=None, remind_later_until="2026-11-14T04:30:00.000Z")  # as list_feed names it


class FilterTest(unittest.TestCase):
    def test_every_word_the_help_names_is_a_filter(self):
        for word in ("reminders", "learning", "work", "family", "bookmarks", "misc", "github", "files",
                     "favorites", "snoozed"):
            self.assertIn(word, commands.USAGE)
            self.assertIsNotNone(feed_view.find_filter(word), word)

    def test_singulars_plurals_and_the_apps_own_names_work(self):
        for word, kind in (("Learnings", "learning"), ("reminder", "reminder"), ("GitHub issues", "kanban"),
                           ("Misc", "talking_point"), ("work items", "work"), ("favourites", None)):
            self.assertEqual(feed_view.find_filter(word).args.get("types", [None])[0], kind, word)

    def test_each_filter_asks_cardlake_for_just_that(self):
        for word, args in (("family", {"types": ["family"]}), ("favorites", {"liked_only": True}),
                           ("snoozed", {"view": "snoozed"})):
            ctx = FakeCtx(feed=[WORK])
            commands.handle(ctx, f"feed {word}")
            self.assertEqual(ctx.calls[-1], ("mcp__cardlake__list_feed", {"limit": 20, **args}))

    def test_the_heading_and_count_name_the_filter(self):
        text = commands.handle(FakeCtx(feed=[LEARNING, dict(LEARNING, id="l2")]), "feed learning")
        self.assertIn("📚 Your learnings", text)
        self.assertIn("· 2 cards", text)
        tail = feed_view.split_feed([LEARNING] * 4 + MORE, NOW, feed_view.find_filter("learning"))[-1][0]
        self.assertTrue(tail.startswith("**[More learnings]("))

    def test_an_empty_filter_says_so(self):
        self.assertIn("No family cards in your feed.", commands.handle(FakeCtx(feed=[]), "feed family"))
        self.assertIn("Nothing is snoozed.", commands.handle(FakeCtx(feed=[]), "feed snoozed"))

    def test_an_unknown_filter_lists_the_real_ones_and_asks_cardlake_nothing(self):
        ctx = FakeCtx(feed=[WORK])
        reply = commands.handle(ctx, "feed cats")
        self.assertIn('There\'s no "cats" filter', reply)
        self.assertIn("learning", reply)
        self.assertEqual(ctx.calls, [])

    def test_snoozed_cards_say_when_they_come_back(self):
        self.assertIn("⏰ back 14 Nov", feed_view.panel(SNOOZED, NOW))
        self.assertIn("⏰ back tomorrow", feed_view.panel(dict(SNOOZED, remind_later_until="2026-11-08T03:00:00Z"), NOW))
        self.assertIn("⏰ back 9 Nov", feed_view.panel(dict(WORK, snoozed_until="2026-11-09T03:00:00Z"), NOW))


class SnoozedWithButtonsTest(HarnessTest):
    feed = [SNOOZED]

    def setUp(self):
        super().setUp()
        self.h.run("feed snoozed")

    def test_snoozed_cards_only_offer_bring_back(self):
        self.assertEqual(self.h.keyboard(1), [["↩ Bring back"], ["🔗 Open Cardlake"]])
        for code in ("d", "t", "w"):
            self.assertIn("doesn't apply", self.h.tap(1, f"clk:{code}"))
        self.assertEqual(self.h.ctx.written(), [])

    def test_bring_back_unsnoozes_and_undo_snoozes_it_again_until_its_day(self):
        self.assertEqual(self.h.tap(1, "clk:b"), "Back in your feed: Send the pilot proposal")
        self.assertEqual(self.h.ctx.written(), [("unsnooze_card", {"card_type": "reminder", "card_id": "p1"})])
        self.h.tap(1, "clk:u")
        tool, args = self.h.ctx.written()[-1]
        self.assertEqual((tool, args["card_id"]), ("snooze_card", "p1"))
        self.assertGreaterEqual(args["days"], 1)


class WhenButtonsAreLeftOutTest(unittest.TestCase):
    def run_feed(self, env=TELEGRAM_DM, attached=True, bot=None, feed=(REMINDER, WORK)):
        h = Harness(feed, env, attached, bot)
        try:
            return h.run("feed"), h
        finally:
            h.close()

    def test_other_platforms_get_one_plain_message(self):
        reply, h = self.run_feed(env={"HERMES_SESSION_PLATFORM": "signal", "HERMES_SESSION_CHAT_ID": "42"})
        self.assertIn("Open Cardlake: https://cardlake.app/vault/", reply)
        self.assertEqual(h.bot.sent, {})

    def test_older_hermes_without_the_telegram_hook_gets_one_plain_message(self):
        reply, _ = self.run_feed(attached=False)
        self.assertIn("Call mum", reply)

    def test_group_chats_get_one_plain_message(self):
        reply, h = self.run_feed(env={"HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "-100123"})
        self.assertIn("Customer interviews", reply)
        self.assertEqual(h.bot.sent, {})

    def test_forum_topics_get_one_plain_message(self):
        reply, h = self.run_feed(env=dict(TELEGRAM_DM, HERMES_SESSION_THREAD_ID="7"))
        self.assertIn("Call mum", reply)
        self.assertEqual(h.bot.sent, {})

    def test_formatting_telegram_refuses_is_resent_as_plain_text(self):
        reply, h = self.run_feed(bot=FakeBot(refuse_markdown=True))
        self.assertEqual(reply, "")
        self.assertIsNone(h.bot.sent[1]["parse_mode"])
        self.assertNotIn("**", h.bot.sent[1]["text"])

    def test_an_empty_today_is_one_plain_message(self):
        h = Harness([WORK])
        try:
            reply = h.run("today")
        finally:
            h.close()
        self.assertIn("Nothing is overdue", reply)
        self.assertEqual(h.bot.sent, {})


class SlowCtx(FakeCtx):
    """Cardlake answering slowly: each change waits until the test lets it through."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.release = threading.Event()

    def dispatch_tool(self, name, args):
        if not name.endswith(("list_feed", "search_cards")):
            self.release.wait(5)
        return super().dispatch_tool(name, args)


class DoubleTapTest(unittest.TestCase):
    def test_a_second_tap_while_the_first_is_running_does_nothing(self):
        h = Harness([WORK])
        h.ctx = SlowCtx(feed=[WORK])
        h.cards.run_tool = lambda tool, args: commands.call_cardlake(h.ctx, tool, args)
        try:
            h.run("feed")
            first = asyncio.run_coroutine_threadsafe(h.cards.tap("42", "1", "private", "clk:t"), h.loop)
            for _ in range(100):  # until the first tap is waiting on Cardlake
                if h.cards.messages[("42", "1")].get("busy"):
                    break
                threading.Event().wait(0.01)
            self.assertEqual(h.tap(1, "clk:w"), "Still working on the last tap…")
            h.ctx.release.set()
            self.assertEqual(first.result(5), "Snoozed until tomorrow: Customer interviews")
            self.assertEqual(len(h.ctx.written()), 1)
            self.assertEqual(h.tap(1, "clk:u"), "Undone: Customer interviews")
        finally:
            h.close()


class BadRequest(Exception):
    """Named like python-telegram-bot's, which is what the plugin checks for."""


class FlakyBot(FakeBot):
    """Fails the first send with the given error, then works."""

    def __init__(self, error):
        super().__init__()
        self.error, self.attempts = error, 0

    async def send_message(self, *args, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            raise self.error
        return await super().send_message(*args, **kwargs)


class SendErrorsTest(unittest.TestCase):
    def run_feed(self, bot):
        h = Harness([WORK], bot=bot)
        try:
            return h.run("feed"), h
        finally:
            h.close()

    def test_a_network_error_is_not_resent_as_a_second_copy(self):
        # The first message may have arrived; Hermes' own plain reply is the one fallback.
        reply, h = self.run_feed(FlakyBot(TimeoutError("Timed out")))
        self.assertIn("Customer interviews", reply)
        self.assertEqual(h.bot.attempts, 1)

    def test_a_bad_request_is_resent_as_plain_text(self):
        reply, h = self.run_feed(FlakyBot(BadRequest("Can't find end of the entity")))
        self.assertEqual(reply, "")
        self.assertIsNone(h.bot.sent[1]["parse_mode"])

    def test_sending_too_fast_waits_and_sends_once(self):
        error = Exception("Flood control exceeded")
        error.retry_after = 0.01
        reply, h = self.run_feed(FlakyBot(error))
        self.assertEqual(reply, "")
        self.assertEqual(len(h.bot.sent), 1)
        self.assertEqual(h.bot.sent[1]["parse_mode"], "MarkdownV2")

    def test_a_long_wait_isnt_worth_it(self):
        error = Exception("Flood control exceeded")
        error.retry_after = 600
        reply, h = self.run_feed(FlakyBot(error))
        self.assertIn("Customer interviews", reply)

    def test_a_send_that_times_out_is_stopped(self):
        h = Harness([WORK])
        try:
            started = threading.Event()

            async def hang(*args, **kwargs):
                started.set()
                await asyncio.sleep(30)
            h.bot.send_message = hang
            original, buttons._SEND_TIMEOUT_SECONDS = buttons._SEND_TIMEOUT_SECONDS, 0.2
            try:
                reply = h.run("feed")
            finally:
                buttons._SEND_TIMEOUT_SECONDS = original
            self.assertIn("Customer interviews", reply)
            self.assertTrue(started.is_set())
            pending = asyncio.run_coroutine_threadsafe(_other_tasks(), h.loop).result(5)
            self.assertEqual(pending, 0)
        finally:
            h.close()


async def _other_tasks():
    await asyncio.sleep(0.05)  # let the cancellation land
    return len([t for t in asyncio.all_tasks() if t is not asyncio.current_task()])


if __name__ == "__main__":
    unittest.main()
