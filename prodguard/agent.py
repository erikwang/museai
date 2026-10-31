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

import re

from llm import MockLLM
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
"""

ACTION_RE = re.compile(r"Action:\s*(\w+)\((.*?)\)", re.DOTALL)
ARG_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


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
              show_prompt: bool = False) -> str:
    """Run the ReAct loop on one question. Returns the final answer text.

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
