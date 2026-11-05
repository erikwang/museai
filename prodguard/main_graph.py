#!/usr/bin/env python3
"""
ProdGuard — Stage 4 entry point (LangGraph + human-in-the-loop).

First run — the graph investigates, builds the report, and (once
TODO(YU-2) is wired) STOPS at the approval gate:

    python main_graph.py --demo --thread case-1

The state is checkpointed in a local SQLite file, so you can close
this process, come back later, and resume the SAME thread:

    python main_graph.py --thread case-1 --resume approve
    python main_graph.py --thread case-1 --resume reject --note "not during market hours"
    python main_graph.py --thread case-1 --resume edit --action "restart pricing canary first"

With a real local model instead of the scripted demo brain:

    python main_graph.py --provider ollama --thread case-2 --question "Why did pricing fail?"
"""
from __future__ import annotations

import argparse
import json

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from graph_agent import build_graph, initial_state
from llm import MockLLM, OllamaLLM

DEMO_QUESTION = "Why did the pricing service fail at 3pm?"


def _show(result: dict) -> None:
    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value
        print("\n=== APPROVAL REQUESTED — the graph is PAUSED ===")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("\nThe state is checkpointed. Resume this thread with:")
        print("    python main_graph.py --thread <same-thread> --resume approve|reject|edit")
        return
    print("\n=== OUTCOME ===")
    print(result.get("outcome") or "(no outcome recorded)")
    if result.get("report"):
        print("\n=== INCIDENT REPORT (JSON) ===")
        print(json.dumps(result["report"], indent=2, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="ProdGuard Stage 4 — LangGraph + HITL")
    ap.add_argument("--demo", action="store_true", help="use the scripted MockLLM")
    ap.add_argument("--provider", choices=["ollama"], default="ollama")
    ap.add_argument("--model", default=None, help="model name for --provider ollama")
    ap.add_argument("--question", default=DEMO_QUESTION)
    ap.add_argument("--thread", default="case-1", help="checkpoint thread id")
    ap.add_argument("--db", default="checkpoints.sqlite", help="checkpoint database file")
    ap.add_argument("--resume", choices=["approve", "reject", "edit"], default=None,
                    help="resume a paused thread with this decision")
    ap.add_argument("--note", default="", help="approver note (with --resume)")
    ap.add_argument("--action", default=None, help="replacement action text (with --resume edit)")
    args = ap.parse_args()

    llm = MockLLM() if args.demo else OllamaLLM(model=args.model)
    config = {"configurable": {"thread_id": args.thread}}

    with SqliteSaver.from_conn_string(args.db) as checkpointer:
        graph = build_graph(llm=llm, checkpointer=checkpointer)
        if args.resume:
            decision = {"decision": args.resume, "note": args.note}
            if args.action:
                decision["action"] = args.action
            result = graph.invoke(Command(resume=decision), config)
        else:
            result = graph.invoke(initial_state(args.question), config)
    _show(result)


if __name__ == "__main__":
    main()
