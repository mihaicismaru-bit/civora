from __future__ import annotations

from typing import Any


class EditorialRemediationPlanner:
    """Build deterministic, read-only remediation guidance from consistency results.

    The planner never mutates durable state. Automatic recovery is recommended
    only for mismatches already classified as recoverable by
    ``EditorialConsistencyInspector`` because an exact prepared transaction
    covers the approval/Review Queue divergence. All other inconsistencies are
    fail-closed and require operator inspection.
    """

    MANUAL_TYPES = {
        "missing_review_queue_item",
        "approval_queue_state_mismatch",
        "transaction_missing_approval_case",
        "transaction_story_mismatch",
        "committed_resolution_not_reflected",
    }

    @staticmethod
    def _inspect_commands(item: dict[str, Any]) -> list[list[str]]:
        commands: list[list[str]] = []
        story_id = item.get("story_id")
        case_id = item.get("case_id")
        transaction_id = item.get("transaction_id")
        if story_id:
            commands.append(["editorial-story", str(story_id)])
        if case_id:
            commands.append(["approval-case", str(case_id)])
        if transaction_id:
            commands.append(["transaction", str(transaction_id)])
        for tx_id in item.get("transaction_ids", []) or []:
            commands.append(["transaction", str(tx_id)])
        return commands

    def plan(self, report: dict[str, Any]) -> dict[str, Any]:
        status = report.get("status")
        if status == "healthy":
            return {
                "classification": "no_action",
                "safe_to_automate": True,
                "summary": "Editorial durable stores are consistent.",
                "actions": [],
            }

        actions: list[dict[str, Any]] = []
        for item in report.get("recoverable_mismatches", []) or []:
            actions.append(
                {
                    "severity": "recoverable",
                    "safe_to_automate": True,
                    "mismatch_type": item.get("type"),
                    "story_id": item.get("story_id"),
                    "case_id": item.get("case_id"),
                    "transaction_ids": list(item.get("transaction_ids", []) or []),
                    "operation": "startup_transaction_replay",
                    "instruction": (
                        "Run normal CIVORA startup recovery. The exact prepared editorial "
                        "resolution transaction may be replayed idempotently before work is accepted."
                    ),
                    "verification_command": ["editorial-consistency"],
                    "inspection_commands": self._inspect_commands(item),
                }
            )

        for item in report.get("mismatches", []) or []:
            mismatch_type = item.get("type")
            actions.append(
                {
                    "severity": "fail_closed",
                    "safe_to_automate": False,
                    "mismatch_type": mismatch_type,
                    "story_id": item.get("story_id"),
                    "case_id": item.get("case_id"),
                    "transaction_id": item.get("transaction_id"),
                    "operation": "operator_investigation",
                    "instruction": (
                        "Do not synthesize or overwrite durable state. Inspect the authoritative "
                        "approval case, Review Queue state and transaction history, then restore or "
                        "repair only from verified evidence."
                    ),
                    "inspection_commands": self._inspect_commands(item),
                }
            )

        degraded = any(not action["safe_to_automate"] for action in actions)
        classification = "manual_investigation_required" if degraded else "automatic_recovery_available"
        return {
            "classification": classification,
            "safe_to_automate": not degraded,
            "summary": (
                "At least one inconsistency requires operator investigation; startup must remain fail-closed."
                if degraded
                else "All detected inconsistencies are covered by exact prepared transactions and are recoverable."
            ),
            "actions": actions,
        }
