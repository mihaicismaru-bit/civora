#!/usr/bin/env python3
"""Fail-closed guard that prevents credential values entering persistence.

PRS-039 permits persistence of credential reference *names* and verification
state only. Runtime credential values remain outside durable project state.
The guard is provider- and instance-neutral and never returns a detected value
in diagnostics.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Any

CONTRACT = "CIVORA_PERSISTENCE_CREDENTIAL_SAFETY_V1"

_FORBIDDEN_KEY_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"(?:^|_)(?:password|passwd|pwd)$",
        r"(?:^|_)(?:api_?key)$",
        r"(?:^|_)(?:access_token|refresh_token|auth_token|bearer_token|oauth_token)$",
        r"(?:^|_)(?:client_secret|app_secret|webhook_secret|private_key)$",
        r"(?:^|_)(?:credential_value|credentials_value|secret_value)$",
    )
)

_REFERENCE_KEY_HINTS = (
    "credential_reference",
    "credential_ref",
    "secret_reference",
    "secret_ref",
    "reference_name",
    "reference_names",
)

_VERIFICATION_CONTAINER_HINTS = (
    "credential_verification",
    "credential_verifications",
    "credential_state",
    "credential_states",
    "credential_status",
    "credential_statuses",
    "verification_state",
    "verification_states",
    "verification_status",
    "verification_statuses",
)

_SAFE_EMPTY_MARKERS = {
    "",
    "null",
    "none",
    "redacted",
    "<redacted>",
    "[redacted]",
    "not_persisted",
    "not-persisted",
    "unavailable",
}

_ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*[\"']?([A-Za-z0-9_.-]+)[\"']?\s*[:=]\s*[\"']?([^\r\n\"']*)"
)
_BEARER_RE = re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+\S+")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


@dataclass(frozen=True)
class CredentialViolation:
    path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "reason": self.reason}


def _normalize_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def _is_reference_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(hint in normalized for hint in _REFERENCE_KEY_HINTS) or normalized.endswith("_ref")


def _is_verification_container_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(hint in normalized for hint in _VERIFICATION_CONTAINER_HINTS)


def _is_forbidden_value_key(key: str) -> bool:
    normalized = _normalize_key(key)
    if _is_reference_key(normalized):
        return False
    return any(pattern.search(normalized) for pattern in _FORBIDDEN_KEY_PATTERNS)


def _value_is_effectively_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _SAFE_EMPTY_MARKERS
    return False


def _walk_json(
    value: Any,
    path: str,
    out: list[CredentialViolation],
    *,
    credential_name_context: bool = False,
) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            if (
                not credential_name_context
                and _is_forbidden_value_key(key)
                and not _value_is_effectively_empty(child)
            ):
                out.append(CredentialViolation(child_path, "FORBIDDEN_CREDENTIAL_VALUE_FIELD"))
            _walk_json(
                child,
                child_path,
                out,
                credential_name_context=(
                    _is_reference_key(key) or _is_verification_container_key(key)
                ),
            )
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _walk_json(
                child,
                f"{path}[{index}]",
                out,
                credential_name_context=credential_name_context,
            )
        return
    if isinstance(value, str) and _PRIVATE_KEY_RE.search(value):
        out.append(CredentialViolation(path or "$", "PRIVATE_KEY_MATERIAL"))


def find_credential_value_violations(content: str) -> list[CredentialViolation]:
    """Return credential-value violations without ever echoing credential data."""
    violations: list[CredentialViolation] = []
    text = str(content)

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if parsed is not None:
        _walk_json(parsed, "$", violations)

    for match in _ASSIGNMENT_RE.finditer(text):
        key, raw_value = match.group(1), match.group(2).strip()
        if _is_forbidden_value_key(key) and raw_value.lower() not in _SAFE_EMPTY_MARKERS:
            violations.append(CredentialViolation(_normalize_key(key), "FORBIDDEN_CREDENTIAL_VALUE_ASSIGNMENT"))

    if _BEARER_RE.search(text):
        violations.append(CredentialViolation("authorization", "BEARER_CREDENTIAL_MATERIAL"))
    if _PRIVATE_KEY_RE.search(text):
        violations.append(CredentialViolation("private_key", "PRIVATE_KEY_MATERIAL"))

    deduped: list[CredentialViolation] = []
    seen: set[tuple[str, str]] = set()
    for row in violations:
        marker = (row.path, row.reason)
        if marker not in seen:
            seen.add(marker)
            deduped.append(row)
    return deduped


def persistence_content_is_credential_safe(content: str) -> bool:
    return not find_credential_value_violations(content)


def self_test() -> int:
    safe_json = json.dumps(
        {
            "credential_reference_names": [
                "FACEBOOK_PAGE_ACCESS_TOKEN",
                "INSTAGRAM_ACCESS_TOKEN",
            ],
            "credential_verification": {
                "FACEBOOK_PAGE_ACCESS_TOKEN": "VERIFIED_PRESENT",
                "INSTAGRAM_ACCESS_TOKEN": "UNCONFIRMED",
            },
            "lease_token": "coordination-nonce-is-not-an-external-credential",
        }
    )
    assert find_credential_value_violations(safe_json) == []

    unsafe_json = json.dumps(
        {
            "credential_reference_names": ["SOCIAL_ACCESS_TOKEN"],
            "access_token": "runtime-value-must-never-persist",
        }
    )
    hits = find_credential_value_violations(unsafe_json)
    assert hits and all("runtime-value" not in str(hit.to_dict()) for hit in hits)

    unsafe_nested = json.dumps(
        {
            "credentials": {
                "SOCIAL_ACCESS_TOKEN": "runtime-value-must-never-persist",
            }
        }
    )
    assert find_credential_value_violations(unsafe_nested)

    assert find_credential_value_violations("API_KEY=actual-value\n")
    assert find_credential_value_violations("Authorization: Bearer actual-value\n")
    assert find_credential_value_violations("client_secret: actual-value\n")
    assert find_credential_value_violations(
        "private_key: -----BEGIN PRIVATE KEY-----\nmaterial\n-----END PRIVATE KEY-----\n"
    )
    assert find_credential_value_violations("access_token: <redacted>\n") == []
    assert find_credential_value_violations("secret_ref: SOCIAL_SECRET_NAME\n") == []

    print(f"{CONTRACT} self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    parser.error("This module is a library guard. Use --self-test or import it.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
