#!/usr/bin/env bash
#
# Reproducible HACS beta release pipeline for hass-teslemetry.
#
# Usage:  ./release.sh <major|minor|patch> [--line <major.minor>] [--lower-floor <version>] [--publish]
#         ./release.sh daily [--waive <#N|fork#N>] [--approve-requirements <digest>] [--lower-floor <version>] [--publish]
#
# This script IS the release process. AGENTS.md's "Task: build a release"
# section documents WHY each step exists and the gotchas behind each gate;
# this file owns HOW. Keep the two in sync when either changes.
#
# A cut composes the pinned core base (the core release tag named by hacs.json's
# "homeassistant" floor, with the integration and its tests taken from core dev)
# + every open Bre77 teslemetry PR on core + every open teslemetry PR on the
# staging fork Teslemetry/home-assistant (base dev), core PRs first (see
# apply_prs). With PROMOTE_QUEUE=<ha-promoter queue file> set, only the fork PRs
# queued there are taken (see list_fork_prs). A queue line is
# `<fork PR> [<docs branch>] [needs=core#<N>|needs=fork#<N>]`; a needs= entry
# builds on that unmerged base PR, is taken only when the cut also composes the
# base (or core#<N> is merged into dev), applies after it, and applies only its
# own change (see apply_one_pr). The build gate tests the
# integration against that core release (see restore_core_base).
#
# It runs the deterministic steps mechanically and hard-enforces the gates the
# old prose runbook trusted an operator to remember (the post-commit
# conflict-marker grep; the full local build gate). It STOPS for a human at exactly two kinds
# of checkpoint: an unresolved conflict, and the pre-publish approval pause.
# With RELEASE_RERERE_CACHE set, git rerere replays conflict resolutions
# recorded by earlier cuts, so only a conflict it has not seen before stops.
# A bump cut never auto-publishes: the real tag/release only runs with --publish
# AND an explicit human "publish" at the approval pause. Daily mode (below) has
# no human, so it stops at every checkpoint and publishes on --publish alone.
#
# Safe to run from an isolated worktree: it never checks out main. Every update
# to main goes through the temporary sync-dev branch: main's fork commits
# rebased onto a fresh core base commit (see sync_dev), pushed with a lease on
# the main this run fetched.
#
# Daily mode (`daily`) is the headless pre-release build a timer runs at 00:00
# UTC. It differs from a bump cut in these ways:
#   - Version v$(date -u +%Y.%-m.%-d); a further build on the same UTC day takes
#     .1, .2, ... (the first free tag). No bump argument, no --line.
#   - Change detection, two steps, no local state. Before composing it compares
#     an input fingerprint with the one in the newest pre-release tag's
#     annotation; after composing it compares the composed integration tree
#     (manifest "version" ignored) with that tag's. Either match exits 0 with
#     nothing published.
#   - Every human checkpoint becomes a headless stop: the run prints why and
#     exits 3 without reading /dev/tty. A gate failure exits 1, as in a bump cut.
#   - With --publish it publishes automatically once every gate has passed, as a
#     GitHub pre-release titled "Pre-release v<version>". It refuses to publish
#     when 25 or more releases are newer than the current latest release.
#   - It pushes the dev sync to main only after every gate has passed, and stops
#     with nothing published if main moved during the run.
#   - Without --publish it is a dry run that pushes nothing, main included.
#   - It also builds a new latest (stable) release when the rules below pass.
#
# Latest (`daily` decides it first, every run): latest is BUILT from the changes
# that met their own lead time, never promoted in place. "Breakfix goes fast,
# everything else goes safe."
#   - A change is one PR: an open core PR, a composed fork PR, or a core PR
#     merged into dev (the "(#N)" in its commit subject). Its type is the core
#     PR's type label, or the checked "Type of change" box of a fork PR's body;
#     a missing or ambiguous type counts as new-feature.
#   - Two clocks, in whole UTC days, from the pre-release tag annotations: the
#     change's age (first pre-release with the PR, or with its dev commit) must
#     reach its lead time, and its current head's age (first pre-release with
#     that head SHA, or with its dev commit) must reach 2 days. Lead times:
#     bugfix and code-quality 2 days; everything else 7 days; any change to the
#     hacs.json floor or manifest requirements 7 days.
#   - Base: the newest pre-release (its recorded dev and main) whose every
#     teslemetry dev commit since latest's own dev base has soaked; else
#     latest's own base. On it, every soaked change the base lacks, core then
#     fork, each ascending, at its current head; a change already in latest
#     that has not soaked again stays at latest's head. A change whose diff
#     cannot apply at all (it needs a younger change) waits, named in the
#     notes; a conflict rerere cannot replay stops the run as in a pre-release.
#   - When: weekly (7 days since latest) takes every soaked change. On other
#     days a soaked bugfix missing from latest builds latest's own change set
#     plus the soaked bugfixes. An open issue labelled blocks-latest that links
#     a culprit PR keeps that PR out. Nothing is built when the set equals
#     latest's.
#   - A floor or requirements difference from latest holds latest for the
#     captain's word: rerun with --approve-requirements <digest the run
#     printed>. --waive <#N|fork#N> is the captain's urgent waiver of one PR's
#     lead time; the run builds latest with it, then the pre-release.
#   - On a latest run neither change-detection skip applies. Latest is tagged
#     first and the pre-release a second later; the pre-release is published
#     first and latest last. Any gate failure publishes neither. A held latest
#     exits 4 after the pre-release step.
#
# Latest tag annotation:
#   Release <version>
#   <blank line>
#   release-kind: latest
#   dev: <dev commit SHA of the base>
#   main: <fork main commit SHA of the base>
#   pr: <owner/repo> <number> <head SHA>       (one line per applied PR)
#
# Daily pre-release tag annotation (the durable record of each build; a later
# latest build dates every change from these, so keep the format stable):
#   Pre-release <version>
#   <blank line>
#   release-kind: prerelease
#   fingerprint: <sha256 hex of the fingerprint input below>
#   dev: <upstream/dev commit SHA whose integration the build took>
#   main: <fork main commit SHA after the dev sync>
#   pr: <owner/repo> <number> <head SHA>       (one line per composed PR, in
#                                               apply order)
# The fingerprint input is these lines, newline-terminated, PR lines sorted:
#   dev-tree <tree hash of homeassistant/components/teslemetry at upstream/dev>
#   main-tree <tree hash of the same path on fork main after the dev sync>
#   pr <owner/repo> <number> <head SHA>

set -euo pipefail

# --- fork remotes / repo -----------------------------------------------------
FORK_REPO="Teslemetry/hass-teslemetry"      # origin: the HACS fork we release
CORE_REPO="home-assistant/core"             # upstream: core, source of PRs/dev
STAGING_REPO="Teslemetry/home-assistant"    # staging fork: PRs awaiting review, layered on top
PR_LIST_LIMIT=200                           # gh pr list page size; filling it dies (see list_open_prs)
INTEGRATION="homeassistant/components/teslemetry"
INIT_PY="$INTEGRATION/__init__.py"
MIGRATION_TEST="tests/components/teslemetry/test_migration.py"
ISSUE_TRACKER="https://github.com/$FORK_REPO/issues"  # manifest.json issue_tracker (issue_tracker_gate)
CORE_BASE_SUBJECT="HACS core base:"  # subject prefix of main's base commit (see sync_dev)
LEAD_SHORT=2                    # days: bugfix, code-quality, and every PR's current head
LEAD_LONG=7                     # days: every other type, and floor/requirements changes
BLOCKS_LATEST_LABEL="blocks-latest"
# Tracked patches that reconcile two composed PRs (see apply_fixups).
RELEASE_FIXUPS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/release-fixups"

# Core CI/CD workflows this fork deliberately excludes. The core-dev sync would
# otherwise resurrect them; stripped every cut. Keep in sync with the identical
# list in AGENTS.md ("CI: the clean per-integration gate").
CORE_CI_PATHS=(
  .github/workflows/ci.yaml
  .github/workflows/validate.yml
  .github/workflows/check-requirements-deterministic.yml
  .github/workflows/check-requirements.lock.yml
  .github/workflows/check-requirements.md
  .github/workflows/codeql.yml
  .github/workflows/translations.yml
  .github/workflows/builder.yml
  .github/workflows/wheels.yml
  .github/workflows/e2e-tests.yml
  .github/workflows/quality-scale-reviewer-trigger.yml
  .github/workflows/quality-scale-reviewer.md
  .github/workflows/quality-scale-reviewer.lock.yml
  .github/workflows/matchers
)

# --- output helpers ----------------------------------------------------------
log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

# Exit status of a daily run that needs a human (see pause).
HEADLESS_STOP_EXIT=3
# Exit status of a daily run whose latest waits for the captain (see finish).
LATEST_HELD_EXIT=4

# Human checkpoint. Blocks until the operator confirms they have handled what
# the message describes. Reads from the terminal even inside a pipeline. A daily
# run has no operator, so it stops instead and leaves the work for a human.
pause() {
  if [ "${DAILY:-0}" = 1 ]; then
    printf '\n\033[1;31mHEADLESS STOP (needs a human, nothing published): %s\033[0m\n' "$*" >&2
    exit "$HEADLESS_STOP_EXIT"
  fi
  printf '\n\033[1;33m>>> %s\033[0m\n' "$*"
  read -r -p "    Press Enter to continue, or Ctrl-C to abort: " _ < /dev/tty
}

# --- gate helpers ------------------------------------------------------------

