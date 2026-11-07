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
        self.assertEqual(feed_view.OPEN_LINK, f"{address.ADDRESS}/vault/")
        self.assertIn(f"--url {address.ADDRESS}/api/mcp", commands.CONNECT_COMMAND)


if __name__ == "__main__":
    unittest.main()
