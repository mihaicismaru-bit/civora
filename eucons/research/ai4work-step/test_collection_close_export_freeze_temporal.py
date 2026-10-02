from __future__ import annotations

# TEST TWIN ONLY — NON-EVIDENCE. Synthetic engineering fixtures only.

import unittest
from datetime import datetime, timedelta, timezone

import collection_close_export_freeze as FREEZE
import nf06_persisted_handoff as HANDOFF
from test_nf06_persisted_handoff import (
    freeze_receipt,
    handoff,
    persisted_bundle,
    rights_snapshot,
)
from test_nf06_preingest import collection_frame, normalized_records


class CollectionCloseExportFreezeTemporalTests(unittest.TestCase):
    def setUp(self):
        self.records = normalized_records()
        self.bundles = [persisted_bundle(record) for record in self.records]
        self.frame, _ = collection_frame(self.records, prod=True)
        self.snapshot = rights_snapshot()

    def _future_control_time(self) -> str:
        return (
            datetime.now(timezone.utc)
            + FREEZE.MAX_CONTROL_CLOCK_SKEW
            + timedelta(seconds=5)
        ).isoformat().replace("+00:00", "Z")

    def test_future_runtime_disable_claim_fails_closed(self):
        future = self._future_control_time()
        receipt = freeze_receipt(
            self.bundles,
            self.frame,
            self.snapshot,
            runtime_acceptance_disabled_at=future,
            export_frozen_at=future,
        )
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "runtime_acceptance_disabled_at is future-dated beyond allowed clock skew",
        ):
            handoff(self.bundles, self.frame, self.snapshot, receipt)

    def test_future_export_freeze_claim_fails_closed(self):
        future = self._future_control_time()
        receipt = freeze_receipt(
            self.bundles,
            self.frame,
            self.snapshot,
            export_frozen_at=future,
        )
        with self.assertRaisesRegex(
            HANDOFF.NF06PersistedHandoffError,
            "export_frozen_at is future-dated beyond allowed clock skew",
        ):
            handoff(self.bundles, self.frame, self.snapshot, receipt)


if __name__ == "__main__":
    unittest.main()
