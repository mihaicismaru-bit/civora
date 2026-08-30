<?php
declare(strict_types=1);

final class EuconsResearchPersistedBundleExport
{
    private const ALLOWED_FORMS = ['AI4WORK_ADULTS_V1', 'AI4WORK_EMPLOYERS_V1'];
    private const SHA256_RE = '/^[0-9a-f]{64}$/';
    private const WRAPPER_KEYS = ['normalized_sha256', 'raw_sha256', 'received_at', 'record', 'schema_version'];
    private const RECEIPT_KEYS = ['accepted_at', 'body_sha256', 'form_id', 'normalized_sha256', 'pii_in_receipt', 'raw_sha256', 'response_id', 'schema_version'];

    private EuconsResearchRuntime $runtime;

    public function __construct(EuconsResearchRuntime $runtime)
    {
        $this->runtime = $runtime;
    }

    private static function loadJson(string $path): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) {
            throw new RuntimeException('RESEARCH_EXPORT_ARTIFACT_UNAVAILABLE');
        }
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) {
            throw new RuntimeException('RESEARCH_EXPORT_ARTIFACT_INVALID');
        }
        return $data;
    }

    private static function exactKeys(array $value, array $expected): bool
    {
        $actual = array_keys($value);
        sort($actual, SORT_STRING);
        sort($expected, SORT_STRING);
        return $actual === $expected;
    }

    private static function assertBundleIntegrity(string $filenameResponseId, string $formId, array $wrapper, array $receipt): void
    {
        if (!preg_match(self::SHA256_RE, $filenameResponseId)) {
            throw new RuntimeException('RESEARCH_EXPORT_FILENAME_RESPONSE_ID_INVALID');
        }
        if (!self::exactKeys($wrapper, self::WRAPPER_KEYS)) {
            throw new RuntimeException('RESEARCH_EXPORT_WRAPPER_FIELDS_MISMATCH');
        }
        if (!self::exactKeys($receipt, self::RECEIPT_KEYS)) {
            throw new RuntimeException('RESEARCH_EXPORT_RECEIPT_FIELDS_MISMATCH');
        }
        if (($wrapper['schema_version'] ?? null) !== 1 || ($receipt['schema_version'] ?? null) !== 1) {
            throw new RuntimeException('RESEARCH_EXPORT_SCHEMA_VERSION_MISMATCH');
        }
        $record = $wrapper['record'] ?? null;
        if (!is_array($record)) {
            throw new RuntimeException('RESEARCH_EXPORT_RECORD_INVALID');
        }
        if (($record['response_id'] ?? null) !== $filenameResponseId
            || ($receipt['response_id'] ?? null) !== $filenameResponseId
            || ($record['form_id'] ?? null) !== $formId
            || ($receipt['form_id'] ?? null) !== $formId
            || ($record['synthetic'] ?? null) !== false
            || ($receipt['pii_in_receipt'] ?? null) !== false
            || ($wrapper['received_at'] ?? null) !== ($record['received_at'] ?? null)
            || ($receipt['accepted_at'] ?? null) !== ($record['received_at'] ?? null)) {
            throw new RuntimeException('RESEARCH_EXPORT_BUNDLE_BINDING_MISMATCH');
        }
        foreach (['raw_sha256', 'normalized_sha256'] as $field) {
            if (!is_string($wrapper[$field] ?? null)
                || !preg_match(self::SHA256_RE, (string)$wrapper[$field])
                || ($receipt[$field] ?? null) !== $wrapper[$field]) {
                throw new RuntimeException('RESEARCH_EXPORT_HASH_BINDING_MISMATCH');
            }
        }
        if (!is_string($receipt['body_sha256'] ?? null)
            || !preg_match(self::SHA256_RE, (string)$receipt['body_sha256'])) {
            throw new RuntimeException('RESEARCH_EXPORT_BODY_HASH_INVALID');
        }
    }

    public function buildPersistedBundles(): array
    {
        $root = $this->runtime->storageRoot();
        $bundles = [];
        $seen = [];

        foreach (self::ALLOWED_FORMS as $formId) {
            $dir = $root . '/responses/' . $formId;
            if (!is_dir($dir)) {
                continue;
            }
            foreach (glob($dir . '/*.json') ?: [] as $responsePath) {
                $responseId = pathinfo($responsePath, PATHINFO_FILENAME);
                if (isset($seen[$responseId])) {
                    throw new RuntimeException('RESEARCH_EXPORT_DUPLICATE_RESPONSE_ID');
                }
                if (is_file($root . '/holds/' . $responseId . '.json')) {
                    continue;
                }
                $receiptPath = $root . '/receipts/' . $responseId . '.json';
                if (!is_file($receiptPath)) {
                    throw new RuntimeException('RESEARCH_EXPORT_RECEIPT_MISSING');
                }
                $wrapper = self::loadJson($responsePath);
                $receipt = self::loadJson($receiptPath);
                self::assertBundleIntegrity($responseId, $formId, $wrapper, $receipt);
                $seen[$responseId] = true;
                $bundles[] = [
                    'filename_response_id' => $responseId,
                    'wrapper' => $wrapper,
                    'receipt' => $receipt,
                ];
            }
        }

        usort($bundles, static function (array $left, array $right): int {
            $leftRecord = $left['wrapper']['record'];
            $rightRecord = $right['wrapper']['record'];
            $leftKey = (string)$leftRecord['form_id'] . "\0" . (string)$leftRecord['received_at'] . "\0" . (string)$leftRecord['response_id'];
            $rightKey = (string)$rightRecord['form_id'] . "\0" . (string)$rightRecord['received_at'] . "\0" . (string)$rightRecord['response_id'];
            return $leftKey <=> $rightKey;
        });
        return $bundles;
    }
}
