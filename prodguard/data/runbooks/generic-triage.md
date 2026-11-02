# Runbook: Generic Incident Triage

Applies to: every incident, alongside the specific runbook for the
failure type. This is the discipline layer, not a fix.

## Severity classification

- P1: a production service is down or market-facing output is stale.
  Page the on-call immediately.
- P2: service degraded but a workaround exists.
- P3: no user impact; investigate during business hours.

## Evidence discipline

- Every claim in the incident report must cite evidence: a log line, a
  job record, a change record, a health snapshot, or a runbook section.
- If the evidence is missing, write "unknown". Never reconstruct a
  timeline from memory or from what "usually" happens.

## Communication

- For P1, post the first status update within 15 minutes, even if the
  update is only "investigating, service down, next update in 30".
- Keep one timeline: first symptom, first evidence, recovery, close.
