"""
Stage 3 tests — the runbook retrieval must return RELEVANT sections,
irrelevant queries must return nothing (never the least-bad section),
and the agent's recovery action must be grounded in a cited section.

Run from the prodguard/ directory:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import run_agent  # noqa: E402
from llm import MockLLM  # noqa: E402
from runbooks import load_sections, search_runbooks  # noqa: E402
from tools import get_runbook  # noqa: E402


class TestChunking(unittest.TestCase):
    def test_sections_parsed_with_stable_ids(self):
        sections = load_sections()
        ids = {s["id"] for s in sections}
        self.assertIn("oom-triage#restart-first-recovery", ids)
        self.assertIn("db-timeout#triage-the-timeout", ids)
        self.assertTrue(all(s["body"] for s in sections))


class TestRetrievalRelevance(unittest.TestCase):
    def test_oom_query_ranks_oom_runbook_first(self):
        hits = search_runbooks("pricing service out of memory OOM restart recovery")
        self.assertTrue(hits)
        self.assertTrue(hits[0]["id"].startswith("oom-triage#"))

    def test_db_query_ranks_db_runbook_first(self):
        hits = search_runbooks("database timeout connection pool saturated")
        self.assertTrue(hits)
        self.assertTrue(hits[0]["id"].startswith("db-timeout#"))

    def test_irrelevant_query_returns_nothing(self):
        # the RAG honesty rule: no match -> empty, not the least-bad chunk
        self.assertEqual(search_runbooks("kubernetes ingress certificate expiry"), [])

    def test_scores_are_positive_and_descending(self):
        hits = search_runbooks("memory heap kill escalate problem record", top_k=3)
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(s > 0 for s in scores))


class TestRunbookTool(unittest.TestCase):
    def test_tool_returns_citable_evidence_ids(self):
        out = get_runbook("out of memory restart")
        self.assertIn("[evidence: runbook:oom-triage#", out)

    def test_tool_no_match_says_none(self):
        out = get_runbook("kubernetes ingress certificate expiry")
        self.assertIn("[evidence: none]", out)


class TestAgentGrounding(unittest.TestCase):
    def test_demo_consults_runbook_before_answering(self):
        answer = run_agent("Why did the pricing service fail at 3pm?",
                           llm=MockLLM(), verbose=False)
        self.assertIn("runbook:oom-triage#restart-first-recovery", answer)

    def test_demo_actually_calls_the_tool(self):
        # The citation in the final text is NOT proof the tool ran (the
        # scripted answer contains it literally). Watch the transcript:
        # the Action must appear, followed by a real Observation.
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_agent("Why did the pricing service fail at 3pm?",
                      llm=MockLLM(), verbose=True)
        out = buf.getvalue()
        self.assertIn("get_runbook(", out)
        self.assertIn("Observation: [evidence: runbook:oom-triage#", out)


if __name__ == "__main__":
    unittest.main()
