#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CANONICAL_ORIGIN = "https://eucons.ro"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def promote_html(text: str, path: str, builder) -> str:
    text = text.replace(
        '<meta name="robots" content="noindex,nofollow">',
        '<meta name="robots" content="index,follow,max-image-preview:large">',
    )
    text = text.replace(
        '<p class="eu-hint">Versiune de dezvoltare: indexarea publică și colectarea de date rămân dezactivate până la porțile de acceptanță.</p>',
        '<p class="eu-hint">Informațiile despre finanțări și rezultate sunt publicate numai după verificarea sursei și a provenienței.</p>',
    )
    return text


def prod_shell(builder, title: str, description: str, path: str, body: str, *, form_script: bool = False) -> str:
    text = promote_html(builder.shell(title, description, path, body), path, builder)
    if form_script:
        asset = builder.relative_asset_prefix(path) + "assets/forms.js"
        text = text.replace("</head>", f'<script defer src="{esc(asset)}"></script>\n</head>')
    return text


def render_people(builder, data: dict[str, Any]) -> str:
    records = builder.publishable_records(data["people"], "people")
    if not records:
        raise ValueError("production-ready build requires at least one verified public person")
    cards = []
    for item in records:
        name = str(item.get("display_name") or "").strip()
        headline = str(item.get("public_headline") or "").strip()
        bio = str(item.get("public_bio") or "").strip()
        if not name or not headline or not bio:
            raise ValueError("publishable person lacks production copy")
        initials = "".join(part[0] for part in name.split()[:2]).upper()
        cards.append(
            f'<article class="eu-card eu-stack"><p class="eu-eyebrow" aria-hidden="true">{esc(initials)}</p>'
            f'<h2 class="eu-heading-md">{esc(name)}</h2><p class="eu-card__meta">{esc(headline)}</p>'
            f'<p class="eu-card__body">{esc(bio)}</p></article>'
        )
    body = (
        '<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack">'
        '<p class="eu-eyebrow">Echipa Euroconsult</p><h1 class="eu-heading-lg">Oamenii din spatele serviciilor</h1>'
        '<p class="eu-lead">Profilurile de mai jos includ numai roluri și competențe susținute de dovezi publicabile; nu folosim portrete inventate sau calificări neverificate.</p>'
        f'<div class="eu-grid">{"".join(cards)}</div></div></section>'
    )
    return prod_shell(builder, "Echipa", "Profiluri profesionale verificate ale echipei Euroconsult.", "/echipa/", body)


def render_cases(builder, data: dict[str, Any]) -> str:
    records = builder.publishable_records(data["cases"], "cases")
    if not records:
        raise ValueError("production-ready build requires at least one verified public case")
    cards = []
    for item in records:
        title = str(item.get("title") or "").strip()
        problem = str(item.get("public_problem") or "").strip()
        intervention = str(item.get("public_intervention") or "").strip()
        outcomes = item.get("public_outcomes") or []
        if not title or not problem or not intervention or not outcomes:
            raise ValueError("publishable case lacks production copy")
        outcome_html = "".join(f"<li>{esc(row)}</li>" for row in outcomes)
        cards.append(
            f'<article class="eu-card eu-stack"><p class="eu-eyebrow">Exemplu documentat</p><h2 class="eu-heading-md">{esc(title)}</h2>'
            f'<p class="eu-card__meta">Context</p><p class="eu-card__body">{esc(problem)}</p>'
            f'<p class="eu-card__meta">Intervenție</p><p class="eu-card__body">{esc(intervention)}</p>'
            f'<p class="eu-card__meta">Rezultat consemnat</p><ul>{outcome_html}</ul></article>'
        )
    body = (
        '<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack">'
        '<p class="eu-eyebrow">Experiență documentată</p><h1 class="eu-heading-lg">Proiecte și exemple de implementare</h1>'
        '<p class="eu-lead">Separăm experiența documentată de testimonialele clienților. Exemplele publice nu atribuie un client dacă acea relație nu a fost autorizată explicit.</p>'
        f'<div class="eu-grid">{"".join(cards)}</div></div></section>'
    )
    return prod_shell(builder, "Proiecte și studii de caz", "Exemple istorice Euroconsult publicate cu proveniență și limite explicite.", "/proiecte/", body)


