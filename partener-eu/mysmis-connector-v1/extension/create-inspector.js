import { inspectActiveCreateForm } from "./create-inspector-client.mjs";

const inspect = document.getElementById("inspect");
const download = document.getElementById("download");
const status = document.getElementById("status");
const preview = document.getElementById("preview");
let snapshot = null;
let exportedUrl = null;

inspect.addEventListener("click", async () => {
  inspect.disabled = true;
  download.disabled = true;
  snapshot = null;
  preview.hidden = true;
  status.textContent = "Citesc structura din fila activă…";
  try {
    snapshot = await inspectActiveCreateForm(chrome, crypto.randomUUID());
    preview.textContent = JSON.stringify(snapshot, null, 2);
    preview.hidden = false;
    download.disabled = false;
    status.textContent = snapshot.fields.length
      ? `Citite ${snapshot.fields.length} câmpuri și ${snapshot.controls.length} controale. Crearea nu a fost executată.`
      : "Pagina nu conține câmpuri vizibile. Deschide formularul de creare și repetă citirea.";
  } catch (error) {
    const code = /^CREATE_CAPTURE_[A-Z_]+$/u.test(error?.message) ? error.message : "CREATE_CAPTURE_UNAVAILABLE";
    status.textContent = `Citire oprită (${code}). Verifică fila MySMIS și reîncarc-o dacă ai actualizat extensia.`;
  } finally { inspect.disabled = false; }
});

download.addEventListener("click", () => {
  if (!snapshot) return;
  if (exportedUrl) URL.revokeObjectURL(exportedUrl);
  exportedUrl = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = exportedUrl;
  link.download = "MYSMIS_CREATE_FORM_STRUCTURE.json";
  link.click();
});
