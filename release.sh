#!/usr/bin/env bash
#
# Reproducible HACS beta release pipeline for hass-teslemetry.
#
# Usage:  ./release.sh <major|minor|patch> [--line <major.minor>] [--publish]
#
# This script IS the release process. AGENTS.md's "Task: build a release"
# section documents WHY each step exists and the gotchas behind each gate;
# this file owns HOW. Keep the two in sync when either changes.
#
# A cut composes core dev + every open Bre77 teslemetry PR on core + every open
# teslemetry PR on the staging fork Teslemetry/home-assistant (base dev), core
# PRs first (see apply_prs).
#
# It runs the deterministic steps mechanically and hard-enforces the gates the
# old prose runbook trusted an operator to remember (the device_tracker
# ATTR_LATITUDE compat grep that v6.0.9 missed; the post-commit conflict-marker
# grep; the full local build gate). It STOPS for a human at exactly two kinds
# of checkpoint: an unresolved conflict, and the pre-publish approval pause.
# It never auto-publishes: the real tag/release only runs with --publish AND an
# explicit human "publish" at the approval pause.
#
# Safe to run from an isolated worktree: it never checks out main, never
# rebases, and never force-pushes. Every update to main goes through the
# temporary sync-dev branch delivered with a plain non-force push.

set -euo pipefail

# --- fork remotes / repo -----------------------------------------------------
FORK_REPO="Teslemetry/hass-teslemetry"      # origin: the HACS fork we release
CORE_REPO="home-assistant/core"             # upstream: core, source of PRs/dev
STAGING_REPO="Teslemetry/home-assistant"    # staging fork: PRs awaiting review, layered on top
PR_LIST_LIMIT=200                           # gh pr list page size; filling it dies (see list_open_prs)
INTEGRATION="homeassistant/components/teslemetry"
DEVICE_TRACKER="$INTEGRATION/device_tracker.py"
SENSOR_PY="$INTEGRATION/sensor.py"
SERVICES_PY="$INTEGRATION/services.py"
INIT_PY="$INTEGRATION/__init__.py"
MIGRATION_TEST="tests/components/teslemetry/test_migration.py"

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
  .github/workflows/matchers
)

# --- output helpers ----------------------------------------------------------
log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

# Human checkpoint. Blocks until the operator confirms they have handled what
# the message describes. Reads from the terminal even inside a pipeline.
pause() {
  printf '\n\033[1;33m>>> %s\033[0m\n' "$*"
  read -r -p "    Press Enter to continue, or Ctrl-C to abort: " _ < /dev/tty
}

# --- gate helpers ------------------------------------------------------------

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

# --- steps -------------------------------------------------------------------

