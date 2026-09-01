<?php
declare(strict_types=1);

// TEST TWIN ONLY — NON-EVIDENCE. Synthetic engineering fixtures only.
require_once dirname(__DIR__) . '/runtime/php/src/ResearchRuntime.php';
require_once dirname(__DIR__) . '/runtime/php/src/ResearchPersistedBundleExport.php';

function fail_bundle_test(string $message): never {
    fwrite(STDERR, $message . PHP_EOL);
    exit(1);
}

function rrmdir_bundle(string $dir): void {
    if (!is_dir($dir)) return;
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir_bundle($path) : @unlink($path);
    }
    @rmdir($dir);
}

function write_bundle_json(string $path, array $value): void {
    @mkdir(dirname($path), 0700, true);
    file_put_contents($path, json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n");
}

function canonical_bundle_value(mixed $value): mixed {
    if (!is_array($value)) return $value;
    $isList = $value === [] || array_keys($value) === range(0, count($value) - 1);
    if ($isList) return array_map('canonical_bundle_value', $value);
    ksort($value, SORT_STRING);
    foreach ($value as $key => $child) $value[$key] = canonical_bundle_value($child);
    return $value;
}

function canonical_bundle_json(array $value, bool $newline = false): string {
    $json = json_encode(
        canonical_bundle_value($value),
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR
    );
    return $json . ($newline ? "\n" : '');
}

function synthetic_bundle_fixture(string $responseId, string $formId, string $receivedAt): array {
    $rawSha = hash('sha256', 'TEST-TWIN-RAW-' . $responseId);
    $bodySha = hash('sha256', 'TEST-TWIN-BODY-' . $responseId);
    $record = [
        'schema_version' => 1,
        'research_id' => 'AI4WORK-STEP-NF-RUN-001',
        'form_id' => $formId,
        'form_version' => 1,
        'response_id' => $responseId,
        'received_at' => $receivedAt,
        'recruitment_channel_id' => 'CH-TESTTWIN01',
        'profile' => ['region' => 'Centru'],
        'answers' => [],
        'synthetic' => false,
    ];
    $normalizedSha = hash('sha256', canonical_bundle_json($record, true));
    return [
        'wrapper' => [
            'schema_version' => 1,
            'received_at' => $receivedAt,
            'raw_sha256' => $rawSha,
            'normalized_sha256' => $normalizedSha,
            'record' => $record,
        ],
        'receipt' => [
            'schema_version' => 1,
            'response_id' => $responseId,
            'form_id' => $formId,
            'accepted_at' => $receivedAt,
            'body_sha256' => $bodySha,
            'normalized_sha256' => $normalizedSha,
            'raw_sha256' => $rawSha,
            'pii_in_receipt' => false,
        ],
    ];
}

$root = sys_get_temp_dir() . '/ai4work-bundle-export-twin-' . getmypid();
rrmdir_bundle($root);
@mkdir($root . '/public', 0700, true);
putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/research');
putenv('EUCONS_DATA_ROOT=' . $root . '/commercial');
$_SERVER['DOCUMENT_ROOT'] = $root . '/public';

$runtime = new EuconsResearchRuntime(dirname(__DIR__));
$exporter = new EuconsResearchPersistedBundleExport($runtime);

$adultId = str_repeat('a', 64);
$employerId = str_repeat('b', 64);
$heldId = str_repeat('c', 64);
$adult = synthetic_bundle_fixture($adultId, 'AI4WORK_ADULTS_V1', '2026-08-30T20:00:00Z');
$employer = synthetic_bundle_fixture($employerId, 'AI4WORK_EMPLOYERS_V1', '2026-08-30T20:01:00Z');
$held = synthetic_bundle_fixture($heldId, 'AI4WORK_ADULTS_V1', '2026-08-30T20:02:00Z');
foreach ([[$adultId, 'AI4WORK_ADULTS_V1', $adult], [$employerId, 'AI4WORK_EMPLOYERS_V1', $employer], [$heldId, 'AI4WORK_ADULTS_V1', $held]] as [$id, $formId, $fixture]) {
    write_bundle_json($root . '/research/responses/' . $formId . '/' . $id . '.json', $fixture['wrapper']);
    write_bundle_json($root . '/research/receipts/' . $id . '.json', $fixture['receipt']);
}
write_bundle_json($root . '/research/holds/' . $heldId . '.json', [
    'schema_version' => 1,
    'response_id' => $heldId,
    'hold_state' => 'RESTRICTED_PENDING_REVIEW',
]);

$bundles = $exporter->buildPersistedBundles();
if (count($bundles) !== 2) fail_bundle_test('held response leaked into persisted bundle export');
if ($bundles[0]['filename_response_id'] !== $adultId || $bundles[1]['filename_response_id'] !== $employerId) {
    fail_bundle_test('persisted bundles are not deterministically sorted by form/time/response id');
}
foreach ($bundles as $bundle) {
    if (settype($bundle['wrapper'], 'array') === false || settype($bundle['receipt'], 'array') === false) {
        fail_bundle_test('bundle shape invalid');
    }
    if (($bundle['wrapper']['record']['synthetic'] ?? null) !== false) fail_bundle_test('exporter accepted synthetic=true');
}

@unlink($root . '/research/receipts/' . $employerId . '.json');
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('missing receipt did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_RECEIPT_MISSING') fail_bundle_test('unexpected missing-receipt error: ' . $e->getMessage());
}
write_bundle_json($root . '/research/receipts/' . $employerId . '.json', $employer['receipt']);

