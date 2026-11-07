"""Runs against an installed copy of Hermes; skipped when it isn't there.

Uses Hermes's own plugin loader, blueprint form and tool-call hook, with a temporary
home folder. It makes no network calls and no model calls.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .helpers import ROOT, load

try:
    from hermes_cli.plugins import PluginManager
except ImportError:  # Hermes isn't installed
    PluginManager = None


@unittest.skipIf(PluginManager is None, "Hermes isn't installed")
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

    def test_loader_registers_command_tool_guide_and_blueprint(self):
        manager = self._manager()
        self.assertIn("cardlake", manager._plugin_commands)
        self.assertIn("cardlake:morning", manager._automation_blueprints)
        self.assertIn("cardlake", manager._system_prompt_sections)
        self.assertIn(load().TODAY_TOOL, manager._plugin_tool_names)

    def test_blueprint_form_makes_a_morning_telegram_job(self):
        from cron.blueprint_catalog import fill_blueprint
        blueprint = self._manager()._automation_blueprints["cardlake:morning"]
        job = fill_blueprint(blueprint, {"time": "07:15"})
        self.assertEqual(job["schedule"], "15 7 * * *")
        self.assertEqual(job["deliver"], "telegram")
        self.assertEqual(job["name"], load().MORNING_TITLE)
        self.assertIn("[SILENT]", job["prompt"])

    def test_hook_blocks_a_change_during_the_morning_job_through_hermes(self):
        from cron.execution_identity import enter_cron_execution, exit_cron_execution
        from hermes_cli import plugins as hermes_plugins
        manager = self._manager()
        with patch.object(hermes_plugins, "get_plugin_manager", return_value=manager):
            tool = "mcp__cardlake__create_reminder"
            self.assertIsNone(hermes_plugins.get_pre_tool_call_block_message(tool, {}))
            token = enter_cron_execution(
                {"id": "1", "name": load().MORNING_TITLE}, "run", {"source": "builtin"})
            try:
                self.assertIn("can't change", hermes_plugins.get_pre_tool_call_block_message(tool, {}))
            finally:
                exit_cron_execution(token)


if __name__ == "__main__":
    unittest.main()
