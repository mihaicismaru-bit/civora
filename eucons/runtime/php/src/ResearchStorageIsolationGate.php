<?php
declare(strict_types=1);

/**
 * AI4WORK live storage boundary gate.
 *
 * Governance evidence may say that the research store is separate from CRM,
 * but the live filesystem binding must independently prove that the path used
 * by the PHP collector cannot alias the public webroot or commercial/CRM data
 * through relative paths or symlinks.
 */
final class EuconsResearchStorageIsolationGate
{
    private string $euconsRoot;
    private array $commercialRuntimeContract;

    public function __construct(?string $euconsRoot = null)
    {
        $root = $euconsRoot ?: dirname(__DIR__, 3);
        $resolved = realpath($root);
        $this->euconsRoot = $resolved !== false ? $resolved : rtrim(str_replace('\\', '/', $root), '/');
        $this->commercialRuntimeContract = self::loadJson($this->euconsRoot . '/runtime/php/runtime_contract.json');
    }

    private static function loadJson(string $path): array
    {
        $raw = @file_get_contents($path);
        if ($raw === false) {
            throw new RuntimeException('RESEARCH_STORAGE_ISOLATION_CONTRACT_UNAVAILABLE');
        }
        $decoded = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($decoded)) {
            throw new RuntimeException('RESEARCH_STORAGE_ISOLATION_CONTRACT_INVALID');
        }
        return $decoded;
    }

    private static function normalizeAbsolute(string $path, string $error): string
    {
        $normalized = rtrim(str_replace('\\', '/', trim($path)), '/');
        if ($normalized === '' || !str_starts_with($normalized, '/')) {
            throw new RuntimeException($error);
        }
        foreach (explode('/', ltrim($normalized, '/')) as $segment) {
            if ($segment === '.' || $segment === '..') {
                throw new RuntimeException($error);
            }
        }
        return $normalized;
    }

    /**
     * Resolve an existing prefix and preserve any not-yet-created suffix.
     * Broken symlinks and unresolvable existing prefixes fail closed.
     */
    private static function canonicalPlannedPath(string $path, string $error): string
    {
        $normalized = self::normalizeAbsolute($path, $error);
        $probe = $normalized;
        $suffix = [];

        while (!file_exists($probe) && !is_link($probe)) {
            $parent = dirname($probe);
            if ($parent === $probe) {
                throw new RuntimeException($error);
            }
            array_unshift($suffix, basename($probe));
            $probe = str_replace('\\', '/', $parent);
        }

        $resolved = realpath($probe);
        if ($resolved === false) {
            throw new RuntimeException($error);
        }
        $canonical = rtrim(str_replace('\\', '/', $resolved), '/');
        if ($canonical === '') {
            $canonical = '/';
        }
        if ($suffix !== []) {
            $canonical = rtrim($canonical, '/') . '/' . implode('/', $suffix);
        }
        return $canonical;
    }

    /**
     * Research storage is intentionally stricter than comparison roots:
     * no existing component may itself be a symlink. This removes a mutable
     * alias between the request-time gate and the subsequent persistence call.
     */
    private static function rejectResearchSymlinkComponents(string $path): void
    {
        $normalized = self::normalizeAbsolute($path, 'RESEARCH_STORAGE_PATH_INVALID');
        $current = '';
        foreach (explode('/', ltrim($normalized, '/')) as $segment) {
            if ($segment === '') {
                continue;
            }
            $current .= '/' . $segment;
            if (is_link($current)) {
                throw new RuntimeException('RESEARCH_STORAGE_SYMLINK_FORBIDDEN');
            }
            if (!file_exists($current)) {
                // Descendants cannot exist before the first missing component.
                break;
            }
        }
    }

    private static function overlaps(string $left, string $right): bool
    {
        $left = rtrim($left, '/');
        $right = rtrim($right, '/');
        if ($left === '') $left = '/';
        if ($right === '') $right = '/';
        return $left === $right
            || str_starts_with($left . '/', rtrim($right, '/') . '/')
            || str_starts_with($right . '/', rtrim($left, '/') . '/');
    }

    public function validatedStorageRoot(): string
    {
        $configured = trim((string)(getenv('AI4WORK_RESEARCH_ROOT') ?: ''));
        $researchRaw = $configured !== ''
            ? $configured
            : '/home/eucons/eucons-research/ai4work-step';
        self::rejectResearchSymlinkComponents($researchRaw);
        $research = self::canonicalPlannedPath($researchRaw, 'RESEARCH_STORAGE_PATH_INVALID');

        $documentRaw = trim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''));
        if ($documentRaw !== '') {
            $document = self::canonicalPlannedPath($documentRaw, 'RESEARCH_DOCUMENT_ROOT_INVALID');
            if (self::overlaps($research, $document)) {
                throw new RuntimeException('RESEARCH_STORAGE_INSIDE_WEBROOT');
            }
        }

        $commercialConfigured = trim((string)(getenv('EUCONS_DATA_ROOT') ?: ''));
        $commercialRaw = $commercialConfigured !== ''
            ? $commercialConfigured
            : (string)($this->commercialRuntimeContract['storage']['default_root'] ?? '/home/eucons/eucons-data');
        $commercial = self::canonicalPlannedPath($commercialRaw, 'COMMERCIAL_STORAGE_PATH_INVALID');
        if (self::overlaps($research, $commercial)) {
            throw new RuntimeException('RESEARCH_STORAGE_NOT_SEPARATE_FROM_COMMERCIAL');
        }

        return $research;
    }

    public function productionReady(): bool
    {
        try {
            $this->validatedStorageRoot();
            return true;
        } catch (Throwable) {
            return false;
        }
    }
}
