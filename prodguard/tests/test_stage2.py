"""Stage 2 tests — Structured Output + evidence rules.

Two groups:
  * Plumbing tests (should pass NOW): schema shape, evidence extraction,
    the given half of the validator, the format->parse->validate->fallback
    pipeline with scripted brains.
  * Homework tests (skipped): each turns green when Yu implements the
    matching TODO(YU-n) core. Unskip them one by one as you finish.

Run from the prodguard/ directory:
    python -m unittest discover -s tests -v
"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import build_report, run_agent  # noqa: E402
from llm import MockLLM  # noqa: E402
from report import (  # noqa: E402
    EXAMPLE_REPORT,
    REPORT_SCHEMA,
    extract_evidence_ids,
    fallback_report,
    validate_report,
)

SCRATCHPAD = """
Observation: [evidence: log:pricing-1502-oom] FATAL OutOfMemoryError
Observation: [evidence: job:vol_fit_4821] loaded 3758 chains
Observation: [evidence: change:CHG-1042] chain_spec -> wildcard
Observation: [evidence: health:pricing] status=down
"""


class TestSchema(unittest.TestCase):
    def test_required_fields(self):
        for field in ("severity", "symptom", "root_cause_hypothesis", "evidence",
                      "confidence", "ruled_out", "next_action_draft",
                      "needs_human_approval"):
            self.assertIn(field, REPORT_SCHEMA["required"])

    def test_severity_enum(self):
        self.assertEqual(REPORT_SCHEMA["properties"]["severity"]["enum"],
                         ["P1", "P2", "P3"])


class TestExtractEvidenceIds(unittest.TestCase):
    def test_extracts_all_ids(self):
        ids = extract_evidence_ids(SCRATCHPAD)
        self.assertEqual(ids, {"log:pricing-1502-oom", "job:vol_fit_4821",
                               "change:CHG-1042", "health:pricing"})


class TestValidatorGivenHalf(unittest.TestCase):
    def test_example_report_passes(self):
        self.assertEqual(validate_report(EXAMPLE_REPORT, SCRATCHPAD), [])

    def test_missing_field_is_an_error(self):
        bad = {k: v for k, v in EXAMPLE_REPORT.items() if k != "severity"}
        self.assertTrue(any("severity" in e for e in validate_report(bad, SCRATCHPAD)))

    def test_bad_severity_and_confidence(self):
        bad = dict(EXAMPLE_REPORT, severity="P9", confidence=1.5)
        errors = validate_report(bad, SCRATCHPAD)
        self.assertEqual(len(errors), 2)

    def test_unknown_root_cause_needs_no_evidence(self):
        report = fallback_report("anything", [])
        report.pop("validation_errors")
        self.assertEqual(validate_report(report, ""), [])


class GarbageBrain:
    name = "garbage"
    def complete(self, prompt):
        return "definitely not json {"

    def complete_structured(self, prompt, schema):
        return "definitely not json {"


class FixedBrain:
    def __init__(self, payload):
        self.payload = payload
        self.name = "fixed"

    def complete(self, prompt):
        return self.payload

    def complete_structured(self, prompt, schema):
        return self.payload


class TestPipeline(unittest.TestCase):
    def test_mock_end_to_end_report(self):
        result = run_agent("Why did the pricing service fail at 3pm?",
                           llm=MockLLM(), verbose=False, as_report=True)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["root_cause_hypothesis"],
                         EXAMPLE_REPORT["root_cause_hypothesis"])
        self.assertNotIn("validation_errors", result)

    def test_unparseable_output_falls_back_to_unknown(self):
        result = build_report("q", "some answer", SCRATCHPAD, GarbageBrain())
        self.assertEqual(result["root_cause_hypothesis"], "unknown")
        self.assertIn("validation_errors", result)

    def test_invalid_report_falls_back_to_unknown(self):
        brain = FixedBrain(json.dumps({"severity": "P1"}))  # missing fields
        result = build_report("q", "some answer", SCRATCHPAD, brain)
        self.assertEqual(result["root_cause_hypothesis"], "unknown")


@unittest.skip("TODO(YU-1): implement the invented-evidence rule in report.py")
class TestHomeworkYu1(unittest.TestCase):
    def test_invented_evidence_is_rejected(self):
        bad = copy.deepcopy(EXAMPLE_REPORT)
        bad["evidence"] = list(bad["evidence"]) + ["log:pricing-9999-fake"]
        errors = validate_report(bad, SCRATCHPAD)
        self.assertTrue(any("invented" in e for e in errors), errors)


@unittest.skip("TODO(YU-2): implement the right-source rule in report.py")
class TestHomeworkYu2(unittest.TestCase):
    def test_root_cause_needs_log_evidence(self):
        bad = copy.deepcopy(EXAMPLE_REPORT)
        bad["evidence"] = ["health:pricing", "job:vol_fit_4821", "change:CHG-1042"]
        errors = validate_report(bad, SCRATCHPAD)
        self.assertTrue(any("log:" in e for e in errors), errors)


@unittest.skip("TODO(YU-3): implement retry-once in agent.py build_report")
class TestHomeworkYu3(unittest.TestCase):
    def test_retry_once_recovers(self):
        class FlakyBrain:
            name = "flaky"
            def __init__(self):
                self.calls = 0

            def complete(self, prompt):
                return self.complete_structured(prompt, None)

            def complete_structured(self, prompt, schema):
                self.calls += 1
                if self.calls == 1:
                    return "not json {"
                return json.dumps(EXAMPLE_REPORT)

        result = build_report("q", "some answer", SCRATCHPAD, FlakyBrain())
        self.assertEqual(result["severity"], "P1")
        self.assertNotIn("validation_errors", result)


if __name__ == "__main__":
    unittest.main()
