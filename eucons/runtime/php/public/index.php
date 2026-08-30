<?php
declare(strict_types=1);

require_once dirname(__DIR__) . '/src/LeadRuntime.php';
require_once dirname(__DIR__) . '/src/CrmRuntime.php';
require_once dirname(__DIR__) . '/src/RetentionRuntime.php';
require_once dirname(__DIR__) . '/src/MailRuntime.php';
require_once dirname(__DIR__) . '/src/ResearchRuntime.php';

const AI4WORK_RESEARCH_PATH = '/research/ai4work/v1/submit';
const AI4WORK_MAX_BODY_BYTES = 65536;

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
        header('Access-Control-Allow-Headers: Content-Type, X-AI4WORK-Idempotency-Key, X-AI4WORK-Recruitment-Channel');
        header('Access-Control-Max-Age: 600');
    }
}

function eucons_json(int $status, array $body): never
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    exit;
}

function eucons_error_code(Throwable $error, string $fallback): string
{
    return preg_replace('/[^A-Z0-9_]/', '', strtoupper($error->getMessage())) ?: $fallback;
}

$origin = trim((string)($_SERVER['HTTP_ORIGIN'] ?? ''));
$method = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
$path = parse_url((string)($_SERVER['REQUEST_URI'] ?? '/'), PHP_URL_PATH) ?: '/';
$path = rtrim($path, '/') ?: '/';
$isResearch = $path === AI4WORK_RESEARCH_PATH;

$leadRuntime = new EuconsLeadRuntime();
$researchRuntime = new EuconsResearchRuntime();
$originAllowed = $isResearch
    ? $researchRuntime->allowedOrigin($origin)
    : $leadRuntime->allowedOrigin($origin);

if ($origin !== '' && !$originAllowed) {
    eucons_security_headers();
    eucons_json(403, ['status' => 'rejected', 'code' => 'ORIGIN_REJECTED']);
}

eucons_security_headers($origin !== '' ? $origin : null);

if ($method === 'OPTIONS') {
    if ($origin === '' || !$originAllowed) {
        eucons_json(403, ['status' => 'rejected', 'code' => 'ORIGIN_REQUIRED']);
    }
    if (!$isResearch && $path !== '/api/leads') {
        eucons_json(404, ['status' => 'not_found']);
    }
    http_response_code(204);
    exit;
}