parse_args() {
  BUMP=""
  PUBLISH=0
  LINE=""   # optional <major.minor> series selector; empty = derive from tags
  while [ "$#" -gt 0 ]; do
    case "$1" in
      major|minor|patch) BUMP="$1" ;;
      --publish)         PUBLISH=1 ;;
      --line)            shift; [ "$#" -gt 0 ] || die "--line requires a <major.minor> value"; LINE="$1" ;;
      --line=*)          LINE="${1#--line=}" ;;
      *) die "unknown argument: $1 (usage: ./release.sh <major|minor|patch> [--line <major.minor>] [--publish])" ;;
    esac
    shift
  done
  [ -n "$BUMP" ] || die "specify one of: major | minor | patch"
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
  fi
  info "branch=$branch publish=$PUBLISH"
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
  tip=$(git tag -l 'v*' | sort -V | tail -1)
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
  minor_count=$(git tag -l 'v*' \
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
    last=$(git tag -l 'v*' | grep -E "^v${lmaj}\.${lmin}\." | sort -V | tail -1 || true)
    [ -n "$last" ] || die "no 'v${LINE}.*' release tags found - cannot bump the $LINE line off an empty series"
    info "line $LINE selected; latest tag in series: $last"
  else
    # No line given: keep the historical behaviour (bump off the overall latest
    # tag) - but only after asserting the newest line is unambiguous, so a
    # forgotten --line cannot silently hijack a maintenance line.
    require_unambiguous_line
    last=$(git tag -l 'v*' | sort -V | tail -1)
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

# Re-delete the core CI/CD workflows and commit if anything was staged.
# --ignore-unmatch makes it a no-op when upstream didn't touch these paths.
strip_core_ci() {
  git rm -rf --ignore-unmatch "${CORE_CI_PATHS[@]}" >/dev/null 2>&1 || true
  if ! git diff --cached --quiet; then
    git commit -m "Strip core CI/CD workflow noise" --no-verify >/dev/null
    info "stripped core CI/CD workflows"
  fi
}

# Step 2: sync main with upstream dev via a temp branch and a non-force push.
sync_dev() {
  log "Step 2: sync main with upstream dev"
  git fetch origin main
  git fetch upstream dev

  git branch -D sync-dev >/dev/null 2>&1 || true
  git checkout -b sync-dev origin/main

  if ! git merge --no-edit upstream/dev; then
    pause "Merge conflicts from upstream/dev. Edit files to resolve (no mergetool), 'git add' each resolved file. Do NOT commit - this script finishes the merge."
    assert_no_unmerged
    git commit --no-edit --no-verify
  fi
  strip_core_ci
  assert_no_conflict_markers

  # Non-force push with concurrent-push retry: if main moved under us, fold in
  # the new origin/main and retry. Never --force / --force-with-lease.
  local tries=0
  until git push origin sync-dev:main; do
    tries=$((tries + 1))
    [ "$tries" -ge 3 ] && die "push to main rejected $tries times - resolve manually and rerun"
    log "push rejected (main moved) - re-merging origin/main (attempt $tries)"
    git fetch origin main
    if ! git merge --no-edit origin/main; then
      pause "Conflicts merging the newer origin/main. Resolve and 'git add'; do NOT commit."
      assert_no_unmerged
      git commit --no-edit --no-verify
    fi
    strip_core_ci
  done
  info "main synced (non-force push)"
}

# Step 3: cut the release branch off the just-synced state.
create_release_branch() {
  log "Step 3: create release branch"
  git branch -D "release-$VERSION" >/dev/null 2>&1 || true
  git checkout -b "release-$VERSION"
  info "on release-$VERSION"
}

# Remove one file's section from a unified diff read on stdin. Used to hold
# quality_scale.yaml out of per-PR patches (TEMPORARY, see apply_prs).
strip_file_from_diff() {
  local drop="$1"
  awk -v drop="$drop" '
    /^diff --git / { keep = ($0 !~ drop) }
    keep { print }
  '
}

# List open PRs on a repo as a JSON array. Extra args are passed to gh pr list.
# gh defaults to 30 results and truncates silently - that dropped the 8 oldest
# core PRs from one cut - so an explicit limit is set and a result that fills it
# fails loudly instead of composing a partial release.
list_open_prs() {
  local repo="$1"; shift
  local json count
  json=$(gh pr list --repo "$repo" --state open --limit "$PR_LIST_LIMIT" \
           --json number,title,isDraft,files "$@") \
    || die "could not list open PRs on $repo"
  count=$(jq 'length' <<<"$json")
  [ "$count" -lt "$PR_LIST_LIMIT" ] \
    || die "gh pr list on $repo returned $count PRs, the --limit - the list may be truncated. Raise PR_LIST_LIMIT and rerun."
  printf '%s' "$json"
}

# Open Bre77 teslemetry PRs on core, ascending (oldest-to-newest proxy), as
# "number<TAB>title<TAB>draft" lines.
list_core_prs() {
  list_open_prs "$CORE_REPO" --author Bre77 --label "integration: teslemetry" \
    | jq -r 'sort_by(.number)[] | "\(.number)\t\(.title)\t\(.isDraft)"'
}

# Open PRs on the staging fork against its dev that touch the integration or
# its tests, draft or ready, ascending, in the same line format.
list_fork_prs() {
  list_open_prs "$STAGING_REPO" --base dev \
    | jq -r '[.[] | select(any(.files[].path;
               startswith("homeassistant/components/teslemetry/")
               or startswith("tests/components/teslemetry/")))]
             | sort_by(.number)[] | "\(.number)\t\(.title)\t\(.isDraft)"'
}

