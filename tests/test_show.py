"""cardlake_show_cards: Hermes' own results as cards, saved to Cardlake only when the user taps."""

import json
import unittest

from tests.helpers import FakeCtx, load
from tests.test_buttons import TELEGRAM_DM, Harness

plugin = load()
show = load("show")
buttons = load("buttons")
commands = load("commands")

VIDEO = {"title": "How AI could save education", "kind": "learning",
         "lines": ["Sal Khan, TED 2023", "15 minutes"], "url": "https://www.youtube.com/watch?v=hJP5GqnTrNo"}
LINK = {"title": "Chrome memory report", "kind": "note", "status": "⚠️ 2 GB used",
        "lines": ["28 processes", "Reddit tabs left untouched"]}


class CreatingCtx(FakeCtx):
    """Like Cardlake: a create call answers with the new card's id."""

    def dispatch_tool(self, name, args):
        if self.connected and name.rsplit("__", 1)[1].startswith("create_"):
            self.calls.append((name, args))
            return json.dumps({"result": json.dumps({"id": "11111111-1111-4111-8111-111111111111"})})
        return super().dispatch_tool(name, args)


class CleanTest(unittest.TestCase):
    def test_keeps_what_it_should_and_caps_the_rest(self):
        heading, cards = show.clean({"heading": "Two **things**", "cards": [
            VIDEO, dict(LINK, lines=["x" * 400, "b", "c", "d"]), {"title": ""}, "nonsense"]})
        self.assertEqual(heading, "Two things")
        self.assertEqual([c["kind"] for c in cards], ["learning", "note"])
        self.assertEqual(len(cards[1]["lines"]), 3)
        self.assertLessEqual(len(cards[1]["lines"][0]), 160)

    def test_unsafe_links_are_dropped_and_the_kind_is_guessed_from_the_link(self):
        _, cards = show.clean({"cards": [{"title": "a", "url": "javascript:alert(1)"},
                                         {"title": "b", "url": "https://example.com/x"}]})
        self.assertEqual(cards[0]["metadata"]["url"], "")
        self.assertEqual([c["kind"] for c in cards], ["note", "link"])

    def test_at_most_eight_cards(self):
        _, cards = show.clean({"cards": [{"title": str(i)} for i in range(12)]})
        self.assertEqual(len(cards), 8)


class SaveTest(unittest.TestCase):
    def card(self, raw):
        return show.clean({"cards": [raw]})[1][0]

    def test_each_kind_saves_as_the_matching_cardlake_card(self):
        expected = {
            "learning": ("create_learning", "delete_learning", "Learning"),
            "link": ("create_bookmark", "delete_bookmark", "Bookmark"),
            "task": ("create_work_item", "delete_work_item", "Work item"),
            "reminder": ("create_reminder", "delete_reminder", "Reminder"),
            "note": ("create_talking_point", "delete_talking_point", "Misc card"),
        }
        for kind, (create, delete, label) in expected.items():
            tool, args, undo_tool, saved_as = show.save_call(self.card({"title": "T", "kind": kind}))
            self.assertEqual((tool, undo_tool, saved_as), (create, delete, label), kind)

    def test_a_learning_keeps_its_link_and_lines(self):
        _, args, _, _ = show.save_call(self.card(VIDEO))
        self.assertEqual(args["url"], VIDEO["url"])
        self.assertEqual(args["notes"], "Sal Khan, TED 2023\n15 minutes")

    def test_remind_me_makes_tomorrows_reminder_with_the_link(self):
        tool, args = show.remind_call(self.card(VIDEO))
        self.assertEqual(tool, "create_reminder")
        self.assertIn(VIDEO["url"], args["title"])
        self.assertRegex(args["due_date"], r"^\d{4}-\d{2}-\d{2}$")


class ShowToolTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness(env=TELEGRAM_DM)
        self.h.ctx = CreatingCtx()
        self.h.cards.ctx = self.h.ctx
        self.h.cards.run_tool = lambda tool, args: commands.call_cardlake(self.h.ctx, tool, args)

    def tearDown(self):
        self.h.close()

    def test_sends_each_card_with_save_and_remind_and_asks_hermes_not_to_repeat_them(self):
        result = json.loads(show.show_tool(self.h.cards, {"heading": "For you", "cards": [VIDEO, LINK]}))
        self.assertEqual(result["shown"], 2)
        self.assertIn("Don't repeat", result["note"])
        self.assertIn("For you", self.h.text(1))
        self.assertIn("⚠️ 2 GB used", self.h.text(2))
        self.assertEqual(self.h.keyboard(1), [["💾 Save to Cardlake", "⏰ Remind me"]])
        self.assertEqual(self.h.keyboard(2), [["💾 Save to Cardlake", "⏰ Remind me"], ["🔗 Open Cardlake"]])
        self.assertEqual(self.h.bot.sent[1]["preview"], {"url": VIDEO["url"]})

    def test_nothing_is_saved_until_a_tap_and_undo_deletes_what_the_tap_made(self):
        show.show_tool(self.h.cards, {"cards": [VIDEO]})
        self.assertEqual(self.h.ctx.calls, [])
        self.assertEqual(self.h.tap(1, "clk:s"), "Saved as Learning: How AI could save education")
        self.assertEqual(self.h.ctx.calls[0][0], "mcp__cardlake__create_learning")
        self.assertEqual(self.h.keyboard(1), [["✓ Saved as Learning", "↩ Undo"], ["🔗 Open Cardlake"]])
        self.h.tap(1, "clk:u")
        self.assertEqual(self.h.ctx.calls[-1], ("mcp__cardlake__delete_learning", {"id": "11111111-1111-4111-8111-111111111111"}))
        self.assertEqual(self.h.keyboard(1)[0], ["💾 Save to Cardlake", "⏰ Remind me"])

    def test_remind_me_creates_a_reminder(self):
        show.show_tool(self.h.cards, {"cards": [LINK]})
        self.assertEqual(self.h.tap(1, "clk:r"), "Reminder for tomorrow: Chrome memory report")
        self.assertEqual(self.h.ctx.calls[0][0], "mcp__cardlake__create_reminder")

    def test_feed_buttons_dont_work_on_shown_cards(self):
        show.show_tool(self.h.cards, {"cards": [VIDEO]})
        for code in ("d", "t", "w", "b"):
            self.assertIn("doesn't apply", self.h.tap(1, f"clk:{code}"))
        self.assertEqual(self.h.ctx.calls, [])

    def test_without_an_id_back_there_is_no_undo(self):
        self.h.ctx = FakeCtx()  # answers {"id": "new"}... so make it answer nothing useful
        self.h.ctx.dispatch_tool = lambda name, args: json.dumps({"result": "ok"})
        self.h.cards.run_tool = lambda tool, args: commands.call_cardlake(self.h.ctx, tool, args)
        show.show_tool(self.h.cards, {"cards": [LINK]})
        self.h.tap(1, "clk:s")
        self.assertEqual(self.h.keyboard(1)[0], ["✓ Saved as Misc card"])


class ShowToolElsewhereTest(unittest.TestCase):
    def test_returns_the_cards_as_text_for_hermes_to_reply_with(self):
        h = Harness(env={"HERMES_SESSION_PLATFORM": "signal", "HERMES_SESSION_CHAT_ID": "42"})
        try:
            result = json.loads(show.show_tool(h.cards, {"cards": [VIDEO]}))
        finally:
            h.close()
        self.assertEqual(result["shown"], 0)
        self.assertIn("How AI could save education", result["text"])
        self.assertEqual(h.bot.sent, {})

    def test_bad_input_is_an_error_not_a_crash(self):
        self.assertIn("error", json.loads(show.show_tool(None, {"cards": [{"title": ""}]})))
        self.assertIn("error", json.loads(show.show_tool(None, {"cards": "nope"})) | {"error": 1})

    def test_hermes_is_told_when_to_use_it(self):
        self.assertIn("cardlake_show_cards", plugin.chat_guide())
        self.assertIn("one short line", show.SHOW_SCHEMA["description"])


if __name__ == "__main__":
    unittest.main()
