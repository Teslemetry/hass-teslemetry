# Agent instructions

This repository is the **HACS beta release** of the Teslemetry integration for Home Assistant. The only code that matters is in `homeassistant/components/teslemetry/`. Everything else is upstream HA core scaffolding for testing.

## Task: build a release

```bash
./release.sh <major|minor|patch> [--line <major.minor>]            # dry run, stops before publish
./release.sh <major|minor|patch> [--line <major.minor>] --publish  # arms the real tag + GitHub release
```

`release.sh` (repo root) **is** the release process and owns the HOW — read its header comment for the step list. This file owns the WHY and the gotchas. Do not re-add hand-run step lists here; they drift from the script.

`release.sh` is a **fork-only tracked file at the repo root**, like `.github/workflows/teslemetry-test.yml` and `release.yml`. Core `dev` has no `release.sh` and the CI-strip only touches `.github/workflows/`, so the core-`dev` sync never clobbers it. Do not move it under `script/` — that tree is core-synced and the name could collide upstream.

The pipeline runs every phase automatically and fail-stop. It **never** runs `git checkout main`, rebases, or force-pushes, so it is safe from an isolated worktree. It hands control to you at exactly three points:

- **Any conflict** — an `upstream/dev` merge conflict, a PR patch that doesn't apply cleanly, or the concurrent-push re-merge. Edit files directly (no `git mergetool`) and `git add` each resolved file **without committing**; the script finishes the commit and re-runs the conflict-marker grep.
- **The TEMPORARY `quality_scale.yaml` checkpoint** — the script excludes `quality_scale.yaml` from every per-PR patch (it conflicts repeatedly while quality-scale work is in flight) and pauses once for you to write the correct combined final state and `git add` it. Retire the checkpoint and the exclusion together once the quality scale PRs have merged.
- **The approval pause** — reached only after the build gate passed in full. Type `publish`; anything else aborts with nothing published.

### How the release line is selected

Versions bump off the latest release **tag** (`git tag -l 'v*'`, version-sorted). Tags are the durable record even when a release object is deleted (a yanked build whose tag is kept), and are the same source `aiopowerwall_pin_gate` reads.

A bare `sort -V | tail -1` lets a newer preview or minor line hijack an older maintenance line: with a `v6.1.x` tag present, a `6.0.x` maintenance `patch` cut would silently compute a 6.1 number. The line cannot be inferred from the branch being cut — release tags live on `release-*` branches never merged back (so `git tag --merged` finds nothing), `main`'s `custom_components/.../manifest.json` carries no version, and 30-plus historical `major.minor` series rule out "refuse when more than one series exists". So the line is stated explicitly:

- **`--line <major.minor>`** filters candidate tags to that series before taking the `sort -V` max. It names the series you compute **from**: `--line 6.1 patch` advances the 6.1 line; `--line 6.1 minor` births 6.2.0 off it; `--line 6.0 patch` continues 6.0 maintenance.
- **`require_unambiguous_line`** derives ambiguity purely from the tag list — no memory, no clock — and `die`s demanding `--line` when the newest tag is a pre-release (a preview line is open) or more than one minor line exists under the newest tag's major. **Both 6.0.x and 6.1.x are tagged, so this fires on every cut today: `--line` is effectively mandatory.**

The guard is deliberately not full inference — a *cross-major* stable transition (a stable `v7.0.0` while `6.x` is maintained) is undecidable from tags alone, and is caught by the pre-release condition while that line is still in preview. Do not "simplify" the guard back to a bare `sort -V | tail -1`, and do not weaken the parse/bump arithmetic it feeds: the point is that a forgotten flag stops the release loudly instead of shipping the wrong series.

A cut based on a release **tag** inherits that tag's frozen copy of `release.sh`, which may predate current gates and flags. Any tag-based cut MUST adopt `main`'s current `release.sh` before resolving the version or running gates.

### What the gates guarantee (all fail-stop, enforced by the script)

- **Conflict-marker grep after every commit** over the integration + tests.
- **`device_tracker_gate`** — stable-core `ATTR_LATITUDE`/`ATTR_LONGITUDE` compat; see "HACS-only patches" below.
- **`services_child_devices_gate`** — no dev-only `include_child_devices` kwarg; see below.
- **`subentry_migration_gate`** — `hacs_migrate_subentry_entities` defined, called, and its tests present in the composed build.
- **`aiopowerwall_pin_gate`** — the composed pin never drops below the last shipped tag's.
- **`subentry_translations_gate`** — every `SUBENTRY_TYPE_*` value in the composed `const.py` has a non-empty `config_subentries.<type>.initiate_flow.user` (the string the `+` button renders) in both `strings.json` and the separately-compiled `translations/en.json`. Nothing else tests this, so a `strings.json` conflict resolved by keeping one side ships a bare unlabelled button and an unlabelled setup flow with a green build. The block is not HACS-only — a correct cut restores it and this gate proves it did. Never hand-edit `translations/en.json` to satisfy it; fix `strings.json` and recompile. Retire once every declared subentry type's translations land and stay on `main` with no per-cut compose step.
- **Full build gate**, mirroring `.github/workflows/teslemetry-test.yml` command-for-command. This is the real publish gate for this repo; there is no branch-protection required-check.

