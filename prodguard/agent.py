"""
ProdGuard — Stage 1: a hand-written ReAct loop. No framework.

ReAct = Reasoning + Acting

    Thought     the model decides what to do next          (model's job)
    Action      a tool call, in a strict text format        (program parses it)
    Observation the tool's real result, fed back verbatim   (program's job)
    ... repeat until the model emits "Final Answer" or max_steps is hit.

Study this file top to bottom — it IS the lesson. Everything a framework
like LangGraph does is, at its core, this loop plus state management.
"""
from __future__ import annotations

import json
import re

from llm import MockLLM
from report import REPORT_SCHEMA, extract_evidence_ids, fallback_report, validate_report
from tools import TOOLS

MAX_STEPS = 6          # 保命参数: never let the loop turn forever
TEMPERATURE = 0.0      # noted for real LLMs: triage wants determinism, not creativity

SYSTEM_PROMPT = """You are ProdGuard, a production incident triage agent.
Investigate the user's question by using tools, one step at a time.

Available tools:
{tool_list}

Reply in EXACTLY one of these two formats:

Thought: <your reasoning>
Action: <tool_name>(<arg>="<value>", ...)

—or, when you have enough evidence—

Thought: <your reasoning>
Final Answer: <your conclusion, citing [evidence: ...] ids>

Rules:
- One Action per reply. Wait for the Observation before deciding the next step.
- Every factual claim in the Final Answer must cite an evidence id
  that actually appeared in an Observation. No evidence = say "unknown".
- Never claim you executed an action (restart, deploy, delete).
  You may only *draft* actions for a human to approve.
- Your Final Answer must cover ALL four points, in this order:
  (1) what failed, citing the fatal log evidence;
  (2) the contributing factor (job and/or change), citing its evidence;
  (3) the service's current status, citing its health evidence;
  (4) the draft next action.
  Do not skip a point: if you have no evidence for one, write "unknown"
  for that point. A short answer that skips points is a failed answer.
- Before writing the Final Answer, you MUST call get_runbook once,
  with a query naming the failure type (e.g. "database timeout",
  "out of memory"), to fetch the approved runbook procedure. Base the
  draft next action (point 4) on the returned section and cite its
  [evidence: runbook:...] id. If it returns [evidence: none], say so
  in point 4 and proceed on the other evidence.
"""

ACTION_RE = re.compile(r"Action:\s*(\w+)\((.*?)\)", re.DOTALL)
ARG_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# ------------------------------------------------------- Stage 2: report

FORMAT_PROMPT = """Convert the incident investigation below into a JSON incident report.

JSON Schema (your output must match it exactly):
{schema}

The investigator's free-text final answer:
{final_answer}

Evidence ids you may cite — ONLY these. Any other id is fabrication:
{evidence_ids}

Filling rules:
- root_cause_hypothesis keeps the quantified details from the evidence
  (counts, percentages, times). Do not summarise the numbers away.
- next_action_draft is restore-first: restoring the service comes
  before fixing the cause.
- Where the investigation has no evidence for a claim, write "unknown"
  or leave the claim out. Never invent an evidence id.

Return ONLY the JSON object."""


def _call_structured(llm, prompt: str) -> str:
    """Use the client's constrained structured call when it has one
    (Ollama `format`, MockLLM's script); otherwise fall back to a plain
    completion and let json.loads + the validator sort it out."""
    if hasattr(llm, "complete_structured"):
        return llm.complete_structured(prompt, REPORT_SCHEMA)
    return llm.complete(prompt)


