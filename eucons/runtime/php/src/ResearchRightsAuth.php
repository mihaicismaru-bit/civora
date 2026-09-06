<?php
declare(strict_types=1);

/**
 * AI4WORK rights-request proof-of-possession verifier.
 *
 * The browser-generated UUIDv4 already used as the submission idempotency key
 * doubles as a private verification code. It is never stored in clear by this
 * adapter and is not a civil-identity credential. Together with response_id it
 * proves control of the original high-entropy submission credential without
 * creating an identity registry or consulting CRM/IP/device data.
 */
final class EuconsResearchRightsAuth
{
    private const RESEARCH_ID = 'AI4WORK-STEP-NF-RUN-001';
    private const ALLOWED_FORMS = ['AI4WORK_ADULTS_V1', 'AI4WORK_EMPLOYERS_V1'];

    private static function validateResponseId(string $responseId): string
    {
        $value = strtolower(trim($responseId));
        if (!preg_match('/^[0-9a-f]{64}$/', $value)) {
            throw new InvalidArgumentException('INVALID_RESPONSE_ID');
        }
        return $value;
    }

    private static function validatePrivateCode(string $privateCode): string
    {
        $value = strtolower(trim($privateCode));
        if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/', $value)) {
            throw new InvalidArgumentException('INVALID_RIGHTS_PRIVATE_CODE');
        }
        return $value;
    }

    public static function deriveResponseId(string $formId, string $privateCode): string
    {
        if (!in_array($formId, self::ALLOWED_FORMS, true)) {
            throw new InvalidArgumentException('UNKNOWN_FORM');
        }
        $code = self::validatePrivateCode($privateCode);
        return hash('sha256', self::RESEARCH_ID . ':' . $formId . ':' . $code);
    }

    /**
     * Returns the matched form id when the two opaque values belong together.
     * Returns null on a well-formed but non-matching pair.
     *
     * Callers must separately confirm that the response_id still exists in the
     * isolated research store before disclosing or mutating any record.
     */
    public static function authenticate(string $responseId, string $privateCode): ?string
    {
        $receipt = self::validateResponseId($responseId);
        $code = self::validatePrivateCode($privateCode);
        foreach (self::ALLOWED_FORMS as $formId) {
            $candidate = hash('sha256', self::RESEARCH_ID . ':' . $formId . ':' . $code);
            if (hash_equals($receipt, $candidate)) {
                return $formId;
            }
        }
        return null;
    }
}