@unlink($root . '/research/receipts/' . $heldId . '.json');
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('held response missing receipt did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_RECEIPT_MISSING') fail_bundle_test('unexpected held missing-receipt error: ' . $e->getMessage());
}
write_bundle_json($root . '/research/receipts/' . $heldId . '.json', $held['receipt']);

$orphanId = str_repeat('d', 64);
$orphan = synthetic_bundle_fixture($orphanId, 'AI4WORK_ADULTS_V1', '2026-08-30T20:03:00Z');
write_bundle_json($root . '/research/receipts/' . $orphanId . '.json', $orphan['receipt']);
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('orphan acceptance receipt did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_ORPHAN_RECEIPT') fail_bundle_test('unexpected orphan-receipt error: ' . $e->getMessage());
}
@unlink($root . '/research/receipts/' . $orphanId . '.json');

$invalidHold = [
    'schema_version' => 1,
    'response_id' => $heldId,
    'hold_state' => 'UNBOUNDED_HOLD',
];
write_bundle_json($root . '/research/holds/' . $heldId . '.json', $invalidHold);
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('invalid rights-hold artifact did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_HOLD_ARTIFACT_INVALID') fail_bundle_test('unexpected invalid-hold error: ' . $e->getMessage());
}
write_bundle_json($root . '/research/holds/' . $heldId . '.json', [
    'schema_version' => 1,
    'response_id' => $heldId,
    'hold_state' => 'RESTRICTED_PENDING_REVIEW',
]);

$orphanHoldId = str_repeat('e', 64);
write_bundle_json($root . '/research/holds/' . $orphanHoldId . '.json', [
    'schema_version' => 1,
    'response_id' => $orphanHoldId,
    'hold_state' => 'OBJECTED_PENDING_REVIEW',
]);
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('orphan rights-hold artifact did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_ORPHAN_HOLD') fail_bundle_test('unexpected orphan-hold error: ' . $e->getMessage());
}
@unlink($root . '/research/holds/' . $orphanHoldId . '.json');

$badHeldReceipt = $held['receipt'];
$badHeldReceipt['normalized_sha256'] = str_repeat('0', 64);
write_bundle_json($root . '/research/receipts/' . $heldId . '.json', $badHeldReceipt);
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('held response with corrupt receipt did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_HASH_BINDING_MISMATCH') fail_bundle_test('unexpected held-receipt error: ' . $e->getMessage());
}
write_bundle_json($root . '/research/receipts/' . $heldId . '.json', $held['receipt']);

$badReceipt = $employer['receipt'];
$badReceipt['normalized_sha256'] = str_repeat('0', 64);
write_bundle_json($root . '/research/receipts/' . $employerId . '.json', $badReceipt);
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('hash-binding mismatch did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_HASH_BINDING_MISMATCH') fail_bundle_test('unexpected hash-binding error: ' . $e->getMessage());
}
write_bundle_json($root . '/research/receipts/' . $employerId . '.json', $employer['receipt']);

$tamperedWrapper = $employer['wrapper'];
$tamperedWrapper['record']['answers'] = ['tampered' => true];
write_bundle_json($root . '/research/responses/AI4WORK_EMPLOYERS_V1/' . $employerId . '.json', $tamperedWrapper);
try {
    $exporter->buildPersistedBundles();
    fail_bundle_test('normalized record tamper did not fail closed');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'RESEARCH_EXPORT_NORMALIZED_HASH_MISMATCH') fail_bundle_test('unexpected normalized-hash error: ' . $e->getMessage());
}

putenv('AI4WORK_RESEARCH_ROOT');
putenv('EUCONS_DATA_ROOT');
rrmdir_bundle($root);
echo "AI4WORK persisted-bundle export TEST TWIN NON-EVIDENCE: PASS\n";
