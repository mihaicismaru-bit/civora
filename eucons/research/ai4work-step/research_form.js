"use strict";
(() => {
  const CHANNEL_RE = /^CH-[A-Z0-9]{8,32}$/;
  const retryState = new WeakMap();

  const uuidv4 = () => {
    if (!globalThis.crypto || typeof crypto.randomUUID !== "function") {
      throw new Error("SECURE_UUID_UNAVAILABLE");
    }
    return crypto.randomUUID();
  };

  const statusText = (form, message) => {
    const node = form.querySelector("[data-ai4work-status]");
    if (node) node.textContent = message;
  };

  const recruitmentChannel = (() => {
    // Recruitment metadata arrives only in the URL fragment. Fragments are not
    // sent in the HTTP request, but leaving the channel token visible in the
    // address bar/history would retain more recruitment metadata than needed.
    // Capture it once in ephemeral JS memory, then scrub navigation metadata
    // without introducing any persistent browser-side state.
    const fragment = String(globalThis.location.hash || "").replace(/^#/, "");
    const params = new URLSearchParams(fragment);
    const value = params.get("channel") || "";
    if (params.has("channel")
        && globalThis.history
        && typeof globalThis.history.replaceState === "function") {
      globalThis.history.replaceState(null, "", globalThis.location.pathname);
    }
    return CHANNEL_RE.test(value) ? value : null;
  })();

  const channelId = () => recruitmentChannel;

  const selectedValue = (node) => {
    const type = node.dataset.questionType;
    if (type === "select") {
      const select = node.querySelector("select");
      return select && select.value !== "" ? select.value : undefined;
    }
    if (type === "multi") {
      return [...node.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value);
    }
    if (type === "rating_matrix") {
      const result = {};
      for (const row of node.querySelectorAll("[data-matrix-row]")) {
        const checked = row.querySelector('input[type="radio"]:checked');
        if (!checked) return undefined;
        result[row.dataset.matrixRow] = Number(checked.value);
      }
      return result;
    }
    const checked = node.querySelector('input[type="radio"]:checked');
    if (!checked) return undefined;
    if (type === "rating") return Number(checked.value);
    if (type === "boolean") return checked.value === "true";
    return checked.value;
  };

  const dependencyValue = (form, fieldId) => {
    const question = form.querySelector(`[data-question-id="${CSS.escape(fieldId)}"]`);
    if (question) return selectedValue(question);
    const profile = form.querySelector(`[data-profile-field="${CSS.escape(fieldId)}"]`);
    return profile ? profile.value : undefined;
  };

  const applyDependencies = (form) => {
    for (const node of form.querySelectorAll("[data-depends-field]")) {
      const expected = node.dataset.dependsValue;
      const actual = dependencyValue(form, node.dataset.dependsField);
      const actualToken = typeof actual === "boolean" ? String(actual) : String(actual ?? "");
      const active = actualToken === expected;
      node.hidden = !active;
      for (const control of node.querySelectorAll("input, select, textarea")) {
        control.disabled = !active || form.dataset.collectionEnabled !== "true";
      }
    }
  };

  const payloadFromForm = (form) => {
    const profile = {};
    for (const select of form.querySelectorAll("select[data-profile-field]")) {
      if (!select.disabled && select.value !== "") profile[select.dataset.profileField] = select.value;
    }
    const answers = {};
    for (const node of form.querySelectorAll("[data-question-id]")) {
      if (node.hidden) continue;
      const value = selectedValue(node);
      if (value !== undefined) answers[node.dataset.questionId] = value;
    }
    return {
      form_id: form.dataset.formId,
      notice_read_and_voluntary_participation: form.querySelector('[name="notice_read_and_voluntary_participation"]')?.checked === true,
      profile,
      answers,
    };
  };

  const submit = async (form) => {
    if (form.dataset.collectionEnabled !== "true") {
      statusText(form, "Colectarea nu este activată.");
      return;
    }
    applyDependencies(form);
    if (!form.reportValidity()) return;

    const channel = channelId();
    if (!channel) {
      statusText(form, "Acest link de cercetare nu are un cod de distribuire valid. Folosiți linkul primit pentru participare.");
      return;
    }

    try {
      const payload = payloadFromForm(form);
      const body = JSON.stringify(payload);
      const previous = retryState.get(form);
      const idempotencyKey = previous && previous.body === body ? previous.key : uuidv4();
      retryState.set(form, {body, key: idempotencyKey});
      statusText(form, "Se transmite răspunsul…");

      const response = await fetch(form.dataset.endpoint, {
        method: "POST",
        mode: "cors",
        credentials: "omit",
        cache: "no-store",
        referrerPolicy: "no-referrer",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
          "X-AI4WORK-Idempotency-Key": idempotencyKey,
          "X-AI4WORK-Recruitment-Channel": channel,
        },
        body,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.accepted !== true) {
        if (result.code === "RESEARCH_COLLECTION_DISABLED") {
          statusText(form, "Colectarea nu este activată.");
        } else {
          statusText(form, "Răspunsul nu a fost acceptat. Verificați câmpurile și încercați din nou.");
        }
        return;
      }

      retryState.delete(form);
      for (const control of form.querySelectorAll("input, select, button")) control.disabled = true;
      const receipt = form.querySelector("[data-ai4work-receipt]");
      if (receipt) {
        receipt.hidden = false;
        receipt.textContent = `Răspuns înregistrat. Păstrați acest cod opac dacă doriți să formulați ulterior o cerere privind răspunsul: ${result.response_id}`;
      }
      statusText(form, "Răspunsul a fost înregistrat.");
    } catch (_error) {
      statusText(form, "Transmiterea nu este disponibilă acum. Datele rămân numai în această pagină; încercați din nou.");
    }
  };

  for (const form of document.querySelectorAll("form[data-ai4work-research-form]")) {
    applyDependencies(form);
    form.addEventListener("change", () => applyDependencies(form));
    const button = form.querySelector("[data-ai4work-submit]");
    if (button) button.addEventListener("click", () => submit(form));
  }
})();
