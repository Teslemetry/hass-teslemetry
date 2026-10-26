#!/usr/bin/env bash
#
# HACS pre-release build for hass-teslemetry.
#
# Usage:  ./release.sh daily [--publish]
#
# One channel: every build is a GitHub pre-release v<UTC Y.M.D> (a second build
# on the same UTC day takes .1, .2, ...). The captain promotes a tested
# pre-release to latest himself; this script never builds latest.
#
# The steps follow the original release.sh (73e316e6680) and the runbook that
# replaced it (1160c4445da). AGENTS.md ("Task: build a release") says why each
# kept piece exists.
#   1. Version from today's UTC date.
#   2. Release branch release-<version> at HEAD (fork main).
#   3. Sync: core dev's changes to the integration and its tests since main's
#      last sync, as one net diff.
#   4. Every open Bre77 teslemetry PR on core, then every fork PR in the
#      ha-promoter queue (PROMOTE_QUEUE), each as one net diff; then the
#      release fixups. An approved PR that cannot be composed stops the run.
#   5. Version into both manifests; release notes.
#   6. Gates, then the integration's tests on the hacs.json floor release.
#   7. With --publish: push the sync to main, tag, zip, publish the pre-release.
#
# Every diff applies with a three-way merge. With RELEASE_RERERE_CACHE set,
# git rerere replays the resolutions recorded by earlier runs. A conflict it
# cannot replay, or an approved PR that cannot be composed, is a stop: the run
# prints why and exits 3, nothing published. A failed gate exits 1. Without
# --publish the run is a dry run that pushes nothing.

set -euo pipefail

FORK_REPO="Teslemetry/hass-teslemetry"      # origin: the HACS fork we release
CORE_REPO="home-assistant/core"             # upstream: core, source of PRs/dev
STAGING_REPO="Teslemetry/home-assistant"    # staging fork: approved PRs awaiting upstream
PR_LIST_LIMIT=200                           # gh pr list page size; filling it dies (see list_open_prs)
INTEGRATION="homeassistant/components/teslemetry"
TESTS="tests/components/teslemetry"

# --- output helpers ----------------------------------------------------------
log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }
# A checkpoint that needs a human: nothing is published.
stop() {
  printf '\n\033[1;31mHEADLESS STOP (needs a human, nothing published): %s\033[0m\n' "$*" >&2
  exit 3
}

# Stop at a conflict rerere could not replay, leaving it in the tree. $1 says
# what conflicted. To record a resolution: edit each unmerged file, `git add`
# it, run `git -c rerere.enabled=true rerere`, and rerun from the start commit.
stop_conflict() {
  git diff --name-only --diff-filter=U | sed 's/^/    unmerged: /' >&2
  # shellcheck disable=SC2016  # backticks are literal
  printf '    To resolve: edit each unmerged file, git add it, run `git -c rerere.enabled=true rerere`, then `git reset -q --hard && git checkout -q -f %s` and rerun.\n' "$START" >&2
  stop "$1"
}

# Fail if a tracked file in the integration or its tests has a leftover
# conflict marker.
assert_no_conflict_markers() {
  if git grep -nE '^(<{7}|>{7})( |$)' -- "$INTEGRATION" "$TESTS"; then
    die "conflict markers found (above)"
  fi
}

# Point git rerere at the persistent cache RELEASE_RERERE_CACHE, so a
# resolution recorded in one run replays in the next. git has no setting for
# the rr-cache location, so the repo's rr-cache becomes a symlink to it.
setup_rerere() {
  RERERE=0
  [ -n "${RELEASE_RERERE_CACHE:-}" ] || { info "rerere: off (RELEASE_RERERE_CACHE unset)"; return 0; }
  mkdir -p "$RELEASE_RERERE_CACHE"
  local cache link
  cache=$(cd "$RELEASE_RERERE_CACHE" && pwd -P)
  link="$(git rev-parse --git-common-dir)/rr-cache"
  if [ -L "$link" ]; then
    [ "$(readlink -f "$link")" = "$cache" ] \
      || die "$link points at $(readlink -f "$link"), not RELEASE_RERERE_CACHE ($cache)"
  elif [ -e "$link" ]; then
    die "$link is a real directory - move its contents into $cache and delete it, so rerere uses one cache"
  else
    ln -s "$cache" "$link"
  fi
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=rerere.enabled GIT_CONFIG_VALUE_0=true
  RERERE=1
  info "rerere: on, cache $cache"
}

# After a failed `git apply -3`, return 0 only if rerere replayed a recorded
# resolution for every conflicted path, and stage those paths.
rerere_resolved() {
  [ "$RERERE" = 1 ] || return 1
  local unmerged path
  unmerged=$(git diff --name-only --diff-filter=U)
  [ -n "$unmerged" ] || return 1
  [ -z "$(git rerere remaining)" ] || return 1
  git diff -z --name-only --diff-filter=U | xargs -0 git add --
  while IFS= read -r path; do info "rerere replayed: $path"; done <<<"$unmerged"
}

# Apply a diff from stdin with a three-way merge. Returns 1 on a conflict
# rerere did not replay.
apply_3way() {
  git apply -3 && return 0
  rerere_resolved
}

