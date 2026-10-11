#!/usr/bin/env bash
# F0 proposal: existing Newsroom's Git persistence step only. Never a publisher.
set -euo pipefail
: "\${BASE_SHA:?BASE_SHA required}"
: "\${TX_GUARD_SCRIPT:?TX_GUARD_SCRIPT required}"
root=$(git rev-parse --show-toplevel)
cd "$root"
test "$(git rev-parse HEAD)" = "$BASE_SHA" || { echo TX_HOLD_BASE_HEAD_MISMATCH >&2; exit 7; }
python3 "$TX_GUARD_SCRIPT" "$root"
paths=(
  valcea-clar/editions
  valcea-clar/editorial/news_discovery_state.json
  valcea-clar/site/current_edition.json
  valcea-clar/site/last_edition_attempt.json
  valcea-clar/site/newsroom_decision.json
  valcea-clar/site/newsroom_state.json
  valcea-clar/site/story_publication_event.json
  valcea-clar/site/story_archive.json
  valcea-clar/site/public_ux_state.json
  valcea-clar/site/runtime
  valcea-clar/state/source_health.json
  valcea-clar/ops/resolution_tasks
)
for p in "\${paths[@]}"; do
  if test -e "$p" || test -n "$(git ls-files -- "$p")"; then git add -A -- "$p"; fi
done
scratch=$(mktemp -d)
wt="$scratch/staging"
cleanup() { git worktree remove --force "$wt" >/dev/null 2>&1 || true; rm -rf "$scratch"; }
trap cleanup EXIT
git diff --cached --binary --full-index "$BASE_SHA" -- > "$scratch/changes.patch"
git diff --cached --name-only -z "$BASE_SHA" > "$scratch/changed.z"
test -s "$scratch/changed.z" || { echo TX_NO_DIFF_NOT_DELIVERED >&2; exit 21; }
cat > "$scratch/check.py" <<'PY'
from pathlib import Path
import subprocess,sys
base,changed,work=sys.argv[1:]
written=set(filter(None,Path(changed).read_bytes().decode().split('\0')))
upstream=set(filter(None,subprocess.check_output(['git','diff','--name-only','-z',base,'origin/main'],cwd=work).decode().split('\0')))
overlap=written & upstream
if overlap:
 print('TX_HOLD_OVERLAPPING_PEER_PATH:'+','.join(sorted(overlap)),file=sys.stderr);sys.exit(11)
# Closed read-set for the direct/transitive Newsroom generator/renderer code audited at F0.
# Some prefixes deliberately fail closed while dependency tracing remains in progress.
inputs=(
 'valcea-clar/site/story_archive.json',
 'valcea-clar/editorial/news_discovery_state.json',
 'valcea-clar/editorial/publication_holds.json',
 'valcea-clar/editorial/facts_registry.json',
 'valcea-clar/editorial/auto_facts.json',
 'valcea-clar/editorial/news_sources.json',
 'valcea-clar/editorial/currentness_overrides.json',
 'valcea-clar/editorial/editorial_manual.json',
 'valcea-clar/editorial/editorial_products.json',
 'valcea-clar/data/', 'valcea-clar/web/data/',
 'valcea-clar/site/navigation.json','valcea-clar/site/indexing_routes.json',
 'valcea-clar/site/legal/',
 'valcea-clar/site/current_edition.json','valcea-clar/site/newsroom_state.json',
 'valcea-clar/site/runtime/stiri/index.html',
 'valcea-clar/site/runtime/stiri/manifest.json',
 'valcea-clar/site/runtime/live-feed.json',
 'valcea-clar/site/runtime/people.json','valcea-clar/site/runtime/artists.json',
 'valcea-clar/social/story_visuals.json',
 'valcea-clar/social/social_media_manifest.json',
 'valcea-clar/visuals/s3_visual_manifest.json',
 'valcea-clar/editions/',
 'valcea-clar/scripts/', 'local-news-os/core/',
 'local-news-os/instances/valcea/',
 '.github/workflows/valcea-clar-newsroom-live.yml',
)
invalid=[p for p in upstream if any(p==q or (q.endswith('/') and p.startswith(q)) for q in inputs)]
if invalid:
 print('TX_HOLD_INPUT_STALE:'+','.join(sorted(invalid)),file=sys.stderr);sys.exit(12)
PY
for attempt in 1 2 3 4 5; do
  git fetch origin main
  python3 "$scratch/check.py" "$BASE_SHA" "$scratch/changed.z" "$root"
  git worktree add --detach "$wt" origin/main >/dev/null
  git -C "$wt" apply --index --binary "$scratch/changes.patch" || { echo TX_HOLD_PATCH_APPLY >&2; exit 13; }
  python3 "$TX_GUARD_SCRIPT" "$wt"
  if git -C "$wt" diff --cached --quiet; then echo TX_NO_DIFF_NOT_DELIVERED >&2; exit 21; fi
  git -C "$wt" -c user.name='valcea-clar-live-newsroom[bot]' -c user.email='valcea-clar-live-newsroom@users.noreply.github.com' commit -m 'Publish VÂLCEA CLAR coherent story transaction' >/dev/null
  if git -C "$wt" push origin HEAD:main; then
    echo "TX_GIT_COMMIT_PASS attempt=$attempt (NOT a public-delivery receipt)"
    exit 0
  fi
  git worktree remove --force "$wt" >/dev/null
  echo "TX_NON_FAST_FORWARD attempt=$attempt" >&2
done
echo TX_HOLD_RETRY_EXHAUSTED >&2
exit 14
