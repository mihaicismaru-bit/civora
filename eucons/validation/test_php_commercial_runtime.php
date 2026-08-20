<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/runtime/php/src/LeadRuntime.php';
require_once dirname(__DIR__) . '/runtime/php/src/CrmRuntime.php';
require_once dirname(__DIR__) . '/runtime/php/src/RetentionRuntime.php';
require_once dirname(__DIR__) . '/runtime/php/src/MailRuntime.php';

function fail_commercial(string $message): never { fwrite(STDERR, $message . PHP_EOL); exit(1); }
function rrmdir_commercial(string $dir): void {
    if (!is_dir($dir)) return;
    foreach (scandir($dir) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        $path = $dir . '/' . $item;
        is_dir($path) ? rrmdir_commercial($path) : @unlink($path);
    }
    @rmdir($dir);
}

$root = sys_get_temp_dir() . '/eucons-commercial-' . getmypid();
rrmdir_commercial($root);
@mkdir($root . '/public', 0700, true);
@mkdir($root . '/secrets', 0700, true);
putenv('EUCONS_DATA_ROOT=' . $root . '/data');
$_SERVER['DOCUMENT_ROOT'] = $root . '/public';
$leadRuntime = new EuconsLeadRuntime(dirname(__DIR__));

$payload = [
    'form_id' => 'proposal_request',
    'submission_id' => 'SYNTH-E29-COMMERCIAL-001',
    'submission_age_ms' => '1800',
    'website' => '',
    'privacy_ack' => 'true',
    'marketing_consent' => 'false',
    'contact_name' => 'Synthetic Commercial Contact',
    'email' => 'commercial.synthetic@example.invalid',
    'phone' => '',
    'organization_name' => 'Synthetic Commercial Organization',
    'audience_id' => 'companies_entrepreneurs',
    'investment_terms' => ['digitalizare'],
    'activity_codes' => ['CAEN 6201'],
    'county' => 'Vâlcea',
    'project_stage' => 'preparation',
    'timeline' => '31_90_days',
    'requested_grant_eur' => '250000',
    'message' => 'Synthetic commercial runtime validation.',
];
$processed = $leadRuntime->process($payload);
$rawReceipt = $leadRuntime->persist($processed);
$dataRoot = $leadRuntime->storageRoot();

$crm = new EuconsCrmRuntime($dataRoot, dirname(__DIR__));
$crmReceipt = $crm->ingest($processed, '2026-08-20T05:00:00+00:00');
if (($crmReceipt['status'] ?? '') !== 'accepted' || ($crmReceipt['stage'] ?? '') !== 'NEW') fail_commercial('CRM initial ingest failed');
$crmReplay = $crm->ingest($processed, '2026-08-20T05:01:00+00:00');
if (($crmReplay['idempotent_replay'] ?? false) !== true || $crmReplay['lead_id'] !== $crmReceipt['lead_id']) fail_commercial('CRM replay failed');
$crmState = json_decode((string)file_get_contents($dataRoot . '/crm/state.json'), true, 512, JSON_THROW_ON_ERROR);
if (count($crmState['leads']) !== 1 || count($crmState['contacts']) !== 1 || count($crmState['organizations']) !== 1) fail_commercial('CRM state cardinality drift');
if (($crmState['leads'][$crmReceipt['lead_id']]['retention_class'] ?? '') !== 'LEAD_INQUIRY') fail_commercial('CRM retention class missing');

