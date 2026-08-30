<?php
declare(strict_types=1);

final class EuconsResearchChannelGate
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const REGISTER_SCHEMA = 'eucons.ai4work_collection_channel_register.v0.1';
    private const TARGET_REGIONS = ['Centru', 'Sud-Muntenia', 'Sud-Vest Oltenia'];
    private const TARGET_AUDIENCES = ['adults', 'employers'];
    private const REGISTER_KEYS = ['entries', 'research_id', 'schema_version'];
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

    private array $channelsById = [];

    public function __construct(string $registerPath)
    {
        $raw = @file_get_contents($registerPath);
        if ($raw === false) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_UNAVAILABLE');
        }
        try {
            $register = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
        } catch (JsonException $e) {
            throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID', 0, $e);
        }
        if (!is_array($register) || self::isList($register)) {
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

        foreach ($register['entries'] as $entry) {
            $this->validateAndAddEntry($entry);
        }
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

        foreach (['invitation_version', 'distributor_role'] as $field) {
            if (!is_string($entry[$field] ?? null) || trim((string)$entry[$field]) === '') {
                throw new RuntimeException('COLLECTION_CHANNEL_REGISTER_INVALID');
            }
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
