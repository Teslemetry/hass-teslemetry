#!/usr/bin/env bash
#
# Reproducible HACS beta release pipeline for hass-teslemetry.
#
# Usage:  ./release.sh <major|minor|patch> [--publish]
#
# This script IS the release process. AGENTS.md's "Task: build a release"
# section documents WHY each step exists and the gotchas behind each gate;
# this file owns HOW. Keep the two in sync when either changes.
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
INTEGRATION="homeassistant/components/teslemetry"
DEVICE_TRACKER="$INTEGRATION/device_tracker.py"
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

# HACS-only standing patches applied on top of the core PR patches. Each rides
# on the tree of an unmerged core PR, so it lives on a fork branch rather than
# an open PR - apply_prs enumerates OPEN PRs and never finds it. Applied by
# apply_standing_patches after apply_prs. A dropped standing patch is a silent
# regression with a green build, the shape that already lost the subentry
# back-migration and the aiopowerwall pin. Add a new one as a single line here.
# Fields: <remote-url>|<branch>|<patch-commit>|<reason>. See AGENTS.md
# ("HACS-only patches that ride main").
STANDING_PATCHES=(
  "https://github.com/Bre77/core|fm/teslemetry-ble-key-storage|7469d6924e3234f1d47dd1aea6cbb0fe4631cbb0|Vehicle BLE key stored under STORAGE_DIR, not the config root - based on #176296's tree"
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
  for arg in "$@"; do
    case "$arg" in
      major|minor|patch) BUMP="$arg" ;;
      --publish)         PUBLISH=1 ;;
      *) die "unknown argument: $arg (usage: ./release.sh <major|minor|patch> [--publish])" ;;
    esac
  done
  [ -n "$BUMP" ] || die "specify one of: major | minor | patch"
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

  for tool in gh yq jq git; do
    command -v "$tool" >/dev/null 2>&1 || die "required tool not found: $tool"
  done
  if [ "$PUBLISH" = 1 ]; then
    command -v zip >/dev/null 2>&1 || die "'zip' required for --publish"
  fi
  info "branch=$branch publish=$PUBLISH"
}

