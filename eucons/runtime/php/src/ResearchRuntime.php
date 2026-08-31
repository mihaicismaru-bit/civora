<?php
declare(strict_types=1);

final class EuconsResearchRuntime
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const ALLOWED_FORMS = ['AI4WORK_ADULTS_V1', 'AI4WORK_EMPLOYERS_V1'];
    private const ALLOWED_HOLDS = ['RESTRICTED_PENDING_REVIEW', 'OBJECTED_PENDING_REVIEW'];
    private const MAX_BODY_BYTES = 65536;
    private const MAX_REPLAY_SECONDS = 86400;

    private array $contract;
    private array $formsDocument;
    private array $commercialRuntimeContract;
    private array $activationManifest;

    public function __construct(?string $euconsRoot = null)
    {
        $root = $euconsRoot ?: dirname(__DIR__, 3);
        $researchRoot = $root . '/research/ai4work-step';
        $this->contract = self::loadJson($researchRoot . '/form_contract.json');
        $this->formsDocument = self::loadJson($researchRoot . '/forms_definition.json');
        $this->commercialRuntimeContract = self::loadJson($root . '/runtime/php/runtime_contract.json');
        $this->activationManifest = self::loadJson($researchRoot . '/PROD_ACTIVATION_MANIFEST_DRAFT.json');

        if (($this->contract['research_id'] ?? null) !== self::RESEARCH_ID) {
            throw new RuntimeException('RESEARCH_CONTRACT_ID_MISMATCH');
        }
        if (($this->contract['crm_integration'] ?? null) !== 'FORBIDDEN'
            || ($this->contract['commercial_analytics'] ?? null) !== 'FORBIDDEN') {
            throw new RuntimeException('RESEARCH_ISOLATION_CONTRACT_NOT_FAIL_CLOSED');
        }
    }

    private static function loadJson(string $path): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) {
            throw new RuntimeException('RESEARCH_CONTRACT_UNAVAILABLE');
        }
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) {
            throw new RuntimeException('RESEARCH_CONTRACT_INVALID');
        }
        return $data;
    }

    public function productionEnabled(): bool
    {
        $approvalRef = trim((string)($this->activationManifest['explicit_user_approval_reference'] ?? ''));
        return ($this->contract['production_enabled'] ?? false) === true
            && ($this->activationManifest['approved_for_prod'] ?? false) === true
            && ($this->activationManifest['collection_enabled'] ?? false) === true
            && ($this->activationManifest['deploy_authorized'] ?? null) === false
            && ($this->activationManifest['real_collection_authorized'] ?? false) === true
            && $approvalRef !== ''
            && trim((string)(getenv('AI4WORK_RESEARCH_PROD_ENABLED') ?: '')) === '1';
    }

    public function allowedOrigin(string $origin): bool
    {
        return in_array($origin, ['https://eucons.ro', 'https://www.eucons.ro'], true);
    }

    public function storageRoot(): string
    {
        $configured = trim((string)(getenv('AI4WORK_RESEARCH_ROOT') ?: ''));
        $root = $configured !== '' ? $configured : '/home/eucons/eucons-research/ai4work-step';
        $candidate = rtrim(str_replace('\\', '/', $root), '/');

        $documentRoot = trim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''));
        if ($documentRoot !== '') {
            $doc = rtrim(str_replace('\\', '/', $documentRoot), '/');
            if ($candidate === $doc || str_starts_with($candidate . '/', $doc . '/')) {
                throw new RuntimeException('RESEARCH_STORAGE_INSIDE_WEBROOT');
            }
        }

        $commercialConfigured = trim((string)(getenv('EUCONS_DATA_ROOT') ?: ''));
        $commercialRoot = $commercialConfigured !== ''
            ? $commercialConfigured
            : (string)($this->commercialRuntimeContract['storage']['default_root'] ?? '/home/eucons/eucons-data');
        $commercial = rtrim(str_replace('\\', '/', $commercialRoot), '/');

        if ($candidate === $commercial
            || str_starts_with($candidate . '/', $commercial . '/')
            || str_starts_with($commercial . '/', $candidate . '/')) {
            throw new RuntimeException('RESEARCH_STORAGE_NOT_SEPARATE_FROM_COMMERCIAL');
        }
        return $candidate;
    }

    private static function ensureDirectory(string $path): void
    {
        if (!is_dir($path) && !@mkdir($path, 0700, true) && !is_dir($path)) {
            throw new RuntimeException('RESEARCH_STORAGE_DIRECTORY_UNAVAILABLE');
        }
        @chmod($path, 0700);
    }

    private static function atomicWriteJson(string $path, array $value): void
    {
        self::ensureDirectory(dirname($path));
        $tmp = tempnam(dirname($path), '.ai4work-');
        if ($tmp === false) {
            throw new RuntimeException('RESEARCH_STORAGE_PREPARE_FAILED');
        }
        try {
            $json = json_encode(
                $value,
                JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR
            ) . "\n";
            if (@file_put_contents($tmp, $json, LOCK_EX) === false) {
                throw new RuntimeException('RESEARCH_STORAGE_WRITE_FAILED');
            }
            @chmod($tmp, 0600);
            if (!@rename($tmp, $path)) {
                throw new RuntimeException('RESEARCH_STORAGE_COMMIT_FAILED');
            }
        } finally {
            if (is_file($tmp)) {
                @unlink($tmp);
            }
        }
    }

    private static function isList(array $value): bool
    {
        if ($value === []) {
            return true;
        }
        return array_keys($value) === range(0, count($value) - 1);
    }

    private static function canonicalize(mixed $value): mixed
    {
        if (!is_array($value)) {
            return $value;
        }
        if (self::isList($value)) {
            return array_map([self::class, 'canonicalize'], $value);
        }
        ksort($value, SORT_STRING);
        foreach ($value as $key => $child) {
            $value[$key] = self::canonicalize($child);
        }
        return $value;
    }

    private static function canonicalJson(array $value, bool $newline = false): string
    {
        $json = json_encode(
            self::canonicalize($value),
            JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR
        );
        return $json . ($newline ? "\n" : '');
    }

    private static function forbiddenKeys(): array
    {
        return array_fill_keys([
            'name', 'first_name', 'last_name', 'surname', 'cnp', 'national_id', 'identity_document',
            'email', 'phone', 'telephone', 'address', 'exact_address', 'exact_employer', 'employer_name',
            'organisation_name', 'organization_name', 'cui', 'ip', 'ip_address', 'user_agent', 'cookie_id',
            'login_id', 'account_id', 'device_fingerprint', 'advertising_id', 'marketing_id', 'social_account',
            'photo', 'signature',
        ], true);
    }

    private static function rejectForbiddenKeys(mixed $value): void
    {
        if (!is_array($value)) {
            return;
        }
        $forbidden = self::forbiddenKeys();
        foreach ($value as $key => $child) {
            if (is_string($key) && isset($forbidden[strtolower($key)])) {
                throw new InvalidArgumentException('FORBIDDEN_DIRECT_IDENTIFIER_FIELD');
            }
            self::rejectForbiddenKeys($child);
        }
    }

    private function formById(string $formId): array
    {
        $matches = [];
        foreach (($this->formsDocument['forms'] ?? []) as $form) {
            if (($form['id'] ?? null) === $formId) {
                $matches[] = $form;
            }
        }
        if (count($matches) !== 1) {
            throw new InvalidArgumentException('UNKNOWN_FORM');
        }
        return $matches[0];
    }

    private static function dependencyActive(array $field, array $values): bool
    {
        $rule = $field['depends_on'] ?? null;
        if (!is_array($rule)) {
            return true;
        }
        return ($values[$rule['field']] ?? null) === ($rule['equals'] ?? null);
    }

    private static function validateScalar(array $field, mixed $value): mixed
    {
        $type = (string)($field['type'] ?? '');
        if ($type === 'rating') {
            if (!is_int($value)) {
                throw new InvalidArgumentException('INTEGER_RATING_EXPECTED');
            }
            $min = (int)$field['min'];
            $max = (int)$field['max'];
            if ($value < $min || $value > $max) {
                throw new InvalidArgumentException('RATING_OUT_OF_RANGE');
            }
            return $value;
        }
        if ($type === 'boolean') {
            if (!is_bool($value)) {
                throw new InvalidArgumentException('BOOLEAN_EXPECTED');
            }
            return $value;
        }
        if ($type === 'single' || $type === 'select') {
            if (!in_array($value, $field['options'] ?? [], true)) {
                throw new InvalidArgumentException('OPTION_OUTSIDE_ALLOWLIST');
            }
            return $value;
        }
        if ($type === 'multi') {
            if (!is_array($value) || !self::isList($value)) {
                throw new InvalidArgumentException('LIST_EXPECTED');
            }
            $max = $field['max_selections'] ?? null;
            if ($max !== null && count($value) > (int)$max) {
                throw new InvalidArgumentException('TOO_MANY_SELECTIONS');
            }
            $allowed = $field['options'] ?? [];
            foreach ($value as $item) {
                if (!in_array($item, $allowed, true)) {
                    throw new InvalidArgumentException('MULTI_OPTION_OUTSIDE_ALLOWLIST');
                }
            }
            if (count($value) !== count(array_unique($value, SORT_REGULAR))) {
                throw new InvalidArgumentException('DUPLICATE_MULTI_SELECTION');
            }
            return $value;
        }
        if ($type === 'rating_matrix') {
            if (!is_array($value) || self::isList($value)) {
                throw new InvalidArgumentException('MATRIX_OBJECT_EXPECTED');
            }
            $rows = $field['rows'] ?? [];
            $actualKeys = array_keys($value);
            $expectedKeys = array_keys($rows);
            sort($actualKeys, SORT_STRING);
            sort($expectedKeys, SORT_STRING);
            if ($actualKeys !== $expectedKeys) {
                throw new InvalidArgumentException('MATRIX_KEYS_MISMATCH');
            }
            $out = [];
            foreach ($rows as $key => $_label) {
                $score = $value[$key];
                if (!is_int($score) || $score < (int)$field['min'] || $score > (int)$field['max']) {
                    throw new InvalidArgumentException('MATRIX_RATING_OUT_OF_RANGE');
                }
                $out[$key] = $score;
            }
            return $out;
        }
        if ($type === 'text' || $type === 'textarea') {
            if (!is_string($value)) {
                throw new InvalidArgumentException('TEXT_EXPECTED');
            }
            $text = trim(preg_replace('/\s+/u', ' ', $value) ?? $value);
            $limit = (int)($field['max_chars'] ?? 160);
            $length = function_exists('mb_strlen') ? mb_strlen($text, 'UTF-8') : strlen($text);
            if ($length > $limit) {
                throw new InvalidArgumentException('TEXT_TOO_LONG');
            }
            if (preg_match('/(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/', $text)
                || preg_match('/(?<!\d)(?:\+?40|0)\s?7(?:[ .-]?\d){8}(?!\d)/', $text)
                || preg_match('/(?<!\d)[1-8]\d{12}(?!\d)/', $text)
                || preg_match('/(?i)\b(?:https?:\/\/|www\.)\S+/', $text)) {
                throw new InvalidArgumentException('IDENTIFIER_LIKE_TEXT_REJECTED');
            }
            return $text;
        }
        throw new InvalidArgumentException('UNSUPPORTED_FIELD_TYPE');
    }

    private static function validateGroup(array $definitions, mixed $values): array
    {
        if (!is_array($values) || self::isList($values)) {
            throw new InvalidArgumentException('GROUP_OBJECT_EXPECTED');
        }
        $byId = [];
        foreach ($definitions as $field) {
            $byId[(string)$field['id']] = $field;
        }
        foreach (array_keys($values) as $key) {
            if (!isset($byId[$key])) {
                throw new InvalidArgumentException('UNKNOWN_GROUP_FIELD');
            }
        }
        $out = [];
        foreach ($definitions as $field) {
            $id = (string)$field['id'];
            $active = self::dependencyActive($field, $values);
            $required = ($field['required'] ?? true) === true && $active;
            if (!array_key_exists($id, $values)) {
                if ($required) {
                    throw new InvalidArgumentException('REQUIRED_GROUP_FIELD_MISSING');
                }
                if (in_array($field['type'] ?? '', ['text', 'textarea'], true)) {
                    $out[$id] = '';
                }
                continue;
            }
            if (!$active) {
                $inactive = $values[$id];
                if (!($inactive === null || $inactive === '' || $inactive === [])) {
                    throw new InvalidArgumentException('INACTIVE_DEPENDENCY_FIELD_MUST_BE_EMPTY');
                }
                if (in_array($field['type'] ?? '', ['text', 'textarea'], true)) {
                    $out[$id] = '';
                }
                continue;
            }
            $out[$id] = self::validateScalar($field, $values[$id]);
        }
        return $out;
    }

    private static function validateUuidV4(mixed $value): string
    {
        if (!is_string($value)
            || !preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $value)) {
            throw new InvalidArgumentException('INVALID_IDEMPOTENCY_KEY');
        }
        return $value;
    }

    private static function validateChannelId(mixed $value): string
    {
        if (!is_string($value) || !preg_match('/^CH-[A-Z0-9]{8,32}$/', $value)) {
            throw new InvalidArgumentException('INVALID_RECRUITMENT_CHANNEL');
        }
        return $value;
    }

    public function validateSubmission(mixed $payload, mixed $idempotencyKey, mixed $recruitmentChannelId): array
    {
        if (!is_array($payload) || self::isList($payload)) {
            throw new InvalidArgumentException('PAYLOAD_MUST_BE_OBJECT');
        }
        $expectedTop = ['answers', 'form_id', 'notice_read_and_voluntary_participation', 'profile'];
        $actualTop = array_keys($payload);
        sort($expectedTop, SORT_STRING);
        sort($actualTop, SORT_STRING);
        if ($expectedTop !== $actualTop) {
            throw new InvalidArgumentException('TOP_LEVEL_FIELDS_MISMATCH');
        }

        self::rejectForbiddenKeys($payload);
        $key = self::validateUuidV4($idempotencyKey);
        $channelId = self::validateChannelId($recruitmentChannelId);

        if (($payload['notice_read_and_voluntary_participation'] ?? null) !== true) {
            throw new InvalidArgumentException('VOLUNTARY_PARTICIPATION_ACK_REQUIRED');
        }
        if (!is_string($payload['form_id'] ?? null)) {
            throw new InvalidArgumentException('UNKNOWN_FORM');
        }

        $formId = $payload['form_id'];
        $form = $this->formById($formId);
        $profile = self::validateGroup($form['profile'] ?? [], $payload['profile'] ?? null);
        $answers = self::validateGroup($form['questions'] ?? [], $payload['answers'] ?? null);
        $responseId = hash('sha256', self::RESEARCH_ID . ':' . $formId . ':' . $key);

        $record = [
            'schema_version' => 1,
            'research_id' => self::RESEARCH_ID,
            'form_id' => $formId,
            'form_version' => 1,
            'response_id' => $responseId,
            'received_at' => gmdate('Y-m-d\TH:i:s\Z'),
            'recruitment_channel_id' => $channelId,
            'profile' => $profile,
            'answers' => $answers,
            'synthetic' => false,
        ];
        $analyticalBody = [
            'research_id' => $record['research_id'],
            'form_id' => $record['form_id'],
            'form_version' => $record['form_version'],
            'recruitment_channel_id' => $record['recruitment_channel_id'],
            'profile' => $record['profile'],
            'answers' => $record['answers'],
            'synthetic' => false,
        ];
        return [
            'record' => $record,
            'body_sha256' => hash('sha256', self::canonicalJson($analyticalBody)),
        ];
    }

    private function paths(string $responseId, string $formId): array
    {
        $root = $this->storageRoot();
        return [
            'response' => $root . '/responses/' . $formId . '/' . $responseId . '.json',
            'receipt' => $root . '/receipts/' . $responseId . '.json',
            'hold' => $root . '/holds/' . $responseId . '.json',
            'erased' => $root . '/erased/' . $responseId . '.json',
            'lock' => $root . '/locks/' . $responseId . '.lock',
        ];
    }

    private static function loadOptionalJson(string $path): ?array
    {
        if (!is_file($path)) {
            return null;
        }
        return self::loadJson($path);
    }

    private static function replayMarkerActive(string $path): bool
    {
        $marker = self::loadOptionalJson($path);
        if ($marker === null) {
            return false;
        }
        $expires = (string)($marker['expires_at_utc'] ?? '');
        $ts = strtotime($expires);
        if ($ts === false) {
            throw new RuntimeException('INVALID_REPLAY_MARKER_EXPIRY');
        }
        if ($ts <= time()) {
            @unlink($path);
            return false;
        }
        return true;
    }

    public function persist(array $prepared, string $rawBody): array
    {
        if (strlen($rawBody) > self::MAX_BODY_BYTES) {
            throw new InvalidArgumentException('PAYLOAD_TOO_LARGE');
        }
        $record = $prepared['record'] ?? null;
        $bodySha = $prepared['body_sha256'] ?? null;
        if (!is_array($record) || !is_string($bodySha) || !preg_match('/^[0-9a-f]{64}$/', $bodySha)) {
            throw new RuntimeException('INVALID_PREPARED_RESEARCH_RECORD');
        }
        if (($record['research_id'] ?? null) !== self::RESEARCH_ID
            || !in_array($record['form_id'] ?? null, self::ALLOWED_FORMS, true)
            || ($record['synthetic'] ?? null) !== false
            || !is_string($record['response_id'] ?? null)
            || !preg_match('/^[0-9a-f]{64}$/', (string)$record['response_id'])) {
            throw new RuntimeException('INVALID_RESEARCH_RECORD_ENVELOPE');
        }

        $responseId = (string)$record['response_id'];
        $formId = (string)$record['form_id'];
        $paths = $this->paths($responseId, $formId);
        self::ensureDirectory(dirname($paths['lock']));
        $lock = @fopen($paths['lock'], 'c+');
        if ($lock === false || !flock($lock, LOCK_EX)) {
            throw new RuntimeException('RESEARCH_STORAGE_LOCK_UNAVAILABLE');
        }

        try {
            if (self::replayMarkerActive($paths['erased'])) {
                throw new RuntimeException('ERASED_RESPONSE_REPLAY_BLOCKED');
            }

            $existingReceipt = self::loadOptionalJson($paths['receipt']);
            if ($existingReceipt !== null) {
                if (($existingReceipt['body_sha256'] ?? null) !== $bodySha) {
                    throw new RuntimeException('IDEMPOTENCY_CONFLICT');
                }
                if (!is_file($paths['response'])) {
                    throw new RuntimeException('IDEMPOTENCY_RECEIPT_WITHOUT_RECORD');
                }
                return [
                    'status' => 'accepted',
                    'response_id' => $responseId,
                    'normalized_sha256' => (string)$existingReceipt['normalized_sha256'],
                    'inserted' => false,
                ];
            }

            $normalizedJson = self::canonicalJson($record, true);
            $normalizedSha = hash('sha256', $normalizedJson);
            $rawSha = hash('sha256', $rawBody);
            self::atomicWriteJson($paths['response'], [
                'schema_version' => 1,
                'received_at' => $record['received_at'],
                'raw_sha256' => $rawSha,
                'normalized_sha256' => $normalizedSha,
                'record' => $record,
            ]);
            self::atomicWriteJson($paths['receipt'], [
                'schema_version' => 1,
                'response_id' => $responseId,
                'form_id' => $formId,
                'accepted_at' => $record['received_at'],
                'body_sha256' => $bodySha,
                'normalized_sha256' => $normalizedSha,
                'raw_sha256' => $rawSha,
                'pii_in_receipt' => false,
            ]);
            return [
                'status' => 'accepted',
                'response_id' => $responseId,
                'normalized_sha256' => $normalizedSha,
                'inserted' => true,
            ];
        } finally {
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }

    public function getByResponseId(string $responseId): ?array
    {
        if (!preg_match('/^[0-9a-f]{64}$/', $responseId)) {
            throw new InvalidArgumentException('INVALID_RESPONSE_ID');
        }
        foreach (self::ALLOWED_FORMS as $formId) {
            $path = $this->paths($responseId, $formId)['response'];
            $wrapper = self::loadOptionalJson($path);
            if ($wrapper !== null) {
                return is_array($wrapper['record'] ?? null) ? $wrapper['record'] : null;
            }
        }
        return null;
    }

    public function setAnalysisHold(string $responseId, string $holdState): bool
    {
        if (!preg_match('/^[0-9a-f]{64}$/', $responseId)) {
            throw new InvalidArgumentException('INVALID_RESPONSE_ID');
        }
        if (!in_array($holdState, self::ALLOWED_HOLDS, true)) {
            throw new InvalidArgumentException('INVALID_HOLD_STATE');
        }
        $record = $this->getByResponseId($responseId);
        if ($record === null) {
            return false;
        }
        $path = $this->paths($responseId, (string)$record['form_id'])['hold'];
        self::atomicWriteJson($path, [
            'schema_version' => 1,
            'response_id' => $responseId,
            'hold_state' => $holdState,
        ]);
        return true;
    }

    public function clearAnalysisHold(string $responseId): bool
    {
        $record = $this->getByResponseId($responseId);
        if ($record === null) {
            return false;
        }
        $path = $this->paths($responseId, (string)$record['form_id'])['hold'];
        return !is_file($path) || @unlink($path);
    }

    public function deleteByResponseId(string $responseId): bool
    {
        $record = $this->getByResponseId($responseId);
        if ($record === null) {
            return false;
        }
        $formId = (string)$record['form_id'];
        $paths = $this->paths($responseId, $formId);
        self::ensureDirectory(dirname($paths['lock']));
        $lock = @fopen($paths['lock'], 'c+');
        if ($lock === false || !flock($lock, LOCK_EX)) {
            throw new RuntimeException('RESEARCH_STORAGE_LOCK_UNAVAILABLE');
        }
        try {
            $expires = gmdate('Y-m-d\TH:i:s\Z', time() + self::MAX_REPLAY_SECONDS);
            self::atomicWriteJson($paths['erased'], [
                'schema_version' => 1,
                'response_id' => $responseId,
                'expires_at_utc' => $expires,
            ]);
            foreach (['hold', 'receipt', 'response'] as $kind) {
                if (is_file($paths[$kind]) && !@unlink($paths[$kind])) {
                    throw new RuntimeException('RESEARCH_ERASURE_FAILED');
                }
            }
            foreach (['hold', 'receipt', 'response'] as $kind) {
                if (is_file($paths[$kind])) {
                    throw new RuntimeException('RESEARCH_ERASURE_NOT_CONFIRMED');
                }
            }
            return true;
        } finally {
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }

    public function purgeExpiredReplayMarkers(): int
    {
        $root = $this->storageRoot() . '/erased';
        if (!is_dir($root)) {
            return 0;
        }
        $count = 0;
        foreach (glob($root . '/*.json') ?: [] as $path) {
            $marker = self::loadOptionalJson($path);
            if ($marker === null) {
                continue;
            }
            $expires = strtotime((string)($marker['expires_at_utc'] ?? ''));
            if ($expires === false) {
                throw new RuntimeException('INVALID_REPLAY_MARKER_EXPIRY');
            }
            if ($expires <= time() && @unlink($path)) {
                $count++;
            }
        }
        return $count;
    }

    public function exportForm(string $formId): array
    {
        if (!in_array($formId, self::ALLOWED_FORMS, true)) {
            throw new InvalidArgumentException('UNKNOWN_FORM');
        }
        $dir = $this->storageRoot() . '/responses/' . $formId;
        if (!is_dir($dir)) {
            return [];
        }
        $out = [];
        foreach (glob($dir . '/*.json') ?: [] as $path) {
            $wrapper = self::loadOptionalJson($path);
            $record = $wrapper['record'] ?? null;
            if (!is_array($record)) {
                throw new RuntimeException('INVALID_RESEARCH_RECORD_ON_DISK');
            }
            $responseId = (string)($record['response_id'] ?? '');
            if (is_file($this->paths($responseId, $formId)['hold'])) {
                continue;
            }
            $out[] = $record;
        }
        usort($out, static function (array $a, array $b): int {
            $left = (string)($a['received_at'] ?? '') . "\0" . (string)($a['response_id'] ?? '');
            $right = (string)($b['received_at'] ?? '') . "\0" . (string)($b['response_id'] ?? '');
            return $left <=> $right;
        });
        return $out;
    }
}
