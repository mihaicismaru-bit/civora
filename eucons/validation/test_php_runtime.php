<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/runtime/php/src/LeadRuntime.php';

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
    $items = scandir($dir) ?: [];
    foreach ($items as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir($path) : @unlink($path);
    }
    @rmdir($dir);
}

$root = sys_get_temp_dir() . '/eucons-php-runtime-' . getmypid();
rrmdir($root);
putenv('EUCONS_DATA_ROOT=' . $root . '/data');
$_SERVER['DOCUMENT_ROOT'] = $root . '/public';
$runtime = new EuconsLeadRuntime(dirname(__DIR__));

$payload = [
    'form_id' => 'proposal_request',
    'submission_id' => 'SYNTH-E29-PHP-001',
    'submission_age_ms' => '1800',
    'website' => '',
    'privacy_ack' => 'true',
    'marketing_consent' => 'false',
    'contact_name' => 'Synthetic Runtime Person',
    'email' => 'runtime.synthetic@example.invalid',
    'phone' => '',
    'organization_name' => 'Synthetic Runtime Organization',
    'audience_id' => 'companies_entrepreneurs',
    'investment_terms' => ['digitalizare'],
    'activity_codes' => ['CAEN 6201'],
    'county' => 'Vâlcea',
    'project_stage' => 'preparation',
    'timeline' => '31_90_days',
    'requested_grant_eur' => '250000',
    'message' => 'Synthetic E29 PHP runtime validation.',
];

$processed = $runtime->process($payload);
if ($processed['record_state'] !== 'QUALIFIED_INTAKE') fail_test('record_state drift');
if ($processed['lead']['marketing_consent'] !== false) fail_test('marketing default drift');
if ($processed['lead']['requested_grant_eur'] !== 250000.0) fail_test('numeric normalization drift');
if ($processed['scores']['lead_score'] <= 0) fail_test('lead score missing');
if ($processed['matching_profile']['profile_id'] !== 'lead:SYNTH-E29-PHP-001') fail_test('matching profile drift');

$receipt = $runtime->persist($processed);
if ($receipt['status'] !== 'accepted' || $receipt['idempotent_replay'] !== false) fail_test('initial persistence failed');
$replay = $runtime->persist($processed);
if ($replay['status'] !== 'accepted' || $replay['idempotent_replay'] !== true) fail_test('idempotent replay failed');
$recordPath = $root . '/data/leads/' . $receipt['request_id'] . '.json';
$receiptPath = $root . '/data/receipts/' . $receipt['request_id'] . '.json';
if (!is_file($recordPath) || !is_file($receiptPath)) fail_test('persistent artifacts missing');
$publicReceipt = json_decode(file_get_contents($receiptPath), true, 512, JSON_THROW_ON_ERROR);
if (isset($publicReceipt['email']) || isset($publicReceipt['contact_name']) || isset($publicReceipt['message'])) fail_test('PII leaked into receipt');

$spam = $payload; $spam['submission_id'] = 'SPAM'; $spam['website'] = 'filled';
expect_exception(fn() => $runtime->process($spam), 'SPAM_REJECTED');
$badEmail = $payload; $badEmail['submission_id'] = 'BADMAIL'; $badEmail['email'] = 'invalid';
expect_exception(fn() => $runtime->process($badEmail), 'INVALID_EMAIL');
$unknown = $payload; $unknown['submission_id'] = 'UNKNOWN'; $unknown['password'] = 'not-allowed';
expect_exception(fn() => $runtime->process($unknown), 'UNSUPPORTED_FIELD');
$noPrivacy = $payload; $noPrivacy['submission_id'] = 'NOPRIV'; $noPrivacy['privacy_ack'] = 'false';
expect_exception(fn() => $runtime->process($noPrivacy), 'PRIVACY_ACK_REQUIRED');
$markup = $payload; $markup['submission_id'] = 'MARKUP'; $markup['message'] = '<script>alert(1)</script>';
expect_exception(fn() => $runtime->process($markup), 'ACTIVE_MARKUP_REJECTED');
$missing = $payload; $missing['submission_id'] = 'MISSING'; unset($missing['audience_id']);
expect_exception(fn() => $runtime->process($missing), 'FORM_FIELD_REQUIRED');

putenv('EUCONS_DATA_ROOT=' . $root . '/public/data');
expect_exception(fn() => $runtime->storageRoot(), 'PII_STORAGE_INSIDE_WEBROOT');

putenv('EUCONS_DATA_ROOT');
rrmdir($root);
echo "EUCONS E29 PHP runtime tests: PASS\n";
