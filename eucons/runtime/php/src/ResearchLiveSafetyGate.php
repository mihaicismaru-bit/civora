<?php
declare(strict_types=1);

final class EuconsResearchLiveSafetyGate
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const SECURITY_SCHEMA = 'eucons.ai4work_public_surface_security_binding.v0.1';
    private const INCIDENT_SCHEMA = 'eucons.ai4work_gdpr_security_incident_response.v0.1';
    private const MAX_READBACK_AGE_SECONDS = 86400;
    private const MAX_FUTURE_SKEW_SECONDS = 300;
    private const EXPECTED_PUBLIC_ROUTES = [
        'https://eucons.ro/cercetare/ai4work-step/',
        'https://eucons.ro/cercetare/ai4work-step/adulti/',
        'https://eucons.ro/cercetare/ai4work-step/angajatori/',
    ];
    private const EXPECTED_API_ROUTE = 'https://api.eucons.ro/research/ai4work/v1/submit';
    private const REQUIRED_INCIDENT_BINDINGS = [
        'controller_approval',
        'privacy_contact_bound',
        'incident_owner_assigned',
        'breach_register_location_bound',
        'anspdcp_notification_route_live_verified',
        'processor_escalation_route_bound',
        'restore_and_recovery_control_live_verified',
        'access_and_logging_control_live_verified',
        'provider_breach_notification_contract_path_verified',
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
            throw new RuntimeException('RESEARCH_LIVE_SAFETY_ARTIFACT_UNAVAILABLE');
        }
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) {
            throw new RuntimeException('RESEARCH_LIVE_SAFETY_ARTIFACT_INVALID');
        }
        return $data;
    }

    private function artifact(string $name): array
    {
        if ($name === '' || basename($name) !== $name) {
            throw new RuntimeException('RESEARCH_LIVE_SAFETY_ARTIFACT_PATH_INVALID');
        }
        return self::loadJson($this->researchRoot . '/' . $name);
    }

    private static function nonPlaceholder(mixed $value): bool
    {
        if (!is_string($value) || trim($value) === '') {
            return false;
        }
        $upper = strtoupper(trim($value));
        foreach (['OPEN_', 'TO_BE_', 'UNRESOLVED_', 'DRAFT_', 'PENDING_'] as $prefix) {
            if (str_starts_with($upper, $prefix)) {
                return false;
            }
        }
        return !str_contains($upper, 'TEST_TWIN');
    }

    private static function isList(array $value): bool
    {
        return $value === [] || array_keys($value) === range(0, count($value) - 1);
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

    private static function canonicalSha256(array $value): string
    {
        return hash('sha256', json_encode(
            self::canonicalize($value),
            JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR
        ));
    }

    private static function freshTimestamp(mixed $value, ?int $now = null): bool
    {
        if (!is_string($value) || trim($value) === '') {
            return false;
        }
        $text = trim($value);
        if (!preg_match('/(?:Z|[+-][0-9]{2}:[0-9]{2})$/i', $text)) {
            return false;
        }
        try {
            $verified = new DateTimeImmutable($text);
        } catch (Throwable) {
            return false;
        }
        $verifiedTs = $verified->getTimestamp();
        $clock = $now ?? time();
        if ($verifiedTs > $clock + self::MAX_FUTURE_SKEW_SECONDS) {
            return false;
        }
        if ($verifiedTs < $clock - self::MAX_READBACK_AGE_SECONDS) {
            return false;
        }
        return true;
    }

    private static function parseCsp(string $value): array
    {
        $out = [];
        foreach (explode(';', $value) as $segment) {
            $segment = trim($segment);
            if ($segment === '') continue;
            $parts = preg_split('/\s+/', $segment) ?: [];
            $name = strtolower((string)array_shift($parts));
            if ($name === '' || array_key_exists($name, $out)) {
                return [];
            }
            $out[$name] = array_values(array_unique(array_map('strval', $parts)));
        }
        return $out;
    }

    private static function headerSetReady(array $headers): bool
    {
        $normalized = [];
        foreach ($headers as $key => $value) {
            $normalized[strtolower(trim((string)$key))] = trim((string)$value);
        }
        foreach (['content-security-policy', 'referrer-policy', 'x-content-type-options', 'permissions-policy', 'cache-control'] as $name) {
            if (!array_key_exists($name, $normalized)) return false;
        }
        if (strtolower($normalized['referrer-policy']) !== 'no-referrer') return false;
        if (strtolower($normalized['x-content-type-options']) !== 'nosniff') return false;
        if (!str_contains(strtolower($normalized['cache-control']), 'no-store')) return false;
        $permissions = strtolower($normalized['permissions-policy']);
        foreach (['camera=()', 'microphone=()', 'geolocation=()'] as $token) {
            if (!str_contains($permissions, $token)) return false;
        }

        $cspText = strtolower($normalized['content-security-policy']);
        foreach (["*", "'unsafe-inline'", "'unsafe-eval'", 'data:', 'blob:', 'http:', 'google-analytics', 'googletagmanager', 'facebook.com', 'connect.facebook.net', 'hotjar', 'clarity.ms', 'segment.com', 'mixpanel'] as $forbidden) {
            if (str_contains($cspText, strtolower($forbidden))) return false;
        }
        $csp = self::parseCsp($normalized['content-security-policy']);
        $required = [
            'default-src' => ["'self'"],
            'script-src' => ["'self'"],
            'style-src' => ["'self'"],
            'img-src' => ["'self'"],
            'connect-src' => ['https://api.eucons.ro'],
            'form-action' => ["'none'"],
            'base-uri' => ["'none'"],
            'object-src' => ["'none'"],
            'frame-ancestors' => ["'none'"],
            'frame-src' => ["'none'"],
            'worker-src' => ["'none'"],
            'manifest-src' => ["'none'"],
            'media-src' => ["'none'"],
        ];
        foreach ($required as $directive => $tokens) {
            if (!isset($csp[$directive])) return false;
            foreach ($tokens as $token) {
                if (!in_array($token, $csp[$directive], true)) return false;
            }
        }
        return true;
    }

    private static function securityReady(array $binding, ?int $now = null): bool
    {
        if (($binding['schema_version'] ?? null) !== self::SECURITY_SCHEMA
            || ($binding['research_id'] ?? null) !== self::RESEARCH_ID
            || ($binding['synthetic'] ?? null) !== false
            || ($binding['status'] ?? null) !== 'APPROVED_FOR_PROD'
            || ($binding['approved_for_prod'] ?? null) !== true
            || ($binding['collection_enabled'] ?? null) !== true) {
            return false;
        }
        $scope = $binding['scope'] ?? null;
        if (!is_array($scope)
            || ($scope['public_routes'] ?? null) !== self::EXPECTED_PUBLIC_ROUTES
            || ($scope['api_route'] ?? null) !== self::EXPECTED_API_ROUTE) {
            return false;
        }
        $twin = $binding['test_twin'] ?? null;
        if (!is_array($twin)
            || ($twin['classification'] ?? null) !== 'TEST_TWIN_NON_EVIDENCE'
            || ($twin['can_satisfy_live_readback'] ?? null) !== false
            || ($twin['prod_promotion_eligible'] ?? null) !== false) {
            return false;
        }
        $readback = $binding['live_provider_readback'] ?? null;
        if (!is_array($readback)
            || ($readback['readback_classification'] ?? null) !== 'LIVE_PROVIDER_READBACK'
            || ($readback['verified'] ?? null) !== true
            || !self::nonPlaceholder($readback['provider_account'] ?? null)
            || !self::nonPlaceholder($readback['verified_by'] ?? null)
            || !self::freshTimestamp($readback['verified_at_utc'] ?? null, $now)) {
            return false;
        }
        $routes = $readback['routes'] ?? null;
        if (!is_array($routes) || count($routes) !== count(self::EXPECTED_PUBLIC_ROUTES)) return false;
        $byUrl = [];
        foreach ($routes as $route) {
            if (!is_array($route)) return false;
            $url = (string)($route['url'] ?? '');
            if ($url === '' || isset($byUrl[$url])) return false;
            $byUrl[$url] = $route;
        }
        if (array_keys($byUrl) !== self::EXPECTED_PUBLIC_ROUTES) {
            if (array_diff(array_keys($byUrl), self::EXPECTED_PUBLIC_ROUTES) !== []
                || array_diff(self::EXPECTED_PUBLIC_ROUTES, array_keys($byUrl)) !== []) return false;
        }
        foreach (self::EXPECTED_PUBLIC_ROUTES as $url) {
            $route = $byUrl[$url] ?? null;
            if (!is_array($route) || ($route['status_code'] ?? null) !== 200 || !is_array($route['headers'] ?? null)) return false;
            if (!self::headerSetReady($route['headers'])) return false;
        }
        $digest = $readback['readback_sha256'] ?? null;
        return is_string($digest)
            && preg_match('/^[0-9a-f]{64}$/', $digest) === 1
            && hash_equals(self::canonicalSha256($routes), $digest);
    }

    private static function incidentReady(array $procedure): bool
    {
        if (($procedure['schema_version'] ?? null) !== self::INCIDENT_SCHEMA
            || ($procedure['research_id'] ?? null) !== self::RESEARCH_ID
            || ($procedure['evidence_binding_key'] ?? null) !== 'security_incident_response_procedure'
            || ($procedure['synthetic'] ?? null) !== false
            || ($procedure['status'] ?? null) !== 'APPROVED_FOR_PROD'
            || ($procedure['controller_approval'] ?? null) !== true
            || ($procedure['prod_eligible'] ?? null) !== true
            || ($procedure['collection_enabled'] ?? null) !== true) {
            return false;
        }
        foreach (['privacy_contact', 'incident_owner', 'breach_register_location', 'anspdcp_notification_route', 'processor_escalation_route'] as $field) {
            if (!self::nonPlaceholder($procedure[$field] ?? null)) return false;
        }
        $mandatory = $procedure['mandatory_before_prod'] ?? null;
        if (!is_array($mandatory)) return false;
        $actual = array_keys($mandatory);
        $expected = self::REQUIRED_INCIDENT_BINDINGS;
        sort($actual, SORT_STRING);
        sort($expected, SORT_STRING);
        if ($actual !== $expected) return false;
        foreach (self::REQUIRED_INCIDENT_BINDINGS as $key) {
            if (($mandatory[$key] ?? null) !== true) return false;
        }
        $communications = $procedure['external_communication_boundary'] ?? null;
        $resume = $procedure['resume_collection_gate'] ?? null;
        $security = $procedure['security_and_data_minimisation'] ?? null;
        return is_array($communications)
            && ($communications['automatic_external_notification'] ?? null) === false
            && is_array($resume)
            && ($resume['automatic_resume'] ?? null) === false
            && is_array($security)
            && ($security['incident_register_separate_from_crm'] ?? null) === true
            && ($security['commercial_tracking_forbidden'] ?? null) === true;
    }

    public function productionReady(?int $now = null): bool
    {
        try {
            $security = $this->artifact('PUBLIC_RESEARCH_SURFACE_SECURITY_BINDING_DRAFT.json');
            $incident = $this->artifact('GDPR_SECURITY_INCIDENT_RESPONSE_DRAFT.json');
        } catch (Throwable) {
            return false;
        }
        return self::securityReady($security, $now) && self::incidentReady($incident);
    }
}
