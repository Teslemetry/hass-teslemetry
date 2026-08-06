# Claude Code instructions

This repository is the **HACS beta release** of the Teslemetry integration for Home Assistant. The only code that matters is in `homeassistant/components/teslemetry/`. Everything else is upstream HA core scaffolding for testing.

## Task: build a release

The whole release runs through one committed helper, **`release.sh`** (repo root). The user says **major**, **minor**, or **patch**; you invoke:

```bash
./release.sh <major|minor|patch>            # default: dry run, stops before the real publish
./release.sh <major|minor|patch> --publish  # arms the real tag + GitHub release
```

`release.sh` owns the deterministic HOW and mechanically enforces the gates this file used to trust an operator to remember. This section owns the WHY and the gotchas; the "HACS-only patches that ride `main`", "CI: the clean per-integration gate", and "Conflict resolution guidelines" sections below stay authoritative for the details the script's comments point back to. Do not re-add hand-run step lists here - they drift from the script.

### Where the helper lives and why there

`release.sh` is a **fork-only tracked file at the repo root**, exactly like `.github/workflows/teslemetry-test.yml` and `release.yml`. Core `dev` has no `release.sh`, so the automatic core-`dev` sync never conflicts with or clobbers it, and the CI-strip only deletes paths under `.github/workflows/` - so the helper survives every cut untouched. Keep it there; do not move it under `script/` (that tree is core-synced and a name could collide upstream).

### What the pipeline does, and where it stops for you

It runs the phases the runbook used to spell out - version bump off the latest release; the `sync-dev` merge of `upstream/dev` + CI-strip + **non-force** `git push origin sync-dev:main` (with concurrent-push re-merge/retry); cutting `release-$VERSION`; applying Bre77's open core PRs oldest-to-newest; stamping both manifests; writing `release_notes.txt` (standing compat note prepended verbatim); the full local build gate; then the approval pause and publish. It **never** runs `git checkout main`, rebases, or force-pushes, so it is safe from an isolated worktree.

It pauses and hands control to you at exactly these points; everything else is automatic and fail-stop:

- **Any conflict** - an `upstream/dev` merge conflict, a PR patch that doesn't apply cleanly, or the concurrent-push re-merge. The script prints what to read and resolve, you edit files directly (no `git mergetool`) and `git add` each resolved file **without committing**; the script finishes the commit and re-runs the conflict-marker grep. See "Conflict resolution guidelines" below.
- **The TEMPORARY `quality_scale.yaml` checkpoint** - the script excludes `quality_scale.yaml` from every per-PR patch (it conflicts repeatedly while quality-scale work is in flight), then pauses once for you to write the correct combined final state from the PRs and `git add` it. Retire this checkpoint (and the exclusion in the script) once the quality scale PRs have all merged.
- **The approval pause** - reached only after the build gate passed in full. The script shows the applied PRs, any conflicts resolved, and the green gate, then waits for you to type `publish`. Anything else aborts with nothing published.

### What the gates guarantee (all fail-stop, enforced by the script)

- **Conflict-marker grep after every commit** over the integration + tests - a leaked `<<<<<<<`/`>>>>>>>` stops the release.
- **`device_tracker.py` stable-core compat grep** - asserts `ATTR_LATITUDE`/`ATTR_LONGITUDE` are present and the 2026.8-dev-only `EntityStateAttribute.LATITUDE`/`.LONGITUDE` are absent **from code** (a comment mention is allowed). This is the check v6.0.9 skipped; the build gate can't catch it (the break is stable-core-only). See "HACS-only patches that ride `main`" for the full why.
- **Full build gate**, mirroring `.github/workflows/teslemetry-test.yml` command-for-command (`translations develop --all`, `hassfest --skip-plugins manifest`, `ruff check`/`format --check`, `pytest`) - any failure stops the release before the approval pause is ever reached. This is the real publish gate for this repo; there is no branch-protection required-check (the captain gates at publish).

### Publish safety