### Publish safety

Two independent gates guard the real release: the interactive `publish` confirmation **and** the `--publish` flag. Without `--publish`, even an approved run stops at a dry run, so validating the pipeline never risks a real tag or release. With both, the script tags `v$VERSION`, zips the integration, runs `gh release create ... --prerelease` + upload, then **guarantees** the prerelease flag with a typed API PATCH (`gh api --method PATCH .../releases/$id -F prerelease=true`; never `gh release edit`, which resets it), and pushes `release-$VERSION`.

## Conflict resolution guidelines

- Preserve the intent of both the upstream change and the PR change; read the full PR diff first.
- Follow HA coding conventions: f-strings, type hints, Python 3.13+, American English, sentence case. Keep try blocks minimal; process data after the try/catch. Lazy logging (`_LOGGER.debug("Message with %s", variable)` — no periods, no integration name). Entity names use `_attr_translation_key`, never hardcoded strings. Ruff owns formatting.

PRs are based on different upstream commits, so a later PR may revert an earlier one. Watch for:
- A PR re-introducing old code a previously-applied PR already changed (e.g. reverting translated exceptions back to plain strings).
- Two PRs both creating the same new file — combine them into one file with a shared `async_setup_entry`.
- Nested conflict markers (`<<<<<<< ours` inside another) from three-way merge fallback — always grep after committing.

## HACS-only patches

These live only in this HACS tree, never upstream, and must survive PR application and conflict resolution. Some ride `main`; the two TEMPORARY compat shims and the dependency pin are re-composed at cut time, because the core-`dev` sync reverts them to the upstream form.

- **`beta_migration_fix`** (`__init__.py`) — backfills `auth_implementation` for early beta installs.
- **Opt-in ClickStack log shipping** — the `logship` acquire/release block in `async_setup_entry` plus `logship.py`. Shipping has a single durable authorization gate: the per-entry config option `ship_logs_to_clickstack` (options flow in `config_flow.py`, default off), tracked as a force-count on the per-`hass` `TeslemetryLogShipper` singleton, with `is_shipping_authorized()` the single source of truth. It is deliberately *not* tied to the live DEBUG log level — that coupling silently drops shipping on restart whenever the user's debug-logging choice isn't "persistent". A change to the option reloads the entry (`_async_setup_option_reload` reloads only on that option, not on every entry update) so the force-count re-derives.
- **`hacs_migrate_subentry_entities`** (`__init__.py`) — standing cross-version registry normalization for any install that ever ran the entity-parenting subentry layout (v5.2.0, v5.3.0, v6.0.0, v6.0.1). Runs before any inventory or subentry cleanup and moves Teslemetry entities and devices onto the main entry without changing unique IDs or entity IDs, preserving every config-holder subentry and its local-control credentials. Must keep working against both the stable multi-owner and dev single-owner device registries. It is **release-branch-only unless merged back to `main`**: release branches that carry it and are never merged back leave the next cut starting from a `main` that lacks it, silently. `subentry_migration_gate` — not documentation — is what keeps it alive. Retire only with evidence that no such install can still upgrade directly, removing the function, its call, its tests, the gate, and this bullet together.
- **`aiopowerwall` dependency pin** (`manifest.json` + `requirements_all.txt`) — a HACS-side standing minimum, bumped for local grid import/export. Core carries no `aiopowerwall` entry; the local-Powerwall PR introduces it at an older pin, so applying that PR silently **downgrades** the library and breaks grid import/export, and the build gate can't catch it (both versions import cleanly). Every release MUST restore the pin: after applying PRs set `aiopowerwall` in `manifest.json` to at least the last shipped release's version, re-copy the manifest to `custom_components/teslemetry/`, and regenerate requirements (`python3 -m script.gen_requirements_all`). Retire only once the pin lands on `main`, removing the restoration, `aiopowerwall_pin_gate`, and this bullet together.
- **`include_child_devices` drop** (`services.py`, `async_get_device_for_service_call`) — **TEMPORARY.** Core dev calls `device_registry.async_get(device_id, include_child_devices=False)`; the kwarg first ships in core 2026.9.0 and raises `TypeError` on every released core, so all device-targeted Actions fail with a generic "unknown error" while the dev-form build gate stays green. The fork drops the kwarg (`async_get(device_id)`), which is behaviourally identical because Teslemetry never parents devices (it sets only `via_device_id`, which core forbids from being a child), so a targeted device is always a main device — a `cast` keeps the narrow `DeviceEntry` return type. The core-`dev` sync **re-conflicts on this line every cut**: keep the fork's kwarg-less call, never accept upstream's. Retire the drop, `services_child_devices_gate`, and this bullet together once the minimum core floor reaches 2026.9.0.
- **Stable-core `EntityStateAttribute` compat** (`device_tracker.py`) — **TEMPORARY, and a MUST-DO release step.** `device_tracker.py` MUST import and use `ATTR_LATITUDE`/`ATTR_LONGITUDE` from `homeassistant.const` and MUST NEVER reference `EntityStateAttribute.LATITUDE`/`.LONGITUDE` in code (a compat comment mention is allowed). Those enum members are dev-only and absent on the stable cores HACS users run, so referencing them raises `AttributeError` in `TeslemetryStreamingDeviceTrackerEntity.async_added_to_hass` on every restart — the `location` and `route` device_trackers never register and show unavailable. The break is stable-only, so the dev-form build gate passes green; `device_tracker_gate`'s grep is the only thing that catches it. Leave `media_player.py` (`MediaPlayerEntityStateAttribute.*`) and `update.py` (`UpdateEntityStateAttribute.*`) alone — those members exist on stable. Retire the shim, the gate, and this bullet together once stable core ships the `LATITUDE`/`LONGITUDE` members.

