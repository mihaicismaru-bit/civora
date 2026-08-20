<?php
declare(strict_types=1);

final class EuconsCrmRuntime
{
    private string $dataRoot;
    private array $contract;

    public function __construct(string $dataRoot, ?string $euconsRoot = null)
    {
        $this->dataRoot = rtrim($dataRoot, '/');
        $root = $euconsRoot ?: dirname(__DIR__, 3);
        $this->contract = self::loadJson($root . '/crm/crm_contract.json');
    }

    private static function loadJson(string $path): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) throw new RuntimeException('CRM_CONTRACT_UNAVAILABLE');
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) throw new RuntimeException('CRM_CONTRACT_INVALID');
        return $data;
    }

    private static function ensureDirectory(string $path): void
    {
        if (!is_dir($path) && !@mkdir($path, 0700, true) && !is_dir($path)) {
            throw new RuntimeException('CRM_STORAGE_UNAVAILABLE');
        }
    }

    private static function atomicWrite(string $path, array $value): void
    {
        self::ensureDirectory(dirname($path));
        $tmp = tempnam(dirname($path), '.crm-');
        if ($tmp === false) throw new RuntimeException('CRM_STORAGE_PREPARE_FAILED');
        try {
            $json = json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
            if (@file_put_contents($tmp, $json, LOCK_EX) === false) throw new RuntimeException('CRM_STORAGE_WRITE_FAILED');
            @chmod($tmp, 0600);
            if (!@rename($tmp, $path)) throw new RuntimeException('CRM_STORAGE_COMMIT_FAILED');
        } finally {
            if (is_file($tmp)) @unlink($tmp);
        }
    }

    private static function fold(string $value): string
    {
        $value = strtolower(trim($value));
        if (function_exists('iconv')) {
            $ascii = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $value);
            if ($ascii !== false) $value = $ascii;
        }
        $value = preg_replace('/[^a-z0-9]+/', ' ', $value) ?? $value;
        return trim($value);
    }

    private static function hid(string $namespace, string $value): string
    {
        $digest = hash('sha256', $namespace . '|' . $value);
        return strtoupper(substr($namespace, 0, 3)) . '-' . substr($digest, 0, 24);
    }

    private static function emptyState(): array
    {
        return [
            'schema_version' => 1,
            'revision' => 0,
            'organizations' => [],
            'contacts' => [],
            'leads' => [],
            'opportunities' => [],
            'offers' => [],
            'activities' => [],
        ];
    }

    private static function appendActivity(array &$state, string $eventType, string $entityType, string $entityId, array $details, string $at): void
    {
        $state['activities'][] = [
            'sequence' => count($state['activities']) + 1,
            'event_type' => $eventType,
            'entity_type' => $entityType,
            'entity_id' => $entityId,
            'at' => $at,
            'details' => $details,
        ];
    }

    public function ingest(array $processed, ?string $at = null): array
    {
        if (($processed['engine_id'] ?? null) !== 'EUCONS_E11_LEAD_ENGINE' || ($processed['record_state'] ?? null) !== 'QUALIFIED_INTAKE') {
            throw new RuntimeException('CRM_UNSUPPORTED_LEAD_RECORD');
        }
        $dedupe = (string)($processed['dedupe_key'] ?? '');
        if (!preg_match('/^[0-9a-f]{64}$/', $dedupe)) throw new RuntimeException('CRM_DEDUPE_REQUIRED');
        $leadPayload = $processed['lead'] ?? [];
        if (empty($leadPayload['email']) || empty($leadPayload['contact_name'])) throw new RuntimeException('CRM_CONTACT_REQUIRED');
        if (($processed['consent']['privacy_ack'] ?? false) !== true) throw new RuntimeException('CRM_PRIVACY_ACK_REQUIRED');

        $at = $at ?: gmdate('c');
        $crmDir = $this->dataRoot . '/crm';
        self::ensureDirectory($crmDir);
        $lockPath = $crmDir . '/state.lock';
        $lock = @fopen($lockPath, 'c+');
        if ($lock === false || !flock($lock, LOCK_EX)) throw new RuntimeException('CRM_LOCK_UNAVAILABLE');

        try {
            $statePath = $crmDir . '/state.json';
            $state = is_file($statePath) ? self::loadJson($statePath) : self::emptyState();
            foreach ($state['leads'] as $existing) {
                if (($existing['dedupe_key'] ?? '') === $dedupe) {
                    self::appendActivity($state, 'LEAD_SEEN_AGAIN', 'lead', $existing['id'], ['dedupe_key' => $dedupe], $at);
                    $state['revision']++;
                    self::atomicWrite($statePath, $state);
                    return ['status' => 'accepted', 'lead_id' => $existing['id'], 'stage' => $existing['stage'], 'idempotent_replay' => true];
                }
            }

            $organizationName = trim((string)($leadPayload['organization_name'] ?? '')) ?: 'UNSPECIFIED_ORGANIZATION';
            $orgId = self::hid('organization', self::fold($organizationName));
            $contactId = self::hid('contact', strtolower(trim((string)$leadPayload['email'])));
            $leadId = self::hid('lead', $dedupe);

            if (!isset($state['organizations'][$orgId])) {
                $state['organizations'][$orgId] = [
                    'id' => $orgId,
                    'name' => $organizationName,
                    'audience_id' => (string)($leadPayload['audience_id'] ?? ''),
                    'created_from_lead_id' => $leadId,
                ];
                self::appendActivity($state, 'ORGANIZATION_CREATED', 'organization', $orgId, ['source' => 'E11'], $at);
            }
            if (!isset($state['contacts'][$contactId])) {
                $state['contacts'][$contactId] = [
                    'id' => $contactId,
                    'name' => (string)$leadPayload['contact_name'],
                    'email' => (string)$leadPayload['email'],
                    'phone' => (string)($leadPayload['phone'] ?? ''),
                    'organization_id' => $orgId,
                    'consent' => $processed['consent'],
                ];
                self::appendActivity($state, 'CONTACT_CREATED', 'contact', $contactId, ['source' => 'E11'], $at);
            }
            $state['leads'][$leadId] = [
                'id' => $leadId,
                'dedupe_key' => $dedupe,
                'organization_id' => $orgId,
                'contact_id' => $contactId,
                'stage' => 'NEW',
                'owner' => (string)$this->contract['ownership']['default_owner'],
                'next_action' => (string)($processed['next_action'] ?? 'REQUEST_MISSING_DATA'),
                'scores' => $processed['scores'] ?? [],
                'matching_profile' => $processed['matching_profile'] ?? [],
                'consent' => $processed['consent'],
                'retention_class' => 'LEAD_INQUIRY',
                'last_material_activity_at' => $at,
            ];
            self::appendActivity($state, 'LEAD_CREATED', 'lead', $leadId, ['stage' => 'NEW', 'source' => 'E11'], $at);
            $state['revision']++;
            self::atomicWrite($statePath, $state);
            return ['status' => 'accepted', 'lead_id' => $leadId, 'stage' => 'NEW', 'idempotent_replay' => false];
        } finally {
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }
}
