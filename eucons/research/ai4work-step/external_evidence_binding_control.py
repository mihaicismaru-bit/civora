from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from prod_activation_gate import REQUIRED_EXTERNAL_KEYS

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_STATUSES = {"OPEN", "FROZEN", "PASS", "APPROVED"}
PROMOTED_STATUSES = {"FROZEN", "PASS", "APPROVED"}
SEMANTIC_ATTESTATION_STATUSES = {"PASS", "APPROVED"}
NON_EVIDENCE_MARKERS = ("TEST_TWIN", "NON_EVIDENCE", "SYNTHETIC")


class ExternalEvidenceBindingError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_local_reference(reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference.strip():
        return None
    reference = reference.strip()
    if "://" in reference or reference.startswith(("gdrive:", "gmail:", "http:", "https:")):
        return None
    raw = Path(reference)
    if raw.is_absolute():
        return None
    candidate = (HERE / raw).resolve()
    try:
        candidate.relative_to(HERE.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _semantic_attestation_errors(
    *, key: str, artifact: Any, research_id: str
) -> list[str]:
    """Require PASS/APPROVED evidence to attest what it actually proves.

    A matching path and digest establish immutability, but not semantic relevance.
    Production-grade external/operational evidence must therefore identify both the
    research run and the exact manifest evidence key it is intended to satisfy.
    TEST TWIN or other explicitly non-evidence artifacts can never satisfy a
    promoted gate even when their bytes are immutable.
    """
    if not isinstance(artifact, dict):
        return [f"promoted_evidence_attestation_not_object:{key}"]

    errors: list[str] = []
    if artifact.get("research_id") != research_id:
        errors.append(f"promoted_evidence_research_id_missing_or_mismatch:{key}")
    if artifact.get("evidence_binding_key") != key:
        errors.append(f"promoted_evidence_key_missing_or_mismatch:{key}")

    if artifact.get("synthetic") is True:
        errors.append(f"promoted_evidence_is_synthetic:{key}")

    for field in ("evidence_class", "mode", "artifact_class"):
        value = artifact.get(field)
        if isinstance(value, str):
            normalized = value.upper()
            if any(marker in normalized for marker in NON_EVIDENCE_MARKERS):
                errors.append(f"promoted_evidence_non_evidence_marker:{key}:{field}")

    return errors


def _binding_errors_for_item(*, key: str, item: Any, research_id: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(item, dict):
        return [f"evidence_item_not_object:{key}"]

    status = item.get("status")
    reference = item.get("reference")
    digest = item.get("sha256")

    if status not in ALLOWED_STATUSES:
        errors.append(f"evidence_status_invalid:{key}")
        return errors

    has_reference = isinstance(reference, str) and bool(reference.strip())
    has_digest = isinstance(digest, str) and bool(SHA256_RE.fullmatch(digest))

    if status in PROMOTED_STATUSES and not (has_reference and has_digest):
        errors.append(f"promoted_evidence_not_immutable:{key}")
        return errors

    # OPEN gates may be empty, but if a draft/control artifact is cited, the citation
    # must still be a truthful immutable local binding rather than an unverifiable label.
    if status == "OPEN" and reference is None and digest is None:
        return errors
    if status == "OPEN" and not (has_reference and has_digest):
        errors.append(f"open_evidence_partial_binding:{key}")
        return errors

    candidate = _resolve_local_reference(reference)
    if candidate is None:
        errors.append(f"evidence_reference_not_local_immutable:{key}")
        return errors

    actual_digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if actual_digest != digest:
        errors.append(f"evidence_sha256_mismatch:{key}")
        return errors

    artifact: Any | None = None
    if candidate.suffix.lower() == ".json":
        try:
            artifact = _load(candidate)
        except (OSError, json.JSONDecodeError):
            errors.append(f"evidence_json_invalid:{key}")
            return errors
        if not isinstance(artifact, dict):
            errors.append(f"evidence_json_not_object:{key}")
            return errors
        artifact_research_id = artifact.get("research_id")
        if artifact_research_id is not None and artifact_research_id != research_id:
            errors.append(f"evidence_research_id_mismatch:{key}")

    # FROZEN may bind documentary/provider context. PASS/APPROVED is stronger: it
    # must point to a machine-verifiable attestation for this exact gate, not merely
    # to any immutable repository file that happens to have a correct digest.
    if status in SEMANTIC_ATTESTATION_STATUSES:
        if artifact is None:
            errors.append(f"promoted_evidence_attestation_not_json:{key}")
        else:
            errors.extend(
                _semantic_attestation_errors(
                    key=key,
                    artifact=artifact,
                    research_id=research_id,
                )
            )

    return errors


def evidence_binding_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    research_id = manifest.get("research_id")
    if not isinstance(research_id, str) or not research_id.strip():
        errors.append("manifest_research_id_missing")
        research_id = ""

    evidence = manifest.get("required_external_or_operational_evidence")
    if not isinstance(evidence, dict):
        return errors + ["external_evidence_map_missing"]

    missing = REQUIRED_EXTERNAL_KEYS - set(evidence)
    unexpected = set(evidence) - REQUIRED_EXTERNAL_KEYS
    if missing:
        errors.append("external_evidence_keys_missing:" + ",".join(sorted(missing)))
    if unexpected:
        errors.append("external_evidence_keys_unexpected:" + ",".join(sorted(unexpected)))

    for key in sorted(REQUIRED_EXTERNAL_KEYS & set(evidence)):
        errors.extend(_binding_errors_for_item(key=key, item=evidence[key], research_id=research_id))
    return errors


def evaluate_repository_binding(manifest_path: Path = MANIFEST_PATH) -> tuple[bool, list[str]]:
    manifest = _load(manifest_path)
    errors = evidence_binding_errors(manifest)
    return not errors, errors


def assert_repository_external_evidence_bindings() -> None:
    ready, errors = evaluate_repository_binding()
    if not ready:
        raise ExternalEvidenceBindingError("; ".join(errors))


def main() -> int:
    try:
        assert_repository_external_evidence_bindings()
    except (OSError, json.JSONDecodeError, ExternalEvidenceBindingError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print("PASS: activation evidence references are immutable repo-local bindings; PASS/APPROVED gates are semantically attested; OPEN gates remain non-promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())