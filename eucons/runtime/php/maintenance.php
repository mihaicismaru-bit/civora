<?php
declare(strict_types=1);

require_once __DIR__ . '/src/LeadRuntime.php';
require_once __DIR__ . '/src/RetentionRuntime.php';
require_once __DIR__ . '/src/MailRuntime.php';

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

$leadRuntime = new EuconsLeadRuntime();
$dataRoot = $leadRuntime->storageRoot();
$retention = new EuconsRetentionRuntime($dataRoot);
$mail = new EuconsMailRuntime($dataRoot);

$result = ['retention' => $retention->sweep(), 'mail_retry' => ['attempted' => 0, 'sent' => 0, 'held' => 0]];
$outboxDir = $dataRoot . '/mail/outbox';
if (is_dir($outboxDir)) {
    foreach (glob($outboxDir . '/*.json') ?: [] as $path) {
        $row = json_decode((string)file_get_contents($path), true, 64, JSON_THROW_ON_ERROR);
        if (($row['state'] ?? '') === 'SENT') continue;
        $requestId = basename($path, '.json');
        $result['mail_retry']['attempted']++;
        try {
            $mail->dispatch($requestId);
            $result['mail_retry']['sent']++;
        } catch (RuntimeException $e) {
            $result['mail_retry']['held']++;
            error_log('EUCONS_MAINTENANCE_MAIL_HOLD code=' . preg_replace('/[^A-Z0-9_]/', '', strtoupper($e->getMessage())));
        }
    }
}

echo json_encode($result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . PHP_EOL;