$secretFile = $root . '/secrets/mail.json';
file_put_contents($secretFile, json_encode(['username' => 'office@eucons.ro', 'password' => 'synthetic-secret-not-real'], JSON_THROW_ON_ERROR));
chmod($secretFile, 0600);
$transportCalls = 0;
$transport = function(array $secret, array $record) use (&$transportCalls): void {
    $transportCalls++;
    if ($secret['username'] !== 'office@eucons.ro') fail_commercial('SMTP username drift');
    if (($record['message_type'] ?? '') !== 'LEAD_ACKNOWLEDGEMENT') fail_commercial('unexpected automatic message type');
    if (($record['recipient'] ?? '') !== 'commercial.synthetic@example.invalid') fail_commercial('SMTP recipient drift');
};
$mail = new EuconsMailRuntime($dataRoot, $secretFile, $transport);
$mail->queueAcknowledgement($processed, $rawReceipt['request_id']);
$mailReceipt = $mail->dispatch($rawReceipt['request_id']);
if (($mailReceipt['status'] ?? '') !== 'sent' || $transportCalls !== 1) fail_commercial('mail dispatch failed');
$mailReplay = $mail->dispatch($rawReceipt['request_id']);
if (($mailReplay['idempotent_replay'] ?? false) !== true || $transportCalls !== 1) fail_commercial('mail idempotency failed');
$publicMailReceipt = json_decode((string)file_get_contents($dataRoot . '/mail/receipts/' . $rawReceipt['request_id'] . '.json'), true, 64, JSON_THROW_ON_ERROR);
foreach (['recipient','email','contact_name','body','password'] as $forbidden) {
    if (array_key_exists($forbidden, $publicMailReceipt)) fail_commercial('PII or secret leaked into mail receipt');
}

$oldPayload = $payload;
$oldPayload['submission_id'] = 'SYNTH-E29-RETENTION-OLD';
$oldPayload['email'] = 'old.synthetic@example.invalid';
$oldPayload['organization_name'] = 'Old Synthetic Organization';
$oldProcessed = $leadRuntime->process($oldPayload);
$oldRaw = $leadRuntime->persist($oldProcessed);
$oldPath = $dataRoot . '/leads/' . $oldRaw['request_id'] . '.json';
$oldRecord = json_decode((string)file_get_contents($oldPath), true, 512, JSON_THROW_ON_ERROR);
$oldRecord['received_at'] = '2025-01-01T00:00:00+00:00';
file_put_contents($oldPath, json_encode($oldRecord, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n");
$oldCrm = $crm->ingest($oldProcessed, '2025-01-01T00:00:00+00:00');
$retention = new EuconsRetentionRuntime($dataRoot, dirname(__DIR__));
$retentionReceipt = $retention->sweep('2026-08-20T06:00:00+00:00');
if (($retentionReceipt['deleted_lead_files'] ?? 0) < 1 || ($retentionReceipt['deleted_crm_leads'] ?? 0) < 1) fail_commercial('retention sweep did not erase expired lead');
if (is_file($oldPath)) fail_commercial('expired raw lead remained');
$maintenanceReceipts = glob($dataRoot . '/maintenance/receipts/*.json') ?: [];
if (!$maintenanceReceipts) fail_commercial('retention receipt missing');
$maintenance = json_decode((string)file_get_contents($maintenanceReceipts[0]), true, 64, JSON_THROW_ON_ERROR);
if (($maintenance['pii_in_receipt'] ?? true) !== false) fail_commercial('retention receipt PII flag drift');

$missingSecretMail = new EuconsMailRuntime($dataRoot, $root . '/secrets/missing.json', $transport);
$secondProcessed = $leadRuntime->process(array_merge($payload, ['submission_id' => 'SYNTH-E29-MAIL-HOLD', 'email' => 'hold.synthetic@example.invalid']));
$secondRaw = $leadRuntime->persist($secondProcessed);
$missingSecretMail->queueAcknowledgement($secondProcessed, $secondRaw['request_id']);
try {
    $missingSecretMail->dispatch($secondRaw['request_id']);
    fail_commercial('missing mailbox secret failed open');
} catch (RuntimeException $e) {
    if ($e->getMessage() !== 'MAILBOX_SECRET_UNAVAILABLE') fail_commercial('unexpected mailbox secret error');
}

putenv('EUCONS_DATA_ROOT');
rrmdir_commercial($root);
echo "EUCONS E29 PHP commercial runtime tests: PASS\n";
