import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  discoverArtifacts,
  planAcquisition,
  sanitizeUrl
} from "../core/artifact-discovery.mjs";
import {
  normalizeDownloadObservation,
  normalizeResponseMetadata
} from "../core/observation.mjs";
import { assertNoSensitivePersistence } from "../core/policy.mjs";

async function fixture(name) {
  return JSON.parse(await readFile(new URL(`../fixtures/${name}`, import.meta.url), "utf8"));
}

test("310224 inventories every exposed target and prefers observation over unsafe controls", async () => {
  const input = await fixture("310224-failed-direct-get.json");
  const inventory = discoverArtifacts(input);
  const plan = planAcquisition(inventory);

  assert.equal(inventory.project.code, "310224");
  assert.equal(inventory.candidates.length, 10);
  assert.equal(inventory.counts.ROUTE_METADATA_ONLY, 7);
  assert.equal(inventory.counts.UI_READONLY_DOWNLOAD_OBSERVE, 1);
  assert.equal(inventory.counts.BLOCKED_WRITE_CONTROL, 2);
  assert.equal(inventory.invariants.writeActionsPerformed, 0);
  assert.equal(plan.next.strategy, "UI_READONLY_DOWNLOAD_OBSERVE");
  assert.equal(plan.next.label, "Descarcă formular");
  assert.equal(plan.next.automatedActionAllowed, false);
  assert.deepEqual(plan.blocked.map((candidate) => candidate.label).sort(), ["Salvează", "Șterge"]);
});

test("367944 maps schema routes but cannot invent a generated export", async () => {
  const input = await fixture("367944-schema-discovery.json");
  const inventory = discoverArtifacts(input);
  const plan = planAcquisition(inventory);

  assert.equal(inventory.project.code, "367944");
  assert.equal(inventory.counts.ROUTE_METADATA_ONLY, 8);
  assert.equal(inventory.counts.BLOCKED_WRITE_CONTROL, 1);
  assert.equal(inventory.counts.BLOCKED_UNSAFE_METHOD, 1);
  assert.ok(plan.selected.every((candidate) => candidate.strategy === "ROUTE_METADATA_ONLY"));
  assert.equal(plan.selected.some((candidate) => candidate.strategy === "DIRECT_URL_SAFE_GET"), false);
  assert.equal(inventory.invariants.controlsClicked, 0);
});

test("least-invasive strategy ranks direct binary before UI observation and route metadata", () => {
  const input = {
    page: { url: "https://mysmis2021.gov.ro/project/example" },
    elements: [
      { tag: "a", text: "Contract PDF", href: "/files/contract.pdf?token=secret&version=2", download: true },
      { tag: "button", text: "Descarcă formular" },
      { tag: "a", text: "Raport", href: "/reports/1" }
    ]
  };
  const plan = planAcquisition(discoverArtifacts(input));
  assert.equal(plan.next.strategy, "DIRECT_URL_SAFE_GET");
  assert.equal(plan.next.url.includes("token="), false);
  assert.equal(plan.next.url.includes("version=2"), true);
});

test("POST download is blocked unless separately proven read-only", () => {
  const common = {
    page: { url: "https://mysmis2021.gov.ro/project/example" }
  };
  const blocked = discoverArtifacts({
    ...common,
    elements: [{ tag: "form", text: "Export raport", action: "/export", method: "POST" }]
  });
  assert.equal(blocked.candidates[0].strategy, "BLOCKED_UNSAFE_METHOD");

  const approved = discoverArtifacts({
    ...common,
    elements: [{ tag: "form", text: "Export raport", action: "/export", method: "POST", approvedReadOnly: true }]
  });
  assert.equal(approved.candidates[0].strategy, "ROUTE_METADATA_ONLY");
  assert.equal(approved.candidates[0].automatedActionAllowed, false);
});

test("URL and observation normalization never persists auth material", () => {
  const sanitized = sanitizeUrl(
    "https://mysmis2021.gov.ro/file.pdf?token=secret&state=x&version=4",
    "https://mysmis2021.gov.ro/"
  );
  assert.equal(sanitized, "https://mysmis2021.gov.ro/file.pdf?version=4");

  const response = normalizeResponseMetadata({
    requestId: "r-1",
    method: "GET",
    statusCode: 200,
    url: "https://mysmis2021.gov.ro/file.pdf?auth=secret",
    type: "xmlhttprequest",
    responseHeaders: [
      { name: "content-type", value: "application/pdf" },
      { name: "content-length", value: "1234" },
      { name: "set-cookie", value: "never-persist-this" }
    ],
    requestHeaders: [{ name: "Authorization", value: "Bearer never-persist-this" }]
  });
  assert.equal(response.url, "https://mysmis2021.gov.ro/file.pdf");
  assert.equal(JSON.stringify(response).includes("never-persist-this"), false);
  assert.equal(response.contentLength, 1234);
  assertNoSensitivePersistence(response);

  const download = normalizeDownloadObservation({
    id: 7,
    finalUrl: "blob:https://mysmis2021.gov.ro/123#fragment",
    filename: "report.pdf",
    mime: "application/pdf",
    totalBytes: 100
  });
  assert.equal(download.url, "blob:https://mysmis2021.gov.ro/123");
});
