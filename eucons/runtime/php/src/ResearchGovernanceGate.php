<?php
declare(strict_types=1);

final class EuconsResearchGovernanceGate
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const APPROVED_EXTERNAL_STATUSES = ['APPROVED', 'PASS', 'FROZEN'];
    private const SEMANTIC_ATTESTATION_STATUSES = ['APPROVED', 'PASS'];
    private const REQUIRED_EXTERNAL_KEYS = [
        'privacy_notice',
        'lawful_basis_or_lia',
        'processor_chain',
        'provider_account_role_reconciliation',
        'live_hosting_service_mapping',
        'live_public_privacy_surface_reconciliation',
        'provider_annex_4_5',
        'provider_server_logging_profile',
        'account_server_logging_binding',
        'retention_and_deletion',
        'data_subject_rights_procedure',
        'dpia_screening_or_completed_dpia',
        'research_only_store_binding',
        'provider_bound_test_twin_smoke',
    ];

    private string $researchRoot;

    public function __construct(string $researchRoot)
    {
        $resolved = realpath($researchRoot);
        $this->researchRoot = $resolved !== false ? $resolved : rtrim($researchRoot, '/\\');
    }

    private static function loadJson(string $path): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) {
            throw new RuntimeException('RESEARCH_GOVERNANCE_ARTIFACT_UNAVAILABLE');
        }
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) {
            throw new RuntimeException('RESEARCH_GOVERNANCE_ARTIFACT_INVALID');
        }
        return $data;
    }

    private function artifact(string $name): array
    {
        if ($name === '' || basename($name) !== $name) {
            throw new RuntimeException('RESEARCH_GOVERNANCE_ARTIFACT_PATH_INVALID');
        }
        return self::loadJson($this->researchRoot . '/' . $name);
    }

    private static function nonPlaceholder(mixed $value): bool
    {
        if (!is_string($value) || trim($value) === '') {
            return false;
        }
        $normalized = strtoupper(trim($value));
        foreach (['DE COMPLETAT', 'DE APROBAT', 'TO_BE_', 'OPEN_BEFORE_PRODUCTION', 'PENDING_CONTROLLER'] as $marker) {
            if (str_contains($normalized, $marker)) {
                return false;
            }
        }
        return true;
    }

    private function resolveLocalReference(mixed $reference): ?string
    {
        if (!is_string($reference) || trim($reference) === '') {
            return null;
        }
        $reference = trim($reference);
        if (str_contains($reference, '://') || str_starts_with($reference, 'gdrive:') || str_starts_with($reference, 'gmail:')) {
            return null;
        }
        $candidate = realpath($this->researchRoot . '/' . $reference);
        $root = realpath($this->researchRoot);
        if ($candidate === false || $root === false || !is_file($candidate)) {
            return null;
        }
        $prefix = rtrim($root, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR;
        if (!str_starts_with($candidate, $prefix)) {
            return null;
        }
        return $candidate;
    }

    private function externalEvidenceReady(array $manifest): bool
    {
        $evidence = $manifest['required_external_or_operational_evidence'] ?? null;
        if (!is_array($evidence)) {
            return false;
        }
        $actualKeys = array_keys($evidence);
        $expectedKeys = self::REQUIRED_EXTERNAL_KEYS;
        sort($actualKeys, SORT_STRING);
        sort($expectedKeys, SORT_STRING);
        if ($actualKeys !== $expectedKeys) {
            return false;
        }

        foreach (self::REQUIRED_EXTERNAL_KEYS as $key) {
            $binding = $evidence[$key] ?? null;
            if (!is_array($binding)
                || !in_array($binding['status'] ?? null, self::APPROVED_EXTERNAL_STATUSES, true)
                || !is_string($binding['reference'] ?? null)
                || trim((string)$binding['reference']) === ''
                || !is_string($binding['sha256'] ?? null)
                || !preg_match('/^[0-9a-f]{64}$/', (string)$binding['sha256'])) {
                return false;
            }
            $path = $this->resolveLocalReference($binding['reference']);
            if ($path === null || hash_file('sha256', $path) !== $binding['sha256']) {
                return false;
            }
            if (in_array($binding['status'], self::SEMANTIC_ATTESTATION_STATUSES, true)) {
                try {
                    $artifact = self::loadJson($path);
                } catch (Throwable) {
                    return false;
                }
                if (($artifact['research_id'] ?? null) !== self::RESEARCH_ID
                    || ($artifact['evidence_binding_key'] ?? null) !== $key
                    || ($artifact['synthetic'] ?? false) === true) {
                    return false;
                }
                foreach (['evidence_class', 'mode', 'artifact_class'] as $field) {
                    $marker = $artifact[$field] ?? null;
                    if (is_string($marker)) {
                        $upper = strtoupper($marker);
                        if (str_contains($upper, 'TEST_TWIN') || str_contains($upper, 'NON_EVIDENCE') || str_contains($upper, 'SYNTHETIC')) {
                            return false;
                        }
                    }
                }
            }
        }
        return true;
    }

    public function productionReady(): bool
    {
        try {
            $contract = $this->artifact('form_contract.json');
            $manifest = $this->artifact('PROD_ACTIVATION_MANIFEST_DRAFT.json');
            $controller = $this->artifact('CONTROLLER_DETERMINATION_DRAFT.json');
            $frame = $this->artifact('COLLECTION_FRAME_DRAFT.json');
            $dpia = $this->artifact('GDPR_DPIA_SCREENING_DRAFT.json');
            $article13 = $this->artifact('ARTICLE13_NOTICE_SNAPSHOT_DRAFT.json');
        } catch (Throwable) {
            return false;
        }

        foreach ([$contract, $manifest, $controller, $frame, $dpia, $article13] as $artifact) {
            if (($artifact['research_id'] ?? null) !== self::RESEARCH_ID) {
                return false;
            }
        }

        if (($contract['production_enabled'] ?? false) !== true
            || ($contract['crm_integration'] ?? null) !== 'FORBIDDEN'
            || ($contract['commercial_analytics'] ?? null) !== 'FORBIDDEN') {
            return false;
        }

        if (($manifest['state'] ?? null) !== 'APPROVED_FOR_PROD'
            || ($manifest['approved_for_prod'] ?? false) !== true
            || ($manifest['collection_enabled'] ?? false) !== true
            || ($manifest['deploy_authorized'] ?? false) !== true
            || ($manifest['real_collection_authorized'] ?? false) !== true
            || ($manifest['activation_mode'] ?? null) !== 'PROD_REAL_EVIDENCE_ONLY'
            || ($manifest['test_twin_policy'] ?? null) !== 'TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE'
            || !self::nonPlaceholder($manifest['explicit_user_approval_reference'] ?? null)
            || !self::nonPlaceholder($manifest['approval_timestamp'] ?? null)) {
            return false;
        }

        $controllerIdentity = $controller['controller'] ?? null;
        if (!is_array($controllerIdentity)
            || ($controllerIdentity['legal_name'] ?? null) !== 'EUROCONSULT SRL'
            || ($controller['approved'] ?? false) !== true
            || ($controller['collection_enabled'] ?? false) !== true
            || ($controller['nf06_reference_eligible'] ?? false) !== true
            || !self::nonPlaceholder($controller['privacy_contact'] ?? null)) {
            return false;
        }

        $frameApproval = $frame['approval'] ?? null;
        $nf06 = $frame['nf06_handoff'] ?? null;
        if (($frame['frame_status'] ?? null) !== 'APPROVED_FOR_PROD'
            || ($frame['collection_enabled'] ?? false) !== true
            || !is_array($frameApproval)
            || ($frameApproval['approved'] ?? false) !== true
            || ($frameApproval['approved_for_prod'] ?? false) !== true
            || !is_array($nf06)
            || ($nf06['eligible_now'] ?? false) !== true) {
            return false;
        }

        if (($dpia['approved'] ?? false) !== true
            || ($dpia['collection_enabled'] ?? false) !== true
            || !in_array($dpia['screening_conclusion'] ?? null, [
                'DPIA_NOT_REQUIRED_APPROVED',
                'DPIA_REQUIRED_COMPLETED_AND_APPROVED',
            ], true)) {
            return false;
        }

        $surface = $article13['surface_fields'] ?? null;
        $noticeApproval = $article13['approval'] ?? null;
        if (($article13['approved'] ?? false) !== true
            || ($article13['collection_enabled'] ?? false) !== true
            || !is_array($surface)
            || ($surface['operator_legal_name'] ?? null) !== 'EUROCONSULT SRL'
            || !self::nonPlaceholder($surface['operator_contact_details'] ?? null)
            || !self::nonPlaceholder($surface['privacy_contact'] ?? null)
            || !self::nonPlaceholder($surface['legal_basis'] ?? null)
            || !is_array($noticeApproval)
            || ($noticeApproval['controller_approved'] ?? false) !== true
            || !self::nonPlaceholder($noticeApproval['approval_reference'] ?? null)) {
            return false;
        }

        if (!$this->externalEvidenceReady($manifest)) {
            return false;
        }

        return trim((string)(getenv('AI4WORK_RESEARCH_PROD_ENABLED') ?: '')) === '1';
    }
}