def build_report(question: str, final_answer: str, scratchpad: str, llm) -> dict:
    """Turn a free-text Final Answer into a validated report dict.

    Pipeline: format -> parse -> validate -> (your retry) -> fallback.
    A report that cannot pass validation becomes fallback_report():
    'unknown' is a valid incident answer, a fabricated one is not.
    """
    evidence_ids = sorted(extract_evidence_ids(scratchpad))
    prompt = FORMAT_PROMPT.format(
        schema=json.dumps(REPORT_SCHEMA, indent=2),
        final_answer=final_answer,
        evidence_ids="\n".join(f"- {e}" for e in evidence_ids) or "(none)",
    )

    # YU-3 — retry ONCE, with the failure fed back to the model.
    #   A retry is not 'ask again and hope': the second prompt carries the
    #   exact parse error or validation error list, so the model can fix
    #   THOSE problems instead of regenerating blindly. One retry only —
    #   a model that fails twice with the errors spelled out is telling
    #   you something; after that, the honest fallback beats a third roll
    #   of the dice (and caps cost/latency, the Stage 1 lesson).
    last_errors: list[str] = []
    for _attempt in (1, 2):
        raw = _call_structured(llm, prompt)
        try:
            report = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            last_errors = [f"formatter returned unparseable output: {e}"]
            prompt = (
                prompt
                + f"\n\nYour previous output was not valid JSON: {e}. "
                "Return ONLY the JSON object, nothing else."
            )
            continue

        errors = validate_report(report, scratchpad)
        if not errors:
            return report
        last_errors = errors
        prompt = (
            prompt
            + "\n\nYour previous report failed validation:\n"
            + "\n".join(f"- {err}" for err in errors)
            + "\nFix ONLY those problems and return the full corrected JSON object."
        )

    return fallback_report(question, last_errors)


def parse_action(text: str) -> tuple[str, dict] | None:
    """Pull `tool_name(arg="value", ...)` out of the model's reply.

    Returns None when the reply is not an action (e.g. a Final Answer).
    This little parser is the seam between 'model text' and 'real code' —
    in Stage 2 you will replace it with Structured Output / JSON Schema.
    """
    m = ACTION_RE.search(text)
    if not m:
        return None
    tool_name, raw_args = m.group(1), m.group(2)
    return tool_name, dict(ARG_RE.findall(raw_args))


def run_agent(question: str, llm=None, max_steps: int = MAX_STEPS, verbose: bool = True,
              show_prompt: bool = False, as_report: bool = False):
    """Run the ReAct loop on one question.

    Returns the final answer text — or, with as_report=True (Stage 2), a
    validated incident-report dict produced by build_report().

    show_prompt=True prints the EXACT string sent to the model at each step —
    the best way to learn what a model actually 'sees'. Try it once.
    """
    llm = llm or MockLLM()
    tool_list = "\n".join(f"- {desc}" for _, desc in (t for t in TOOLS.values()))
    scratchpad = SYSTEM_PROMPT.format(tool_list=tool_list)
    scratchpad += f"\n\nQuestion: {question}\n"

    for step in range(1, max_steps + 1):
        if show_prompt:
            print(f"===== PROMPT for step {step} ({len(scratchpad)} chars) =====\n"
                  f"{scratchpad}\n===== END PROMPT =====")
        reply = llm.complete(scratchpad)
        scratchpad += reply.strip() + "\n"
        if verbose:
            print(f"--- step {step} ---\n{reply.strip()}")

        if "Final Answer:" in reply:
            answer = reply.split("Final Answer:", 1)[1].strip()
            if verbose:
                print(f"\n[stopped: final answer after {step} step(s)]")
            if as_report:
                return build_report(question, answer, scratchpad, llm)
            return answer

        parsed = parse_action(reply)
        if parsed is None:
            observation = "Invalid format. Reply with Thought/Action or Thought/Final Answer."
        else:
            tool_name, kwargs = parsed
            entry = TOOLS.get(tool_name)
            if entry is None:
                observation = f"Unknown tool '{tool_name}'. Available: {', '.join(TOOLS)}"
            else:
                fn, _ = entry
                try:
                    observation = fn(**kwargs)
                except TypeError as e:
                    observation = f"Tool call failed: {e}. Check the argument names."
        scratchpad += f"Observation: {observation}\n"
        if verbose:
            print(f"Observation: {observation}")

    # max_steps exhausted — this fires in real life more often than you think.
    fallback = (
        f"Stopped after {max_steps} steps without a final answer (max_steps guard). "
        "Treat the root cause as unknown and escalate to a human with the scratchpad above."
    )
    if verbose:
        print(f"\n[stopped: {fallback}]")
    return fallback


# TODO(Stage1-Exercise 3): log the token/cost meter. Count scratchpad length
# each step and print it — watch the Context Window fill up as the loop turns.
# TODO(Stage1-Exercise 4): make parse_action accept JSON actions as well as
# the text format, e.g. Action: {"tool": "query_logs", "args": {...}}