if ($isResearch) {
    if ($method !== 'POST') {
        header('Allow: POST, OPTIONS');
        eucons_json(405, ['status' => 'rejected', 'code' => 'METHOD_NOT_ALLOWED']);
    }
    if ($origin === '' || !$researchRuntime->allowedOrigin($origin)) {
        eucons_json(403, ['status' => 'rejected', 'code' => 'ORIGIN_REQUIRED']);
    }
    if (!$researchRuntime->productionEnabled()) {
        eucons_json(503, ['status' => 'unavailable', 'code' => 'RESEARCH_COLLECTION_DISABLED']);
    }

    $contentType = strtolower(trim(explode(';', (string)($_SERVER['CONTENT_TYPE'] ?? ''))[0]));
    if ($contentType !== 'application/json') {
        eucons_json(415, ['status' => 'rejected', 'code' => 'UNSUPPORTED_CONTENT_TYPE']);
    }
    $declaredLength = (int)($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($declaredLength > AI4WORK_MAX_BODY_BYTES) {
        eucons_json(413, ['status' => 'rejected', 'code' => 'PAYLOAD_TOO_LARGE']);
    }
    $rawBody = file_get_contents('php://input');
    if ($rawBody === false) {
        eucons_json(400, ['status' => 'rejected', 'code' => 'INVALID_BODY']);
    }
    if (strlen($rawBody) > AI4WORK_MAX_BODY_BYTES) {
        eucons_json(413, ['status' => 'rejected', 'code' => 'PAYLOAD_TOO_LARGE']);
    }

    try {
        $payload = json_decode($rawBody, true, 64, JSON_THROW_ON_ERROR);
        $prepared = $researchRuntime->validateSubmission(
            $payload,
            $_SERVER['HTTP_X_AI4WORK_IDEMPOTENCY_KEY'] ?? null,
            $_SERVER['HTTP_X_AI4WORK_RECRUITMENT_CHANNEL'] ?? null,
        );
        $receipt = $researchRuntime->persist($prepared, $rawBody);
        eucons_json($receipt['inserted'] ? 201 : 200, [
            'accepted' => true,
            'inserted' => $receipt['inserted'],
            'response_id' => $receipt['response_id'],
        ]);
    } catch (JsonException $e) {
        eucons_json(400, ['status' => 'rejected', 'code' => 'INVALID_JSON']);
    } catch (InvalidArgumentException $e) {
        $code = eucons_error_code($e, 'RESEARCH_SUBMISSION_REJECTED');
        $status = in_array($code, ['INVALID_IDEMPOTENCY_KEY', 'INVALID_RECRUITMENT_CHANNEL'], true) ? 400 : 422;
        if ($code === 'PAYLOAD_TOO_LARGE') $status = 413;
        error_log('EUCONS_RESEARCH_REJECT code=' . $code);
        eucons_json($status, ['status' => 'rejected', 'code' => $code]);
    } catch (RuntimeException $e) {
        $code = eucons_error_code($e, 'RESEARCH_RUNTIME_FAILURE');
        if ($code === 'IDEMPOTENCY_CONFLICT') {
            eucons_json(409, ['status' => 'rejected', 'code' => 'IDEMPOTENCY_CONFLICT']);
        }
        if ($code === 'ERASED_RESPONSE_REPLAY_BLOCKED') {
            eucons_json(409, ['status' => 'rejected', 'code' => 'RESEARCH_RECORD_UNAVAILABLE']);
        }
        error_log('EUCONS_RESEARCH_ERROR code=' . $code);
        eucons_json(503, ['status' => 'unavailable', 'code' => 'RESEARCH_STORAGE_UNAVAILABLE']);
    } catch (Throwable $e) {
        error_log('EUCONS_RESEARCH_ERROR code=UNEXPECTED_RESEARCH_RUNTIME_FAILURE');
        eucons_json(503, ['status' => 'unavailable', 'code' => 'RESEARCH_RUNTIME_UNAVAILABLE']);
    }
}

if ($path !== '/api/leads') {
    eucons_json(404, ['status' => 'not_found']);
}

if ($method !== 'POST') {
    header('Allow: POST, OPTIONS');
    eucons_json(405, ['status' => 'rejected', 'code' => 'METHOD_NOT_ALLOWED']);
}

if ($origin === '' || !$leadRuntime->allowedOrigin($origin)) {
    eucons_json(403, ['status' => 'rejected', 'code' => 'ORIGIN_REQUIRED']);
}

$contentType = strtolower(trim(explode(';', (string)($_SERVER['CONTENT_TYPE'] ?? ''))[0]));
if (!in_array($contentType, ['application/x-www-form-urlencoded', 'multipart/form-data'], true)) {
    eucons_json(415, ['status' => 'rejected', 'code' => 'UNSUPPORTED_CONTENT_TYPE']);
}

try {
    $processed = $leadRuntime->process($_POST);
    $receipt = $leadRuntime->persist($processed);
    $dataRoot = $leadRuntime->storageRoot();

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
        error_log('EUCONS_MAIL_HELD code=' . eucons_error_code($mailError, 'MAIL_FAILURE'));
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
    error_log('EUCONS_RUNTIME_REJECT code=' . eucons_error_code($e, 'SUBMISSION_REJECTED'));
    eucons_json(422, ['status' => 'rejected', 'code' => $e->getMessage()]);
} catch (RuntimeException $e) {
    $code = eucons_error_code($e, 'RUNTIME_FAILURE');
    error_log('EUCONS_RUNTIME_ERROR code=' . $code);
    $status = $code === 'SUBMISSION_ID_CONFLICT' ? 409 : 503;
    eucons_json($status, ['status' => 'unavailable', 'code' => $code]);
} catch (Throwable $e) {
    error_log('EUCONS_RUNTIME_ERROR code=UNEXPECTED_RUNTIME_FAILURE');
    eucons_json(503, ['status' => 'unavailable', 'code' => 'UNEXPECTED_RUNTIME_FAILURE']);
}
