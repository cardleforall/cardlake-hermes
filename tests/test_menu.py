"""/cardlake in Telegram's / menu: added after connecting when Hermes' own commands crowd it out."""

import asyncio
import sys
import types
import unittest
from types import SimpleNamespace

from tests.helpers import load

menu = load("menu")
buttons = load("buttons")


def cmd(name):
    return SimpleNamespace(command=name, description=name)


class FakeBot:
    """A bot with one menu per scope, like Telegram's."""

    def __init__(self, commands=(), fail=False):
        self.menus = {}
        self.start = [cmd(c) for c in commands]
        self.fail = fail
        self.sets = 0

    async def get_my_commands(self, scope=None):
        if self.fail:
            raise RuntimeError("Telegram is unreachable")
        return tuple(self.menus.get(scope, self.start))

    async def set_my_commands(self, commands, scope=None):
        self.menus[scope] = list(commands)
        self.sets += 1

    def names(self, scope):
        return [c.command for c in self.menus.get(scope, self.start)]


def run(coro):
    return asyncio.run(coro)


SCOPES = ("default", "private", "groups")
make = lambda: cmd(menu.COMMAND)


class AddIfMissingTest(unittest.TestCase):
    def test_adds_cardlake_after_hermes_commands_in_every_scope(self):
        bot = FakeBot(["help", "new", "stop"])
        self.assertTrue(run(menu.add_if_missing(bot, SCOPES, make)))
        for scope in SCOPES:
            self.assertEqual(bot.names(scope), ["help", "new", "stop", "cardlake"])

    def test_never_adds_it_twice(self):
        bot = FakeBot(["help", "cardlake"])
        self.assertFalse(run(menu.add_if_missing(bot, SCOPES, make)))
        self.assertEqual(bot.sets, 0)

    def test_a_full_menu_makes_room_within_telegrams_limit(self):
        bot = FakeBot([f"c{i}" for i in range(100)])
        run(menu.add_if_missing(bot, SCOPES, make))
        self.assertEqual(len(bot.names("private")), 100)
        self.assertEqual(bot.names("private")[-1], "cardlake")
        self.assertEqual(bot.names("private")[0], "c0")


class KeepInMenuTest(unittest.TestCase):
    def test_puts_it_back_after_hermes_rebuilds_its_menu(self):
        bot = FakeBot(["help"])
        rebuilt = []

        async def sleep(_seconds):
            if bot.menus:  # Hermes finishes its own menu after the first check
                bot.menus.clear()
                bot.start = [cmd("help"), cmd("new")]
                rebuilt.append(True)

        run(menu.keep_in_menu(bot, SCOPES, make, checks=(1, 2, 3), sleep=sleep))
        self.assertTrue(rebuilt)
        self.assertEqual(bot.names("private"), ["help", "new", "cardlake"])

    def test_an_unreachable_telegram_never_raises(self):
        async def sleep(_seconds):
            return None
        run(menu.keep_in_menu(FakeBot(fail=True), SCOPES, make, checks=(1, 2), sleep=sleep))


class UsersOwnMenuTest(unittest.TestCase):
    def test_a_menu_set_up_in_hermes_is_left_alone(self):
        config = {"platforms": {"telegram": {"extra": {"command_menu": {"priority": ["help"]}}}}}
        self.assertTrue(menu.menu_is_users(lambda: config))

    def test_otherwise_the_plugin_may_add_itself(self):
        self.assertFalse(menu.menu_is_users(lambda: {"platforms": {"telegram": {"extra": {}}}}))
        self.assertFalse(menu.menu_is_users(lambda: {}))

        def broken():
            raise OSError("no config")
        self.assertFalse(menu.menu_is_users(broken))


class AttachTest(unittest.TestCase):
    """attach() starts the check on Hermes' loop, using python-telegram-bot's own types."""

    def setUp(self):
        fake = types.ModuleType("telegram")
        for name in ("BotCommandScopeDefault", "BotCommandScopeAllPrivateChats", "BotCommandScopeAllGroupChats"):
            setattr(fake, name, type(name, (), {}))
        fake.BotCommand = lambda command, description: SimpleNamespace(command=command, description=description)
        self.saved = sys.modules.get("telegram")
        sys.modules["telegram"] = fake

    def tearDown(self):
        if self.saved is None:
            sys.modules.pop("telegram", None)
        else:
            sys.modules["telegram"] = self.saved

    def start(self, config):
        cards = buttons.TelegramCards(None, lambda tool, args: None, load_config=lambda: config)
        bot = FakeBot(["help"])

        async def connect():
            cards.loop = asyncio.get_running_loop()
            original, menu.CHECKS = menu.CHECKS, (0,)
            try:
                cards._keep_in_menu(bot)
                if cards._menu_task:
                    await cards._menu_task
            finally:
                menu.CHECKS = original
        run(connect())
        return bot

    def test_adds_cardlake_on_connect(self):
        bot = self.start({})
        self.assertEqual(bot.sets, 3)
        self.assertTrue(all(names[-1] == "cardlake" for names in (bot.names(s) for s in bot.menus)))

    def test_leaves_a_users_own_menu_alone(self):
        bot = self.start({"platforms": {"telegram": {"extra": {"command_menu": {"max_commands": 40}}}}})
        self.assertEqual(bot.sets, 0)


if __name__ == "__main__":
    unittest.main()
