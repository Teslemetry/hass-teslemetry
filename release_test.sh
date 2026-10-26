#!/usr/bin/env bash
#
# Sandbox tests for release.sh: the dev sync, the compose set (every queue
# entry ends composed, out of scope, carried by its core PR, or a stop), and a
# needs= compose. Builds throwaway repos; GitHub is mocked. Fork-only, like
# release.sh. Usage: ./release_test.sh
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT
FAILED=0

git_() { git -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }
export GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=t \
  GIT_CONFIG_KEY_1=user.email GIT_CONFIG_VALUE_1=t@t

INTEG_DIR=homeassistant/components/teslemetry
TESTS=tests/components/teslemetry

check() {
  if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$2', got '$3')"; FAILED=1; fi
}

# --- sync_dev ------------------------------------------------------------------
# upstream dev has the integration; origin main is a base commit naming that dev
# commit, plus a HACS-only edit to its last line. Then dev changes line $1.
make_sync_sandbox() {
  rm -rf "$SANDBOX/up.git" "$SANDBOX/origin.git" "$SANDBOX/seed" "$SANDBOX/work"
  git init -q --bare -b dev "$SANDBOX/up.git"
  git init -q --bare -b main "$SANDBOX/origin.git"
  git init -q -b dev "$SANDBOX/seed"
  (
    cd "$SANDBOX/seed" || exit 1
    mkdir -p "$INTEG_DIR" "$TESTS"
    printf 'one\ntwo\nthree\nfour\nfive\n' > "$INTEG_DIR/x.py"
    echo test > "$TESTS/test_x.py"
    echo core > core.txt
    git_ add -A && git_ commit -qm "core dev"
    git push -q "$SANDBOX/up.git" dev
    git checkout -q -b main
    git_ commit -q --allow-empty -m "HACS core base: core 2026.1.0 with teslemetry from dev $(git rev-parse --short=10 dev)"
    sed -i 's/^five$/five hacs/' "$INTEG_DIR/x.py"
    git_ commit -qam "HACS-only patch"
    git push -q "$SANDBOX/origin.git" main
    git checkout -q dev
    sed -i "s/^$1\$/$1 dev/" "$INTEG_DIR/x.py"
    git_ commit -qam "dev change"
    git push -q "$SANDBOX/up.git" dev
  )
  git clone -q "$SANDBOX/origin.git" "$SANDBOX/work"
  git -C "$SANDBOX/work" remote add upstream "$SANDBOX/up.git"
}
run_sync() {
  (
    cd "$SANDBOX/work" || exit 1
    # shellcheck source=release.sh
    source "$ROOT/release.sh"
    RERERE=0 START=$(git rev-parse HEAD)
    sync_dev
  ) >"$SANDBOX/out" 2>&1
}
work() { git -C "$SANDBOX/work" "$@"; }

make_sync_sandbox one
run_sync; rc=$?
check "sync: completes" 0 "$rc"
check "sync: dev change and HACS patch both kept" "one dev|two|three|four|five hacs" "$(work show "HEAD:$INTEG_DIR/x.py" | paste -sd'|' -)"
check "sync: commit names the dev commit" "Sync teslemetry from dev $(git -C "$SANDBOX/seed" rev-parse dev)" "$(work log -1 --format=%s)"
check "sync: core outside the integration untouched" "" "$(work diff HEAD~1 HEAD --name-only -- core.txt)"
# The next sync starts from the dev commit the last sync named.
( cd "$SANDBOX/seed" && sed -i 's/^three$/three dev/' "$INTEG_DIR/x.py" && git_ commit -qam "dev change 2" && git push -q "$SANDBOX/up.git" dev )
run_sync; rc=$?
check "sync: second sync completes" 0 "$rc"
check "sync: second sync applies only the new dev change" "one dev|two|three dev|four|five hacs" "$(work show "HEAD:$INTEG_DIR/x.py" | paste -sd'|' -)"
run_sync; rc=$?
check "sync: nothing new in dev makes no commit" "Sync teslemetry from dev $(git -C "$SANDBOX/seed" rev-parse dev)" "$(work log -1 --format=%s)"
check "sync: nothing new in dev says so" 1 "$(grep -c 'no integration change in core dev' "$SANDBOX/out")"
make_sync_sandbox five
run_sync; rc=$?
check "sync: conflict with a HACS patch stops" 3 "$rc"
check "sync: stop names the unmerged file" 1 "$(grep -c "unmerged: $INTEG_DIR/x.py" "$SANDBOX/out")"

