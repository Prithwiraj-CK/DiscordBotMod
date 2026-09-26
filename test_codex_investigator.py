"""Offline coverage for the opt-in hosted Codex investigation pilot."""

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import bot
from codex_investigator import (
    CodexInvestigationUnavailable, _build_snapshot, _extract_sse,
    _validate_evidence_against_repository, investigate_olympus,
)


class _Response:
    def __init__(self, payload=None, lines=()):
        self.payload = payload or {}
        self._lines = list(lines)

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode=True):
        del decode_unicode
        return iter(self._lines)


class HostedCodexPilotTests(unittest.TestCase):
    def setUp(self):
        # The real webhook may be configured in a developer's .env; mocked
        # hosted-agent tests must never create external Discord traffic.
        self._trace_webhook = patch("codex_trace._webhook_url", return_value=None)
        self._trace_webhook.start()

    def tearDown(self):
        self._trace_webhook.stop()

    def test_snapshot_is_olympus_only_and_redacts_secret_shaped_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps" / "api" / "src").mkdir(parents=True)
            (root / "apps" / "api" / "src" / "service.ts").write_text(
                "const token = 'safe-looking';\nconst API_KEY = 'must-not-leak';\n"
            )
            (root / ".env").write_text("OPENAI_API_KEY=must-not-leak\n")
            (root / "apps" / "api" / "fixtures").mkdir()
            (root / "apps" / "api" / "fixtures" / "users.json").write_text('{"email":"private@example.com"}')
            (root / "apps" / "api" / "config").mkdir()
            (root / "apps" / "api" / "config" / "env.ts").write_text("DATABASE_URL='must-not-leak'\n")
            (root / "apps" / "api" / "src" / "service.test.ts").write_text("const testToken = 'must-not-leak';\n")
            (root / "apps" / "api" / ".private").mkdir()
            (root / "apps" / "api" / ".private" / "notes.md").write_text("must-not-leak")
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False), \
                 patch("codex_investigator._OFFICIAL_FAQ_PATH", root / "missing-faq.md"):
                snapshot = _build_snapshot()
            try:
                with zipfile.ZipFile(snapshot) as archive:
                    self.assertEqual(["olympus/apps/api/src/service.ts"], archive.namelist())
                    source = archive.read("olympus/apps/api/src/service.ts").decode()
                self.assertNotIn("must-not-leak", source)
                self.assertNotIn("private@example.com", source)
                self.assertIn("[REDACTED]", source)
            finally:
                os.unlink(snapshot)

    def test_snapshot_includes_only_the_fixed_official_faq_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps" / "web").mkdir(parents=True)
            (root / "apps" / "web" / "page.tsx").write_text("export const page = true;\n")
            faq = root / "faq.md"
            faq.write_text(
                "# Olympus FAQ\n\nSource: https://www.olympusx.app/docs/08-faq\n\n" + "confirmed FAQ text\n" * 40
            )
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False), \
                 patch("codex_investigator._OFFICIAL_FAQ_PATH", faq):
                snapshot = _build_snapshot()
                try:
                    with zipfile.ZipFile(snapshot) as archive:
                        self.assertEqual(
                            ["olympus/apps/web/page.tsx", "olympus/official-docs/olympus-faq.md"],
                            archive.namelist(),
                        )
                    _validate_evidence_against_repository([
                        {"path": "official-docs/olympus-faq.md", "line_start": 1, "line_end": 4}
                    ])
                finally:
                    os.unlink(snapshot)

    def test_evidence_grounding_accepts_a_real_allowlisted_citation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps" / "worker" / "src").mkdir(parents=True)
            (root / "apps" / "worker" / "src" / "copy.ts").write_text(
                "\n".join("line {}".format(i) for i in range(1, 21)) + "\n"
            )
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False):
                # Within the allowlist, within the file's real line count.
                _validate_evidence_against_repository(
                    [{"path": "apps/worker/src/copy.ts", "line_start": 10, "line_end": 15}]
                )

    def test_evidence_grounding_rejects_a_path_outside_the_snapshot_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps" / "worker" / "src").mkdir(parents=True)
            (root / "apps" / "worker" / "src" / "copy.ts").write_text("one line\n")
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False):
                with self.assertRaises(CodexInvestigationUnavailable):
                    # "src/copy.ts" was never in the allowlist (missing the
                    # apps/ prefix) -- a plausible-looking hallucinated path.
                    _validate_evidence_against_repository(
                        [{"path": "src/copy.ts", "line_start": 1, "line_end": 1}]
                    )

    def test_evidence_grounding_rejects_a_line_range_past_end_of_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps" / "worker" / "src").mkdir(parents=True)
            (root / "apps" / "worker" / "src" / "copy.ts").write_text("only one line\n")
            with patch.dict(os.environ, {"CODEBASE_OLYMPUS_PATH": str(root)}, clear=False):
                with self.assertRaises(CodexInvestigationUnavailable):
                    _validate_evidence_against_repository(
                        [{"path": "apps/worker/src/copy.ts", "line_start": 999, "line_end": 999}]
                    )

    def test_hosted_agent_result_uses_completed_text_only(self):
        temporary = tempfile.NamedTemporaryFile(delete=False)
        temporary.write(b"test archive")
        temporary.close()
        final = json.dumps({
            "status": "confirmed",
            "answer": "The setting caps one copied trade.",
            "evidence": [{"path": "src/copy.ts", "line_start": 10, "line_end": 20}],
            "missing_information": [],
        })
        events = [
            'event: agent.session.created',
            'data: {"type":"agent.session.created","session_id":"sess_123"}',
            'event: agent.session.turn.output_text.done',
            'data: ' + json.dumps({"type": "agent.session.turn.output_text.done", "text": final}),
            'event: agent.session.turn.completed',
            'data: {"type":"agent.session.turn.completed","session_id":"sess_123","turn":{"usage":{"input_tokens":12,"output_tokens":5}}}',
        ]
        completed_turns = _Response({"data": [{"usage": {
            "input_tokens": 12,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 2},
        }}]})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False), \
             patch("codex_investigator._build_snapshot", return_value=temporary.name), \
             patch("codex_investigator.requests.post", return_value=_Response(lines=events)) as post, \
             patch("codex_investigator.requests.get", return_value=completed_turns) as get, \
             patch("codex_investigator.requests.delete") as delete, \
             patch("codex_investigator._root_for", return_value=None):
            # This test covers SSE/session/usage plumbing, not evidence
            # grounding (covered separately below); _root_for is patched out
            # so it does not depend on whatever CODEBASE_OLYMPUS_PATH a
            # developer's real .env happens to set.
            result = investigate_olympus("What does Max Trade Size do?", [])
        self.assertEqual("confirmed", result["status"])
        self.assertEqual("src/copy.ts", result["evidence"][0]["path"])
        self.assertEqual("sess_123", result["session_id"])
        self.assertEqual(1, post.call_count)
        payload = post.call_args.kwargs["json"]
        self.assertTrue(all(item["type"] == "inline" for item in payload["environment"]["files"]))
        self.assertEqual(1, get.call_count)
        self.assertEqual(12, result["usage"]["input_tokens"])
        self.assertEqual(3, result["usage"]["input_tokens_details"]["cached_tokens"])
        self.assertEqual(1, delete.call_count)

    def test_null_usage_is_retried_and_recovered_within_the_poll_window(self):
        # Empirically, a completed turn's usage field is sometimes still
        # null on the /turns endpoint at the instant it completes, and
        # reliably appears roughly 20 seconds later on the same session
        # with no other signal that it has arrived. One immediate check is
        # not enough; this proves the retry loop recovers it.
        temporary = tempfile.NamedTemporaryFile(delete=False)
        temporary.write(b"test archive")
        temporary.close()
        final = json.dumps({
            "status": "confirmed", "answer": "a",
            "evidence": [{"path": "src/copy.ts", "line_start": 1, "line_end": 2}],
            "missing_information": [],
        })
        events = [
            'data: {"type":"agent.session.created","session_id":"sess_delay"}',
            'data: ' + json.dumps({"type": "agent.session.turn.output_text.done", "text": final}),
            'data: {"type":"agent.session.turn.completed","session_id":"sess_delay"}',
        ]
        still_pending = _Response({"data": [{"usage": None}]})
        now_available = _Response({"data": [{"usage": {"input_tokens": 100, "output_tokens": 20}}]})
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AGENTS_USAGE_POLL_MAX_WAIT_SECONDS": "30",
            "AGENTS_USAGE_POLL_INTERVAL_SECONDS": "8",
        }, clear=False), \
             patch("codex_investigator._build_snapshot", return_value=temporary.name), \
             patch("codex_investigator.requests.post", return_value=_Response(lines=events)), \
             patch("codex_investigator.requests.get", side_effect=[still_pending, still_pending, now_available]) as get, \
             patch("codex_investigator.requests.delete"), \
             patch("codex_investigator._root_for", return_value=None), \
             patch("codex_investigator.time.sleep") as sleep:
            result = investigate_olympus("What does Max Trade Size do?", [])
        self.assertEqual(3, get.call_count)
        self.assertEqual(2, sleep.call_count)
        self.assertEqual(100, result["usage"]["input_tokens"])

    def test_usage_poll_gives_up_at_the_configured_wait_ceiling(self):
        temporary = tempfile.NamedTemporaryFile(delete=False)
        temporary.write(b"test archive")
        temporary.close()
        final = json.dumps({
            "status": "confirmed", "answer": "a",
            "evidence": [{"path": "src/copy.ts", "line_start": 1, "line_end": 2}],
            "missing_information": [],
        })
        events = [
            'data: {"type":"agent.session.created","session_id":"sess_never"}',
            'data: ' + json.dumps({"type": "agent.session.turn.output_text.done", "text": final}),
            'data: {"type":"agent.session.turn.completed","session_id":"sess_never"}',
        ]
        never_available = _Response({"data": [{"usage": None}]})
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "AGENTS_USAGE_POLL_MAX_WAIT_SECONDS": "0",
        }, clear=False), \
             patch("codex_investigator._build_snapshot", return_value=temporary.name), \
             patch("codex_investigator.requests.post", return_value=_Response(lines=events)), \
             patch("codex_investigator.requests.get", return_value=never_available) as get, \
             patch("codex_investigator.requests.delete"), \
             patch("codex_investigator._root_for", return_value=None), \
             patch("codex_investigator.time.sleep") as sleep:
            result = investigate_olympus("What does Max Trade Size do?", [])
        # AGENTS_USAGE_POLL_MAX_WAIT_SECONDS=0 must still try exactly once,
        # matching the previous single-attempt behavior, and never sleep.
        self.assertEqual(1, get.call_count)
        sleep.assert_not_called()
        self.assertIsNone(result["usage"])

    def test_hosted_sse_decodes_utf8_punctuation(self):
        final = json.dumps({
            "status": "confirmed",
            "answer": "Yes—Polymarket’s PnL is included.",
            "evidence": [{"path": "src/chart.ts", "line_start": 1, "line_end": 2}],
            "missing_information": [],
        }, ensure_ascii=False)
        events = [
            b"event: agent.session.created",
            b'data: {"type":"agent.session.created","session_id":"sess_utf8"}',
            ("event: agent.session.turn.output_text.done").encode("utf-8"),
            ("data: " + json.dumps({
                "type": "agent.session.turn.output_text.done", "text": final,
            }, ensure_ascii=False)).encode("utf-8"),
            b"event: agent.session.turn.completed",
            b'data: {"type":"agent.session.turn.completed"}',
        ]
        text, _usage, completed, session_id, _sandbox_calls = _extract_sse(_Response(lines=events))
        self.assertTrue(completed)
        self.assertEqual("sess_utf8", session_id)
        self.assertIn("Yes—Polymarket’s", text)

    def test_sandbox_calls_are_counted_once_per_completed_tool_invocation(self):
        final = json.dumps({
            "status": "confirmed", "answer": "a",
            "evidence": [{"path": "p.ts", "line_start": 1, "line_end": 2}],
            "missing_information": [],
        })
        events = [
            b'data: {"type":"agent.session.created","session_id":"sess_sbx"}',
            # Three sandboxed commands, each an added/done pair -- only the
            # "done" side should be counted, once each.
            b'data: {"type":"agent.session.turn.item.added","item":{"type":"command_execution"}}',
            b'data: {"type":"agent.session.turn.item.done","item":{"type":"command_execution"}}',
            b'data: {"type":"agent.session.turn.item.added","item":{"type":"command_execution"}}',
            b'data: {"type":"agent.session.turn.item.done","item":{"type":"command_execution"}}',
            b'data: {"type":"agent.session.turn.item.added","item":{"type":"command_execution"}}',
            b'data: {"type":"agent.session.turn.item.done","item":{"type":"command_execution"}}',
            ("data: " + json.dumps({
                "type": "agent.session.turn.output_text.done", "text": final,
            })).encode(),
            b'data: {"type":"agent.session.turn.completed"}',
        ]
        _text, _usage, completed, _sid, sandbox_calls = _extract_sse(_Response(lines=events))
        self.assertTrue(completed)
        self.assertEqual(3, sandbox_calls)

    def test_agents_runtime_returns_to_existing_responses_pipeline_on_failure(self):
        fallback = bot._decision("answer", "olympus", "settings", "Responses fallback answer.")
        with patch.object(bot, "AGENT_RUNTIME", "agents"), \
             patch.object(bot, "AGENT_FAILURE_FALLBACK_TO_RESPONSES", True), \
             patch("bot.investigate_olympus", side_effect=CodexInvestigationUnavailable("agent_request_failed")), \
             patch("bot._luna_tool_research_decision", return_value=fallback) as responses:
            result = bot.autonomous_decision("What does Max Trade Size do?", [])
        self.assertEqual("Responses fallback answer.", result["draft_answer"])
        responses.assert_called_once()

    def test_pilot_can_abstain_without_a_paid_responses_fallback(self):
        with patch.object(bot, "AGENT_RUNTIME", "agents"), \
             patch.object(bot, "AGENT_FAILURE_FALLBACK_TO_RESPONSES", False), \
             patch("bot.investigate_olympus", side_effect=CodexInvestigationUnavailable("snapshot_empty")), \
             patch("bot._luna_tool_research_decision") as responses:
            result = bot.autonomous_decision("What does Max Trade Size do?", [])
        self.assertEqual(bot.ESCALATE, result["draft_answer"])
        responses.assert_not_called()

    def test_direct_question_starts_hosted_investigation(self):
        investigation = {
            "status": "confirmed", "answer": "It includes unrealized P&L.",
            "evidence": [{"path": "src/overview.tsx", "line_start": 10, "line_end": 18}],
            "missing_information": [], "usage": {"input_tokens": 8, "output_tokens": 4},
        }
        approved = [{"id": "olympus.settings.max_trade_size", "fact": "Max Trade Size caps one copy."}]
        with patch.object(bot, "AGENT_RUNTIME", "agents"), \
             patch("bot.investigate_olympus", return_value=investigation) as investigate, \
             patch("bot.retrieve_facts", return_value=approved) as retrieve, \
             patch("bot.record_usage") as recorded:
            result = bot.autonomous_decision(
                "does the graph include unrealized profit and loss?", [], force_reply=True,
            )
        investigate.assert_called_once()
        retrieve.assert_called_once()
        self.assertEqual(approved, investigate.call_args.kwargs["approved_facts"])
        recorded.assert_called_once_with(
            "gpt-6-luna", investigation["usage"], runtime="agents", sandbox_calls=0,
        )
        self.assertEqual("answer", result["action"])
        self.assertEqual("It includes unrealized P&L.", result["draft_answer"])

    def test_a_real_large_usage_count_does_not_discard_a_completed_investigation(self):
        # Confirmed empirically: once usage actually populates, a real hosted
        # investigation's input tokens routinely exceed the ~50k ceiling
        # ResearchBudget applies to our own iterative Responses/Luna tool
        # loop, because that count reflects the hosted sandbox's own
        # internal context, not messages we chose to send. The budget check
        # only runs *after* investigate_olympus already returned a complete,
        # validated result, so tripping it must never turn that into
        # [[ESCALATE]] and throw away a good, already-paid-for answer.
        investigation = {
            "status": "confirmed", "answer": "Real, grounded answer.",
            "evidence": [{"path": "src/overview.tsx", "line_start": 10, "line_end": 18}],
            "missing_information": [],
            "usage": {"input_tokens": 142_267, "output_tokens": 3_063},
        }
        with patch.object(bot, "AGENT_RUNTIME", "agents"), \
             patch("bot.investigate_olympus", return_value=investigation), \
             patch("bot.retrieve_facts", return_value=[]), \
             patch("bot.record_usage"):
            result = bot.autonomous_decision("does the graph include unrealized profit and loss?", [])
        self.assertEqual("answer", result["action"])
        self.assertEqual("Real, grounded answer.", result["draft_answer"])

    def test_sample_settings_evidence_adds_guide_and_removes_personalised_handoff(self):
        investigation = {
            "status": "confirmed",
            "answer": (
                "There is no one best setting. For a setup tailored to your funds, "
                "please contact Olympus support."
            ),
            "evidence": [{
                "path": "apps/web-v2/src/content/docs/05-sample-settings.mdx",
                "line_start": 12, "line_end": 33,
            }],
            "missing_information": [], "usage": {"input_tokens": 8, "output_tokens": 4},
        }
        with patch.object(bot, "AGENT_RUNTIME", "agents"), \
             patch("bot.investigate_olympus", return_value=investigation), \
             patch("bot.retrieve_facts", return_value=[]), \
             patch("bot.record_usage"):
            result = bot.autonomous_decision("what is the best setting to copy?", [], force_reply=True)
        self.assertNotIn("tailored to your funds", result["draft_answer"])
        self.assertIn("https://www.olympusx.app/docs/05-sample-settings", result["draft_answer"])
        self.assertIn("give it a look", result["draft_answer"])

    def test_unpunctuated_direct_message_clarifies_the_same_on_both_runtimes(self):
        # bot._codex_agents_decision previously used `force_reply or
        # _asks_something(...)`, a looser gate than the Responses path's
        # `_asks_something(...) and not _is_social_smalltalk(...)`. That let
        # switching AGENT_RUNTIME change which messages start a research
        # turn, not just which runtime answers them. Both runtimes must
        # reach the same clarify/investigate decision for the same message.
        query = "does the graph include unrealized profit and loss"
        with patch.object(bot, "AGENT_RUNTIME", "responses"), \
             patch("bot.investigate_olympus") as investigate, \
             patch("bot.ask_json_with_tools") as tools_model:
            responses_result = bot.autonomous_decision(query, [], force_reply=True)
        investigate.assert_not_called()
        tools_model.assert_not_called()
        with patch.object(bot, "AGENT_RUNTIME", "agents"), \
             patch("bot.investigate_olympus") as investigate:
            agents_result = bot.autonomous_decision(query, [], force_reply=True)
        investigate.assert_not_called()
        self.assertEqual("clarify", responses_result["action"])
        self.assertEqual("clarify", agents_result["action"])
        self.assertEqual(responses_result["draft_answer"], agents_result["draft_answer"])

    def test_agents_result_still_uses_existing_shadow_formatting_and_posting(self):
        posted = []
        message = {
            "id": "question-1", "channel_id": "source", "guild_id": "guild",
            "content": "What does Max Trade Size do?",
            "author": {"id": "user", "username": "Billi"},
            "mentions": [],
        }
        investigation = {
            "status": "confirmed", "answer": "It caps one copied trade.",
            "evidence": [{"path": "src/copy.ts", "line_start": 10, "line_end": 20}],
            "missing_information": [], "usage": {"input_tokens": 8, "output_tokens": 4},
        }

        class Memory:
            def load(self, *_args, **_kwargs):
                return []
            def append(self, *_args, **_kwargs):
                return None

        def invoke(_label, fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with patch.object(bot, "AGENT_RUNTIME", "agents"), \
             patch.object(bot, "SHADOW_MODE", True), \
             patch.object(bot, "OUTPUT_CHANNEL_ID", "shadow"), \
             patch.object(bot, "_conversation_memory", Memory()), \
             patch("bot._remember_incoming"), patch("bot._recent_context", return_value=[]), \
             patch("bot._extract_image_context", return_value=""), \
             patch("bot.investigate_olympus", return_value=investigation), \
             patch("bot._guard_output", return_value="shadow"), \
             patch("bot._call", side_effect=invoke), \
             patch("bot.record_usage"), \
             patch("bot._discord_post_message", side_effect=lambda _target, body, **_kwargs: posted.append(body)):
            # record_usage is mocked so this test never writes to the
            # developer's real .runtime/openai_usage.jsonl.
            bot._answer(message)
        self.assertEqual(1, len(posted))
        self.assertIn("**shadow proposal**", posted[0])
        self.assertIn("It caps one copied trade.", posted[0])


if __name__ == "__main__":
    unittest.main()
