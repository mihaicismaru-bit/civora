from __future__ import annotations

import json
from pathlib import Path

from collection_channel_register_control import validate_prod_binding, validate_register

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
FRAME_PATH = HERE / "COLLECTION_FRAME_DRAFT.json"
REGISTER_PATH = HERE / "COLLECTION_CHANNEL_REGISTER_DRAFT.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate() -> tuple[bool, list[str]]:
    contract = _load(CONTRACT_PATH)
    frame = _load(FRAME_PATH)
    register = _load(REGISTER_PATH)
    errors: list[str] = []

    try:
        validate_register(register, require_nonempty=False)
    except ValueError as exc:
        errors.append(f"collection_channel_register_structure_invalid:{exc}")
        return False, errors

    prod_requested = (
        contract.get("production_enabled") is True
        or frame.get("collection_enabled") is True
        or frame.get("frame_status") == "APPROVED_FOR_PROD"
        or (frame.get("approval") or {}).get("approved_for_prod") is True
        or (frame.get("nf06_handoff") or {}).get("eligible_now") is True
    )
    if prod_requested:
        errors.extend(validate_prod_binding(register_path=REGISTER_PATH, collection_frame=frame))
    return not errors, errors


def main() -> int:
    ready, errors = evaluate()
    if errors:
        raise SystemExit("REJECTED: " + "; ".join(errors))
    contract = _load(CONTRACT_PATH)
    if contract.get("production_enabled") is True:
        print("PASS: approved PROD state is bound to a non-empty frozen collection-channel register")
    else:
        print("PASS: collection-channel register is structurally valid and PROD remains fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
