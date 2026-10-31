"""
ProdGuard — Stage 1 fake tools.

These tools read LOCAL SYNTHETIC data files only (data/*.json, data/logs/*.log).
They stand in for the real things you would call in production:
    query_logs        -> Splunk / ELK / journalctl
    get_job_status    -> LSF `bjobs` / Symphony session API
    get_service_health-> your monitoring / health-check endpoint

Design rule (anti-hallucination): every Observation carries an evidence id,
e.g. [evidence: log:pricing-1502-oom]. The final answer must cite these ids.
If a tool has no data, it says so plainly — the agent must then answer
"unknown" instead of inventing a cause.

The tools are deliberately 'dumb': they fetch facts, they never judge.
get_recent_changes will happily return a change record — deciding whether
that change *caused* the incident is the model's job, in its Thought step.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _load_json(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def query_logs(service: str, time_window: str = "") -> str:
    """Return log lines for a service. Optionally filter by HH:MM substring.

    Args:
        service: service name, e.g. "pricing"
        time_window: optional substring filter, e.g. "15:0" for 15:00-15:09
    """
    log_file = DATA_DIR / "logs" / f"{service}.log"
    if not log_file.exists():
        return f"[evidence: none] No logs found for service '{service}'."

    lines = log_file.read_text(encoding="utf-8").splitlines()
    if time_window:
        lines = [ln for ln in lines if time_window in ln] or lines

    # Tag the most "interesting" line with a stable evidence id so the
    # agent (and you) can cite it later.
    tagged = []
    for ln in lines:
        m = re.search(r"(\d{2}):(\d{2})", ln)
        stamp = f"{m.group(1)}{m.group(2)}" if m else "xxxx"
        tag = "oom" if "OOM" in ln or "OutOfMemory" in ln else "line"
        tagged.append(f"[evidence: log:{service}-{stamp}-{tag}] {ln}")
    return "\n".join(tagged) if tagged else "[evidence: none] Log file is empty."


def get_job_status(job_id: str) -> str:
    """Return status of a grid/HPC job by id, e.g. "vol_fit_4821"."""
    jobs = _load_json("jobs.json")
    job = jobs.get(job_id)
    if not job:
        return f"[evidence: none] No job with id '{job_id}'."
    summary = ", ".join(f"{k}={v}" for k, v in job.items())
    return f"[evidence: job:{job_id}] {summary}"


def get_service_health(service: str) -> str:
    """Return current health snapshot of a service."""
    services = _load_json("services.json")
    svc = services.get(service)
    if not svc:
        return f"[evidence: none] No service named '{service}'."
    summary = ", ".join(f"{k}={v}" for k, v in svc.items())
    return f"[evidence: health:{service}] {summary}"


def get_recent_changes(service: str) -> str:
    """Return recent deploys / config changes for a service.

    The triage question behind this tool is the oldest one in production
    support: 'what changed?' Most incidents follow a change, so an agent
    that cannot ask this question is missing half the story.
    Backed by data/changes.json (synthetic).
    """
    changes = _load_json("changes.json")
    records = changes.get(service)
    if records is None:
        return f"[evidence: none] No change records for service '{service}'."
    if not records:
        return f"[evidence: none] No recent changes recorded for service '{service}'."
    lines = [
        f"[evidence: change:{r['change_id']}] {r['time']} {r['type']} by {r['by']}: {r['summary']}"
        for r in records
    ]
    return "\n".join(lines)


# The tool table: name -> (callable, one-line description for the prompt)
# Registering a tool here is ALL it takes: agent.py builds the prompt's
# tool list from this table, and the loop dispatches through it too.
TOOLS = {
    "query_logs": (
        query_logs,
        'query_logs(service="pricing", time_window="15:0") — read a service\'s logs',
    ),
    "get_job_status": (
        get_job_status,
        'get_job_status(job_id="vol_fit_4821") — check a grid job',
    ),
    "get_service_health": (
        get_service_health,
        'get_service_health(service="pricing") — current health snapshot',
    ),
    "get_recent_changes": (
        get_recent_changes,
        'get_recent_changes(service="pricing") — recent deploys/config changes; always ask: what changed?',
    ),
}

# Stage1-Exercise 1 — DONE (see get_recent_changes above). Notice what it
# took: one function + one data file + one row in this table. No changes
# to agent.py at all. That is the payoff of the tool-table design.
