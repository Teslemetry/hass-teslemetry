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

# Build $SANDBOX/work with origin (main) and upstream (dev) remotes.
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
    git_ add -A && git_ commit -qm "core base"
    git push -q "$SANDBOX/upstream.git" dev
    git checkout -q -b main
    [ -z "$deleted" ] || git_ rm -q -- "$deleted"
    [ -z "$content" ] || { echo main > "$content"; git_ add -A; }
    echo fork > fork.txt
    git_ add -A && git_ commit -qm "fork changes"
    git push -q "$SANDBOX/origin.git" main
    git checkout -q dev
    echo "core changed" >> "$modified"
    [ -z "$content" ] || echo dev > "$content"
    git_ add -A && git_ commit -qm "core dev change"
    git push -q "$SANDBOX/upstream.git" dev
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

# The Home Assistant requirement note: beta wording only for a pre-release floor.
bash -c 'source "$1"; floor_requirement_note "$2"' _ "$ROOT/release.sh" 2026.10.0 > "$SANDBOX/note"
check "stable floor: no beta in heading" 0 "$(grep -c "Requires Home Assistant.*beta\*\*" "$SANDBOX/note")"
check "stable floor: names the version" 1 "$(grep -c 'Requires Home Assistant 2026.10\*\*' "$SANDBOX/note")"
check "stable floor: body names the floor" 1 "$(grep -c 'requires Home Assistant 2026.10.0 or newer' "$SANDBOX/note")"
bash -c 'source "$1"; floor_requirement_note "$2"' _ "$ROOT/release.sh" 2026.11.0b0 > "$SANDBOX/note"
check "pre-release floor: beta wording" 1 "$(grep -c 'Requires Home Assistant 2026.11 beta\*\*' "$SANDBOX/note")"
check "pre-release floor: body names the floor" 1 "$(grep -c 'requires Home Assistant 2026.11.0b0 or newer' "$SANDBOX/note")"

exit "$FAILED"
