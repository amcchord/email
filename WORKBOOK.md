# Mail Client Workbook

This is the navigation page for ongoing work on `email.mcchord.net`. It keeps
project continuity in the repository so a new session can resume without
depending on chat history.

## Quick Resume

1. Read [Current Status](docs/progress/CURRENT.md).
2. Read the latest [Journal](docs/progress/JOURNAL.md) entry.
3. Check durable [Decisions](docs/progress/DECISIONS.md) that affect the task.
4. Run `git status --short --branch`.
5. Run `make remote-status` if live state matters.

## Working Model

```text
This checkout -> branch + checks -> origin/main -> /opt/mail on production
       |                                                |
       +---- workbook records intent and evidence ------+
```

Normal development happens in this checkout. Production is observed over SSH
and changed only as an explicit deployment or operations task. The Git commit
deployed to `/opt/mail` is the release identifier.

## Workbook Files

| File | Purpose | Editing rule |
| --- | --- | --- |
| `docs/progress/CURRENT.md` | Present objective, baseline, queue, blockers, next action | Rewrite as the current truth |
| `docs/progress/JOURNAL.md` | Evidence-backed session history | Append newest entry at the top |
| `docs/progress/DECISIONS.md` | Durable technical and operating choices | Append numbered decisions; supersede instead of deleting |
| `docs/operations/RUNBOOK.md` | Setup, inspection, deploy, incident, and recovery procedures | Update when actual operations change |
| `AGENTS.md` | Guardrails and completion rules for coding agents | Keep concise and repository-wide |

## Work Item Shape

Use this compact form in `CURRENT.md`:

```markdown
### P1 — Short outcome

- State: ready | active | blocked | verifying
- Why: user or system value
- Scope: likely files/components
- Acceptance: observable definition of done
- Next: one concrete action
```

Keep only active and near-term work in `CURRENT.md`. Completed work belongs in
the journal and Git history. Do not turn the workbook into a second issue
tracker.

## Session Closeout

Before handing off:

1. Review `git diff` and `git status`.
2. Record validation results, including failures or skipped checks.
3. Record every production mutation (or explicitly say “none”).
4. Update current status and name one next safe action.
5. Add a decision entry only if future work needs to honor it.

## Initial Baseline

The baseline observed on 2026-08-26 is recorded in
[Current Status](docs/progress/CURRENT.md). Re-run `make remote-status` rather
than assuming it remains current.
