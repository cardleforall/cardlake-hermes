"""Which Cardlake the links open: cardlake.app, or the self-hosted copy Hermes is connected to."""

import unittest

from tests.helpers import load

address = load("address")
feed_view = load("feed_view")
commands = load("commands")


def config(url):
    return lambda: {"mcp_servers": {"cardlake": {"url": url, "auth": "oauth"}}}


class AddressTest(unittest.TestCase):
    def test_cardlake_app_when_nothing_says_otherwise(self):
        self.assertEqual(address.cardlake_address({}, lambda: {}), "https://cardlake.app")

    def test_follows_the_connection_hermes_already_has(self):
        self.assertEqual(address.cardlake_address({}, config("https://cards.example.com/api/mcp")),
                         "https://cards.example.com")
        self.assertEqual(address.cardlake_address({}, config("http://localhost:3000/api/mcp/")),
                         "http://localhost:3000")
        self.assertEqual(address.cardlake_address({}, config("https://example.com/cardlake/api/mcp")),
                         "https://example.com/cardlake")

    def test_cardlake_url_overrides_the_connection(self):
        env = {"CARDLAKE_URL": "https://web.example.com/"}
        self.assertEqual(address.cardlake_address(env, config("https://api.example.com/api/mcp")),
                         "https://web.example.com")

    def test_other_servers_and_broken_config_fall_back(self):
        other = lambda: {"mcp_servers": {"github": {"url": "https://api.github.com/mcp"}}}
        self.assertEqual(address.cardlake_address({}, other), "https://cardlake.app")

        def broken():
            raise RuntimeError("no config")
        self.assertEqual(address.cardlake_address({}, broken), "https://cardlake.app")
        self.assertEqual(address.cardlake_address({}, lambda: {"mcp_servers": None}), "https://cardlake.app")

    def test_unsafe_addresses_are_ignored(self):
        for bad in ("javascript:alert(1)", "https://x.com/a b", "https://x.com/)[evil](https://e.com",
                    "ftp://x.com", "https://", "https://x.com/'\"", "  "):
            self.assertEqual(address.cardlake_address({"CARDLAKE_URL": bad}, config(bad)),
                             "https://cardlake.app", bad)

    def test_links_and_connect_hint_use_the_address(self):
        self.assertEqual(address.open_link(), f"{address.current()}/vault/")
        self.assertIn(f"--url {address.current()}/api/mcp", commands.connect_command())


class FollowsAChangedConnectionTest(unittest.TestCase):
    """Hermes reconnects to a changed connection without a restart, so the links must follow."""

    def setUp(self):
        self.url = "https://cardlake.app/api/mcp"
        self.now = 1000.0
        self.saved = (address._hermes_config, dict(address._cache))
        address._hermes_config = lambda: {"mcp_servers": {"cardlake": {"url": self.url}}}
        address._cache.update(address=None, at=0.0)
        self.clock = lambda: self.now

    def tearDown(self):
        address._hermes_config, cache = self.saved
        address._cache.clear()
        address._cache.update(cache)

    def test_the_address_is_reread_after_the_connection_changes(self):
        self.assertEqual(address.current(env={}, clock=self.clock), "https://cardlake.app")
        self.url = "https://cards.example.com/api/mcp"
        self.now += 5
        self.assertEqual(address.current(env={}, clock=self.clock), "https://cardlake.app")  # cached briefly
        self.now += 60
        self.assertEqual(address.current(env={}, clock=self.clock), "https://cards.example.com")

    def test_links_buttons_and_the_chat_guide_follow_it(self):
        self.url = "https://cards.example.com/api/mcp"
        plugin, buttons = load(), load("buttons")
        self.assertTrue(feed_view.with_open_link("x").endswith("Open Cardlake: https://cards.example.com/vault/"))
        self.assertEqual(buttons.keyboard_rows(None, last=True), [[{"text": "🔗 Open Cardlake", "url": "https://cards.example.com/vault/"}]])
        self.assertIn("Open Cardlake: https://cards.example.com/vault/", plugin.chat_guide())
        self.assertIn("--url https://cards.example.com/api/mcp", commands.not_connected())


class ReadsItsOwnProfileTest(unittest.TestCase):
    """Commands run outside Hermes' plugin-loading scope; the config must still be the profile's."""

    def setUp(self):
        import sys, types
        self.sys = sys
        self.saved = {k: sys.modules.get(k) for k in ("hermes_constants", "hermes_cli", "hermes_cli.config")}
        self.override = None
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: "/home/robin/.hermes/profiles/work"

        def set_override(path):
            previous, self.override = self.override, path
            return previous
        constants.set_hermes_home_override = set_override
        constants.reset_hermes_home_override = lambda token: setattr(self, "override", token)
        config = types.ModuleType("hermes_cli.config")
        homes = {"/home/robin/.hermes/profiles/work": "https://cards.example.com/api/mcp",
                 None: "https://cardlake.app/api/mcp"}
        config.load_config = lambda: {"mcp_servers": {"cardlake": {"url": homes[self.override]}}}
        sys.modules.update({"hermes_constants": constants, "hermes_cli": types.ModuleType("hermes_cli"),
                            "hermes_cli.config": config})
        self.home = address._home

    def tearDown(self):
        address._home = self.home
        for key, module in self.saved.items():
            if module is None:
                self.sys.modules.pop(key, None)
            else:
                self.sys.modules[key] = module

    def test_reads_the_home_it_was_loaded_for(self):
        address.remember_home()
        self.assertEqual(address.cardlake_address({}), "https://cards.example.com")
        self.assertIsNone(self.override)  # put back afterwards

    def test_without_a_remembered_home_reads_the_default(self):
        address._home = None
        self.assertEqual(address.cardlake_address({}), "https://cardlake.app")


if __name__ == "__main__":
    unittest.main()
