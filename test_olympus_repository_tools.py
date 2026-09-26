"""Fixture-only safety and discovery tests for Olympus repository tools."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm import ResearchBudget
from olympus_repository_tools import OLYMPUS_REPOSITORY_TOOL_SCHEMAS, OlympusRepositoryTools


class OlympusRepositoryToolsTests(unittest.TestCase):
    def _repository(self, root):
        files = {
            "src/copy.ts": """export function maxTradeSize(value: number) {
  return value;
}
""",
            "src/entry.ts": """import { maxTradeSize } from \"./copy\";

export function entryPoint(value: number) {
  return maxTradeSize(value);
}
""",
            "tests/copy.test.ts": """import { maxTradeSize } from \"../src/copy\";

test(\"caps size\", () => maxTradeSize(2));
""",
            "docs/settings.md": """# Max Trade Size

Max Trade Size limits a copied order.
""",
            ".env": "MAX_TRADE_SIZE_SECRET=never expose this\n",
            "src/secret-config.ts": "const MaxTradeSizeSecret = 'never expose this';\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def _session(self, root, budget=None):
        return OlympusRepositoryTools(budget=budget)

    def _with_repository(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        self._repository(root)
        patcher = patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(directory.cleanup)
        return root

    def test_traversal_and_unknown_anchor_are_rejected(self):
        root = self._with_repository()
        session = self._session(root)
        result = session.execute("read_section", {"anchor_id": "../../outside"})
        self.assertEqual("error", result["status"])
        self.assertEqual("anchor_not_found", result["error"])

    def test_tool_schemas_are_olympus_only_and_never_accept_paths_or_commands(self):
        schemas = {schema["name"]: schema for schema in OLYMPUS_REPOSITORY_TOOL_SCHEMAS}
        self.assertEqual({
            "search_exact_phrase", "search_repository", "search_symbols", "find_references",
            "read_section", "read_callers", "read_tests_for_symbol", "repository_revision",
            "run_allowlisted_test",
        }, set(schemas))
        self.assertNotIn("product", str(schemas))
        self.assertNotIn("path", schemas["read_section"]["parameters"]["properties"])
        self.assertEqual(["olympus_unit_tests"], schemas["run_allowlisted_test"]["parameters"]["properties"]["command_id"]["enum"])

    def test_symlink_escape_secret_files_and_oversized_files_are_not_searchable(self):
        root = self._with_repository()
        outside = Path(tempfile.mkdtemp()) / "outside.ts"
        outside.write_text("Max Trade Size outside root")
        try:
            (root / "src" / "escape.ts").symlink_to(outside)
            (root / "src" / "large.ts").write_text("Max Trade Size\n" + ("x" * (513 * 1024)))
            session = self._session(root)
            result = session.execute("search_exact_phrase", {"phrase": "Max Trade Size"})
        finally:
            outside.unlink()
            outside.parent.rmdir()
        previews = "\n".join(anchor["preview"] for anchor in result["anchors"])
        self.assertNotIn("outside root", previews)
        self.assertNotIn("never expose this", previews)
        self.assertNotIn("large.ts", previews)

    def test_duplicate_searches_reuse_opaque_anchor_ids(self):
        root = self._with_repository()
        session = self._session(root)
        first = session.execute("search_exact_phrase", {"phrase": "Max Trade Size"})
        second = session.execute("search_exact_phrase", {"phrase": "Max Trade Size"})
        self.assertTrue(first["anchors"])
        self.assertEqual(
            [anchor["anchor_id"] for anchor in first["anchors"]],
            [anchor["anchor_id"] for anchor in second["anchors"]],
        )
        self.assertTrue(all(anchor["anchor_id"].startswith("oa_") for anchor in first["anchors"]))

    def test_valid_reference_caller_and_test_discovery(self):
        root = self._with_repository()
        session = self._session(root)
        entry = session.execute("search_symbols", {"query": "entryPoint"})["anchors"][0]
        references = session.execute("find_references", {"anchor_id": entry["anchor_id"]})
        self.assertTrue(references["anchors"])

        symbol = session.execute("search_symbols", {"query": "maxTradeSize"})["anchors"][0]
        callers = session.execute("read_callers", {"anchor_id": symbol["anchor_id"]})
        tests = session.execute("read_tests_for_symbol", {"anchor_id": symbol["anchor_id"]})
        self.assertTrue(callers["sections"])
        self.assertTrue(tests["sections"])
        self.assertTrue(all(section["citable"] for section in callers["sections"] + tests["sections"]))

    def test_metadata_trace_and_budget_limit_are_enforced(self):
        root = self._with_repository()
        budget = ResearchBudget(max_tool_output_tokens=1)
        session = self._session(root, budget=budget)
        result = session.execute("search_repository", {"query": "Max Trade Size"})
        self.assertEqual("budget_exhausted", result["status"])
        self.assertEqual("budget_exhausted", result["error"])
        self.assertTrue(session.trace_events)
        self.assertNotIn("Max Trade Size", str(session.trace_events))

    def test_unexpected_repository_failure_is_traceable_but_safe_for_the_model(self):
        root = self._with_repository()
        session = self._session(root)
        with patch("olympus_repository_tools.search_codebase", side_effect=IndexError("internal detail")), \
             patch("olympus_repository_tools.log.exception") as log_exception:
            result = session.execute("search_repository", {"query": "Max Trade Size"})
        self.assertEqual("error", result["status"])
        self.assertEqual("tool_internal_error", result["error"])
        self.assertRegex(result["failure_id"], r"^repo_tool_[0-9a-f]{12}$")
        self.assertNotIn("internal detail", str(result))
        self.assertNotIn(str(root), str(result))
        log_exception.assert_called_once()
        self.assertNotIn("Max Trade Size", str(session.trace_events))

    def test_arbitrary_test_commands_are_rejected_and_allowlisted_tests_fail_closed(self):
        root = self._with_repository()
        session = self._session(root)
        with patch("olympus_repository_tools.subprocess.run") as runner:
            arbitrary = session.execute("run_allowlisted_test", {"command_id": "python -c 'import os'"})
            allowlisted = session.execute("run_allowlisted_test", {"command_id": "olympus_unit_tests"})
        self.assertEqual("unknown_test_command", arbitrary["error"])
        self.assertEqual("test_execution_unavailable", allowlisted["status"])
        runner.assert_not_called()

    def test_repository_revision_timeout_is_bounded(self):
        root = self._with_repository()
        session = self._session(root)
        with patch("olympus_repository_tools.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 3)):
            result = session.execute("repository_revision", {})
        self.assertEqual("error", result["status"])
        self.assertEqual("repository_revision_timeout", result["error"])


if __name__ == "__main__":
    unittest.main()