def render_knowledge(builder, data: dict[str, Any], kind: str, path: str, title: str, lead: str) -> str:
    services = [row for row in data["services"].get("services", []) if row.get("id") in builder.publishable_service_ids(data["evidence"])]
    cards = []
    for service in services:
        label = service["label"]
        summary = service["summary"]
        if kind == "GUIDE":
            body_copy = " · ".join(service.get("deliverables") or [])
            card_title = f"Ghid: {label}"
        elif kind == "ANALYSIS":
            body_copy = " · ".join(service.get("process") or [])
            card_title = f"Cum abordăm {label.lower()}"
        else:
            body_copy = " · ".join(service.get("boundaries") or [])
            card_title = f"Întrebări utile despre {label.lower()}"
        cards.append(
            f'<article class="eu-card eu-stack"><p class="eu-eyebrow">{esc(kind.title())}</p>'
            f'<h2 class="eu-heading-md">{esc(card_title)}</h2><p class="eu-card__body">{esc(summary)}</p>'
            f'<p class="eu-hint">{esc(body_copy)}</p></article>'
        )
    body = (
        f'<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Cunoaștere aplicată</p>'
        f'<h1 class="eu-heading-lg">{esc(title)}</h1><p class="eu-lead">{esc(lead)}</p><div class="eu-grid">{"".join(cards)}</div></div></section>'
    )
    return prod_shell(builder, title, lead, path, body)


def render_funding(builder) -> str:
    body = (
        '<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack">'
        '<p class="eu-eyebrow">Oportunități verificate</p><h1 class="eu-heading-lg">Finanțări relevante, cu statut și proveniență controlate</h1>'
        '<p class="eu-lead">EUCONS preia numai oportunități admise de proiecția verificată PARTENER → EUCONS. Un apel expirat, stale sau insuficient verificat nu este prezentat ca disponibil.</p>'
        '<div class="eu-alert eu-alert--info" role="status">Lista publică se reconstruiește din proiecția verificată la fiecare ciclu de publicare. În lipsa unei oportunități acționabile, pagina rămâne fără apeluri demonstrative.</div>'
        '<div class="eu-actions"><a class="eu-button eu-button--primary" href="/evaluare-proiect/">Verifică potrivirea proiectului tău</a><a class="eu-button eu-button--secondary" href="/servicii/strategie-finantare-eligibilitate/">Vezi serviciul de eligibilitate</a></div>'
        '</div></section>'
    )
    return prod_shell(builder, "Finanțări", "Oportunități de finanțare publicate numai după verificarea statutului și provenienței.", "/finantari/", body)


def progressive_input(field: str, *, required: bool = False) -> str:
    labels = {
        "organization_name": "Organizație",
        "audience_id": "Tipul organizației",
        "investment_terms": "Ce investiție sau nevoie ai?",
        "project_stage": "Etapa proiectului",
        "message": "Contextul relevant",
        "activity_codes": "Coduri CAEN relevante",
        "county": "Județ",
        "requested_grant_eur": "Valoarea orientativă solicitată (EUR)",
        "timeline": "Când este necesar următorul pas?",
    }
    label = labels.get(field, field.replace("_", " ").title())
    required_attr = " required" if required else ""
    if field == "audience_id":
        control = (
            f'<select name="{field}"{required_attr}><option value="">Alege</option>'
            '<option value="companies_entrepreneurs">Companie / antreprenor</option>'
            '<option value="public_authorities_institutions">Autoritate / instituție publică</option>'
            '<option value="ngos_eligible_organizations">ONG / organizație eligibilă</option>'
            '<option value="existing_beneficiaries">Beneficiar cu proiect contractat</option></select>'
        )
    elif field == "project_stage":
        control = (
            f'<select name="{field}"{required_attr}><option value="">Alege</option>'
            '<option value="idea">Idee</option><option value="preparation">Pregătire</option>'
            '<option value="application">Depunere</option><option value="contracted">Contractat</option>'
            '<option value="implementation">Implementare</option><option value="at_risk">În risc / blocat</option>'
            '<option value="unknown">Nu știu încă</option></select>'
        )
    elif field == "timeline":
        control = (
            f'<select name="{field}"{required_attr}><option value="">Alege</option>'
            '<option value="now_30_days">În următoarele 30 de zile</option><option value="31_90_days">31–90 de zile</option>'
            '<option value="91_180_days">91–180 de zile</option><option value="later">Mai târziu</option>'
            '<option value="unknown">Nu știu încă</option></select>'
        )
    elif field == "message":
        control = f'<textarea name="{field}" rows="5" maxlength="4000"{required_attr}></textarea>'
    elif field == "requested_grant_eur":
        control = f'<input name="{field}" type="number" min="1" step="1"{required_attr}>'
    else:
        list_attr = ' data-eucons-list="true"' if field in {"investment_terms", "activity_codes"} else ""
        control = f'<input name="{field}" maxlength="300"{list_attr}{required_attr}>'
    hint = '<span class="eu-hint">Separă valorile prin virgulă.</span>' if field in {"investment_terms", "activity_codes"} else ""
    return f"<label>{esc(label)}{control}{hint}</label>"


