#!/usr/bin/env bash
#
# Sandbox tests for release.sh's sync_dev workflow handling. Builds throwaway
# origin and upstream repos, then runs the real sync_dev rebase against them.
# Fork-only, like release.sh. Usage: ./release_test.sh
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT
FAILED=0

git_() { git -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }

TAG=2026.1.0
INTEG_DIR=homeassistant/components/teslemetry
TESTS=tests/components/teslemetry

# Build $SANDBOX/work with origin (main) and upstream (dev) remotes. Core tag
# $TAG (main's hacs.json floor, the pinned core base) is upstream dev's tip.
#   $1: file main deletes from core's tree (empty: none)
#   $2: file upstream/dev modifies afterwards
#   $3: file main edits itself and dev edits too (empty: none), for a content conflict
make_sandbox() {
  local deleted=$1 modified=$2 content=${3:-}
  rm -rf "$SANDBOX/work" "$SANDBOX/origin.git" "$SANDBOX/upstream.git" "$SANDBOX/seed"
  git init -q --bare -b main "$SANDBOX/origin.git"
  git init -q --bare -b dev "$SANDBOX/upstream.git"
  git init -q -b dev "$SANDBOX/seed"
  (
    cd "$SANDBOX/seed" || exit 1
    mkdir -p .github/workflows/matchers
    for f in ci.yaml builder.yml teslemetry-test.yml release.yml matchers/python.json; do
      echo "core $f" > ".github/workflows/$f"
    done
    echo base > code.txt
    mkdir -p "$INTEG_DIR" "$TESTS"
    echo base > "$INTEG_DIR/x.py"
    echo base > "$TESTS/test_x.py"
    git_ add -A && git_ commit -qm "core base"
    git push -q "$SANDBOX/upstream.git" dev
    git checkout -q -b main
    [ -z "$deleted" ] || git_ rm -q -- "$deleted"
    [ -z "$content" ] || { echo main > "$content"; git_ add -A; }
    echo fork > fork.txt
    printf '{"homeassistant": "%s"}\n' "$TAG" > hacs.json
    git_ add -A && git_ commit -qm "fork changes"
    git push -q "$SANDBOX/origin.git" main
    git checkout -q dev
    echo "core changed" >> "$modified"
    [ -z "$content" ] || echo dev > "$content"
    git_ add -A && git_ commit -qm "core dev change"
    git push -q "$SANDBOX/upstream.git" dev
    git tag "$TAG"
    git push -q "$SANDBOX/upstream.git" "$TAG"
  )
  git clone -q "$SANDBOX/origin.git" "$SANDBOX/work"
  git -C "$SANDBOX/work" remote add upstream "$SANDBOX/upstream.git"
}

# Run sync_dev as a daily run (a stop exits 3 instead of reading a terminal).
run_sync() {
  (
    cd "$SANDBOX/work" || exit 1
    export GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=t \
      GIT_CONFIG_KEY_1=user.email GIT_CONFIG_VALUE_1=t@t
    # shellcheck source=release.sh
    source "$ROOT/release.sh"
    DAILY=1 RERERE=0
    # Fault injection (set by a test): define a git wrapper that stands in for a
    # git subcommand misbehaving.
    [ -z "${FAKE_GIT:-}" ] || eval "$FAKE_GIT"
    sync_dev
  ) >"$SANDBOX/out" 2>&1
}

check() {
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$2', got '$3')"; FAILED=1; fi
}

make_sandbox .github/workflows/ci.yaml .github/workflows/ci.yaml
run_sync; rc=$?
check "deleted workflow: sync completes" 0 "$rc"
check "deleted workflow: stays deleted" "" "$(git -C "$SANDBOX/work" ls-files .github/workflows/ci.yaml)"
check "deleted workflow: fork commit kept" fork "$(cat "$SANDBOX/work/fork.txt" 2>/dev/null)"
check "deleted workflow: logged" 1 "$(grep -c 'kept deleted: .github/workflows/ci.yaml' "$SANDBOX/out")"

make_sandbox .github/workflows/matchers/python.json .github/workflows/matchers/python.json
run_sync; rc=$?
check "deleted matchers file: sync completes" 0 "$rc"

make_sandbox .github/workflows/ci.yaml .github/workflows/teslemetry-test.yml
run_sync; rc=$?
check "unrelated core change: sync completes" 0 "$rc"

# A workflow main deletes but CORE_CI_PATHS does not list (here release.yml, which
# main keeps in the real repo) is not auto-kept: the run stops.
make_sandbox .github/workflows/release.yml .github/workflows/release.yml
run_sync; rc=$?
check "kept workflow: stops headless" 3 "$rc"

make_sandbox "" code.txt code.txt
run_sync; rc=$?
check "content conflict: stops headless" 3 "$rc"

# One path auto-kept, one content conflict: still stops, and only the conflict remains.
make_sandbox .github/workflows/ci.yaml .github/workflows/ci.yaml code.txt
run_sync; rc=$?
check "mixed: stops headless" 3 "$rc"
check "mixed: deletion logged" 1 "$(grep -c 'kept deleted: .github/workflows/ci.yaml' "$SANDBOX/out")"

