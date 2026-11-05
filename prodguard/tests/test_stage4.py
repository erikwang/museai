"""
Stage 4 tests — LangGraph skeleton: the graph runs end-to-end, state
is structured and checkpointable, and the three homework holes
(gate / approval interrupt / post-approval routing) are marked by
skipped tests, exactly like Stage 2's homework pattern.

Requires: pip install langgraph langgraph-checkpoint-sqlite
(the whole module skips cleanly when langgraph is absent)

Run from the prodguard/ directory:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from langgraph.types import Command

    import graph_agent
    from graph_agent import build_graph, initial_state
    from llm import MockLLM

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False


def _run_demo(thread: str = "test-thread") -> dict:
    graph = build_graph(llm=MockLLM())
    return graph.invoke(
        initial_state("Why did the pricing service fail at 3pm?"),
        {"configurable": {"thread_id": thread}},
    )


@unittest.skipUnless(HAS_LANGGRAPH, "langgraph not installed")
class TestSkeletonGiven(unittest.TestCase):
    def test_graph_runs_end_to_end(self):
        result = _run_demo()
        self.assertEqual(result["report"]["severity"], "P1")
        # In the skeleton the run completes with approval 'auto_skipped';
        # once YU-2 is wired it PAUSES with __interrupt__ instead. Both
        # are the same safety property: it did not act on its own.
        self.assertTrue("__interrupt__" in result
                        or result["approval_status"] == "auto_skipped")
        self.assertIsNone(result["execution"])

    def test_investigation_state_is_structured(self):
        result = _run_demo("t2")
        # state fields, not string archaeology:
        self.assertTrue(result["runbook_consulted"])
        self.assertFalse(result["gate_forced"])
        self.assertGreaterEqual(result["steps"], 1)
        self.assertIn("OOM", result["answer"])

    def test_initial_state_is_checkpoint_serialisable(self):
        # the checkpointer stores this dict — it must be plain data
        json.dumps(initial_state("q"))

    def test_checkpoint_keeps_state_by_thread(self):
        graph = build_graph(llm=MockLLM())
        cfg = {"configurable": {"thread_id": "persist-1"}}
        graph.invoke(initial_state("Why did the pricing service fail at 3pm?"), cfg)
        snapshot = graph.get_state(cfg)
        self.assertEqual(snapshot.values["report"]["severity"], "P1")


@unittest.skipUnless(HAS_LANGGRAPH, "langgraph not installed")
@unittest.skip("TODO(YU-1): implement runbook_gate in graph_agent.py")
class TestHomeworkYu1(unittest.TestCase):
    def test_unconsulted_investigation_is_forced(self):
        state = initial_state("q")
        state["runbook_consulted"] = False
        state["gate_forced"] = False
        self.assertEqual(graph_agent.runbook_gate(state), "force_runbook")

    def test_consulted_or_already_forced_proceeds(self):
        state = initial_state("q")
        state["runbook_consulted"] = True
        self.assertEqual(graph_agent.runbook_gate(state), "build_report")
        state["runbook_consulted"] = False
        state["gate_forced"] = True  # forced once already — never loop
        self.assertEqual(graph_agent.runbook_gate(state), "build_report")


@unittest.skipUnless(HAS_LANGGRAPH, "langgraph not installed")
@unittest.skip("TODO(YU-2): wire interrupt() in request_approval")
class TestHomeworkYu2(unittest.TestCase):
    def test_graph_pauses_at_approval_then_resumes(self):
        graph = build_graph(llm=MockLLM())
        cfg = {"configurable": {"thread_id": "hitl-1"}}
        result = graph.invoke(
            initial_state("Why did the pricing service fail at 3pm?"), cfg)
        # the graph must STOP and hand the decision to a human
        self.assertIn("__interrupt__", result)
        payload = result["__interrupt__"][0].value
        self.assertEqual(payload["kind"], "approval_request")
        self.assertIn("restart", payload["action"].lower())

        resumed = graph.invoke(
            Command(resume={"decision": "approve", "note": "go"}), cfg)
        self.assertEqual(resumed["approval_status"], "approved")

    def test_rejection_is_recorded(self):
        graph = build_graph(llm=MockLLM())
        cfg = {"configurable": {"thread_id": "hitl-2"}}
        graph.invoke(initial_state("Why did the pricing service fail at 3pm?"), cfg)
        resumed = graph.invoke(
            Command(resume={"decision": "reject", "note": "market hours"}), cfg)
        self.assertEqual(resumed["approval_status"], "rejected")
        self.assertIsNone(resumed["execution"])


@unittest.skipUnless(HAS_LANGGRAPH, "langgraph not installed")
@unittest.skip("TODO(YU-3): implement route_after_approval in graph_agent.py")
class TestHomeworkYu3(unittest.TestCase):
    def test_approved_and_edited_route_to_execute(self):
        for status in ("approved", "edited"):
            state = initial_state("q")
            state["approval_status"] = status
            self.assertEqual(graph_agent.route_after_approval(state), "execute")

    def test_everything_else_routes_to_finalize(self):
        for status in ("rejected", "pending", "auto_skipped", "not_requested"):
            state = initial_state("q")
            state["approval_status"] = status
            self.assertEqual(graph_agent.route_after_approval(state), "finalize")


if __name__ == "__main__":
    unittest.main()