def progressive_form(journey: dict[str, Any], form_id: str, step: str, fields: list[str], *, hidden: bool = False) -> str:
    required = step == "PROFILE"
    controls = "".join(progressive_input(field, required=required) for field in fields)
    hidden_attr = " hidden" if hidden else ""
    step_labels = {"PROFILE": "1. Organizația și situația", "CONTEXT": "2. Detalii utile", "CONTACT": "3. Date pentru răspuns"}
    if step == "CONTACT":
        controls = '''<label>Nume și prenume<input name="contact_name" required maxlength="300" autocomplete="name"></label>
<label>Email<input name="email" type="email" required maxlength="300" autocomplete="email"></label>
<label>Telefon — opțional<input name="phone" maxlength="80" autocomplete="tel"></label>
<label><input type="checkbox" name="privacy_ack" value="true" required> Am citit informarea privind prelucrarea datelor pentru această solicitare.</label>
<label><input type="checkbox" name="marketing_consent" value="true"> Doresc separat comunicări comerciale. Alegerea nu condiționează răspunsul la solicitare.</label>'''
    return f'''<form class="eu-card eu-stack" method="post" action="/api/inbound/sessions" data-eucons-inbound-form data-journey-id="{esc(journey["id"])}" data-form-id="{esc(form_id)}" data-step="{step}"{hidden_attr}>
<input type="hidden" name="session_id" value="">
<input type="hidden" name="request_id" value="">
<input type="hidden" name="submission_age_ms" value="0">
<input type="text" name="website" value="" tabindex="-1" autocomplete="off" aria-hidden="true" hidden>
<h2 class="eu-heading-md">{step_labels[step]}</h2>
{controls}
<button class="eu-button eu-button--primary" type="submit">{"Trimite solicitarea" if step == "CONTACT" else "Continuă"}</button>
<p class="eu-form-status eu-hint" role="status" aria-live="polite"></p>
</form>'''


def render_progressive_journey(builder, data: dict[str, Any], journey: dict[str, Any], form_id: str) -> str:
    forms = "".join([
        progressive_form(journey, form_id, "PROFILE", list(journey.get("first_step_fields") or [])),
        progressive_form(journey, form_id, "CONTEXT", list(journey.get("later_fields") or []), hidden=True),
        progressive_form(journey, form_id, "CONTACT", [], hidden=True),
    ])
    body = f'''<section class="eu-section eu-section--surface"><div class="eu-shell eu-reading eu-stack">
<p class="eu-eyebrow">{esc(journey["eyebrow"])}</p><h1 class="eu-heading-lg">{esc(journey["headline"])}</h1>
<p class="eu-lead">{esc(journey["lead"])}</p>
<div class="eu-alert eu-alert--info" role="note"><strong>Limită:</strong> {esc(journey["boundary"])}</div>
</div></section>
<section class="eu-section"><div class="eu-shell eu-reading eu-stack">
<p class="eu-eyebrow">Evaluare progresivă</p><h2 class="eu-heading-md">Cerem datele în trei pași</h2>
<p>Primești un următor pas preliminar. Acesta nu confirmă eligibilitatea și nu înlocuiește verificarea sursei oficiale și a documentelor.</p>
<div class="eu-progressive-forms" data-eucons-inbound>{forms}</div>
<noscript><p class="eu-alert eu-alert--info">Evaluarea progresivă necesită JavaScript și un endpoint securizat activ. Poți folosi pagina de contact.</p></noscript>
</div></section>'''
    return prod_shell(builder, journey["question"], journey["lead"], journey["path"], body, form_script=True)


