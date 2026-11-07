"""Runs against an installed copy of Hermes; skipped when it isn't there.

Uses Hermes's own plugin loader, session store, blueprint form and tool-call hook, with
a temporary home folder. It makes no network calls and no model calls.
"""

import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from .helpers import ROOT, load

try:
    from hermes_state import SessionDB
    from hermes_cli.plugins import PluginManager
except ImportError:  # Hermes isn't installed
    SessionDB = None

conversations = load("conversations")


@unittest.skipIf(SessionDB is None, "Hermes isn't installed")
class RealHermesTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        patcher = patch.dict(os.environ, {"HERMES_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _manager(self):
        target = self.home / "plugins" / "cardlake"
        shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (self.home / "config.yaml").write_text("plugins:\n  enabled:\n    - cardlake\n", encoding="utf-8")
        manager = PluginManager()
        manager.discover_and_load()
        return manager

    def test_loader_registers_the_command_hook_and_blueprint(self):
        manager = self._manager()
        self.assertIn("cardlake", manager._plugin_commands)
        self.assertIn("cardlake:morning-briefing", manager._automation_blueprints)

    def test_blueprint_form_makes_a_morning_telegram_job(self):
        from cron.blueprint_catalog import fill_blueprint
        blueprint = self._manager()._automation_blueprints["cardlake:morning-briefing"]
        job = fill_blueprint(blueprint, {"time": "07:15"})
        self.assertEqual(job["schedule"], "15 7 * * *")
        self.assertEqual(job["deliver"], "telegram")
        self.assertEqual(job["name"], load().BRIEFING_TITLE)
        self.assertIn("[SILENT]", job["prompt"])

    def test_reads_only_this_periods_messages_and_skips_scheduled_jobs(self):
        db = SessionDB()
        now = time.time()
        db.create_session("chat", "cli")
        db.set_session_title("chat", "Launch plan")
        db.append_message("chat", "user", "old message", timestamp=now - 7200)
        db.append_message("chat", "user", "email Sam", timestamp=now - 60)
        db.append_message("chat", "assistant", "Noted", timestamp=now - 50)
        db.append_message("chat", "tool", "tool noise", timestamp=now - 40)
        db.create_session("job", "cron")
        db.append_message("job", "assistant", "briefing text", timestamp=now - 30)
        db.close()

        end = datetime.fromtimestamp(now).astimezone()
        batch = conversations.read_conversations(end - timedelta(hours=1), end)
        self.assertEqual([c.title for c in batch.conversations], ["Launch plan"])
        text = batch.conversations[0].text
        self.assertIn("user: email Sam", text)
        self.assertIn("assistant: Noted", text)
        self.assertNotIn("old message", text)
        self.assertNotIn("tool noise", text)

    def test_secret_in_a_stored_conversation_is_removed_when_read(self):
        secret = "gh" + "p_" + "a1B2c3D4e5" * 4
        db = SessionDB()
        now = time.time()
        db.create_session("chat", "cli")
        db.append_message("chat", "user", f"my token is {secret}", timestamp=now - 60)
        db.close()
        end = datetime.fromtimestamp(now).astimezone()
        batch = conversations.read_conversations(end - timedelta(hours=1), end)
        self.assertNotIn(secret, batch.conversations[0].text)

    def test_hook_blocks_a_change_during_the_briefing_through_hermes(self):
        from cron.execution_identity import enter_cron_execution, exit_cron_execution
        from hermes_cli import plugins as hermes_plugins
        manager = self._manager()
        with patch.object(hermes_plugins, "get_plugin_manager", return_value=manager):
            tool = "mcp__cardlake__create_reminder"
            self.assertIsNone(hermes_plugins.get_pre_tool_call_block_message(tool, {}))
            token = enter_cron_execution(
                {"id": "1", "name": load().BRIEFING_TITLE}, "run", {"source": "builtin"})
            try:
                self.assertIn("can't change", hermes_plugins.get_pre_tool_call_block_message(tool, {}))
            finally:
                exit_cron_execution(token)


if __name__ == "__main__":
    unittest.main()
