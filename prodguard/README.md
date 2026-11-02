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

## Run a real model locally (no subscription, no API key)

With a GPU you can run an open-weight model on your own machine with
[Ollama](https://ollama.com) — free, private, and it plugs straight into
the same agent loop:

```bash
ollama pull qwen3:8b        # ~5.2 GB, comfortable on a 12 GB card (RTX 4070 Ti)
python main.py --provider ollama
# stronger brain, tighter fit on 12 GB (~9.3 GB weights, cap context):
ollama pull qwen3:14b
python main.py --provider ollama --model qwen3:14b
```

Notes from the field:
- `OllamaLLM` pins `num_ctx=16384`. On ≤12 GB cards Ollama's default
  context can be tiny (4K), which silently truncates the system prompt.
- Local models sometimes emit `<think>…</think>` blocks; `llm.py` strips
  them before the reply reaches the ReAct parser. Cloud APIs hide this
  housekeeping — locally it is yours.
- Expect the 8B to occasionally fumble the Action format where a frontier
  cloud model would not. That gap *is* the lesson: watch the loop recover.
- Prefer a GUI? LM Studio serves the same models behind an
  OpenAI-compatible endpoint and works the same way.

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
| `llm.py` | Brain clients: `MockLLM` (scripted), `OllamaLLM` (local GPU, ready to use), Anthropic/OpenAI stubs |
| `tools.py` | Fake tools over local synthetic data; every result carries an evidence id |
| `main.py` | CLI entry point (`--demo` / `--provider` / `--question`) |
| `data/` | Synthetic logs, service health, grid job status |
| `tests/` | Stdlib unittest smoke tests |

## Stage 1 exercises (marked `TODO` in the code)

1. ✅ **Add a 4th tool** — DONE: `get_recent_changes(service)` backed by
   `data/changes.json`, registered in `TOOLS`. Notice the investigation
   story it completes: a 14:31 config change (wildcard chain_spec) →
   the job loading 3,758 chains → the OOM. Try adding a 5th tool yourself
   the same way (e.g. `get_disk_usage(service)`).
2. **Wire a real brain** — run the same question on your local model
   (`--provider ollama`, ready out of the box) and compare its tool choices
   with MockLLM's script. *Or* complete `AnthropicLLM.complete()` /
   `OpenAILLM.complete()` in `llm.py` with a cloud API key.
3. **Watch the Context Window fill** — log the scratchpad length each step.
4. **JSON actions** — extend `parse_action` to also accept
   `Action: {"tool": "...", "args": {...}}` (your bridge to Stage 2's
   Structured Output).

## Stage 1 acceptance criteria

- [ ] Demo runs end-to-end; agent takes ≥2 tool steps before answering
- [ ] Final answer cites evidence ids that appeared in Observations
- [ ] With logs emptied, the agent answers "unknown" instead of inventing a cause
- [ ] `max_steps` guard demonstrably stops a forever-looping brain (see tests)

## Stage 2 — Structured Output + evidence rules (skeleton)

The free-text Final Answer becomes a validated JSON incident report:

```bash
python main.py --demo --report          # offline, scripted brain
python main.py --provider ollama --report
```

Pipeline: ReAct loop → free-text Final Answer → formatter call
(Ollama `format` = constrained decoding against `REPORT_SCHEMA`)
→ `json.loads` → `validate_report()` → report, or an honest
`unknown` fallback if validation fails for good.

**Status: COMPLETE — all 30 tests pass, 0 skipped.**
- ✅ `YU-1` in `report.py` — invented evidence ids rejected (exact-match
  against the scratchpad; the `[evidence: none]` placeholder counts as
  fabrication too).
- ✅ `YU-2` in `report.py` — a non-unknown root cause must cite at least
  one `log:` evidence id (primary source, not a health summary).
- ✅ `YU-3` in `agent.py` — retry-once: parse/validation errors are fed
  back to the model for one targeted fix before the `unknown` fallback.

Remaining acceptance item (hardware side): local qwen3:8b produces a
passing report on the pricing question 3 times in a row via
`python main.py --provider ollama --report`.