def lead_form(form_id: str, heading: str) -> str:
    return f'''<form class="eu-card eu-stack" method="post" action="/api/leads" data-eucons-lead-form>
  <input type="hidden" name="form_id" value="{esc(form_id)}">
  <input type="hidden" name="submission_id" value="">
  <input type="hidden" name="submission_age_ms" value="0">
  <input type="text" name="website" value="" tabindex="-1" autocomplete="off" aria-hidden="true" hidden>
  <h2 class="eu-heading-md">{esc(heading)}</h2>
  <label>Nume și prenume<input name="contact_name" required maxlength="300" autocomplete="name"></label>
  <label>Email<input name="email" type="email" required maxlength="300" autocomplete="email"></label>
  <label>Organizație<input name="organization_name" maxlength="300" autocomplete="organization"></label>
  <label>Telefon<input name="phone" maxlength="80" autocomplete="tel"></label>
  <label>Descrie pe scurt proiectul sau situația<textarea name="message" maxlength="4000" rows="6"></textarea></label>
  <label><input type="checkbox" name="privacy_ack" value="true" required> Am citit informațiile privind prelucrarea datelor pentru această solicitare.</label>
  <label><input type="checkbox" name="marketing_consent" value="true"> Doresc separat să primesc oportunități și comunicări comerciale. Alegerea nu condiționează răspunsul la solicitarea mea.</label>
  <button class="eu-button eu-button--primary" type="submit">Trimite solicitarea</button>
  <p class="eu-hint">Transmiterea devine activă numai după conectarea endpointului securizat al mediului de producție. Motorul respinge câmpurile nepermise și păstrează consimțământul de marketing separat.</p>
</form>'''


def render_lead(builder, title: str, path: str, form_id: str, lead: str) -> str:
    body = (
        f'<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Flux comercial structurat</p>'
        f'<h1 class="eu-heading-lg">{esc(title)}</h1><p class="eu-lead">{esc(lead)}</p>{lead_form(form_id, "Date pentru evaluare")}</div></section>'
    )
    return prod_shell(builder, title, lead, path, body, form_script=True)


def render_contact(builder) -> str:
    body = (
        '<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Contact</p>'
        '<h1 class="eu-heading-lg">Discută cu Euroconsult</h1><p class="eu-lead">Pentru o solicitare comercială, folosește formularul structurat. Canalul de email al companiei este atașat la activarea mediului de producție, fără a introduce credențiale în repository.</p>'
        f'{lead_form("proposal_request", "Solicitare comercială")}</div></section>'
    )
    return prod_shell(builder, "Contact", "Contact comercial Euroconsult și solicitări de consultanță.", "/contact/", body, form_script=True)


def render_about(builder, data: dict[str, Any]) -> str:
    claims = {row.get("id"): row for row in data["evidence"].get("claims", [])}
    identity = claims.get("CLM-COMPANY-LEGAL-IDENTITY-VERIFIED")
    experience = claims.get("CLM-COMPANY-PROJECT-EXPERIENCE-VERIFIED")
    if not identity or identity.get("publication_state") != "PUBLISHABLE":
        raise ValueError("production about page requires verified company identity")
    body = (
        '<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Euroconsult</p>'
        '<h1 class="eu-heading-lg">Consultanță pentru finanțare, implementare și controlul proiectelor</h1>'
        f'<p class="eu-lead">{esc(identity["public_statement"])}</p>'
        f'<article class="eu-card eu-stack"><h2 class="eu-heading-md">Experiență documentată</h2><p class="eu-card__body">{esc(experience["public_statement"] if experience else "Experiența publică este afișată numai după verificare.")}</p></article>'
        '<div class="eu-actions"><a class="eu-button eu-button--primary" href="/echipa/">Cunoaște echipa</a><a class="eu-button eu-button--secondary" href="/proiecte/">Vezi exemple documentate</a></div>'
        '</div></section>'
    )
    return prod_shell(builder, "Despre Euroconsult", "Identitatea și experiența Euroconsult prezentate cu afirmații verificabile.", "/despre/", body)


