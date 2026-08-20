from __future__ import annotations

from typing import Any, Dict, Mapping


class PartenerSourceError(ValueError):
    """Raised when PARTENER source state cannot safely support a material fact."""


def get_source_state(checkpoint: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    sources = checkpoint.get("sources")
    if not isinstance(sources, Mapping):
        raise PartenerSourceError("PARTENER source-state checkpoint has no sources mapping")
    state = sources.get(source_id)
    if not isinstance(state, Mapping):
        raise PartenerSourceError(f"unknown PARTENER source: {source_id}")
    return state


def material_fact_receipt(checkpoint: Mapping[str, Any], source_id: str) -> Dict[str, Any]:
    """Return the stable last-known-good source receipt or fail closed.

    A pending semantic hash is intentionally not promoted. The adapter exposes it as
    a reconciliation signal while continuing to reference the stable semantic hash.
    """
    state = get_source_state(checkpoint, source_id)
    failures = []
    if state.get("health") != "PASS":
        failures.append("health_not_pass")
    if state.get("quarantined") is True:
        failures.append("source_quarantined")
    if not state.get("last_success"):
        failures.append("missing_last_success")
    if not state.get("semantic_sha256"):
        failures.append("missing_semantic_sha256")
    if not state.get("final_url"):
        failures.append("missing_final_url")
    if failures:
        raise PartenerSourceError(f"source {source_id} is not material-fact ready: {','.join(failures)}")

    semantic = str(state["semantic_sha256"])
    pending = state.get("pending_semantic_sha256")
    return {
        "source_id": source_id,
        "source_snapshot_id": f"{source_id}@{semantic[:16]}",
        "health": state.get("health"),
        "quarantined": bool(state.get("quarantined")),
        "raw_sha256": state.get("raw_sha256"),
        "semantic_sha256": semantic,
        "final_url": state.get("final_url"),
        "last_success": state.get("last_success"),
        "last_observed": state.get("last_observed"),
        "pending_change": bool(pending),
        "pending_semantic_sha256": pending,
        "material_fact_state": "LAST_KNOWN_GOOD_PENDING_RECONCILIATION" if pending else "STABLE_LAST_KNOWN_GOOD",
    }


def attach_partener_provenance(
    evidence: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    source_id: str,
) -> Dict[str, Any]:
    receipt = material_fact_receipt(checkpoint, source_id)
    result = dict(evidence)
    result["partener_source"] = receipt
    result.setdefault("source_url", receipt["final_url"])
    result.setdefault("health", receipt["health"])
    result.setdefault("quarantined", receipt["quarantined"])
    result.setdefault("raw_sha256", receipt["raw_sha256"])
    result.setdefault("semantic_sha256", receipt["semantic_sha256"])
    return result
