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

exit "$FAILED"