# Rename/delete conflict: main deletes code.txt, dev renames it onto a CORE_CI_PATHS
# path. The conflict leaves stages 1 and 2 at that path, but the replayed commit
# deletes code.txt, not the workflow, so it must not be removed.
make_sandbox code.txt code.txt
(
  cd "$SANDBOX/seed" || exit 1
  git checkout -q -f dev && git reset -q --hard HEAD~1
  git_ mv code.txt .github/workflows/wheels.yml
  git_ commit -qm "core renames code.txt"
  git push -q -f "$SANDBOX/upstream.git" dev
  git tag -f "$TAG" >/dev/null
  git push -q -f "$SANDBOX/upstream.git" "$TAG"
)
git -C "$SANDBOX/work" fetch -q upstream 2>/dev/null
run_sync; rc=$?
check "rename/delete conflict: stops headless" 3 "$rc"
check "rename/delete conflict: not logged as kept" 0 "$(grep -c 'kept deleted' "$SANDBOX/out")"

# Race: git diff refreshes the index, so it can still hold index.lock after it has
# printed its paths. The wrapper holds the lock for a second after the diff output,
# as a real refresh can; a loop fed straight from the diff would reach git rm while
# the lock exists.
# shellcheck disable=SC2016
LOCK_RACE='git() {
  if [ "${1:-}" = diff ] && [ "${2:-}" = -z ]; then
    local lock; lock=$(command git rev-parse --git-path index.lock)
    command git "$@"
    : > "$lock"
    ( sleep 1; rm -f "$lock" ) &
    return 0
  fi
  if [ "${1:-}" = rm ] && [ -e "$(command git rev-parse --git-path index.lock)" ]; then
    echo "fatal: Unable to create index.lock: File exists." >&2
    return 128
  fi
  command git "$@"
}'
make_sandbox .github/workflows/ci.yaml .github/workflows/ci.yaml
FAKE_GIT=$LOCK_RACE run_sync; rc=$?
check "index lock held after diff: sync completes" 0 "$rc"
check "index lock held after diff: stays deleted" "" "$(git -C "$SANDBOX/work" ls-files .github/workflows/ci.yaml)"

# A failing git rm is reported, never logged as kept: the run stops headless.
make_sandbox .github/workflows/ci.yaml .github/workflows/ci.yaml
# shellcheck disable=SC2016
FAKE_GIT='git() { if [ "${1:-}" = rm ]; then echo "fatal: git rm failed" >&2; return 128; fi; command git "$@"; }' run_sync; rc=$?
check "failing git rm: stops headless" 3 "$rc"
check "failing git rm: not logged as kept" 0 "$(grep -c 'kept deleted' "$SANDBOX/out")"

# Pinned core base: core paths come from the tag, the integration and its tests
# from upstream dev, the fork commits on top.
make_sandbox "" .github/workflows/teslemetry-test.yml
(
  cd "$SANDBOX/seed" || exit 1
  git checkout -q dev
  echo "dev only" >> code.txt
  echo dev > "$INTEG_DIR/x.py"
  echo dev > "$TESTS/test_x.py"
  git_ add -A && git_ commit -qm "core dev beyond the tag"
  git push -q "$SANDBOX/upstream.git" dev
)
run_sync; rc=$?
work() { git -C "$SANDBOX/work" "$@"; }
check "pinned base: sync completes" 0 "$rc"
check "pinned base: core file at the tag" base "$(work show sync-dev:code.txt)"
check "pinned base: integration from dev" dev "$(work show "sync-dev:$INTEG_DIR/x.py")"
check "pinned base: integration tests from dev" dev "$(work show "sync-dev:$TESTS/test_x.py")"
check "pinned base: fork commit kept" fork "$(work show sync-dev:fork.txt)"
check "pinned base: on the tag" 0 "$(work merge-base --is-ancestor "$TAG" sync-dev; echo $?)"
check "pinned base: dev not in main" 1 "$(work merge-base --is-ancestor upstream/dev sync-dev; echo $?)"
check "pinned base: one base commit" 1 "$(work log --format=%s "$TAG..sync-dev" | grep -c '^HACS core base:')"

# A second sync with nothing new leaves main as it is.
work push -q -f origin sync-dev:main
work checkout -q --detach
run_sync; rc=$?
check "resync: completes" 0 "$rc"
check "resync: main unchanged" "$(work rev-parse origin/main)" "$(work rev-parse sync-dev)"