Two independent gates guard the real release: the interactive `publish` confirmation **and** the `--publish` flag. Without `--publish`, even an approved run stops at a dry run that prints what it would do - so validating the pipeline never risks a real tag or GitHub release. With both, the script tags `v$VERSION`, zips the integration, runs `gh release create ... --prerelease` + upload, then **guarantees** the prerelease flag with a typed API PATCH (`gh api --method PATCH .../releases/$id -F prerelease=true`; never `gh release edit`, which resets it), and pushes `release-$VERSION`.

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
- **Opt-in ClickStack log shipping** - the `logship` acquire/release block in `async_setup_entry` plus `logship.py`. Shipping has a single durable authorization gate: a per-entry config option (`ship_logs_to_clickstack`, set via the options flow in `config_flow.py`, default off), tracked as a force-count on the per-`hass` `TeslemetryLogShipper` singleton. It is deliberately *not* tied to the live DEBUG log level - that coupling used to silently drop shipping on restart whenever the user's debug-logging choice wasn't "persistent". `TeslemetryLogShipper.is_shipping_authorized()` is the single source of truth. An options-flow update reloads the entry (`_async_update_listener` in `__init__.py`) so the force-count re-derives correctly.
- **`hacs_migrate_subentry_entities`** - transitional back-migration off the v6.0.0/6.0.1 config-subentry layout (entities/devices move from per-subentry back onto the main entry; cloud energy preserved, local Powerwall control gone). Standing until a captain retires it, expected once no installs remain on v6.0.0/6.0.1. Idempotent, so it is safe to keep replaying. Tests in `tests/components/teslemetry/test_migration.py`. Retire the function, its call, its test, and this bullet together.
- **Stable-core `*EntityStateAttribute` compat** (`device_tracker.py`) - **TEMPORARY shim, and a MUST-DO release step no build crew may skip.** v6.0.9 skipped it and shipped broken location/route device_trackers to every stable-core user; that regression is exactly what this step exists to prevent, so treat it as a hard gate, not a nicety.
  - **Every release MUST verify** that `device_tracker.py` imports and uses `ATTR_LATITUDE`/`ATTR_LONGITUDE` (from `homeassistant.const`), and **NEVER** `EntityStateAttribute.LATITUDE`/`.LONGITUDE`. Grep the composed file before tagging: `ATTR_LATITUDE` must be present and `EntityStateAttribute.LATITUDE`/`.LONGITUDE` must be absent from code (it may appear only inside the compat comment). This is the check v6.0.9 missed.
  - **Why it silently breaks:** the dev form arrives automatically via the core-`dev` sync (core PR #176119, 2026-07-09, added the `LATITUDE`/`LONGITUDE` members to the `EntityStateAttribute` StrEnum; core PR #175970 refactors this component onto the typed `*EntityStateAttribute` enums). Those two members are **2026.8-dev-only** and absent on the stable cores HACS users run, so `EntityStateAttribute.LATITUDE` raises `AttributeError` inside `TeslemetryStreamingDeviceTrackerEntity.async_added_to_hass` on every restart - the `location` and `route` device_trackers never register and show unavailable. **Reproduced on both 2026.7.2 and the newest stable 2026.7.3** (both below the `hacs.json` 2025.6.0 floor's stable line). Because the break is on stable only, the release gate (which runs against dev-form core) passes green - the grep above is the only thing that catches it.
  - Leave `media_player.py` (`MediaPlayerEntityStateAttribute.*`) and `update.py` (`UpdateEntityStateAttribute.*`) unchanged - those members already exist on stable; only `LATITUDE`/`LONGITUDE` are dev-only.
  - **When to retire (temporary):** this shim is removable once core **2026.8** (the next major, ~2 weeks out from 2026-07-23) ships stable with the `LATITUDE`/`LONGITUDE` enum members - i.e. once the stable support floor reaches 2026.8. Retire the shim, this MUST-DO step, and this bullet together then.

## CI: the clean per-integration gate

`.github/workflows/teslemetry-test.yml` is the only PR/push CI gate this repo keeps: a fork-owned file that runs `pytest tests/components/teslemetry`, ruff, and hassfest scoped to just the integration, on every PR/push to `main` and push to `release-*`. Treat this job as the pass/fail gate for whether the integration itself is healthy.

Core `dev` carries a much larger `.github/workflows/` set that would otherwise run whole-repo and fail here as fork-irrelevant noise (whole-repo hassfest, prek, workflow/copilot-instructions checks, requirements-lock bots, CodeQL, the HAOS/supervisor `builder`/`wheels` pipelines, translation sync, manual e2e-tests). These are deleted, and `release.sh`'s `sync_dev` strip (`strip_core_ci`, from the same `CORE_CI_PATHS` list) re-deletes them every release so the merge from core `dev` can't bring them back: `ci.yaml`, `validate.yml`, `check-requirements-deterministic.yml`, `check-requirements.lock.yml`, `check-requirements.md`, `codeql.yml`, `translations.yml`, `builder.yml`, `wheels.yml`, `e2e-tests.yml`, `matchers/`. A red check from any of these reappearing means the strip didn't run or missed a path - not a signal about the integration.

Kept alongside `teslemetry-test.yml` because they aren't PR/push CI noise: `release.yml` (HACS-specific - posts the GitHub release to Discord) and the issue-automation bots `detect-duplicate-issues.yml`, `detect-non-english-issues.yml`, `stale.yml`, `lock.yml`, `restrict-task-creation.yml` (manage this fork's own Issues, unrelated to the PR/push gate).

- `manifest.json`'s `issue_tracker` key (pointing at this fork's own issue tracker) is deliberate, but hassfest's `manifest` plugin only permits that key on integrations it treats as "custom" - and it classifies anything under `homeassistant/components/` as core regardless of `--integration-path` scoping, so real hassfest always rejects it here. This is structural, not a bug: the workflow runs hassfest with `--skip-plugins manifest` to avoid a permanent false-positive; everything else hassfest checks still runs.
- Test dependencies: install `requirements_all.txt` + `requirements_test.txt` (+ `requirements_test_pre_commit.txt` for ruff), same as `script/bootstrap`/`ci.yaml` and `release.sh`'s `build_gate`. There is no `requirements_test_all.txt` in this checkout - don't chase it if you see it referenced.
- Before `pytest`, translations must be compiled for **all** integrations (`python3 -m script.translations develop --all`, <1s, no network) or `check_translations` (`tests/components/conftest.py`) fails any test touching a platform teslemetry's entities inherit services from (e.g. `media_player`, `button`) - not just teslemetry itself. `homeassistant/components/*/translations` is gitignored except teslemetry's own, so this is never pre-populated on a fresh checkout; a local worktree with stale generated files from an earlier `--all` run will falsely pass with only `--integration teslemetry` compiled - verify translation-dependent changes against a clean checkout, not a dev worktree.
- Publish gating: this workflow alone can't block `gh release create` - it's a manual command outside any workflow, and this repo doesn't use branch-protection required-checks (captain gates at publish, not via a GitHub repo setting). The actual gate is `release.sh`'s `build_gate`, which runs this same suite locally and stops the release cold on any failure before the approval pause and publish are ever reached.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
