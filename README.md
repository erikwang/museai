# ProdGuard — Production Incident Triage Agent (practice project)

An AI agent that investigates production incidents on its own: given a
symptom, it queries logs, grid job status and runbooks in a ReAct loop and
produces an evidence-backed incident report. Actions are drafted for human
approval, never auto-executed.

Built as a staged learning project — see [PROJECT.md](PROJECT.md) for the
full design and roadmap.

| Stage | What | Status |
|---|---|---|
| 1 | Hand-written ReAct loop, fake tools, synthetic data | ✅ in `prodguard/` |
| 2 | Structured Output + evidence rule enforced in code | ✅ code complete (30 tests, 0 skipped) — local-model acceptance runs remain |
| 3 | RAG over runbooks | ✅ code complete (38 tests) |
| 4 | LangGraph + human-in-the-loop + checkpointing | ⬜ |
| 5 | Evaluation set (20 scenarios, hallucination rate) | ⬜ |
| 6 | MCP server + multi-agent (optional) | ⬜ |

Start here: [`prodguard/README.md`](prodguard/README.md)

> All data is fictional and synthetic. No real company data, ever.
