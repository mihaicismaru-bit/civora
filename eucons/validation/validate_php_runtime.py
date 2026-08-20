#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    contract = load_json(EUCONS / "runtime" / "php" / "runtime_contract.json")
    if contract.get("engine_id") != "EUCONS_E29_PHP_RUNTIME_ADAPTER":
        raise SystemExit("PHP runtime engine id drift")
    if contract.get("runtime") != "PHP_8_PLUS_SHARED_HOSTING":
        raise SystemExit("PHP runtime class drift")
    if contract.get("public_origin") != "https://eucons.ro" or contract.get("api_origin") != "https://api.eucons.ro":
        raise SystemExit("PHP runtime origins drift")
    if contract.get("lead_route") != "/api/leads":
        raise SystemExit("PHP runtime lead route drift")
    if contract.get("activation", {}).get("production_enabled") is not False:
        raise SystemExit("PHP runtime may not activate production before full commercial live gate")
    if contract.get("storage", {}).get("real_pii_in_git") is not False:
        raise SystemExit("PHP runtime PII storage failed open")
    if contract.get("storage", {}).get("strategy") != "FILESYSTEM_ATOMIC_JSON_OUTSIDE_WEBROOT":
        raise SystemExit("PHP runtime persistence strategy drift")

    source = (EUCONS / "runtime" / "php" / "src" / "LeadRuntime.php").read_text(encoding="utf-8")
    crm = (EUCONS / "runtime" / "php" / "src" / "CrmRuntime.php").read_text(encoding="utf-8")
    retention = (EUCONS / "runtime" / "php" / "src" / "RetentionRuntime.php").read_text(encoding="utf-8")
    mail = (EUCONS / "runtime" / "php" / "src" / "MailRuntime.php").read_text(encoding="utf-8")
    maintenance = (EUCONS / "runtime" / "php" / "maintenance.php").read_text(encoding="utf-8")
    public = (EUCONS / "runtime" / "php" / "public" / "index.php").read_text(encoding="utf-8")
    htaccess = (EUCONS / "runtime" / "php" / "public" / ".htaccess").read_text(encoding="utf-8")

    for token in ["lead_contract.json", "forms.json", "PII_STORAGE_INSIDE_WEBROOT", "SPAM_REJECTED", "PRIVACY_ACK_REQUIRED", "atomicWriteJson", "flock", "dedupe_key"]:
        if token not in source:
            raise SystemExit(f"PHP lead runtime missing {token}")
    for token in ["crm_contract.json", "LEAD_CREATED", "LEAD_SEEN_AGAIN", "retention_class", "last_material_activity_at", "state.json", "flock"]:
        if token not in crm:
            raise SystemExit(f"PHP CRM runtime missing {token}")
    for token in ["privacy_security_contract.json", "LEAD_INQUIRY", "COMMERCIAL_RELATIONSHIP", "RETENTION_ERASED", "maintenance/receipts", "holds/"]:
        if token not in retention:
            raise SystemExit(f"PHP retention runtime missing {token}")
    for token in ["/home/eucons/eucons-secrets/mail.json", "office@eucons.ro", "mail.eucons.ro:465", "LEAD_ACKNOWLEDGEMENT", "mail/outbox", "mail/receipts", "verify_peer"]:
        if token not in mail:
            raise SystemExit(f"PHP mail runtime missing {token}")
    for token in ["PHP_SAPI !== 'cli'", "retention", "mail_retry", "EUCONS_MAINTENANCE_MAIL_HOLD"]:
        if token not in maintenance:
            raise SystemExit(f"PHP maintenance runtime missing {token}")
    for token in ["EuconsCrmRuntime", "EuconsMailRuntime", "EuconsRetentionRuntime", "CRM_PERSISTENCE_NOT_CONFIRMED", "EUCONS_MAIL_HELD"]:
        if token not in public:
            raise SystemExit(f"PHP endpoint commercial bridge missing {token}")

    for token in ["Access-Control-Allow-Origin", "Content-Security-Policy", "Referrer-Policy", "X-Content-Type-Options", "X-Frame-Options", "Permissions-Policy", "ORIGIN_REQUIRED", "UNSUPPORTED_CONTENT_TYPE"]:
        if token not in public:
            raise SystemExit(f"PHP endpoint missing {token}")
    for token in ["Options -Indexes", "RewriteRule ^ index.php", "RewriteCond %{HTTPS} !=on", "RewriteCond %{HTTP:X-Forwarded-Proto} !https", "https://api.eucons.ro%{REQUEST_URI}"]:
        if token not in htaccess:
            raise SystemExit(f"PHP runtime htaccess guard incomplete: {token}")

    combined = "\n".join([source, crm, retention, mail, maintenance, public])
    for forbidden in ["API_KEY=", "PASSWORD=", "CLIENT_SECRET=", "ACCESS_TOKEN=", "synthetic-secret-not-real"]:
        if forbidden in combined:
            raise SystemExit("secret-like assignment committed in PHP runtime")
    if "password' => '" in mail or '"password": "' in mail:
        raise SystemExit("mail runtime contains inline password")
    sensitive_log_tokens = ["$_POST", "$payload", "$processed", "['email']", "['contact_name']", "['phone']", "['message']", "['password']"]
    for line in (public + "\n" + maintenance).splitlines():
        if "error_log(" in line and any(token in line for token in sensitive_log_tokens):
            raise SystemExit("PHP runtime logs sensitive field")

    builder = load_module("e29_prod_builder", EUCONS / "deployment" / "build_production_ready.py")
    activator = load_module("e29_php_activator", EUCONS / "deployment" / "activate_php_runtime.py")
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "site"
        before = builder.build_site(target)
        if before.get("pages") != 26:
            raise SystemExit("production build page count drift before PHP activation")
        activated = activator.activate(target)
        if activated.get("forms", 0) < 3 or activated.get("form_pages", 0) < 3:
            raise SystemExit("PHP runtime form activation incomplete")
        if activated.get("runtime_production_enabled") is not False:
            raise SystemExit("activation artifact may not declare live before full commercial smoke")
        for page in [target / "evaluare-proiect" / "index.html", target / "solicita-oferta" / "index.html", target / "contact" / "index.html"]:
            text = page.read_text(encoding="utf-8")
            if 'action="https://api.eucons.ro/api/leads"' not in text:
                raise SystemExit(f"external PHP lead action missing: {page}")
            for field in ["audience_id", "investment_terms[]", "project_stage", "timeline", "county", "activity_codes[]", "requested_grant_eur"]:
                if f'name="{field}"' not in text:
                    raise SystemExit(f"activated form missing {field}: {page}")
            if 'name="organization_name" required' not in text or 'name="message" required' not in text:
                raise SystemExit(f"activated form required-field contract incomplete: {page}")
        js = (target / "assets" / "forms.js").read_text(encoding="utf-8")
        for token in ["fetch(form.action", "URLSearchParams", "credentials: \"omit\"", "data-eucons-form-status"]:
            if token not in js:
                raise SystemExit(f"activated forms.js missing {token}")
        privacy = (target / "confidentialitate" / "index.html").read_text(encoding="utf-8")
        if "romania-webhosting.com" not in privacy:
            raise SystemExit("active hosting role not reconciled in privacy page")
        activation_doc = load_json(target / "runtime-activation.json")
        if activation_doc.get("api_origin") != "https://api.eucons.ro":
            raise SystemExit("runtime activation manifest drift")

    print(json.dumps({
        "status": "PASS",
        "phase": "E29",
        "runtime": "PHP_8_PLUS_SHARED_HOSTING",
        "lead_route": "https://api.eucons.ro/api/leads",
        "production_pages": 26,
        "activated_forms": activated["forms"],
        "pii_storage": "OUTSIDE_WEBROOT",
        "crm_persistence": "IMPLEMENTED_FAIL_CLOSED",
        "retention": "IMPLEMENTED_WITH_RECEIPTS",
        "mailbox": "EXTERNAL_SECRET_REQUIRED",
        "https_redirect": "CANONICAL_HTACCESS",
        "production_enabled": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
