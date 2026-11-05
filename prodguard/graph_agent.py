"""
ProdGuard — Stage 4: the same agent as a LangGraph state graph,
with a human-in-the-loop approval gate and checkpointing.

What changed vs agent.py (and what did NOT):

  * The hand-written while-loop is now an explicit graph: nodes are
    functions, routing is edges, and the 'scratchpad string' grew up
    into a structured State dict with named fields.
  * UNCHANGED: the tools (tools.py), the runbook retrieval
    (runbooks.py), the report builder + validator (agent.build_report /
    report.py), and the brains (llm.py). Stage 4 replaces the SCHEDULING
    layer only. If a Stage 4 bug smells like a Stage 1-3 bug, it is
    probably in the reused part — go look there first.

Graph shape:

    START -> investigate --(loop: more steps)--> investigate
                |
             (answer ready)
                v
              gate --(runbook not consulted)--> force_runbook
                |                                    |
             (consulted)                             v
                +-------------> build_report -> request_approval
                                                      |
                                        (approved)    |    (rejected)
                                                      v    v
                                              execute_simulated -> finalize -> END
                                                           finalize ------^

Human-in-the-loop: request_approval is supposed to PAUSE the graph
with langgraph's interrupt() and wait for a human decision; the
checkpointer (per thread_id) persists the whole State at that point,
so the process can exit and resume tomorrow exactly where it stopped.

YOUR THREE CORE TASKS are marked TODO(YU-1..3) below. The plumbing
around them runs end-to-end right now — with three deliberate holes:
the gate never forces, the approval never actually pauses, and the
routing after approval never executes anything. Safe holes, all of
them: the skeleton can under-deliver, it cannot over-act.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt  # noqa: F401  (you will use this in YU-2)

import agent as agent_mod
from llm import MockLLM
from tools import TOOLS


class ProdGuardState(TypedDict, total=False):
    """The graph's shared state — the scratchpad, grown up.

    Every field is plain data (str/bool/dict/None) ON PURPOSE: the
    checkpointer serialises this dict. The LLM object is NOT state —
    it is captured by the node closures in build_graph() instead.
    """
    question: str
    scratchpad: str            # the ReAct transcript (kept for evidence extraction)
    steps: int
    answer: str | None         # free-text Final Answer, once produced
    runbook_consulted: bool    # a get_runbook Observation exists
    gate_forced: bool          # the gate already forced a consultation once
    report: dict | None        # validated Stage 2 JSON report
    approval_status: str       # not_requested | pending | approved | rejected | edited
    approval_note: str
    approved_action: str | None  # the action text as approved (post-edit)
    execution: str | None      # simulated execution record — never real
    outcome: str | None        # final human-readable summary


# ------------------------------------------------------ YOUR core tasks
# (module-level on purpose: the homework tests import these directly,
#  the same way Stage 2's tests imported validate_report)


def runbook_gate(state: ProdGuardState) -> str:
    """Conditional edge out of the gate node: 'force_runbook' or
    'build_report'."""
    # TODO(YU-1) — the enforcement the Stage 3 prompt rule could
    #   never guarantee: if the investigation finished WITHOUT
    #   consulting a runbook, do not let the flow reach the report —
    #   route to 'force_runbook' so the procedure enters the record
    #   first. Guard against loops with state['gate_forced']: force
    #   at most once, then proceed to 'build_report' regardless.
    #   (Right now this returns 'build_report' unconditionally —
    #   the gate is wide open, exactly like the prompt-only era.)
    return "build_report"

def request_approval(state: ProdGuardState) -> dict:
    """The human-in-the-loop node: pause, wait, record the decision."""
    # TODO(YU-2) — make the graph actually STOP here:
    #   decision = interrupt({
    #       "kind": "approval_request",
    #       "severity": state["report"]["severity"],
    #       "action": state["approved_action"],
    #       "report": state["report"],
    #   })
    #   interrupt() raises inside the node; LangGraph checkpoints
    #   the state and returns control to the caller with the
    #   payload in result["__interrupt__"]. When the human answers,
    #   the caller resumes with Command(resume={...}) and THIS
    #   NODE RUNS AGAIN from the top, with interrupt() returning
    #   the resumed value instead of raising. (So: no side effects
    #   before the interrupt call — they would run twice.)
    #   Resume protocol (fixed — the CLI already speaks it):
    #     {"decision": "approve"|"reject"|"edit",
    #      "note": str, "action": str (only for edit)}
    #   Map it to state: approval_status approved/rejected/edited,
    #   approval_note from 'note', and for 'edit' replace
    #   approved_action with the human's 'action' text.
    #   (Right now: no pause at all — status 'auto_skipped', the
    #   flow sails through the checkpoint that exists to stop it.)
    return {"approval_status": "auto_skipped",
            "approval_note": "skeleton: interrupt() not wired yet"}

def route_after_approval(state: ProdGuardState) -> str:
    """Conditional edge: 'execute' or 'finalize'."""
    # TODO(YU-3) — route on the recorded decision:
    #   approval_status in ('approved', 'edited') -> 'execute'
    #   anything else (rejected, pending, auto_skipped) -> 'finalize'
    #   The safe default is what you see here: while approval is
    #   not wired, NOTHING routes to execution. Keep that bias —
    #   when in doubt, the graph must fall toward not acting.
    return "finalize"


# ------------------------------------------------------------------ nodes

def build_graph(llm=None, checkpointer=None):
    """Assemble and compile the graph. The brain is injected here and
    captured by the node closures, keeping State purely serialisable."""
    llm = llm or MockLLM()
    tool_list = "\n".join(f"- {desc}" for _, desc in (t for t in TOOLS.values()))

    def investigate_step(state: ProdGuardState) -> dict:
        """One ReAct step — the old loop body, as a node.

        Loops via a conditional edge until the model emits a Final
        Answer or MAX_STEPS is exhausted (same guard as Stage 1).
        """
        scratchpad = state.get("scratchpad") or (
            agent_mod.SYSTEM_PROMPT.format(tool_list=tool_list)
            + f"\n\nQuestion: {state['question']}\n"
        )
        steps = state.get("steps", 0) + 1
        reply = llm.complete(scratchpad)
        scratchpad += reply.strip() + "\n"
        update: dict = {"scratchpad": scratchpad, "steps": steps}

        if "Final Answer:" in reply:
            update["answer"] = reply.split("Final Answer:", 1)[1].strip()
            return update
        if steps >= agent_mod.MAX_STEPS:
            update["answer"] = (
                f"Stopped after {steps} steps without a final answer "
                "(max_steps guard). Root cause unknown; escalate to a human."
            )
            return update

        parsed = agent_mod.parse_action(reply)
        if parsed is None:
            observation = ("Invalid format. Reply with Thought/Action "
                           "or Thought/Final Answer.")
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
                if tool_name == "get_runbook":
                    # Tracked as a STATE FIELD, not by searching the
                    # transcript for a substring — remember the Stage 3
                    # lesson about instructions impersonating evidence.
                    update["runbook_consulted"] = True
        update["scratchpad"] = scratchpad + f"Observation: {observation}\n"
        return update

    def route_after_investigate(state: ProdGuardState) -> str:
        return "gate" if state.get("answer") else "investigate"

    def gate(state: ProdGuardState) -> dict:
        return {}  # pass-through node; the DECISION lives in runbook_gate()

    def force_runbook(state: ProdGuardState) -> dict:
        """Programmatic consultation — the program, not the model,
        fetches the procedure and appends it to the evidence record.
        The query is derived from failure keywords, the dumb way, on
        purpose: this node is a safety net, not a second brain."""
        text = (state.get("answer") or "") + " " + state["question"]
        low = text.lower()
        if "out of memory" in low or "oom" in low:
            query = "out of memory OOM restart recovery"
        elif "timeout" in low or "database" in low:
            query = "database timeout connection pool recovery"
        else:
            query = "incident triage severity escalation"
        observation = TOOLS["get_runbook"][0](query)
        return {
            "scratchpad": state["scratchpad"] + f"Observation: {observation}\n",
            "runbook_consulted": True,
            "gate_forced": True,
        }

    def build_report_node(state: ProdGuardState) -> dict:
        report = agent_mod.build_report(
            state["question"], state["answer"], state["scratchpad"], llm)
        return {"report": report,
                "approved_action": report.get("next_action_draft")}

    def execute_simulated(state: ProdGuardState) -> dict:
        """SIMULATED execution. Prints what WOULD happen. There is no
        real execution anywhere in this project — that is the point of
        the design, not a missing feature."""
        action = state.get("approved_action") or "(no action)"
        return {"execution": f"SIMULATED execution (not real): {action}"}

    def finalize(state: ProdGuardState) -> dict:
        report = state.get("report") or {}
        lines = [
            f"Severity: {report.get('severity', 'unknown')}",
            f"Root cause: {report.get('root_cause_hypothesis', 'unknown')}",
            f"Approval: {state.get('approval_status', 'not_requested')}"
            + (f" — {state['approval_note']}" if state.get("approval_note") else ""),
            f"Execution: {state.get('execution') or 'none — nothing was executed'}",
        ]
        return {"outcome": "\n".join(lines)}

    # ------------------------------------------------------------- wiring

    g = StateGraph(ProdGuardState)
    g.add_node("investigate", investigate_step)
    g.add_node("gate", gate)
    g.add_node("force_runbook", force_runbook)
    g.add_node("build_report", build_report_node)
    g.add_node("request_approval", request_approval)
    g.add_node("execute", execute_simulated)
    g.add_node("finalize", finalize)

    g.add_edge(START, "investigate")
    g.add_conditional_edges("investigate", route_after_investigate,
                            {"investigate": "investigate", "gate": "gate"})
    g.add_conditional_edges("gate", runbook_gate,
                            {"force_runbook": "force_runbook",
                             "build_report": "build_report"})
    g.add_edge("force_runbook", "build_report")
    g.add_edge("build_report", "request_approval")
    g.add_conditional_edges("request_approval", route_after_approval,
                            {"execute": "execute", "finalize": "finalize"})
    g.add_edge("execute", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())


def initial_state(question: str) -> ProdGuardState:
    return {
        "question": question,
        "scratchpad": "",
        "steps": 0,
        "answer": None,
        "runbook_consulted": False,
        "gate_forced": False,
        "report": None,
        "approval_status": "not_requested",
        "approval_note": "",
        "approved_action": None,
        "execution": None,
        "outcome": None,
    }
