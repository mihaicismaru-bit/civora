<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/src/LeadRuntime.php';
require_once dirname(__DIR__) . '/src/CrmRuntime.php';
require_once dirname(__DIR__) . '/src/RetentionRuntime.php';
require_once dirname(__DIR__) . '/src/MailRuntime.php';

function eucons_security_headers(?string $origin = null): void
{
    header("Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
    header('Referrer-Policy: no-referrer');
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
    header('Cache-Control: no-store, max-age=0');
    header('Content-Type: application/json; charset=utf-8');
    if ($origin !== null && $origin !== '') {
        header('Access-Control-Allow-Origin: ' . $origin);
        header('Vary: Origin');
        header('Access-Control-Allow-Methods: POST, OPTIONS');
        header('Access-Control-Allow-Headers: Content-Type');
        header('Access-Control-Max-Age: 600');
    }
}

function eucons_json(int $status, array $body): never
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    exit;
}

$runtime = new EuconsLeadRuntime();
$origin = trim((string)($_SERVER['HTTP_ORIGIN'] ?? ''));
$method = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
$path = parse_url((string)($_SERVER['REQUEST_URI'] ?? '/'), PHP_URL_PATH) ?: '/';
$path = rtrim($path, '/') ?: '/';

if ($origin !== '' && !$runtime->allowedOrigin($origin)) {
    eucons_security_headers();
    eucons_json(403, ['status' => 'rejected', 'code' => 'ORIGIN_REJECTED']);
}

eucons_security_headers($origin !== '' ? $origin : null);

if ($method === 'OPTIONS') {
    if ($origin === '' || !$runtime->allowedOrigin($origin)) {
        eucons_json(403, ['status' => 'rejected', 'code' => 'ORIGIN_REQUIRED']);
    }
    http_response_code(204);
    exit;
}

if ($path !== '/api/leads') {
    eucons_json(404, ['status' => 'not_found']);
}

if ($method !== 'POST') {
    header('Allow: POST, OPTIONS');
    eucons_json(405, ['status' => 'rejected', 'code' => 'METHOD_NOT_ALLOWED']);
}

if ($origin === '' || !$runtime->allowedOrigin($origin)) {
    eucons_json(403, ['status' => 'rejected', 'code' => 'ORIGIN_REQUIRED']);
}

$contentType = strtolower(trim(explode(';', (string)($_SERVER['CONTENT_TYPE'] ?? ''))[0]));
if (!in_array($contentType, ['application/x-www-form-urlencoded', 'multipart/form-data'], true)) {
    eucons_json(415, ['status' => 'rejected', 'code' => 'UNSUPPORTED_CONTENT_TYPE']);
}

try {
    $processed = $runtime->process($_POST);
    $receipt = $runtime->persist($processed);
    $dataRoot = $runtime->storageRoot();

    $crm = new EuconsCrmRuntime($dataRoot);
    $crmReceipt = $crm->ingest($processed);
    if (($crmReceipt['status'] ?? '') !== 'accepted') {
        throw new RuntimeException('CRM_PERSISTENCE_NOT_CONFIRMED');
    }

    $mail = new EuconsMailRuntime($dataRoot);
    $mail->queueAcknowledgement($processed, $receipt['request_id']);
    try {
        $mail->dispatch($receipt['request_id']);
    } catch (RuntimeException $mailError) {
        error_log('EUCONS_MAIL_HELD code=' . preg_replace('/[^A-Z0-9_]/', '', strtoupper($mailError->getMessage())));
    }

    try {
        (new EuconsRetentionRuntime($dataRoot))->sweep();
    } catch (Throwable $retentionError) {
        error_log('EUCONS_RETENTION_HOLD code=RETENTION_SWEEP_FAILED');
    }

    eucons_json(202, [
        'status' => $receipt['status'],
        'request_id' => $receipt['request_id'],
        'next_action' => $receipt['next_action'],
    ]);
} catch (InvalidArgumentException $e) {
    error_log('EUCONS_RUNTIME_REJECT code=' . preg_replace('/[^A-Z0-9_]/', '', strtoupper($e->getMessage())));
    eucons_json(422, ['status' => 'rejected', 'code' => $e->getMessage()]);
} catch (RuntimeException $e) {
    $code = preg_replace('/[^A-Z0-9_]/', '', strtoupper($e->getMessage())) ?: 'RUNTIME_FAILURE';
    error_log('EUCONS_RUNTIME_ERROR code=' . $code);
    $status = $code === 'SUBMISSION_ID_CONFLICT' ? 409 : 503;
    eucons_json($status, ['status' => 'unavailable', 'code' => $code]);
} catch (Throwable $e) {
    error_log('EUCONS_RUNTIME_ERROR code=UNEXPECTED_RUNTIME_FAILURE');
    eucons_json(503, ['status' => 'unavailable', 'code' => 'UNEXPECTED_RUNTIME_FAILURE']);
}