# --- plan_compose --------------------------------------------------------------
# Open core PRs 100 and 300. Open fork PRs: 48, 49, 50, 51 (teslemetry, base
# dev), 74 (teslemetry, base fm/x), 75 (teslemetry, base fm/y), 46 (teslemetry),
# 58 (no teslemetry path). Closed fork PRs: 47 (opened upstream as core 300), 52
# (teslemetry, not promoted), 53 (no teslemetry path), 54 (opened upstream as
# core 302, neither open nor merged), 45 (not promoted). Core 301 is merged.
run_plan() {
  printf '%s\n' "$@" > "$SANDBOX/queue"
  # shellcheck disable=SC2016,SC2329
  bash -c '
    source "$1"
    pr() { printf "{\"number\": %s, \"title\": \"t%s\", \"isDraft\": true, \"headRefOid\": \"h%s\", \"baseRefName\": \"%s\", \"files\": [{\"path\": \"%s\"}]}" "$1" "$1" "$1" "$2" "$3"; }
    list_open_prs() {
      if [ "$1" = "$CORE_REPO" ]; then echo "[$(pr 300 dev x), $(pr 100 dev x)]"; return; fi
      echo "[$(pr 48 dev "$TESTS/a"), $(pr 49 dev "$INTEGRATION/a"), $(pr 50 dev "$INTEGRATION/a"),
             $(pr 51 dev "$INTEGRATION/a"), $(pr 74 fm/x "$INTEGRATION/a"), $(pr 75 fm/y "$INTEGRATION/a"),
             $(pr 46 dev "$INTEGRATION/a"), $(pr 58 dev homeassistant/components/tesla_fleet/a)]"
    }
    gh() {
      case "$*" in
        *pulls/52/files*) echo "$INTEGRATION/a" ;;
        *pulls/45/files*) echo "$INTEGRATION/a" ;;
        *pulls/53/files*) echo README ;;
        "api repos/$STAGING_REPO/pulls/"4[57]|"api repos/$STAGING_REPO/pulls/"5[234]) echo "{}" ;;
        *) return 1 ;;
      esac
    }
    promoted_core_pr() { case "$1" in 47) echo 300 ;; 54) echo 302 ;; esac; }
    core_pr_merged_head() { [ "$1" != 301 ] || echo m301; }
    fetch_ref() { echo "head-of-$2"; }
    PROMOTE_QUEUE=$2
    plan_compose
    printf "%s" "$FORK_PRS"' _ "$ROOT/release.sh" "$SANDBOX/queue" >"$SANDBOX/out" 2>&1
}
run_plan "74 docs-branch needs=fork#48" "48 docs-branch" 58 "49 needs=fork#47" "50 needs=core#301" "51 needs=core#100" 47 53; rc=$?
check "plan: completes" 0 "$rc"
check "plan: fork order and bases" "48 - -|49 fork#47 head-of-pull/47/head|50 core#301 m301|51 core#100 h100|74 fork#48 @fork#48" \
  "$(grep -P '^\d+\t' "$SANDBOX/out" | awk -F'\t' '{ print $1, ($5 == "" ? "-" : $5), ($6 == "" ? "-" : $6) }' | paste -sd'|' -)"
check "plan: core PRs ascending" 1 "$(grep -c '#100: open Bre77 teslemetry PR on core, composed' "$SANDBOX/out")"
check "plan: out of scope logged" 1 "$(grep -c 'fork#58: changes no teslemetry path' "$SANDBOX/out")"
check "plan: closed non-teslemetry logged" 1 "$(grep -c 'fork#53: closed and changes no teslemetry path' "$SANDBOX/out")"
check "plan: promoted queue entry carried by its core PR" 1 "$(grep -c 'fork#47: opened upstream as #300, which this build carries (composed)' "$SANDBOX/out")"
check "plan: promoted needs= base resolves" 1 "$(grep -c 'fork#49: its base fork#47 was opened upstream as #300 (composed)' "$SANDBOX/out")"
check "plan: every composed fork PR logged" 5 "$(grep -c 'approved in the queue, composed' "$SANDBOX/out")"

