<?php
declare(strict_types=1);

final class EuconsResearchChannelGate
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const REGISTER_SCHEMA = 'eucons.ai4work_collection_channel_register.v0.2';
    private const CATALOG_SCHEMA = 'eucons.ai4work_research_invitation_catalog.v0.1';
    private const TARGET_REGIONS = ['Centru', 'Sud-Muntenia', 'Sud-Vest Oltenia'];
    private const TARGET_AUDIENCES = ['adults', 'employers'];
    private const REGISTER_KEYS = ['entries', 'invitation_catalog', 'research_id', 'schema_version'];
    private const CATALOG_BINDING_KEYS = ['reference', 'sha256'];
    private const ENTRY_KEYS = [
        'audience_scope',
        'channel_id',
        'channel_type',
        'closed_at',
        'distributor_role',
        'invitation_version',
        'non_coercion_confirmed',
        'opened_at',
        'region_scope',
    ];
    private const REQUIRED_SAFEGUARDS = [
        'no_commercial_marketing',
        'no_direct_identifier_request',
        'no_disadvantage',
        'no_incentive_condition',
        'no_project_enrolment_condition',
        'one_response_request',
        'privacy_notice_before_form',
        'voluntary_participation',
    ];

    private array $channelsById = [];
    private array $catalogByVersion = [];

    public function __construct(string $registerPath)
    {
        $register = self::loadJson($registerPath, 'COLLECTION_CHANNEL_REGISTER');
        if (self::isList($register)) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $keys = array_keys($register);
        sort($keys, SORT_STRING);
        if ($keys !== self::REGISTER_KEYS
            || ($register['schema_version'] ?? null) !== self::REGISTER_SCHEMA
            || ($register['research_id'] ?? null) !== self::RESEARCH_ID
            || !is_array($register['entries'] ?? null)
            || !self::isList($register['entries'])) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $this->catalogByVersion = $this->loadBoundApprovedCatalog($registerPath, $register['invitation_catalog'] ?? null);
        foreach ($register['entries'] as $entry) {
            $this->validateAndAddEntry($entry);
        }
    }

    private static function loadJson(string $path, string $prefix): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) {
            throw new RuntimeException($prefix . '_UNAVAILABLE');
        }
        try {
            $data = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
        } catch (JsonException $e) {
            throw new RuntimeException($prefix . '_INVALID', 0, $e);
        }
        if (!is_array($data)) {
            throw new RuntimeException($prefix . '_INVALID');
        }
        return $data;
    }

    private static function isList(array $value): bool
    {
        return $value === [] || array_keys($value) === range(0, count($value) - 1);
    }

    private static function parseTimestamp(mixed $value): DateTimeImmutable
    {
        if (!is_string($value) || trim($value) === '') {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        try {
            $parsed = new DateTimeImmutable($value);
        } catch (Exception $e) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID', 0, $e);
        }
        if (!preg_match('/(?:Z|[+-]\d{2}:\d{2})$/', trim($value))) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        return $parsed->setTimezone(new DateTimeZone('UTC'));
    }

    private function loadBoundApprovedCatalog(string $registerPath, mixed $binding): array
    {
        if (!is_array($binding) || self::isList($binding)) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        $keys = array_keys($binding);
        sort($keys, SORT_STRING);
        if ($keys !== self::CATALOG_BINDING_KEYS) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $reference = $binding['reference'] ?? null;
        $sha256 = $binding['sha256'] ?? null;
        if (!is_string($reference) || trim($reference) === '' || basename($reference) !== $reference
            || !is_string($sha256) || !preg_match('/^[0-9a-f]{64}$/', $sha256)) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $catalogPath = dirname($registerPath) . DIRECTORY_SEPARATOR . $reference;
        $actualSha = @hash_file('sha256', $catalogPath);
        if (!is_string($actualSha) || !hash_equals($sha256, $actualSha)) {
            throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_MISMATCH');
        }

        $catalog = self::loadJson($catalogPath, 'COLLECTION_CHANNEL_INVITATION_CATALOG');
        if (self::isList($catalog)
            || ($catalog['schema_version'] ?? null) !== self::CATALOG_SCHEMA
            || ($catalog['research_id'] ?? null) !== self::RESEARCH_ID
            || ($catalog['status'] ?? null) !== 'APPROVED_FOR_PROD'
            || ($catalog['evidence_class'] ?? null) !== 'CONTROL_ARTIFACT_NOT_EVIDENCE'
            || ($catalog['approved_for_prod'] ?? false) !== true
            || ($catalog['test_twin_policy'] ?? null) !== 'TEST_TWIN_NON_EVIDENCE_PERMANENTLY_NON_PROMOTABLE'
            || ($catalog['merge_authorized'] ?? null) !== false
            || ($catalog['deploy_authorized'] ?? null) !== false
            || ($catalog['real_dissemination_authorized'] ?? null) !== false) {
            throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
        }

        $approval = $catalog['approval'] ?? null;
        if (!is_array($approval)
            || ($approval['approved_for_prod'] ?? false) !== true
            || !is_string($approval['approver_name_or_role'] ?? null)
            || trim((string)$approval['approver_name_or_role']) === ''
            || !is_string($approval['approval_date'] ?? null)
            || trim((string)$approval['approval_date']) === '') {
            throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
        }

        $policy = $catalog['transport_policy'] ?? null;
        $expectedPolicy = [
            'channel_identifier_mode' => 'OPAQUE_URL_FRAGMENT_ONLY',
            'channel_identifier_format' => 'CH-[A-Z0-9]{8,32}',
            'query_tracking_parameters_allowed' => false,
            'commercial_tracking_allowed' => false,
            'crm_identifier_allowed' => false,
            'referrer_derived_channel_allowed' => false,
        ];
        if (!is_array($policy) || $policy !== $expectedPolicy) {
            throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
        }

        $entries = $catalog['entries'] ?? null;
        if (!is_array($entries) || !self::isList($entries) || $entries === []) {
            throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
        }
        $byVersion = [];
        $covered = [];
        foreach ($entries as $entry) {
            if (!is_array($entry) || self::isList($entry)) {
                throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
            }
            $version = $entry['invitation_version'] ?? null;
            $audiences = $entry['audience_scope'] ?? null;
            $safeguards = $entry['required_safeguards'] ?? null;
            if (!is_string($version) || !preg_match('/^[A-Z0-9][A-Z0-9_-]{5,63}$/', $version)
                || isset($byVersion[$version])
                || !is_array($audiences) || !self::isList($audiences) || $audiences === []
                || count($audiences) !== count(array_unique($audiences, SORT_STRING))) {
                throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
            }
            foreach ($audiences as $audience) {
                if (!is_string($audience) || !in_array($audience, self::TARGET_AUDIENCES, true)) {
                    throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
                }
                $covered[$audience] = true;
            }
            if (!is_array($safeguards) || self::isList($safeguards)) {
                throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
            }
            $safeguardKeys = array_keys($safeguards);
            sort($safeguardKeys, SORT_STRING);
            if ($safeguardKeys !== self::REQUIRED_SAFEGUARDS) {
                throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
            }
            foreach (self::REQUIRED_SAFEGUARDS as $safeguard) {
                if (($safeguards[$safeguard] ?? null) !== true) {
                    throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
                }
            }
            $byVersion[$version] = $audiences;
        }
        foreach (self::TARGET_AUDIENCES as $audience) {
            if (!isset($covered[$audience])) {
                throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_CATALOG_INVALID');
            }
        }
        return $byVersion;
    }

    private function validateAndAddEntry(mixed $entry): void
    {
        if (!is_array($entry) || self::isList($entry)) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        $keys = array_keys($entry);
        sort($keys, SORT_STRING);
        if ($keys !== self::ENTRY_KEYS) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $channelId = $entry['channel_id'] ?? null;
        $channelType = $entry['channel_type'] ?? null;
        if (!is_string($channelId) || !preg_match('/^CH-[A-Z0-9]{8,32}$/', $channelId)
            || isset($this->channelsById[$channelId])) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        if (!is_string($channelType) || !preg_match('/^[a-z][a-z0-9_]{2,48}$/', $channelType)) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $regions = $entry['region_scope'] ?? null;
        $audiences = $entry['audience_scope'] ?? null;
        if (!is_array($regions) || !self::isList($regions) || $regions === []
            || count($regions) !== count(array_unique($regions, SORT_STRING))) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        foreach ($regions as $region) {
            if (!is_string($region) || !in_array($region, self::TARGET_REGIONS, true)) {
                throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
            }
        }
        if (!is_array($audiences) || !self::isList($audiences) || $audiences === []
            || count($audiences) !== count(array_unique($audiences, SORT_STRING))) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        foreach ($audiences as $audience) {
            if (!is_string($audience) || !in_array($audience, self::TARGET_AUDIENCES, true)) {
                throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
            }
        }

        $invitationVersion = $entry['invitation_version'] ?? null;
        if (!is_string($invitationVersion) || trim($invitationVersion) === ''
            || !isset($this->catalogByVersion[$invitationVersion])) {
            throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_VERSION_NOT_APPROVED');
        }
        foreach ($audiences as $audience) {
            if (!in_array($audience, $this->catalogByVersion[$invitationVersion], true)) {
                throw new RuntimeException('COLLECTION_CHANNEL_INVITATION_AUDIENCE_MISMATCH');
            }
        }
        if (!is_string($entry['distributor_role'] ?? null) || trim((string)$entry['distributor_role']) === '') {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }
        if (($entry['non_coercion_confirmed'] ?? null) !== true) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $opened = self::parseTimestamp($entry['opened_at'] ?? null);
        $closed = self::parseTimestamp($entry['closed_at'] ?? null);
        if ($closed < $opened) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
        }

        $entry['_opened_utc'] = $opened;
        $entry['_closed_utc'] = $closed;
        $this->channelsById[$channelId] = $entry;
    }

    public function assertApprovedRecord(array $record, ?DateTimeImmutable $now = null): void
    {
        if (($record['research_id'] ?? null) !== self::RESEARCH_ID) {
            throw new RuntimeException('RESEARCH_CHANNEL_BINDING_RECORD_INVALID');
        }
        $channelId = $record['recruitment_channel_id'] ?? null;
        if (!is_string($channelId) || !preg_match('/^CH-[A-Z0-9]{8,32}$/', $channelId)) {
            throw new InvalidArgumentException('INVALID_RECRUITMENT_CHANNEL');
        }
        $channel = $this->channelsById[$channelId] ?? null;
        if (!is_array($channel)) {
            throw new InvalidArgumentException('RECRUITMENT_CHANNEL_NOT_APPROVED');
        }

        $formId = $record['form_id'] ?? null;
        $audience = match ($formId) {
            'AI4WORK_ADULTS_V1' => 'adults',
            'AI4WORK_EMPLOYERS_V1' => 'employers',
            default => null,
        };
        if ($audience === null) {
            throw new RuntimeException('RESEARCH_CHANNEL_BINDING_RECORD_INVALID');
        }
        if (!in_array($audience, $channel['audience_scope'], true)) {
            throw new InvalidArgumentException('RECRUITMENT_CHANNEL_AUDIENCE_MISMATCH');
        }

        $region = $record['profile']['region'] ?? null;
        if (!is_string($region) || !in_array($region, self::TARGET_REGIONS, true)) {
            throw new RuntimeException('RESEARCH_CHANNEL_BINDING_RECORD_INVALID');
        }
        if (!in_array($region, $channel['region_scope'], true)) {
            throw new InvalidArgumentException('RECRUITMENT_CHANNEL_REGION_MISMATCH');
        }

        $instant = ($now ?? new DateTimeImmutable('now', new DateTimeZone('UTC')))
            ->setTimezone(new DateTimeZone('UTC'));
        if ($instant < $channel['_opened_utc'] || $instant > $channel['_closed_utc']) {
            throw new InvalidArgumentException('RECRUITMENT_CHANNEL_OUTSIDE_APPROVED_WINDOW');
        }
    }
}
