"""Loads the plugin the way Hermes does (as a package from its folder), plus a stand-in for Hermes."""

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "cardlake_hermes_plugin"


def load(module=None):
    if PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{PACKAGE}.{module}") if module else sys.modules[PACKAGE]


class FakeCtx:
    """Records every Cardlake call and answers like Hermes's MCP tools do."""

    def __init__(self, search_cards=(), feed=(), llm_answer=None, choice=None, connected=True):
        self.calls = []
        self.search_cards = list(search_cards)
        self.feed = list(feed)
        self.choice = choice
        self.connected = connected
        self.choice_asked = None
        self.prompts = []
        self.llm_answer = llm_answer
        self.llm = SimpleNamespace(complete_structured=self._complete)

    def _complete(self, **kwargs):
        self.prompts.append(kwargs)
        if isinstance(self.llm_answer, Exception):
            raise self.llm_answer
        return SimpleNamespace(parsed=self.llm_answer)

    def dispatch_tool(self, name, args):
        if not self.connected:
            return json.dumps({"error": f"Unknown tool: {name}"})
        self.calls.append((name, args))
        tool = name.rsplit("__", 1)[1]
        if tool == "list_feed":
            data = {"cards": self.feed}
        elif tool == "search_cards":
            data = {"cards": self.search_cards, "total": len(self.search_cards)}
        else:
            data = {"id": "new"}
        return json.dumps({"result": json.dumps(data)})

    def ask_choice(self, question, choices):
        self.choice_asked = (question, choices)
        return self.choice

    def written(self):
        """Calls that change something."""
        return [(n.rsplit("__", 1)[1], a) for n, a in self.calls
                if n.rsplit("__", 1)[1] not in ("list_feed", "search_cards")]
