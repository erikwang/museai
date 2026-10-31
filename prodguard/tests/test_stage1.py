"""Stage 1 smoke tests — stdlib only, no API key needed.

Run from the prodguard/ directory:
    python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import parse_action, run_agent  # noqa: E402
from llm import MockLLM  # noqa: E402
from tools import TOOLS, get_job_status, get_service_health, query_logs  # noqa: E402


class TestTools(unittest.TestCase):
    def test_logs_contain_oom_evidence(self):
        out = query_logs("pricing", "15:0")
        self.assertIn("OutOfMemoryError", out)
        self.assertIn("[evidence: log:pricing-1502-oom]", out)

    def test_unknown_service_says_none(self):
        self.assertIn("[evidence: none]", query_logs("does_not_exist"))

    def test_job_status(self):
        self.assertIn("3758", get_job_status("vol_fit_4821"))

    def test_service_health(self):
        self.assertIn("down", get_service_health("pricing"))

    def test_tool_table_matches_functions(self):
        self.assertEqual(set(TOOLS), {"query_logs", "get_job_status", "get_service_health"})


class TestParser(unittest.TestCase):
    def test_parse_action(self):
        text = 'Thought: check logs\nAction: query_logs(service="pricing", time_window="15:0")'
        name, kwargs = parse_action(text)
        self.assertEqual(name, "query_logs")
        self.assertEqual(kwargs, {"service": "pricing", "time_window": "15:0"})

    def test_parse_final_answer_is_none(self):
        self.assertIsNone(parse_action("Thought: done\nFinal Answer: it was OOM"))


class TestLoop(unittest.TestCase):
    def test_demo_reaches_grounded_final_answer(self):
        answer = run_agent("Why did the pricing service fail at 3pm?",
                           llm=MockLLM(), verbose=False)
        self.assertIn("OOM", answer)
        # anti-hallucination contract: the answer cites evidence ids
        self.assertIn("[evidence:", answer)

    def test_max_steps_guard_exists(self):
        class LoopForever:
            name = "loop"
            def complete(self, prompt):
                return 'Thought: again\nAction: get_service_health(service="feed")'

        answer = run_agent("anything", llm=LoopForever(), max_steps=3, verbose=False)
        self.assertIn("max_steps guard", answer)


if __name__ == "__main__":
    unittest.main()
