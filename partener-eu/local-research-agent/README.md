# PARTENER.EU Local Research Agent

Windows acquisition agent for official funding/programming sources that are dynamic, browser-dependent, or unreliable from GitHub-hosted runners.

## Canonical boundary

This component is **acquisition only**. It never authorizes or publishes call facts.

Hard false in every run manifest and every source receipt:

- `material_fact_use`
- `open_call_authorized`
- `closed_call_authorized`
- `deadline_authorized`
- `budget_authorized`
- `eligibility_authorized`
- `publish_authorized`
- `distribution_authorized`
- `call_alert_authorized`
- `canonical_corpus_mutation`

The output is immutable research/source evidence for later PARTENER Engine reconciliation and field-scoped admission.

## What it does

- runs daily on a Windows PC using Task Scheduler;
- self-updates its code and source registry with `git pull --ff-only` before each run;
- acquires official pages with normal verified HTTPS;
- for dynamic pages, uses headless Chromium through Playwright and captures the rendered DOM;
- never sets `ignore_https_errors`; TLS verification remains enabled;
- stores raw evidence, requested/final URL, HTTP status, content type, byte count, fetched time, SHA-256, semantic fingerprint, strategy used, source health and LKG requirement;
- compares the new semantic fingerprint with local previous state and emits only non-authorizing change classes;
- builds a ZIP evidence bundle per run;
- optionally publishes the ZIP to the dedicated GitHub branch `partener-local-research-evidence` using the GitHub Contents API;
- maintains a local LKG/state store under `%LOCALAPPDATA%\PARTENER.EU\research-agent`;
- accepts a GitHub request queue so ChatGPT can ask the local agent to prioritise specific source IDs on the next run.

## Initial coverage

The registry starts with 20+ official sources across:

- Romania: MySMIS2021 calls/home, AFIR funds counter;
- EEA/Norway: Civil Society Fund Romania;
- Interreg: Romania-Bulgaria, Romania-Hungary, Romania-Serbia, NEXT Romania-Ukraine, NEXT Romania-Republic of Moldova, Danube Region, Interreg Europe;
- EU Direct: Funding & Tenders topic search, LIFE, Innovation Fund, EUI/Portico, EIC, Horizon Europe, CERV, Digital Europe, CEF, Erasmus+.

The list is code-controlled in `sources.json`, so it updates with the agent without reinstalling it.

## Installation (one time)

Open **PowerShell** and run the installer from a checkout of this branch:

```powershell
powershell -ExecutionPolicy Bypass -File .\partener-eu\local-research-agent\install.ps1
```

Defaults:

- repository: `mihaicismaru-bit/civora`
- update channel: `partener/local-research-agent-v1-20260903`
- dedicated clone: `%LOCALAPPDATA%\PARTENER.EU\local-research-agent-repo`
- data/evidence: `%LOCALAPPDATA%\PARTENER.EU\research-agent`
- scheduled task: `PARTENER.EU Local Research Agent`
- daily run: **07:15 local time**

The installer creates a private venv, installs Playwright, installs Chromium, writes `agent.local.json` (gitignored), and registers the daily Task Scheduler task.

To use another time:

```powershell
.\partener-eu\local-research-agent\install.ps1 -DailyAt '06:30'
```

Microsoft documents daily scheduling through `schtasks /Create /SC DAILY /ST HH:mm`; the installer uses that mechanism.

## GitHub publishing token (one time, local machine only)

