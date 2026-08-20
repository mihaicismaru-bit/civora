# Needs Factory

Needs Factory is the first isolated production vertical of the EU Project Intelligence stack. Its job is to transform a minimal project/call input into an auditable, evidence-backed needs model before any narrative is generated.

## Product boundary

Needs Factory owns only domain logic specific to needs analysis:

`project intake -> call requirements -> research plan -> evidence -> evidence gaps -> primary research -> needs -> ranking -> causal model -> intervention traceability -> QA -> narrative-ready package`

It does **not** duplicate source crawling, generic source health, persistence, checkpoint orchestration or artifact registry capabilities already available in CIVORA / PARTENER.EU / DAPE.

## Reuse contract

- **PARTENER.EU** supplies call/domain intelligence and source-state/health. Material facts should consume last-known-good, non-quarantined sources and retain raw/semantic hashes when available.
- **CIVORA** supplies discovery/provenance patterns and external-source retrieval capability.
- **DAPE** supplies the production semantics: deterministic resume, checkpoints, artifact registry, QA gates, versioning and rollback. Needs Factory emits deterministic artifacts that can be registered by DAPE instead of maintaining a second registry.

See `contracts/ENGINE_REUSE_CONTRACT.json`.

## Canonical stages

1. `NF00_INTAKE`
2. `NF01_CALL_INTELLIGENCE`
3. `NF02_RESEARCH_PLAN`
4. `NF03_EXTERNAL_EVIDENCE`
5. `NF04_EVIDENCE_VALIDATION`
6. `NF05_GAP_DETECTION`
7. `NF06_PRIMARY_RESEARCH` (conditional)
8. `NF07_NEED_DISCOVERY`
9. `NF08_NEED_RANKING`
10. `NF09_CAUSAL_MODEL`
11. `NF10_INTERVENTION_TRACEABILITY`
12. `NF11_ADVERSARIAL_QA`
13. `NF12_PACKAGE`

No narrative document may be released before `NF11_ADVERSARIAL_QA` passes.

## Fail-closed principles

- no material factual claim without evidence;
- no statistical claim without measure type, population/universe, period and territory;
- no local claim silently inferred from national evidence;
- no school/beneficiary-specific perception or deficit without direct local evidence;
- no programme indicator may create a need;
- compliance requirements (equality, nondiscrimination, DNSH etc.) are separate from empirically diagnosed needs;
- contradictions remain contradictions until resolved;
- evidence gaps are first-class outputs and can trigger primary research;
- raw primary-research responses are canonical; charts and narrative are generated from raw data;
- historical reconstruction is cutoff-locked.

## Benchmark

`benchmarks/310224` is `NF-BENCH-001`. The blind historical run recovered the defensible core of the evaluator-accepted analysis while rejecting an unsupported discrimination need and exposing the missing primary-research layer. The benchmark therefore defines the initial production acceptance suite.

## Current release target

`v0.1-alpha` is reached when the deterministic validators and primary-research planner can:

1. read the canonical JSON artifacts;
2. emit blocking/non-blocking evidence gaps;
3. generate a research instrument specification for unresolved school-specific gaps;
4. validate imported response rows and deterministic aggregates;
5. validate Need -> Evidence -> Intervention -> Result -> Indicator traceability;
6. fail on the known 310224 defect fixtures.
