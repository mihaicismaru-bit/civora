#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

API_ORIGIN = "https://api.eucons.ro"
FORM_ACTION = f"{API_ORIGIN}/api/leads"

DETAIL_FIELDS = '''
  <label>Tip organizație<select name="audience_id" required>
    <option value="">Alege categoria</option>
    <option value="companies_entrepreneurs">Companie / antreprenor</option>
    <option value="public_authorities_institutions">Autoritate / instituție publică</option>
    <option value="ngos_eligible_organizations">ONG / organizație eligibilă</option>
    <option value="existing_beneficiaries">Beneficiar cu proiect în implementare</option>
  </select></label>
  <label>Investiția sau domeniul vizat<input name="investment_terms[]" required maxlength="300" placeholder="ex. digitalizare, energie, producție"></label>
  <label>Stadiul proiectului<select name="project_stage" required>
    <option value="unknown">Nu știu încă</option>
    <option value="idea">Idee</option>
    <option value="preparation">Pregătire</option>
    <option value="application">Cerere în pregătire / depunere</option>
    <option value="contracted">Contractat</option>
    <option value="implementation">În implementare</option>
    <option value="at_risk">În dificultate / risc</option>
  </select></label>
  <label>Orizont de timp<select name="timeline">
    <option value="unknown">Nu știu încă</option>
    <option value="now_30_days">Acum – 30 zile</option>
    <option value="31_90_days">31 – 90 zile</option>
    <option value="91_180_days">91 – 180 zile</option>
    <option value="later">Mai târziu</option>
  </select></label>
  <label>Județ / localizare<input name="county" maxlength="300" autocomplete="address-level1"></label>
  <label>Cod CAEN / activitate relevantă<input name="activity_codes[]" maxlength="300" placeholder="opțional"></label>
  <label>Valoarea finanțării vizate (EUR)<input name="requested_grant_eur" type="number" min="1" step="1" inputmode="numeric" placeholder="opțional"></label>'''

ACTIVE_HINT = (
    '<p class="eu-hint">Solicitarea este transmisă securizat către runtime-ul EUCONS. '
    'Datele reale rămân în mediul de găzduire autorizat și nu sunt scrise în GitHub.</p>'
)
STATUS_NODE = '<p class="eu-hint" data-eucons-form-status aria-live="polite"></p>'

FORMS_JS = r'''"use strict";
(() => {
  const starts = new WeakMap();
  const makeId = () => (globalThis.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `eucons-${Date.now()}-${Math.random().toString(36).slice(2)}`;

  const initialize = (form) => {
    starts.set(form, Date.now());
    const id = form.querySelector('input[name="submission_id"]');
    const age = form.querySelector('input[name="submission_age_ms"]');
    if (id) id.value = makeId();
    if (age) age.value = "0";
  };

  for (const form of document.querySelectorAll("form[data-eucons-lead-form]")) {
    initialize(form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const age = form.querySelector('input[name="submission_age_ms"]');
      if (age) age.value = String(Math.max(0, Date.now() - (starts.get(form) || Date.now())));
      const status = form.querySelector("[data-eucons-form-status]");
      const button = form.querySelector('button[type="submit"]');
      if (button) button.disabled = true;
      if (status) status.textContent = "Se transmite solicitarea…";
      try {
        const body = new URLSearchParams();
        for (const [key, value] of new FormData(form).entries()) body.append(key, String(value));
        const response = await fetch(form.action, {
          method: "POST",
          mode: "cors",
          credentials: "omit",
          referrerPolicy: "strict-origin-when-cross-origin",
          headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
          body,
        });
        let data = {};
        try { data = await response.json(); } catch (_) { data = {}; }
        if (!response.ok || data.status !== "accepted") {
          throw new Error(data.code || `HTTP_${response.status}`);
        }
        if (status) status.textContent = `Solicitarea a fost înregistrată. Cod: ${data.request_id}.`;
        form.reset();
        initialize(form);
      } catch (_) {
        if (status) status.textContent = "Solicitarea nu a putut fi înregistrată acum. Datele nu au fost confirmate ca salvate; te rugăm să încerci din nou.";
      } finally {
        if (button) button.disabled = false;
      }
    });
  }
})();
'''


def activate(target: Path) -> dict[str, object]:
    target = target.resolve()
    form_pages = 0
    forms = 0
    marker = '<label>Telefon<input name="phone" maxlength="80" autocomplete="tel"></label>'
    old_hint = '<p class="eu-hint">Transmiterea devine activă numai după conectarea endpointului securizat al mediului de producție. Motorul respinge câmpurile nepermise și păstrează consimțământul de marketing separat.</p>'

    for page in sorted(target.rglob("index.html")):
        text = page.read_text(encoding="utf-8")
        if "data-eucons-lead-form" not in text:
            continue
        form_pages += 1
        page_forms = text.count("data-eucons-lead-form")
        forms += page_forms
        if 'action="/api/leads"' not in text:
            raise ValueError(f"lead action drift in {page}")
        if marker not in text:
            raise ValueError(f"lead field insertion marker missing in {page}")
        text = text.replace('action="/api/leads"', f'action="{FORM_ACTION}"')
        text = text.replace(
            '<input name="organization_name" maxlength="300" autocomplete="organization">',
            '<input name="organization_name" required maxlength="300" autocomplete="organization">',
        )
        text = text.replace(marker, marker + DETAIL_FIELDS)
        text = text.replace(
            '<textarea name="message" maxlength="4000" rows="6"></textarea>',
            '<textarea name="message" required maxlength="4000" rows="6"></textarea>',
        )
        if old_hint not in text:
            raise ValueError(f"lead activation hint drift in {page}")
        text = text.replace(old_hint, STATUS_NODE + ACTIVE_HINT)
        page.write_text(text, encoding="utf-8")

    if forms < 3:
        raise ValueError(f"expected at least three production lead forms, found {forms}")

    forms_js = target / "assets" / "forms.js"
    if not forms_js.is_file():
        raise ValueError("forms.js missing")
    forms_js.write_text(FORMS_JS, encoding="utf-8")

    privacy = target / "confidentialitate" / "index.html"
    if not privacy.is_file():
        raise ValueError("privacy page missing")
    privacy_text = privacy.read_text(encoding="utf-8")
    provider_sentence = (
        " Componenta de primire a formularelor este găzduită separat de site, pe infrastructura "
        "de hosting asociată domeniului romania-webhosting.com, exclusiv pentru primire, stocare și procesare comercială solicitată."
    )
    needle = "Orice furnizor activat la găzduire trebuie reflectat în această informare înainte de colectarea reală."
    if needle not in privacy_text:
        raise ValueError("privacy provider reconciliation marker missing")
    privacy_text = privacy_text.replace(needle, needle + provider_sentence)
    privacy.write_text(privacy_text, encoding="utf-8")

    activation = {
        "schema_version": 1,
        "state": "PHP_RUNTIME_CONNECTED_ARTIFACT",
        "public_origin": "https://eucons.ro",
        "api_origin": API_ORIGIN,
        "lead_route": FORM_ACTION,
        "form_pages": form_pages,
        "forms": forms,
        "runtime_production_enabled": False,
        "activation_requires_live_https_and_synthetic_smoke": True,
    }
    (target / "runtime-activation.json").write_text(
        json.dumps(activation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return activation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(json.dumps(activate(Path(args.target)), ensure_ascii=False))


if __name__ == "__main__":
    main()
