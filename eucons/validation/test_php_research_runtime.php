<?php
declare(strict_types=1);

// TEST TWIN ONLY — NON-EVIDENCE. Uses only temporary synthetic engineering fixtures.
require_once dirname(__DIR__) . '/runtime/php/src/ResearchRuntime.php';

function fail_test(string $message): never {
    fwrite(STDERR, $message . PHP_EOL);
    exit(1);
}

function expect_exception(callable $fn, string $expected): void {
    try {
        $fn();
    } catch (InvalidArgumentException|RuntimeException $e) {
        if ($e->getMessage() !== $expected) {
            fail_test("expected {$expected}, got {$e->getMessage()}");
        }
        return;
    }
    fail_test("expected exception {$expected}");
}

function rrmdir(string $dir): void {
    if (!is_dir($dir)) return;
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir($path) : @unlink($path);
    }
    @rmdir($dir);
}

function adult_payload(): array {
    return [
        'form_id' => 'AI4WORK_ADULTS_V1',
        'notice_read_and_voluntary_participation' => true,
        'profile' => [
            'region' => 'Sud-Vest Oltenia',
            'status' => 'persoană ocupată potențial eligibilă',
            'age_band' => '40-49',
            'occupational_family' => 'administrativ/back-office',
        ],
        'answers' => [
            'Q01' => 3,
            'Q02' => 2,
            'Q03' => 3,
            'Q04' => 3,
            'Q05' => 4,
            'Q06' => 2,
            'Q07' => false,
            'Q08' => ['lipsa timpului'],
            'Q09' => ['nu am folosit AI'],
            'Q10' => [
                'utilizare_digitala_functionala' => 3,
                'utilizarea_instrumentelor_AI' => 4,
                'verificarea_rezultatelor_AI' => 4,
                'protectia_datelor_confidentialitate' => 4,
                'integrarea_AI_in_flux_de_lucru' => 5,
            ],
            'Q11' => 'productivitate/calitate mai bună',
            'Q12' => ['redactare și documente'],
        ],
    ];
}

function employer_payload(): array {
    return [
        'form_id' => 'AI4WORK_EMPLOYERS_V1',
        'notice_read_and_voluntary_participation' => true,
        'profile' => [
            'region' => 'Centru',
            'sector_aggregated' => 'servicii profesionale/tehnice',
            'size_band' => '10-49',
            'respondent_role' => 'management',
        ],
        'answers' => [
            'E01' => 'pilot/test',
            'E02' => ['redactare/comunicare'],
            'E03' => [
                'formularea_cerintelor' => 4,
                'verificarea_calitatii' => 4,
                'protectia_datelor' => 5,
                'limitele_si_riscurile_AI' => 4,
                'integrarea_in_procese' => 4,
                'definirea_fluxului_asistat_AI' => 4,
                'competente_digitale_generale' => 3,
            ],
            'E04' => 'nu',
            'E05' => 'nu',
            'E06' => ['timp disponibil'],
            'E07' => 'moderat',
            'E08' => ['verificarea factuală/calității', 'protecția datelor'],
            'E09' => ['redactare și documente'],
            'E10' => 'posibil',
        ],
    ];
}

$root = sys_get_temp_dir() . '/ai4work-research-twin-' . getmypid();
rrmdir($root);
@mkdir($root . '/public', 0700, true);
putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/research');
putenv('EUCONS_DATA_ROOT=' . $root . '/commercial');
putenv('AI4WORK_RESEARCH_PROD_ENABLED=1'); // final manifest + contract latch must still block PROD.
$_SERVER['DOCUMENT_ROOT'] = $root . '/public';

$runtime = new EuconsResearchRuntime(dirname(__DIR__));
if ($runtime->productionEnabled() !== false) fail_test('PROD must remain disabled without approved manifest/contract');
$runtimeSource = file_get_contents(dirname(__DIR__) . '/runtime/php/src/ResearchRuntime.php');
if ($runtimeSource === false) fail_test('ResearchRuntime.php unavailable for activation-scope regression check');
if (str_contains($runtimeSource, "deploy_authorized'] ?? false) === true")) fail_test('collection latch must not require deploy authority');
if (!str_contains($runtimeSource, "deploy_authorized'] ?? null) === false")) fail_test('collection latch must fail closed unless deploy authority remains false');
if (!$runtime->allowedOrigin('https://eucons.ro') || $runtime->allowedOrigin('https://example.invalid')) fail_test('origin policy drift');
if ($runtime->storageRoot() !== $root . '/research') fail_test('research root drift');

