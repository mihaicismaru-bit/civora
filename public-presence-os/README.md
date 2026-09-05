# PUBLIC PRESENCE OS — TEXT/PHOTO

Canonical executable-source layout introduced by CP30.

## Authority split
- **GitHub**: executable source, schemas/config, tests and CI.
- **Google Drive**: checkpoints, evidence, decisions, changelog and rollback evidence.

## Safety posture
Pre-pilot only. Active lanes are Facebook Page, Instagram Professional and Threads. LinkedIn remains API-gated, X excluded while paid, Bluesky HOLD_ROI. No network publishing, real-account connection, scheduler writes, queue mutation, deploy or paid-service dependency is enabled.

## Validate
`PYTHONPATH=src python -m public_presence_os.cli validate --root .`

## Reproducible package
`PYTHONPATH=src python scripts/build_release.py`

The build creates a deterministic ZIP from source/config/tests/docs/CI inputs. It is not a deploy artifact and contains no secrets or account credentials.
