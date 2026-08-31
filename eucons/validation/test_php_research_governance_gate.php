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

function is_list_gate(array $value): bool {
    if ($value === []) return true;
    return array_keys($value) === range(0, count($value) - 1);
}

function canonicalize_gate(mixed $value): mixed {
    if (!is_array($value)) return $value;
    if (is_list_gate($value)) return array_map('canonicalize_gate', $value);
    ksort($value, SORT_STRING);
    foreach ($value as $key => $child) $value[$key] = canonicalize_gate($child);
    return $value;
}

function canonical_sha_gate(array $value): string {
    return hash('sha256', json_encode(canonicalize_gate($value), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR));
}

$repoResearchRoot = dirname(__DIR__) . '/research/ai4work-step';
putenv('AI4WORK_RESEARCH_PROD_ENABLED=1');
$repoGate = new EuconsResearchGovernanceGate($repoResearchRoot);
if ($repoGate->productionReady() !== false) fail_gate_test('repository draft governance must remain fail-closed even when env latch is set');

$root = sys_get_temp_dir() . '/ai4work-governance-twin-' . getmypid();
rrmdir_gate($root);
@mkdir($root, 0700, true);

$researchId = 'AI4WORK-STEP-NF-RUN-001';
$frameId = 'AI4WORK-STEP-PROD-FRAME-TEST-TWIN-001';
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
write_json_gate($root . '/RESEARCH_INVITATION_CATALOG_DRAFT.json', [
    'research_id' => $researchId,
    'fixture_class' => 'TEST_TWIN_NON_EVIDENCE',
    'purpose' => 'scope-binding mechanics only',
]);
write_json_gate($root . '/COLLECTION_CHANNEL_REGISTER_DRAFT.json', [
    'research_id' => $researchId,
    'fixture_class' => 'TEST_TWIN_NON_EVIDENCE',
    'purpose' => 'scope-binding mechanics only',
]);
write_json_gate($root . '/CONTROLLER_DETERMINATION_DRAFT.json', [
    'research_id' => $researchId,
    'controller' => ['legal_name' => 'EUROCONSULT SRL'],
    'approved' => true,
    'collection_enabled' => true,
    'nf06_reference_eligible' => true,
    'privacy_contact' => 'privacy@example.invalid',
]);
$frame = [
    'research_id' => $researchId,
    'collection_frame_id' => $frameId,
    'frame_status' => 'APPROVED_FOR_PROD',
    'collection_enabled' => true,
    'approval' => ['approved' => true, 'approved_for_prod' => true],
    'nf06_handoff' => ['eligible_now' => true],
];
write_json_gate($root . '/COLLECTION_FRAME_DRAFT.json', $frame);
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

$plan = [
    'schema_version' => 'eucons.ai4work_need_analysis_plan.v0.2',
    'research_id' => $researchId,
    'collection_frame_id' => $frameId,
    'status' => 'APPROVED_FOR_PROD',
    'evidence_class' => 'METHOD_PLAN_NOT_EVIDENCE',
    'core_skill_ranking' => [
        'respondent_weighting_allowed' => false,
        'secondary_evidence_can_change_numeric_order' => false,
        'missing_direct_indicator_imputation_allowed' => false,
        'representativeness_claim_allowed' => false,
        'causal_claim_allowed' => false,
    ],
    'approval' => [
        'approved' => true,
        'approved_for_prod' => true,
        'approved_at' => '2026-08-30T19:00:00Z',
        'approver_reference' => 'TEST-TWIN-METHOD-APPROVAL',
    ],
    'synthetic_records_allowed' => false,
    'test_twin_evidence_class' => 'TEST_TWIN_NON_EVIDENCE',
    'project_activity_as_need_evidence' => false,
    'merge_authorized' => false,
    'deploy_authorized' => false,
    'prod_activation_authorized' => false,
];
write_json_gate($root . '/NEED_ANALYSIS_PLAN_DRAFT.json', $plan);
$planLock = [
    'schema_version' => 'eucons.ai4work_precollection_analysis_plan_lock.v0.2',
    'research_id' => $researchId,
    'collection_frame_id' => $frameId,
    'state' => 'LOCKED_BEFORE_PROD_ACTIVATION',
    'evidence_class' => 'METHOD_CONTROL_NOT_EVIDENCE',
    'purpose' => 'TEST TWIN dual method immutability mechanics only.',
    'need_analysis_plan_reference' => 'NEED_ANALYSIS_PLAN_DRAFT.json',
    'need_analysis_plan_sha256' => canonical_sha_gate($plan),
    'collection_frame_reference' => 'COLLECTION_FRAME_DRAFT.json',
    'collection_frame_sha256' => canonical_sha_gate($frame),
    'approved_at' => '2026-08-30T19:30:00Z',
    'approver_reference' => 'TEST-TWIN-METHOD-LOCK-APPROVAL',
    'activation_boundary' => 'DUAL_METHOD_LOCK_REQUIRED_BEFORE_ANY_PROD_COLLECTION_ENABLEMENT',
    'method_mutation_after_lock' => 'FORBIDDEN_WHILE_COLLECTION_OR_PROD_ACTIVATION_IS_ENABLED',
    'post_hoc_threshold_exception' => 'FORBIDDEN',
    'amendment_rule' => 'TEST TWIN fixture: any material amendment requires collection disabled and a new dual lock.',
    'synthetic_or_test_twin_can_satisfy_lock' => false,
    'project_activity_as_need_evidence' => false,
    'secondary_evidence_can_change_numeric_order' => false,
    'merge_authorized' => false,
    'deploy_authorized' => false,
    'prod_activation_authorized' => false,
];
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);