## CI: the clean per-integration gate

`.github/workflows/teslemetry-test.yml` is the only PR/push CI gate this repo keeps: a fork-owned file running `pytest tests/components/teslemetry`, ruff, and integration-scoped hassfest on every PR/push to `main` and push to `release-*`. Treat it as the pass/fail signal for the integration's health.

Core `dev` carries a much larger `.github/workflows/` set that would run whole-repo and fail here as fork-irrelevant noise. It is deleted, and `release.sh`'s `strip_core_ci` re-deletes it every cut. Keep this list in sync with `CORE_CI_PATHS` in `release.sh`: `ci.yaml`, `validate.yml`, `check-requirements-deterministic.yml`, `check-requirements.lock.yml`, `check-requirements.md`, `codeql.yml`, `translations.yml`, `builder.yml`, `wheels.yml`, `e2e-tests.yml`, `matchers/`. A red check from any of these means the strip didn't run or missed a path — not a signal about the integration.

Kept alongside `teslemetry-test.yml` because they aren't PR/push CI noise: `release.yml` (posts the GitHub release to Discord) and the issue-automation bots `detect-duplicate-issues.yml`, `detect-non-english-issues.yml`, `stale.yml`, `lock.yml`, `restrict-task-creation.yml`.

- **`--skip-plugins manifest` is structural, not a workaround-of-convenience.** `manifest.json`'s `issue_tracker` key (this fork's own tracker) is deliberate, but hassfest's `manifest` plugin only permits it on integrations it treats as "custom", and it classifies anything under `homeassistant/components/` as core regardless of `--integration-path`. Skipping that one plugin avoids a permanent false positive; everything else hassfest checks still runs.
- **Test dependencies**: `requirements_all.txt` + `requirements_test.txt` (+ `requirements_test_pre_commit.txt` for ruff). There is no `requirements_test_all.txt` in this checkout — don't chase it if you see it referenced.
- **Compile translations for ALL integrations before `pytest`** (`python3 -m script.translations develop --all`, <1s, no network) or `check_translations` (`tests/components/conftest.py`) fails any test touching a platform teslemetry's entities inherit services from (e.g. `media_player`, `button`). `homeassistant/components/*/translations` is gitignored except teslemetry's own, so it is never pre-populated on a fresh checkout; a worktree with stale generated files from an earlier `--all` run falsely passes with only `--integration teslemetry` compiled — verify translation-dependent changes against a clean checkout.
- **This workflow cannot gate publishing** — `gh release create` is a manual command outside any workflow and this repo uses no branch-protection required-checks. The actual gate is `release.sh`'s `build_gate`, which runs the same suite locally before the approval pause.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Record current facts only — no dated entries, no release/incident history, no narrative.
Prefer rewriting or pruning existing entries over appending new ones, and keep the file bounded.

Editing this file trips the core-synced `gen_copilot_instructions` pre-commit hook, which fails here because this fork deliberately deletes `.github/PULL_REQUEST_TEMPLATE.md`. Commit AGENTS.md changes with `--no-verify`; do not regenerate `.github/copilot-instructions.md`, which is core-synced and would conflict every cut.
