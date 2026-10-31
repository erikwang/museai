#!/usr/bin/env python3
"""
ProdGuard — Stage 1 entry point.

Run the demo (no API key needed, scripted MockLLM):

    python main.py --demo

Run against a real model (after you fill in llm.py and set your key):

    export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY=...
    python main.py --provider anthropic --question "Why did pricing fail at 3pm?"
"""
from __future__ import annotations

import argparse

from agent import run_agent
from llm import AnthropicLLM, MockLLM, OpenAILLM

DEMO_QUESTION = "Why did the pricing service fail at 3pm?"


def main() -> None:
    ap = argparse.ArgumentParser(description="ProdGuard Stage 1 — hand-written ReAct agent")
    ap.add_argument("--demo", action="store_true", help="use the scripted MockLLM (no API key)")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--question", default=DEMO_QUESTION)
    args = ap.parse_args()

    if args.demo:
        llm = MockLLM()
    elif args.provider == "anthropic":
        llm = AnthropicLLM()
    else:
        llm = OpenAILLM()

    print(f"Question: {args.question}")
    print(f"Brain: {llm.name}\n")
    answer = run_agent(args.question, llm=llm)
    print("\n=== FINAL ANSWER ===")
    print(answer)


if __name__ == "__main__":
    main()
