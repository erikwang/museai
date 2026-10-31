# ProdGuard — Stage 1: Hand-written ReAct Agent

A production incident triage agent, built **without any framework** —
a bare ReAct loop (Thought → Action → Observation) over fake tools and
fully synthetic data. Stage 1 of the ProdGuard practice project
(see `../PROJECT.md` for the full roadmap).

> ⚠️ All data in `data/` is fictional and synthetic. Never replace it with
> real company logs, hostnames, or internal system data.

## Quick start (no API key needed)

```bash
cd prodguard
python main.py --demo
python -m unittest discover -s tests -v
```

The demo uses `MockLLM`, a scripted brain, so you can watch the loop turn
and debug the harness before spending a cent on API calls.

## What you should see

```
--- step 1 ---
Thought: I don't know the cause yet. I should check the pricing logs...
Action: query_logs(service="pricing", time_window="15:0")
Observation: [evidence: log:pricing-1502-oom] ... OutOfMemoryError ...

--- step 2 ---  (checks the job the log pointed to)
--- step 3 ---  (confirms current service health)
--- step 4 ---
Final Answer: ... OOM-killed at 15:02 [evidence: log:pricing-1502-oom] ...
```

## Files

| File | Role |
|---|---|
| `agent.py` | ⭐ The ReAct loop + action parser. **Read this first — it is the lesson.** |
| `llm.py` | Brain clients: `MockLLM` (scripted) + Anthropic/OpenAI stubs for you to complete |
| `tools.py` | Fake tools over local synthetic data; every result carries an evidence id |
| `main.py` | CLI entry point (`--demo` / `--provider` / `--question`) |
| `data/` | Synthetic logs, service health, grid job status |
| `tests/` | Stdlib unittest smoke tests |

## Stage 1 exercises (marked `TODO` in the code)

1. **Add a 4th tool** — `get_recent_changes(service)` backed by a new
   `data/changes.json`. Register it in `TOOLS` and watch the prompt update itself.
2. **Wire a real brain** — complete `AnthropicLLM.complete()` *or*
   `OpenAILLM.complete()` in `llm.py` (temperature is already 0), set your
   key from `.env.example`, and run the same question. Compare its tool
   choices with MockLLM's script.
3. **Watch the Context Window fill** — log the scratchpad length each step.
4. **JSON actions** — extend `parse_action` to also accept
   `Action: {"tool": "...", "args": {...}}` (your bridge to Stage 2's
   Structured Output).

## Stage 1 acceptance criteria

- [ ] Demo runs end-to-end; agent takes ≥2 tool steps before answering
- [ ] Final answer cites evidence ids that appeared in Observations
- [ ] With logs emptied, the agent answers "unknown" instead of inventing a cause
- [ ] `max_steps` guard demonstrably stops a forever-looping brain (see tests)

## Next

Stage 2: Structured Output (JSON Schema incident report) + the
"no evidence = unknown" rule enforced by code, not by prompt politeness.
