from pathlib import Path

from public_presence_os.import_registry import (
    EXPECTED_CHECKPOINTS,
    import_candidates,
    load_registry,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "config" / "checkpoint_source_registry.json"


def registry():
    return load_registry(REG)


def test_registry_passes():
    result = validate_registry(registry())
    assert result.ok, result.errors


def test_exact_checkpoint_range():
    assert tuple(package["checkpoint"] for package in registry()["packages"]) == EXPECTED_CHECKPOINTS


def test_exact_drive_revision_binding():
    data = registry()
    assert all(package["drive_document_id"] and package["drive_revision_id"] for package in data["packages"])
    assert all(package["checkpoint_evidence_state"] == "BOUND_TO_EXACT_DRIVE_REVISION" for package in data["packages"])


def test_no_fake_source_imports():
    data = registry()
    assert import_candidates(data) == ()
    assert all(package["source_bytes_available"] is False for package in data["packages"])
    assert all(package["import_eligible"] is False for package in data["packages"])


def test_archive_discovery_fail_closed():
    data = registry()
    assert data["source_archive_discovery"]["result"] == "NO_RESULTS"
    assert all(package["reference_package_discovery"] == "NOT_FOUND_IN_GOOGLE_DRIVE" for package in data["packages"])


def test_unavailable_source_with_hash_rejected():
    data = registry()
    data["packages"][0]["source_archive_sha256"] = "0" * 64
    result = validate_registry(data)
    assert not result.ok
    assert any("unavailable_source_cannot_have_hash" in error for error in result.errors)


def test_unavailable_source_cannot_be_eligible():
    data = registry()
    data["packages"][0]["import_eligible"] = True
    result = validate_registry(data)
    assert not result.ok
    assert any("unavailable_source_cannot_be_eligible" in error for error in result.errors)


def test_available_source_requires_hash():
    data = registry()
    package = data["packages"][0]
    package["source_bytes_available"] = True
    package["import_eligible"] = True
    package["import_state"] = "READY"
    result = validate_registry(data)
    assert not result.ok
    assert any("source_hash_required" in error for error in result.errors)


def test_available_source_requires_paths():
    data = registry()
    package = data["packages"][0]
    package["source_bytes_available"] = True
    package["import_eligible"] = True
    package["source_archive_sha256"] = "a" * 64
    package["expected_source_paths"] = []
    result = validate_registry(data)
    assert not result.ok
    assert any("source_paths_required" in error for error in result.errors)


def test_checkpoint_reorder_rejected():
    data = registry()
    data["packages"][0], data["packages"][1] = data["packages"][1], data["packages"][0]
    assert not validate_registry(data).ok


def test_authority_split_rejected_if_changed():
    data = registry()
    data["authority"]["executable_source"] = "GOOGLE_DRIVE"
    assert not validate_registry(data).ok


def test_import_candidates_only_eligible_after_exact_source_binding():
    data = registry()
    package = data["packages"][0]
    package["source_bytes_available"] = True
    package["source_archive_sha256"] = "a" * 64
    package["import_eligible"] = True
    package["import_state"] = "READY_EXACT_SOURCE"
    assert import_candidates(data) == ("CP23",)
