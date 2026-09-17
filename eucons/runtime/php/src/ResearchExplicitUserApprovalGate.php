<?php
declare(strict_types=1);

final class EuconsResearchExplicitUserApprovalGate
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const APPROVAL_SCHEMA = 'eucons.ai4work_explicit_user_approval_receipt.v0.1';
    private const APPROVAL_SOURCE = 'HUMAN_EXPLICIT_USER_APPROVAL';
    private const APPROVAL_ACTION = 'REAL_COLLECTION_PROD_ACTIVATION_ONLY';
    private const CLOCK_SKEW_SECONDS = 300;
    private const REQUIRED_BINDINGS = [
        'need_analysis_plan' => 'NEED_ANALYSIS_PLAN_DRAFT.json',
        'collection_frame' => 'COLLECTION_FRAME_DRAFT.json',
        'form_contract' => 'form_contract.json',
        'invitation_catalog' => 'RESEARCH_INVITATION_CATALOG_DRAFT.json',
        'collection_channel_register' => 'COLLECTION_CHANNEL_REGISTER_DRAFT.json',
    ];

    private string $researchRoot;

    public function __construct(string $researchRoot)
    {
        $resolved = realpath($researchRoot);
        $this->researchRoot = $resolved !== false ? $resolved : rtrim($researchRoot, '/\\');
    }

    private function resolveLocalReference(mixed $reference): ?string
    {
        if (!is_string($reference) || trim($reference) === '') {
            return null;
        }
        $reference = trim($reference);
        if (basename($reference) !== $reference
            || str_contains($reference, '://')
            || str_starts_with($reference, 'gdrive:')
            || str_starts_with($reference, 'gmail:')) {
            return null;
        }
        $candidate = realpath($this->researchRoot . '/' . $reference);
        $root = realpath($this->researchRoot);
        if ($candidate === false || $root === false || !is_file($candidate)) {
            return null;
        }
        $prefix = rtrim($root, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR;
        return str_starts_with($candidate, $prefix) ? $candidate : null;
    }

    private static function loadJson(string $path): ?array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) {
            return null;
        }
        try {
            $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        } catch (Throwable) {
            return null;
        }
        return is_array($data) ? $data : null;
    }

    private static function validSha256(mixed $value): bool
    {
        return is_string($value) && preg_match('/^[0-9a-f]{64}$/', $value) === 1;
    }

    private static function validApprovalTimestamp(mixed $value): bool
    {
        if (!is_string($value) || preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/', $value) !== 1) {
            return false;
        }
        $parsed = strtotime($value);
        return $parsed !== false && $parsed <= time() + self::CLOCK_SKEW_SECONDS;
    }

    public function ready(array $manifest): bool
    {
        if (($manifest['research_id'] ?? null) !== self::RESEARCH_ID) {
            return false;
        }
        $reference = $manifest['explicit_user_approval_reference'] ?? null;
        $digest = $manifest['explicit_user_approval_sha256'] ?? null;
        if (!self::validSha256($digest)) {
            return false;
        }
        $path = $this->resolveLocalReference($reference);
        if ($path === null || !hash_equals((string)$digest, hash_file('sha256', $path))) {
            return false;
        }
        $receipt = self::loadJson($path);
        if ($receipt === null
            || ($receipt['schema_version'] ?? null) !== self::APPROVAL_SCHEMA
            || ($receipt['research_id'] ?? null) !== self::RESEARCH_ID
            || ($receipt['status'] ?? null) !== 'APPROVED'
            || ($receipt['artifact_class'] ?? null) !== 'CONTROL_ARTIFACT_NOT_EVIDENCE'
            || ($receipt['synthetic'] ?? null) !== false
            || ($receipt['approval_source'] ?? null) !== self::APPROVAL_SOURCE
            || ($receipt['authorized_action'] ?? null) !== self::APPROVAL_ACTION
            || ($receipt['approved'] ?? false) !== true
            || ($receipt['real_collection_authorized'] ?? false) !== true
            || ($receipt['merge_authorized'] ?? null) !== false
            || ($receipt['deploy_authorized'] ?? null) !== false
            || ($receipt['canonicalization_authorized'] ?? null) !== false
            || ($receipt['test_twin_policy'] ?? null) !== 'TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE'
            || ($receipt['evidence_use'] ?? null) !== 'CONTROL_ONLY_NOT_NEED_EVIDENCE'
            || !is_string($receipt['approved_by_user_reference'] ?? null)
            || trim((string)$receipt['approved_by_user_reference']) === ''
            || !self::validApprovalTimestamp($receipt['approved_at'] ?? null)
            || ($manifest['approval_timestamp'] ?? null) !== ($receipt['approved_at'] ?? null)) {
            return false;
        }

        $bindings = $receipt['bound_artifacts'] ?? null;
        if (!is_array($bindings)) {
            return false;
        }
        $actualKeys = array_keys($bindings);
        $expectedKeys = array_keys(self::REQUIRED_BINDINGS);
        sort($actualKeys, SORT_STRING);
        sort($expectedKeys, SORT_STRING);
        if ($actualKeys !== $expectedKeys) {
            return false;
        }

        foreach (self::REQUIRED_BINDINGS as $key => $expectedReference) {
            $binding = $bindings[$key] ?? null;
            if (!is_array($binding)
                || ($binding['reference'] ?? null) !== $expectedReference
                || !self::validSha256($binding['sha256'] ?? null)) {
                return false;
            }
            $boundPath = $this->resolveLocalReference($expectedReference);
            if ($boundPath === null || !hash_equals((string)$binding['sha256'], hash_file('sha256', $boundPath))) {
                return false;
            }
        }

        return true;
    }
}