def render_terms(builder) -> str:
    body = '''<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack">
<p class="eu-eyebrow">Termeni de utilizare</p><h1 class="eu-heading-lg">Condiții pentru utilizarea eucons.ro</h1>
<h2 class="eu-heading-md">Rolul site-ului</h2><p>eucons.ro prezintă serviciile EUROCONSULT SRL, materiale de informare și oportunități de finanțare verificate. Conținutul public nu reprezintă o garanție de eligibilitate, de finanțare sau de rezultat.</p>
<h2 class="eu-heading-md">Relația comercială</h2><p>Transmiterea unei solicitări prin site nu încheie automat un contract. Domeniul serviciilor, livrabilele, termenele și condițiile comerciale devin obligatorii numai prin documentele comerciale sau contractuale acceptate de părți. Sistemul nu publică prețuri numerice fără o regulă comercială aprobată.</p>
<h2 class="eu-heading-md">Finanțări și surse</h2><p>Statutul apelurilor poate evolua. EUCONS publică numai stări admise prin fluxul său de verificare, însă utilizatorul trebuie să consulte documentația oficială aplicabilă înainte de o decizie juridică, financiară sau investițională.</p>
<h2 class="eu-heading-md">Conținut și proveniență</h2><p>Exemplele de proiecte și profilurile profesionale sunt limitate la afirmații susținute de evidențe publicabile. Relațiile cu clienți și testimonialele nu sunt atribuite fără bază documentară și autorizare.</p>
<h2 class="eu-heading-md">Disponibilitate</h2><p>EUROCONSULT poate actualiza conținutul și mecanismele tehnice pentru securitate, acuratețe și conformitate. Erorile identificate sunt corectate prin fluxul de reconciliere și proveniență.</p>
</div></section>'''
    return prod_shell(builder, "Termeni", "Condițiile de utilizare ale site-ului comercial Euroconsult.", "/termeni/", body)