# Step 1: determine and bump the version off the latest published release.
determine_version() {
  log "Step 1: determine version"
  local last major minor patch
  last=$(gh release list --repo "$FORK_REPO" --limit 1 --json tagName --jq '.[0].tagName')
  [ -n "$last" ] || die "could not read latest release tag from $FORK_REPO"
  info "latest release: $last"

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

# Step 4: apply Bre77 open core PRs oldest-to-newest. JUDGMENT checkpoint:
# clean applies auto-commit; any conflict STOPS for manual resolution. Per-PR
# note lines are collected here and written to release_notes.txt in
# update_version - never a tracked file, so `git add -A` can't stage it.
apply_prs() {
  log "Step 4: apply core PR patches"

  APPLIED_PRS=()
  CONFLICTED_PRS=()
  NOTE_LINES=()

  # Oldest-to-newest == ascending PR number (proxy the runbook already uses).
  local prs
  prs=$(gh pr list --repo "$CORE_REPO" --author Bre77 --state open \
        --label "integration: teslemetry" --json number,title \
        --jq 'sort_by(.number)[] | "\(.number)\t\(.title)"')

  if [ -z "$prs" ]; then
    info "no open Bre77 teslemetry PRs to apply"
  else
    local num title
    while IFS=$'\t' read -r num title; do
      [ -n "$num" ] || continue
      log "  PR #$num: $title"
      # TEMPORARY (quality-scale work in progress): keep quality_scale.yaml out
      # of every per-PR patch to avoid repeated conflicts; the combined final
      # state is applied once at the end below. Remove this filter and the
      # end-of-loop checkpoint once the quality scale PRs have all merged.
      if gh pr diff "$num" --patch --repo "$CORE_REPO" \
           | strip_file_from_diff "quality_scale.yaml" \
           | git apply -3; then
        info "applied cleanly"
      else
        CONFLICTED_PRS+=("#$num")
        pause "PR #$num did not apply cleanly. Read its intent (gh pr diff $num --repo $CORE_REPO), edit files to resolve, 'git add' each. Do NOT commit - this script commits."
        assert_no_unmerged
      fi
      # -A (not -am): capture any new files the patch adds (e.g. a new calendar.py).
      git add -A
      git commit -m "#$num: $title" --no-verify >/dev/null
      # Enforce the post-commit marker grep the runbook left to memory.
      assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
      NOTE_LINES+=("[#$num](https://github.com/$CORE_REPO/pull/$num): $title")
      APPLIED_PRS+=("#$num $title")
    done <<<"$prs"
  fi

  # TEMPORARY: apply the combined final quality_scale.yaml once (judgment step).
  pause "quality_scale.yaml was excluded from every patch above. If it changed in any PR, apply the correct combined final state now (read the PRs' final quality_scale.yaml and write it), 'git add' it. Leave it untouched if no PR changed it."
  if ! git diff --cached --quiet; then
    git commit -m "Apply combined quality_scale.yaml" --no-verify >/dev/null
    info "committed combined quality_scale.yaml"
  fi
  assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
}

# Step 4b: apply the HACS-only standing patches (STANDING_PATCHES) on top of the
# core PR patches. Runs after apply_prs because each is based on an unmerged core
# PR's tree. A patch that will not apply STOPS for a human exactly like apply_prs
# - never a soft warning, never a silent skip: a dropped standing patch is the
# regression this step exists to prevent. The one clean skip is when the change
# has already arrived through the dev sync (its core PR merged upstream), which a
# reverse-apply check detects. See AGENTS.md ("HACS-only patches that ride main").
apply_standing_patches() {
  log "Step 4b: apply HACS-only standing patches"

  APPLIED_PATCHES=()

  local entry url branch sha reason
  for entry in ${STANDING_PATCHES[@]+"${STANDING_PATCHES[@]}"}; do
    IFS='|' read -r url branch sha reason <<<"$entry"
    log "  standing patch: $branch ($reason)"

    # An unresolvable remote/branch or a missing patch commit is a hard failure:
    # a standing patch we cannot even fetch must never be silently absent.
    git fetch "$url" "$branch" >/dev/null 2>&1 \
      || die "cannot fetch standing patch '$branch' from $url - remote or branch unresolvable. See AGENTS.md."
    git cat-file -e "$sha^{commit}" 2>/dev/null \
      || die "standing patch commit $sha not found after fetching '$branch' from $url. See AGENTS.md."

    # Already-applied: the change arrived via the dev sync, so the whole patch
    # reverse-applies. Skip cleanly rather than failing on an empty apply.
    if git show "$sha" | git apply --reverse --check >/dev/null 2>&1; then
      info "already present (arrived via dev sync); skipping"
      continue
    fi

    # -3 gives a 3-way merge fallback; on conflict it stages unmerged paths and
    # leaves markers, and we STOP for the human just like apply_prs.
    if git show "$sha" | git apply -3; then
      info "applied"
    else
      pause "Standing patch '$branch' ($sha) did not apply cleanly. Read its intent (git show $sha), edit files to resolve, 'git add' each. Do NOT commit - this script commits."
      assert_no_unmerged
    fi

    # -A: capture any new files the patch adds.
    git add -A
    git commit -m "Standing patch: $branch" --no-verify >/dev/null
    assert_no_conflict_markers "$INTEGRATION" tests/components/teslemetry
    APPLIED_PATCHES+=("$branch ($reason)")
  done

  if [ "${#APPLIED_PATCHES[@]}" -eq 0 ]; then
    info "no standing patches applied (all already present or none configured)"
  fi
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

# Hard gate: the vehicle BLE private key must live under STORAGE_DIR, not the
# user-browsable config root. This is the third HACS-only standing patch (see
# AGENTS.md), applied by apply_standing_patches; it rides on an unmerged core
# PR's tree, so a cut that drops it silently reverts the key to the config root
# with a green build - the same shape that lost the back-migration and the
# aiopowerwall pin. Assert against the composed tree. Retires gracefully: inert
# when the tree carries no vehicle key handling; when it does, the key path must
# resolve under STORAGE_DIR and never the bare config root.
keystore_gate() {
  log "Gate: vehicle BLE key stored under STORAGE_DIR"
  # Detector: does the composed integration handle a vehicle key file at all? If
  # not (pre-BLE tree, or handling removed upstream), the invariant is vacuous.
  if ! git grep -q 'VEHICLE_KEY_FILE' -- "$INTEGRATION"; then
    info "no vehicle BLE key handling in composed tree; gate inert"
    return 0
  fi
  # Regression form: the key file passed to hass.config.path() as the sole
  # argument resolves to the config root. (The LEGACY_ migration source is a
  # deliberate config-root read and does not match this anchor.)
  if git grep -nE 'config\.path\([[:space:]]*VEHICLE_KEY_FILE[[:space:]]*\)' -- "$INTEGRATION"; then
    die "vehicle BLE key path resolves to the config root (above) - it must be hass.config.path(STORAGE_DIR, VEHICLE_KEY_FILE). The HACS-only vehicle BLE key-storage patch was dropped from this cut; re-apply it. See AGENTS.md."
  fi
  # Correct form: joined under STORAGE_DIR.
  git grep -qE 'config\.path\([[:space:]]*STORAGE_DIR[[:space:]]*,[[:space:]]*VEHICLE_KEY_FILE' -- "$INTEGRATION" \
    || die "vehicle BLE key file is referenced but never joined under STORAGE_DIR - the key-storage patch is missing or incomplete; the key must live under STORAGE_DIR, not the config root. See AGENTS.md."
  info "vehicle BLE key path resolves under STORAGE_DIR"
}

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
  info "Standing patches:"
  if [ "${#APPLIED_PATCHES[@]}" -eq 0 ]; then info "  (none applied)"; else printf '      - %s\n' "${APPLIED_PATCHES[@]}"; fi
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
  apply_standing_patches
  update_version
  device_tracker_gate
  subentry_migration_gate
  aiopowerwall_pin_gate
  subentry_translations_gate
  keystore_gate
  build_gate
  approve_and_publish
}

main "$@"
