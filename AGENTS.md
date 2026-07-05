# Claude Code instructions

This repository is the **HACS beta release** of the Teslemetry integration for Home Assistant. The only code that matters is in `homeassistant/components/teslemetry/`. Everything else is upstream HA core scaffolding for testing.

## Task: build a release

The user will say **major**, **minor**, or **patch**. Follow these steps:

### 1. Determine version

```bash
gh release ls --repo teslemetry/hass-teslemetry --limit 1
```

Parse the current version (e.g. `v0.5.2`) and bump the appropriate segment. Strip the `v` prefix for the version string used in manifest/commits (e.g. `0.6.0`).

### 2. Rebase onto upstream

```bash
git checkout main
git fetch upstream dev
git rebase upstream/dev
git push --force-with-lease
```

### 3. Create release branch

```bash
git checkout -b release-$VERSION
```

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

Write each applied PR to `release_notes.txt` as: `[#$PR_NUMBER](https://github.com/home-assistant/core/pull/$PR_NUMBER): $PR_TITLE`

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
uv pip install -r requirements_test_all.txt
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
git checkout main
git restore .
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
- Integrations with Platinum or Gold level in the Integration Quality Scale reflect a high standard of code quality and maintainability. When looking for examples of something, these are good places to start. The level is indicated in the manifest.json of the integration.
- When reviewing entity actions, do not suggest extra defensive checks for input fields that are already validated by Home Assistant's service/action schemas and entity selection filters. Suggest additional guards only when data bypasses those validators or is transformed into a less-safe form.
- When validation guarantees a dict key exists, prefer direct key access (`data["key"]`) instead of `.get("key")` so contract violations are surfaced instead of silently masked.
- Keep comments concise. Prefer one short line stating the non-obvious constraint, or no comment at all.
- Do not add comments that just restate the code on the following line(s) (e.g. `# Check if initialized` above `if self.initialized:`). Comments should only explain why (non-obvious constraints, surprising behavior, or workarounds), never what. Never add comments that justify a change by referencing what the code looked like before.
- Do not add section or divider comments (e.g. `# --- XYZ Triggers ---`) inside or outside of functions, since those can easily become stale and be misleading.
- When catching exceptions, try-clauses should be as small as possible, i.e. avoid wrapping large blocks of code in a try-clause, and avoid catching exceptions from functions that are not expected to raise them.

## Teslemetry router beta (`fm/teslemetry-router-beta` on the Bre77 fork)

- This branch combines two fork-only features on top of `teslemetry-subentries`: Bluetooth-first vehicle command routing (`tesla_fleet_api.tesla.VehicleRouter`) and local-Powerwall-first energy site command routing (`tesla_fleet_api.tesla.EnergySiteRouter`). Both wrap the cloud API and are never merged upstream — mergeability is not a goal for this branch.
- Both features gained their own `TeslemetryVehicleData.api` / `TeslemetryEnergyData.api` union types (`Vehicle | VehicleRouter`, `EnergySite | EnergySiteRouter`). Every shared entity mixin in `entity.py` (and any platform file — climate/cover/lock/media_player/number/select/switch/update — that redeclares its own `api:` type or a `Callable[[Vehicle, ...], ...]`/`Callable[[EnergySite, ...], ...]` field for a description) must use the widened union too, or mypy's LSP check on multiply-inherited mixins fails. Coordinators keep the narrow `Vehicle`/`EnergySite` type since they always poll the plain cloud client, never the router.
- Both `OAuth2FlowHandler.async_get_supported_subentry_types` implementations return a dict; combine them (don't let one shadow the other) — one entry per subentry type (`vehicle` → `VehicleSubentryFlowHandler`, `energy_site` → `EnergySiteSubentryFlowHandler`).
- `translations/en.json` is gitignored and generated from `strings.json`; a stale copy on disk can make platform tests fail with "entity not found" even though the code and `strings.json` are correct, because `supported_fn` gating passes but the friendly name (hence entity_id) differs. Regenerate it (`script.translations develop --integration teslemetry`) whenever a test fails with a missing entity and `strings.json` changed recently.