# Print the line number of the first line inside top-level block $1 (a line
# matching that regex, up to the next top-level statement) of file $3 whose code
# contains text $2, or 0. A match in a comment passes on a commented-out call,
# so comments are stripped first.
block_line() {
  awk -v start="$1" -v text="$2" '
    $0 ~ start                      { inside=1; next }
    inside && /^[^[:space:]#)]/     { inside=0 }
    { code=$0; sub(/#.*/, "", code) }
    inside && !line && index(code, text) { line=NR }
    END { print line+0 }
  ' "$3"
}

# Print the line number of the first line inside async_setup_entry of file $2
# whose code contains text $1, or 0. A grep for a name alone passes on a
# defined-but-never-called function.
setup_entry_line() { block_line '^async def async_setup_entry\(' "$1" "$2"; }

# Fail if any tracked file carries a leftover conflict marker. Optional
# pathspecs narrow the search. Enforced after every commit that could have
# merged or applied a patch. git grep searches tracked files only, which is
# exactly what we want post-commit.
assert_no_conflict_markers() {
  if git grep -nE '^(<{7}|>{7})( |$)' -- "$@" 2>/dev/null; then
    die "conflict markers found (above) - resolve before continuing"
  fi
  info "no conflict markers"
}

# Complete an in-progress merge/apply only once the tree is fully resolved.
assert_no_unmerged() {
  if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    git diff --name-only --diff-filter=U | sed 's/^/    unmerged: /'
    die "unmerged paths remain - 'git add' every resolved file, then rerun this step"
  fi
}

# Point git rerere at the persistent cache named by RELEASE_RERERE_CACHE, so a
# resolution recorded in one cut replays in the next. Unset: rerere stays as
# the repo and user config leave it, as before. git has no setting for the
# rr-cache location, so the repo's rr-cache becomes a symlink to the cache. The
# config is passed through the environment, never written to the shared repo.
setup_rerere() {
  RERERE=0
  [ -n "${RELEASE_RERERE_CACHE:-}" ] || { info "rerere: off (RELEASE_RERERE_CACHE unset)"; return 0; }
  mkdir -p "$RELEASE_RERERE_CACHE" || die "cannot create RELEASE_RERERE_CACHE: $RELEASE_RERERE_CACHE"
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

# After a failed merge, rebase or `git apply -3`, return 0 only if rerere replayed a
# recorded resolution for every conflicted path, and stage those paths. Each
# command runs rerere itself. Not rerere.autoUpdate: inside `git apply -3`
# it fails on apply's own index lock. A failure that left no unmerged path
# (a patch that did not apply at all) and any path rerere cannot resolve
# (modify/delete, or a conflict it has not seen) return 1, so the caller stops.
rerere_resolved() {
  [ "$RERERE" = 1 ] || return 1
  local unmerged
  unmerged=$(git diff --name-only --diff-filter=U)
  [ -n "$unmerged" ] || return 1
  [ -z "$(git rerere remaining)" ] || return 1
  git diff -z --name-only --diff-filter=U | xargs -0 git add --
  local path
  while IFS= read -r path; do info "rerere replayed: $path"; done <<<"$unmerged"
}

# --- pinned core base ----------------------------------------------------------
# A build's core is the core release tag named by hacs.json's "homeassistant"
# floor, never core dev: the floor is what the build claims to support, so it is
# what the integration is tested against. Only the integration and its tests
# come from core dev. hacs.json is the one place the pin lives; AGENTS.md has
# the monthly bump. Any core API the integration needs that the pinned release
# lacks is bridged inside the integration.

# Core-owned paths a build takes from the pinned tag. The integration, its
# tests and homeassistant/generated are excluded (see restore_core_base), and
# requirements_all.txt then takes the integration's own pins (see
# pin_integration_requirements). The generated files are data made from the
# manifests, not core API: core reads them for a built-in integration (here,
# teslemetry's Labs preview features in generated/labs.py), where a HACS
# install reads its own manifest instead.
CORE_BASE_PATHS=(homeassistant tests script pyproject.toml requirements.txt
  requirements_all.txt requirements_test.txt requirements_test_pre_commit.txt
  .python-version)

# Print the pinned core tag: the hacs.json floor at commit $1, or in the work
# tree when $1 is empty. It must be a full core version, the name of its tag.
core_base_tag() {
  local floor
  if [ -n "${1:-}" ]; then
    floor=$(git show "$1:hacs.json" | jq -r '.homeassistant // ""')
  else
    floor=$(jq -r '.homeassistant // ""' hacs.json)
  fi
  [[ "$floor" =~ ^[0-9]{4}\.[0-9]+\.[0-9]+(b[0-9]+)?$ ]] \
    || die "hacs.json homeassistant floor '$floor' is not a full core version (e.g. 2026.10.0): it names the pinned core base tag"
  printf '%s\n' "$floor"
}

# Fetch core tag $1 into refs/tags/$1 from the upstream remote, or from core on
# GitHub where there is none (CI). A shallow clone (CI) fetches only the tag's
# commit; a full clone is never made shallow. Returns 1 if it cannot.
fetch_core_tag() {
  local src depth=()
  src=$(git remote get-url upstream 2>/dev/null || echo "https://github.com/$CORE_REPO")
  if [ "$(git rev-parse --is-shallow-repository)" = true ]; then depth=(--depth=1); fi
  git fetch --quiet --no-tags ${depth[@]+"${depth[@]}"} "$src" "+refs/tags/$1:refs/tags/$1"
}

# Return 0 when commit $1 sits on the core tag its own hacs.json floor names. A
# main from before the pinned base sits on core dev, which no release tag is in.
on_core_base() {
  local tag
  tag=$(git show "$1:hacs.json" 2>/dev/null | jq -r '.homeassistant // ""') || return 1
  [ -n "$tag" ] || return 1
  git rev-parse -q --verify "refs/tags/$tag^{commit}" >/dev/null || fetch_core_tag "$tag" 2>/dev/null || return 1
  git merge-base --is-ancestor "refs/tags/$tag^{commit}" "$1"
}

# Put every CORE_BASE_PATHS path outside the integration and its tests in the
# work tree at the pinned core tag, so tests and tooling run against exactly the
# core release the build claims to support, whatever a composed PR changed
# outside the integration. Work tree only: the index and commits keep the
# composed state. The build gate and the CI workflow both run it first.
restore_core_base() {
  local tag
  tag=$(core_base_tag)
  log "Core at the pinned base $tag"
  fetch_core_tag "$tag" || die "could not fetch core tag $tag - the hacs.json floor must be a released core version"
  git restore --source="refs/tags/$tag^{commit}" --worktree -- "${CORE_BASE_PATHS[@]}" \
    ":(exclude)$INTEGRATION" ":(exclude)tests/components/teslemetry" ":(exclude)homeassistant/generated"
  pin_integration_requirements
  info "core paths outside the integration match core $tag; requirements_all.txt has the integration's pins"
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

# Print main $1's base commit: the newest commit on its first-parent line whose
# subject starts with CORE_BASE_SUBJECT. A main from before the pinned base has
# none; its base is where it meets upstream/dev.
main_base_commit() {
  local base
  base=$(git log --first-parent --format='%H%x09%s' --grep="^$CORE_BASE_SUBJECT" "$1" \
           | awk -F'\t' -v p="$CORE_BASE_SUBJECT" '!found && index($2, p) == 1 { print $1; found = 1 }')
  [ -n "$base" ] || base=$(git merge-base "$1" upstream/dev) || die "cannot find the base of $1"
  printf '%s\n' "$base"
}

# Print the commit sync_dev rebases main $1's fork commits from: no commit it
# reaches is a fork commit. Those are every base commit main reaches (a merged
# branch started before a sync can bring an older one) and where main meets
# upstream/dev (a main, or a merged branch, from before the pinned base sits on
# dev). Several are joined by a merge commit that is never pushed.
rebase_upstream() {
  local parents=() p args=() mb
  mapfile -t parents < <(git log --format='%H%x09%s' --grep="^$CORE_BASE_SUBJECT" "$1" \
                           | awk -F'\t' -v p="$CORE_BASE_SUBJECT" 'index($2, p) == 1 { print $1 }')
  mb=$(git merge-base "$1" upstream/dev) || die "cannot find where $1 meets upstream/dev"
  parents+=("$mb")
  if [ "${#parents[@]}" -eq 1 ]; then
    printf '%s\n' "${parents[0]}"
    return 0
  fi
  for p in "${parents[@]}"; do args+=(-p "$p"); done
  git commit-tree "$(git rev-parse "$1^{tree}")" "${args[@]}" -m "Bases of $1 (rebase upstream, never pushed)"
}

# Print the base commit for core tag $1 with the integration and its tests
# from commit $2: the tag's tree with those two paths replaced, its parent the
# tag. Prints $3 (main's current base) instead when it is exactly that already,
# so a sync with nothing new leaves main unchanged.
make_base_commit() {
  local tag="$1" src="$2" old="$3" tag_commit dir tree
  tag_commit=$(git rev-parse "refs/tags/$tag^{commit}")
  dir=$(mktemp -d)
  GIT_INDEX_FILE="$dir/index" git read-tree "$tag_commit"
  GIT_INDEX_FILE="$dir/index" git rm -r -q -f --cached --ignore-unmatch -- "$INTEGRATION" tests/components/teslemetry
  GIT_INDEX_FILE="$dir/index" git read-tree --prefix="$INTEGRATION/" "$src:$INTEGRATION"
  GIT_INDEX_FILE="$dir/index" git read-tree --prefix=tests/components/teslemetry/ "$src:tests/components/teslemetry"
  tree=$(GIT_INDEX_FILE="$dir/index" git write-tree)
  rm -rf "$dir"
  if [ "$(git rev-parse "$old^{tree}")" = "$tree" ] && [ "$(git rev-parse -q --verify "$old^1" || true)" = "$tag_commit" ]; then
    printf '%s\n' "$old"
    return 0
  fi
  git commit-tree "$tree" -p "$tag_commit" \
    -m "$CORE_BASE_SUBJECT core $tag with teslemetry from dev $(git rev-parse --short=10 "$src")"
}

# --- steps -------------------------------------------------------------------

parse_args() {
  BUMP=""
  PUBLISH=0
  DAILY=0
  LINE=""   # optional <major.minor> series selector; empty = derive from tags
  WAIVE=""  # daily: the one PR whose lead time the captain waived
  WAIVE_REF=""
  APPROVE_REQUIREMENTS=""
  LOWER_FLOOR=""  # the composed hacs.json floor a deliberate lowering names (hacs_floor_gate)
  LATEST_BUILT=0
  LATEST_HELD=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      major|minor|patch) BUMP="$1" ;;
      daily)             DAILY=1 ;;
      --publish)         PUBLISH=1 ;;
      --line)            shift; [ "$#" -gt 0 ] || die "--line requires a <major.minor> value"; LINE="$1" ;;
      --line=*)          LINE="${1#--line=}" ;;
      --waive)           shift; [ "$#" -gt 0 ] || die "--waive requires a PR (#N or fork#N)"; WAIVE="$1" ;;
      --approve-requirements)
                         shift; [ "$#" -gt 0 ] || die "--approve-requirements requires the digest a run printed"; APPROVE_REQUIREMENTS="$1" ;;
      --lower-floor)     shift; [ "$#" -gt 0 ] || die "--lower-floor requires the new hacs.json floor"; LOWER_FLOOR="$1" ;;
      *) die "unknown argument: $1 (usage: ./release.sh <major|minor|patch> [--line <major.minor>] [--lower-floor <version>] [--publish] | daily [--waive <#N|fork#N>] [--approve-requirements <digest>] [--lower-floor <version>] [--publish])" ;;
    esac
    shift
  done
  if [ "$DAILY" = 1 ]; then
    [ -z "$BUMP" ] && [ -z "$LINE" ] || die "daily takes no bump and no --line: its version is the UTC date"
    if [ -n "$WAIVE" ]; then
      [[ "$WAIVE" =~ ^(fork#|#)?([0-9]+)$ ]] || die "--waive takes #N (core) or fork#N, got: $WAIVE"
      if [ "${BASH_REMATCH[1]}" = "fork#" ]; then WAIVE_REF="$STAGING_REPO#${BASH_REMATCH[2]}"; else WAIVE_REF="$CORE_REPO#${BASH_REMATCH[2]}"; fi
    fi
    return 0
  fi
  [ -z "$WAIVE" ] && [ -z "$APPROVE_REQUIREMENTS" ] || die "--waive and --approve-requirements apply to daily only"
  [ -n "$BUMP" ] || die "specify one of: major | minor | patch | daily"
  if [ -n "$LINE" ]; then
    [[ "$LINE" =~ ^[0-9]+\.[0-9]+$ ]] || die "--line must be <major.minor> (e.g. 6.0), got: $LINE"
  fi
}

preflight() {
  log "Preflight"
  # Never operate from a main checkout: checking out / committing on main in a
  # shared clone dirties it. This pipeline only ever touches temp branches.
  local branch
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  [ "$branch" = "main" ] && die "on 'main' - run this from an isolated worktree/branch, never a main checkout"

  [ -z "$(git status --porcelain)" ] || die "working tree is dirty - start from a clean checkout"

  git remote get-url origin   >/dev/null 2>&1 || die "no 'origin' remote (expected $FORK_REPO)"
  git remote get-url upstream >/dev/null 2>&1 || die "no 'upstream' remote (expected $CORE_REPO)"

  for tool in gh yq jq git curl uv; do
    command -v "$tool" >/dev/null 2>&1 || die "required tool not found: $tool"
  done
  if [ "$PUBLISH" = 1 ]; then
    command -v zip >/dev/null 2>&1 || die "'zip' required for --publish"
    # A preview resolution has no place in a real cut. It cannot change the
    # gate's verdict anyway (see preview_core_ref); this keeps it out entirely.
    [ -z "${CORE_CONSTRAINTS_PREVIEW_REF:-}" ] || die "CORE_CONSTRAINTS_PREVIEW_REF is set - unset it; a preview cannot be part of a --publish cut"
  fi
  info "branch=$branch publish=$PUBLISH daily=$DAILY"
}

# Every v* tag a bump cut computes from: all of them except the daily
# v<UTC Y.M.D> pre-releases, whose four-digit-year major sorts above every 6.x
# tag and would make a bare `patch` compute the next date instead of the next
# 6.x number.
line_tags() {
  git tag -l 'v*' | grep -Ev '^v[0-9]{4}\.' || true
}

# Memory-independent guard for the no-line path. With --line omitted we bump off
# the overall newest tag, which is safe only while the newest line is
# unambiguous. It stops being unambiguous the moment a newer line opens above a
# still-tagged one: a v6.1.0-beta preview while v6.0.x is still maintained makes
# sort -V pick the 6.1 tag, so a bare `patch` meant for 6.0.x silently computes
# 6.1.x. This derives the ambiguity purely from the tag list - no memory, no
# clock - and dies demanding --line in exactly that shape. A cross-major stable
# transition with a still-live lower major is undecidable from tags alone and is
# not covered; see AGENTS.md ("How the release line is selected").
require_unambiguous_line() {
  local tip tip_ver tip_major minor_count
  tip=$(line_tags | sort -V | tail -1)
  [ -n "$tip" ] || return 0   # no tags at all: the absent-tag die handles it
  tip_ver=${tip#v}
  tip_major=${tip_ver%%.*}

  # (a) A pre-release tip means a preview line is open above the stable line, so
  # which line to cut is genuinely ambiguous.
  case "$tip_ver" in
    *-*) die "newest tag $tip is a pre-release - a preview line is open. Pass --line <major.minor> to name the line you are cutting (e.g. --line ${tip_major}.0 to keep maintaining the stable line)." ;;
  esac

  # (b) More than one minor line under the current major means the newest line is
  # ambiguous within the major you are almost certainly working in.
  minor_count=$(line_tags \
    | sed -n 's/^v\([0-9][0-9]*\)\.\([0-9][0-9]*\)\..*/\1 \2/p' \
    | awk -v M="$tip_major" '$1==M {print $2}' \
    | sort -u | wc -l | tr -d '[:space:]')
  if [ "$minor_count" -gt 1 ]; then
    die "more than one ${tip_major}.x minor line exists in tags - the newest line is ambiguous. Pass --line <major.minor> to name the line you are cutting (e.g. --line ${tip_major}.0)."
  fi
}

# Step 1: determine and bump the version off the latest release tag.
# Tags, not the GitHub release list, are the durable record of which version
# numbers have been used: a release object can be deleted while its tag is kept,
# as when a bad build is yanked. Keying off releases would then recompute the
# yanked number and collide with the retained tag at publish. Reading tags also
# matches aiopowerwall_pin_gate, so the version driver and pin floor agree.
# Release tags point at release branches, not main, so main's fetches never
# bring them down - fetch tags first, or a stale local list recomputes a taken
# version and reopens this very bug. Fail loud rather than read a stale list.
determine_version() {
  log "Step 1: determine version"
  local last major minor patch
  git fetch --tags origin || die "could not fetch tags from origin - refusing to compute a version off a stale local tag list"

  if [ -n "$LINE" ]; then
    # Explicit line: bump off the highest tag in exactly this major.minor series,
    # so a 6.1 preview tag can never pull a 6.0.x maintenance cut onto the 6.1
    # line. `|| true` lets the empty-series die below fire instead of set -e.
    local lmaj lmin
    IFS='.' read -r lmaj lmin <<<"$LINE"
    last=$(line_tags | grep -E "^v${lmaj}\.${lmin}\." | sort -V | tail -1 || true)
    [ -n "$last" ] || die "no 'v${LINE}.*' release tags found - cannot bump the $LINE line off an empty series"
    info "line $LINE selected; latest tag in series: $last"
  else
    # No line given: keep the historical behaviour (bump off the overall latest
    # tag) - but only after asserting the newest line is unambiguous, so a
    # forgotten --line cannot silently hijack a maintenance line.
    require_unambiguous_line
    last=$(line_tags | sort -V | tail -1)
    [ -n "$last" ] || die "could not read latest release tag from git (no 'v*' tags found)"
    info "latest release tag: $last"
  fi

  IFS='.' read -r major minor patch <<<"${last#v}"
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ && "$patch" =~ ^[0-9]+$ ]] \
    || die "cannot parse semver from '$last'"

  case "$BUMP" in
    major) major=$((major + 1)); minor=0; patch=0 ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    patch) patch=$((patch + 1)) ;;
  esac
  VERSION="$major.$minor.$patch"
  info "new version: $VERSION ($BUMP bump)"
}

# --- daily mode ----------------------------------------------------------------

# Print the first free daily version for a UTC date given as Y.M.D with no
# zero-padding: the date itself, then date.1, date.2, ... Reads local tags, so
# fetch tags first. AwesomeVersion orders 2026.10.5 < 2026.10.5.1 < 2026.10.6
# and every one of them above 6.x; a bN suffix would not order (see AGENTS.md).
# $2, when given, is a version this run already claimed but has not tagged yet.
daily_version() {
  local base="$1" taken="${2:-}" v="$1" n=0
  while git rev-parse -q --verify "refs/tags/v$v" >/dev/null || [ "$v" = "$taken" ]; do
    n=$((n + 1))
    v="$base.$n"
  done
  printf '%s\n' "$v"
}

# Step 1 (daily): the version from today's UTC date.
determine_daily_version() {
  log "Step 1: determine daily version"
  git fetch --tags origin || die "could not fetch tags from origin - refusing to compute a version off a stale local tag list"
  VERSION=$(daily_version "$(date -u +%Y.%-m.%-d)")
  info "new version: $VERSION (daily pre-release)"
}

