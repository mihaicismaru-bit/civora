<?php
declare(strict_types=1);

final class EuconsResearchPersistedBundleExport
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const ALLOWED_FORMS = ['AI4WORK_ADULTS_V1', 'AI4WORK_EMPLOYERS_V1'];
    private const SHA256_RE = '/^[0-9a-f]{64}$/';
    private const CHANNEL_RE = '/^CH-[A-Z0-9]{8,32}$/';
    private const WRAPPER_KEYS = ['normalized_sha256', 'raw_sha256', 'received_at', 'record', 'schema_version'];
    private const RECEIPT_KEYS = ['accepted_at', 'body_sha256', 'form_id', 'normalized_sha256', 'pii_in_receipt', 'raw_sha256', 'response_id', 'schema_version'];
    private const RECORD_KEYS = ['answers', 'form_id', 'form_version', 'profile', 'received_at', 'recruitment_channel_id', 'research_id', 'response_id', 'schema_version', 'synthetic'];

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
        if (!self::exactKeys($record, self::RECORD_KEYS)) {
            throw new RuntimeException('RESEARCH_EXPORT_RECORD_FIELDS_MISMATCH');
        }
        if (($record['schema_version'] ?? null) !== 1
            || ($record['research_id'] ?? null) !== self::RESEARCH_ID
            || ($record['form_version'] ?? null) !== 1
            || !is_string($record['recruitment_channel_id'] ?? null)
            || !preg_match(self::CHANNEL_RE, (string)$record['recruitment_channel_id'])) {
            throw new RuntimeException('RESEARCH_EXPORT_RECORD_CONTRACT_MISMATCH');
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

        $recomputedNormalizedSha = hash('sha256', self::canonicalJson($record, true));
        if (!hash_equals($recomputedNormalizedSha, (string)$wrapper['normalized_sha256'])) {
            throw new RuntimeException('RESEARCH_EXPORT_NORMALIZED_HASH_MISMATCH');
        }
    }

    private static function assertReceiptCensus(string $root, array $knownResponseIds): void
    {
        $receiptDir = $root . '/receipts';
        if (!is_dir($receiptDir)) {
            if ($knownResponseIds !== []) {
                throw new RuntimeException('RESEARCH_EXPORT_RECEIPT_STORE_MISSING');
            }
            return;
        }

        foreach (glob($receiptDir . '/*.json') ?: [] as $receiptPath) {
            $receiptResponseId = pathinfo($receiptPath, PATHINFO_FILENAME);
            if (!preg_match(self::SHA256_RE, $receiptResponseId)) {
                throw new RuntimeException('RESEARCH_EXPORT_RECEIPT_FILENAME_INVALID');
            }
            if (!isset($knownResponseIds[$receiptResponseId])) {
                throw new RuntimeException('RESEARCH_EXPORT_ORPHAN_RECEIPT');
            }
        }
    }

    public function buildPersistedBundles(): array
    {
        $root = $this->runtime->storageRoot();
        $bundles = [];
        $knownResponseIds = [];

        foreach (self::ALLOWED_FORMS as $formId) {
            $dir = $root . '/responses/' . $formId;
            if (!is_dir($dir)) {
                continue;
            }
            foreach (glob($dir . '/*.json') ?: [] as $responsePath) {
                $responseId = pathinfo($responsePath, PATHINFO_FILENAME);
                if (!preg_match(self::SHA256_RE, $responseId)) {
                    throw new RuntimeException('RESEARCH_EXPORT_FILENAME_RESPONSE_ID_INVALID');
                }
                if (isset($knownResponseIds[$responseId])) {
                    throw new RuntimeException('RESEARCH_EXPORT_DUPLICATE_RESPONSE_ID');
                }
                $knownResponseIds[$responseId] = true;

                $receiptPath = $root . '/receipts/' . $responseId . '.json';
                if (!is_file($receiptPath)) {
                    throw new RuntimeException('RESEARCH_EXPORT_RECEIPT_MISSING');
                }
                if (is_file($root . '/holds/' . $responseId . '.json')) {
                    continue;
                }
                $wrapper = self::loadJson($responsePath);
                $receipt = self::loadJson($receiptPath);
                self::assertBundleIntegrity($responseId, $formId, $wrapper, $receipt);
                $bundles[] = [
                    'filename_response_id' => $responseId,
                    'wrapper' => $wrapper,
                    'receipt' => $receipt,
                ];
            }
        }

        self::assertReceiptCensus($root, $knownResponseIds);

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
