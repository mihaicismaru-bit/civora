#!/usr/bin/env python3
"""Adversarial exact-2026 official EPSS gateway and immutable provenance tests."""
import json
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
import water4all_2026_official_pair as pair
import water4all_2026_epss_gateway as gate

EU = gate.CALL_ID
STAMP = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
HEAD = ("""<!doctype html><html><body>
<h1>Water4All 2026 Joint Transnational Call</h1>
<p>10 November 2026 preproposals; 6 April 2027 full proposals; EPSS updated October 23.</p>
<h3>Online Submission Tool &amp; Partnering Tool</h3>
<p>Online submission tool and partnering tool are available at a new link
<a href="https://epss.proposals.ee/water4all/2026">here</a></p>
<h3>Tentative timeline</h3><p>Open calls are stage specific.</p>
</body></html>""").encode()
LOGIN = ("""<!doctype html><html><body><h1>Water4All 2026 Joint Transnational Call</h1>
<p>"Sustainable Water Management"</p><h3>Sign in</h3>
<p>For accessing the Water4All EPSS, please sign in. Partner / project search.</p>
<p>Technical support for authorized applicants.</p></body></html>""").encode()


def reject(f, marker):
    try:
        f()
    except (ValueError, OSError, KeyError, TypeError) as e:
        assert marker in str(e), (marker, str(e))
        return
    raise AssertionError("unsafe Water4All EPSS evidence accepted: " + marker)


def run():
    pair.validate_html(EU, HEAD, "text/html")
    assert gate.source_link(HEAD) == gate.GATEWAY
    gate.validate_gateway(LOGIN, "text/html")
    assert gate.OLD_PDF_ENDPOINT != gate.GATEWAY
    for bad in (
        HEAD.replace(b"epss.proposals.ee/water4all/2026", b"proposals.etag.ee/water4all/"),
        HEAD.replace(b"https://epss.", b"http://epss."),
        HEAD.replace(b'<a href=', b'<a href="https://evil.invalid/" href='),
        HEAD.replace(b'<a href=', b'<a hidden href='),
        HEAD.replace(b'here</a>', b'click</a>'),
        HEAD.replace(b'</body>', b'<a href="https://evil.invalid/">here</a></body>').replace(
            b'<h3>Tentative timeline</h3>', b''),
        HEAD.replace(b'</body>', b'<h3>Online Submission Tool &amp; Partnering Tool</h3>'
                     b'<a href="https://evil.invalid/">here</a></body>'),
        HEAD.replace(b'<a href=', b'<script><a href=', 1),
    ):
        reject(lambda b=bad: gate.source_link(b), "")
    for bad in (
        LOGIN.replace(b"Water4All 2026", b"Water4All 2025"),
        LOGIN.replace(b"Sign in", b"News"),
        b"<!doctype html><html><script>" + LOGIN + b"</script></html>",
    ):
        reject(lambda b=bad: gate.validate_gateway(b, "text/html"), "")
    reject(lambda: gate.validate_gateway(LOGIN, "application/pdf"), "MIME")
    reject(lambda: gate.validate_gateway_url("https://proposals.etag.ee/water4all/"), "drift")
    reject(lambda: gate.validate_gateway_url(gate.GATEWAY + "?stage=open"), "drift")

    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        source_dir, output = base / "source", base / "gateway"
        source = pair.seal(source_dir, {EU: (HEAD, "text/html", STAMP)}, "water4all-epss-test")
        assert source["pair_complete"] is False
        result = gate.seal(source_dir, output, LOGIN, "text/html", STAMP)
        assert result["status"] == "EPSS_PUBLIC_LOGIN_RAW_REPLAY_VERIFIED_NON_AUTHORIZING"
        assert result["open_call_authorized"] is False
        assert gate.replay(source_dir, output) == result
        manifest = output / "handoff.json"
        original = manifest.read_bytes()
        evidence = json.loads(original)
        assert evidence["source_pair_handoff_sha256"] == json.loads(
            (source_dir / "handoff.json").read_bytes())["handoff_sha256"]
        assert evidence["official_operator_raw_sha256"] == pair.sha(HEAD)
        assert all(evidence[k] is False for k in gate.LOCKED)
        reject(lambda: gate.seal(source_dir, output, LOGIN, "text/html", STAMP), "immutable")
        for key, value in (("open_call_authorized", True),
                           ("submission_live_authorized", True),
                           ("observation_state", "OPEN_CALL"),
                           ("official_operator_raw_sha256", "0" * 64),
                           ("source_pair_handoff_sha256", "0" * 64),
                           ("requested_url", gate.OLD_PDF_ENDPOINT)):
            modified = dict(evidence)
            modified[key] = value
            modified["handoff_sha256"] = pair.sha(pair.canonical({
                k: v for k, v in modified.items() if k != "handoff_sha256"
            }))
            manifest.write_bytes(pair.canonical(modified))
            reject(lambda: gate.replay(source_dir, output), "mismatch")
        manifest.write_bytes(original)
        login_path = output / "raw/epss_2026.html"
        login_path.write_bytes(LOGIN + b"\n<!-- tampered -->")
        reject(lambda: gate.replay(source_dir, output), "mismatch")
        login_path.write_bytes(LOGIN)
        (output / "raw/extra.html").write_bytes(LOGIN)
        reject(lambda: gate.replay(source_dir, output), "file-set")
        (output / "raw/extra.html").unlink()
        assert gate.replay(source_dir, output) == result
        reject(lambda: gate.seal(source_dir, base / "too-late", LOGIN,
                                 "text/html", "2026-11-11T10:00:00Z"), "near")
    print("Water4All exact-page -> current EPSS login bound replay PASS; stale PDF URL rejected, NO OPEN")


if __name__ == "__main__":
    run()
