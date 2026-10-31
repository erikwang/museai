"""
ProdGuard — Stage 1 LLM clients.

The agent loop only needs one method:  complete(prompt: str) -> str

Three implementations:
  * MockLLM      — scripted, deterministic, NO API key needed. Start here.
                   It plays a fixed investigation strategy so you can watch
                   the ReAct loop turn and debug the harness itself.
  * AnthropicLLM — real model via the Anthropic API (fill in the TODO).
  * OpenAILLM    — real model via the OpenAI API (fill in the TODO).

Lesson: the harness (loop, parsing, tools) is model-agnostic. Swap the
client and the exact same agent code runs on a real brain.
"""
from __future__ import annotations

import os
import re


class MockLLM:
    """A scripted fake brain for the demo scenario.

    Strategy (notice how each step REACTS to the last Observation):
      1. No observations yet        -> check the pricing logs around 15:00
      2. Log mentions a job id      -> check that job's status
      3. Job checked                -> check current service health
      4. Health checked             -> Final Answer, citing evidence ids
    """

    name = "mock"

    def complete(self, prompt: str) -> str:
        # NOTE: search the whole scratchpad, not just Observation first lines —
        # observations are multi-line, and the interesting clue (a job id in
        # an early log line) is rarely on line one. A classic beginner bug.
        if "Observation:" not in prompt:
            return (
                "Thought: I don't know the cause yet. "
                "I should check the pricing service logs first.\n"
                'Action: query_logs(service="pricing")'
            )

        job_match = re.search(r"job_id=(\w+)", prompt)
        if job_match and "[evidence: job:" not in prompt:
            job_id = job_match.group(1)
            return (
                "Thought: The log points to a job that was running when memory "
                "spiked. Let me check what that job was doing.\n"
                f'Action: get_job_status(job_id="{job_id}")'
            )

        if "[evidence: health:" not in prompt:
            return (
                "Thought: I have a likely cause. Let me confirm the current "
                "state of the service before answering.\n"
                'Action: get_service_health(service="pricing")'
            )

        return (
            "Thought: I have enough evidence to answer.\n"
            "Final Answer: The pricing service was OOM-killed at 15:02 "
            "[evidence: log:pricing-1502-oom]. The vol_fit job vol_fit_4821 "
            "loaded 3,758 option chains at 14:58 and exhausted the heap it "
            "shares with the pricing service [evidence: job:vol_fit_4821]. "
            "The service is still down and needs a restart "
            "[evidence: health:pricing] — restart is a draft action only, "
            "it requires human approval."
        )


class AnthropicLLM:
    """Real brain via Anthropic. TODO(Stage1-Exercise 2): complete this."""

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5", temperature: float = 0.0):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "Set ANTHROPIC_API_KEY first (see .env.example), "
                "or run with --demo to use MockLLM."
            )
        self.model = model
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        # TODO: 
        #   from anthropic import Anthropic
        #   client = Anthropic()
        #   msg = client.messages.create(model=self.model,
        #       max_tokens=1024, temperature=self.temperature,
        #       messages=[{"role": "user", "content": prompt}])
        #   return msg.content[0].text
        raise NotImplementedError("Fill in the Anthropic call — see TODO above.")


class OpenAILLM:
    """Real brain via OpenAI. TODO(Stage1-Exercise 2, alternative)."""

    name = "openai"

    def __init__(self, model: str = "gpt-5", temperature: float = 0.0):
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "Set OPENAI_API_KEY first (see .env.example), "
                "or run with --demo to use MockLLM."
            )
        self.model = model
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        # TODO:
        #   from openai import OpenAI
        #   client = OpenAI()
        #   resp = client.responses.create(model=self.model,
        #       temperature=self.temperature, input=prompt)
        #   return resp.output_text
        raise NotImplementedError("Fill in the OpenAI call — see TODO above.")
