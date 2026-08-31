<?php
declare(strict_types=1);

// TEST TWIN ONLY — NON-EVIDENCE. This fixture never represents a real respondent,
// distributor, recruitment channel, or collection event.
require_once dirname(__DIR__) . '/runtime/php/src/ResearchChannelGate.php';

function expect_channel_error(callable $fn, string $expected): void
{
    try {
        $fn();
    } catch (Throwable $e) {
        if ($e->getMessage() === $expected) {
            return;
        }
        throw new RuntimeException('unexpected channel-gate error: ' . $e->getMessage());
    }
    throw new RuntimeException('expected channel-gate error not raised: ' . $expected);
}

function rrmdir_channel(string $dir): void
{
    if (!is_dir($dir)) return;
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir_channel($path) : @unlink($path);
    }
    @rmdir($dir);
}

function write_json_channel(string $path, array $value): void
{
    file_put_contents(
        $path,
        json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n"
    );
}

function approved_catalog_channel(): array
{
    $safeguards = [
        'voluntary_participation' => true,
        'no_disadvantage' => true,
        'no_project_enrolment_condition' => true,
        'no_commercial_marketing' => true,
        'no_direct_identifier_request' => true,
        'no_incentive_condition' => true,
        'privacy_notice_before_form' => true,
        'one_response_request' => true,
    ];
    return [
        'schema_version' => 'eucons.ai4work_research_invitation_catalog.v0.1',
        'research_id' => 'AI4WORK-STEP-NF-RUN-001',
        'status' => 'APPROVED_FOR_PROD',
        'evidence_class' => 'CONTROL_ARTIFACT_NOT_EVIDENCE',
        'approved_for_prod' => true,
        'purpose' => 'TEST TWIN only — validate exact invitation binding mechanics without real dissemination.',
        'entries' => [
            [
                'invitation_version' => 'TEST_TWIN_ADULTS_INV_V1',
                'audience_scope' => ['adults'],
                'invitation_text' => str_repeat('Neutral TEST TWIN invitation text only. ', 5),
                'required_safeguards' => $safeguards,
            ],
            [
                'invitation_version' => 'TEST_TWIN_EMPLOYERS_INV_V1',
                'audience_scope' => ['employers'],
                'invitation_text' => str_repeat('Neutral TEST TWIN employer invitation text only. ', 5),
                'required_safeguards' => $safeguards,
            ],
        ],
        'transport_policy' => [
            'channel_identifier_mode' => 'OPAQUE_URL_FRAGMENT_ONLY',
            'channel_identifier_format' => 'CH-[A-Z0-9]{8,32}',
            'query_tracking_parameters_allowed' => false,
            'commercial_tracking_allowed' => false,
            'crm_identifier_allowed' => false,
            'referrer_derived_channel_allowed' => false,
        ],
        'approval' => [
            'approved_for_prod' => true,
            'approver_name_or_role' => 'TEST_TWIN_MECHANICS_ONLY',
            'approval_date' => '2026-08-31T17:00:00Z',
            'notes' => 'Synthetic engineering approval marker only; NON-EVIDENCE.',
        ],
        'test_twin_policy' => 'TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE',
        'merge_authorized' => false,
        'deploy_authorized' => false,
        'real_dissemination_authorized' => false,
    ];
}

function write_test_register(array $entries): array
{
    $root = sys_get_temp_dir() . '/ai4work-channel-test-' . bin2hex(random_bytes(6));
    if (!@mkdir($root, 0700, true) && !is_dir($root)) {
        throw new RuntimeException('unable to create TEST TWIN register directory');
    }
    $catalogPath = $root . '/RESEARCH_INVITATION_CATALOG_DRAFT.json';
    write_json_channel($catalogPath, approved_catalog_channel());
    $registerPath = $root . '/COLLECTION_CHANNEL_REGISTER_DRAFT.json';
    $register = [
        'schema_version' => 'eucons.ai4work_collection_channel_register.v0.2',
        'research_id' => 'AI4WORK-STEP-NF-RUN-001',
        'invitation_catalog' => [
            'reference' => 'RESEARCH_INVITATION_CATALOG_DRAFT.json',
            'sha256' => hash_file('sha256', $catalogPath),
        ],
        'entries' => $entries,
    ];
    write_json_channel($registerPath, $register);
    return [$root, $registerPath, $catalogPath];
}

