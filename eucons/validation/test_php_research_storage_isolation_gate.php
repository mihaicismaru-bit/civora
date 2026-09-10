<?php
declare(strict_types=1);

// TEST TWIN ONLY — NON-EVIDENCE. Temporary filesystem fixtures only.
require_once dirname(__DIR__) . '/runtime/php/src/ResearchStorageIsolationGate.php';

function isolation_fail(string $message): never {
    fwrite(STDERR, $message . PHP_EOL);
    exit(1);
}

function isolation_expect_not_ready(EuconsResearchStorageIsolationGate $gate, string $label): void {
    if ($gate->productionReady()) {
        isolation_fail($label . ' must fail closed');
    }
}

function isolation_remove(string $path): void {
    if (is_link($path)) {
        @unlink($path);
        return;
    }
    if (!is_dir($path)) {
        @unlink($path);
        return;
    }
    foreach (scandir($path) ?: [] as $item) {
        if ($item === '.' || $item === '..') continue;
        isolation_remove($path . '/' . $item);
    }
    @rmdir($path);
}

$root = sys_get_temp_dir() . '/ai4work-storage-isolation-twin-' . getmypid();
isolation_remove($root);
@mkdir($root . '/public', 0700, true);
@mkdir($root . '/commercial', 0700, true);
@mkdir($root . '/research', 0700, true);

$_SERVER['DOCUMENT_ROOT'] = $root . '/public';
putenv('EUCONS_DATA_ROOT=' . $root . '/commercial');
putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/research');
$gate = new EuconsResearchStorageIsolationGate(dirname(__DIR__));
if (!$gate->productionReady()) isolation_fail('direct separated research root must pass isolation gate');
if ($gate->validatedStorageRoot() !== $root . '/research') isolation_fail('validated research root drift');

putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/commercial/research');
isolation_expect_not_ready($gate, 'research nested in commercial');

putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/public/research');
isolation_expect_not_ready($gate, 'research nested in public webroot');

putenv('AI4WORK_RESEARCH_ROOT=relative/research');
isolation_expect_not_ready($gate, 'relative research path');

putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/research/../research');
isolation_expect_not_ready($gate, 'dot-segment research path');

if (function_exists('symlink')) {
    $researchAlias = $root . '/research-alias';
    if (@symlink($root . '/commercial', $researchAlias)) {
        putenv('AI4WORK_RESEARCH_ROOT=' . $researchAlias . '/ai4work-step');
        isolation_expect_not_ready($gate, 'symlinked research parent');
        @unlink($researchAlias);
    }

    $commercialAlias = $root . '/commercial-alias';
    if (@symlink($root . '/research', $commercialAlias)) {
        putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/research');
        putenv('EUCONS_DATA_ROOT=' . $commercialAlias);
        isolation_expect_not_ready($gate, 'commercial alias resolving to research root');
        @unlink($commercialAlias);
    }

    $publicAlias = $root . '/public-alias';
    if (@symlink($root, $publicAlias)) {
        putenv('EUCONS_DATA_ROOT=' . $root . '/commercial');
        putenv('AI4WORK_RESEARCH_ROOT=' . $root . '/research');
        $_SERVER['DOCUMENT_ROOT'] = $publicAlias;
        isolation_expect_not_ready($gate, 'webroot alias containing research root');
        @unlink($publicAlias);
    }
}

putenv('AI4WORK_RESEARCH_ROOT');
putenv('EUCONS_DATA_ROOT');
unset($_SERVER['DOCUMENT_ROOT']);
isolation_remove($root);
echo "AI4WORK PHP research storage isolation TEST TWIN NON-EVIDENCE: PASS\n";
