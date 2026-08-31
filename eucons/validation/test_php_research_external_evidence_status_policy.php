<?php
declare(strict_types=1);

// TEST TWIN ONLY — NON-EVIDENCE. Synthetic engineering fixtures only.
require_once dirname(__DIR__) . '/runtime/php/src/ResearchGovernanceGate.php';

function fail_external_status_test(string $message): never {
    fwrite(STDERR, $message . PHP_EOL);
    exit(1);
}

function rrmdir_external_status(string $dir): void {
    if (!is_dir($dir)) return;
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir_external_status($path) : @unlink($path);
    }
    @rmdir($dir);
}

$root = sys_get_temp_dir() . '/ai4work-external-status-twin-' . getmypid();
rrmdir_external_status($root);
@mkdir($root, 0700, true);

$researchId = 'AI4WORK-STEP-NF-RUN-001';
$keys = [
    'privacy_notice',
    'lawful_basis_or_lia',
    'processor_chain',
    'provider_account_role_reconciliation',
    'live_hosting_service_mapping',
    'live_public_privacy_surface_reconciliation',
    'provider_annex_4_5',
    'provider_server_logging_profile',
    'account_server_logging_binding',
    'retention_and_deletion',
    'data_subject_rights_procedure',
    'dpia_screening_or_completed_dpia',
    'research_only_store_binding',
    'provider_bound_test_twin_smoke',
];
$documentary = [
    'provider_account_role_reconciliation',
    'live_hosting_service_mapping',
    'provider_annex_4_5',
    'provider_server_logging_profile',
];

$evidence = [];
foreach ($keys as $key) {
    $reference = 'EVIDENCE_' . strtoupper($key) . '.json';
    $path = $root . '/' . $reference;
    file_put_contents($path, json_encode([
        'research_id' => $researchId,
        'evidence_binding_key' => $key,
        'evidence_class' => 'CONTROL_ARTIFACT_NOT_EVIDENCE',
        'synthetic' => false,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n");
    $evidence[$key] = [
        'status' => in_array($key, $documentary, true) ? 'FROZEN' : 'APPROVED',
        'reference' => $reference,
        'sha256' => hash_file('sha256', $path),
    ];
}

$manifest = ['required_external_or_operational_evidence' => $evidence];
$gate = new EuconsResearchGovernanceGate($root);
$externalReady = Closure::bind(
    function (array $candidate): bool { return $this->externalEvidenceReady($candidate); },
    $gate,
    EuconsResearchGovernanceGate::class
);
if (!$externalReady instanceof Closure) fail_external_status_test('private external-evidence test binding failed');

if ($externalReady($manifest) !== true) {
    fail_external_status_test('approved operational + frozen documentary baseline should pass external-evidence mechanics');
}

$manifest['required_external_or_operational_evidence']['research_only_store_binding']['status'] = 'FROZEN';
if ($externalReady($manifest) !== false) {
    fail_external_status_test('live research-only store may not satisfy PROD with FROZEN documentary-only status');
}
$manifest['required_external_or_operational_evidence']['research_only_store_binding']['status'] = 'APPROVED';

$manifest['required_external_or_operational_evidence']['live_public_privacy_surface_reconciliation']['status'] = 'FROZEN';
if ($externalReady($manifest) !== false) {
    fail_external_status_test('live public privacy reconciliation may not satisfy PROD with FROZEN status');
}
$manifest['required_external_or_operational_evidence']['live_public_privacy_surface_reconciliation']['status'] = 'APPROVED';

$manifest['required_external_or_operational_evidence']['provider_annex_4_5']['status'] = 'FROZEN';
if ($externalReady($manifest) !== true) {
    fail_external_status_test('immutable provider documentary binding must remain eligible as FROZEN');
}

rrmdir_external_status($root);
echo "AI4WORK PHP external evidence status policy TEST TWIN NON-EVIDENCE: PASS\n";
