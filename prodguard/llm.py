"""
ProdGuard — Stage 1 LLM clients.

The agent loop only needs one method:  complete(prompt: str) -> str

Four implementations:
  * MockLLM      — scripted, deterministic, NO API key needed. Start here.
                   It plays a fixed investigation strategy so you can watch
                   the ReAct loop turn and debug the harness itself.
  * OllamaLLM    — a REAL model running on your own GPU via Ollama.
                   No subscription, no API key, no data leaves your machine.
                   This is the recommended real brain if you have a GPU.
  * AnthropicLLM — real model via the Anthropic API (fill in the TODO).
  * OpenAILLM    — real model via the OpenAI API (fill in the TODO).

Lesson: the harness (loop, parsing, tools) is model-agnostic. Swap the
client and the exact same agent code runs on a real brain.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class MockLLM:
    """A scripted fake brain for the demo scenario.

    Strategy (notice how each step REACTS to the last Observation):
      1. No observations yet        -> check the pricing logs around 15:00
      2. Log mentions a job id      -> check that job's status
      3. Job checked                -> check current service health
      4. Health checked             -> check recent changes ('what changed?')
      5. Changes checked            -> Final Answer, citing evidence ids
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

        if "[evidence: change:" not in prompt:
            return (
                "Thought: Before I conclude, the classic triage question: "
                "what changed today? Let me check recent changes.\n"
                'Action: get_recent_changes(service="pricing")'
            )

        return (
            "Thought: I have enough evidence to answer.\n"
            "Final Answer: The pricing service was OOM-killed at 15:02 "
            "[evidence: log:pricing-1502-oom]. The vol_fit job vol_fit_4821 "
            "loaded 3,758 option chains at 14:58 and exhausted the heap it "
            "shares with the pricing service [evidence: job:vol_fit_4821]. "
            "The trigger was a 14:31 config change that widened the vol_fit "
            "prefetch chain_spec to a wildcard [evidence: change:CHG-1042]. "
            "The service is still down and needs a restart "
            "[evidence: health:pricing] — restart is a draft action only, "
            "it requires human approval."
        )

    def complete_structured(self, prompt: str, schema: dict) -> str:
        """Scripted structured reply: the EXAMPLE_REPORT from report.py,
        serialised. Lets the Stage 2 pipeline run end-to-end offline."""
        from report import EXAMPLE_REPORT

        return json.dumps(EXAMPLE_REPORT)


def _strip_think(text: str) -> str:
    """Remove <think>...</think> blocks some local models emit.

    The ReAct parser looks for 'Thought:' / 'Action:' lines; a raw thinking
    block in front of them can confuse it (and wastes Context Window when the
    reply is appended to the scratchpad). Cloud APIs hide this for you —
    locally, cleaning model output is your job. Remember this moment when
    Stage 2 introduces Structured Output.
    """
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


class OllamaLLM:
    """Real brain on your own GPU, served by Ollama (https://ollama.com).

    Setup (Windows/macOS/Linux):
        1. Install Ollama
        2. ollama pull qwen3:8b        # ~5.2 GB — comfy on a 12 GB card
           ollama pull qwen3:14b       # ~9.3 GB — stronger, tight on 12 GB
        3. Ollama serves http://localhost:11434 automatically.

    Uses Ollama's native /api/chat endpoint with stdlib only (no pip
    packages), and pins num_ctx explicitly: on <=12 GB cards Ollama's
    default context can be as small as 4K, which silently truncates the
    agent's system prompt and produces baffling, tool-less behaviour.

    Three field lessons baked in:
      * think=False — Qwen3's thinking mode can burn minutes generating
        hidden reasoning before its (short) ReAct reply. ReAct already
        externalises the reasoning as 'Thought:' lines; we don't need a
        second, invisible one.
      * num_predict cap — a ReAct reply is a few lines, never an essay.
        Without a cap, a rambling model can generate 'forever' at 100% GPU
        and the caller sees nothing, because...
      * streaming — with stream=False the API returns only when the FULL
        reply is done, so a working model looks identical to a hung one.
        Streaming prints tokens as they are produced: you can watch the
        model work, and spot a repetition loop in seconds.
    """

    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        temperature: float = 0.0,
        num_ctx: int = 16384,
        num_predict: int = 512,
        show_tokens: bool = True,
    ):
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen3:8b")
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.show_tokens = show_tokens
        self.name = f"ollama:{self.model}"

    @staticmethod
    def _collect_stream(lines, on_token=None) -> str:
        """Assemble content from Ollama's NDJSON stream (one JSON per line)."""
        parts = []
        for line in lines:
            if not line or not line.strip():
                continue
            chunk = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
            piece = chunk.get("message", {}).get("content", "")
            if piece:
                parts.append(piece)
                if on_token:
                    on_token(piece)
        return "".join(parts)

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        def _show(piece: str) -> None:
            print(piece, end="", flush=True)

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                if self.show_tokens:
                    print("[model generating — live tokens]", flush=True)
                content = self._collect_stream(resp, on_token=_show if self.show_tokens else None)
                if self.show_tokens:
                    print("\n[model done]", flush=True)
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.host}. Is it installed and running? "
                f"Install from https://ollama.com, then: ollama pull {self.model} "
                f"(original error: {e})"
            ) from e
        except TimeoutError as e:
            raise RuntimeError(
                "Ollama timed out — the first call loads the model into VRAM "
                "and can be slow; try again, or pull a smaller model (qwen3:8b)."
            ) from e
        if not content:
            raise RuntimeError("Ollama returned an empty reply.")
        return _strip_think(content)

    def complete_structured(self, prompt: str, schema: dict) -> str:
        """One call with Ollama's `format` parameter: constrained decoding.

        The model physically cannot emit tokens that break the JSON
        Schema — compare this with Stage 1's 'please reply in this format'
        prompt politeness. Non-streaming is fine here: a report is short.
        Returns the raw reply text (JSON, if the model behaved); parsing
        and validation are agent.py / report.py's job, not the client's.
        """
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "format": schema,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": 1024,
            },
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.host} for a structured call. "
                f"Is it installed and running? (original error: {e})"
            ) from e
        content = data.get("message", {}).get("content", "")
        if not content:
            raise RuntimeError(f"Ollama returned an empty structured reply: {data}")
        return _strip_think(content)


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
