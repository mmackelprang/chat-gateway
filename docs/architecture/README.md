# Architecture decisions

Decisions that span more than one PR, or that constrain future work, live here
as ADRs. Single-PR choices belong in the spec/plan under `docs/superpowers/`,
not here.

An ADR records: the context, the **evidence** it rests on, the options with
honest trade-offs, the decision, its consequences, what could not be verified,
and what would trigger revisiting it. An ADR that hides a gap is worse than no
ADR — it converts an open question into a silent assumption.

ADRs are not relitigated without explicit user direction. If a later decision
conflicts with one, say so in the new ADR and supersede it deliberately.

## Index

| ADR | Date | Status | Subject |
|---|---|---|---|
| [0001 — Tier-2 interaction model](decisions/2026-07-29-tier2-interaction-model.md) | 2026-07-29 | Proposed | Whether to depend on undocumented topic-as-function routing for card interactions; where action identity lives now that `action.id` arrives empty; how breakage is detected |

## Related

- `CLAUDE.md` — the six hard rules. An ADR may not quietly override one; §9 of
  ADR-0001 shows the audit an ADR is expected to carry.
- `docs/consumers/` — per-tenant contracts (jobhunt, aitrader).
- `docs/superpowers/specs/` + `plans/` — Planner's per-change designs, which
  defer cross-cutting calls to ADRs here.
- `docs/BUILDER_QUEUE.md` — items marked `⏸ blocked · ADR` are waiting on a
  decision in this directory.