$approvalReceipt = [
    'schema_version' => 'eucons.ai4work_explicit_user_approval_receipt.v0.1',
    'research_id' => $researchId,
    'status' => 'APPROVED',
    'artifact_class' => 'CONTROL_ARTIFACT_NOT_EVIDENCE',
    'test_fixture_class' => 'TEST_TWIN_NON_EVIDENCE',
    'synthetic' => false,
    'approval_source' => 'HUMAN_EXPLICIT_USER_APPROVAL',
    'authorized_action' => 'REAL_COLLECTION_PROD_ACTIVATION_ONLY',
    'approved' => true,
    'approved_at' => '2026-08-30T20:00:00Z',
    'approved_by_user_reference' => 'TEST-TWIN-OPAQUE-USER-APPROVAL-NON-EVIDENCE',
    'real_collection_authorized' => true,
    'merge_authorized' => false,
    'deploy_authorized' => false,
    'canonicalization_authorized' => false,
    'bound_artifacts' => [
        'need_analysis_plan' => [
            'reference' => 'NEED_ANALYSIS_PLAN_DRAFT.json',
            'sha256' => hash_file('sha256', $root . '/NEED_ANALYSIS_PLAN_DRAFT.json'),
        ],
        'collection_frame' => [
            'reference' => 'COLLECTION_FRAME_DRAFT.json',
            'sha256' => hash_file('sha256', $root . '/COLLECTION_FRAME_DRAFT.json'),
        ],
        'form_contract' => [
            'reference' => 'form_contract.json',
            'sha256' => hash_file('sha256', $root . '/form_contract.json'),
        ],
        'invitation_catalog' => [
            'reference' => 'RESEARCH_INVITATION_CATALOG_DRAFT.json',
            'sha256' => hash_file('sha256', $root . '/RESEARCH_INVITATION_CATALOG_DRAFT.json'),
        ],
        'collection_channel_register' => [
            'reference' => 'COLLECTION_CHANNEL_REGISTER_DRAFT.json',
            'sha256' => hash_file('sha256', $root . '/COLLECTION_CHANNEL_REGISTER_DRAFT.json'),
        ],
    ],
    'test_twin_policy' => 'TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE',
    'evidence_use' => 'CONTROL_ONLY_NOT_NEED_EVIDENCE',
];
write_json_gate($root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json', $approvalReceipt);

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
    'schema_version' => 'eucons.ai4work_prod_activation_manifest.v0.9',
    'research_id' => $researchId,
    'state' => 'APPROVED_FOR_PROD',
    'approved_for_prod' => true,
    'collection_enabled' => true,
    'merge_authorized' => false,
    'deploy_authorized' => false,
    'canonicalization_authorized' => false,
    'real_collection_authorized' => true,
    'activation_mode' => 'PROD_REAL_EVIDENCE_ONLY',
    'test_twin_policy' => 'TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE',
    'explicit_user_approval_reference' => 'EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json',
    'explicit_user_approval_sha256' => hash_file('sha256', $root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json'),
    'approval_timestamp' => '2026-08-30T20:00:00Z',
    'required_external_or_operational_evidence' => $evidence,
];
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);

$gate = new EuconsResearchGovernanceGate($root);
if ($gate->productionReady() !== true) fail_gate_test('fully satisfied TEST TWIN governance fixture should pass mechanics');

