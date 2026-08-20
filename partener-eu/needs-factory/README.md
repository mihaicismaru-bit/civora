# Needs Factory

Needs Factory is the first isolated production vertical of the EU Project Intelligence stack. Its job is to transform a minimal project/call input into an auditable, evidence-backed needs model before any narrative is generated.

## Product boundary

Needs Factory owns only domain logic specific to needs analysis:

`project intake -> call requirements -> research plan -> evidence -> evidence gaps -> primary research -> needs -> ranking -> causal model -> intervention traceability -> QA -> narrative-ready package`

It does **not** duplicate source crawling, generic source health, persistence, checkpoint orchestration or artifact registry capabilities already available in CIVORA / PARTENER.EU / DAPE.

## Reuse contract

- **PARTENER.EU** supplies call/domain intelligence and source-state/health. Material facts consume only current, non-quarantined, quality-approved source state and preserve provider document provenance.
- **CIVORA** supplies discovery/provenance patterns and external-source retrieval capability.
- **DAPE** supplies the production semantics: deterministic resume, checkpoints, artifact registry, QA gates, versioning and rollback. Needs Factory emits deterministic artifacts that can be registered by DAPE instead of maintaining a second registry.

See `contracts/ENGINE_REUSE_CONTRACT.json`.

## Live discovery binding

`tools/run_research_cycle.py` is the live research boundary. It sends canonical research tasks to an existing CIVORA discovery command and, by default, decorates the provider with `PartenerSourceGateProvider`.

The source gate reads the canonical PARTENER.EU `ingest/state/source_registry_health.json` snapshot. It does not crawl. A discovery receipt is blocked before evidence promotion when the registry snapshot is stale, the source is unregistered, unhealthy, quarantined, low-quality, awaiting resolution, or has a material semantic change that still requires reconciliation. Provider-reported document URL and raw/semantic hashes remain intact; registry hashes are attached separately as source-health provenance.

The `--fixture-provider-no-source-gate` switch exists only for deterministic synthetic CI fixtures. Production invocations are fail-closed through the PARTENER source registry.

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
- historical reconstruction is cutoff-locked;
- source-provider PASS claims cannot override PARTENER source-health state.

## Benchmark

`benchmarks/310224` is `NF-BENCH-001`. The blind historical run recovered the defensible core of the evaluator-accepted analysis while rejecting an unsupported discrimination need and exposing the missing primary-research layer. The benchmark therefore defines the initial production acceptance suite. It remains intentionally `BLOCKED_RESEARCH` where authoritative historical/local evidence is missing; no fixture may be promoted as real 310224 evidence.

## v1 release boundary

The unified lifecycle covers plan -> discovery -> blocked/research pack -> resume -> need synthesis -> standalone needs analysis -> QA -> DOCX -> DAPE handoff. DAPE handoff remains non-canonical until explicit owner approval.

The remaining v1 production gate is live socioeconomic source coverage: the PARTENER registry must expose the authoritative source families required by the selected research profile (for example INS/TEMPO, AJOFM/ANOFM, ISJ and beneficiary/school official evidence where applicable). Until those sources are registered and healthy, discovery for those requirements fails closed rather than fabricating evidence.
