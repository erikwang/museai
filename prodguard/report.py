"""
ProdGuard — Stage 2: the incident report as Structured Output.

Stage 1's Final Answer was free text with a politeness contract in the
prompt ("please cite evidence, please cover four points"). Yu's local
qwen3:8b runs showed exactly what that buys: missing points, wrong
evidence source, details summarised away.

Stage 2 replaces politeness with machinery:
  1. REPORT_SCHEMA  — the report is JSON with required, typed fields.
  2. A formatter call — the model converts its free-text answer into the
     schema (Ollama does this under constrained decoding via `format`).
  3. validate_report — CODE checks the report, including the evidence
     rules. An ungrounded report never reaches the user as-is.

Your three core tasks are marked TODO(YU-1..3) in this file and agent.py.
The plumbing around them works; the *judgement* in the validator is yours.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- schema

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": ["P1", "P2", "P3"]},
        "symptom": {"type": "string"},
        "root_cause_hypothesis": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "ruled_out": {"type": "array", "items": {"type": "string"}},
        "next_action_draft": {"type": "string"},
        "needs_human_approval": {"type": "boolean"},
    },
    "required": [
        "severity", "symptom", "root_cause_hypothesis", "evidence",
        "confidence", "ruled_out", "next_action_draft", "needs_human_approval",
    ],
}

REQUIRED_FIELDS = REPORT_SCHEMA["required"]
SEVERITIES = set(REPORT_SCHEMA["properties"]["severity"]["enum"])

# The target: a report like this PASSES every rule, including yours.
EXAMPLE_REPORT = {
    "severity": "P1",
    "symptom": "Pricing service down from 15:02",
    "root_cause_hypothesis": (
        "vol_fit job vol_fit_4821 loaded 3,758 option chains into the shared "
        "heap after CHG-1042 widened its prefetch chain_spec to a wildcard; "
        "heap reached 98% and the pricing process was OOM-killed at 15:02."
    ),
    "evidence": [
        "log:pricing-1502-oom",
        "job:vol_fit_4821",
        "change:CHG-1042",
        "health:pricing",
    ],
    "confidence": 0.9,
    "ruled_out": [
        "CHG-1037 deploy (logging verbosity only)",
        "Feed outage (feed heartbeat ok, gap_count=0)",
    ],
    "next_action_draft": (
        "1) Restart the pricing service (requires human approval). "
        "2) Revert CHG-1042's wildcard chain_spec to the enumerated list. "
        "3) Follow up: heap alert at 90% for shared-cache jobs."
    ),
    "needs_human_approval": True,
}

# ------------------------------------------------------------- utilities

_EVIDENCE_RE = re.compile(r"\[evidence:\s*([^\]]+)\]")


def extract_evidence_ids(text: str) -> set[str]:
    """All evidence ids that actually appeared in a text (e.g. scratchpad).

    Note the tools emit ids like 'log:pricing-1502-oom'; the model's Final
    Answer cites them in the same '[evidence: ...]' wrapper.
    """
    return {m.group(1).strip() for m in _EVIDENCE_RE.finditer(text)}


def fallback_report(symptom: str, errors: list[str]) -> dict:
    """The honest report: used when formatting/validation fails for good.

    'unknown' is a valid incident answer. A fabricated one is not.
    """
    return {
        "severity": "P3",
        "symptom": symptom,
        "root_cause_hypothesis": "unknown",
        "evidence": [],
        "confidence": 0.0,
        "ruled_out": [],
        "next_action_draft": "Escalate to a human with the investigation transcript.",
        "needs_human_approval": True,
        "validation_errors": errors,
    }

# ------------------------------------------------------------- validator

def validate_report(report, scratchpad: str) -> list[str]:
    """Check a report dict against the rules. Returns a list of errors
    (empty list = the report passes).

    GIVEN (already implemented): shape, required fields, severity enum,
    confidence range, evidence is a list of strings.

    YOURS (TODO below): the two grounding rules that make this Stage 2
    instead of mere JSON formatting.
    """
    errors: list[str] = []

    if not isinstance(report, dict):
        return ["report is not a JSON object"]

    for field in REQUIRED_FIELDS:
        if field not in report:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    if report["severity"] not in SEVERITIES:
        errors.append(f"severity must be one of {sorted(SEVERITIES)}")

    conf = report["confidence"]
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        errors.append("confidence must be a number in [0, 1]")

    evidence = report["evidence"]
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        errors.append("evidence must be a list of strings")
        return errors

    if report["root_cause_hypothesis"] != "unknown" and not evidence:
        errors.append("a non-'unknown' root cause needs at least one evidence id")

    known_ids = extract_evidence_ids(scratchpad)

    # TODO(YU-1) — the invented-evidence rule (anti-hallucination gate):
    #   Every id in report["evidence"] must be present in known_ids.
    #   An id the model made up is the one unforgivable sin: append
    #   f"invented evidence id: {eid}" for each offender.
    #   (Right now this hole is OPEN — a fabricated id sails through.
    #    Close it. The skipped test test_invented_evidence_is_rejected
    #    in tests/test_stage2.py turns green when you do.)

    # TODO(YU-2) — the right-source rule:
    #   If root_cause_hypothesis != "unknown", at least one cited id must
    #   start with "log:". Stage 1's local run cited health evidence for
    #   the failure itself; health data is a second-hand summary, the log
    #   line is the primary source. Append a clear error when violated.
    #   (Skipped test: test_root_cause_needs_log_evidence.)

    return errors