# --- the hacs.json floor release -----------------------------------------------
# The zip must run on the core release hacs.json's "homeassistant" floor names,
# so the tests run with every core path outside the integration at that tag.

# Core-owned paths the tests take from the floor tag. homeassistant/generated
# stays as main has it: it carries teslemetry's own Labs data (generated/labs.py),
# which a HACS install reads from its manifest instead.
CORE_BASE_PATHS=(homeassistant tests script pyproject.toml requirements.txt
  requirements_all.txt requirements_test.txt requirements_test_pre_commit.txt
  .python-version)

# Print the hacs.json floor: a full core version, the name of its tag.
core_base_tag() {
  local floor
  floor=$(jq -r '.homeassistant // ""' hacs.json)
  [[ "$floor" =~ ^[0-9]{4}\.[0-9]+\.[0-9]+(b[0-9]+)?$ ]] \
    || die "hacs.json homeassistant floor '$floor' is not a full core version (e.g. 2026.10.0)"
  printf '%s\n' "$floor"
}

# Fetch core tag $1 into refs/tags/$1 from the upstream remote, or from core on
# GitHub where there is none (CI).
fetch_core_tag() {
  local src
  src=$(git remote get-url upstream 2>/dev/null || echo "https://github.com/$CORE_REPO")
  git fetch --quiet --no-tags "$src" "+refs/tags/$1:refs/tags/$1"
}

# Put every CORE_BASE_PATHS path outside the integration and its tests in the
# work tree at the floor tag. Work tree only. The CI workflow runs it too.
restore_core_base() {
  local tag
  tag=$(core_base_tag)
  log "Core at the hacs.json floor $tag"
  fetch_core_tag "$tag" || die "could not fetch core tag $tag - the hacs.json floor must be a released core version"
  git restore --source="refs/tags/$tag^{commit}" --worktree -- "${CORE_BASE_PATHS[@]}" \
    ":(exclude)$INTEGRATION" ":(exclude)$TESTS" ":(exclude)homeassistant/generated"
  pin_integration_requirements
  alias_pytest_homeassistant "$tag"
  info "core paths outside the integration match core $tag; requirements_all.txt has the integration's pins"
}