# Apply one PR as one commit. $1 repo, $2 number, $3 title, $4 draft flag,
# $5 ref prefix ("#" for core, "fork#" for the staging fork). The prefix marks
# the commit subject, the approval summary and the release-notes line.
apply_one_pr() {
  local repo="$1" num="$2" title="$3" draft="$4" ref="$5$2"
  log "  PR $ref: $title"
  # The staging fork's dev can hold commits upstream/dev lacks. Fetch the PR
  # head so the pre-image blobs exist locally and git apply -3 can fall back to
  # a real three-way merge instead of failing outright.
  if [ "$repo" != "$CORE_REPO" ]; then
    git fetch --quiet "https://github.com/$repo" "pull/$num/head" \
      || die "could not fetch $repo pull/$num/head"
  fi
  # TEMPORARY (quality-scale work in progress): keep quality_scale.yaml out
  # of every per-PR patch to avoid repeated conflicts; the combined final
  # state is applied once at the end of apply_prs. Remove this filter and the
  # end-of-loop checkpoint once the quality scale PRs have all merged.
  if gh pr diff "$num" --patch --repo "$repo" \
       | strip_file_from_diff "quality_scale.yaml" \
       | git apply -3; then
    info "applied cleanly"
  else
    CONFLICTED_PRS+=("$ref")
    pause "PR $ref did not apply cleanly. Read its intent (gh pr diff $num --repo $repo), edit files to resolve, 'git add' each. Do NOT commit - this script commits."
    assert_no_unmerged
  fi
  # -A (not -am): capture any new files the patch adds (e.g. a new calendar.py).
  git add -A
  git commit -m "$ref: $title" --no-verify >/dev/null
  # Enforce the post-commit marker grep the runbook left to memory.
  assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
  local status=""
  if [ "$repo" = "$STAGING_REPO" ]; then
    # Fork PRs are staged changes awaiting review; say which state each is in.
    if [ "$draft" = true ]; then status=" (staged, draft)"; else status=" (staged, ready)"; fi
  fi
  NOTE_LINES+=("[$ref](https://github.com/$repo/pull/$num): $title$status")
  APPLIED_PRS+=("$ref $title$status")
}

# Step 4: compose the release on top of synced core dev - every open Bre77
# teslemetry PR on core, then every open teslemetry PR on the staging fork, each
# group oldest-to-newest. JUDGMENT checkpoint: clean applies auto-commit; any
# conflict STOPS for manual resolution. Per-PR note lines are collected here and
# written to release_notes.txt in update_version - never a tracked file, so
# `git add -A` can't stage it.
apply_prs() {
  log "Step 4: apply core and staging-fork PR patches"

  APPLIED_PRS=()
  CONFLICTED_PRS=()
  NOTE_LINES=()

  # Capture both lists before applying anything, so a truncated or failed
  # listing dies before the first commit.
  local core_prs fork_prs
  core_prs=$(list_core_prs)
  fork_prs=$(list_fork_prs)

  local num title draft
  if [ -z "$core_prs" ]; then
    info "no open Bre77 teslemetry PRs on $CORE_REPO to apply"
  else
    while IFS=$'\t' read -r num title draft; do
      [ -n "$num" ] || continue
      apply_one_pr "$CORE_REPO" "$num" "$title" "$draft" "#"
    done <<<"$core_prs"
  fi

  if [ -z "$fork_prs" ]; then
    info "no open teslemetry PRs on $STAGING_REPO (base dev) to apply"
  else
    while IFS=$'\t' read -r num title draft; do
      [ -n "$num" ] || continue
      apply_one_pr "$STAGING_REPO" "$num" "$title" "$draft" "fork#"
    done <<<"$fork_prs"
  fi

  # TEMPORARY: apply the combined final quality_scale.yaml once (judgment step).
  pause "quality_scale.yaml was excluded from every patch above. If it changed in any PR, apply the correct combined final state now (read the PRs' final quality_scale.yaml and write it), 'git add' it. Leave it untouched if no PR changed it."
  if ! git diff --cached --quiet; then
    git commit -m "Apply combined quality_scale.yaml" --no-verify >/dev/null
    info "committed combined quality_scale.yaml"
  fi
  assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
}

