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

function write_test_register(array $entries): string
{
    $path = tempnam(sys_get_temp_dir(), 'ai4work-channel-test-');
    if ($path === false) {
        throw new RuntimeException('unable to create TEST TWIN register');
    }
    $register = [
        'schema_version' => 'eucons.ai4work_collection_channel_register.v0.1',
        'research_id' => 'AI4WORK-STEP-NF-RUN-001',
        'entries' => $entries,
    ];
    file_put_contents($path, json_encode($register, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));
    return $path;
}

$entry = [
    'channel_id' => 'CH-TESTTWIN01',
    'channel_type' => 'test_twin',
    'region_scope' => ['Centru'],
    'audience_scope' => ['adults'],
    'invitation_version' => 'TEST_TWIN_NON_EVIDENCE_V1',
    'opened_at' => '2026-08-30T00:00:00+00:00',
    'closed_at' => '2026-08-31T00:00:00+00:00',
    'distributor_role' => 'TEST_TWIN_ONLY_NON_EVIDENCE',
    'non_coercion_confirmed' => true,
];
$path = write_test_register([$entry]);

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

    $emptyPath = write_test_register([]);
    try {
        $emptyGate = new EuconsResearchChannelGate($emptyPath);
        expect_channel_error(fn() => $emptyGate->assertApprovedRecord($validRecord, $now), 'RECRUITMENT_CHANNEL_NOT_APPROVED');
    } finally {
        @unlink($emptyPath);
    }

    $badEntry = $entry;
    $badEntry['non_coercion_confirmed'] = false;
    $badPath = write_test_register([$badEntry]);
    try {
        expect_channel_error(fn() => new EuconsResearchChannelGate($badPath), 'COLLECTION_CHANNEL_REGISTER_INVALID');
    } finally {
        @unlink($badPath);
    }
} finally {
    @unlink($path);
}

echo "PASS TEST_TWIN_NON_EVIDENCE research channel gate\n";