Publishing evidence back to GitHub is fail-closed until a token exists. Create a **fine-grained token** limited to `mihaicismaru-bit/civora` with repository `Contents: Read and write`, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\partener-eu\local-research-agent\configure-token.ps1
```

The token is stored in the current Windows user's environment as `PARTENER_RESEARCH_GITHUB_TOKEN`; it is never written to this repository or to evidence bundles.

Without a token the agent still runs and stores evidence locally, but `publish-result.json` records `PARTENER_RESEARCH_GITHUB_TOKEN_NOT_SET`.

## Manual use

Run all enabled sources and publish:

```powershell
.\partener-eu\local-research-agent\run.ps1
```

Run locally without publishing:

```powershell
.\partener-eu\local-research-agent\run.ps1 -NoPublish
```

Run one source only:

```powershell
.\partener-eu\local-research-agent\run.ps1 -SourceId INTERREG_RO_MD
```

Health check:

```powershell
.\.partener-research-venv\Scripts\python.exe .\partener-eu\local-research-agent\agent.py doctor
```

## How ChatGPT calls the agent

`control/requests.json` is the mailbox. A request has this shape:

```json
{
  "request_id": "REQ-20260903-001",
  "enabled": true,
  "source_ids": ["INTERREG_RO_MD", "RO_MYSMIS_CALLS"],
  "reason": "fresh transport/source readback"
}
```

ChatGPT can update this queue through the connected GitHub repository. At the next local run:

1. the agent self-updates the branch;
2. it reads the queue;
3. uncompleted request IDs restrict/prioritise acquisition to the requested sources;
4. the request IDs are written into the immutable run manifest;
5. successful local processing records those IDs in local state so they are not re-run indefinitely;
6. the evidence ZIP is published to `partener-local-research-evidence` when the token is configured.

The latest pointer is:

`partener-eu/local-research-evidence/latest.json`

The evidence bundle path is:

`partener-eu/local-research-evidence/YYYY-MM-DD/<run_id>.zip`

## Evidence model

Every run creates:

```text
%LOCALAPPDATA%\PARTENER.EU\research-agent\
  state.json
  runs\<run_id>\
    manifest.json
    publish-result.json
    raw\<source_id>.<ext>
  bundles\<run_id>.zip
```

Change classes are deliberately non-authorizing:

- `BASELINE_CAPTURED_NON_AUTHORIZING`
- `NO_CHANGE`
- `CONTENT_CHANGED_NON_AUTHORIZING`
- `SOURCE_HEALTH_RECOVERED_NON_AUTHORIZING`
- `SOURCE_DEGRADED_NON_AUTHORIZING`

A content change is only a research signal. PARTENER Engine must perform programme/call-specific semantic reconciliation before anything material can be admitted.

## Transport policy

`strategy: auto` first tries verified HTTPS with Python/OS trust. On failure it retries using a real headless Chromium browser through Playwright. Browser contexts are created with `ignore_https_errors=False`.

This is intentional: a local Windows trust store and a real browser often reach official dynamic sites that fail on GitHub Linux runners, while the agent still refuses certificate bypasses.

## Auto-update and rollback

Before each scheduled run, `run.ps1` does:

```text
git fetch origin <code_branch>
git checkout <code_branch>
git pull --ff-only origin <code_branch>
```

No force reset or rebase is used. If update fails, the installed LKG code runs and emits a warning.

Rollback is normal Git rollback: pin `code_branch` to a prior validated branch/commit or revert the bounded code changes. Historical evidence bundles are not deleted by code rollback.

## Uninstall

Remove only the scheduled task:

```powershell
.\partener-eu\local-research-agent\uninstall.ps1
```

Optionally remove local data and/or the dedicated clone:

```powershell
.\partener-eu\local-research-agent\uninstall.ps1 -RemoveData -RemoveRepositoryClone
```

## Security notes

- No passwords, MFA codes, cookies, MySMIS credentials or browser profiles are read.
- No authenticated MySMIS/private account scraping is implemented.
- Browser acquisition runs in a fresh isolated Playwright context.
- GitHub publishing needs only repository Contents access; no Actions, Administration, Issues or Secrets permission is required.
- The agent never writes to `main`; evidence uses a dedicated branch.
- Evidence cannot authorize status, deadlines, budgets, eligibility, publication, alerts or canonical corpus mutations.