# Step 5: stamp version into both manifests and write release_notes.txt.
# release_notes.txt stays untracked: it feeds `gh release create -F`, not a commit.
update_version() {
  log "Step 5: update version and manifests"

  # Standing compatibility note, verbatim, before any per-PR lines.
  cat > release_notes.txt <<'NOTE'
> ⚠️ **Compatibility with the built-in Tessie and Tesla Fleet integrations**
>
> This beta pins a newer `tesla-fleet-api` than the latest released Home Assistant Core version ships. The built-in **Tessie** and **Tesla Fleet** integrations share that library, so this beta is incompatible with them whenever its pinned `tesla-fleet-api` is ahead of the version in the latest core release — which is almost always. Do not run this beta alongside the built-in Tessie or Tesla Fleet integrations.

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

# Hard gate: the stable-core device_tracker compat shim v6.0.9 shipped broken.
# The break is stable-core-only, so the dev-form build gate passes green - this
# grep is the only thing that catches it. See AGENTS.md for the full why.
device_tracker_gate() {
  log "Gate: device_tracker stable-core ATTR_LATITUDE compat"
  [ -f "$DEVICE_TRACKER" ] || die "$DEVICE_TRACKER missing"
  grep -q 'ATTR_LATITUDE'  "$DEVICE_TRACKER" || die "device_tracker.py must import/use ATTR_LATITUDE (not the dev-only enum member)"
  grep -q 'ATTR_LONGITUDE' "$DEVICE_TRACKER" || die "device_tracker.py must import/use ATTR_LONGITUDE (not the dev-only enum member)"
  # Forbidden only in code: the enum members are 2026.8-dev-only and raise
  # AttributeError on the stable cores HACS users run. Allowed inside comments.
  local hits
  hits=$(awk '{ code=$0; sub(/#.*/,"",code);
               if (code ~ /EntityStateAttribute\.(LATITUDE|LONGITUDE)/) print NR": "$0 }' \
             "$DEVICE_TRACKER" || true)
  [ -z "$hits" ] || die "device_tracker.py uses dev-only EntityStateAttribute.LATITUDE/.LONGITUDE in code:
$hits"
  info "ATTR_LATITUDE/ATTR_LONGITUDE present, dev-only enum absent from code"
}

# Hard gate: the stable-core TPMS UnitOfPressure.ATM compat shim v6.0.20
# shipped broken. Core PR #181508 ships four streamed tire-pressure sensors
# using UnitOfPressure.ATM (PressureConverter), but that member is dev-only
# (core PR #178708, first released 2026.10) and raises AttributeError on every
# stable core HACS users run - the break is stable-core-only, so the dev-form
# build gate passes green. This grep is the only thing that catches it. See
# AGENTS.md.
tpms_atm_gate() {
  log "Gate: sensor.py stable-core UnitOfPressure.ATM TPMS compat"
  [ -f "$SENSOR_PY" ] || die "$SENSOR_PY missing"
  # Forbidden only in code: the enum member is 2026.10-dev-only and raises
  # AttributeError on the stable cores HACS users run. Allowed inside comments.
  local hits
  hits=$(awk '{ code=$0; sub(/#.*/,"",code);
               if (code ~ /UnitOfPressure\.ATM/) print NR": "$0 }' \
             "$SENSOR_PY" || true)
  [ -z "$hits" ] || die "$SENSOR_PY uses dev-only UnitOfPressure.ATM in code - the four streamed TPMS sensors will raise AttributeError on stable core:
$hits"
  info "UnitOfPressure.ATM absent from sensor.py code"
}

# Hard gate: services.py must not call async_get with the dev-only
# include_child_devices kwarg. Core PR #178666 added it to teslemetry's own
# service helper on dev; it is absent on every released core, so it raises
# TypeError there and every device-targeted Action fails with "unknown error" -
# and the dev-form build gate passes green because dev has the kwarg. The sync
# from core dev re-introduces it on the exact line every cut. Retire this gate
# when the minimum core floor reaches 2026.9.0 (the kwarg's first release).
services_child_devices_gate() {
  log "Gate: services.py free of dev-only include_child_devices kwarg"
  [ -f "$SERVICES_PY" ] || die "$SERVICES_PY missing"
  # Forbidden only in code; allowed inside a comment explaining the shim.
  local hits
  hits=$(awk '{ code=$0; sub(/#.*/,"",code);
               if (code ~ /include_child_devices/) print NR": "$0 }' \
             "$SERVICES_PY" || true)
  [ -z "$hits" ] || die "$SERVICES_PY passes dev-only include_child_devices to async_get - drop the kwarg (call async_get(device_id)); it raises TypeError on released cores. Re-introduced by the core-dev sync:
$hits"
  info "include_child_devices absent from services.py code"
}

# Hard gate: the HACS-only subentry back-migration silently vanished in v6.0.9
# when the release branches carrying it were never merged back to main - two
# releases shipped without it and nothing noticed, because only a doc sentence
# asserted its existence. See AGENTS.md. Assert against the composed tree that
# the function is defined, actually CALLED from async_setup_entry (a defined-
# but-uncalled migration is exactly as broken as a missing one), and its tests
# ship with it.
subentry_migration_gate() {
  log "Gate: hacs_migrate_subentry_entities present in composed release"
  local fn="hacs_migrate_subentry_entities"
  [ -f "$INIT_PY" ] || die "$INIT_PY missing"
  grep -q "def $fn" "$INIT_PY" \
    || die "$fn not defined in $INIT_PY - the HACS-only subentry back-migration is missing. It silently vanished in v6.0.9; see AGENTS.md."
  # Extract the async_setup_entry body (up to the next top-level def) and
  # confirm the call is inside it - a grep for the name alone passes on a
  # defined-but-never-called function.
  local called
  called=$(awk -v fn="$fn" '
    /^async def async_setup_entry\(/ { inside=1; next }
    inside && /^(async def |def )/   { inside=0 }
    inside && index($0, fn "(")       { found=1 }
    END { print found+0 }
  ' "$INIT_PY")
  [ "$called" = 1 ] \
    || die "$fn is defined but never called from async_setup_entry in $INIT_PY - a defined-but-uncalled migration is as broken as a missing one. See AGENTS.md for the v6.0.9 history."
  [ -f "$MIGRATION_TEST" ] \
    || die "$MIGRATION_TEST missing - the subentry back-migration must ship with its tests. See AGENTS.md."
  info "$fn defined, called from async_setup_entry, tests present"
}

# Hard gate: aiopowerwall is a HACS-side standing pin that lives only on the
# release branches. Core main has no aiopowerwall entry, and the local-Powerwall
# PR reintroduces an older pin on every cut, so a fresh compose silently
# downgrades the library and breaks local grid import/export. The build gate
# passes green either way (both versions import), so this floor check is the
# only thing that catches it. See AGENTS.md. Assert the composed pin is not
# below the last shipped release's.
aiopowerwall_pin_gate() {
  log "Gate: aiopowerwall not downgraded below last shipped release"
  local extract='s/.*"aiopowerwall==\([0-9][0-9.]*\)".*/\1/p'
  local composed last_tag shipped lowest
  composed=$(sed -n "$extract" "$INTEGRATION/manifest.json")
  [ -n "$composed" ] || die "aiopowerwall pin missing from composed $INTEGRATION/manifest.json"
  last_tag=$(git tag -l 'v*' | sort -V | tail -1)
  if [ -z "$last_tag" ]; then info "no prior release tag; skipping floor check"; return 0; fi
  shipped=$(git show "$last_tag:$INTEGRATION/manifest.json" 2>/dev/null | sed -n "$extract")
  if [ -z "$shipped" ]; then info "$last_tag pins no aiopowerwall; nothing to floor against"; return 0; fi
  lowest=$(printf '%s\n%s\n' "$shipped" "$composed" | sort -V | head -1)
  [ "$lowest" = "$shipped" ] \
    || die "aiopowerwall==$composed downgrades below last shipped $last_tag ($shipped) - the HACS-side standing pin was overwritten by a PR patch. Restore it and regenerate requirements_all.txt. See AGENTS.md."
  info "aiopowerwall==$composed >= last shipped $shipped ($last_tag)"
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

# Hard gate: the services.py device-lookup shim (the include_child_devices
# drop) raises ServiceValidationError with translation_key values whose
# exceptions.<key>.message strings live only in strings.json / translations/en.json,
# not in services.py itself. A core-dev sync can resolve services.py correctly
# (keep the shim) while strings.json has no textual conflict and silently takes
# upstream's deletion of those keys, orphaning the shim's error messages with a
# green build. Happened twice (release-6.0.19, release-6.0.20) before landing on
# main. See AGENTS.md. Assert against the composed tree that every
# translation_key="..." raised in services.py has a non-empty
# exceptions.<key>.message in both strings.json and the compiled translations/en.json.
services_exceptions_gate() {
  log "Gate: services.py exception keys carry translations"
  local strings="$INTEGRATION/strings.json"
  local compiled="$INTEGRATION/translations/en.json"
  [ -f "$SERVICES_PY" ] || die "$SERVICES_PY missing"

  local keys
  keys=$(sed -n 's/.*translation_key="\([^"]*\)".*/\1/p' "$SERVICES_PY" | sort -u)
  if [ -z "$keys" ]; then
    info "no translation_key=\"...\" raised in services.py; nothing to check"
    return 0
  fi

  [ -f "$strings" ]  || die "$strings missing but services.py raises translation_key values"
  [ -f "$compiled" ] || die "$compiled missing but services.py raises translation_key values"

  local key pair file kind
  while read -r key; do
    [ -n "$key" ] || continue
    for pair in "$strings|strings.json" "$compiled|compiled translations/en.json"; do
      file=${pair%%|*}
      kind=${pair#*|}
      jq -e --arg k "$key" \
        '(.exceptions[$k].message) as $m | ($m | type == "string") and ($m | length > 0)' \
        "$file" >/dev/null 2>&1 \
        || die "translation_key '$key' is raised in services.py but has no non-empty exceptions.$key.message in $kind.
A core-dev sync can resolve services.py correctly while silently dropping the matching strings.json exceptions entry (no textual conflict), orphaning the shim's error message with a green build. Restore exceptions.$key in strings.json and recompile translations; do not hand-edit en.json. See AGENTS.md."
    done
    info "translation_key '$key' labelled in source and compiled strings"
  done <<<"$keys"
}

# Hard gate: the composed requirements must be INSTALLABLE on the current stable
# Home Assistant. Core installs an integration's requirements under its own
# homeassistant/package_constraints.txt, and the build gate runs against dev,
# whose constraints run ahead of stable - so a pin that only resolves on dev
# passes green and then cannot install on any stable core, and the integration
# never starts. v6.0.24 shipped exactly this: tesla-fleet-api==1.17.0 needs
# protobuf>=6.33.5 while stable pinned protobuf==6.32.0. This resolution is the
# only thing that catches it. See AGENTS.md.
#
# Stable is read from PyPI, not the core repo's "latest" GitHub release: PyPI is
# the index the resolution already talks to (no extra host, no gh auth), its
# info.version is version-ordered and skips pre-releases and yanked builds
# (GitHub's "latest" is date-ordered, so a late patch on an older line would
# win), and the same document carries that release's requires_python. Core tags
# each release with the bare version, so the constraints are fetched at that tag.
#
# Resolution only (uv pip compile): nothing is installed and the build venv is
# untouched. Takes an optional manifest path, so a manifest can be checked
# without cutting - `source ./release.sh`, then e.g.
#   stable_constraints_gate <(git show v6.0.24:$INTEGRATION/manifest.json)
# Two distinct failures: "NOT INSTALLABLE" is the resolver's verdict on the
# manifest; "UNVERIFIED" is a network or tooling failure that says nothing about
# the manifest. Both stop the cut. The body is a subshell so the EXIT trap
# removes the temp dir on every die.
stable_constraints_gate() (
  log "Gate: requirements installable on stable Home Assistant"
  local manifest="${1:-$INTEGRATION/manifest.json}"
  local unverified="stable constraints UNVERIFIED (network or tooling failure, not a dependency conflict)"
  local tool
  for tool in curl jq uv; do
    command -v "$tool" >/dev/null 2>&1 || die "$unverified: required tool not found: $tool"
  done

  local reqs
  reqs=$(jq -r '.requirements[]?' "$manifest") || die "$unverified: cannot read requirements from $manifest"
  if [ -z "$reqs" ]; then info "no requirements in $manifest; nothing to resolve"; return 0; fi

  # Latest stable release and the Python it requires, never dev and never a
  # hard-coded version. The regex refuses a pre-release rather than trust PyPI.
  local pypi stable requires py
  pypi=$(curl -fsSL --retry 2 --max-time 60 https://pypi.org/pypi/homeassistant/json) \
    || die "$unverified: could not read the latest homeassistant release from PyPI"
  stable=$(jq -r '.info.version // empty' <<<"$pypi" 2>/dev/null || true)
  requires=$(jq -r '.info.requires_python // empty' <<<"$pypi" 2>/dev/null || true)
  [[ "$stable" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "$unverified: PyPI's latest homeassistant version is not a stable release: '$stable'"
  py=$(sed -n 's/.*>= *\([0-9][0-9.]*\).*/\1/p' <<<"$requires")
  [ -n "$py" ] || die "$unverified: no minimum Python in homeassistant==$stable requires_python '$requires'"

  # Not local: the EXIT trap runs after the function's locals are gone.
  tmp=$(mktemp -d) || die "$unverified: mktemp failed"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL --retry 2 --max-time 60 -o "$tmp/constraints.txt" \
    "https://raw.githubusercontent.com/$CORE_REPO/$stable/homeassistant/package_constraints.txt" \
    || die "$unverified: could not fetch homeassistant/package_constraints.txt from $CORE_REPO at tag $stable"
  printf '%s\n' "$reqs" > "$tmp/requirements.in"

  # --no-config: core's [tool.uv] overrides are dev-tree settings and must not
  # bend this resolution. --python-platform linux: what stable core runs on,
  # whatever the operator's machine is.
  local out rc=0
  out=$(uv pip compile --no-config --quiet --python-version "$py" --python-platform linux \
          -c "$tmp/constraints.txt" -o "$tmp/resolved.txt" "$tmp/requirements.in" 2>&1) || rc=$?
  if [ "$rc" -ne 0 ]; then
    grep -q 'No solution found' <<<"$out" \
      || die "$unverified: uv pip compile exited $rc without a resolver verdict:
$out"
    # uv folds a constraint into whichever requirement it narrows, so its
    # explanation can name a stable pin as if a dependency declared it. List the
    # stable pins on every package it mentions so the real conflict is readable.
    local names pins
    names=$(grep -oE '[A-Za-z0-9][A-Za-z0-9._-]*(==|>=|<=|~=|!=|<|>)' <<<"$out" \
              | sed -E 's/[=<>~!]+$//' | sort -u | paste -sd'|' -)
    pins=$(grep -iE "^($names)==" "$tmp/constraints.txt" | paste -sd' ' - || true)
    die "requirements in $manifest are NOT INSTALLABLE on stable Home Assistant $stable (python >=$py) - the integration would fail to start on every stable core. Fix the pin (or its library's dependency floor) and recompose; the dev-form build gate cannot see this.
$out
homeassistant==$stable constrains: ${pins:-(none of the packages named above)}"
  fi
  info "$(paste -sd' ' - <<<"$reqs") resolve under homeassistant==$stable constraints (python >=$py)"
)

# Step 6: full local build gate - the actual publish gate for this repo.
# Mirrors .github/workflows/teslemetry-test.yml command-for-command. Blocks the
# release on any failure before the approval pause is ever reached.
build_gate() {
  log "Step 6: build gate (blocking)"
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

# Steps 7 & 8: approval pause, then publish. Never auto-publishes.
approve_and_publish() {
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

  local ans
  read -r -p "    Type 'publish' to tag & release v$VERSION, anything else aborts: " ans < /dev/tty
  [ "$ans" = "publish" ] || { info "aborted at approval - nothing published"; exit 0; }

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

  ( cd "$INTEGRATION" && rm -rf __pycache__ && rm -f ./*.orig && zip -r ../../../teslemetry.zip ./* >/dev/null )
  gh release create "v$VERSION" -F release_notes.txt --repo "$FORK_REPO" -t "Beta v$VERSION" --prerelease
  gh release upload "v$VERSION" teslemetry.zip --repo "$FORK_REPO"
  rm -f teslemetry.zip

  # Guarantee the prerelease flag with a TYPED API PATCH (-F sends a real
  # boolean). Never `gh release edit`, which resets prerelease to false.
  local rel_id
  rel_id=$(gh release view "v$VERSION" --repo "$FORK_REPO" --json databaseId --jq '.databaseId')
  gh api --method PATCH "repos/$FORK_REPO/releases/$rel_id" -F prerelease=true >/dev/null

  git push --set-upstream origin "release-$VERSION"
  log "Published v$VERSION (prerelease) on $FORK_REPO"
}

main() {
  parse_args "$@"
  preflight
  determine_version
  sync_dev
  create_release_branch
  apply_prs
  update_version
  device_tracker_gate
  tpms_atm_gate
  services_child_devices_gate
  subentry_migration_gate
  aiopowerwall_pin_gate
  subentry_translations_gate
  services_exceptions_gate
  stable_constraints_gate
  build_gate
  approve_and_publish
}

# Run only when executed, so a harness can source the functions (e.g. to print
# the compose set with list_core_prs / list_fork_prs) without starting a cut.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
