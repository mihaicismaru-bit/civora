# CYBERSTEP creation pilot — 18 September 2026

## What this increment does

The recovered baseline is PR #976 at dd9c30c4ca83cee145f88ef40a6245f9754569db.
It dispatches HEALTH and DISCOVER_ARTIFACTS only. It has no create-project operation.
The listed LIST_PROJECTS capability is not a dispatchable project-list command.
Its existing HEALTH heuristic needs a six-digit project code; it is not evidence of
an authenticated pre-creation screen. This increment makes no new auth claim.

The new extension popup reads the visible form structure in exactly the active tab
and main frame. It works without a project code or the loopback runtime. It provides
an explicit JSON download for field identifiers, labels, required/disabled flags and
length limits. It does not inspect values, hidden fields, option lists or page bodies.
It rejects sign-in pages, mismatched responses and navigation during the capture.

This is the missing observation step for implementing a bounded draft writer. It is
**not** a draft writer and does not claim CYBERSTEP has been created. Existing bridge
operations and their restrictions remain unchanged. The same extension package is
extended; no second connector, remote shell or credential access is introduced.

## Observed live boundary

Opera exposes read/navigation functions, no click/fill/create. In this session it can
navigate to MySMIS `/home`, which redirects to the sign-in page. Cloud Browser was
rejected by MySMIS in the preceding test; no further cloud retry is needed.
There is no authenticated creation-form snapshot and no installed version receipt
for the updated extension yet. All automated tests use explicitly synthetic fixtures.

## Operator steps, in Romanian

1. În Opera, autentifică-te în fila MySMIS deschisă. Parola și codurile se introduc
   doar în MySMIS, nu în conversație.
2. Selectează CPP și deschide formularul de proiect nou pe apelul potrivit. Lasă
   formularul deschis; această versiune nu îl completează și nu creează proiectul.
3. Încarcă versiunea actualizată a extensiei din directorul PAYLOAD al pachetului
   verificat, folosind funcția Load unpacked / Încarcă extensia neîmpachetată din
   pagina de extensii. Dacă folosești deja această extensie, păstrează copia veche
   pentru revenire și încarcă noua copie o singură dată. Nu configura loopback-ul
   pentru această captură; configurarea veche rămâne legată de vechiul build.
4. Reîncarcă fila MySMIS după instalare, redeschide formularul dacă este necesar,
   apoi apasă pictograma extensiei și «Citește formularul din fila activă».
5. Verifică previzualizarea, apasă «Descarcă structura pentru verificare» și adaugă
   MYSMIS_CREATE_FORM_STRUCTURE.json în conversație.

## Next implementation gate

Use the actual capture to bind the title, applicant and call fields and the exact
create action. Confirm the available call and applicant context from the visible UI.
The writer must check for a duplicate before execution, perform at most one creation
attempt and treat a lost response as uncertain until the project list is reread.
Success requires the resulting SMIS code and matching title/applicant/call readback.
Do not infer selectors, create endpoints or field limits from synthetic tests.

User authorization to create CYBERSTEP is already recorded in the conversation.
The remaining blocker is access and observed schema, not a missing generic approval.
