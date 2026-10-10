<?php
declare(strict_types=1);

// TEST TWIN ONLY — NON-EVIDENCE. Synthetic production-shaped fixtures; never promotable.
require_once dirname(__DIR__) . '/runtime/php/src/ResearchLiveSafetyGate.php';

function fail_live_safety(string $message): never {
    fwrite(STDERR, $message . PHP_EOL);
    exit(1);
}

function rrmdir_live_safety(string $dir): void {
    if (!is_dir($dir)) return;
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir_live_safety($path) : @unlink($path);
    }
    @rmdir($dir);
}

function write_live_safety(string $path, array $value): void {
    file_put_contents($path, json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n");
}

function is_list_live_safety(array $value): bool {
    return $value === [] || array_keys($value) === range(0, count($value) - 1);
}

function canonicalize_live_safety(mixed $value): mixed {
    if (!is_array($value)) return $value;
    if (is_list_live_safety($value)) return array_map('canonicalize_live_safety', $value);
    ksort($value, SORT_STRING);
    foreach ($value as $key => $child) $value[$key] = canonicalize_live_safety($child);
    return $value;
}

function canonical_sha_live_safety(array $value): string {
    return hash('sha256', json_encode(canonicalize_live_safety($value), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR));
}

$repoRoot = dirname(__DIR__) . '/research/ai4work-step';
$repoGate = new EuconsResearchLiveSafetyGate($repoRoot);
if ($repoGate->productionReady() !== false) {
    fail_live_safety('repository draft live-safety controls must remain fail-closed');
}

$root = sys_get_temp_dir() . '/ai4work-live-safety-twin-' . getmypid();
rrmdir_live_safety($root);
@mkdir($root, 0700, true);
$researchId = 'AI4WORK-STEP-NF-RUN-001';
$now = time();
$verifiedAt = gmdate('Y-m-d\TH:i:s\Z', $now - 60);
$csp = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src https://api.eucons.ro; form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; media-src 'none'";
$headers = [
    'Content-Security-Policy' => $csp,
    'Referrer-Policy' => 'no-referrer',
    'X-Content-Type-Options' => 'nosniff',
    'Permissions-Policy' => 'camera=(), microphone=(), geolocation=()',
    'Cache-Control' => 'no-store, max-age=0',
];
$urls = [
    'https://eucons.ro/cercetare/ai4work-step/',
    'https://eucons.ro/cercetare/ai4work-step/adulti/',
    'https://eucons.ro/cercetare/ai4work-step/angajatori/',
];
$routes = [];
foreach ($urls as $url) {
    $routes[] = ['url' => $url, 'status_code' => 200, 'headers' => $headers];
}
$security = [
    'schema_version' => 'eucons.ai4work_public_surface_security_binding.v0.1',
    'research_id' => $researchId,
    'evidence_class' => 'CONTROL_ARTIFACT_NOT_EVIDENCE',
    'synthetic' => false,
    'status' => 'APPROVED_FOR_PROD',
    'approved_for_prod' => true,
    'collection_enabled' => true,
    'scope' => [
        'public_routes' => $urls,
        'api_route' => 'https://api.eucons.ro/research/ai4work/v1/submit',
    ],
    'live_provider_readback' => [
        'readback_classification' => 'LIVE_PROVIDER_READBACK',
        'provider_account' => 'provider-account-fixture.invalid',
        'verified' => true,
        'verified_at_utc' => $verifiedAt,
        'verified_by' => 'fixture-verifier.invalid',
        'routes' => $routes,
        'readback_sha256' => canonical_sha_live_safety($routes),
    ],
    'test_twin' => [
        'classification' => 'TEST_TWIN_NON_EVIDENCE',
        'synthetic_only' => true,
        'can_satisfy_live_readback' => false,
        'prod_promotion_eligible' => false,
    ],
];
$mandatory = [
    'controller_approval' => true,
    'privacy_contact_bound' => true,
    'incident_owner_assigned' => true,
    'breach_register_location_bound' => true,
    'anspdcp_notification_route_live_verified' => true,
    'processor_escalation_route_bound' => true,
    'restore_and_recovery_control_live_verified' => true,
    'access_and_logging_control_live_verified' => true,
    'provider_breach_notification_contract_path_verified' => true,
];
$incident = [
    'schema_version' => 'eucons.ai4work_gdpr_security_incident_response.v0.1',
    'research_id' => $researchId,
    'evidence_binding_key' => 'security_incident_response_procedure',
    'evidence_class' => 'CONTROL_ARTIFACT_NOT_EVIDENCE',
    'synthetic' => false,
    'status' => 'APPROVED_FOR_PROD',
    'controller_approval' => true,
    'prod_eligible' => true,
    'collection_enabled' => true,
    'privacy_contact' => 'privacy-fixture@example.invalid',
    'incident_owner' => 'ROLE_SECURITY_INCIDENT_OWNER',
    'breach_register_location' => '/protected/fixture/breach-register',
    'anspdcp_notification_route' => 'CONTROLLER_VERIFIED_ROUTE_FIXTURE',
    'processor_escalation_route' => 'PROVIDER_ESCALATION_ROUTE_FIXTURE',
    'mandatory_before_prod' => $mandatory,
    'external_communication_boundary' => ['automatic_external_notification' => false],
    'resume_collection_gate' => ['automatic_resume' => false],
    'security_and_data_minimisation' => [
        'incident_register_separate_from_crm' => true,
        'commercial_tracking_forbidden' => true,
    ],
];
write_live_safety($root . '/PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json', $security);
write_live_safety($root . '/GDPR_SECURITY_INCIDENT_RESPONSE_DRAFT.json', $incident);
$gate = new EuconsResearchLiveSafetyGate($root);
if ($gate->productionReady($now) !== true) {
    fail_live_safety('fully satisfied TEST TWIN live-safety mechanics should pass');
}

$security['live_provider_readback']['verified_at_utc'] = gmdate('Y-m-d\TH:i:s\Z', $now - 90000);
write_live_safety($root . '/PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json', $security);
if ($gate->productionReady($now) !== false) {
    fail_live_safety('stale public security readback must fail closed');
}
$security['live_provider_readback']['verified_at_utc'] = $verifiedAt;
write_live_safety($root . '/PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json', $security);

$incident['mandatory_before_prod']['restore_and_recovery_control_live_verified'] = false;
write_live_safety($root . '/GDPR_SECURITY_INCIDENT_RESPONSE_DRAFT.json', $incident);
if ($gate->productionReady($now) !== false) {
    fail_live_safety('incomplete incident-response live binding must fail closed');
}
$incident['mandatory_before_prod']['restore_and_recovery_control_live_verified'] = true;
write_live_safety($root . '/GDPR_SECURITY_INCIDENT_RESPONSE_DRAFT.json', $incident);

$security['live_provider_readback']['routes'][0]['headers']['Content-Security-Policy'] .= "; script-src 'unsafe-inline'";
$security['live_provider_readback']['readback_sha256'] = canonical_sha_live_safety($security['live_provider_readback']['routes']);
write_live_safety($root . '/PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json', $security);
if ($gate->productionReady($now) !== false) {
    fail_live_safety('weakened CSP must fail closed even when readback SHA is recomputed');
}

rrmdir_live_safety($root);
echo "AI4WORK PHP live safety gate TEST TWIN NON-EVIDENCE: PASS\n";
