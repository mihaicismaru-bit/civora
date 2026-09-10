from __future__ import annotations

from copy import deepcopy
from typing import Any

from research_storage import ResearchStorage


ACCESS_COPY_VERSION = "eucons.ai4work_rights_access_copy.v0.1"
ACCESS_COPY_SCOPE = "RESPONDENT_RECORD_COPY_ONLY"

# Keep the reference access path deliberately narrower than the storage schema.
# Any newly introduced stored field must be reviewed before it can be disclosed.
ALLOWED_RECORD_FIELDS = {
    "schema_version",
    "research_id",
    "form_id",
    "form_version",
    "response_id",
    "received_at",
    "recruitment_channel_id",
    "profile",
    "answers",
    "synthetic",
}
REQUIRED_RECORD_FIELDS = ALLOWED_RECORD_FIELDS


class RightsAccessError(ValueError):
    pass


def build_receipt_keyed_access_copy(
    storage: ResearchStorage,
    response_id: str,
) -> dict[str, Any] | None:
    """Build the respondent-record copy component of an Article 15 response.

    This reference operation is intentionally limited to the analytical record
    located by the opaque response receipt. It does not authenticate the
    requester and does not replace the controller's obligation to supply the
    contextual information required by Article 15. Internal storage metadata,
    idempotency digests, rights-hold state and erasure-replay controls are not
    exposed through this interface.
    """

    record = storage.get_by_response_id(response_id)
    if record is None:
        return None

    fields = set(record)
    unexpected = fields - ALLOWED_RECORD_FIELDS
    missing = REQUIRED_RECORD_FIELDS - fields
    if unexpected:
        raise RightsAccessError(
            "stored record contains fields not approved for rights access copy: "
            + ", ".join(sorted(unexpected))
        )
    if missing:
        raise RightsAccessError(
            "stored record is missing fields required for rights access copy: "
            + ", ".join(sorted(missing))
        )

    safe_record = {field: deepcopy(record[field]) for field in sorted(ALLOWED_RECORD_FIELDS)}
    return {
        "access_copy_version": ACCESS_COPY_VERSION,
        "scope": ACCESS_COPY_SCOPE,
        "controller_article15_context_required": True,
        "requester_authentication_not_implemented_here": True,
        "record": safe_record,
    }
