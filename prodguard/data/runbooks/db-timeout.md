# Runbook: Database Timeout

Applies to: a service reporting database timeouts while the database
itself may still be healthy. The common trap is restarting the service
when the real problem is one saturated connection pool.

## Triage the timeout

- Confirm the timeout lines in the service log and note the first
  occurrence time; check whether the database accepts new connections.
- Check the connection pool: full saturation (every connection busy)
  points at a slow query or a connection leak, not a dead database.

## Recovery steps

- If one long-running query is holding the pool, cancel that query
  through the DBA-approved procedure BEFORE restarting anything.
- Restart the service only if connections are leaked, i.e. the pool
  does not drain after the offending query has ended.

## Escalation and follow up

- Escalate to the DBA team with the offending query id and the pool
  metrics attached; do not just say "the database is slow".
- Follow up: review statement timeouts and add pool-usage alerting so
  saturation pages before users notice.