# Print the newest daily pre-release tag (by version), or nothing. Only tags
# whose annotation says "release-kind: prerelease" count, so a later latest
# build's date tags never become the change-detection baseline.
last_prerelease_tag() {
  local tag
  for tag in $(git tag -l 'v[0-9][0-9][0-9][0-9].*' | sort -rV); do
    if git tag -l --format='%(contents)' "$tag" | grep -qx 'release-kind: prerelease'; then
      printf '%s\n' "$tag"
      return 0
    fi
  done
}

# Print one field ("fingerprint", "dev", ...) of a daily tag's annotation.
tag_field() {
  tag_lines "$1" "$2" | head -1
}

# Print every value of a repeated annotation field ("pr"), one per line.
tag_lines() {
  git tag -l --format='%(contents)' "$1" | sed -n "s/^$2: //p"
}

# End a daily run that reached no failure. A latest held for the captain's word
# exits LATEST_HELD_EXIT, so the timer sees it even when the pre-release step
# published or found nothing to publish.
finish() {
  if [ -n "$LATEST_HELD" ]; then
    printf '\n\033[1;31mLATEST HELD (needs the captain, latest not published): %s\033[0m\n' "$LATEST_HELD" >&2
    exit "$LATEST_HELD_EXIT"
  fi
  exit 0
}

# Print the fingerprint of a compose's inputs. $1 dev tree hash, $2 main tree
# hash; PR lines "<owner/repo> <number> <head SHA>" on stdin. The input format
# is documented in the header; changing it rebuilds once on the next run.
input_fingerprint() {
  {
    printf 'dev-tree %s\nmain-tree %s\n' "$1" "$2"
    sed '/^$/d; s/^/pr /' | LC_ALL=C sort
  } | sha256sum | cut -d' ' -f1
}

# The compose set as "<owner/repo> <number> <head SHA>" lines, in apply order.
compose_set_lines() {
  local num title draft sha
  while IFS=$'\t' read -r num title draft sha; do
    [ -n "$num" ] && printf '%s %s %s\n' "$CORE_REPO" "$num" "$sha"
  done <<<"$CORE_PRS"
  while IFS=$'\t' read -r num title draft sha _; do
    [ -n "$num" ] && printf '%s %s %s\n' "$STAGING_REPO" "$num" "$sha"
  done <<<"$FORK_PRS"
  return 0
}

# Change detection, step 1 (before composing): exit 0 when today's inputs equal
# the ones the last pre-release recorded. The main tree here is fork main before
# today's sync; the recorded one is main after the last build's sync, which is
# what main holds the next day when nothing changed.
skip_if_inputs_unchanged() {
  log "Change detection: compose inputs"
  git fetch origin main
  git fetch upstream dev
  collect_prs
  BASE_TAG=$(last_prerelease_tag)
  if [ -z "$BASE_TAG" ]; then info "no daily pre-release tag yet; building"; return 0; fi
  local fp recorded
  fp=$(compose_set_lines | input_fingerprint \
         "$(git rev-parse "upstream/dev:$INTEGRATION")" "$(git rev-parse "origin/main:$INTEGRATION")")
  recorded=$(tag_field "$BASE_TAG" fingerprint)
  if [ "$fp" = "$recorded" ]; then
    log "Nothing changed since $BASE_TAG (input fingerprint $fp) - nothing published"
    finish
  fi
  info "inputs changed since $BASE_TAG; building"
}

# Change detection, step 2 (after composing): exit 0 when the composed
# integration, which is all the release zip ships, equals the last pre-release's
# with the manifest version ignored. Runs before the gates, whose verdict cannot
# change a skip.
skip_if_integration_unchanged() {
  log "Change detection: composed integration"
  [ -n "$BASE_TAG" ] || { info "no daily pre-release tag yet; building"; return 0; }
  local manifest="$INTEGRATION/manifest.json"
  if git diff --quiet "$BASE_TAG" HEAD -- "$INTEGRATION" ":(exclude)$manifest" \
     && cmp -s <(git show "$BASE_TAG:$manifest" | jq -S 'del(.version)') <(jq -S 'del(.version)' "$manifest"); then
    log "Composed integration is identical to $BASE_TAG - nothing published"
    finish
  fi
  info "composed integration differs from $BASE_TAG; building"
}

# The daily tag annotation (format in the header). Run after the dev sync: the
# dev and main values must be what this build composed.
daily_tag_message() {
  local dev_sha main_sha fp
  dev_sha=$(git rev-parse upstream/dev)
  main_sha=$(git rev-parse sync-dev)
  fp=$(compose_set_lines | input_fingerprint \
         "$(git rev-parse "$dev_sha:$INTEGRATION")" "$(git rev-parse "$main_sha:$INTEGRATION")")
  printf 'Pre-release %s\n\nrelease-kind: prerelease\nfingerprint: %s\ndev: %s\nmain: %s\n' \
    "$VERSION" "$fp" "$dev_sha" "$main_sha"
  compose_set_lines | sed 's/^/pr: /'
}

# Print how many published releases GitHub lists above the current latest
# release, from the release list JSON (newest first) on stdin. $1 is latest's
# tag; a latest missing from the list counts the whole list.
count_newer_than_latest() {
  jq --arg t "$1" '[.[] | select(.draft | not) | .tag_name] | (index($t) // length)'
}

# HACS and Home Assistant read only the 30 newest releases. If latest falls out
# of that window, users are no longer offered it, so refuse at 25 newer.
release_window_guard() {
  log "Gate: latest release stays inside the 30-release window"
  local latest newer
  latest=$(gh api "repos/$FORK_REPO/releases/latest" --jq '.tag_name') \
    || die "could not read the latest release on $FORK_REPO"
  newer=$(gh api "repos/$FORK_REPO/releases?per_page=100" | count_newer_than_latest "$latest") \
    || die "could not list releases on $FORK_REPO"
  [ "$newer" -lt 25 ] \
    || die "$newer releases are newer than latest $latest - one more pre-release pushes latest toward the 30-release window HACS reads. Publish a new latest first."
  info "$newer releases newer than latest $latest"
}

# --- latest (rules in the header) ----------------------------------------------

declare -A PR_INFO=()
declare -A APPLIED_HEADS=()  # applied PR ref ("#N", "fork#N") -> head, for needs= (see compose_prs)

today_day() { echo $(( $(date -u +%s) / 86400 )); }

# Every daily pre-release, oldest first, as "<UTC day> <tag> dev <SHA>" and
# "<UTC day> <tag> pr <owner/repo> <number> <head SHA>" lines. A UTC day is
# whole days since the epoch. Only these annotations date a change.
prerelease_index() {
  local tag unix day
  git for-each-ref --sort=taggerdate --format='%(refname:short) %(taggerdate:unix)' \
      'refs/tags/v[0-9][0-9][0-9][0-9].*' \
    | while read -r tag unix; do
        git tag -l --format='%(contents)' "$tag" | grep -qx 'release-kind: prerelease' || continue
        day=$((unix / 86400))
        printf '%s %s dev %s\n' "$day" "$tag" "$(tag_field "$tag" dev)"
        tag_lines "$tag" pr | sed "s/^/$day $tag pr /"
      done
}

# First UTC day a pre-release contained PR $2 of repo $1 (at head $3 if given).
first_day_pr() {
  awk -v r="$1" -v n="$2" -v s="${3:-}" \
    '$3 == "pr" && $4 == r && $5 == n && (s == "" || $6 == s) { print $1; exit }' <<<"$PRE_INDEX"
}

# First UTC day a pre-release's dev contained commit $1.
first_day_commit() {
  local day tag kind sha
  while read -r day tag kind sha; do
    [ "$kind" = dev ] || continue
    if git merge-base --is-ancestor "$1" "$sha" 2>/dev/null; then echo "$day"; return 0; fi
  done <<<"$PRE_INDEX"
}

# The earlier of two UTC days, either of which may be empty.
min_day() {
  if [ -z "$1" ]; then echo "$2"; elif [ -z "$2" ] || [ "$1" -le "$2" ]; then echo "$1"; else echo "$2"; fi
}

# The hacs.json floor and the sorted manifest requirements at commit $1.
requirements_text() {
  git show "$1:hacs.json" 2>/dev/null | jq -r '.homeassistant // ""' || true
  git show "$1:$INTEGRATION/manifest.json" 2>/dev/null | jq -r '(.requirements // []) | sort[]' || true
}

requirements_differ() { [ "$(requirements_text "$1")" != "$(requirements_text "$2")" ]; }

# Cache PR $2 of repo $1 (title, draft, head, labels, body) in PR_INFO. Not in
# a command substitution, so the cache survives.
load_pr_info() {
  [ -z "${PR_INFO[$1#$2]:-}" ] || return 0
  PR_INFO[$1#$2]=$(gh api "repos/$1/pulls/$2" \
    --jq '{title, draft, head: .head.sha, labels: [.labels[].name], body: (.body // "")}') \
    || die "could not read $1 pull $2"
}

# The type of a cached PR: a core PR's one type label, or a fork PR's one
# checked "Type of change" box (the core PR template). Missing or ambiguous is
# new-feature.
pr_type() {
  local info="${PR_INFO[$1#$2]}"
  if [ "$1" = "$STAGING_REPO" ]; then
    jq -r .body <<<"$info" | tr -d '\r' | awk '
      /^#+[[:space:]]*Type of change/ { s = 1; next }
      s && /^#+[[:space:]]/ { s = 0 }
      s && /^[[:space:]]*[-*][[:space:]]+\[[xX]\]/ {
        t = "new-feature"
        if ($0 ~ /\][[:space:]]*Dependency upgrade/) t = "dependency"
        else if ($0 ~ /\][[:space:]]*Bugfix/) t = "bugfix"
        else if ($0 ~ /\][[:space:]]*Deprecation/) t = "deprecation"
        else if ($0 ~ /\][[:space:]]*Breaking change/) t = "breaking-change"
        else if ($0 ~ /\][[:space:]]*Code quality/) t = "code-quality"
        seen[t] = 1
      }
      END { n = 0; for (k in seen) { n++; one = k }; print (n == 1 ? one : "new-feature") }'
  else
    jq -r '[.labels[] | select(IN("bugfix", "code-quality", "new-feature", "dependency", "breaking-change", "deprecation"))]
           | unique | if length == 1 then .[0] else "new-feature" end' <<<"$info"
  fi
}

# Print "soaked" or why not; return 0 only when soaked. $1 type, $2 first day
# the change shipped, $3 first day its current head shipped, $4 1 when it
# changes the floor or requirements, $5 1 when the captain waived it.
soak_verdict() {
  local lead=$LEAD_LONG today
  if [ "$5" = 1 ]; then echo "soaked (lead time waived by the captain)"; return 0; fi
  case "$1" in bugfix|code-quality) lead=$LEAD_SHORT ;; esac
  [ "$4" != 1 ] || lead=$LEAD_LONG
  today=$(today_day)
  [ -n "$2" ] || { echo "never shipped in a pre-release"; return 1; }
  [ $((today - $2)) -ge "$lead" ] || { echo "change age $((today - $2))d < ${lead}d"; return 1; }
  [ -n "$3" ] || { echo "current head never shipped in a pre-release"; return 1; }
  [ $((today - $3)) -ge "$LEAD_SHORT" ] || { echo "head age $((today - $3))d < ${LEAD_SHORT}d"; return 1; }
  echo soaked
}

# Judge one change: PR $2 of repo $1 (empty for a dev commit with no PR) at
# head $3 (empty: the PR's head now), $4 the base the PR branched from, $5 its
# dev commit when merged. Sets JUDGED_TYPE, JUDGED_HEAD, JUDGED_FIX (bugfix or
# waived), JUDGED_BLOCKED, VERDICT and VERDICT_OK (1 = soaked).
judge_change() {
  local repo="$1" num="$2" head="$3" base="$4" commit="$5" cday="" hday="" reqs=0 waived=0 d
  JUDGED_TYPE=new-feature JUDGED_HEAD="" JUDGED_FIX=0 JUDGED_BLOCKED=0
  if [ -n "$num" ]; then
    load_pr_info "$repo" "$num"
    JUDGED_TYPE=$(pr_type "$repo" "$num")
    [ -n "$head" ] || head=$(jq -r .head <<<"${PR_INFO[$repo#$num]}")
    JUDGED_HEAD=$head
    cday=$(first_day_pr "$repo" "$num")
    hday=$(first_day_pr "$repo" "$num" "$head")
    [ "$WAIVE_REF" != "$repo#$num" ] || waived=1
    if grep -qxF "$repo#$num" <<<"$BLOCKED"; then JUDGED_BLOCKED=1; fi
  fi
  if [ -n "$commit" ]; then
    d=$(first_day_commit "$commit")
    cday=$(min_day "$cday" "$d")
    hday=$(min_day "$hday" "$d")
    if requirements_differ "$commit^" "$commit"; then reqs=1; fi
  else
    git cat-file -e "$head^{commit}" 2>/dev/null || fetch_ref "$repo" "pull/$num/head" >/dev/null
    git cat-file -e "$head^{commit}" 2>/dev/null || fetch_ref "$repo" "$head" >/dev/null
    if requirements_differ "$(git merge-base "$base" "$head")" "$head"; then reqs=1; fi
  fi
  if [ "$JUDGED_TYPE" = bugfix ] || [ "$waived" = 1 ]; then JUDGED_FIX=1; fi
  if [ "$JUDGED_BLOCKED" = 1 ]; then
    VERDICT="kept out by an open $BLOCKS_LATEST_LABEL issue" VERDICT_OK=0
  elif VERDICT=$(soak_verdict "$JUDGED_TYPE" "$cday" "$hday" "$reqs" "$waived"); then
    VERDICT_OK=1
  else
    VERDICT_OK=0
  fi
  [ "$reqs" = 0 ] || VERDICT+=" (changes the floor or requirements)"
}

# Culprit PRs of open blocks-latest issues on the fork, as "<owner/repo>#<N>"
# lines in BLOCKED, from the PR URLs each issue links. An issue that links none
# holds latest: the run cannot tell what to keep out.
load_blocked() {
  local issues unnamed
  issues=$(gh issue list --repo "$FORK_REPO" --label "$BLOCKS_LATEST_LABEL" --state open \
             --limit "$PR_LIST_LIMIT" --json number,title,body) \
    || die "could not list $BLOCKS_LATEST_LABEL issues on $FORK_REPO"
  local culprits='[(.title + "\n" + (.body // ""))
    | scan("https://github\\.com/(home-assistant/core|Teslemetry/home-assistant)/pull/([0-9]+)")
    | "\(.[0])#\(.[1])"]'
  BLOCKED=$(jq -r ".[] | $culprits | .[]" <<<"$issues")
  unnamed=$(jq -r ".[] | select($culprits | length == 0) | \"#\(.number)\"" <<<"$issues" | paste -sd' ' -)
  if [ -n "$unnamed" ]; then
    LATEST_HELD="$BLOCKS_LATEST_LABEL issue(s) $unnamed on $FORK_REPO link no culprit PR URL - link it, or close the issue"
    return 1
  fi
  [ -z "$BLOCKED" ] || info "kept out by $BLOCKS_LATEST_LABEL: $(paste -sd' ' - <<<"$BLOCKED")"
}