$entry = [
    'channel_id' => 'CH-TESTTWIN01',
    'channel_type' => 'test_twin',
    'region_scope' => ['Centru'],
    'audience_scope' => ['adults'],
    'invitation_version' => 'TEST_TWIN_ADULTS_INV_V1',
    'opened_at' => '2026-08-30T00:00:00+00:00',
    'closed_at' => '2026-08-31T00:00:00+00:00',
    'distributor_role' => 'TEST_TWIN_ONLY_NON_EVIDENCE',
    'non_coercion_confirmed' => true,
];
[$root, $path, $catalogPath] = write_test_register([$entry]);

try {
    $gate = new EuconsResearchChannelGate($path);
    $validRecord = [
        'research_id' => 'AI4WORK-STEP-NF-RUN-001',
        'form_id' => 'AI4WORK_ADULTS_V1',
        'recruitment_channel_id' => 'CH-TESTTWIN01',
        'profile' => ['region' => 'Centru'],
    ];
    $now = new DateTimeImmutable('2026-08-30T12:00:00+00:00');
    $gate->assertApprovedRecord($validRecord, $now);

    $unknown = $validRecord;
    $unknown['recruitment_channel_id'] = 'CH-UNKNOWN01';
    expect_channel_error(fn() => $gate->assertApprovedRecord($unknown, $now), 'RECRUITMENT_CHANNEL_NOT_APPROVED');

    $wrongAudience = $validRecord;
    $wrongAudience['form_id'] = 'AI4WORK_EMPLOYERS_V1';
    expect_channel_error(fn() => $gate->assertApprovedRecord($wrongAudience, $now), 'RECRUITMENT_CHANNEL_AUDIENCE_MISMATCH');

    $wrongRegion = $validRecord;
    $wrongRegion['profile']['region'] = 'Sud-Muntenia';
    expect_channel_error(fn() => $gate->assertApprovedRecord($wrongRegion, $now), 'RECRUITMENT_CHANNEL_REGION_MISMATCH');

    $outside = new DateTimeImmutable('2026-09-01T00:00:00+00:00');
    expect_channel_error(fn() => $gate->assertApprovedRecord($validRecord, $outside), 'RECRUITMENT_CHANNEL_OUTSIDE_APPROVED_WINDOW');

    [$emptyRoot, $emptyPath] = write_test_register([]);
    try {
        $emptyGate = new EuconsResearchChannelGate($emptyPath);
        expect_channel_error(fn() => $emptyGate->assertApprovedRecord($validRecord, $now), 'RECRUITMENT_CHANNEL_NOT_APPROVED');
    } finally {
        rrmdir_channel($emptyRoot);
    }

    $badEntry = $entry;
    $badEntry['non_coercion_confirmed'] = false;
    [$badRoot, $badPath] = write_test_register([$badEntry]);
    try {
        expect_channel_error(fn() => new EuconsResearchChannelGate($badPath), 'COLLECTION_CHANNEL_REGISTER_INVALID');
    } finally {
        rrmdir_channel($badRoot);
    }

    $badInvitation = $entry;
    $badInvitation['invitation_version'] = 'TEST_TWIN_EMPLOYERS_INV_V1';
    [$audienceRoot, $audiencePath] = write_test_register([$badInvitation]);
    try {
        expect_channel_error(fn() => new EuconsResearchChannelGate($audiencePath), 'COLLECTION_CHANNEL_INVITATION_AUDIENCE_MISMATCH');
    } finally {
        rrmdir_channel($audienceRoot);
    }

    file_put_contents($catalogPath, "\n", FILE_APPEND);
    expect_channel_error(fn() => new EuconsResearchChannelGate($path), 'COLLECTION_CHANNEL_INVITATION_CATALOG_MISMATCH');
} finally {
    rrmdir_channel($root);
}

echo "PASS TEST_TWIN_NON_EVIDENCE research channel gate v0.2 invitation binding\n";