$manifest['explicit_user_approval_sha256'] = str_repeat('0', 64);
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== false) fail_gate_test('unbound explicit user approval receipt must fail closed');
$manifest['explicit_user_approval_sha256'] = hash_file('sha256', $root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json');
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== true) fail_gate_test('restored explicit user approval hash should pass mechanics');

$approvalReceipt['deploy_authorized'] = true;
write_json_gate($root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json', $approvalReceipt);
$manifest['explicit_user_approval_sha256'] = hash_file('sha256', $root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json');
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== false) fail_gate_test('collection approval may not escalate to deploy authority');
$approvalReceipt['deploy_authorized'] = false;
write_json_gate($root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json', $approvalReceipt);
$manifest['explicit_user_approval_sha256'] = hash_file('sha256', $root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json');
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== true) fail_gate_test('restored collection-only user approval should pass mechanics');

$approvalReceipt['approved_at'] = '2999-01-01T00:00:00Z';
write_json_gate($root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json', $approvalReceipt);
$manifest['explicit_user_approval_sha256'] = hash_file('sha256', $root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json');
$manifest['approval_timestamp'] = '2999-01-01T00:00:00Z';
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== false) fail_gate_test('future-dated explicit user approval must fail closed');
$approvalReceipt['approved_at'] = '2026-08-30T20:00:00Z';
write_json_gate($root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json', $approvalReceipt);
$manifest['explicit_user_approval_sha256'] = hash_file('sha256', $root . '/EXPLICIT_USER_APPROVAL_RECEIPT_DRAFT.json');
$manifest['approval_timestamp'] = '2026-08-30T20:00:00Z';
write_json_gate($root . '/PROD_ACTIVATION_MANIFEST_DRAFT.json', $manifest);
if ($gate->productionReady() !== true) fail_gate_test('restored non-future explicit user approval should pass mechanics');

$planLock['state'] = 'OPEN_NOT_LOCKED';
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== false) fail_gate_test('open dual method lock must fail closed at live governance gate');
$planLock['state'] = 'LOCKED_BEFORE_PROD_ACTIVATION';
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== true) fail_gate_test('restored dual method lock should pass mechanics');

$plan['core_skill_ranking']['secondary_evidence_can_change_numeric_order'] = true;
write_json_gate($root . '/NEED_ANALYSIS_PLAN_DRAFT.json', $plan);
$planLock['need_analysis_plan_sha256'] = canonical_sha_gate($plan);
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== false) fail_gate_test('method plan allowing secondary evidence to change rank must fail closed');
$plan['core_skill_ranking']['secondary_evidence_can_change_numeric_order'] = false;
write_json_gate($root . '/NEED_ANALYSIS_PLAN_DRAFT.json', $plan);
$planLock['need_analysis_plan_sha256'] = canonical_sha_gate($plan);
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== true) fail_gate_test('restored deterministic plan lock should pass mechanics');

$planLock['need_analysis_plan_sha256'] = str_repeat('0', 64);
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== false) fail_gate_test('analysis-plan lock hash mismatch must fail closed');
$planLock['need_analysis_plan_sha256'] = canonical_sha_gate($plan);
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== true) fail_gate_test('restored plan hash must pass mechanics');

$frame['approval']['approved_for_prod'] = false;
write_json_gate($root . '/COLLECTION_FRAME_DRAFT.json', $frame);
if ($gate->productionReady() !== false) fail_gate_test('collection-frame drift after lock must fail closed');
$frame['approval']['approved_for_prod'] = true;
write_json_gate($root . '/COLLECTION_FRAME_DRAFT.json', $frame);
if ($gate->productionReady() !== true) fail_gate_test('restored collection frame must pass mechanics');

$planLock['collection_frame_sha256'] = str_repeat('0', 64);
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== false) fail_gate_test('collection-frame lock hash mismatch must fail closed');
$planLock['collection_frame_sha256'] = canonical_sha_gate($frame);
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== true) fail_gate_test('restored collection-frame hash must pass mechanics');

$planLock['post_hoc_threshold_exception'] = 'ALLOWED';
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== false) fail_gate_test('post-hoc threshold exception must fail closed');
$planLock['post_hoc_threshold_exception'] = 'FORBIDDEN';
write_json_gate($root . '/PRECOLLECTION_ANALYSIS_PLAN_LOCK_DRAFT.json', $planLock);
if ($gate->productionReady() !== true) fail_gate_test('restored no-exception dual lock must pass mechanics');

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
echo "AI4WORK PHP governance + dual method-lock + explicit user approval gate TEST TWIN NON-EVIDENCE: PASS\n";