# TEMPORARY. Core dev's teslemetry tests import their helpers from the
# pytest_homeassistant package (packages/pytest-home-assistant), which core tag
# $1 predates: there they are the same modules under tests. When the tag has no
# such package, write an untracked pytest_homeassistant package at the repo root
# that makes every pytest_homeassistant.<name> import return the module
# tests.<name>, the same object, so module state and mock.patch targets are
# shared. Delete this function and its call once the floor has the package.
alias_pytest_homeassistant() {
  rm -rf pytest_homeassistant
  if git cat-file -e "refs/tags/$1^{commit}:packages/pytest-home-assistant/pytest_homeassistant" 2>/dev/null; then
    return 0
  fi
  mkdir pytest_homeassistant
  cat > pytest_homeassistant/__init__.py <<'EOF'
"""pytest_homeassistant as an alias of tests, for a core release before it.

Written by release.sh's alias_pytest_homeassistant; never committed.
"""

import importlib
import importlib.abc
import importlib.util
import sys


class _TestsAlias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import pytest_homeassistant.<name> as the module tests.<name>."""

    def find_spec(self, fullname, path, target=None):
        if fullname.startswith(f"{__name__}."):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        module = importlib.import_module(f"tests{spec.name[len(__name__) :]}")
        spec.loader_state = module.__spec__
        return module

    def exec_module(self, module):
        # The import system set the alias spec on the tests module; put back its own.
        module.__spec__ = module.__spec__.loader_state


sys.meta_path.insert(0, _TestsAlias())
EOF
  info "core $1 has no pytest_homeassistant package: aliased it to tests (untracked, see alias_pytest_homeassistant)"
}

# In requirements_all.txt, replace the line of each package the integration's
# manifest requires with the manifest's pin, and append a pin no line has.
# Package names compare as pip does: case-insensitive, with - _ . the same.
pin_integration_requirements() {
  local out
  out=$(jq -r '.requirements[]' "$INTEGRATION/manifest.json" | awk '
    function norm(r) { r = tolower(r); sub(/[=<>!~\[;[:space:]].*/, "", r); gsub(/[-_.]+/, "-", r); return r }
    FNR == NR { pin[norm($0)] = $0; next }
    /^[^#[:space:]]/ && (norm($0) in pin) { print pin[norm($0)]; used[norm($0)] = 1; next }
    { print }
    END {
      for (p in pin) if (!(p in used)) {
        if (!header++) print "\n# homeassistant.components.teslemetry"
        print pin[p]
      }
    }' - requirements_all.txt) || die "could not pin the integration requirements in requirements_all.txt"
  printf '%s\n' "$out" > requirements_all.txt
}

# --- steps -------------------------------------------------------------------

parse_args() {
  PUBLISH=0
  local mode=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      daily)     mode=daily ;;
      --publish) PUBLISH=1 ;;
      *) die "unknown argument: $1 (usage: ./release.sh daily [--publish])" ;;
    esac
    shift
  done
  [ "$mode" = daily ] || die "usage: ./release.sh daily [--publish]"
}

preflight() {
  log "Preflight"
  local branch
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  [ "$branch" != main ] || die "on 'main' - run this from a detached or other checkout; it commits on a release branch"
  [ -z "$(git status --porcelain)" ] || die "working tree is dirty - start from a clean checkout"
  git remote get-url origin   >/dev/null 2>&1 || die "no 'origin' remote (expected $FORK_REPO)"
  git remote get-url upstream >/dev/null 2>&1 || die "no 'upstream' remote (expected $CORE_REPO)"
  local tool
  for tool in gh jq yq git uv zip; do
    command -v "$tool" >/dev/null 2>&1 || die "required tool not found: $tool"
  done
  [ -n "${PROMOTE_QUEUE:-}" ] || die "PROMOTE_QUEUE is not set - it names the ha-promoter queue of approved fork PRs"
  [ -r "$PROMOTE_QUEUE" ] || die "PROMOTE_QUEUE=$PROMOTE_QUEUE is not a readable file"
  # A shallow clone breaks the merge-base work in apply_one_pr.
  if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
    info "shallow clone: fetching full history"
    git fetch --quiet --unshallow origin || die "could not unshallow the clone from origin"
  fi
  START=$(git rev-parse HEAD)
  git fetch --quiet origin '+refs/heads/main:refs/remotes/origin/main' || die "could not fetch origin main"
  # A publish pushes the sync commit to main, so it must be built on main.
  if [ "$PUBLISH" = 1 ] && [ "$START" != "$(git rev-parse refs/remotes/origin/main)" ]; then
    die "--publish builds only from origin/main, and HEAD is $START"
  fi
  info "start=$START publish=$PUBLISH"
}

# Step 1: the first free v<UTC Y.M.D>, then .1, .2, ... AwesomeVersion orders
# 2026.10.5 < 2026.10.5.1 < 2026.10.6.
determine_version() {
  log "Step 1: determine version"
  git fetch --quiet --tags origin || die "could not fetch tags from origin"
  local base n=0
  base=$(date -u +%Y.%-m.%-d)
  VERSION=$base
  while git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; do
    n=$((n + 1))
    VERSION="$base.$n"
  done
  info "new version: $VERSION (pre-release)"
}

# Step 2: the release branch, at the commit this run started from.
create_release_branch() {
  log "Step 2: create release branch"
  git checkout -q -B "release-$VERSION"
  info "on release-$VERSION"
}

# Print the core dev commit main last took the integration from: the newest
# first-parent commit whose subject says "teslemetry from dev <SHA>" (a sync
# commit, or main's original "HACS core base:" commit).
last_synced_dev() {
  local sha
  sha=$(git log --first-parent --format=%s HEAD \
          | sed -nE 's/.*teslemetry from dev ([0-9a-f]{10,40}).*/\1/p' | head -1)
  [ -n "$sha" ] || die "no commit on main says which core dev commit its integration came from (\"teslemetry from dev <SHA>\")"
  git rev-parse --verify -q "$sha^{commit}" || die "core dev commit $sha (main's last sync) is not in this clone - fetch upstream dev"
}

# Step 3: bring core dev's changes to the integration and its tests since
# main's last sync, as one net diff and one commit. --publish pushes that
# commit to main (see publish), so each resolution lands on main once.
sync_dev() {
  log "Step 3: sync the integration from core dev"
  git fetch --quiet upstream dev || die "could not fetch upstream dev"
  DEV=$(git rev-parse upstream/dev)
  SYNC=""
  local from
  from=$(last_synced_dev)
  if git diff --quiet "$from" "$DEV" -- "$INTEGRATION" "$TESTS"; then
    info "no integration change in core dev since ${from:0:10}"
    return 0
  fi
  git diff --full-index --binary --no-renames "$from" "$DEV" -- "$INTEGRATION" "$TESTS" | apply_3way \
    || stop_conflict "core dev's integration changes ${from:0:10}..${DEV:0:10} conflict with main"
  git add -A -- "$INTEGRATION" "$TESTS"
  git commit -q -m "Sync teslemetry from dev $DEV" --no-verify
  assert_no_conflict_markers
  SYNC=$(git rev-parse HEAD)
  info "synced from ${from:0:10} to dev ${DEV:0:10}"
}

# Fetch one ref from a GitHub repo and print its commit.
fetch_ref() {
  git fetch --quiet "https://github.com/$1" "$2" || die "could not fetch $1 $2"
  git rev-parse FETCH_HEAD
}

# List open PRs on a repo as a JSON array. Extra args are passed to gh pr list.
# gh defaults to 30 results and truncates silently, so a result that fills the
# limit dies instead of composing a partial release.
list_open_prs() {
  local repo="$1"; shift
  local json count
  json=$(gh pr list --repo "$repo" --state open --limit "$PR_LIST_LIMIT" \
           --json number,title,isDraft,headRefOid,baseRefName,files "$@") \
    || die "could not list open PRs on $repo"
  count=$(jq 'length' <<<"$json")
  [ "$count" -lt "$PR_LIST_LIMIT" ] \
    || die "gh pr list on $repo returned $count PRs, the --limit - the list may be truncated. Raise PR_LIST_LIMIT and rerun."
  printf '%s' "$json"
}

# Fork PR numbers in queue file $1 as "<number><TAB><needs>" lines, in file
# order. A line is `123`, `#123` or the fork PR URL, optionally a docs branch
# (ignored here), optionally `needs=core#<N>` or `needs=fork#<N>`. Blank lines
# are skipped; any other line dies, so a malformed queue never drops a PR.
read_promote_queue() {
  local file="$1" line entry docs needs rest num
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    read -r entry docs needs rest <<<"$line"
    [ -n "$entry" ] || continue
    [[ "$entry" =~ ^(#|https://github\.com/$STAGING_REPO/pull/)?([0-9]+)$ ]] \
      || die "PROMOTE_QUEUE=$file: bad queue entry: $line"
    num=${BASH_REMATCH[2]}
    # needs= is never a docs branch: without a docs branch it comes second.
    if [[ "$docs" == needs=* ]]; then rest="$needs${rest:+ $rest}" needs=$docs; fi
    if [[ "$needs" != needs=* ]]; then rest="$needs${rest:+ $rest}" needs=""; fi
    if [[ " $rest" == *" needs="* ]] || { [ -n "$needs" ] && ! [[ "$needs" =~ ^needs=(core|fork)#[0-9]+$ ]]; }; then
      die "PROMOTE_QUEUE=$file: bad queue entry: $line"
    fi
    printf '%s\t%s\n' "$num" "${needs#needs=}"
  done < "$file"
}

# Whether PR JSON $1 changes the integration or its tests.
touches_teslemetry() {
  jq -e --arg i "$INTEGRATION/" --arg t "$TESTS/" \
    'any(.files[]?.path; startswith($i) or startswith($t))' <<<"$1" >/dev/null
}

# Print the core PR ha-promoter opened fork PR $1 as (its "opened upstream as
# <core PR URL>" comment), or nothing. ha-promoter then closes the fork PR and
# the change continues as that core PR.
promoted_core_pr() {
  local core
  core=$(gh api "repos/$STAGING_REPO/issues/$1/comments?per_page=100" --paginate \
           --jq '.[].body | capture("opened upstream as https://github\\.com/home-assistant/core/pull/(?<n>[0-9]+)").n') \
    || die "could not read the comments on $STAGING_REPO pull $1"
  tail -1 <<<"$core"
}

# Print the head of core PR $1 when it is merged into core dev at $DEV, or
# nothing.
core_pr_merged_head() {
  local pr merge head
  pr=$(gh api "repos/$CORE_REPO/pulls/$1" --jq 'select(.merged and .base.ref == "dev") | "\(.merge_commit_sha) \(.head.sha)"') \
    || die "could not read $CORE_REPO pull $1"
  read -r merge head <<<"$pr"
  [ -n "$merge" ] && git cat-file -e "$merge^{commit}" 2>/dev/null \
    && git merge-base --is-ancestor "$merge" "$DEV" || return 0
  printf '%s\n' "$head"
}

# Print how core PR $1 reaches this build: "composed" (an open Bre77
# teslemetry PR), "merged" (in core dev), or nothing.
core_change_status() {
  if cut -f1 <<<"$CORE_PRS" | grep -qx "$1"; then echo composed
  elif [ -n "$(core_pr_merged_head "$1")" ]; then echo merged
  fi
}

# Step 4a: the compose set. CORE_PRS: every open Bre77 teslemetry PR on core,
# ascending, as "number<TAB>title<TAB>draft<TAB>head" lines. FORK_PRS: every
# fork PR in the queue, in apply order, with two more fields: its needs= base
# and that base's head ("@fork#N" while the base is a fork PR in this compose).
#
# Each queue entry ends in exactly one logged disposition, or the run stops:
#   - an open fork PR that changes the integration or its tests: composed;
#   - a fork PR that changes neither: not a HACS change, not composed;
#   - a closed fork PR ha-promoter opened upstream as core PR M: its change
#     arrives as M, which must be composed or merged into core dev.
# A needs= base must resolve the same way: an open fork PR in the queue, or a
# fork PR promoted to a core PR this build composes or core dev has merged, or
# such a core PR itself. A needs=fork entry applies after its base.
plan_compose() {
  log "Step 4: compose set"
  local core_json
  core_json=$(list_open_prs "$CORE_REPO" --author Bre77 --label "integration: teslemetry")
  CORE_PRS=$(jq -r 'sort_by(.number)[] | "\(.number)\t\(.title)\t\(.isDraft)\t\(.headRefOid)"' <<<"$core_json")
  local num title
  while IFS=$'\t' read -r num title _; do
    [ -n "$num" ] && info "#$num: open Bre77 teslemetry PR on core, composed ($title)"
  done <<<"$CORE_PRS"

  local open queue
  open=$(list_open_prs "$STAGING_REPO")
  queue=$(read_promote_queue "$PROMOTE_QUEUE")
  local -A line=() needs_of=() seen=()
  local needs pr core status files
  while IFS=$'\t' read -r num needs; do
    [ -n "$num" ] && [ -z "${seen[$num]:-}" ] || continue
    seen[$num]=1
    pr=$(jq -c --argjson n "$num" 'map(select(.number == $n))[0] // empty' <<<"$open")
    if [ -z "$pr" ]; then
      pr=$(gh api "repos/$STAGING_REPO/pulls/$num" 2>/dev/null) \
        || stop "queued fork#$num (https://github.com/$STAGING_REPO/pull/$num) cannot be read - take it out of the queue or fix the entry"
      core=$(promoted_core_pr "$num")
      if [ -z "$core" ]; then
        files=$(gh api "repos/$STAGING_REPO/pulls/$num/files?per_page=100" --paginate --jq '.[].filename') \
          || die "could not read the files of $STAGING_REPO pull $num"
        if grep -qE "^($INTEGRATION|$TESTS)/" <<<"$files"; then
          stop "queued fork#$num (https://github.com/$STAGING_REPO/pull/$num) is closed and was not opened upstream - reopen it or take it out of the queue"
        fi
        info "fork#$num: closed and changes no teslemetry path; not a HACS change, not composed"
        continue
      fi
      status=$(core_change_status "$core")
      [ -n "$status" ] \
        || stop "queued fork#$num was opened upstream as #$core (https://github.com/$CORE_REPO/pull/$core), which is neither an open Bre77 teslemetry PR nor merged into core dev"
      info "fork#$num: opened upstream as #$core, which this build carries ($status)"
      continue
    fi
    if ! touches_teslemetry "$pr"; then
      info "fork#$num: changes no teslemetry path; not a HACS change, not composed"
      continue
    fi
    if [ "$(jq -r .baseRefName <<<"$pr")" != dev ] && [[ "$needs" != fork#* ]]; then
      stop "queued fork#$num (https://github.com/$STAGING_REPO/pull/$num) targets $(jq -r .baseRefName <<<"$pr"), not dev, and its queue line names no needs=fork#<N> base"
    fi
    line[$num]=$(jq -r '"\(.number)\t\(.title)\t\(.isDraft)\t\(.headRefOid)"' <<<"$pr")
    needs_of[$num]=$needs
  done <<<"$queue"

  # Resolve each needs= base to the head its diff starts from.
  local -A base_head=()
  local n ref k
  for n in "${!needs_of[@]}"; do
    ref=${needs_of[$n]}
    [ -n "$ref" ] || continue
    k=${ref#*#}
    if [[ "$ref" == core#* ]]; then
      if cut -f1 <<<"$CORE_PRS" | grep -qx "$k"; then
        base_head[$n]=$(awk -F'\t' -v k="$k" '$1 == k { print $4 }' <<<"$CORE_PRS")
      else
        base_head[$n]=$(core_pr_merged_head "$k")
        [ -n "${base_head[$n]}" ] \
          || stop "fork#$n needs core#$k (https://github.com/$CORE_REPO/pull/$k), which is neither an open Bre77 teslemetry PR nor merged into core dev"
        git cat-file -e "${base_head[$n]}^{commit}" 2>/dev/null || fetch_ref "$CORE_REPO" "pull/$k/head" >/dev/null
      fi
    elif [ -n "${line[$k]:-}" ]; then
      base_head[$n]="@fork#$k"
    else
      core=$(promoted_core_pr "$k")
      [ -n "$core" ] && status=$(core_change_status "$core") && [ -n "$status" ] \
        || stop "fork#$n needs fork#$k (https://github.com/$STAGING_REPO/pull/$k), which is not a queued open teslemetry fork PR and was not opened upstream as a core PR this build carries"
      base_head[$n]=$(fetch_ref "$STAGING_REPO" "pull/$k/head")
      info "fork#$n: its base fork#$k was opened upstream as #$core ($status)"
    fi
  done

  # Ascending, except that an entry waits for its fork base.
  FORK_PRS=""
  local -A done_=()
  local pending ready
  pending=$(printf '%s\n' "${!line[@]}" | sort -n)
  while [ -n "$pending" ]; do
    ready=""
    for n in $pending; do
      ref=${base_head[$n]:-}
      if [[ "$ref" != @fork#* ]] || [ -n "${done_[${ref#@fork#}]:-}" ]; then ready=$n; break; fi
    done
    [ -n "$ready" ] || die "fork PRs $(sed 's/^/fork#/' <<<"$pending" | paste -sd' ' -) need each other in a cycle (PROMOTE_QUEUE needs=)"
    done_[$ready]=1
    FORK_PRS+="${line[$ready]}"$'\t'"${needs_of[$ready]}"$'\t'"${base_head[$ready]:-}"$'\n'
    pending=$(grep -vx "$ready" <<<"$pending" || true)
    info "fork#$ready: approved in the queue, composed${needs_of[$ready]:+ after its base ${needs_of[$ready]}} ($(cut -f2 <<<"${line[$ready]}"))"
  done
}

# Apply one PR as one commit. $1 repo, $2 number, $3 title, $4 draft flag,
# $5 ref prefix ("#" core, "fork#" fork), $6 the PR's base branch commit, $7
# the listed head, $8 the head of its needs= base (empty: none).
#
# It applies the PR's net diff (merge-base to the listed head) to the
# integration and its tests only, which is all the zip ships. A needs= PR's
# branch carries its base's commits, so its diff starts at its merge-base with
# the base's head: re-applying the base's change would conflict (add/add).
# TEMPORARY: quality_scale.yaml is left out of every diff (quality-scale PRs
# conflict on it repeatedly, and Home Assistant never reads it at runtime).
apply_one_pr() {
  local repo="$1" num="$2" title="$3" draft="$4" ref="$5$2" base="$6" listed="$7" needs_head="${8:-}"
  log "  PR $ref: $title"
  local head mb nmb
  head=$(fetch_ref "$repo" "pull/$num/head")
  if [ "$head" != "$listed" ]; then
    info "head moved to $head since listing; applying the listed $listed"
    head=$(fetch_ref "$repo" "$listed")
  fi
  mb=$(git merge-base "$base" "$head") || die "no merge-base for $repo pull/$num and its base"
  if [ -n "$needs_head" ] && nmb=$(git merge-base "$needs_head" "$head") \
     && git merge-base --is-ancestor "$mb" "$nmb"; then
    mb=$nmb
    info "diff from its merge-base with its needs= base, ${mb:0:10}"
  fi
  local pathspec=("$INTEGRATION" "$TESTS" ":(exclude)$INTEGRATION/quality_scale.yaml")
  if git diff --quiet "$mb" "$head" -- "${pathspec[@]}"; then
    info "no teslemetry changes to apply"
  elif git diff --full-index --binary "$mb" "$head" -- "${pathspec[@]}" | apply_3way; then
    info "applied"
  else
    stop_conflict "PR $ref (https://github.com/$repo/pull/$num) did not apply cleanly"
  fi
  git add -A -- "$INTEGRATION" "$TESTS"
  git commit -q -m "$ref: $title" --allow-empty --no-verify
  assert_no_conflict_markers
  local status=""
  if [ "$repo" = "$STAGING_REPO" ]; then
    if [ "$draft" = true ]; then status=" (staged, draft)"; else status=" (staged, ready)"; fi
  fi
  NOTE_LINES+=("[$ref](https://github.com/$repo/pull/$num): $title$status")
  APPLIED_HEADS[$ref]=$head
}

# Step 4b: apply the compose set, core PRs first, then the release fixups.
declare -A APPLIED_HEADS=()
apply_prs() {
  log "Step 4: apply core and fork PR net diffs"
  NOTE_LINES=()
  local num title draft sha needs needs_head core_base fork_base
  core_base=$(fetch_ref "$CORE_REPO" dev)
  while IFS=$'\t' read -r num title draft sha; do
    [ -n "$num" ] || continue
    apply_one_pr "$CORE_REPO" "$num" "$title" "$draft" "#" "$core_base" "$sha"
  done <<<"$CORE_PRS"
  fork_base=$(fetch_ref "$STAGING_REPO" dev)
  while IFS=$'\t' read -r num title draft sha needs needs_head; do
    [ -n "$num" ] || continue
    if [[ "$needs_head" == @fork#* ]]; then needs_head=${APPLIED_HEADS[${needs_head#@}]}; fi
    apply_one_pr "$STAGING_REPO" "$num" "$title" "$draft" "fork#" "$fork_base" "$sha" "$needs_head"
  done <<<"$FORK_PRS"
  apply_fixups
}

# Apply each tracked release fixup whose PRs this build composed, as one
# commit. A fixup adapts composed PRs to each other or to the floor release.
# Its file name lists the PRs it needs, joined by "+": core-<N> for #N,
# fork-<N> for fork#N (release-fixups/fork-60.patch). A fixup whose PRs are not
# all composed does nothing; delete it once its PRs have merged upstream.
apply_fixups() {
  local patch name part ref missing parts
  for patch in release-fixups/*.patch; do
    [ -f "$patch" ] || continue
    name=$(basename "$patch" .patch)
    missing=""
    IFS='+' read -ra parts <<<"$name"
    for part in "${parts[@]}"; do
      ref=${part/#core-/#}; ref=${ref/#fork-/fork#}
      [ -n "${APPLIED_HEADS[$ref]:-}" ] || missing+=" $ref"
    done
    if [ -n "$missing" ]; then
      info "fixup $name: not applied (${missing# } not in this build)"
      continue
    fi
    log "  fixup $name"
    # A fixup's index lines name blobs of the tree it was written on, which
    # this clone may lack: apply it directly first, three-way only if needed.
    git apply --index < "$patch" 2>/dev/null || apply_3way < "$patch" \
      || stop_conflict "$patch no longer applies - update it on main"
    git add -A -- "$INTEGRATION" "$TESTS"
    git commit -q -m "fixup: $name" --allow-empty --no-verify
    assert_no_conflict_markers
  done
}

# Exit 0 when the composed integration, which is all the zip ships, equals the
# newest daily build's (manifest version ignored): nothing new to publish.
skip_if_unchanged() {
  local last manifest="$INTEGRATION/manifest.json"
  last=$(git tag -l 'v[0-9][0-9][0-9][0-9].*' | sort -V | tail -1)
  [ -n "$last" ] || return 0
  if git diff --quiet "$last" HEAD -- "$INTEGRATION" ":(exclude)$manifest" \
     && cmp -s <(git show "$last:$manifest" | jq -S 'del(.version)') <(jq -S 'del(.version)' "$manifest"); then
    log "Composed integration is identical to $last - nothing published"
    exit 0
  fi
  info "composed integration differs from $last"
}

# Step 5: version into both manifests, and release_notes.txt (untracked; it
# feeds gh release create -F).
update_version() {
  log "Step 5: update version and release notes"
  release_compat_note > release_notes.txt
  cat >> release_notes.txt <<'NOTE'
Builds older than v3.0.0 request vehicle data every 30 seconds; v3.0.0 lowered that to every 15 minutes, and v4.0.0 changed it to every 60 seconds (v4.0.1 added the gate). Current builds do not poll modern streaming vehicles at all, and fall back to 60-second polling only for vehicles that cannot use signed commands. Upgrading stops the excess polling.
NOTE
  local line
  for line in ${NOTE_LINES[@]+"${NOTE_LINES[@]}"}; do printf '%s\n' "$line" >> release_notes.txt; done
  printf '\n**Full Changelog**: https://github.com/%s/commits/v%s\n' "$FORK_REPO" "$VERSION" >> release_notes.txt
  yq -i -o json ".version=\"$VERSION\"" "$INTEGRATION/manifest.json"
  cp "$INTEGRATION/manifest.json" "custom_components/teslemetry/manifest.json"
  git commit -q -am "v$VERSION" --no-verify
  info "manifests at $VERSION, release_notes.txt written"
}

# Print the release-notes notes this build needs: that it requires the
# hacs.json floor release, and, when the composed tesla-fleet-api pin is ahead
# of the one the floor release ships, that the built-in Tessie and Tesla Fleet
# integrations sharing that library may break.
release_compat_note() {
  local tag pin core_pin
  tag=$(core_base_tag)
  fetch_core_tag "$tag" || die "could not fetch core tag $tag"
  pin=$(jq -r '.requirements[]? | select(test("^tesla-fleet-api==")) | sub("^tesla-fleet-api=="; "")' "$INTEGRATION/manifest.json")
  core_pin=$(git show "refs/tags/$tag:homeassistant/components/tesla_fleet/manifest.json" \
               | jq -r '.requirements[]? | select(test("^tesla-fleet-api==")) | sub("^tesla-fleet-api=="; "")')
  [ -n "$pin" ] && [ -n "$core_pin" ] || die "cannot read the tesla-fleet-api pins of the build and of core $tag"
  if [ "$pin" != "$core_pin" ] && [ "$(printf '%s\n%s\n' "$pin" "$core_pin" | sort -V | tail -1)" = "$pin" ]; then
    # shellcheck disable=SC2016  # backticks are Markdown
    printf '> ⚠️ **Compatibility with the built-in Tessie and Tesla Fleet integrations**\n>\n> This beta uses `tesla-fleet-api` %s, newer than the %s that Home Assistant %s ships. The built-in **Tessie** and **Tesla Fleet** integrations share that library, so they may break when this beta runs on Home Assistant versions that ship the older library. Do not run this beta alongside them on those versions.\n\n' \
      "$pin" "$core_pin" "$tag"
  fi
  printf '> ⚠️ **Requires Home Assistant %s**\n>\n> This beta requires Home Assistant %s or newer. HACS will not install it on an older Home Assistant version.\n\n' \
    "${tag%.*}" "$tag"
}

# Gate: a config subentry type declared in const.py with no translations ships
# as a bare, unlabelled "+" button. v6.0.11 shipped that after a strings.json
# conflict resolution kept one side, and no test checks it. Every
# SUBENTRY_TYPE_* needs a non-empty config_subentries.<type>.initiate_flow.user
# in strings.json and in the separately compiled translations/en.json.
subentry_translations_gate() {
  log "Gate: declared config subentry types carry translations"
  local type file
  for type in $(sed -n 's/^SUBENTRY_TYPE_[A-Z0-9_]* *= *"\([^"]*\)".*/\1/p' "$INTEGRATION/const.py"); do
    for file in "$INTEGRATION/strings.json" "$INTEGRATION/translations/en.json"; do
      jq -e --arg t "$type" '.config_subentries[$t].initiate_flow.user | type == "string" and length > 0' \
        "$file" >/dev/null 2>&1 \
        || die "config subentry type '$type' has no config_subentries.$type.initiate_flow.user in $file - restore it in strings.json and recompile translations"
    done
    info "subentry type '$type' labelled in strings.json and translations/en.json"
  done
}

# Gate: the manifest requirements must install on the core releases hacs.json
# claims. Core installs them under its homeassistant/package_constraints.txt,
# which the tests do not apply; v6.0.24 shipped a tesla-fleet-api pin released
# core could not install. Resolved (nothing installed) under the floor release
# and under the newest stable core release, each at its own Python floor.
core_constraints_gate() {
  log "Gate: requirements installable on the hacs.json floor and the newest core release"
  local floor newest ref py tmp out
  floor=$(core_base_tag)
  newest=$(git ls-remote --tags --refs upstream \
             | sed -nE 's#.*refs/tags/([0-9]{4}\.[0-9]+\.[0-9]+)$#\1#p' | sort -V | tail -1)
  [ -n "$newest" ] || die "could not list core release tags on upstream"
  tmp=$(mktemp -d)
  jq -r '.requirements[]' "$INTEGRATION/manifest.json" > "$tmp/requirements.in"
  for ref in $(printf '%s\n%s\n' "$floor" "$newest" | sort -uV); do
    fetch_core_tag "$ref" || die "could not fetch core tag $ref"
    git show "refs/tags/$ref:homeassistant/package_constraints.txt" > "$tmp/constraints.txt"
    py=$(git show "refs/tags/$ref:pyproject.toml" | sed -nE 's/^requires-python *= *">= *([0-9.]+)".*/\1/p')
    [ -n "$py" ] || die "no requires-python in core $ref pyproject.toml"
    # --no-config: core's [tool.uv] settings must not bend the resolution.
    out=$(uv pip compile --no-config --quiet --python-version "$py" --python-platform linux \
            -c "$tmp/constraints.txt" -o "$tmp/resolved.txt" "$tmp/requirements.in" 2>&1) \
      || { rm -rf "$tmp"; die "requirements in $INTEGRATION/manifest.json do not resolve under core $ref (python >=$py) - fix the pin or raise the hacs.json floor:
$out"; }
    info "core $ref (python >=$py): resolves"
  done
  rm -rf "$tmp"
}

# HACS and Home Assistant read only the 30 newest releases. If latest falls out
# of that window, users are no longer offered it, so refuse at 25 newer.
release_window_guard() {
  log "Gate: latest release stays inside the 30-release window"
  local latest newer
  latest=$(gh api "repos/$FORK_REPO/releases/latest" --jq '.tag_name') \
    || die "could not read the latest release on $FORK_REPO"
  newer=$(gh api "repos/$FORK_REPO/releases?per_page=100" \
            | jq --arg t "$latest" '[.[] | select(.draft | not) | .tag_name] | (index($t) // length)') \
    || die "could not list releases on $FORK_REPO"
  [ "$newer" -lt 25 ] \
    || die "$newer releases are newer than latest $latest - one more pre-release pushes latest toward the 30-release window HACS reads. Promote a tested pre-release to latest first."
  info "$newer releases newer than latest $latest"
}

# Step 6: test the composed integration on the hacs.json floor release, as
# .github/workflows/teslemetry-test.yml does. This is the publish gate.
build_gate() {
  log "Step 6: tests on the hacs.json floor release"
  restore_core_base
  [ -d .venv ] || script/setup
  # shellcheck disable=SC1091
  source .venv/bin/activate
  script/setup
  uv pip install -r requirements_all.txt -r requirements_test.txt
  # --all: entities inherit services from other platforms whose translations
  # check_translations needs compiled. See AGENTS.md.
  python3 -m script.translations develop --all
  # --skip-plugins manifest: the manifest plugin rejects the fork's
  # issue_tracker key. See AGENTS.md.
  python3 -m script.hassfest --integration-path "$INTEGRATION" --skip-plugins manifest
  pytest "$TESTS"
  deactivate
  info "tests green on the floor release"
}

# Step 7: publish. Without --publish, a dry run that pushes nothing.
publish() {
  if [ "$PUBLISH" != 1 ]; then
    log "DRY RUN (no --publish flag)"
    info "Every gate passed. With --publish this run would push ${SYNC:+the sync commit ${SYNC:0:10} to main, }tag v$VERSION and publish it as the pre-release \"Pre-release v$VERSION\" on $FORK_REPO."
    exit 0
  fi
  log "Step 7: publish"
  if [ -n "$SYNC" ]; then
    git push origin "$SYNC:refs/heads/main" \
      || die "main moved since this run fetched it - nothing published. Rerun."
    info "main fast-forwarded to the sync commit ${SYNC:0:10}"
  fi
  git tag -a "v$VERSION" -m "Pre-release $VERSION"
  git push origin "v$VERSION"
  rm -f teslemetry.zip
  ( cd "$INTEGRATION" && rm -rf __pycache__ && rm -f ./*.orig && zip -qr "$OLDPWD/teslemetry.zip" ./* )
  gh release create "v$VERSION" -F release_notes.txt --repo "$FORK_REPO" -t "Pre-release v$VERSION" --prerelease
  gh release upload "v$VERSION" teslemetry.zip --repo "$FORK_REPO"
  rm -f teslemetry.zip
  git push origin "release-$VERSION"
  log "Published v$VERSION (prerelease) on $FORK_REPO"
}

main() {
  parse_args "$@"
  preflight
  setup_rerere
  determine_version
  create_release_branch
  sync_dev
  plan_compose
  apply_prs
  skip_if_unchanged
  update_version
  subentry_translations_gate
  core_constraints_gate
  [ "$PUBLISH" != 1 ] || release_window_guard
  build_gate
  publish
}

# Run only when executed, so CI can source restore_core_base without a build.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
