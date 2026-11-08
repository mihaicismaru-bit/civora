#!/usr/bin/env python3
"""Hermetic October MFF evidence and non-authorizing stage regression."""
import hashlib
import importlib.util
import json
import tempfile
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("mff_2028_probe", ROOT / "partener-eu/ingest/mff_2028_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

SOURCE = {
    "id": "SRC-EU-MFF-CAP-PARTIAL-20261026",
    "tier": "T1",
    "class": "official_council_partial_negotiating_position",
    "stage": "COUNCIL_PARTIAL_CAP_POSITION",
    "url": "https://www.consilium.europa.eu/en/press/press-releases/2026/10/26/test/",
    "event_date": "2026-10-26",
    "updated_date": "2026-10-28",
    "source_family": "PROGRAMMING_PIPELINE_MFF_2028_2034",
    "programme": "MFF_2028_2034/CAP",
    "authority_class": "T1_COUNCIL_OFFICIAL",
    "open_call_authorized": False,
    "material_fact_publication_authorized": False,
}
REGISTRY = {
    "stage_policy": ["COMMISSION_PROPOSAL", "COUNCIL_PARTIAL_CAP_POSITION"],
    "sources": [SOURCE],
}
BODY = ("<html><body><h1>Council partial negotiating position</h1><p>" +
        ("This is a proposed partial negotiating stage, not an adopted budget or an open funding call. " * 10) +
        "</p></body></html>").encode("utf-8")


class Response:
    def __init__(self, body=BODY, final_url=SOURCE["url"], declared_length=None, content_encoding=None, content_type="text/html; charset=utf-8"):
        self.body = body
        self.final_url = final_url
        self.headers = {"content-type": content_type}
        if declared_length is not None:
            self.headers["Content-Length"] = str(declared_length)
        if content_encoding is not None:
            self.headers["Content-Encoding"] = content_encoding
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.final_url

    def read(self, limit):
        return self.body[:limit]


original_urlopen = probe._open_official


def expect_bad_registry(payload, label):
    try:
        probe.validate_registry(payload)
    except ValueError:
        return
    raise AssertionError(label)


def run_tests():
    assert probe.official_https(SOURCE["url"])
    assert probe.official_https("https://eprs.europarl.europa.eu/home/topics/budgetary-affairs/BUDGET/mff-2028-2034.html")
    assert not probe.official_https("https://eprs.europarl.europa.eu.attacker.example/fake")
    assert not probe.official_https("http://www.consilium.europa.eu/insecure")
    assert not probe.official_https("https://www.consilium.europa.eu.evil.example/test")
    assert not probe.official_https("https://evil.example/test")
    assert not probe.official_https("https://www.consilium.europa.eu:444/test")
    assert not probe.official_https("https://user:pass@www.consilium.europa.eu/test")
    assert probe.same_source_authority(SOURCE["url"], "https://www.consilium.europa.eu/en/policies/")
    assert not probe.same_source_authority(SOURCE["url"], "https://fed.mai.gov.ro/in/eu-2028-2034/")
    assert not probe.same_source_authority(SOURCE["url"], "https://irish-presidency.consilium.europa.eu/en/news/")
    # urllib's default redirects may silently traverse an insecure/off-authority
    # intermediate before returning an apparently official final 200 response.
    handler = probe._StrictOfficialRedirectHandler()
    origin = probe.urllib.request.Request(SOURCE["url"])
    valid = handler.redirect_request(
        origin, None, 302, "Found", {}, "https://www.consilium.europa.eu/en/policies/"
    )
    assert probe.official_https(valid.full_url)
    for intermediate in (
        "http://www.consilium.europa.eu/unsafe-hop",
        "https://untrusted.example/unsafe-hop",
        "https://www.consilium.europa.eu:444/unsafe-hop",
        "https://user:pass@www.consilium.europa.eu/unsafe-hop",
        # Both are registered official sources, but *not* this source host.
        "https://fed.mai.gov.ro/in/eu-2028-2034/",
        "https://irish-presidency.consilium.europa.eu/en/news/",
    ):
        try:
            handler.redirect_request(origin, None, 302, "Found", {}, intermediate)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe MFF redirect accepted: {intermediate}")
    expect_bad_registry({**REGISTRY, "sources": [SOURCE, SOURCE]}, "duplicate ID accepted")
    expect_bad_registry({**REGISTRY, "stage_policy": ["OPEN_CALL"]}, "OPEN_CALL stage accepted")
    expect_bad_registry({**REGISTRY, "sources": [{**SOURCE, "open_call_authorized": True}]}, "call authority accepted")
    expect_bad_registry({**REGISTRY, "sources": [{**SOURCE, "stage": "ADOPTED_MFF"}]}, "adoption stage accepted")

    # The committed official-source registry, not just the synthetic fixture,
    # must preserve distinct October events and original update dates.
    actual = json.loads((ROOT / "partener-eu/ingest/mff_2028_source_registry.json").read_text(encoding="utf-8"))
    probe.validate_registry(actual)
    expected = {
        "SRC-EU-MFF-IRISH-NEGOTIATING-BOX-20261010": ("PRESIDENCY_NEGOTIATING_PROPOSAL", "2026-10-10", None),
        "SRC-EU-MFF-EP-CORAPPORTEURS-20261016": ("PARLIAMENTARY_POSITION_COMMENTARY", "2026-10-16", None),
        "SRC-EU-MFF-CMO-PARTIAL-20261019": ("COUNCIL_PARTIAL_CMO_POSITION", "2026-10-19", "2026-10-20"),
        "SRC-EU-MFF-CAP-PARTIAL-20261026": ("COUNCIL_PARTIAL_CAP_POSITION", "2026-10-26", "2026-10-28"),
    }
    entries = {s["id"]: s for s in actual["sources"]}
    assert len(entries) == len(actual["sources"])
    for sid, (stage, event_date, updated_date) in expected.items():
        source = entries[sid]
        assert source["stage"] == stage
        assert source["event_date"] == event_date
        assert source.get("updated_date") == updated_date
        assert source["open_call_authorized"] is False
        assert source["material_fact_publication_authorized"] is False

    # Parliamentary analysts reported co-rapporteurs' criticism, not an
    # adopted parliamentary resolution. Identity/date/stage cannot drift.
    ep = entries["SRC-EU-MFF-EP-CORAPPORTEURS-20261016"]
    assert ep["authority_class"] == "T1_PARLIAMENTARY_OFFICIAL_CONTEXT"
    assert ep["class"] == "official_parliamentary_analyst_commentary"
    assert len(actual["sources"]) == 12
    for sid, (stage, event_date, updated_date) in expected.items():
        entry = entries[sid]
        for mutated in (
            {**entry, "stage": "ADOPTED"},
            {**entry, "event_date": "2026-10-17"},
            {**entry, "updated_date": "2026-11-01"},
        ):
            candidate = {**actual, "sources": [mutated if row["id"] == sid else row for row in actual["sources"]]}
            expect_bad_registry(candidate, f"identity/stage/date spoof accepted: {sid}")
    # A different EPRS watch ID must not grant a vote/legislative-stage label.
    rogue_ep = {**ep, "id": "SRC-EU-MFF-EP-UNVERIFIED", "stage": "EP_POSITION"}
    expect_bad_registry(
        {**actual, "sources": [rogue_ep if row["id"] == ep["id"] else row for row in actual["sources"]]},
        "EPRS commentary promoted to EP_POSITION",
    )

    with tempfile.TemporaryDirectory(prefix="mff-contract-") as directory:
        temp = Path(directory)
        reg = temp / "registry.json"
        state = temp / "state.json"
        evidence = temp / "evidence"
        reg.write_text(json.dumps(REGISTRY), encoding="utf-8")

        probe._open_official = lambda *_args, **_kwargs: Response()
        first = probe.run(reg, state, evidence / "test-first", "test-first")
        row = first["sources"][0]
        assert first["summary"] == {"total": 1, "pass": 1, "fail": 0, "review_required": 0}
        assert row["observation_state"] == "RAW_FETCHED_STAGE_UNRECONCILED"
        assert row["raw_sha256"] == hashlib.sha256(BODY).hexdigest()
        assert row["fetched_at_utc"] and row["run_id"] == "test-first"
        assert row["stage"] == "COUNCIL_PARTIAL_CAP_POSITION"
        assert row["event_date"] == "2026-10-26" and row["updated_date"] == "2026-10-28"
        assert row["publish_authorized"] is False and row["open_call_authorized"] is False
        assert (evidence / "test-first" / row["raw_evidence_file"]).read_bytes() == BODY
        manifest = json.loads((evidence / "test-first" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["policy"] == "ACQUISITION_EVIDENCE_ONLY_NON_AUTHORIZING"
        assert manifest["sources"][0]["raw_sha256"] == row["raw_sha256"]

        # An original + a manifest are not enough: independently replay before
        # the result can replace the previous source-health/LKG snapshot.
        assert probe.replay_evidence(evidence / "test-first", reg) == first["summary"]
        saved_html = (evidence / "test-first" / row["raw_evidence_file"]).read_bytes()
        (evidence / "test-first" / row["raw_evidence_file"]).write_bytes(saved_html + b"tampered")
        try:
            probe.replay_evidence(evidence / "test-first", reg)
        except ValueError as exc:
            assert "SHA mismatch" in str(exc)
        else:
            raise AssertionError("MFF replay must reject tampered originals")
        (evidence / "test-first" / row["raw_evidence_file"]).write_bytes(saved_html)

        original_manifest = (evidence / "test-first" / "manifest.json").read_bytes()
        # Older valid parser-v2 receipts remain replayable, but never gain
        # stronger publication, stage or content-type authority.
        legacy = json.loads(original_manifest)
        legacy["parser_version"] = probe.PRIOR_REPLAY_VERSION
        legacy["sources"][0]["parser_version"] = probe.PRIOR_REPLAY_VERSION
        (evidence / "test-first" / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
        assert probe.replay_evidence(evidence / "test-first", reg) == first["summary"]
        legacy["sources"][0]["content_type"] = "application/problem+json; note=text/html"
        (evidence / "test-first" / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
        try:
            probe.replay_evidence(evidence / "test-first", reg)
        except ValueError:
            pass
        else:
            raise AssertionError("legacy MFF replay accepted fake HTML media type")
        (evidence / "test-first" / "manifest.json").write_bytes(original_manifest)
        for mutation in ("adoption", "cross-authority", "counter", "duplicate"):
            forged = json.loads(original_manifest)
            if mutation == "adoption":
                forged["sources"][0]["stage"] = "ADOPTED"
            elif mutation == "cross-authority":
                forged["sources"][0]["final_url"] = "https://fed.mai.gov.ro/in/eu-2028-2034/"
            elif mutation == "counter":
                forged["summary"]["pass"] += 1
            else:
                forged["sources"].append(dict(forged["sources"][0]))
            (evidence / "test-first" / "manifest.json").write_text(json.dumps(forged), encoding="utf-8")
            try:
                probe.replay_evidence(evidence / "test-first", reg)
            except ValueError:
                pass
            else:
                raise AssertionError(f"MFF replay must reject forged {mutation}")
            (evidence / "test-first" / "manifest.json").write_bytes(original_manifest)
        # A replay must not silently accept duplicate decoded JSON keys, NaN,
        # or additional instructions injected into a verified evidence envelope.
        raw_manifest = original_manifest.decode("utf-8").strip()
        poisoned_json = (
            '{"run_id":"forged",' + raw_manifest[1:],
            '{"\\u0072un_id":"forged",' + raw_manifest[1:],
            raw_manifest.replace('"review_required":0', '"review_required":NaN', 1),
        )
        for payload in poisoned_json:
            (evidence / "test-first" / "manifest.json").write_text(payload, encoding="utf-8")
            try:
                probe.replay_evidence(evidence / "test-first", reg)
            except ValueError:
                pass
            else:
                raise AssertionError("MFF replay accepted duplicate/non-finite JSON")
            (evidence / "test-first" / "manifest.json").write_bytes(original_manifest)
        for field, target in (
            ("open_call_status", "row"),
            ("publication_effect", "manifest"),
            ("OPEN_CALL", "summary"),
            ("review_required", "boolean_count"),
        ):
            injected = json.loads(original_manifest)
            if target == "row":
                injected["sources"][0][field] = "OPEN_CALL"
            elif target == "manifest":
                injected[field] = "OPEN_CALL"
            elif target == "summary":
                injected["summary"][field] = 1
            else:
                injected["summary"][field] = False  # bool is not an int count
            (evidence / "test-first" / "manifest.json").write_text(json.dumps(injected), encoding="utf-8")
            try:
                probe.replay_evidence(evidence / "test-first", reg)
            except ValueError:
                pass
            else:
                raise AssertionError(f"MFF replay accepted injected {field}/{target}")
            (evidence / "test-first" / "manifest.json").write_bytes(original_manifest)
        injected = json.loads(original_manifest)
        injected["sources"][0]["semantic_hash_changed"] = True
        (evidence / "test-first" / "manifest.json").write_text(json.dumps(injected), encoding="utf-8")
        try:
            probe.replay_evidence(evidence / "test-first", reg)
        except ValueError:
            pass
        else:
            raise AssertionError("MFF replay accepted unreconciled semantic-change flag")
        (evidence / "test-first" / "manifest.json").write_bytes(original_manifest)
        stray = evidence / "test-first" / "unregistered.html"
        stray.write_bytes(saved_html)
        try:
            probe.replay_evidence(evidence / "test-first", reg)
        except ValueError as exc:
            assert "orphaned" in str(exc)
        else:
            raise AssertionError("MFF replay must reject orphaned originals")
        stray.unlink()
        assert probe.replay_evidence(evidence / "test-first", reg) == first["summary"]

        # A replay error cannot advance the persisted last-known health state.
        frozen_state_before_replay = state.read_bytes()
        original_replay = probe.replay_evidence
        try:
            def reject_replay(*_args, **_kwargs):
                raise ValueError("synthetic replay integrity failure")
            probe.replay_evidence = reject_replay
            try:
                probe.run(reg, state, evidence / "test-replay-failure", "test-replay-failure")
            except ValueError as exc:
                assert "integrity failure" in str(exc)
            else:
                raise AssertionError("MFF health state advanced without replay")
        finally:
            probe.replay_evidence = original_replay
        assert state.read_bytes() == frozen_state_before_replay

        # An accidental retry against an existing evidence path cannot overwrite
        # the original source, receipt manifest or committed health snapshot.
        frozen_manifest = (evidence / "test-first" / "manifest.json").read_bytes()
        frozen_state = state.read_bytes()
        try:
            probe.run(reg, state, evidence / "test-first", "test-overwrite")
        except FileExistsError:
            pass
        else:
            raise AssertionError("immutable MFF raw evidence overwritten by retry")
        assert (evidence / "test-first" / "manifest.json").read_bytes() == frozen_manifest
        assert (evidence / "test-first" / row["raw_evidence_file"]).read_bytes() == BODY
        assert state.read_bytes() == frozen_state

        changed = BODY.replace(b"partial negotiating position", b"changed negotiating position")
        probe._open_official = lambda *_args, **_kwargs: Response(changed)
        second = probe.run(reg, state, evidence / "test-second", "test-second")
        assert second["sources"][0]["semantic_hash_changed"] is True
        assert second["sources"][0]["review_required"] is True
        assert second["sources"][0]["publish_authorized"] is False

        def denied(*_args, **_kwargs):
            raise urllib.error.HTTPError(SOURCE["url"], 403, "Denied", {}, None)
        probe._open_official = denied
        fail = probe.run(reg, state, evidence / "test-failed", "test-failed")
        row = fail["sources"][0]
        assert row["observation_state"] == "PROVISIONAL_FAIL_CLOSED"
        assert row["raw_sha256"] is None and row["fetched_at_utc"] is None
        assert row["last_known_semantic_sha256"] == second["sources"][0]["semantic_sha256"]
        assert row["publish_authorized"] is False and row["review_required"] is False

        # Refuse cross-domain redirects and partial/truncated body hashing.
        probe._open_official = lambda *_args, **_kwargs: Response(BODY, "https://evil.example/fake")
        assert probe.run(reg, state, evidence / "test-redirect", "test-redirect")["summary"]["fail"] == 1
        # An official cross-authority final 200 cannot masquerade as Council evidence,
        # even when the transport opener has been mocked or a redirect was hidden.
        probe._open_official = lambda *_args, **_kwargs: Response(BODY, "https://fed.mai.gov.ro/in/eu-2028-2034/")
        cross_authority = probe.run(reg, state, evidence / "test-official-cross-authority", "test-official-cross-authority")["sources"][0]
        assert cross_authority["health"] == "FAIL"
        assert cross_authority["observation_state"] == "PROVISIONAL_FAIL_CLOSED"
        assert cross_authority["raw_sha256"] is None
        assert cross_authority["publish_authorized"] is False
        probe._open_official = lambda *_args, **_kwargs: Response(b"x" * (probe.MAX_BYTES + 1))
        assert probe.run(reg, state, evidence / "test-oversized", "test-oversized")["summary"]["fail"] == 1
        probe._open_official = lambda *_args, **_kwargs: Response(BODY, declared_length=1)
        assert probe.run(reg, state, evidence / "test-truncated", "test-truncated")["summary"]["fail"] == 1
        # A text/plain, JSON or PDF body is not HTML simply because a MIME
        # parameter or suffix contains "html"; no raw receipt is admitted.
        for idx, mime in enumerate((
            "application/problem+json; note=text/html",
            "text/plain; filename=notice.html",
            "application/x-html",
            "text/html-extra",
            "application/pdf; filename=notice.html",
            "",
        )):
            assert not probe.exact_html_mime(mime)
            probe._open_official = lambda *_args, _mime=mime, **_kwargs: Response(BODY, content_type=_mime)
            bad = probe.run(reg, state, evidence / f"test-mime-{idx}", f"test-mime-{idx}")
            bad_row = bad["sources"][0]
            assert bad_row["health"] == "FAIL" and bad_row["observation_state"] == "PROVISIONAL_FAIL_CLOSED"
            assert bad_row["raw_sha256"] is None and bad_row["publish_authorized"] is False
        for mime in ("text/html", "TEXT/HTML; charset=utf-8", "application/xhtml+xml; charset=utf-8"):
            assert probe.exact_html_mime(mime)
        probe._open_official = lambda *_args, **_kwargs: Response(BODY, content_type="application/xhtml+xml")
        assert probe.run(reg, state, evidence / "test-xhtml", "test-xhtml")["summary"]["pass"] == 1
        assert probe.replay_evidence(evidence / "test-xhtml", reg)["pass"] == 1

        # An official 200 response may still be an anti-bot/interstitial page.
        # Nor may compressed bytes be misread as verified UTF-8 HTML.
        challenge = (b"<html><head><title>Access Denied</title></head><body>" +
                     b"Security gateway blocked this request. " * 20 + b"</body></html>")
        probe._open_official = lambda *_args, **_kwargs: Response(challenge)
        challenge_row = probe.run(reg, state, evidence / "test-challenge", "test-challenge")["sources"][0]
        assert challenge_row["health"] == "FAIL"
        assert challenge_row["observation_state"] == "PROVISIONAL_FAIL_CLOSED"
        assert challenge_row["raw_sha256"] is None and challenge_row["fetched_at_utc"] is None
        probe._open_official = lambda *_args, **_kwargs: Response(BODY, content_encoding="gzip")
        encoded_row = probe.run(reg, state, evidence / "test-encoded", "test-encoded")["sources"][0]
        assert encoded_row["health"] == "FAIL" and encoded_row["raw_sha256"] is None
        probe._open_official = lambda *_args, **_kwargs: Response(BODY, content_encoding="identity")
        assert probe.run(reg, state, evidence / "test-identity", "test-identity")["summary"]["pass"] == 1
        probe._open_official = lambda *_args, **_kwargs: Response(BODY, declared_length=len(BODY))
        assert probe.run(reg, state, evidence / "test-complete", "test-complete")["summary"]["pass"] == 1
        assert state.exists() and (evidence / "test-first" / "manifest.json").exists()
        print("PASS: MFF stage/provenance + exact HTML MIME/XHTML + legacy replay + 403/LKG + immutable raw and interstitial fail-closed")


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        probe._open_official = original_urlopen