stops() { run_plan "$@"; echo "$?:$(grep -c "$STOP" "$SANDBOX/out")"; }
check "stop: closed unpromoted teslemetry PR" 3:1 "$(STOP="queued fork#52 .* is closed and was not opened upstream" stops 52)"
check "stop: needs= fork base neither open nor promoted" 3:1 "$(STOP="fork#49 needs fork#45" stops "49 needs=fork#45")"
check "stop: needs= core base neither open nor merged" 3:1 "$(STOP="fork#50 needs core#302" stops "50 needs=core#302")"
check "stop: promoted to a core PR the build lacks" 3:1 "$(STOP="queued fork#54 was opened upstream as #302" stops 54)"
check "stop: base other than dev without needs=" 3:1 "$(STOP="queued fork#75 .* targets fm/y, not dev" stops 75)"
check "stop: unreadable queue entry" 3:1 "$(STOP="queued fork#99 .* cannot be read" stops 99)"
check "die: needs= cycle" 1:1 "$(STOP="need each other in a cycle" stops "46 needs=fork#50" "50 needs=fork#46")"
check "die: malformed queue line" 1:1 "$(STOP="bad queue entry" stops "48 a b needs=fork#1")"

# --- apply_prs with needs= ----------------------------------------------------
# fork#48 branches from fork#47, which creates a file, and fork#47 gains a
# commit afterwards. Applied after fork#47, fork#48 applies only its own change;
# its plain net diff would re-add fork#47's file (add/add).
rm -rf "$SANDBOX/staging.git" "$SANDBOX/st"
git init -q --bare -b dev "$SANDBOX/staging.git"
git init -q -b dev "$SANDBOX/st"
(
  cd "$SANDBOX/st" || exit 1
  mkdir -p "$INTEG_DIR" "$TESTS"
  echo base > "$INTEG_DIR/x.py"
  echo test > "$TESTS/test_x.py"
  git_ add -A && git_ commit -qm "fork dev"
  git push -q "$SANDBOX/staging.git" dev
  git checkout -q -b p47
  echo new > "$INTEG_DIR/new.py"
  echo p47 >> "$INTEG_DIR/x.py"
  git_ add -A && git_ commit -qm "base change"
  git checkout -q -b p48
  echo dependent >> "$INTEG_DIR/new.py"
  git_ commit -qam "dependent change"
  git checkout -q p47
  echo "p47 later" >> "$INTEG_DIR/x.py"
  git_ commit -qam "base change, later"
  git push -q "$SANDBOX/staging.git" p47:refs/pull/47/head p48:refs/pull/48/head
)
H47=$(git -C "$SANDBOX/st" rev-parse p47) H48=$(git -C "$SANDBOX/st" rev-parse p48)
run_compose() {
  rm -rf "$SANDBOX/cw"
  git clone -q -b dev "$SANDBOX/staging.git" "$SANDBOX/cw"
  (
    cd "$SANDBOX/cw" || exit 1
    # shellcheck source=release.sh
    source "$ROOT/release.sh"
    RERERE=0 START=$(git rev-parse HEAD) CORE_PRS="" FORK_PRS=$1
    # shellcheck disable=SC2329
    fetch_ref() { git fetch -q "$SANDBOX/staging.git" "$2" && git rev-parse FETCH_HEAD; }
    apply_prs
  ) >"$SANDBOX/out" 2>&1
}
run_compose "$(printf '47\tbase\tfalse\t%s\t\t\n48\tdependent\tfalse\t%s\tfork#47\t@fork#47\n' "$H47" "$H48")"; rc=$?
check "needs compose: completes" 0 "$rc"
check "needs compose: order" "fork#48: dependent|fork#47: base" "$(git -C "$SANDBOX/cw" log -2 --format=%s | paste -sd'|' -)"
check "needs compose: both changes" "new dependent|base p47 p47 later" \
  "$(git -C "$SANDBOX/cw" show "HEAD:$INTEG_DIR/new.py" | paste -sd' ' -)|$(git -C "$SANDBOX/cw" show "HEAD:$INTEG_DIR/x.py" | paste -sd' ' -)"
run_compose "$(printf '47\tbase\tfalse\t%s\t\t\n48\tdependent\tfalse\t%s\t\t\n' "$H47" "$H48")"; rc=$?
check "needs compose: without needs= the net diff stops" 3 "$rc"

[ "$FAILED" = 0 ] && echo "all passed"
exit "$FAILED"
