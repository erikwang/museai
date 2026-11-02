#!/usr/bin/env python3
"""
ProdGuard — Stage 1 entry point.

Run the demo (no API key needed, scripted MockLLM):

    python main.py --demo

Run against a LOCAL model on your own GPU via Ollama (no key, no cost):

    ollama pull qwen3:8b
    python main.py --provider ollama --question "Why did pricing fail at 3pm?"

Run against a cloud model (after you fill in llm.py and set your key):

    export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY=...
    python main.py --provider anthropic --question "Why did pricing fail at 3pm?"
"""
from __future__ import annotations

import argparse
import json

from agent import run_agent
from llm import AnthropicLLM, MockLLM, OllamaLLM, OpenAILLM

DEMO_QUESTION = "Why did the pricing service fail at 3pm?"


def main() -> None:
    ap = argparse.ArgumentParser(description="ProdGuard Stage 1 — hand-written ReAct agent")
    ap.add_argument("--demo", action="store_true", help="use the scripted MockLLM (no API key)")
    ap.add_argument("--provider", choices=["ollama", "anthropic", "openai"], default="ollama")
    ap.add_argument("--model", default=None, help="model name for --provider ollama, e.g. qwen3:14b")
    ap.add_argument("--show-prompt", action="store_true",
                    help="print the exact prompt string sent to the model at each step")
    ap.add_argument("--report", action="store_true",
                    help="Stage 2: output a validated JSON incident report instead of free text")
    ap.add_argument("--question", default=DEMO_QUESTION)
    args = ap.parse_args()

    if args.demo:
        llm = MockLLM()
    elif args.provider == "ollama":
        llm = OllamaLLM(model=args.model)
    elif args.provider == "anthropic":
        llm = AnthropicLLM()
    else:
        llm = OpenAILLM()

    print(f"Question: {args.question}")
    print(f"Brain: {llm.name}\n")
    result = run_agent(args.question, llm=llm, show_prompt=args.show_prompt,
                       as_report=args.report)
    if isinstance(result, dict):
        print("\n=== INCIDENT REPORT (JSON) ===")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("\n=== FINAL ANSWER ===")
        print(result)


if __name__ == "__main__":
    main()