# The change-set key of a latest: "dev <SHA>" then sorted "<repo> <N> <head>"
# lines from stdin.
latest_set_key() {
  printf 'dev %s\n' "$1"
  sed '/^[[:space:]]*$/d' | LC_ALL=C sort
}

# Add one judged change to LATEST_SELECTED ("repo<TAB>N<TAB>title<TAB>draft<TAB>head<TAB>needs")
# when the mode takes it. $1 repo, $2 N, $3 title, $4 draft, $5 a fork PR's
# needs= base (see list_fork_prs) or empty.
consider_change() {
  local repo="$1" num="$2" ref lhead take="" why="$VERDICT"
  if [ "$repo" = "$STAGING_REPO" ]; then ref="fork#$num"; else ref="#$num"; fi
  lhead=$(awk -v r="$repo" -v n="$num" '$1 == r && $2 == n { print $3 }' <<<"$L_PRS")
  if [ "$JUDGED_BLOCKED" = 1 ]; then
    :
  elif [ "$VERDICT_OK" = 1 ] && { [ "$LATEST_MODE" = weekly ] || [ "$JUDGED_FIX" = 1 ]; }; then
    take=$JUDGED_HEAD
    if [ "$JUDGED_FIX" = 1 ] && [ "$take" != "$lhead" ]; then FIX_FOUND=1; fi
    if [ "$WAIVE_REF" = "$repo#$num" ]; then WAIVED_SEEN=1; fi
  elif [ -n "$lhead" ]; then
    take=$lhead why="kept at latest's head; $VERDICT"
  elif [ "$VERDICT_OK" = 1 ]; then
    why="soaked; a fix build takes only bugfixes"
  fi
  if [ -n "$take" ]; then info "$ref [$JUDGED_TYPE] takes ${take:0:10}: $why"; else info "$ref [$JUDGED_TYPE] waits: $why"; fi
  [ -z "$take" ] || LATEST_SELECTED+="$repo"$'\t'"$num"$'\t'"$3"$'\t'"$4"$'\t'"$take"$'\t'"${5:-}"$'\n'
}

# Return 0 when every judged dev commit that dev commit $1 contains has soaked.
dev_soaked_through() {
  local c num ok
  while read -r c num ok; do
    [ -n "$c" ] || continue
    if [ "$ok" != 1 ] && git merge-base --is-ancestor "$c" "$1"; then return 1; fi
  done <<<"$DEV_VERDICTS"
}

