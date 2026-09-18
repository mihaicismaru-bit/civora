const $ = id => document.getElementById(id);
const prepare = $("prepare"), create = $("create"), check = $("duplicate-check"), readback = $("readback");
const status = $("writer-status"), preview = $("writer-preview"), download = $("writer-download");
let token = null, report = null, locked = false, busy = false, known = false;
function controls() {
  prepare.disabled = busy || locked || !known;
  check.disabled = busy || locked || !token;
  create.disabled = busy || locked || !token || !check.checked;
  readback.disabled = busy || !locked;
}
function show(result) {
  report = result;
  preview.textContent = JSON.stringify(result, null, 2);
  preview.hidden = false;
  download.disabled = false;
}
async function call(type, extra = {}) {
  const reply = await chrome.runtime.sendMessage({ type, ...extra });
  if (!reply?.ok) throw new Error(reply?.error || "CYBERSTEP_UNAVAILABLE");
  return reply.result;
}
function errorText(error) {
  return /^CYBERSTEP_[A-Z_]+$/u.test(error?.message) ? error.message : "CYBERSTEP_UNAVAILABLE";
}
async function refreshStatus() {
  const result = await call("CYBERSTEP_STATUS");
  known = true;
  locked = Boolean(result.attempt);
  if (locked) {
    show(result);
    status.textContent = "Există o încercare înregistrată. Verifică proiectul și codul SMIS în MySMIS. Crearea nu poate fi repetată din extensie.";
  }
}
prepare.addEventListener("click", async () => {
  busy = true; token = null; check.checked = false; controls();
  status.textContent = "Verific formularul și pregătesc titlul…";
  try {
    const result = await call("CYBERSTEP_PREPARE");
    token = result.token; show(result);
    status.textContent = "Formular pregătit. Proiectul nu este creat. Verifică datele afișate și confirmă verificarea duplicatelor înainte de creare (valabil 2 minute).";
  } catch (error) { status.textContent = `Pregătire oprită: ${errorText(error)}. Nu a fost apăsat Adaugă.`; }
  finally { busy = false; controls(); }
});
check.addEventListener("change", controls);
create.addEventListener("click", async () => {
  if (!token || !check.checked || locked || busy) return;
  busy = true; controls();
  status.textContent = "Trimit o singură cerere de creare…";
  try {
    const result = await call("CYBERSTEP_CREATE", { token, fullListChecked: true });
    locked = true; show(result);
    status.textContent = "Încercare înregistrată. Verifică rezultatul în MySMIS, apoi citește lista de proiecte. Un cod observat trebuie verificat împreună cu solicitantul și apelul.";
  } catch (error) {
    known = false;
    status.textContent = `Rezultat neconfirmat: ${errorText(error)}. Nu repeta crearea înainte de verificarea listei MySMIS.`;
    try { await refreshStatus(); } catch { /* Leave creation disabled until durable state can be read. */ }
  } finally { token = null; busy = false; controls(); }
});
readback.addEventListener("click", async () => {
  busy = true; controls();
  try {
    const result = await call("CYBERSTEP_READBACK"); show(result);
    const code = result.attempt?.observation?.smisCode;
    status.textContent = code ? `Cod candidat observat: ${code}. Trimite rezultatul testului; solicitantul și apelul trebuie verificate în proiect.` : "Rezultat încă neconfirmat. Deschide lista de proiecte în aceeași filă și verifică CYBERSTEP. Nu repeta crearea.";
  } catch (error) { status.textContent = `Citire oprită: ${errorText(error)}. Crearea rămâne blocată.`; }
  finally { busy = false; controls(); }
});
download.addEventListener("click", () => {
  if (!report) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify({ extensionVersion: chrome.runtime.getManifest().version, report }, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "CYBERSTEP_CREATE_PILOT_RESULT.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
controls();
refreshStatus().then(() => { if (!locked) status.textContent = "Pregătit pentru pilot. Apasă Pregătește CYBERSTEP."; })
  .catch(error => { status.textContent = `Stare indisponibilă: ${errorText(error)}. Crearea este dezactivată.`; }).finally(controls);