$payload = adult_payload();
$key = '123e4567-e89b-42d3-a456-426614174000';
$channel = 'CH-TESTTWIN01';
$raw = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
$prepared = $runtime->validateSubmission($payload, $key, $channel);
$receipt = $runtime->persist($prepared, $raw);
if ($receipt['status'] !== 'accepted' || $receipt['inserted'] !== true) fail_test('initial research persistence failed');
if (!preg_match('/^[0-9a-f]{64}$/', $receipt['response_id'])) fail_test('response_id is not opaque sha256');

$replay = $runtime->persist($runtime->validateSubmission($payload, $key, $channel), $raw);
if ($replay['inserted'] !== false || $replay['response_id'] !== $receipt['response_id']) fail_test('idempotent replay failed');

$changed = $payload;
$changed['answers']['Q01'] = 4;
$changedRaw = json_encode($changed, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
expect_exception(
    fn() => $runtime->persist($runtime->validateSubmission($changed, $key, $channel), $changedRaw),
    'IDEMPOTENCY_CONFLICT'
);

$forbidden = $payload;
$forbidden['profile']['email'] = 'synthetic@example.invalid';
expect_exception(fn() => $runtime->validateSubmission($forbidden, $key, $channel), 'FORBIDDEN_DIRECT_IDENTIFIER_FIELD');
$stringBoolean = $payload;
$stringBoolean['answers']['Q07'] = 'nu';
expect_exception(fn() => $runtime->validateSubmission($stringBoolean, $key, $channel), 'BOOLEAN_EXPECTED');

if (!$runtime->setAnalysisHold($receipt['response_id'], 'RESTRICTED_PENDING_REVIEW')) fail_test('hold set failed');
if (count($runtime->exportForm('AI4WORK_ADULTS_V1')) !== 0) fail_test('held row leaked into export');
if (!$runtime->clearAnalysisHold($receipt['response_id'])) fail_test('hold clear failed');
if (count($runtime->exportForm('AI4WORK_ADULTS_V1')) !== 1) fail_test('unheld row missing from export');

$receiptPath = $root . '/research/receipts/' . $receipt['response_id'] . '.json';
$storedReceipt = json_decode(file_get_contents($receiptPath), true, 512, JSON_THROW_ON_ERROR);
foreach (['profile', 'answers', 'idempotency_key', 'email', 'name', 'ip', 'user_agent'] as $forbiddenField) {
    if (array_key_exists($forbiddenField, $storedReceipt)) fail_test('forbidden data leaked into receipt: ' . $forbiddenField);
}

if (!$runtime->deleteByResponseId($receipt['response_id'])) fail_test('erasure failed');
if ($runtime->getByResponseId($receipt['response_id']) !== null) fail_test('erased row still readable');
expect_exception(fn() => $runtime->persist($prepared, $raw), 'ERASED_RESPONSE_REPLAY_BLOCKED');
$markerPath = $root . '/research/erased/' . $receipt['response_id'] . '.json';
$marker = json_decode(file_get_contents($markerPath), true, 512, JSON_THROW_ON_ERROR);
$allowedMarkerKeys = ['schema_version', 'response_id', 'expires_at_utc'];
$keys = array_keys($marker); sort($keys); sort($allowedMarkerKeys);
if ($keys !== $allowedMarkerKeys) fail_test('replay marker contains unexpected fields');
$delta = strtotime($marker['expires_at_utc']) - time();
if ($delta < 86390 || $delta > 86400) fail_test('replay marker expiry is not bounded to 24h');

$employer = employer_payload();
$employerKey = '223e4567-e89b-42d3-a456-426614174001';
$employerRaw = json_encode($employer, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
$employerReceipt = $runtime->persist($runtime->validateSubmission($employer, $employerKey, 'CH-TESTTWIN02'), $employerRaw);
if ($employerReceipt['inserted'] !== true || count($runtime->exportForm('AI4WORK_EMPLOYERS_V1')) !== 1) fail_test('employer form path failed');

putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/commercial/research');
expect_exception(fn() => $runtime->storageRoot(), 'RESEARCH_STORAGE_NOT_SEPARATE_FROM_COMMERCIAL');
putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/public/research');
expect_exception(fn() => $runtime->storageRoot(), 'RESEARCH_STORAGE_INSIDE_WEBROOT');

putenv('AI4WORK_RESEARCH_ROOT');
putenv('EUCONS_DATA_ROOT');
putenv('AI4WORK_RESEARCH_PROD_ENABLED');
rrmdir($root);
echo "AI4WORK PHP research TEST TWIN NON-EVIDENCE: PASS\n";
