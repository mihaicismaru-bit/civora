<?php
declare(strict_types=1);

final class EuconsRetentionRuntime
{
    private string $dataRoot;
    private array $contract;

    public function __construct(string $dataRoot, ?string $euconsRoot = null)
    {
        $this->dataRoot = rtrim($dataRoot, '/');
        $root = $euconsRoot ?: dirname(__DIR__, 3);
        $this->contract = self::loadJson($root . '/security/privacy_security_contract.json');
    }

    private static function loadJson(string $path): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) throw new RuntimeException('RETENTION_CONTRACT_UNAVAILABLE');
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) throw new RuntimeException('RETENTION_CONTRACT_INVALID');
        return $data;
    }

    private static function atomicWrite(string $path, array $value): void
    {
        $dir = dirname($path);
        if (!is_dir($dir) && !@mkdir($dir, 0700, true) && !is_dir($dir)) throw new RuntimeException('RETENTION_STORAGE_UNAVAILABLE');
        $tmp = tempnam($dir, '.ret-');
        if ($tmp === false) throw new RuntimeException('RETENTION_PREPARE_FAILED');
        try {
            $json = json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
            if (@file_put_contents($tmp, $json, LOCK_EX) === false) throw new RuntimeException('RETENTION_WRITE_FAILED');
            @chmod($tmp, 0600);
            if (!@rename($tmp, $path)) throw new RuntimeException('RETENTION_COMMIT_FAILED');
        } finally {
            if (is_file($tmp)) @unlink($tmp);
        }
    }

    private function classDays(string $class): int
    {
        $days = $this->contract['retention']['classes'][$class]['days'] ?? null;
        if (!is_int($days) && !is_float($days)) throw new RuntimeException('RETENTION_CLASS_UNKNOWN');
        return (int)$days;
    }

    private function held(string $requestId): bool
    {
        $path = $this->dataRoot . '/holds/' . $requestId . '.json';
        if (!is_file($path)) return false;
        $hold = self::loadJson($path);
        return !empty($hold['reason_code']) && !empty($hold['review_at']);
    }

    public function sweep(?string $nowIso = null): array
    {
        $now = new DateTimeImmutable($nowIso ?: 'now', new DateTimeZone('UTC'));
        $deletedLeadFiles = 0;
        $deletedReceiptFiles = 0;
        $deletedCrmLeads = 0;
        $leadDir = $this->dataRoot . '/leads';

        if (is_dir($leadDir)) {
            foreach (glob($leadDir . '/*.json') ?: [] as $path) {
                $record = self::loadJson($path);
                $requestId = basename($path, '.json');
                if ($this->held($requestId)) continue;
                $received = (string)($record['received_at'] ?? '');
                if ($received === '') continue;
                $at = new DateTimeImmutable($received);
                if ($at->modify('+' . $this->classDays('LEAD_INQUIRY') . ' days') > $now) continue;
                if (@unlink($path)) $deletedLeadFiles++;
                $receipt = $this->dataRoot . '/receipts/' . $requestId . '.json';
                if (is_file($receipt) && @unlink($receipt)) $deletedReceiptFiles++;
                $lock = $this->dataRoot . '/locks/' . $requestId . '.lock';
                if (is_file($lock)) @unlink($lock);
            }
        }

        $crmPath = $this->dataRoot . '/crm/state.json';
        if (is_file($crmPath)) {
            $lockPath = $this->dataRoot . '/crm/state.lock';
            $lock = @fopen($lockPath, 'c+');
            if ($lock === false || !flock($lock, LOCK_EX)) throw new RuntimeException('RETENTION_CRM_LOCK_UNAVAILABLE');
            try {
                $state = self::loadJson($crmPath);
                foreach ($state['leads'] as $leadId => $lead) {
                    $stage = (string)($lead['stage'] ?? 'NEW');
                    $class = in_array($stage, ['NEW', 'QUALIFIED'], true) ? 'LEAD_INQUIRY' : 'COMMERCIAL_RELATIONSHIP';
                    $last = (string)($lead['last_material_activity_at'] ?? '');
                    if ($last === '') continue;
                    $at = new DateTimeImmutable($last);
                    if ($at->modify('+' . $this->classDays($class) . ' days') > $now) continue;
                    $contactId = (string)($lead['contact_id'] ?? '');
                    $orgId = (string)($lead['organization_id'] ?? '');
                    unset($state['leads'][$leadId]);
                    $deletedCrmLeads++;
                    $state['activities'][] = [
                        'sequence' => count($state['activities']) + 1,
                        'event_type' => 'RETENTION_ERASED',
                        'entity_type' => 'lead',
                        'entity_id' => $leadId,
                        'at' => $now->format(DATE_ATOM),
                        'details' => ['retention_class' => $class],
                    ];
                    $contactStillUsed = false;
                    $orgStillUsed = false;
                    foreach ($state['leads'] as $remaining) {
                        if (($remaining['contact_id'] ?? '') === $contactId) $contactStillUsed = true;
                        if (($remaining['organization_id'] ?? '') === $orgId) $orgStillUsed = true;
                    }
                    if (!$contactStillUsed) unset($state['contacts'][$contactId]);
                    if (!$orgStillUsed) unset($state['organizations'][$orgId]);
                }
                if ($deletedCrmLeads > 0) {
                    $state['revision'] = (int)($state['revision'] ?? 0) + 1;
                    self::atomicWrite($crmPath, $state);
                }
            } finally {
                flock($lock, LOCK_UN);
                fclose($lock);
            }
        }

        $receiptDir = $this->dataRoot . '/maintenance/receipts';
        if (!is_dir($receiptDir) && !@mkdir($receiptDir, 0700, true) && !is_dir($receiptDir)) throw new RuntimeException('RETENTION_RECEIPT_DIR_UNAVAILABLE');
        $receipt = [
            'schema_version' => 1,
            'operation' => 'retention_sweep',
            'ran_at' => $now->format(DATE_ATOM),
            'deleted_lead_files' => $deletedLeadFiles,
            'deleted_receipt_files' => $deletedReceiptFiles,
            'deleted_crm_leads' => $deletedCrmLeads,
            'pii_in_receipt' => false,
        ];
        self::atomicWrite($receiptDir . '/' . $now->format('Ymd-His') . '.json', $receipt);
        return $receipt;
    }
}
