from __future__ import annotations

import orchestrator_run100 as _impl

# Canonical Core v2 orchestrator surface. Export private migration seams too,
# because CI regressions intentionally introspect them while the controlled
# rebuild is in progress.
globals().update({name: value for name, value in vars(_impl).items() if not name.startswith("__")})


if __name__ == "__main__":
    raise SystemExit(main())