def render_privacy(builder, security: dict[str, Any]) -> str:
    retention = security["retention"]["classes"]
    rows = "".join(
        f'<li><strong>{esc(key)}</strong>: maximum {esc(value["days"])} zile în politica internă curentă, cu acțiunea terminală {esc(value["terminal_action"].lower().replace("_", " "))}.</li>'
        for key, value in retention.items()
    )
    body = f'''<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack">
<p class="eu-eyebrow">Confidențialitate</p><h1 class="eu-heading-lg">Cum tratăm datele transmise prin EUCONS</h1>
<p class="eu-lead">Operatorul pentru solicitările comerciale este EUROCONSULT SRL, CUI 14250864. Politica este construită pe limitarea scopului, minimizarea datelor, limitarea stocării, securitate și responsabilitate.</p>
<h2 class="eu-heading-md">Ce colectăm și de ce</h2><p>Pentru o solicitare inițiată de tine putem prelucra numele, emailul, organizația, telefonul dacă îl oferi, informații despre proiect și metadatele strict necesare transmiterii și trasabilității solicitării. Scopul este răspunsul la evaluare, consultanță, ofertare sau analiză de implementare solicitată de contact.</p>
<h2 class="eu-heading-md">Marketing separat</h2><p>Comunicările promoționale și alertele de oportunități folosesc un consimțământ separat. Bifarea informării de confidențialitate nu înseamnă consimțământ de marketing, iar retragerea trebuie respectată înainte de următoarea comunicare promoțională.</p>
<h2 class="eu-heading-md">Ce nu solicităm</h2><p>Formularele nu sunt destinate datelor din categorii speciale, datelor privind condamnări, documentelor de identitate, credențialelor bancare sau parolelor. Analytics-ul nu trebuie să primească email, telefon, nume, mesaj, adresă IP brută sau URL-uri care conțin date personale.</p>
<h2 class="eu-heading-md">Păstrarea datelor</h2><p>Perioadele de mai jos sunt reguli interne ale operatorului și nu afirmații despre termene impuse uniform de lege. O obligație legală sau contractuală documentată poate impune o păstrare diferită și trebuie revizuită explicit.</p><ul>{rows}</ul>
<h2 class="eu-heading-md">Drepturile tale</h2><p>În condițiile GDPR poți solicita informare și acces, rectificare, ștergere, restricționarea prelucrării, portabilitate și opoziție; pentru marketing te poți opune folosirii datelor în acest scop. Dacă prelucrarea se bazează pe consimțământ, îl poți retrage fără a afecta legalitatea prelucrării anterioare retragerii.</p>
<h2 class="eu-heading-md">Exercitarea drepturilor</h2><p>Cererile se transmit operatorului prin canalul comercial/electronic publicat pe pagina Contact după activarea mediului de producție sau prin datele oficiale de corespondență ale societății. Identitatea solicitantului poate fi verificată proporțional pentru a evita divulgarea datelor către o altă persoană.</p>
<h2 class="eu-heading-md">Securitate și furnizori</h2><p>Credențialele nu sunt stocate în repository. Endpointurile de producție trebuie să folosească HTTPS, politici de securitate ale browserului și loguri cu redactarea câmpurilor sensibile. Orice furnizor activat la găzduire trebuie reflectat în această informare înainte de colectarea reală.</p>
</div></section>'''
    return prod_shell(builder, "Confidențialitate", "Informarea privind prelucrarea datelor prin serviciile comerciale EUCONS.", "/confidentialitate/", body)


def forms_js() -> str:
    return '''"use strict";
(() => {
  const uuid = () => (globalThis.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `eucons-${Date.now()}-${Math.random().toString(36).slice(2)}`;

  for (const form of document.querySelectorAll("form[data-eucons-lead-form]")) {
    const started = Date.now();
    const id = form.querySelector('input[name="submission_id"]');
    const age = form.querySelector('input[name="submission_age_ms"]');
    if (id) id.value = uuid();
    form.addEventListener("submit", () => { if (age) age.value = String(Math.max(0, Date.now() - started)); });
  }

  for (const group of document.querySelectorAll("[data-eucons-inbound]")) {
    const forms = [...group.querySelectorAll("form[data-eucons-inbound-form]")];
    const sessionId = uuid();
    const started = Date.now();
    for (const form of forms) {
      const session = form.querySelector('input[name="session_id"]');
      if (session) session.value = sessionId;
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const status = form.querySelector(".eu-form-status");
        const formData = new FormData(form);
        const requestId = uuid();
        const age = Math.max(0, Date.now() - started);
        const answers = {};
        for (const element of form.elements) {
          if (!element.name || ["session_id", "request_id", "submission_age_ms", "website"].includes(element.name)) continue;
          if (element.type === "checkbox") {
            answers[element.name] = element.checked;
          } else if (element.dataset.euconsList === "true") {
            answers[element.name] = element.value.split(",").map(value => value.trim()).filter(Boolean);
          } else if (element.value !== "") {
            answers[element.name] = element.type === "number" ? Number(element.value) : element.value;
          }
        }
        const payload = {
          session_id: sessionId,
          journey_id: form.dataset.journeyId,
          form_id: form.dataset.formId,
          request: {
            request_id: requestId,
            submission_age_ms: age,
            website: String(formData.get("website") || ""),
            step: form.dataset.step,
            answers,
          },
        };
        if (status) status.textContent = "Se verifică datele…";
        try {
          const response = await fetch(form.action, {
            method: "POST",
            headers: {"Content-Type": "application/json", "Accept": "application/json"},
            credentials: "same-origin",
            body: JSON.stringify(payload),
          });
          if (!response.ok) throw new Error("unavailable");
          const result = await response.json();
          const next = result?.response?.next_stage;
          form.hidden = true;
          const nextForm = forms.find(item => item.dataset.step === next);
          if (nextForm) nextForm.hidden = false;
          if (!nextForm && status) status.textContent = result?.response?.message || "Solicitarea a fost structurată pentru analiză.";
        } catch (_error) {
          if (status) status.textContent = "Transmiterea nu este disponibilă acum. Datele rămân în pagină; încearcă din nou.";
        }
      });
    }
  }
})();
'''


