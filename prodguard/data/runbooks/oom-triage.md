# Runbook: Service Out of Memory (OOM)

Applies to: any service killed by the runtime or OS with an
OutOfMemoryError / OOM-killed event. Written for the pricing service
pattern; the procedure is service-agnostic.

## Triage the memory failure

- Confirm the kill in the logs: look for FATAL OutOfMemory lines and the
  heap percentage trend in the minutes before the kill (a climb to ~98%
  followed by a kill is the classic signature).
- Identify what was loading memory in the same window: check grid jobs,
  cache warmers and prefetch activity, with sizes (how many records or
  option chains were loaded).
- Check recent changes for anything that widened a data set: wildcard
  specs, a larger universe, bigger batch sizes. Note the change id.

## Restart first recovery

- Restore service first, investigate second: restart the service using
  the approved restart procedure, and confirm the health endpoint
  reports the service UP before starting deeper analysis.
- After recovery, verify output freshness for the affected books before
  declaring the incident closed.
- Do NOT tune heap parameters or raise limits during the incident;
  capture the evidence first, tune later under a change record.

## Escalation and follow up

- If the service runs out of memory again within 24 hours, escalate to
  the service owner and raise a problem record.
- Follow up: propose memory admission control or a hard cap for the job
  that triggered the load, and review whether the triggering change
  should be permanently reverted rather than left in place.