# Decide whether this run builds latest, and from what. Sets LATEST_BUILD and,
# when 1, LATEST_BASE_DEV, LATEST_BASE_MAIN, LATEST_CORE and LATEST_FORK
# (list_core_prs line format). A latest not built for want of the captain's
# word sets LATEST_HELD instead.
plan_latest() {
  log "Latest: plan"
  LATEST_BUILD=0
  git fetch origin main
  git fetch upstream dev
  collect_prs

  local latest_unix
  LATEST_TAG=$(gh api "repos/$FORK_REPO/releases/latest" --jq '.tag_name') \
    || die "could not read the latest release on $FORK_REPO"
  latest_unix=$(git for-each-ref --format='%(taggerdate:unix)' "refs/tags/$LATEST_TAG")
  [ -n "$latest_unix" ] || die "latest release $LATEST_TAG has no annotated tag in the fetched tags"
  if tag_lines "$LATEST_TAG" release-kind | grep -qx latest; then
    L_DEV=$(tag_field "$LATEST_TAG" dev)
    L_MAIN=$(tag_field "$LATEST_TAG" main)
    L_PRS=$(tag_lines "$LATEST_TAG" pr)
  else
    # A latest from before this mode records no change set: its dev base is
    # where its release branch meets dev, and its own base cannot be rebuilt.
    L_DEV=$(git merge-base "$LATEST_TAG" upstream/dev) || die "cannot find the dev base of $LATEST_TAG"
    L_MAIN="" L_PRS=""
  fi
  local age=$(( $(today_day) - latest_unix / 86400 ))
  info "latest $LATEST_TAG: ${age}d old, dev base ${L_DEV:0:10}, $(sed '/^$/d' <<<"$L_PRS" | wc -l) PRs"

  PRE_INDEX=$(prerelease_index)
  load_blocked || { info "latest held: $LATEST_HELD"; return 0; }

  # Judge every teslemetry dev commit since latest's dev base, oldest first.
  local c subject num ok
  DEV_VERDICTS=""
  while IFS=$'\t' read -r c subject; do
    [ -n "$c" ] || continue
    num=$(sed -n 's/.*(#\([0-9][0-9]*\)).*/\1/p' <<<"$subject")
    judge_change "$CORE_REPO" "$num" "" "" "$c"
    DEV_VERDICTS+="$c ${num:--} $VERDICT_OK"$'\n'
    info "dev ${c:0:10} ${num:+#$num }[$JUDGED_TYPE]: $VERDICT"
  done < <(git log --no-merges --reverse --format='%H%x09%s' "$L_DEV..upstream/dev" -- "$INTEGRATION")

  # Weekly once latest is 7 days old; a fix build needs latest's recorded
  # change set, so a waiver on an older-format latest builds weekly.
  if [ "$age" -ge 7 ]; then LATEST_MODE=weekly
  elif [ -n "$L_MAIN" ]; then LATEST_MODE=fix
  elif [ -n "$WAIVE_REF" ]; then LATEST_MODE=weekly
  else info "$LATEST_TAG records no change set and is under 7 days old; no latest"; return 0
  fi

  # Base: the newest pre-release on its pinned core tag whose new dev commits
  # have all soaked. A fix build keeps latest's own base.
  LATEST_BASE_DEV="" LATEST_BASE_MAIN=""
  local day tag kind dev main
  if [ "$LATEST_MODE" = weekly ]; then
    while read -r day tag kind dev; do
      [ "$kind" = dev ] || continue
      git merge-base --is-ancestor "$L_DEV" "$dev" 2>/dev/null || continue
      main=$(tag_field "$tag" main)
      git cat-file -e "$main^{commit}" 2>/dev/null || continue
      on_core_base "$main" || continue
      dev_soaked_through "$dev" || continue
      LATEST_BASE_DEV=$dev LATEST_BASE_MAIN=$main
      info "base: $tag (dev ${dev:0:10})"
      break
    done < <(tac <<<"$PRE_INDEX")
  fi
  if [ -z "$LATEST_BASE_DEV" ]; then
    [ -n "$L_MAIN" ] || { info "no pre-release base has soaked and $LATEST_TAG records no base; no latest"; return 0; }
    on_core_base "$L_MAIN" || { info "no pre-release base has soaked and $LATEST_TAG's base is not on its pinned core tag; no latest"; return 0; }
    LATEST_BASE_DEV=$L_DEV LATEST_BASE_MAIN=$L_MAIN
    info "base: latest's own (dev ${L_DEV:0:10})"
  fi

  log "Latest: $LATEST_MODE build candidates"
  LATEST_SELECTED="" FIX_FOUND=0 WAIVED_SEEN=0
  local title draft sha needs core_base fork_base seen=" "
  core_base=$(fetch_ref "$CORE_REPO" dev)
  while IFS=$'\t' read -r num title draft sha; do
    [ -n "$num" ] || continue
    judge_change "$CORE_REPO" "$num" "$sha" "$core_base" ""
    consider_change "$CORE_REPO" "$num" "$title" "$draft"
  done <<<"$CORE_PRS"
  if [ -n "$FORK_PRS" ]; then fork_base=$(fetch_ref "$STAGING_REPO" dev); fi
  while IFS=$'\t' read -r num title draft sha needs; do
    [ -n "$num" ] || continue
    judge_change "$STAGING_REPO" "$num" "$sha" "$fork_base" ""
    consider_change "$STAGING_REPO" "$num" "$title" "$draft" "$needs"
  done <<<"$FORK_PRS"
  # PRs merged into dev beyond the base apply from their PR diff.
  while read -r c num ok; do
    [ -n "$c" ] && [ "$num" != - ] || continue
    if git merge-base --is-ancestor "$c" "$LATEST_BASE_DEV" || [[ "$seen" == *" $num "* ]]; then continue; fi
    seen+="$num "
    judge_change "$CORE_REPO" "$num" "" "" "$c"
    consider_change "$CORE_REPO" "$num" "$(jq -r .title <<<"${PR_INFO[$CORE_REPO#$num]}")" false
  done <<<"$DEV_VERDICTS"

  if [ -n "$WAIVE_REF" ] && [ "$WAIVED_SEEN" != 1 ]; then
    die "--waive $WAIVE: not an open, composed or newly merged PR that latest can take (kept out by an issue?)"
  fi
  if [ "$LATEST_MODE" = fix ] && [ "$FIX_FOUND" != 1 ]; then
    info "no soaked bugfix is missing from $LATEST_TAG; no latest"
    return 0
  fi
  if [ "$(awk -F'\t' 'NF { print $1, $2, $5 }' <<<"$LATEST_SELECTED" | latest_set_key "$LATEST_BASE_DEV")" \
       = "$(latest_set_key "$L_DEV" <<<"$L_PRS")" ]; then
    info "the soaked set equals $LATEST_TAG's change set; no latest"
    return 0
  fi
  LATEST_CORE=$(awk -F'\t' -v r="$CORE_REPO" '$1 == r { print $2 "\t" $3 "\t" $4 "\t" $5 }' <<<"$LATEST_SELECTED" | sort -n)
  # Fork PRs keep list_fork_prs' order: a needs=fork entry follows its base.
  LATEST_FORK=$(awk -F'\t' -v r="$STAGING_REPO" '$1 == r { print $2 "\t" $3 "\t" $4 "\t" $5 "\t" $6 }' <<<"$LATEST_SELECTED")
  LATEST_BUILD=1
}

# The captain's word on a floor or requirements change: compare the composed
# floor and requirements with latest's. A difference passes only with
# --approve-requirements set to the digest of the composed ones; otherwise it
# sets LATEST_HELD and returns 1.
latest_requirements_word() {
  local old new digest
  old=$(requirements_text "$LATEST_TAG")
  new=$(requirements_text HEAD)
  [ "$old" != "$new" ] || { info "floor and requirements unchanged from $LATEST_TAG"; return 0; }
  digest=$(printf '%s\n' "$new" | sha256sum | cut -c1-12)
  diff <(printf '%s\n' "$old") <(printf '%s\n' "$new") | sed 's/^/      /' || true
  if [ "$APPROVE_REQUIREMENTS" = "$digest" ]; then
    info "floor/requirements change $digest approved by the captain"
    return 0
  fi
  LATEST_HELD="the hacs.json floor or manifest requirements differ from $LATEST_TAG (diff above). With the captain's word, rerun with --approve-requirements $digest"
  return 1
}

# Compose, stamp and gate latest on its own release branch; zip it and write
# its notes outside the worktree. Then claim the pre-release's version.
build_latest() {
  LATEST_VERSION=$VERSION
  log "Latest: compose v$LATEST_VERSION"
  git branch -D "release-$VERSION" >/dev/null 2>&1 || true
  git checkout -q -b "release-$VERSION" "$LATEST_BASE_MAIN"
  COMPOSING_LATEST=1
  compose_prs "$LATEST_CORE" "$LATEST_FORK" "$LATEST_BASE_DEV"
  COMPOSING_LATEST=0
  if [ "$(printf '%s\n' ${APPLIED_SET[@]+"${APPLIED_SET[@]}"} | latest_set_key "$LATEST_BASE_DEV")" \
       = "$(latest_set_key "$L_DEV" <<<"$L_PRS")" ]; then
    info "with the waiting changes left out, the set equals $LATEST_TAG's; no latest"
    return 0
  fi
  if ! latest_requirements_word; then
    info "latest held: $LATEST_HELD"
    return 0
  fi
  update_version
  SHIPPED_FLOOR_TAG=$LATEST_TAG run_gates
  build_gate
  LATEST_DIR=$(mktemp -d)
  trap 'rm -rf "$LATEST_DIR"' EXIT
  mv release_notes.txt "$LATEST_DIR/release_notes.txt"
  zip_integration "$LATEST_DIR/teslemetry.zip"
  # The build gate recompiles translations into the tree; the zip holds them.
  git checkout -q -- .
  LATEST_MSG=$(printf 'Release %s\n\nrelease-kind: latest\ndev: %s\nmain: %s\n' \
                 "$VERSION" "$LATEST_BASE_DEV" "$LATEST_BASE_MAIN"
               printf 'pr: %s\n' ${APPLIED_SET[@]+"${APPLIED_SET[@]}"} | sed '/^pr: $/d')
  LATEST_BUILT=1
  VERSION=$(daily_version "$(date -u +%Y.%-m.%-d)" "$LATEST_VERSION")
  info "latest v$LATEST_VERSION gated; the pre-release takes v$VERSION"
}

# Re-delete the core CI/CD workflows and commit if anything was staged.
# --ignore-unmatch makes it a no-op when upstream didn't touch these paths.
strip_core_ci() {
  git rm -rf --ignore-unmatch "${CORE_CI_PATHS[@]}" >/dev/null 2>&1 || true
  if ! git diff --cached --quiet; then
    git commit -m "Strip core CI/CD workflow noise" --no-verify >/dev/null
    info "stripped core CI/CD workflows"
  fi
}

# During the sync rebase, resolve each modify/delete conflict on a core CI/CD
# workflow this fork deliberately deletes by keeping it deleted. "Deliberately
# deleted" is CORE_CI_PATHS, the same list strip_core_ci re-deletes. A conflict
# qualifies only when main's replayed commit deleted the path (index stages 1
# and 2, no stage 3, and REBASE_HEAD deletes that exact path) and the path is in that list; a workflow main keeps, a
# content conflict and any other path are left for rerere or a human. Returns 0
# if it removed at least one path.
keep_deleted_ci_conflicts() {
  local path stages ci kept=1 conflicted=()
  # Collect every path before the loop so git diff has exited, and released any
  # index lock it took, before git rm needs the index.
  mapfile -d '' -t conflicted < <(git diff -z --name-only --diff-filter=U)
  for path in "${conflicted[@]}"; do
    stages=$(git ls-files -u -- "$path" | awk '{print $3}' | sort -u | tr -d '\n')
    [ "$stages" = "12" ] || continue
    # A rename conflict can also leave stages 1 and 2 here: require the replayed
    # commit itself to delete this exact path.
    git diff --no-renames --diff-filter=D --name-only -z REBASE_HEAD^ REBASE_HEAD -- "$path" \
      | grep -qz . || continue
    for ci in "${CORE_CI_PATHS[@]}"; do
      if [ "$path" = "$ci" ] || [ "${path#"$ci"/}" != "$path" ]; then
        git rm -q -- "$path" || return 1
        info "kept deleted: $path (core changed it; this fork deletes it)"
        kept=0
        break
      fi
    done
  done
  return "$kept"
}

# Step 2: sync main on a temp branch: rebase main's fork commits onto a fresh
# base commit (the pinned core tag named by main's hacs.json, with the
# integration and its tests from upstream dev), then push with a lease on the
# main fetched here. The fork commits are those no base commit and no dev
# commit reaches (see rebase_upstream).
sync_dev() {
  log "Step 2: sync main onto the pinned core base with the integration from upstream dev"
  git fetch origin main
  git fetch upstream dev
  SYNC_BASE_MAIN=$(git rev-parse origin/main)
  local tag old_base new_base from
  tag=$(core_base_tag origin/main)
  fetch_core_tag "$tag" || die "could not fetch core tag $tag - the hacs.json floor must be a released core version"
  old_base=$(main_base_commit origin/main)
  new_base=$(make_base_commit "$tag" upstream/dev "$old_base")
  from=$(rebase_upstream origin/main)
  info "core base $tag, integration from dev $(git rev-parse --short=10 upstream/dev)"

  git branch -D sync-dev >/dev/null 2>&1 || true
  git checkout -b sync-dev origin/main

  if ! git rebase --onto "$new_base" "$from"; then
    [ -d "$(git rev-parse --git-path rebase-merge)" ] || die "rebase of main onto the core base failed"
    while :; do
      if keep_deleted_ci_conflicts && [ -z "$(git diff --name-only --diff-filter=U)" ]; then
        :
      elif ! rerere_resolved; then
        pause "Conflict rebasing a main commit onto the core base (core $tag, integration from upstream/dev). Edit files to resolve (no mergetool), 'git add' each resolved file. Do NOT commit or continue the rebase - this script does."
        assert_no_unmerged
      fi
      GIT_EDITOR=true git rebase --continue && break
    done
  fi
  strip_core_ci
  assert_no_conflict_markers

  # A daily run pushes the sync only once every gate has passed (push_gated_sync).
  if [ "$DAILY" = 1 ]; then
    info "daily: main not pushed until every gate passes"
    return 0
  fi

  git push --force-with-lease="main:$SYNC_BASE_MAIN" origin sync-dev:main \
    || die "push to main refused (main moved since this run fetched it) - rerun"
  info "main synced (rebased, leased push)"
}

# Daily: push the gated dev sync to main, after every gate and the release
# window check passed and before anything is tagged. The lease is the main this
# run rebased. If main moved during the run, the gates covered a stale
# candidate: stop with nothing published and leave the rerun to compose against
# the new main.
push_gated_sync() {
  log "Push the gated dev sync to main"
  git push --force-with-lease="main:$SYNC_BASE_MAIN" origin sync-dev:main \
    || die "main moved since this run synced it - nothing published. Rerun the daily cut so the gates cover the current main."
  info "main synced (rebased, leased push)"
}

# Step 3: cut the release branch off the just-synced state.
create_release_branch() {
  log "Step 3: create release branch"
  git branch -D "release-$VERSION" >/dev/null 2>&1 || true
  git checkout -b "release-$VERSION"
  info "on release-$VERSION"
}

# Fetch one ref from a GitHub repo and print its commit.
fetch_ref() {
  git fetch --quiet "https://github.com/$1" "$2" || die "could not fetch $1 $2"
  git rev-parse FETCH_HEAD
}

# List open PRs on a repo as a JSON array. Extra args are passed to gh pr list.
# gh defaults to 30 results and truncates silently - that dropped the 8 oldest
# core PRs from one cut - so an explicit limit is set and a result that fills it
# fails loudly instead of composing a partial release.
list_open_prs() {
  local repo="$1"; shift
  local json count
  json=$(gh pr list --repo "$repo" --state open --limit "$PR_LIST_LIMIT" \
           --json number,title,isDraft,headRefOid,files "$@") \
    || die "could not list open PRs on $repo"
  count=$(jq 'length' <<<"$json")
  [ "$count" -lt "$PR_LIST_LIMIT" ] \
    || die "gh pr list on $repo returned $count PRs, the --limit - the list may be truncated. Raise PR_LIST_LIMIT and rerun."
  printf '%s' "$json"
}

# Open Bre77 teslemetry PRs on core, ascending (oldest-to-newest proxy), as
# "number<TAB>title<TAB>draft<TAB>head SHA" lines.
list_core_prs() {
  list_open_prs "$CORE_REPO" --author Bre77 --label "integration: teslemetry" \
    | jq -r 'sort_by(.number)[] | "\(.number)\t\(.title)\t\(.isDraft)\t\(.headRefOid)"'
}

# Fork PR numbers in the ha-promoter queue file $1, one "<number><TAB><needs>"
# line per entry, in file order. A queue line is `123`, `#123` or the fork PR
# URL, optionally followed by a docs branch name (ignored here), optionally
# followed by `needs=core#<N>` or `needs=fork#<N>`: the PR builds on that
# unmerged base and is composed only with it (see list_fork_prs). <needs> is
# that ref, or empty. Blank lines are skipped. Any other line dies, so a
# malformed queue never silently drops an approved PR.
read_promote_queue() {
  local file="$1" line entry docs needs rest num
  [ -r "$file" ] || die "PROMOTE_QUEUE=$file is not a readable file"
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

# Open PRs on the staging fork against its dev that touch the integration or
# its tests, draft or ready, ascending, in the same line format plus a fifth
# field: the entry's needs= base ("core#<N>" or "fork#<N>"), or empty.
# With PROMOTE_QUEUE set to the ha-promoter queue file, only the PRs queued
# there are taken. A queued PR that is not in that open set is skipped with a
# note on stderr: ha-promoter closes a fork PR when it opens it upstream, and
# that change then returns through list_core_prs.
#
# A needs= entry is taken only with its base: needs=fork#N only when fork PR N
# is taken too, needs=core#N only when core PR N is in list_core_prs or merged
# into core dev (whose integration the core base carries). Otherwise it is
# skipped with a note, as is any entry whose own base is skipped. Each needs=fork
# entry comes after its base; the rest stay ascending.
list_fork_prs() {
  local queued="null" num
  if [ -n "${PROMOTE_QUEUE:-}" ]; then
    # Bash clears errexit in command substitutions: propagate failures by hand.
    queued=$(read_promote_queue "$PROMOTE_QUEUE" \
      | jq -Rs '[split("\n")[] | select(. != "") | split("\t")
                 | {number: (.[0] | tonumber), needs: (if (.[1] // "") == "" then null else .[1] end)}]
                | unique_by(.number)') || exit 1
  fi
  local json
  json=$(list_open_prs "$STAGING_REPO" --base dev \
    | jq --argjson queued "$queued" \
         '[.[] | select(any(.files[].path;
             startswith("homeassistant/components/teslemetry/")
             or startswith("tests/components/teslemetry/")))
           | .number as $n
           | select($queued == null or any($queued[]; .number == $n))
           | .needs = ($queued // [] | map(select(.number == $n))[0].needs)]
         | sort_by(.number)') || exit 1
  if [ "$queued" != null ]; then
    for num in $(jq -r --argjson open "$json" '[.[].number] - [$open[].number] | .[]' <<<"$queued"); do
      info "fork#$num is queued but not an open teslemetry PR on $STAGING_REPO (base dev); skipped" >&2
    done
  fi

  # Core bases: open ones from list_core_prs (the cut's own listing when
  # collect_prs already made it), the rest only when merged into dev.
  local core_needs core_ok="[]" core_prs merged
  core_needs=$(jq -r '[.[].needs // empty | select(startswith("core#")) | ltrimstr("core#")] | unique | .[]' <<<"$json")
  if [ -n "$core_needs" ]; then
    core_prs=${CORE_PRS-$(list_core_prs)} || exit 1
    for num in $core_needs; do
      if ! cut -f1 <<<"$core_prs" | grep -qx "$num"; then
        merged=$(gh api "repos/$CORE_REPO/pulls/$num" --jq '.merged and .base.ref == "dev"') \
          || die "could not read $CORE_REPO pull $num"
        [ "$merged" = true ] || continue
      fi
      core_ok=$(jq --argjson n "$num" '. + [$n]' <<<"$core_ok")
    done
  fi
  local result
  result=$(jq --argjson core "$core_ok" '
    def missing($nums):
      .needs != null and ((.needs | split("#")) as [$repo, $n]
        | ($n | tonumber) as $n
        | if $repo == "fork" then ($nums | index($n)) == null else ($core | index($n)) == null end);
    # Drop entries whose base is missing until none is: a dropped base drops its dependents.
    def prune($dropped):
      [.[].number] as $nums
      | map(select(missing($nums))) as $miss
      | if $miss == [] then {kept: ., dropped: $dropped}
        else map(select(missing($nums) | not)) | prune($dropped + $miss) end;
    # Ascending, except that a needs=fork entry waits for its base.
    def order($done):
      if . == [] then {order: $done}
      else [$done[].number] as $nums
        | map(select(.needs == null or (.needs | startswith("core#"))
                     or ((.needs | ltrimstr("fork#") | tonumber) as $n | ($nums | index($n)) != null))) as $ready
        | if $ready == [] then {order: $done, cycle: map(.number)}
          else (. - [$ready[0]]) | order($done + [$ready[0]]) end end;
    prune([]) | .dropped as $dropped | .kept | order([]) | .dropped = $dropped' <<<"$json") || exit 1
  jq -r '.dropped[] | "fork#\(.number) needs \(.needs), which this cut does not compose; skipped"' <<<"$result" \
    | while IFS= read -r num; do info "$num" >&2; done
  if jq -e '.cycle' <<<"$result" >/dev/null; then
    die "fork PRs $(jq -r '.cycle | map("fork#\(.)") | join(" ")' <<<"$result") need each other in a cycle (PROMOTE_QUEUE needs=)"
  fi
  jq -r '.order[] | "\(.number)\t\(.title)\t\(.isDraft)\t\(.headRefOid)\t\(.needs // "")"' <<<"$result"
}

# Capture both lists once, before applying anything, so a truncated or failed
# listing dies before the first commit. A daily run collects them early for its
# input fingerprint; apply_prs then composes exactly that set.
collect_prs() {
  [ -z "${PRS_COLLECTED:-}" ] || return 0
  CORE_PRS=$(list_core_prs)
  FORK_PRS=$(list_fork_prs)
  PRS_COLLECTED=1
}

# Apply one PR as one commit. $1 repo, $2 number, $3 title, $4 draft flag,
# $5 ref prefix ("#" for core, "fork#" for the staging fork), $6 the commit of
# the PR's base branch, $7 the head SHA the PR listing returned, $8 the head
# of the PR's needs= base PR (empty: none). The prefix
# marks the commit subject, the approval summary and the release-notes line.
# The listed head is what gets applied, so a push to the PR during the run
# cannot make the build differ from the head SHAs a daily tag records.
#
# Applies the PR's NET diff (merge-base to head, what GitHub shows as the PR's
# changes) with a three-way merge, not one patch per PR commit: on a
# multi-commit PR the intermediate patches conflict with each other even when
# the net change merges cleanly. The fetched head and base give git apply -3
# every pre-image blob, so it falls back to a real three-way merge.
#
# A needs= PR's branch carries its base PR's commits, which the compose has
# already applied. Its diff starts at its merge-base with the base PR's head
# instead, when that is newer than the one with its base branch, so it holds
# only the PR's own change: re-applying the base's change would conflict where
# the base creates a file (add/add).
#
# In a latest compose (COMPOSING_LATEST=1) a diff that cannot apply at all and
# leaves no conflict (it edits a file only a younger change creates) waits: it
# is left out and the notes name it. A real conflict still stops.
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
  # TEMPORARY (quality-scale work in progress): keep quality_scale.yaml out
  # of every per-PR diff to avoid repeated conflicts; the combined final
  # state is applied once at the end of apply_prs, only if a PR touched it.
  # Remove this exclusion and the end-of-loop checkpoint once the quality scale
  # PRs have all merged.
  if ! git diff --quiet "$mb" "$head" -- '*quality_scale.yaml'; then QUALITY_SCALE_PRS+=("$ref"); fi
  local pathspec=(. ':(exclude)*quality_scale.yaml')
  if git diff --quiet "$mb" "$head" -- "${pathspec[@]}"; then
    info "no changes outside quality_scale.yaml"
  elif git diff --full-index --binary "$mb" "$head" -- "${pathspec[@]}" | git apply -3; then
    info "applied cleanly"
  elif rerere_resolved; then
    CONFLICTED_PRS+=("$ref (rerere)")
  elif [ "${COMPOSING_LATEST:-0}" = 1 ] && [ -z "$(git diff --name-only --diff-filter=U)" ]; then
    git reset -q --hard HEAD
    info "does not apply without a younger change; waits"
    NOTE_LINES+=("Waiting for a younger change: [$ref](https://github.com/$repo/pull/$num): $title")
    return 0
  else
    CONFLICTED_PRS+=("$ref")
    pause "PR $ref did not apply cleanly. Read its intent (gh pr diff $num --repo $repo), edit files to resolve, 'git add' each. Do NOT commit - this script commits."
    assert_no_unmerged
  fi
  # -A (not -am): capture any new files the patch adds (e.g. a new calendar.py).
  git add -A
  git commit -m "$ref: $title" --allow-empty --no-verify >/dev/null
  # Enforce the post-commit marker grep the runbook left to memory.
  assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
  local status=""
  if [ "$repo" = "$STAGING_REPO" ]; then
    # Fork PRs are staged changes awaiting review; say which state each is in.
    if [ "$draft" = true ]; then status=" (staged, draft)"; else status=" (staged, ready)"; fi
  fi
  NOTE_LINES+=("[$ref](https://github.com/$repo/pull/$num): $title$status")
  APPLIED_PRS+=("$ref $title$status")
  APPLIED_SET+=("$repo $num $listed")
  APPLIED_HEADS[$ref]=$head
}

# Step 4: compose the release on top of synced core dev - every open Bre77
# teslemetry PR on core, then every open teslemetry PR on the staging fork (only
# the queued ones with PROMOTE_QUEUE set), each group oldest-to-newest. JUDGMENT
# checkpoint: clean applies and conflicts rerere replays auto-commit; any other
# conflict STOPS for manual resolution. Per-PR note lines are collected here and
# written to release_notes.txt in update_version - never a tracked file, so
# `git add -A` can't stage it.
apply_prs() {
  log "Step 4: apply core and staging-fork PR net diffs"
  collect_prs
  compose_prs "$CORE_PRS" "$FORK_PRS" "$(git rev-parse upstream/dev)"
}

# Apply core PR lines $1 (list_core_prs format), then fork PR lines $2
# (list_fork_prs format), each as one commit, then the quality_scale.yaml
# checkpoint. $3 is the core dev commit whose integration the base carries.
# Shared by the pre-release and the latest compose.
#
# A fork PR with a needs= base applies only after that base: a fork PR or open
# core PR this compose applied, or a core PR merged into $3. Otherwise it is
# left out with a note (the latest compose can leave a base out).
compose_prs() {
  APPLIED_PRS=()
  APPLIED_SET=()
  APPLIED_HEADS=()
  CONFLICTED_PRS=()
  NOTE_LINES=()
  QUALITY_SCALE_PRS=()

  local num title draft sha needs needs_head core_base fork_base
  if [ -z "$1" ]; then
    info "no core PRs on $CORE_REPO to apply"
  else
    core_base=$(fetch_ref "$CORE_REPO" dev)
    while IFS=$'\t' read -r num title draft sha; do
      [ -n "$num" ] || continue
      apply_one_pr "$CORE_REPO" "$num" "$title" "$draft" "#" "$core_base" "$sha"
    done <<<"$1"
  fi

  if [ -z "$2" ]; then
    info "no fork PRs on $STAGING_REPO to apply"
  else
    fork_base=$(fetch_ref "$STAGING_REPO" dev)
    while IFS=$'\t' read -r num title draft sha needs; do
      [ -n "$num" ] || continue
      needs_head=""
      if [ -n "$needs" ]; then
        needs_head=${APPLIED_HEADS[${needs#core}]:-}
        if [ -z "$needs_head" ] && [[ "$needs" == core#* ]]; then
          needs_head=$(core_pr_merged_head "${needs#core#}" "$3")
        fi
        if [ -z "$needs_head" ]; then
          info "fork#$num needs $needs, which this compose does not carry; left out"
          NOTE_LINES+=("Waiting for its base $needs: [fork#$num](https://github.com/$STAGING_REPO/pull/$num): $title")
          continue
        fi
      fi
      apply_one_pr "$STAGING_REPO" "$num" "$title" "$draft" "fork#" "$fork_base" "$sha" "$needs_head"
    done <<<"$2"
  fi

  apply_fixups

  # TEMPORARY: apply the combined final quality_scale.yaml once (judgment step),
  # only when an applied PR changed it.
  if [ "${#QUALITY_SCALE_PRS[@]}" -gt 0 ]; then
    pause "quality_scale.yaml was excluded from every patch above and ${QUALITY_SCALE_PRS[*]} changed it. Apply the correct combined final state now (read those PRs' final quality_scale.yaml and write it), 'git add' it."
    if ! git diff --cached --quiet; then
      git commit -m "Apply combined quality_scale.yaml" --no-verify >/dev/null
      info "committed combined quality_scale.yaml"
    fi
  else
    info "no applied PR changed quality_scale.yaml"
  fi
  assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
}

# Apply each tracked release fixup whose PRs this compose applied, as one
# commit. A fixup reconciles PRs that apply cleanly together but clash in
# meaning (one changes a signature the other calls). Its file name lists the
# PRs it needs, joined by "+": core-<N> for core #N, fork-<N> for fork#N
# (release-fixups/core-174090+core-186075.patch). A fixup whose PRs are not all
# applied (merged upstream, closed, or left out) does nothing; delete it once
# one of its PRs merges upstream.
apply_fixups() {
  local patch name part ref missing parts
  for patch in "$RELEASE_FIXUPS"/*.patch; do
    [ -e "$patch" ] || continue
    name=$(basename "$patch" .patch)
    missing=""
    IFS='+' read -ra parts <<<"$name"
    for part in "${parts[@]}"; do
      ref=${part/#core-/#}; ref=${ref/#fork-/fork#}
      [ -n "${APPLIED_HEADS[$ref]:-}" ] || missing+=" $ref"
    done
    if [ -n "$missing" ]; then
      info "fixup $name: not applied (${missing# } not in this compose)"
      continue
    fi
    log "  fixup $name"
    git apply --index "$patch" \
      || pause "release-fixups/$name.patch no longer applies to this compose. Update the patch on main, or apply its intent by hand and 'git add' each file. Do NOT commit - this script commits."
    assert_no_unmerged
    git commit -m "fixup: $name" --allow-empty --no-verify >/dev/null
    assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
  done
}

# Print the head of core PR $1 when it is merged into dev and its merge commit
# is in core dev commit $2; print nothing otherwise.
core_pr_merged_head() {
  local pr merge head
  pr=$(gh api "repos/$CORE_REPO/pulls/$1" --jq 'select(.merged and .base.ref == "dev") | "\(.merge_commit_sha) \(.head.sha)"') \
    || die "could not read $CORE_REPO pull $1"
  read -r merge head <<<"$pr"
  [ -n "$merge" ] && git cat-file -e "$merge^{commit}" 2>/dev/null \
    && git merge-base --is-ancestor "$merge" "$2" || return 0
  git cat-file -e "$head^{commit}" 2>/dev/null || head=$(fetch_ref "$CORE_REPO" "pull/$1/head")
  printf '%s\n' "$head"
}

# Step 5: stamp version into both manifests and write release_notes.txt.
# release_notes.txt stays untracked: it feeds `gh release create -F`, not a commit.
update_version() {
  log "Step 5: update version and manifests"

  # Compatibility notes (only those the composed build needs), then the
  # standing polling note, before any per-PR lines.
  release_compat_note > release_notes.txt \
    || die "release notes not written: see the compatibility note failure above"
  cat >> release_notes.txt <<'NOTE'
Builds older than v3.0.0 request vehicle data every 30 seconds; v3.0.0 lowered that to every 15 minutes, and v4.0.0 changed it to every 60 seconds (v4.0.1 added the gate). Current builds do not poll modern streaming vehicles at all, and fall back to 60-second polling only for vehicles that cannot use signed commands. Upgrading stops the excess polling.
NOTE
  local line
  for line in ${NOTE_LINES[@]+"${NOTE_LINES[@]}"}; do printf '%s\n' "$line" >> release_notes.txt; done
  printf '\n**Full Changelog**: https://github.com/%s/commits/v%s\n' "$FORK_REPO" "$VERSION" >> release_notes.txt

  yq -i -o json ".version=\"$VERSION\"" "$INTEGRATION/manifest.json"
  cp "$INTEGRATION/manifest.json" "custom_components/teslemetry/manifest.json"
  git commit -am "v$VERSION" --no-verify >/dev/null
  info "manifests at $VERSION, release_notes.txt written"
}

# Hard gate: the composed build sits on the core tag its hacs.json floor names,
# so the build gate tests the integration against the release it claims to
# support. A latest built on a main from before the pinned base fails here.
core_base_gate() {
  log "Gate: build sits on its pinned core base"
  local tag
  tag=$(core_base_tag)
  on_core_base HEAD || die "HEAD is not on core tag $tag (the hacs.json floor) - the build must be composed on the pinned core base"
  info "on core $tag"
}

# Hard gate: the HACS-only subentry back-migration silently vanished in v6.0.9
# when the release branches carrying it were never merged back to main - two
# releases shipped without it and nothing noticed, because only a doc sentence
# asserted its existence. See AGENTS.md. Assert against the composed tree that
# the function is defined, actually CALLED from async_setup_entry (a defined-
# but-uncalled migration is exactly as broken as a missing one), and its tests
# ship with it. The empty-holder cleanup must run after it: run first, it would
# remove holders that still own records.
subentry_migration_gate() {
  log "Gate: hacs_migrate_subentry_entities present in composed release"
  local fn="hacs_migrate_subentry_entities" holder="hacs_remove_empty_holder_subentries"
  local fn_line holder_line
  [ -f "$INIT_PY" ] || die "$INIT_PY missing"
  grep -q "def $fn" "$INIT_PY" \
    || die "$fn not defined in $INIT_PY - the HACS-only subentry back-migration is missing. It silently vanished in v6.0.9; see AGENTS.md."
  fn_line=$(setup_entry_line "$fn(" "$INIT_PY")
  [ "$fn_line" != 0 ] \
    || die "$fn is defined but never called from async_setup_entry in $INIT_PY - a defined-but-uncalled migration is as broken as a missing one. See AGENTS.md for the v6.0.9 history."
  [ -f "$MIGRATION_TEST" ] \
    || die "$MIGRATION_TEST missing - the subentry back-migration must ship with its tests. See AGENTS.md."
  grep -q "^def $holder(" "$INIT_PY" \
    || die "$holder not defined in $INIT_PY - the HACS-only empty-holder cleanup is missing. See AGENTS.md."
  holder_line=$(setup_entry_line "$holder(" "$INIT_PY")
  [ "$holder_line" -gt "$fn_line" ] \
    || die "$holder must be called from async_setup_entry after $fn in $INIT_PY - run before it, it removes holders that still own records. See AGENTS.md."
  info "$fn defined, called from async_setup_entry, tests present; $holder runs after it"
}

# Hard gate: beta_migration_fix backfills auth_implementation for early beta
# entries. Dev has no test that sets up such an entry, so a conflict resolution
# that drops it ships green and those installs fail OAuth setup. The core-dev
# sync conflicts on its call. See AGENTS.md.
beta_migration_gate() {
  log "Gate: beta_migration_fix present in composed release"
  local fn="beta_migration_fix"
  [ -f "$INIT_PY" ] || die "$INIT_PY missing"
  grep -q "^def $fn(" "$INIT_PY" \
    || die "$fn not defined in $INIT_PY - the HACS-only auth_implementation backfill is missing. See AGENTS.md."
  [ "$(setup_entry_line "$fn(" "$INIT_PY")" != 0 ] \
    || die "$fn is defined but never called from async_setup_entry in $INIT_PY. See AGENTS.md."
  info "$fn defined and called from async_setup_entry"
}

# Hard gate: the opt-in ClickStack log shipping setup in async_setup_entry. A
# conflict resolution that drops it turns shipping off for every user who opted
# in, and no test asserts that setup acquires the shipper. See AGENTS.md.
logship_gate() {
  log "Gate: ClickStack log shipping set up in composed release"
  local call
  [ -f "$INIT_PY" ] || die "$INIT_PY missing"
  [ -f "$INTEGRATION/logship.py" ] || die "$INTEGRATION/logship.py missing - the HACS-only log shipper is gone. See AGENTS.md."
  for call in "async_get_or_create_logship(" ".async_acquire(" ".async_release" "_async_setup_option_reload("; do
    [ "$(setup_entry_line "$call" "$INIT_PY")" != 0 ] \
      || die "async_setup_entry in $INIT_PY no longer contains $call - the HACS-only log shipping setup was dropped. See AGENTS.md."
  done
  grep -q 'def async_get_options_flow' "$INTEGRATION/config_flow.py" \
    || die "$INTEGRATION/config_flow.py has no options flow - users cannot opt in to log shipping. See AGENTS.md."
  [ "$(block_line '^class [A-Za-z_]*\(OptionsFlow\)' CONF_SHIP_LOGS_TO_CLICKSTACK "$INTEGRATION/config_flow.py")" != 0 ] \
    || die "the options flow in $INTEGRATION/config_flow.py no longer offers CONF_SHIP_LOGS_TO_CLICKSTACK - users cannot opt in to log shipping. See AGENTS.md."
  info "log shipper acquired, released and reloaded from async_setup_entry; options flow offers the opt-in"
}

# Hard gate: aiopowerwall is a HACS-side standing pin that lives only on the
# release branches. Core main has no aiopowerwall entry, and the local-Powerwall
# PR reintroduces an older pin on every cut, so a fresh compose silently
# downgrades the library and breaks local grid import/export. The build gate
# passes green either way (both versions import), so this floor check is the
# only thing that catches it. See AGENTS.md. Assert the composed pin is not
# below the last shipped release's. A latest build sets SHIPPED_FLOOR_TAG
# to the current latest: its older base may trail the newest pre-release's pin.
aiopowerwall_pin_gate() {
  log "Gate: aiopowerwall not downgraded below last shipped release"
  local extract='s/.*"aiopowerwall==\([0-9][0-9.]*\)".*/\1/p'
  local composed last_tag shipped lowest
  composed=$(sed -n "$extract" "$INTEGRATION/manifest.json")
  [ -n "$composed" ] || die "aiopowerwall pin missing from composed $INTEGRATION/manifest.json"
  last_tag=${SHIPPED_FLOOR_TAG:-$(git tag -l 'v*' | sort -V | tail -1)}
  if [ -z "$last_tag" ]; then info "no prior release tag; skipping floor check"; return 0; fi
  shipped=$(git show "$last_tag:$INTEGRATION/manifest.json" 2>/dev/null | sed -n "$extract")
  if [ -z "$shipped" ]; then info "$last_tag pins no aiopowerwall; nothing to floor against"; return 0; fi
  lowest=$(printf '%s\n%s\n' "$shipped" "$composed" | sort -V | head -1)
  [ "$lowest" = "$shipped" ] \
    || die "aiopowerwall==$composed downgrades below last shipped $last_tag ($shipped) - the HACS-side standing pin was overwritten by a PR patch. Restore it and regenerate requirements_all.txt. See AGENTS.md."
  info "aiopowerwall==$composed >= last shipped $shipped ($last_tag)"
}

# Hard gate: manifest.json's issue_tracker sends HA's "report issue" link to
# this fork's tracker. Core's manifest has no such key, so a conflict
# resolution that takes core's side drops it, and hassfest's manifest plugin,
# the one check that reads the key, is skipped here. See AGENTS.md.
issue_tracker_gate() {
  log "Gate: manifest.json issue_tracker names the fork's tracker"
  jq -e --arg url "$ISSUE_TRACKER" '.issue_tracker == $url' "$INTEGRATION/manifest.json" >/dev/null \
    || die "$INTEGRATION/manifest.json issue_tracker is not $ISSUE_TRACKER - HA's report-issue link would point at core. Restore the key. See AGENTS.md."
  info "issue_tracker is $ISSUE_TRACKER"
}

# Print hacs.json floor $1 as a key sort -V orders as core does: 2026.10.0b1
# before 2026.10.0, where plain sort -V puts the beta after it.
floor_sort_key() {
  if [[ "$1" =~ ^(.*[0-9])b([0-9]+)$ ]]; then
    printf '%s.0.%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
  else
    printf '%s.1\n' "$1"
  fi
}

# Hard gate: HACS offers a build to every core at or above its hacs.json floor.
# A PR or conflict resolution that lowers the floor below the last shipped
# release's offers the build to cores it was never tested on, and the build
# gate passes green (it tests whatever floor the tree names). A deliberate
# lowering passes --lower-floor <the composed floor>. A latest build sets
# SHIPPED_FLOOR_TAG to the current latest, as for aiopowerwall_pin_gate.
hacs_floor_gate() {
  log "Gate: hacs.json floor not below last shipped release"
  local composed last_tag shipped lowest
  composed=$(jq -r '.homeassistant // ""' hacs.json)
  [ -n "$composed" ] || die "hacs.json declares no homeassistant floor"
  last_tag=${SHIPPED_FLOOR_TAG:-$(git tag -l 'v*' | sort -V | tail -1)}
  if [ -z "$last_tag" ]; then info "no prior release tag; skipping floor check"; return 0; fi
  shipped=$(git show "$last_tag:hacs.json" 2>/dev/null | jq -r '.homeassistant // ""' 2>/dev/null || true)
  if [ -z "$shipped" ]; then info "$last_tag declares no floor; nothing to compare"; return 0; fi
  lowest=$(printf '%s\n%s\n' "$(floor_sort_key "$shipped")" "$(floor_sort_key "$composed")" | sort -V | head -1)
  if [ "$lowest" = "$(floor_sort_key "$shipped")" ]; then
    info "floor $composed >= last shipped $shipped ($last_tag)"
    return 0
  fi
  [ "${LOWER_FLOOR:-}" = "$composed" ] \
    || die "hacs.json floor $composed is below last shipped $last_tag ($shipped) - HACS would offer this build to cores it was not tested on. Restore the floor, or pass --lower-floor $composed to lower it deliberately. See AGENTS.md."
  info "floor $composed lowered below $shipped ($last_tag) by --lower-floor"
}

# Hard gate: a config subentry type declared in code with no translations ships
# as a bare, unlabelled "+" button and an unlabelled setup flow. v6.0.11 shipped
# exactly this - SUBENTRY_TYPE_VEHICLE = "vehicle" was declared, but a compose
# resolving a strings.json conflict kept only the energy_site block and dropped
# every config_subentries.vehicle string. Same failure shape as the vanished
# back-migration: content present upstream and on main, lost at cut time, with a
# green build (no existing gate checks that a declared type has any translations).
# See AGENTS.md. Assert against the composed tree that every SUBENTRY_TYPE_*
# declared in const.py has a non-empty initiate_flow.user - the string the button
# renders - in both strings.json and the separately-compiled translations/en.json.
subentry_translations_gate() {
  log "Gate: declared config subentry types carry translations"
  local const="$INTEGRATION/const.py"
  local strings="$INTEGRATION/strings.json"
  local compiled="$INTEGRATION/translations/en.json"
  [ -f "$const" ] || die "$const missing"

  # Discover declared subentry types by their string value, straight from the
  # composed const.py, so a future third type is covered without editing this gate.
  local types
  types=$(sed -n 's/^SUBENTRY_TYPE_[A-Z0-9_]* *= *"\([^"]*\)".*/\1/p' "$const")
  if [ -z "$types" ]; then
    info "no SUBENTRY_TYPE_* declared in const.py; nothing to check"
    return 0
  fi

  [ -f "$strings" ]  || die "$strings missing but subentry types are declared in const.py"
  [ -f "$compiled" ] || die "$compiled missing but subentry types are declared in const.py"

  local type pair file kind
  while read -r type; do
    [ -n "$type" ] || continue
    # strings.json is the source; translations/en.json is compiled separately, so
    # a block can survive one and not the other - check both.
    for pair in "$strings|strings.json" "$compiled|compiled translations/en.json"; do
      file=${pair%%|*}
      kind=${pair#*|}
      jq -e --arg t "$type" \
        '(.config_subentries[$t].initiate_flow.user) as $u
           | ($u | type == "string") and ($u | length > 0)' \
        "$file" >/dev/null 2>&1 \
        || die "config subentry type '$type' is declared in const.py but has no non-empty config_subentries.$type.initiate_flow.user in $kind.
A declared subentry type without translations renders as a bare unlabelled '+' button and an unlabelled setup flow - v6.0.11 shipped exactly this for 'vehicle'. The block exists upstream and on main; a cut dropped it (likely a strings.json conflict resolved by keeping one side). Restore config_subentries.$type in strings.json and recompile translations; do not hand-edit en.json. See AGENTS.md."
    done
    info "subentry type '$type' labelled in source and compiled strings"
  done <<<"$types"
}

# Lowest Python a requires-python specifier admits (">=3.14.2" -> 3.14.2).
min_python() { sed -n 's/.*>= *\([0-9][0-9.]*\).*/\1/p' <<<"$1"; }

# Fetch file $2 of core ref $1 into $3. On failure prints why on stdout and
# returns 1, telling a ref that does not exist (404) from a network failure.
fetch_core_file() {
  local ref="$1" path="$2" dest="$3" code
  code=$(curl -sSL --retry 2 --max-time 60 -o "$dest" -w '%{http_code}' \
           "https://raw.githubusercontent.com/$CORE_REPO/$ref/$path") \
    || { printf 'could not fetch %s from %s at %s (network failure)' "$path" "$CORE_REPO" "$ref"; return 1; }
  case "$code" in
    200) return 0 ;;
    404) printf '%s has no tag or ref %s (HTTP 404 for %s there)' "$CORE_REPO" "$ref" "$path"; return 1 ;;
    *)   printf 'HTTP %s fetching %s from %s at %s' "$code" "$path" "$CORE_REPO" "$ref"; return 1 ;;
  esac
}

# Resolve requirements file $1 under constraints file $2 for Python $3, as a
# resolution only: nothing is installed and the build venv is untouched.
# Returns 0 when it resolves; otherwise prints uv's output and returns 1 for the
# resolver's own verdict ("No solution found") or 2 when uv could not run.
resolve_under_constraints() {
  # --no-config: core's [tool.uv] overrides are dev-tree settings and must not
  # bend this resolution. --python-platform linux: what core runs on, whatever
  # the operator's machine is.
  local out rc=0
  out=$(uv pip compile --no-config --quiet --python-version "$3" --python-platform linux \
          -c "$2" -o "$2.resolved" "$1" 2>&1) || rc=$?
  [ "$rc" -eq 0 ] && return 0
  printf '%s\n' "$out"
  grep -q 'No solution found' <<<"$out" || return 2
  # uv folds a constraint into whichever requirement it narrows, so its
  # explanation can name a core pin as if a dependency declared it. List the
  # core pins on every package it mentions so the real conflict is readable.
  local names pins
  names=$(grep -oE '[A-Za-z0-9][A-Za-z0-9._-]*(==|>=|<=|~=|!=|<|>)' <<<"$out" \
            | sed -E 's/[=<>~!]+$//' | sort -u | paste -sd'|' -)
  pins=$(grep -iE "^($names)==" "$2" | paste -sd' ' - || true)
  printf 'core constrains: %s\n' "${pins:-(none of the packages named above)}"
  return 1
}

# Preview only: resolve under an arbitrary core ref (e.g. dev) before the
# floor's release exists. It prints its result and always returns 0 - the gate
# reads no status from it and runs the real checks regardless, so a preview can
# never turn a failing or unverified gate into a pass.
preview_core_ref() {
  local reqs="$1" ref="$2" dir="$3" why py detail rc=0
  printf '\n\033[1;33m>>> PREVIEW ONLY (CORE_CONSTRAINTS_PREVIEW_REF=%s): not a release verdict. The gate result below comes only from released core tags.\033[0m\n' "$ref"
  if ! why=$(fetch_core_file "$ref" homeassistant/package_constraints.txt "$dir/preview-constraints.txt"); then
    info "PREVIEW could not run: $why"; return 0
  fi
  if ! why=$(fetch_core_file "$ref" pyproject.toml "$dir/preview-pyproject.toml"); then
    info "PREVIEW could not run: $why"; return 0
  fi
  py=$(min_python "$(sed -n 's/^requires-python *= *"\(.*\)"/\1/p' "$dir/preview-pyproject.toml")")
  if [ -z "$py" ]; then info "PREVIEW could not run: no requires-python in pyproject.toml at $ref"; return 0; fi
  detail=$(resolve_under_constraints "$reqs" "$dir/preview-constraints.txt" "$py") || rc=$?
  case "$rc" in
    0) info "PREVIEW core $ref (python >=$py): resolves" ;;
    1) info "PREVIEW core $ref (python >=$py): NOT INSTALLABLE"; printf '%s\n' "$detail" ;;
    *) info "PREVIEW core $ref (python >=$py) could not run:"; printf '%s\n' "$detail" ;;
  esac
  return 0
}

# Plan the core releases hacs.json floor $1 claims, from PyPI's homeassistant
# release list (saved into dir $2). Prints
# floor-tag|newest|floor requires_python|newest requires_python, where
# floor-tag is the core tag the floor names. On failure prints why and returns 1.
#
# key: [year, month, patch, stage, n] with stage a=0 b=1 rc=2 final=3, which
# sorts as AwesomeVersion does for these forms.
core_release_plan() {
  local floor="$1" dir="$2" plan
  curl -fsSL --retry 2 --max-time 60 -o "$dir/pypi.json" https://pypi.org/pypi/homeassistant/json \
    || { printf 'could not read the homeassistant release list from PyPI'; return 1; }
  plan=$(jq -r --arg floor "$floor" '
    def parse: [capture("^v?(?<y>[0-9]+)\\.(?<m>[0-9]+)(\\.(?<p>[0-9]+))?((?<s>a|b|rc)(?<n>[0-9]+))?$")][0];
    def key: parse | if . == null then null else
      [(.y | tonumber), (.m | tonumber), ((.p // "0") | tonumber),
       ({a: 0, b: 1, rc: 2}[.s // ""] // 3), ((.n // "0") | tonumber)] end;
    def tag: parse | "\(.y | tonumber).\(.m | tonumber).\((.p // "0") | tonumber)\(.s // "")\(.n // "")";
    def py($v): (.[$v] // []) | map(.requires_python // empty) | .[0] // "";
    ($floor | key) as $fk
    | if $fk == null then "" else
        ($floor | tag) as $ft
        | [.releases | to_entries[]
            | select(.value | any(.[]; .yanked | not))
            | {v: .key, k: (.key | key)}
            | select(.k != null and .k >= $fk)] as $at
        | ((($at | map(select(.k[3] == 3))) | if length > 0 then . else $at end)
            | max_by(.k) | .v // "") as $new
        | [$ft, $new, (.releases | py($ft)), (.releases | py($new))] | join("|")
      end' "$dir/pypi.json") || { printf "cannot read PyPI's homeassistant release list"; return 1; }
  [ -n "$plan" ] \
    || { printf "hacs.json floor '%s' does not name a core release - expected X.Y or X.Y.Z with an optional aN/bN/rcN pre-release (e.g. 2026.10.0b0). HACS parses other forms too, but none of them has a core tag to verify against." "$floor"; return 1; }
  printf '%s\n' "$plan"
}

# Print the release-notes note naming the Home Assistant floor tag $1. A stable
# floor reads "Requires Home Assistant X.Y"; a pre-release floor (aN/bN/rcN)
# says "beta". Prints nothing when $1 is not a core tag.
floor_requirement_note() {
  local floor_tag="$1" beta=""
  [[ "$floor_tag" =~ ^([0-9]+\.[0-9]+)\.[0-9]+((a|b|rc)[0-9]+)?$ ]] || return 0
  [ -z "${BASH_REMATCH[2]}" ] || beta=" beta"
  printf '> ⚠️ **Requires Home Assistant %s%s**\n>\n> This beta requires Home Assistant %s or newer. HACS will not install it on an older Home Assistant version.\n\n' \
    "${BASH_REMATCH[1]}" "$beta" "$floor_tag"
}

# Print the release-notes compatibility notes the composed build needs, on
# stdout, from its manifest $1 and hacs.json $2:
#   - the Tessie/Tesla Fleet library note, only when the composed tesla-fleet-api
#     pin is ahead of the one the hacs.json floor release ships. The floor is
#     the oldest core HACS will install this build on, so an equal pin there
#     shares the library with the built-in integrations and the note is untrue.
#   - the Home Assistant requirement note, worded as a beta only when the floor
#     names a core pre-release.
# The floor's pin is read from that tag's tesla_fleet/manifest.json: it is the
# requirement core installs for Tesla Fleet, while requirements_all.txt is only
# generated from the manifests (script.gen_requirements_all).
# Any unreadable input stops the cut - the note is never written or dropped on
# a guess. Usable without cutting after `source ./release.sh`:
#   release_compat_note [manifest.json] [hacs.json]
# The body is a subshell so the EXIT trap removes the temp dir on every die.
release_compat_note() (
  local manifest="${1:-$INTEGRATION/manifest.json}" hacs_json="${2:-hacs.json}"
  local fail="cannot decide the release-notes compatibility note"
  local tool
  for tool in curl jq python3; do
    command -v "$tool" >/dev/null 2>&1 || die "$fail: required tool not found: $tool"
  done

  local pin floor
  pin=$(jq -r '.requirements[]? | select(test("^tesla-fleet-api=="))' "$manifest") \
    || die "$fail: cannot read requirements from $manifest"
  [ -n "$pin" ] || die "$fail: $manifest has no tesla-fleet-api==<version> requirement"
  floor=$(jq -r '.homeassistant // empty' "$hacs_json") || die "$fail: cannot read $hacs_json"
  [ -n "$floor" ] || die "$fail: $hacs_json declares no 'homeassistant' floor"

  # Not local: the EXIT trap runs after the function's locals are gone.
  tmp=$(mktemp -d) || die "$fail: mktemp failed"
  trap 'rm -rf "$tmp"' EXIT
  local plan floor_tag why core_pin ahead
  plan=$(core_release_plan "$floor" "$tmp") || die "$fail: $plan"
  floor_tag=${plan%%|*}
  why=$(fetch_core_file "$floor_tag" homeassistant/components/tesla_fleet/manifest.json "$tmp/tesla_fleet.json") \
    || die "$fail: $why. $hacs_json floor $floor names core $floor_tag, whose tesla-fleet-api pin decides the note."
  core_pin=$(jq -r '.requirements[]? | select(test("^tesla-fleet-api=="))' "$tmp/tesla_fleet.json") \
    || die "$fail: cannot read requirements from tesla_fleet/manifest.json at core $floor_tag"
  [ -n "$core_pin" ] || die "$fail: tesla_fleet/manifest.json at core $floor_tag has no tesla-fleet-api==<version> requirement"

  ahead=$(python3 - "${pin#*==}" "${core_pin#*==}" <<'PY'
import sys
from packaging.version import Version
print(int(Version(sys.argv[1]) > Version(sys.argv[2])))
PY
) || die "$fail: cannot compare tesla-fleet-api ${pin#*==} with ${core_pin#*==} (python3 needs the packaging module)"
  info "composed $pin, core $floor_tag ships $core_pin" >&2

  if [ "$ahead" = 1 ]; then
    # shellcheck disable=SC2016  # backticks are Markdown, not command substitution
    printf '> ⚠️ **Compatibility with the built-in Tessie and Tesla Fleet integrations**\n>\n> This beta uses `tesla-fleet-api` %s, newer than the %s that Home Assistant %s ships. The built-in **Tessie** and **Tesla Fleet** integrations share that library, so they may break when this beta runs on Home Assistant versions that ship the older library. Do not run this beta alongside them on those versions.\n\n' \
      "${pin#*==}" "${core_pin#*==}" "$floor_tag"
  fi
  floor_requirement_note "$floor_tag"
)

# Hard gate: the composed requirements must be INSTALLABLE on the core releases
# the build CLAIMS to support. Core installs an integration's requirements under
# its own homeassistant/package_constraints.txt, and the build gate runs against
# dev, whose constraints run ahead of every release - so a pin that only
# resolves on dev passes green and then cannot install, and the integration
# never starts. v6.0.24 shipped exactly this: tesla-fleet-api==1.17.0 needs
# protobuf>=6.33.5 while released core pinned protobuf==6.32.0. This resolution
# is the only thing that catches it. See AGENTS.md.
#
# The claim is the composed hacs.json "homeassistant" floor - the value HACS
# compares the running core against before offering the build - never a
# hard-coded version. Two releases are checked, each under its own tag's
# constraints and its own Python requirement:
#   (a) the floor release itself: the core tag equal to the floor value;
#   (b) the newest released core version at or above the floor, pre-releases
#       counted only while no stable release at or above the floor exists.
# When (a) and (b) are the same tag that is one resolution.
#
# HACS compares with AwesomeVersion (hacs/integration
# custom_components/hacs/utils/version.py and repositories/base.py can_download),
# which parses more forms than core ever tags. The gate accepts the forms that
# name a core release - X.Y or X.Y.Z, an optional leading v, an optional
# aN/bN/rcN pre-release - and orders them as AwesomeVersion does. Anything else
# HACS can parse (.devN, beta0, -beta.0) names no core tag and stops UNVERIFIED.
#
# The release list and each release's requires_python come from PyPI, the index
# the resolution already talks to; core tags each release with the bare version.
#
# Two distinct failures, both stop the cut: "NOT INSTALLABLE" is the resolver's
# verdict on the manifest; "UNVERIFIED" means no verdict could be reached - a
# network or tooling failure, or a floor whose release does not exist yet. A
# missing floor tag never passes and never falls back to stable or dev.
#
# Usable without cutting after `source ./release.sh`:
#   core_constraints_gate [manifest.json] [hacs.json]
# CORE_CONSTRAINTS_PREVIEW_REF=<core ref> adds a preview resolution (see
# preview_core_ref); it is refused outright with --publish (see preflight).
# The body is a subshell so the EXIT trap removes the temp dir on every die.
core_constraints_gate() (
  log "Gate: requirements installable on the core releases hacs.json claims"
  local manifest="${1:-$INTEGRATION/manifest.json}" hacs_json="${2:-hacs.json}"
  local unverified="core constraints UNVERIFIED (no verdict reached - not a dependency conflict)"
  local tool
  for tool in curl jq uv; do
    command -v "$tool" >/dev/null 2>&1 || die "$unverified: required tool not found: $tool"
  done

  local reqs floor
  reqs=$(jq -r '.requirements[]?' "$manifest") || die "$unverified: cannot read requirements from $manifest"
  if [ -z "$reqs" ]; then info "no requirements in $manifest; nothing to resolve"; return 0; fi
  floor=$(jq -r '.homeassistant // empty' "$hacs_json") || die "$unverified: cannot read $hacs_json"
  [ -n "$floor" ] \
    || die "$unverified: $hacs_json declares no 'homeassistant' floor, so the build claims every core release and there is nothing to verify it against"

  # Not local: the EXIT trap runs after the function's locals are gone.
  tmp=$(mktemp -d) || die "$unverified: mktemp failed"
  trap 'rm -rf "$tmp"' EXIT
  printf '%s\n' "$reqs" > "$tmp/requirements.in"

  local plan floor_tag newest floor_py newest_py
  plan=$(core_release_plan "$floor" "$tmp") || die "$unverified: $plan"
  IFS='|' read -r floor_tag newest floor_py newest_py <<<"$plan"
  info "hacs.json floor $floor: floor release $floor_tag, newest release at or above it ${newest:-(none yet)}"

  if [ -n "${CORE_CONSTRAINTS_PREVIEW_REF:-}" ]; then
    preview_core_ref "$tmp/requirements.in" "$CORE_CONSTRAINTS_PREVIEW_REF" "$tmp"
  fi

  local refs=("$floor_tag") pys=("$floor_py")
  if [ -n "$newest" ] && [ "$newest" != "$floor_tag" ]; then refs+=("$newest"); pys+=("$newest_py"); fi
  local i ref py why detail rc failed=() report=""
  for i in "${!refs[@]}"; do
    ref=${refs[$i]}
    why=$(fetch_core_file "$ref" homeassistant/package_constraints.txt "$tmp/constraints-$ref.txt") \
      || die "$unverified: $why. $hacs_json claims core $floor and up, so release $ref must exist before this build can be verified - the gate never falls back to stable or dev."
    py=$(min_python "${pys[$i]}")
    [ -n "$py" ] || die "$unverified: PyPI lists no Python requirement for homeassistant==$ref"
    rc=0
    detail=$(resolve_under_constraints "$tmp/requirements.in" "$tmp/constraints-$ref.txt" "$py") || rc=$?
    case "$rc" in
      0) info "homeassistant==$ref (python >=$py): resolves" ;;
      1) failed+=("$ref"); report+=$'\n'"--- homeassistant==$ref (python >=$py)"$'\n'"$detail" ;;
      *) die "$unverified: uv pip compile reached no resolver verdict under homeassistant==$ref:
$detail" ;;
    esac
  done
  [ "${#failed[@]}" -eq 0 ] \
    || die "requirements in $manifest are NOT INSTALLABLE on core ${failed[*]}, which $hacs_json (floor $floor) claims to support - the integration would fail to start there. Fix the pin (or its library's dependency floor) or raise the floor, and recompose; the dev-form build gate cannot see this.$report"
  info "$(paste -sd' ' - <<<"$reqs") resolve on every checked release"
)

# The fail-stop gates on the composed tree, before the build gate.
run_gates() {
  core_base_gate
  subentry_migration_gate
  aiopowerwall_pin_gate
  subentry_translations_gate
  core_constraints_gate
  beta_migration_gate
  logship_gate
  issue_tracker_gate
  hacs_floor_gate
}

# Zip the composed integration, the release asset, into absolute path $1.
zip_integration() {
  rm -f "$1"
  ( cd "$INTEGRATION" && rm -rf __pycache__ && rm -f ./*.orig && zip -r "$1" ./* >/dev/null )
}

# Step 6: full local build gate - the actual publish gate for this repo.
# Mirrors .github/workflows/teslemetry-test.yml command-for-command. Blocks the
# release on any failure before the approval pause is ever reached.
build_gate() {
  log "Step 6: build gate (blocking)"
  restore_core_base
  [ -d .venv ] || script/setup
  # shellcheck disable=SC1091
  source .venv/bin/activate
  script/setup
  uv pip install -r requirements_all.txt -r requirements_test.txt -r requirements_test_pre_commit.txt
  # --all (not --integration teslemetry): entities inherit services from other
  # platforms whose translations check_translations needs compiled. See AGENTS.md.
  python3 -m script.translations develop --all
  # --skip-plugins manifest: the manifest plugin rejects this fork's HACS-only
  # issue_tracker key as a structural false positive. See AGENTS.md.
  python3 -m script.hassfest --integration-path "$INTEGRATION" --skip-plugins manifest
  ruff check "$INTEGRATION" tests/components/teslemetry
  ruff format --check "$INTEGRATION" tests/components/teslemetry
  pytest tests/components/teslemetry
  deactivate
  info "build gate green"
}

# Steps 7 & 8: approval pause, then publish. A bump cut never auto-publishes; a
# daily run with --publish publishes once every gate has passed (it gets here
# only then) and the release window allows it. A new latest resets the window,
# so a latest run skips that check.
approve_and_publish() {
  if [ "$DAILY" = 1 ]; then
    [ "$LATEST_BUILT" = 1 ] || release_window_guard
    if [ "$PUBLISH" != 1 ]; then
      log "DRY RUN (no --publish flag)"
      info "Every gate passed. With --publish this run would push the dev sync to main, then:"
      if [ "$LATEST_BUILT" = 1 ]; then
        info "tag latest v$LATEST_VERSION (release-$LATEST_VERSION) with this annotation:"
        printf '%s\n' "$LATEST_MSG" | sed 's/^/      /'
      fi
      info "tag v$VERSION with this annotation:"
      daily_tag_message | sed 's/^/      /'
      info "and publish it as the prerelease \"Pre-release v$VERSION\" on $FORK_REPO."
      [ "$LATEST_BUILT" != 1 ] || info "then publish v$LATEST_VERSION as latest \"Release v$LATEST_VERSION\"."
      finish
    fi
    push_gated_sync
    # Latest is tagged first and the pre-release a second later: GitHub lists
    # releases by tag date, so the pre-release stays the newest entry HACS reads.
    if [ "$LATEST_BUILT" = 1 ]; then
      git tag -a "v$LATEST_VERSION" "release-$LATEST_VERSION" -m "$LATEST_MSG"
      sleep 1
    fi
    git tag -a "v$VERSION" -m "$(daily_tag_message)"
    if [ "$LATEST_BUILT" = 1 ]; then
      git push --atomic origin "v$LATEST_VERSION" "v$VERSION"
    else
      git push origin "v$VERSION"
    fi
    zip_integration "$PWD/teslemetry.zip"
    publish_release "Pre-release" "$VERSION" release_notes.txt "$PWD/teslemetry.zip" prerelease
    rm -f teslemetry.zip
    if [ "$LATEST_BUILT" = 1 ]; then
      publish_release "Release" "$LATEST_VERSION" "$LATEST_DIR/release_notes.txt" "$LATEST_DIR/teslemetry.zip" latest
    fi
    finish
  fi

  log "Step 7: approval"
  echo
  info "Version:  v$VERSION"
  info "Applied PRs:"
  if [ "${#APPLIED_PRS[@]}" -eq 0 ]; then info "  (none)"; else printf '      - %s\n' "${APPLIED_PRS[@]}"; fi
  if [ "${#CONFLICTED_PRS[@]}" -gt 0 ]; then
    info "Conflicts resolved during apply: ${CONFLICTED_PRS[*]}"
  fi
  info "Build gate: green (step 6 passed in full)"
  echo

  local answer
  read -r -p "    Type 'publish' to tag & release v$VERSION, anything else aborts: " answer < /dev/tty
  [ "$answer" = "publish" ] || { info "aborted at approval - nothing published"; exit 0; }

  if [ "$PUBLISH" != 1 ]; then
    log "DRY RUN (no --publish flag)"
    info "Approved, but --publish was not passed. Would now:"
    info "  git tag -a v$VERSION && git push origin v$VERSION"
    info "  zip the integration and gh release create/upload v$VERSION on $FORK_REPO (prerelease)"
    info "  git push --set-upstream origin release-$VERSION"
    info "Rerun with --publish to perform the real release."
    exit 0
  fi

  log "Step 8: publish"
  git tag -a "v$VERSION" -m "Release $VERSION"
  git push origin "v$VERSION"
  zip_integration "$PWD/teslemetry.zip"
  publish_release "Beta" "$VERSION" release_notes.txt "$PWD/teslemetry.zip" prerelease
  rm -f teslemetry.zip
}

# Step 8: release the pushed tag v$2 titled "$1 v$2" with notes file $3 and
# asset $4, then push its release branch. $5 "prerelease" or "latest". Latest
# is created with --latest and without --prerelease; nothing flips it later.
publish_release() {
  local title="$1" version="$2" notes="$3" asset="$4" kind="$5"
  log "Publish v$version ($kind)"
  if [ "$kind" = latest ]; then
    gh release create "v$version" -F "$notes" --repo "$FORK_REPO" -t "$title v$version" --latest
  else
    gh release create "v$version" -F "$notes" --repo "$FORK_REPO" -t "$title v$version" --prerelease
  fi
  gh release upload "v$version" "$asset" --repo "$FORK_REPO"

  if [ "$kind" != latest ]; then
    # Guarantee the prerelease flag with a TYPED API PATCH (-F sends a real
    # boolean). Never `gh release edit`, which resets prerelease to false.
    local rel_id
    rel_id=$(gh release view "v$version" --repo "$FORK_REPO" --json databaseId --jq '.databaseId')
    gh api --method PATCH "repos/$FORK_REPO/releases/$rel_id" -F prerelease=true >/dev/null
  fi

  git push --set-upstream origin "release-$version"
  log "Published v$version ($kind) on $FORK_REPO"
}

main() {
  parse_args "$@"
  preflight
  setup_rerere
  if [ "$DAILY" = 1 ]; then
    determine_daily_version
    plan_latest
    if [ "$LATEST_BUILD" = 1 ]; then build_latest; fi
    # Neither change-detection skip applies on a run that builds latest.
    [ "$LATEST_BUILT" = 1 ] || skip_if_inputs_unchanged
  else
    determine_version
  fi
  sync_dev
  create_release_branch
  apply_prs
  if [ "$DAILY" = 1 ] && [ "$LATEST_BUILT" != 1 ]; then skip_if_integration_unchanged; fi
  update_version
  run_gates
  build_gate
  approve_and_publish
}

# Run only when executed, so a harness can source the functions (e.g. to print
# the compose set with list_core_prs / list_fork_prs) without starting a cut.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
