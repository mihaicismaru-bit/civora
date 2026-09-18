# CYBERSTEP creation pilot — 0.2.0 — 18 September 2026

## Observed baseline and scope

The 0.1.1 inspector was installed by the operator and produced a live structural
capture: one text input named `nume`, two input comboboxes, and an `Adaugă` submit
button. The operator screenshot confirms the selected applicant CPP and call
PEO/1160/PEO_P11/OP4/ESO4.7/PEO_A66. It shows a blank title, no created project.
Opera's earlier observation did not match that screenshot. Do not promote it over
the operator's current screen. The creation-form wrapper hierarchy is not captured;
0.2.0 discovers it conservatively and rejects ambiguous layouts at runtime.

The fixed working title is CYBERSTEP. The fixed applicant is FUNDAȚIA CENTRUL DE
PREGĂTIRE PROFESIONALĂ VÂLCEA. This is a local, operator-triggered pilot for creating
one draft. It does not submit the funding application, sign, upload attachments,
change the applicant/call, or implement a generic remote write API. The read-only
bridge HEALTH/DISCOVER_ARTIFACTS dispatch and its policy remain unchanged.

## Operator steps

1. Extract the new package. Copy the **contents of its PAYLOAD** into the same
   PAYLOAD directory used by the installed 0.1.1 extension, replacing matching files.
   In opera://extensions press Reload on that extension. Do not load a second copy.
   Verify version 0.2.0. The same path/extension identity retains the attempt lock.
2. Reload the MySMIS tab once to replace the old content script. Reopen “Adaugă
   proiect”, select CPP and the exact PEO/1160 call, close the dropdown. The title
   may be blank or exactly CYBERSTEP. Do not press MySMIS “Adaugă” manually.
3. Open the extension popup and press **Pregătește CYBERSTEP**. This may write only
   the title. Review the displayed fixed applicant, call and title. No creation has
   occurred. If preparation returns an error, stop and report its exact code.
4. Check the full project list for an existing CYBERSTEP under the same applicant
   and call. If already checked before opening the form, attest that in the checkbox.
   The extension's automatic duplicate check covers visible rows only; the operator
   check is required for other pages and rows hidden by the modal. If you must leave
   the form to check, return and prepare again; preparation expires after 2 minutes.
5. Press **Creează ciorna CYBERSTEP** once. The background stores a durable attempt
   lock before dispatch. The content script revalidates origin, form identities,
   selected applicant/call, title, enabled button and visible duplicates, then invokes
   the observed submit button once. A changed or unsupported form is rejected.
6. Inspect the MySMIS result. In the same tab open the project list and use
   **Citește rezultatul din lista de proiecte**. Download the JSON result. A six-digit
   code next to the exact title is only a candidate: verify applicant and call inside
   the resulting project before recording full acceptance.

After any dispatch attempt, do not click MySMIS Adaugă manually, reinstall another
copy, clear extension storage, or use another device to retry. The lock is local to
this extension installation; it cannot prevent manual writes or another installation.
An uncertain response remains locked. There is intentionally no automatic reset.
Investigate the project list before any separately reviewed recovery.

## Binding and privacy

No generated React IDs are hardcoded. The title selector and submit metadata come
from the captured form. Labels and selected context are checked in a bounded parent
scope with exactly three visible fields and one submit action. Unsupported label or
wrapper variations stop before submission. No private DOM runtime/framework state,
network endpoints, credentials, cookies, site storage or tokens are inspected.
Only the fixed project identity and local attempt status enter the downloadable receipt.

The popup communicates with its own service worker. The worker serializes requests,
binds the active tab/URL, and persists a single attempt before sending the commit.
Only that extension's background context may invoke page mutations. Sender URL is
optional in the platform API, so service-worker messages without it are admitted
only with the same extension ID and no sending tab. See the official
[MessageSender contract](https://developer.chrome.com/docs/extensions/reference/api/runtime#type-MessageSender).

## Verification and remaining acceptance

Fourteen new synthetic tests cover fixed identity mismatch, title preservation,
layout change, duplicate detection, disabled submit, expiration, navigation, sender
restriction, concurrent commits, restart, storage failure and lost responses. They
exercise an explicit synthetic DOM adapter and Chrome API doubles, not the live site.
The full local suite passes 233/233; the MV3 static compatibility gate passes.
No live 0.2.0 installation, actual creation, or code/applicant/call readback has yet
been observed. Status: **WRITER_IMPLEMENTED_LOCAL_TESTS_PASS_LIVE_ACCEPTANCE_PENDING**.
The public source contains no uploaded screenshot or real capture JSON.
