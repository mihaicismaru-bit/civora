"""Exercise the workflow's actual persistence shell against local Git remotes."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = ('sync_local_life_events.py', 'repair_local_life_event_projection.py', 'sync_local_life_surfaces.py')
EVENT_PATH = 'valcea-clar/editorial/local_life_events.json'
SURFACE_PATH = 'valcea-clar/editorial/local_life_surface_registry.json'
FOREIGN_ROUTE = 'valcea-clar/site/runtime/unde-iesim/verificat/index.html'
BASH = shutil.which('bash') or ('C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else None)


class LocalLifePersistenceTests(unittest.TestCase):
    def run_command(self, cwd, *args):
        result = subprocess.run(args, cwd=cwd, env=self.env, capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def git(self, cwd, *args):
        return self.run_command(cwd, 'git', *args)

    def write_json(self, cwd, name, data):
        path = cwd / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + '\n', encoding='utf-8')

    def commit(self, cwd, message):
        self.git(cwd, 'add', '.')
        self.git(cwd, 'commit', '-m', message)

    def configure(self, cwd):
        self.git(cwd, 'config', 'user.name', 'Local fixture')
        self.git(cwd, 'config', 'user.email', 'fixture@example.test')
        self.git(cwd, 'config', 'core.autocrlf', 'false')

    def case(self, race_on_push):
        if not BASH or not Path(BASH).is_file():
            self.fail('Bash is required to test the actual persistence shell')
        with tempfile.TemporaryDirectory(prefix='local-life-git-fixture-') as temporary:
            workspace = Path(temporary).resolve()
            self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0')
            self.env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + self.env.get('PATH', '')
            origin, seed, runner, peer = (workspace / n for n in ('origin.git', 'seed', 'runner', 'peer'))
            self.git(workspace, 'init', '--bare', str(origin))
            seed.mkdir()
            self.git(seed, 'init', '-b', 'main')
            self.configure(seed)
            for name in SCRIPTS:
                target = seed / 'valcea-clar/scripts' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / 'valcea-clar/scripts' / name, target)
            delta = {'event_id': 'operator', 'title': 'Fixture operator event', 'event_start': '2099-10-10', 'venue': 'Fixture venue', 'locality': 'Fixture locality', 'source_url': 'https://example.test/operator', 'source_tier': 'T1', 'checked_at': '2026-10-09T10:00:00+03:00', 'status': 'scheduled'}
            self.write_json(seed, EVENT_PATH, {'events': []})
            self.write_json(seed, 'valcea-clar/ops/live-newsroom-trigger.json', {'event_deltas': [delta]})
            self.write_json(seed, SURFACE_PATH, {'fitness': {'entries': [{'name': 'Fixture gym', 'address': 'BASE_ADDRESS', 'locality': 'Fixture locality', 'source_url': 'https://example.test/gym', 'checked_at': '2026-10-09T10:00:00+03:00'}]}})
            route = seed / FOREIGN_ROUTE
            route.parent.mkdir(parents=True, exist_ok=True)
            route.write_text('BASE_FOREIGN_ROUTE', encoding='utf-8')
            self.commit(seed, 'Fixture baseline')
            self.git(seed, 'remote', 'add', 'origin', str(origin))
            self.git(seed, 'push', 'origin', 'main')
            self.git(workspace, 'clone', '--branch', 'main', str(origin), str(runner))
            self.git(workspace, 'clone', '--branch', 'main', str(origin), str(peer))
            self.configure(runner)
            self.configure(peer)
            for name in SCRIPTS:
                self.run_command(runner, sys.executable, 'valcea-clar/scripts/' + name)

            update = workspace / 'advance.py'
            update.write_text(
                "import json,subprocess,sys\nfrom pathlib import Path\np=Path(sys.argv[1])\n"
                "events=json.loads((p/'" + EVENT_PATH + "').read_text())\n"
                "events['events'].append(" + repr(dict(delta, event_id='peer', title='Fixture peer event')) + ")\n"
                "(p/'" + EVENT_PATH + "').write_text(json.dumps(events)+'\\n')\n"
                "surface=json.loads((p/'" + SURFACE_PATH + "').read_text())\n"
                "surface['fitness']['entries'][0]['address']='NEW_ADDRESS'\n"
                "(p/'" + SURFACE_PATH + "').write_text(json.dumps(surface)+'\\n')\n"
                "(p/'" + FOREIGN_ROUTE + "').write_text('NEW_FOREIGN_ROUTE')\n"
                "subprocess.run(['git','add','.'],cwd=p,check=True)\n"
                "subprocess.run(['git','commit','-m','Concurrent fixture update'],cwd=p,check=True)\n"
                "subprocess.run(['git','push','origin','main'],cwd=p,check=True)\n",
                encoding='utf-8',
            )
            if race_on_push:
                hook = runner / '.git/hooks/pre-push'
                hook.write_bytes((
                    '#!/bin/sh\n'
                    'if [ ! -f .git/race-injected ]; then\n'
                    '  touch .git/race-injected\n'
                    '  python ' + shlex.quote(update.as_posix()) + ' ' + shlex.quote(peer.as_posix()) + '\n'
                    'fi\n'
                ).encode('utf-8'))
                hook.chmod(0o755)
            else:
                self.run_command(workspace, sys.executable, str(update), str(peer))

            workflow = (REPO / '.github/workflows/valcea-clar-local-life-sync.yml').read_text(encoding='utf-8')
            marker = '      - name: Persist Local Life registries and complete route tree'
            body = textwrap.dedent(workflow.split(marker, 1)[1].split('        run: |\n', 1)[1])
            # Relocate the legacy shell's /tmp snapshots into this private fixture.
            scratch = runner / '.phase0-test-tmp'
            self.assertTrue(scratch.resolve().is_relative_to(workspace))
            scratch.mkdir()
            body = body.replace('/tmp/', '.phase0-test-tmp/')
            result = subprocess.run([BASH, '-c', body], cwd=runner, env=self.env, capture_output=True, text=True, encoding='utf-8', errors='replace')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.git(peer, 'pull', '--ff-only', 'origin', 'main')
            events = json.loads((peer / EVENT_PATH).read_text())
            with self.subTest(resource='concurrent registry event'):
                self.assertEqual({row['event_id'] for row in events['events']}, {'operator', 'peer'})
            with self.subTest(resource='latest canonical child surface'):
                self.assertTrue('NEW_ADDRESS' in (peer / 'valcea-clar/site/runtime/unde-iesim/fitness/index.html').read_text(encoding='utf-8'), 'newer canonical address was overwritten')
            with self.subTest(resource='route owned by another writer'):
                self.assertEqual((peer / FOREIGN_ROUTE).read_text(encoding='utf-8'), 'NEW_FOREIGN_ROUTE')
            if race_on_push:
                self.assertTrue((runner / '.git/race-injected').exists())

    def test_main_advance_before_persistence_preserves_newer_state(self):
        self.case(False)

    def test_rejected_push_regenerates_against_new_head(self):
        self.case(True)


if __name__ == '__main__':
    unittest.main()
