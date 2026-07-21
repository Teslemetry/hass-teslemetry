# Claude Code instructions

This repository is the **HACS beta release** of the Teslemetry integration for Home Assistant. The only code that matters is in `homeassistant/components/teslemetry/`. Everything else is upstream HA core scaffolding for testing.

## Task: build a release

The user will say **major**, **minor**, or **patch**. Follow these steps:

### 1. Determine version

```bash
gh release ls --repo teslemetry/hass-teslemetry --limit 1
```

Parse the current version (e.g. `v0.5.2`) and bump the appropriate segment. Strip the `v` prefix for the version string used in manifest/commits (e.g. `0.6.0`).

### Working model: isolated worktree, never check out main

This process runs in an isolated worktree, not the primary checkout. **Never run `git checkout main` anywhere in this process** - `main` is typically checked out in a shared primary clone, and checking it out here dirties that shared clone. Every step that touches `main` goes through a temporary branch, delivered with a plain non-force `git push origin <temp-branch>:main`. Nothing in this process rebases `main` or force-pushes.

### 2. Sync main with upstream dev

`main` tracks home-assistant/core `dev`. This sync is automatic as part of every release build - there is no separate approval PR for it.

```bash
git fetch origin main
git fetch upstream dev
git checkout -b sync-dev origin/main
git merge upstream/dev   # append-only; resolve conflicts by editing files directly, same as step 4
git push origin sync-dev:main
```

- Resolve any merge conflicts the same way as PR conflicts in step 4: read the conflicting files and edit directly, no `git mergetool`.
- The push is a plain non-force push (no `--force` / `--force-with-lease`). If it's rejected as non-fast-forward, someone else pushed to `main` in the meantime - re-fetch `origin/main`, re-merge `upstream/dev` into `sync-dev`, and push again. Never force the push.

You stay on `sync-dev` (now holding the synced state of `main`) for the next step.

### 3. Create release branch

```bash
git checkout -b release-$VERSION
```

Branches off the `sync-dev` state from step 2, so no further checkout is needed. If starting fresh instead (e.g. resuming in a new worktree), use `git fetch origin main && git checkout -b release-$VERSION origin/main` - never `git checkout main` first.

### 4. Apply PR patches

Get the list of open PRs:

```bash
gh pr list --repo home-assistant/core --author Bre77 --state open --label "integration: teslemetry" --json number,title
```

**Ordering**: Apply PRs from oldest to newest. If multiple PRs touch the same files (check with `gh pr diff --name-only`), apply them adjacently to minimize conflicts.

**TEMPORARY**: While quality scale work is in progress, exclude `quality_scale.yaml` from each patch to avoid repeated conflicts. Apply it once at the end of step 4 by reading the final state of all PRs and writing the correct combined result. Remove this workaround once quality scale PRs are all merged.

For each PR, apply its patch:

```bash
gh pr diff $PR_NUMBER --patch --repo home-assistant/core | git apply -3
```

- **If it applies cleanly**: stage and commit with `git commit -am "#$PR_NUMBER: $PR_TITLE" --no-verify`
- **If it conflicts**: resolve by editing files directly (no `git mergetool`):
  1. Run `git status` to find unmerged files
  2. Read each conflicted file and the original PR (`gh pr diff $PR_NUMBER --repo home-assistant/core`) to understand intent
  3. Edit to resolve conflicts, preserving both upstream and PR changes
  4. `git add` resolved files, then `git commit -am "#$PR_NUMBER: $PR_TITLE" --no-verify`

**After every commit**, verify no conflict markers leaked through:

```bash
grep -r "<<<<<<" homeassistant/components/teslemetry/ tests/components/teslemetry/ && echo "CONFLICT MARKERS FOUND - fix before continuing" || echo "Clean"
```

If markers are found, fix them immediately and amend the commit before proceeding to the next PR.

Start `release_notes.txt` with the standing compatibility note below, verbatim, before any per-PR lines:

```
> ⚠️ **Compatibility with the built-in Tessie and Tesla Fleet integrations**
>
> This beta pins a newer `tesla-fleet-api` than the latest released Home Assistant Core version ships. The built-in **Tessie** and **Tesla Fleet** integrations share that library, so this beta is incompatible with them whenever its pinned `tesla-fleet-api` is ahead of the version in the latest core release — which is almost always. Do not run this beta alongside the built-in Tessie or Tesla Fleet integrations.
```

Then write each applied PR to `release_notes.txt` as: `[#$PR_NUMBER](https://github.com/home-assistant/core/pull/$PR_NUMBER): $PR_TITLE`

### 5. Update version and build

```bash
yq -i -o json ".version=\"$VERSION\"" "homeassistant/components/teslemetry/manifest.json"
cp "homeassistant/components/teslemetry/manifest.json" "custom_components/teslemetry/manifest.json"
```

Append to `release_notes.txt`:
```
**Full Changelog**: https://github.com/Teslemetry/hass-teslemetry/commits/v$VERSION
```

Commit: `git commit -am "v$VERSION" --no-verify`

### 6. Run tests

```bash
source .venv/bin/activate
script/setup
uv pip install -r requirements_all.txt -r requirements_test.txt
pytest tests/components/teslemetry
deactivate
```

### 7. Pause for approval

Show the user:
- List of applied PRs and any conflicts that were resolved
- Test results
- Ask for confirmation before publishing

### 8. Publish release

