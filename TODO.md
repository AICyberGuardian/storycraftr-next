# StoryCraftr TODO

This file tracks the highest-priority engineering work identified by the March 2026 repository audit.

Scope:
- Close the gap between the current fail-closed commit pipeline and a fully validator-gated, fully auditable autonomous writing pipeline.
- Turn prompt-only story guidance into explicit machine-checked contracts where practical.
- Produce operational proof for real-provider runs instead of relying only on mocked tests and documentation claims.

## P0: Required Before Claiming “Fully Validator-Gated”

- Persist raw planner responses for every attempt in `outline/chapter_packets/chapter-<nnn>/`.
- Persist raw semantic-review, coherence-review, and state-extractor model responses for every attempt.
- Require coherence gating on every chapter for all real-provider runs, not only strict-autonomous mode.
- Fail closed for autonomous real-provider runs when validator independence cannot be established from the active model-routing path.
- Add deterministic pre-commit contradiction checks for hard canon facts that should never depend on an LLM judge alone.
- Add deterministic pre-commit checks that scene-plan coverage survived drafting/editing/stitching instead of relying only on prompt guidance.

## P0: Auditability and Forensics

- Add packet-local attempt manifests that index every retry, model choice, failure reason, and persisted artifact.
- Record explicit rollback events when commit-path rollback is triggered.
- Make failed early-stage planner/reviewer/extractor halts reconstructable from disk artifacts alone.
- Add a stable schema for any new raw-attempt artifacts so downstream tooling can rely on them.

## P1: Semantic and Coherence Hardening

- Add deterministic contradiction checks for character death, location occupancy, impossible timeline jumps, and chapter-to-canon fact reversals.
- Strengthen coherence validation so it is not just a single `PASS` or `FAIL` LLM verdict over a long prompt.
- Add explicit coverage checks for unresolved required scene beats: goal, conflict pressure, stakes movement, and outcome/disaster movement.
- Revisit provider-routing policy so reviewer and coherence roles prefer genuinely independent families, not just alternate ranked models.

## P1: Story-Quality Enforcement

- Promote the most important rules from `storycraftr/prompts/corpus.md` into explicit validator checks.
- Add validators for filler scenes, summary-heavy stitch output, and weak chapter endings.
- Add validators for POV drift and obvious head-hopping if the scene contract is supposed to remain single-POV.
- Add machine-checkable chapter ending pressure rules so chapters do not commit with flat endings.

## P1: Operational Proof

- Capture and keep at least one successful multi-chapter real-provider artifact set for regression review.
- Add an automated smoke profile that exercises strict autonomous `storycraftr book` with packet/audit assertions against real-provider or replay-safe fixtures.
- Document exactly what constitutes a production-ready autonomous run versus an experimental supervised run.
- Add a repeatable runbook that includes failure-recovery and rollback verification on real-provider executions.

## P2: Documentation and Contributor Hygiene

- Keep `README.md`, `docs/getting_started.md`, and `release_notes.md` aligned with the actual runtime guarantees instead of aspirational wording.
- Update contributor docs whenever a backlog item above is closed so maintainers know what changed in the runtime contract.
- Add a short operator playbook for reviewing `chapter_packets`, `book_audit.json`, `book_audit.md`, and `narrative_audit.jsonl` after strict-provider runs.
- Reevaluate whether the unsafe direct-write command path should remain available in production profiles.

## P2: Nice-To-Have Follow-Up

- Add packet visualization or summary tooling for quickly reviewing why a chapter passed or failed.
- Add comparative validator telemetry so model families can be evaluated by retry rate, semantic-failure rate, and coherence-failure rate.
- Add a compact machine-readable “run health” summary file for automation and dashboards.

## Current Status Summary

Already strong:
- Fail-closed commit ordering and rollback
- Chapter packets and validator reports
- Run-level audits
- State mutation audit trail
- Planner-schema, prose-completeness, and state-signal guards

Still incomplete:
- Fully deterministic semantic validation
- Guaranteed independent validators
- Full raw-attempt artifact persistence
- Full runtime enforcement of the deeper story corpus
- Real-provider operational proof
