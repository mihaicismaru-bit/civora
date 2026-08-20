<?php
declare(strict_types=1);

final class EuconsLeadRuntime
{
    private array $leadContract;
    private array $formsDocument;
    private array $runtimeContract;

    public function __construct(?string $euconsRoot = null)
    {
        $root = $euconsRoot ?: dirname(__DIR__, 3);
        $this->leadContract = self::loadJson($root . '/leads/lead_contract.json');
        $this->formsDocument = self::loadJson($root . '/leads/forms.json');
        $this->runtimeContract = self::loadJson(dirname(__DIR__) . '/runtime_contract.json');
    }

    private static function loadJson(string $path): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) {
            throw new RuntimeException('RUNTIME_CONTRACT_UNAVAILABLE');
        }
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) {
            throw new RuntimeException('RUNTIME_CONTRACT_INVALID');
        }
        return $data;
    }

    private static function cleanText(mixed $value, int $limit): string
    {
        if (is_array($value) || is_object($value)) {
            throw new InvalidArgumentException('INVALID_TEXT_VALUE');
        }
        $text = trim((string)($value ?? ''));
        $text = preg_replace('/\s+/u', ' ', $text) ?? $text;
        if (preg_match('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', $text)) {
            throw new InvalidArgumentException('CONTROL_CHARACTER_REJECTED');
        }
        if (preg_match('/<\s*script\b|javascript\s*:|\bon[a-z]+\s*=/iu', $text)) {
            throw new InvalidArgumentException('ACTIVE_MARKUP_REJECTED');
        }
        $length = function_exists('mb_strlen') ? mb_strlen($text, 'UTF-8') : strlen($text);
        if ($length > $limit) {
            throw new InvalidArgumentException('TEXT_TOO_LONG');
        }
        return $text;
    }

    private static function lower(string $value): string
    {
        return function_exists('mb_strtolower') ? mb_strtolower($value, 'UTF-8') : strtolower($value);
    }

    private static function fold(string $value): string
    {
        $text = self::lower(self::cleanText($value, 4000));
        if (function_exists('iconv')) {
            $ascii = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $text);
            if ($ascii !== false) {
                $text = $ascii;
            }
        }
        return $text;
    }

    private static function boolValue(mixed $value): bool
    {
        if ($value === true || $value === 1 || $value === '1') {
            return true;
        }
        if (is_string($value)) {
            return in_array(strtolower(trim($value)), ['true', 'yes', 'on'], true);
        }
        return false;
    }

    private static function normalizeList(mixed $value, int $limit): array
    {
        if ($value === null || $value === '') {
            return [];
        }
        if (!is_array($value)) {
            throw new InvalidArgumentException('EXPECTED_LIST');
        }
        $out = [];
        foreach ($value as $item) {
            $text = self::cleanText($item, $limit);
            if ($text !== '' && !in_array($text, $out, true)) {
                $out[] = $text;
            }
        }
        return $out;
    }

    private function formsById(): array
    {
        $out = [];
        foreach (($this->formsDocument['forms'] ?? []) as $form) {
            if (isset($form['id'])) {
                $out[(string)$form['id']] = $form;
            }
        }
        return $out;
    }

    public function normalizeTransport(array $payload): array
    {
        if (isset($payload['submission_age_ms']) && is_numeric($payload['submission_age_ms'])) {
            $payload['submission_age_ms'] = (int)$payload['submission_age_ms'];
        }
        if (array_key_exists('requested_grant_eur', $payload)) {
            if ($payload['requested_grant_eur'] === '' || $payload['requested_grant_eur'] === null) {
                $payload['requested_grant_eur'] = null;
            } elseif (is_numeric($payload['requested_grant_eur'])) {
                $payload['requested_grant_eur'] = (float)$payload['requested_grant_eur'];
            }
        }
        $payload['privacy_ack'] = self::boolValue($payload['privacy_ack'] ?? false);
        $payload['marketing_consent'] = self::boolValue($payload['marketing_consent'] ?? false);
        return $payload;
    }

    public function validateAndNormalize(array $payload): array
    {
        $allowed = array_fill_keys($this->leadContract['allowed_fields'], true);
        foreach (array_keys($payload) as $field) {
            if (!isset($allowed[$field])) {
                throw new InvalidArgumentException('UNSUPPORTED_FIELD');
            }
        }
        foreach ($this->leadContract['required_global_fields'] as $field) {
            if (!array_key_exists($field, $payload) || $payload[$field] === null || $payload[$field] === '') {
                throw new InvalidArgumentException('REQUIRED_FIELD_MISSING');
            }
        }

        $anti = $this->leadContract['anti_spam'];
        $honeypot = (string)$anti['honeypot_field'];
        if (($anti['honeypot_must_be_blank'] ?? false) && self::cleanText($payload[$honeypot] ?? '', 300) !== '') {
            throw new InvalidArgumentException('SPAM_REJECTED');
        }
        $age = $payload['submission_age_ms'] ?? null;
        if (!is_int($age) && !is_float($age)) {
            throw new InvalidArgumentException('INVALID_SUBMISSION_AGE');
        }
        if ($age < (int)$anti['minimum_submission_age_ms'] || $age > (int)$anti['maximum_submission_age_ms']) {
            throw new InvalidArgumentException('INVALID_SUBMISSION_AGE');
        }
        if (($payload['privacy_ack'] ?? false) !== true) {
            throw new InvalidArgumentException('PRIVACY_ACK_REQUIRED');
        }

        $forms = $this->formsById();
        $formId = self::cleanText($payload['form_id'], 100);
        if (!isset($forms[$formId])) {
            throw new InvalidArgumentException('UNKNOWN_FORM');
        }
        foreach (($forms[$formId]['required'] ?? []) as $field) {
            $value = $payload[$field] ?? null;
            if ($value === null || $value === '' || $value === []) {
                throw new InvalidArgumentException('FORM_FIELD_REQUIRED');
            }
        }

        $validation = $this->leadContract['validation'];
        $short = (int)$validation['max_short_text_length'];
        $long = (int)$validation['max_text_length'];
        $email = self::lower(self::cleanText($payload['email'], $short));
        if (!preg_match('/^[^\s@]+@[^\s@]+\.[^\s@]+$/u', $email)) {
            throw new InvalidArgumentException('INVALID_EMAIL');
        }
        $audience = self::cleanText($payload['audience_id'] ?? '', 100);
        if ($audience !== '' && !in_array($audience, $validation['allowed_audiences'], true)) {
            throw new InvalidArgumentException('INVALID_AUDIENCE');
        }
        $timeline = self::cleanText($payload['timeline'] ?? 'unknown', 100) ?: 'unknown';
        if (!in_array($timeline, $validation['allowed_timelines'], true)) {
            throw new InvalidArgumentException('INVALID_TIMELINE');
        }
        $projectStage = self::cleanText($payload['project_stage'] ?? 'unknown', 100) ?: 'unknown';
        if (!in_array($projectStage, $validation['allowed_project_stages'], true)) {
            throw new InvalidArgumentException('INVALID_PROJECT_STAGE');
        }
        $requested = $payload['requested_grant_eur'] ?? null;
        if ($requested !== null && (!is_int($requested) && !is_float($requested) || (float)$requested <= 0)) {
            throw new InvalidArgumentException('INVALID_REQUESTED_GRANT');
        }

        return [
            'form_id' => $formId,
            'submission_id' => self::cleanText($payload['submission_id'], $short),
            'submitted_at' => self::cleanText($payload['submitted_at'] ?? '', $short),
            'privacy_ack' => true,
            'marketing_consent' => ($payload['marketing_consent'] ?? false) === true,
            'contact_name' => self::cleanText($payload['contact_name'], $short),
            'email' => $email,
            'phone' => self::cleanText($payload['phone'] ?? '', $short),
            'organization_name' => self::cleanText($payload['organization_name'] ?? '', $short),
            'audience_id' => $audience,
            'organization_labels' => self::normalizeList($payload['organization_labels'] ?? [], $short),
            'activity_codes' => self::normalizeList($payload['activity_codes'] ?? [], $short),
            'county' => self::cleanText($payload['county'] ?? '', $short),
            'region_terms' => self::normalizeList($payload['region_terms'] ?? [], $short),
            'investment_terms' => self::normalizeList($payload['investment_terms'] ?? [], $short),
            'requested_grant_eur' => $requested === null ? null : (float)$requested,
            'project_stage' => $projectStage,
            'timeline' => $timeline,
            'message' => self::cleanText($payload['message'] ?? '', $long),
        ];
    }

    private static function matchingProfile(array $lead): array
    {
        $regions = $lead['region_terms'];
        if ($lead['county'] !== '' && !in_array($lead['county'], $regions, true)) {
            $regions[] = $lead['county'];
        }
        $labels = $lead['organization_labels'];
        if ($lead['organization_name'] !== '') {
            $labels[] = $lead['organization_name'];
        }
        $profile = [
            'profile_id' => 'lead:' . $lead['submission_id'],
            'audience_id' => $lead['audience_id'],
            'organization_labels' => $labels,
            'activity_codes' => $lead['activity_codes'],
            'region_terms' => $regions,
            'investment_terms' => $lead['investment_terms'],
        ];
        if ($lead['requested_grant_eur'] !== null) {
            $profile['requested_grant_eur'] = $lead['requested_grant_eur'];
        }
        return $profile;
    }

    private static function dedupeKey(array $lead): string
    {
        return hash('sha256', self::lower($lead['email']) . '|' . self::fold($lead['organization_name']));
    }

    private function scoreLead(array $lead): array
    {
        $scoring = $this->leadContract['scoring'];
        $fields = ['organization_name', 'audience_id', 'investment_terms', 'activity_codes', 'county', 'message'];
        $populated = 0;
        foreach ($fields as $field) {
            if (!empty($lead[$field])) {
                $populated++;
            }
        }
        $completeness = (int)round(((int)$scoring['completeness_max']) * $populated / count($fields));
        $intent = (int)($scoring['form_intent'][$lead['form_id']] ?? 0);
        $urgency = (int)($scoring['timeline_urgency'][$lead['timeline']] ?? 0);
        $total = min((int)$scoring['lead_score_max'], $completeness + $intent + $urgency);
        $maxIntent = max(array_map('intval', $scoring['form_intent']));
        $maxUrgency = max(array_map('intval', $scoring['timeline_urgency']));
        return [
            'lead_score' => $total,
            'intent_score' => $intent ? (int)round(100 * $intent / $maxIntent) : 0,
            'urgency_score' => $urgency ? (int)round(100 * $urgency / $maxUrgency) : 0,
            'completeness_score' => $completeness,
            'matching_candidate_count' => 0,
            'matching_requires_data_count' => 0,
        ];
    }

    private function nextAction(array $lead, array $scores): string
    {
        $actions = $this->leadContract['next_actions'];
        if ($lead['form_id'] === 'project_recovery') {
            return (string)$actions['project_recovery'];
        }
        if ($scores['lead_score'] >= 70) {
            return (string)$actions['high_score'];
        }
        return (string)$actions['default'];
    }

    public function process(array $payload): array
    {
        $normalizedTransport = $this->normalizeTransport($payload);
        $lead = $this->validateAndNormalize($normalizedTransport);
        $scores = $this->scoreLead($lead);
        return [
            'schema_version' => 1,
            'engine_id' => $this->leadContract['engine_id'],
            'record_state' => 'QUALIFIED_INTAKE',
            'dedupe_key' => self::dedupeKey($lead),
            'lead' => $lead,
            'matching_profile' => self::matchingProfile($lead),
            'scores' => $scores,
            'next_action' => $this->nextAction($lead, $scores),
            'consent' => [
                'privacy_ack' => true,
                'marketing_consent' => $lead['marketing_consent'],
                'marketing_allowed' => $lead['marketing_consent'] === true,
            ],
            'storage_state' => 'READY_FOR_PROVIDER_STORAGE',
        ];
    }

    public function storageRoot(): string
    {
        $configured = trim((string)(getenv('EUCONS_DATA_ROOT') ?: ''));
        $root = $configured !== '' ? $configured : (string)$this->runtimeContract['storage']['default_root'];
        $documentRoot = trim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''));
        if ($documentRoot !== '') {
            $doc = rtrim(str_replace('\\', '/', $documentRoot), '/');
            $candidate = rtrim(str_replace('\\', '/', $root), '/');
            if ($candidate === $doc || str_starts_with($candidate . '/', $doc . '/')) {
                throw new RuntimeException('PII_STORAGE_INSIDE_WEBROOT');
            }
        }
        return rtrim($root, '/');
    }

    private static function ensureDirectory(string $path): void
    {
        if (!is_dir($path) && !@mkdir($path, 0700, true) && !is_dir($path)) {
            throw new RuntimeException('STORAGE_DIRECTORY_UNAVAILABLE');
        }
    }

    private static function stableJson(array $value): string
    {
        return json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    }

    public function persist(array $processed): array
    {
        $root = $this->storageRoot();
        $leadsDir = $root . '/leads';
        $receiptsDir = $root . '/receipts';
        self::ensureDirectory($leadsDir);
        self::ensureDirectory($receiptsDir);
        self::ensureDirectory($root . '/locks');

        $requestId = substr(hash('sha256', (string)$processed['lead']['submission_id']), 0, 32);
        $payloadHash = hash('sha256', self::stableJson($processed));
        $recordPath = $leadsDir . '/' . $requestId . '.json';
        $receiptPath = $receiptsDir . '/' . $requestId . '.json';
        $lockPath = $root . '/locks/' . $requestId . '.lock';
        $lock = @fopen($lockPath, 'c+');
        if ($lock === false || !flock($lock, LOCK_EX)) {
            throw new RuntimeException('STORAGE_LOCK_UNAVAILABLE');
        }
        try {
            if (is_file($recordPath)) {
                $existing = self::loadJson($recordPath);
                if (($existing['payload_hash'] ?? null) !== $payloadHash) {
                    throw new RuntimeException('SUBMISSION_ID_CONFLICT');
                }
                return [
                    'status' => 'accepted',
                    'request_id' => $requestId,
                    'next_action' => (string)($existing['record']['next_action'] ?? 'COMMERCIAL_REVIEW'),
                    'idempotent_replay' => true,
                ];
            }

            $record = [
                'schema_version' => 1,
                'received_at' => gmdate('c'),
                'payload_hash' => $payloadHash,
                'record' => $processed,
            ];
            self::atomicWriteJson($recordPath, $record);
            self::atomicWriteJson($receiptPath, [
                'schema_version' => 1,
                'request_id' => $requestId,
                'accepted_at' => $record['received_at'],
                'payload_hash' => $payloadHash,
                'dedupe_key' => $processed['dedupe_key'],
                'next_action' => $processed['next_action'],
                'pii_in_receipt' => false,
            ]);
            return [
                'status' => 'accepted',
                'request_id' => $requestId,
                'next_action' => (string)$processed['next_action'],
                'idempotent_replay' => false,
            ];
        } finally {
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }

    private static function atomicWriteJson(string $path, array $value): void
    {
        $directory = dirname($path);
        $tmp = tempnam($directory, '.eucons-');
        if ($tmp === false) {
            throw new RuntimeException('STORAGE_PREPARE_FAILED');
        }
        try {
            $json = json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
            if (@file_put_contents($tmp, $json, LOCK_EX) === false) {
                throw new RuntimeException('STORAGE_WRITE_FAILED');
            }
            @chmod($tmp, 0600);
            if (!@rename($tmp, $path)) {
                throw new RuntimeException('STORAGE_COMMIT_FAILED');
            }
        } finally {
            if (is_file($tmp)) {
                @unlink($tmp);
            }
        }
    }

    public function allowedOrigin(string $origin): bool
    {
        return in_array($origin, $this->runtimeContract['allowed_origins'], true);
    }
}