```bash
git tag -a v$VERSION -m "Release $VERSION"
git push origin v$VERSION
cd homeassistant/components/teslemetry && rm -rf __pycache__ && rm -f *.orig && zip -r ../../../teslemetry.zip * && cd ../../..
gh release create v$VERSION -F release_notes.txt --repo Teslemetry/hass-teslemetry -t "Beta v$VERSION"
gh release upload v$VERSION teslemetry.zip --repo Teslemetry/hass-teslemetry
rm teslemetry.zip
git push --set-upstream origin release-$VERSION
```

## Conflict resolution guidelines

When resolving merge conflicts:
- Preserve the intent of both the upstream change and the PR change
- Read the full PR diff to understand what the PR is trying to do
- Follow HA coding conventions: f-strings, type hints, Python 3.13+, American English, sentence case
- Keep try blocks minimal; process data after the try/catch
- Lazy logging: `_LOGGER.debug("Message with %s", variable)` — no periods, no integration name
- Entity names use `_attr_translation_key`, not hardcoded strings
- Formatting is handled by Ruff

**Common conflict patterns**: PRs are based on different upstream commits, so a later PR may revert changes from an earlier one. Watch for:
- A PR re-introducing old code that a previously-applied PR already changed (e.g. reverting translated exceptions back to plain strings)
- Two PRs both creating the same new file (e.g. calendar.py) — combine both into one file with a shared `async_setup_entry`
- Nested conflict markers (`<<<<<<< ours` inside another `<<<<<<< ours`) from three-way merge fallback — always grep after committing

## HACS-only patches that ride `main`

These live only in this HACS tree, never upstream. They are re-applied on top of core `dev` every release and must survive PR application and conflict resolution. All live in `homeassistant/components/teslemetry/__init__.py` unless noted:

- **`beta_migration_fix`** - backfills `auth_implementation` for early beta installs.
- **Opt-in ClickStack log shipping** - the `logship` acquire/release block in `async_setup_entry` plus `logship.py`.
- **`hacs_migrate_subentry_entities`** - transitional back-migration off the v6.0.0/6.0.1 config-subentry layout (entities/devices move from per-subentry back onto the main entry; cloud energy preserved, local Powerwall control gone). Standing until a captain retires it, expected once no installs remain on v6.0.0/6.0.1. Idempotent, so it is safe to keep replaying. Tests in `tests/components/teslemetry/test_migration.py`. Retire the function, its call, its test, and this bullet together.
- **Stable-core `*EntityStateAttribute` compat** (`device_tracker.py`) - core `dev` PR #175970 refactors the component to the typed `*EntityStateAttribute` StrEnums. When that PR is applied during a build, revert only `device_tracker.py`'s `EntityStateAttribute.LATITUDE`/`.LONGITUDE` back to the plain `"latitude"`/`"longitude"` attribute keys (identical enum values): those two members are 2026.8-dev-only and raise `AttributeError` on every restart on stable cores (crash reproduced on 2026.7.2, below the `hacs.json` 2025.6.0 floor's stable line), so the location/route device_trackers never register. Leave `media_player.py` (`MediaPlayerEntityStateAttribute.*`) and `update.py` (`UpdateEntityStateAttribute.*`) unchanged - those members already exist on stable. Retire once the stable support floor includes the 2026.8 enums.

## CI: the clean per-integration gate

`ci.yaml`/`validate.yml`/`builder.yml`/`wheels.yml` etc. are synced whole-repo from upstream core `dev` (see step 2) and mostly fail here as fork-irrelevant noise (whole-repo hassfest, prek, workflow/copilot-instructions checks) - a red check from one of those is not a signal about the teslemetry integration.

`.github/workflows/teslemetry-test.yml` is the real signal: a fork-owned file (never synced/overwritten by the upstream merge) that runs `pytest tests/components/teslemetry`, ruff, and hassfest scoped to just the integration, on every PR/push to `main` and push to `release-*`. Treat this job, not the upstream-noise checks, as the pass/fail gate for whether the integration itself is healthy.

- `manifest.json`'s `issue_tracker` key (pointing at this fork's own issue tracker) is deliberate, but hassfest's `manifest` plugin only permits that key on integrations it treats as "custom" - and it classifies anything under `homeassistant/components/` as core regardless of `--integration-path` scoping, so real hassfest always rejects it here. This is structural, not a bug: the workflow runs hassfest with `--skip-plugins manifest` to avoid a permanent false-positive; everything else hassfest checks still runs.
- Test dependencies: install `requirements_all.txt` + `requirements_test.txt` (+ `requirements_test_pre_commit.txt` for ruff), same as `script/bootstrap`/`ci.yaml` and step 6 above. There is no `requirements_test_all.txt` in this checkout - don't chase it if you see it referenced.
- Before `pytest`, translations must be compiled for **all** integrations (`python3 -m script.translations develop --all`, <1s, no network) or `check_translations` (`tests/components/conftest.py`) fails any test touching a platform teslemetry's entities inherit services from (e.g. `media_player`, `button`) - not just teslemetry itself. `homeassistant/components/*/translations` is gitignored except teslemetry's own, so this is never pre-populated on a fresh checkout; a local worktree with stale generated files from an earlier `--all` run will falsely pass with only `--integration teslemetry` compiled - verify translation-dependent changes against a clean checkout, not a dev worktree.
- Publish gating: this workflow is necessary but not sufficient - the actual `gh release create` (step 8) is a manual command outside any workflow, so nothing here can block it directly. Making this job a **required status check on `main`** (branch protection, a repo setting only a captain can enable) is the intended way to guarantee `release-*` branches are cut from a green `main`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
