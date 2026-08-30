<?php
declare(strict_types=1);

// TEST TWIN ONLY — NON-EVIDENCE. Synthetic engineering fixtures only.
require_once dirname(__DIR__) . '/runtime/php/src/ResearchGovernanceGate.php';

function fail_gate_test(string $message): never {
    fwrite(STDERR, $message . PHP_EOL);
    exit(1);
}

function rrmdir_gate(string $dir): void {
    if (!is_dir($dir)) return;
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir_gate($path) : @unlink($path);
    }
    @rmdir($dir);
}

function write_json_gate(string $path, array $value): void {
    file_put_contents($path, json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n");
}

$repoResearchRoot = dirname(__DIR__) . '/research/ai4work-step';
putenv('AI4WORK_RESEARCH_PROD_ENABLED=1');
$repoGate = new EuconsResearchGovernanceGate($repoResearchRoot);
if ($repoGate->productionReady() !== false) fail_gate_test('repository draft governance must remain fail-closed even when env latch is set');

$root = sys_get_temp_dir() . '/ai4work-governance-twin-' . getmypid();
rrmdir_gate($root);
@mkdir($root, 0700, true);

$researchId = 'AI4WORK-STEP-NF-RUN-001';
$requiredKeys = [
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

write_json_gate($root . '/form_contract.json', [
    'research_id' => $researchId,
    'production_enabled' => true,
    'crm_integration' => 'FORBIDDEN',
    'commercial_analytics' => 'FORBIDDEN',
]);
write_json_gate($root . '/CONTROLLER_DETERMINATION_DRAFT.json', [
    'research_id' => $researchId,
    'controller' => ['legal_name' => 'EUROCONSULT SRL'],
    'approved' => true,
    'collection_enabled' => true,
    'nf06_reference_eligible' => true,
    'privacy_contact' => 'privacy@example.invalid',
]);
write_json_gate($root . '/COLLECTION_FRAME_DRAFT.json', [
    'research_id' => $researchId,
    'frame_status' => 'APPROVED_FOR_PROD',
    'collection_enabled' => true,
    'approval' => ['approved' => true, 'approved_for_prod' => true],
    'nf06_handoff' => ['eligible_now' => true],
]);
write_json_gate($root . '/GDPR_DPIA_SCREENING_DRAFT.json', [
    'research_id' => $researchId,
    'approved' => true,
    'collection_enabled' => true,
    'screening_conclusion' => 'DPIA_NOT_REQUIRED_APPROVED',
]);
$article13 = [
    'research_id' => $researchId,
    'evidence_binding_key' => 'privacy_notice',
    'evidence_class' => 'CONTROL_ARTIFACT_NOT_EVIDENCE',
    'synthetic' => false,
    'status' => 'APPROVED_FOR_PROD',
    'approved' => true,
    'collection_enabled' => true,
    'surface_fields' => [
        'operator_legal_name' => 'EUROCONSULT SRL',
        'operator_contact_details' => 'office@example.invalid',
        'privacy_contact' => 'privacy@example.invalid',
        'legal_basis' => 'GDPR Article 6(1)(f) approved legitimate interest',
    ],
    'approval' => [
        'controller_approved' => true,
        'approval_reference' => 'TEST-TWIN-CONTROLLER-APPROVAL',
    ],
];
write_json_gate($root . '/ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json', $article13);

$evidence = [];
foreach ($requiredKeys as $key) {
    if ($key === 'privacy_notice') {
        $path = $root . '/ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json';
        $ref = 'ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json';
    } else {
        $ref = 'EVIDENCE_' . strtoupper($key) . '.json';
        $path = $root . '/' . $ref;
        write_json_gate($path, [
            'research_id' => $researchId,
            'evidence_binding_key' => $key,
            'evidence_class' => 'CONTROL_ARTIFACT_NOT_EVIDENCE',
            'synthetic' => false,
            'status' => 'APPROVED_FOR_TEST_TWIN_GATE_MECHANICS',
        ]);
    }
    $evidence[$key] = [
        'status' => 'APPROVED',
        'reference' => $ref,
        'sha256' => hash_file('sha256', $path),
    ];
}

$manifest = [
    'research_id' => $researchId,
    'state' => 'APPROVED_FOR_PROD',
    'approved_for_prod' => true,
    'collection_enabled' => true,
    'deploy_authorized' => true,
    'real_collection_authorized' => true,
    'activation_mode' => 'PROD_REAL_EVIDENCE_ONLY',
    'test_twin_policy' => 'TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE',
    'explicit_user_approval_reference' => 'TEST-TWIN-USER-APPROVAL',
    'approval_timestamp' => '2026-08-30T20:00:00Z',
    'required_external_or_operational_evidence' => $evidence,
];
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);

$gate = new EuconsResearchGovernanceGate($root);
if ($gate->productionReady() !== true) fail_gate_test('fully satisfied TEST TWIN governance fixture should pass mechanics');

$article13['surface_fields']['privacy_contact'] = 'DE COMPLETAT ÎNAINTE DE ACTIVAREA COLECTĂRII';
write_json_gate($root . '/ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json', $article13);
$manifest['required_external_or_operational_evidence']['privacy_notice']['sha256'] = hash_file('sha256', $root . '/ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json');
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== false) fail_gate_test('placeholder Article 13 privacy contact must fail closed');

$article13['surface_fields']['privacy_contact'] = 'privacy@example.invalid';
write_json_gate($root . '/ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json', $article13);
$manifest['required_external_or_operational_evidence']['privacy_notice']['sha256'] = hash_file('sha256', $root . '/ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json');
$manifest['required_external_or_operational_evidence']['research_only_store_binding']['sha256'] = str_repeat('0', 64);
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== false) fail_gate_test('external evidence hash mismatch must fail closed');

$manifest['required_external_or_operational_evidence']['research_only_store_binding']['sha256'] = hash_file('sha256', $root . '/' . $manifest['required_external_or_operational_evidence']['research_only_store_binding']['reference']);
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
putenv('AI4WORK_RESEARCH_PROD_ENABLED');
if ($gate->productionReady() !== false) fail_gate_test('environment latch must remain required');

rrmdir_gate($root);
echo "AI4WORK PHP governance gate TEST TWIN NON-EVIDENCE: PASS\n";
