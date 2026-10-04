# PUBLIC PRESENCE OS — TEXT/PHOTO

Canonical executable-source layout introduced by CP30.

## Authority split
- **GitHub**: executable source, schemas/config, tests and CI.
- **Google Drive**: checkpoints, evidence, decisions, changelog and rollback evidence.

## Safety posture
Ready for credential-gated `READ_ONLY_REAL`. The current pilot activates Facebook Page and Instagram Professional. Threads is temporarily `HOLD_EXTERNAL` and can be re-enabled with `META_THREADS_ENABLED=true` once its tester authorization/token is available. LinkedIn remains API-gated, X excluded while paid, Bluesky HOLD_ROI. The live read runtime is GET-only and requires the global kill switch to remain engaged with `LIVE_WRITE=OFF`. No network publishing, scheduler write, queue mutation, deploy, paid-service dependency, external GREEN action, or owner write authority is enabled.

## Validate
`PYTHONPATH=src python -m public_presence_os.cli validate --root .`

Secret-safe Meta preflight (prints presence/status only):

`PYTHONPATH=src python -m public_presence_os.cli meta-preflight --db var/meta-events.sqlite3`

After credentials are locally provisioned, explicitly add `--live` to perform the bounded read-only identity/content probe. Real tokens must never be passed on the command line or committed.

Read-only sync and shadow decision materialization:

`PYTHONPATH=src python -m public_presence_os.cli meta-sync --db var/meta-events.sqlite3`

`PYTHONPATH=src python -m public_presence_os.cli meta-shadow --events-db var/meta-events.sqlite3 --shadow-db var/meta-shadow.sqlite3`

## Reproducible package
`PYTHONPATH=src python scripts/build_release.py`

The build creates a deterministic ZIP from source/config/tests/docs/CI inputs. It is not a deploy artifact and contains no secrets or account credentials.
