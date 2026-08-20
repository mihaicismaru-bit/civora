<?php
declare(strict_types=1);

final class EuconsMailRuntime
{
    private string $dataRoot;
    private string $secretFile;
    private $transport;

    public function __construct(string $dataRoot, ?string $secretFile = null, ?callable $transport = null)
    {
        $this->dataRoot = rtrim($dataRoot, '/');
        $configured = trim((string)(getenv('EUCONS_MAIL_SECRET_FILE') ?: ''));
        $this->secretFile = $secretFile ?: ($configured !== '' ? $configured : '/home/eucons/eucons-secrets/mail.json');
        $this->transport = $transport;
    }

    private static function ensureDirectory(string $path): void
    {
        if (!is_dir($path) && !@mkdir($path, 0700, true) && !is_dir($path)) throw new RuntimeException('MAIL_STORAGE_UNAVAILABLE');
    }

    private static function atomicWrite(string $path, array $value): void
    {
        self::ensureDirectory(dirname($path));
        $tmp = tempnam(dirname($path), '.mail-');
        if ($tmp === false) throw new RuntimeException('MAIL_STORAGE_PREPARE_FAILED');
        try {
            $json = json_encode($value, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
            if (@file_put_contents($tmp, $json, LOCK_EX) === false) throw new RuntimeException('MAIL_STORAGE_WRITE_FAILED');
            @chmod($tmp, 0600);
            if (!@rename($tmp, $path)) throw new RuntimeException('MAIL_STORAGE_COMMIT_FAILED');
        } finally {
            if (is_file($tmp)) @unlink($tmp);
        }
    }

    private function secret(): array
    {
        if (!is_file($this->secretFile)) throw new RuntimeException('MAILBOX_SECRET_UNAVAILABLE');
        $raw = @file_get_contents($this->secretFile);
        if ($raw === false) throw new RuntimeException('MAILBOX_SECRET_UNREADABLE');
        $data = json_decode($raw, true, 32, JSON_THROW_ON_ERROR);
        if (!is_array($data)) throw new RuntimeException('MAILBOX_SECRET_INVALID');
        $username = trim((string)($data['username'] ?? ''));
        $password = (string)($data['password'] ?? '');
        if ($username !== 'office@eucons.ro' || $password === '') throw new RuntimeException('MAILBOX_SECRET_INVALID');
        return ['username' => $username, 'password' => $password];
    }

    public function queueAcknowledgement(array $processed, string $requestId): array
    {
        $lead = $processed['lead'] ?? [];
        $email = trim((string)($lead['email'] ?? ''));
        $name = trim((string)($lead['contact_name'] ?? ''));
        if ($email === '' || $name === '') throw new RuntimeException('MAIL_ACK_RECIPIENT_REQUIRED');
        $outboxDir = $this->dataRoot . '/mail/outbox';
        self::ensureDirectory($outboxDir);
        $path = $outboxDir . '/' . $requestId . '.json';
        if (is_file($path)) return ['status' => 'queued', 'request_id' => $requestId, 'idempotent_replay' => true];

        $body = "Bună ziua, {$name},\n\nAm primit solicitarea transmisă către Euroconsult. Codul solicitării este {$requestId}.\n\nVom folosi informațiile exclusiv pentru evaluarea și gestionarea solicitării inițiate de dumneavoastră. Mesajele promoționale sau alertele de oportunități sunt tratate separat și necesită consimțământ distinct.\n\nEuroconsult\noffice@eucons.ro\nhttps://eucons.ro\n";
        $record = [
            'schema_version' => 1,
            'message_type' => 'LEAD_ACKNOWLEDGEMENT',
            'request_id' => $requestId,
            'recipient' => $email,
            'from' => 'office@eucons.ro',
            'subject' => 'Am primit solicitarea ta — Euroconsult',
            'body' => $body,
            'created_at' => gmdate('c'),
            'attempts' => 0,
            'state' => 'QUEUED',
        ];
        self::atomicWrite($path, $record);
        return ['status' => 'queued', 'request_id' => $requestId, 'idempotent_replay' => false];
    }

    public function dispatch(string $requestId): array
    {
        $receiptPath = $this->dataRoot . '/mail/receipts/' . $requestId . '.json';
        if (is_file($receiptPath)) {
            $receipt = json_decode((string)file_get_contents($receiptPath), true, 32, JSON_THROW_ON_ERROR);
            return ['status' => 'sent', 'request_id' => $requestId, 'idempotent_replay' => true, 'operation_id' => $receipt['operation_id']];
        }
        $outboxPath = $this->dataRoot . '/mail/outbox/' . $requestId . '.json';
        if (!is_file($outboxPath)) throw new RuntimeException('MAIL_OUTBOX_RECORD_MISSING');
        $record = json_decode((string)file_get_contents($outboxPath), true, 64, JSON_THROW_ON_ERROR);
        if (!is_array($record)) throw new RuntimeException('MAIL_OUTBOX_RECORD_INVALID');
        if (($record['message_type'] ?? '') !== 'LEAD_ACKNOWLEDGEMENT') throw new RuntimeException('MAIL_MESSAGE_TYPE_NOT_AUTOMATIC');

        $secret = $this->secret();
        $operationId = hash('sha256', 'smtp|lead-ack|' . $requestId);
        $record['attempts'] = (int)($record['attempts'] ?? 0) + 1;
        self::atomicWrite($outboxPath, $record);

        if ($this->transport !== null) {
            ($this->transport)($secret, $record);
        } else {
            $this->smtpSend($secret, $record);
        }

        $receipt = [
            'schema_version' => 1,
            'provider' => 'mail.eucons.ro:465',
            'operation_id' => $operationId,
            'status' => 'SENT',
            'written_at' => gmdate('c'),
            'message_type' => 'LEAD_ACKNOWLEDGEMENT',
            'request_id' => $requestId,
            'pii_in_receipt' => false,
        ];
        self::atomicWrite($receiptPath, $receipt);
        $record['state'] = 'SENT';
        self::atomicWrite($outboxPath, $record);
        return ['status' => 'sent', 'request_id' => $requestId, 'idempotent_replay' => false, 'operation_id' => $operationId];
    }

    private function smtpSend(array $secret, array $record): void
    {
        $context = stream_context_create(['ssl' => [
            'verify_peer' => true,
            'verify_peer_name' => true,
            'peer_name' => 'mail.eucons.ro',
            'SNI_enabled' => true,
        ]]);
        $socket = @stream_socket_client('ssl://mail.eucons.ro:465', $errno, $errstr, 12, STREAM_CLIENT_CONNECT, $context);
        if ($socket === false) throw new RuntimeException('SMTP_CONNECT_FAILED');
        stream_set_timeout($socket, 12);
        try {
            $this->expect($socket, [220]);
            $this->command($socket, "EHLO eucons.ro\r\n", [250]);
            $this->command($socket, "AUTH LOGIN\r\n", [334]);
            $this->command($socket, base64_encode($secret['username']) . "\r\n", [334]);
            $this->command($socket, base64_encode($secret['password']) . "\r\n", [235]);
            $this->command($socket, "MAIL FROM:<office@eucons.ro>\r\n", [250]);
            $this->command($socket, 'RCPT TO:<' . $record['recipient'] . ">\r\n", [250, 251]);
            $this->command($socket, "DATA\r\n", [354]);
            $subject = '=?UTF-8?B?' . base64_encode((string)$record['subject']) . '?=';
            $messageId = '<' . substr(hash('sha256', (string)$record['request_id']), 0, 24) . '@eucons.ro>';
            $body = str_replace(["\r\n", "\r"], "\n", (string)$record['body']);
            $body = str_replace("\n", "\r\n", $body);
            $body = preg_replace('/^\./m', '..', $body) ?? $body;
            $headers = [
                'From: Euroconsult <office@eucons.ro>',
                'To: <' . $record['recipient'] . '>',
                'Subject: ' . $subject,
                'Date: ' . date(DATE_RFC2822),
                'Message-ID: ' . $messageId,
                'MIME-Version: 1.0',
                'Content-Type: text/plain; charset=UTF-8',
                'Content-Transfer-Encoding: 8bit',
            ];
            fwrite($socket, implode("\r\n", $headers) . "\r\n\r\n" . $body . "\r\n.\r\n");
            $this->expect($socket, [250]);
            $this->command($socket, "QUIT\r\n", [221]);
        } finally {
            fclose($socket);
        }
    }

    private function command($socket, string $command, array $expected): void
    {
        if (fwrite($socket, $command) === false) throw new RuntimeException('SMTP_WRITE_FAILED');
        $this->expect($socket, $expected);
    }

    private function expect($socket, array $expected): void
    {
        $response = '';
        while (($line = fgets($socket, 4096)) !== false) {
            $response .= $line;
            if (strlen($line) >= 4 && $line[3] === ' ') break;
        }
        if ($response === '') throw new RuntimeException('SMTP_EMPTY_RESPONSE');
        $code = (int)substr($response, 0, 3);
        if (!in_array($code, $expected, true)) throw new RuntimeException('SMTP_PROTOCOL_FAILED_' . $code);
    }
}
