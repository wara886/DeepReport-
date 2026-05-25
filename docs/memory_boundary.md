# Durable Memory Boundary

FinSight has optional durable memory for report-run context. The implemented store is file-backed, is disabled by default in `configs/app.yaml`, and must never be treated as evidence.

## Implemented Behavior

- `src/agents/durable_memory.py` writes bounded working, episodic and company-domain JSON snapshots below `memory/`.
- A later run can read compact notes about prior decisions, scores and planner constraints.
- The context brief explicitly warns that every factual report claim still requires current `evidence_id` citations.
- `src/agents/conversation_memory.py` keeps bounded run-level intent, constraints and verifier feedback for planning and revision.

## Default Configuration

```yaml
memory:
  durable:
    enabled: false
    root: memory
    context_scope: planner_router
  chat:
    enabled: false
    root: memory/chat
    boundary: context_only_not_evidence
```

## Safety Boundary

- Memory may guide query planning or preserve verifier feedback.
- Memory may not supply company facts, financial figures or citations.
- Enabling memory does not relax verifier or quality-gate checks.
- Local `memory/` contents are runtime state and are excluded from the public repository.
