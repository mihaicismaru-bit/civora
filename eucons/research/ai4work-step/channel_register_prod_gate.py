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

    # An approved frozen method/frame is not itself dissemination or collection activation.
    # Real channel rows may only be created from actual authorised dissemination batches, so
    # require the non-empty immutable register only when collection/NF06 is actually enabled.
    prod_requested = (
        contract.get("production_enabled") is True
        or frame.get("collection_enabled") is True
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
    frame = _load(FRAME_PATH)
    if contract.get("production_enabled") is True or frame.get("collection_enabled") is True:
        print("PASS: active collection/PROD state is bound to a non-empty frozen collection-channel register")
    else:
        print("PASS: collection-channel register is structurally valid; approved method exists but real dissemination/collection remains fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