def build_site(target: Path) -> dict[str, Any]:
    builder = load_module("eucons_preview_builder", EUCONS / "web" / "build_public_site.py")
    seo = load_module("eucons_seo", EUCONS / "seo" / "seo_engine.py")
    data = builder.load_contracts()
    security = load_json(EUCONS / "security" / "privacy_security_contract.json")
    target = Path(target)
    pages = builder.build_site(target, data)

    for path in list(pages):
        out = builder.route_file(target, path)
        promoted = promote_html(out.read_text(encoding="utf-8"), path, builder)
        out.write_text(promoted, encoding="utf-8")

    overrides = {
        "/echipa/": render_people(builder, data),
        "/proiecte/": render_cases(builder, data),
        "/finantari/": render_funding(builder),
        "/expertiza/": render_knowledge(builder, data, "ANALYSIS", "/expertiza/", "Expertiză aplicată", "Interpretări operaționale legate de serviciile Euroconsult, separate explicit de faptele administrative despre apeluri."),
        "/ghiduri/": render_knowledge(builder, data, "GUIDE", "/ghiduri/", "Ghiduri pentru beneficiari", "Repere despre livrabile, pași și limite, derivate numai din serviciile comerciale aprobate."),
        "/articole/": render_knowledge(builder, data, "ANALYSIS", "/articole/", "Analize și bune practici", "Conținut orientat spre decizie și implementare, fără transformarea interpretărilor în reguli administrative."),
        "/resurse/": render_knowledge(builder, data, "FAQ", "/resurse/", "Resurse și întrebări utile", "Puncte de control pentru pregătire, implementare, conformitate și remediere."),
        **{
            journey["path"]: render_progressive_journey(
                builder,
                data,
                journey,
                load_json(EUCONS / "leads" / "inbound_runtime_contract.json")["journey_form_map"][journey["id"]],
            )
            for journey in data["ux"].get("journeys", [])
        },
        "/despre/": render_about(builder, data),
        "/evaluare-proiect/": render_lead(builder, "Evaluare proiect", "/evaluare-proiect/", "project_evaluation", "Descrie investiția sau proiectul; motorul de calificare structurează solicitarea și o corelează cu serviciile și oportunitățile verificate."),
        "/solicita-oferta/": render_lead(builder, "Solicită ofertă", "/solicita-oferta/", "proposal_request", "Transmite contextul necesar pentru definirea serviciilor, livrabilelor și condițiilor comerciale. Prețurile nu sunt inventate de sistem."),
        "/contact/": render_contact(builder),
        "/termeni/": render_terms(builder),
        "/confidentialitate/": render_privacy(builder, security),
    }
    for path, content in overrides.items():
        out = builder.route_file(target, path)
        out.write_text(content, encoding="utf-8")
        pages[path] = content

    (target / "assets" / "forms.js").write_text(forms_js(), encoding="utf-8")

    seo_contract = load_json(EUCONS / "seo" / "seo_contract.json")
    projection = seo.build_projection(data["ia"], data["services"], data["evidence"], seo_contract)
    sitemap_rows = "".join(f'<url><loc>{esc(row["loc"])}</loc></url>' for row in projection["sitemap"])
    (target / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + sitemap_rows + '</urlset>\n',
        encoding="utf-8",
    )
    (target / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {CANONICAL_ORIGIN}/sitemap.xml\n", encoding="utf-8")

    return {
        "status": "PASS",
        "mode": "production-ready",
        "pages": len(pages),
        "people": len(builder.publishable_records(data["people"], "people")),
        "cases": len(builder.publishable_records(data["cases"], "cases")),
        "sitemap_entries": len(projection["sitemap"]),
        "production_deployed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(json.dumps(build_site(Path(args.target)), ensure_ascii=False))


if __name__ == "__main__":
    main()