# Pin bump: main's hacs.json names a newer tag; the old base commit is dropped.
(
  cd "$SANDBOX/seed" || exit 1
  git checkout -q dev
  git_ commit -q --allow-empty -m "core next release"
  git tag 2026.2.0
  git push -q "$SANDBOX/upstream.git" dev 2026.2.0
)
(
  cd "$SANDBOX/work" || exit 1
  git checkout -q -B bump origin/main
  printf '{"homeassistant": "2026.2.0"}\n' > hacs.json
  git_ commit -qam "Bump the pinned core base to 2026.2.0"
  git push -q origin bump:main
)
run_sync; rc=$?
check "pin bump: completes" 0 "$rc"
check "pin bump: on the new tag" 0 "$(work merge-base --is-ancestor 2026.2.0 sync-dev; echo $?)"
check "pin bump: one base commit" 1 "$(work log --format=%s "2026.2.0..sync-dev" | grep -c '^HACS core base:')"
check "pin bump: fork commits kept" "fork 2026.2.0" \
  "$(work show sync-dev:fork.txt) $(work show sync-dev:hacs.json | jq -r .homeassistant)"

# on_core_base: only a commit on the tag its own hacs.json names passes.
check "on_core_base: synced main" 0 \
  "$(cd "$SANDBOX/work" && bash -c 'source "$1"; on_core_base sync-dev' _ "$ROOT/release.sh" >/dev/null 2>&1; echo $?)"
check "on_core_base: main before the sync" 1 \
  "$(cd "$SANDBOX/work" && bash -c 'source "$1"; on_core_base origin/main' _ "$ROOT/release.sh" >/dev/null 2>&1; echo $?)"

# A branch started at an old base commit or on core dev and merged after a
# sync brings that base and that dev history into main; neither is a fork
# commit. (A branch also carrying old copies of fork commits replays them, as
# it did before the pinned base.)
(
  cd "$SANDBOX/work" || exit 1
  git fetch -q origin
  git checkout -q -B late "$(git rev-parse 'origin/main^{/^HACS core base:}')"
  echo later > later.txt && git_ add -A && git_ commit -qm "fork change on the old base"
  git checkout -q -B stale-dev "$(git merge-base origin/main upstream/dev)"
  echo late > late.txt && git_ add -A && git_ commit -qm "fork change on core dev"
  git checkout -q -B merged sync-dev
  git_ merge -q --no-edit late stale-dev >/dev/null
  git push -q -f origin merged:main
  git checkout -q --detach
)
run_sync; rc=$?
check "stale merges: completes" 0 "$rc"
check "stale merges: one base commit" 1 "$(work log --format=%s "2026.2.0..sync-dev" | grep -c '^HACS core base:')"
check "stale merges: fork changes kept" "late later fork" \
  "$(work show sync-dev:late.txt) $(work show sync-dev:later.txt) $(work show sync-dev:fork.txt)"
check "stale merges: core file at the tag" "$(work show 2026.2.0:code.txt)" "$(work show sync-dev:code.txt)"
check "stale merges: linear" 0 "$(work rev-list --merges --count "2026.2.0..sync-dev")"

# pin_integration_requirements: manifest pins replace the same package's line
# (names compared as pip does) and a pin with no line is appended.
mkdir -p "$SANDBOX/pins/$INTEG_DIR"
printf '{"requirements": ["Tesla_Fleet.API==2.0.0", "new-lib==1.0"]}\n' > "$SANDBOX/pins/$INTEG_DIR/manifest.json"
printf '# homeassistant.components.tessie\ntesla-fleet-api==1.0.0\n\nother==3\n' > "$SANDBOX/pins/requirements_all.txt"
(cd "$SANDBOX/pins" && bash -c 'source "$1"; pin_integration_requirements' _ "$ROOT/release.sh")
check "requirements pin: replaced" 1 "$(grep -cx 'Tesla_Fleet.API==2.0.0' "$SANDBOX/pins/requirements_all.txt")"
check "requirements pin: old line gone" 0 "$(grep -c 'tesla-fleet-api==1.0.0' "$SANDBOX/pins/requirements_all.txt")"
check "requirements pin: appended" 1 "$(grep -cx 'new-lib==1.0' "$SANDBOX/pins/requirements_all.txt")"
check "requirements pin: others kept" 1 "$(grep -cx 'other==3' "$SANDBOX/pins/requirements_all.txt")"

# The Home Assistant requirement note: beta wording only for a pre-release floor.
bash -c 'source "$1"; floor_requirement_note "$2"' _ "$ROOT/release.sh" 2026.10.0 > "$SANDBOX/note"
check "stable floor: no beta in heading" 0 "$(grep -c "Requires Home Assistant.*beta\*\*" "$SANDBOX/note")"
check "stable floor: names the version" 1 "$(grep -c 'Requires Home Assistant 2026.10\*\*' "$SANDBOX/note")"
check "stable floor: body names the floor" 1 "$(grep -c 'requires Home Assistant 2026.10.0 or newer' "$SANDBOX/note")"
bash -c 'source "$1"; floor_requirement_note "$2"' _ "$ROOT/release.sh" 2026.11.0b0 > "$SANDBOX/note"
check "pre-release floor: beta wording" 1 "$(grep -c 'Requires Home Assistant 2026.11 beta\*\*' "$SANDBOX/note")"
check "pre-release floor: body names the floor" 1 "$(grep -c 'requires Home Assistant 2026.11.0b0 or newer' "$SANDBOX/note")"

exit "$FAILED"
