# Agent instructions

This repository is the **HACS beta release** of the Teslemetry integration for Home Assistant. The only code that matters is in `homeassistant/components/teslemetry/`. Everything else is upstream HA core scaffolding for testing.

## Task: build a release

```bash
./release.sh daily            # dry run: composes, gates and tests; pushes nothing
./release.sh daily --publish  # publishes the pre-release v<UTC Y.M.D>
```

`release.sh` (repo root) **is** the release process and owns the HOW; its header lists the steps. This file owns the WHY and the gotchas. It follows the original single script (`73e316e6680`) and the runbook that replaced it (`1160c4445da`). Keep it that small: add a piece only when a real failure proves it necessary.

`release.sh` is a **fork-only tracked file at the repo root**, like `.github/workflows/teslemetry-test.yml` and `release.yml`. Core `dev` has no `release.sh`. Do not move it under `script/`: that tree is core's and the name could collide upstream.

There is **one channel**. Every build is a GitHub pre-release titled `Pre-release v<version>`, versioned by the UTC date (a second build that day takes `.1`, `.2`, ...). The captain tests a pre-release and promotes it to latest himself (`gh release edit v<version> --repo Teslemetry/hass-teslemetry --prerelease=false --latest`). The script never builds latest and has no major/minor/patch mode.

The systemd timer (`~/tools/hacs-release/hacs-release.sh`) runs `release.sh daily --publish` at 00:00 UTC from a clean `origin/main` checkout, with `PROMOTE_QUEUE` and `RELEASE_RERERE_CACHE` set. Exit 0: published, or the composed integration equals the newest daily tag's (nothing published). Exit 3: a stop that needs a human. Exit 1: a gate or the run failed. Exit 3 and 1 publish nothing.

### What a build composes

On a `release-<version>` branch at the start commit (fork `main` for the timer):

1. **Sync.** Core dev's changes to `homeassistant/components/teslemetry/` and `tests/components/teslemetry/` since `main`'s last sync, as one net diff and one commit `Sync teslemetry from dev <SHA>`. `main`'s last sync is the newest first-parent commit whose subject says `teslemetry from dev <SHA>`. With `--publish`, that commit is fast-forwarded onto `main` before tagging, so each resolution lands on `main` once. Nothing outside the integration and its tests is ever synced from core, so the core CI workflows `main` deletes never return.
2. Every open Bre77 PR on `home-assistant/core` labelled `integration: teslemetry`, ascending. Commit subject `#<N>: <title>`.
3. Every fork PR in the ha-promoter queue file (`PROMOTE_QUEUE`, required), ascending, an entry after its `needs=fork#<N>` base. Commit subject `fork#<N>: <title>`; the release notes mark it `(staged, draft)` or `(staged, ready)`.
4. The release fixups (below).

Each PR applies as its net diff (merge-base to the listed head) with a three-way merge, limited to the integration and its tests: that is all the zip ships, and the tests put every other core path at the floor tag. **TEMPORARY:** `quality_scale.yaml` is left out of every diff, because quality-scale PRs conflict on it repeatedly and Home Assistant never reads it at runtime. Retire the exclusion once the quality-scale PRs have merged.

**No approved PR is skipped silently.** Each queue entry logs one disposition: composed; changes no teslemetry path (not a HACS change); or closed and opened upstream as core PR M ("opened upstream as <core PR URL>" on the fork PR), which the build composes or core dev has merged. Anything else stops the run and names the PR: a closed teslemetry fork PR that was not opened upstream, a promoted PR whose core PR is neither open nor merged, a queued PR whose base is not `dev` with no `needs=fork#<N>`, a `needs=` base that does not resolve, or a PR that does not apply. A malformed queue line fails the run.

A queue line is `<fork PR> [<docs branch>] [needs=core#<N>|needs=fork#<N>]`. A `needs=` PR is built on an unmerged base and ships before the base merges upstream. Its base resolves to a queued open fork PR, a fork PR opened upstream as a core PR this build composes or dev has merged, or such a core PR itself. The PR applies after its base and diffs from its merge-base with the base's head, because re-applying the base's change makes an add/add conflict on every file the base creates.

Both PR lists use `gh pr list --limit 200` (`PR_LIST_LIMIT`), and the run dies if a list fills it: gh's default of 30 truncates silently.

`release-fixups/` holds patches applied after every PR, each as one commit, when every PR its name lists is composed (`fork-60.patch`, `core-<N>+fork-<N>.patch`). A fixup adapts composed PRs to each other (a call to a signature another PR changes) or to the floor release. A PR whose own content changes can make its fixup stop applying; update the fixup on `main`. Delete a fixup once its PRs have merged upstream.

### Stops and conflicts

`git rerere` replays every resolution recorded in `RELEASE_RERERE_CACHE` (the timer's is `~/.local/state/hacs-release/rr-cache`), so only a conflict it has not seen stops. To clear a stop, in a clone whose `RELEASE_RERERE_CACHE` is that cache: run `release.sh daily`, edit each unmerged file at the stop, `git add` it, run `git -c rerere.enabled=true rerere`, check out the start commit again as the stop message says, and rerun. Repeat until the run reaches the tests. Two PRs that apply cleanly but clash in meaning need a release fixup instead. A conflict in the sync can also be resolved for good with a `main` PR whose commit subject says `teslemetry from dev <SHA>`.

### The hacs.json floor release

The zip must run on the core release that `hacs.json`'s `homeassistant` floor names (a full version such as `2026.10.0`). The tests run with every core path outside the integration and its tests restored to that tag (`restore_core_base`), except `homeassistant/generated`: it carries teslemetry's Labs data (`labs.py`), which a HACS install reads from its own manifest. When a merged core PR adds or changes a Labs feature, update `main`'s `labs.py`. `requirements_all.txt` takes the integration's own pins. **TEMPORARY:** dev's teslemetry tests import from `pytest_homeassistant` (`packages/pytest-home-assistant`), which the floor tag predates, so `restore_core_base` writes an untracked alias package (`alias_pytest_homeassistant`); delete it once the floor has the package. `teslemetry-test.yml` runs the same function.

If the integration needs core API newer than the floor, bridge it inside the integration with the API the floor has (see "HACS-only patches"). Never backport core code. The tests fail until the gap is bridged.

Monthly floor bump, after core `X.Y.0` ships: open a PR to `main` that sets the `hacs.json` floor to `X.Y.0`, refresh `main`'s `homeassistant/generated` from that tag (keep teslemetry's `labs.py` block), fix each test failure inside the integration, and retire each compat shim whose retirement condition the new floor meets.

### Gates (fail-stop)

- **Conflict-marker grep** after every commit, over the integration and its tests.
- **`subentry_translations_gate`**: every `SUBENTRY_TYPE_*` in `const.py` has a non-empty `config_subentries.<type>.initiate_flow.user` in `strings.json` and in the separately compiled `translations/en.json`. Nothing else tests it, and a `strings.json` resolution that keeps one side ships an unlabelled `+` button. Fix `strings.json` and recompile; never hand-edit `translations/en.json`.
- **`core_constraints_gate`**: the manifest `requirements` resolve (`uv pip compile`, nothing installed) under `homeassistant/package_constraints.txt` of the floor release and of the newest stable core release, each at its own Python floor. Core installs requirements under those constraints and the tests do not, so a conflicting pin passes the tests and then cannot install. Fix the pin or raise the floor.
- **Release window** (`--publish` only): HACS reads only the 30 newest releases, so the run refuses when 25 or more are newer than latest. Promote a tested pre-release first.
- **Tests on the floor release**, as `teslemetry-test.yml` runs them: translations for all integrations, hassfest, pytest. This is the publish gate; there is no branch-protection required check.

### Publish safety

Without `--publish` the run pushes nothing. `--publish` builds only when the start commit is `origin/main`. It fast-forwards `main` to the sync commit (if `main` moved, the push fails and nothing is published), tags and pushes `v<version>`, zips the integration, runs `gh release create ... --prerelease` and uploads the zip, then pushes `release-<version>`. Release branches are a record of each build and are never merged back.

## Conflict resolution guidelines

- Preserve the intent of both the upstream change and the PR change; read the full PR diff first.
- Follow HA coding conventions: f-strings, type hints, Python 3.13+, American English, sentence case. Keep try blocks minimal; process data after the try/catch. Lazy logging (`_LOGGER.debug("Message with %s", variable)` — no periods, no integration name). Entity names use `_attr_translation_key`, never hardcoded strings. Ruff owns formatting.

PRs are based on different upstream commits, so a later PR may revert an earlier one. Watch for:
- A PR re-introducing old code a previously-applied PR already changed (e.g. reverting translated exceptions back to plain strings).
- Two PRs both creating the same new file — combine them into one file with a shared `async_setup_entry`.
- Nested conflict markers (`<<<<<<< ours` inside another) from three-way merge fallback — always grep after committing.

## HACS-only patches

These live only in this HACS tree, never upstream, and must survive PR application and conflict resolution. They ride `main`, including the TEMPORARY compat shims: the sync conflicts wherever dev changes their lines, so keep the fork's form.

Land every fix on `main`, never only on a `release-*` branch: release branches are never merged back, so a fix made only there is lost from the next build.

- **`beta_migration_fix`** (`__init__.py`) — backfills `auth_implementation` for early beta installs. No dev test sets up such an entry, so a dropped call ships green.
- **Opt-in ClickStack log shipping** — the `logship` acquire/release block in `async_setup_entry` plus `logship.py`. Shipping has a single durable authorization gate: the per-entry config option `ship_logs_to_clickstack` (options flow in `config_flow.py`, default off), tracked as a force-count on the per-`hass` `TeslemetryLogShipper` singleton, with `is_shipping_authorized()` the single source of truth. It is deliberately *not* tied to the live DEBUG log level — that coupling silently drops shipping on restart whenever the user's debug-logging choice isn't "persistent". A change to the option reloads the entry (`_async_setup_option_reload` reloads only on that option, not on every entry update) so the force-count re-derives. The shipper takes the integration's logger name from `LOGGER.name`, never a hardcoded `homeassistant.components.teslemetry`: a HACS install runs as `custom_components.teslemetry`, so a hardcoded name ships nothing.
- **`hacs_migrate_subentry_entities`** (`__init__.py`) — standing cross-version registry normalization for any install that ever ran the entity-parenting subentry layout (v5.2.0, v5.3.0, v6.0.0, v6.0.1). Runs before any inventory or subentry cleanup and moves Teslemetry entities and devices onto the main entry without changing unique IDs or entity IDs, preserving every config-holder subentry and its local-control credentials. Retire only with evidence that no such install can still upgrade directly, removing the function, its call, its tests, and this bullet together.
- **`hacs_remove_empty_holder_subentries`** (`__init__.py`) — removes the unpaired auto-created holder subentries older builds left behind. It MUST run after `hacs_migrate_subentry_entities` in `async_setup_entry`: run first, it removes holders that still own records. Retire with `hacs_migrate_subentry_entities`.
- **Boolean config entry returns** (`__init__.py`) — **TEMPORARY.** `async_setup_entry`, `async_unload_entry` and `async_migrate_entry` return `bool`, and unload calls `async_unload_platforms`, never `async_unload_platforms_or_raise`. The 2026.10.0 floor fails a setup that does not return a boolean and has no `async_unload_platforms_or_raise`. The sync re-introduces dev's form wherever dev changes these lines: keep the fork's form. The tests catch a regression, because every setup test fails. Retire the shim and this bullet together once the floor reaches the first core release where `async_setup_entry` may return `None`.
- **`issue_tracker`** (`manifest.json`) — points HA's "report issue" link at this fork's tracker. Core's manifest has no such key, so a conflict resolution that takes core's side drops it. See also `--skip-plugins manifest` under "CI".
- **Stable-core climate temperature attributes** (`climate.py`) — **TEMPORARY.** The climate entities set `_attr_temperature_unit`, `_attr_current_temperature` and `_attr_target_temperature`, never the `_attr_native_*` forms core dev uses (a compat comment mention is allowed). The 2026.10.0 floor has no `_attr_native_*` climate API, so the native form raises `AttributeError` while HA adds every Teslemetry climate entity, and they show unavailable. `snapshots/test_climate.ambr` carries no `temperature_unit` state attribute for the same reason. The sync re-introduces the native form wherever dev changes these lines: keep the fork's form. The climate tests catch a regression. Retire the shim, the snapshot change, and this bullet together once the floor reaches the first core release with `_attr_native_temperature_unit` on `ClimateEntity`.
- **Stable-core DeviceInfo key access** (`__init__.py`, `config_flow.py`) — **TEMPORARY.** `async_setup_energy_device` sets `energysite.device["model"]` and `["sw_version"]` by key and registers the device with `async_get_or_create(**energysite.device)`, never `async_get_or_create_device`, and `_energy_site_name` reads `energy_data.device.get("name")`, never the attribute form core dev uses (a compat comment mention is allowed). The 2026.10.0 floor's `DeviceInfo` is a `TypedDict` and its device registry has no `async_get_or_create_device`, so dev's form raises `AttributeError` and energy site setup fails. Dev's `DeviceInfo` class still accepts the key form. The sync re-introduces the attribute form wherever dev changes these lines: keep the fork's form. The tests catch a regression, because every energy site setup test fails. Retire the shim and this bullet together once the floor reaches the first core release where `DeviceInfo` is a class and `async_get_or_create_device` exists.

## CI: the clean per-integration gate

`.github/workflows/teslemetry-test.yml` is the only PR/push CI gate this repo keeps: a fork-owned file running `pytest tests/components/teslemetry`, ruff, and integration-scoped hassfest against the `hacs.json` floor release (its first step runs `restore_core_base`) on every PR/push to `main` and push to `release-*`. Treat it as the pass/fail signal for the integration's health.

Core `dev` carries a much larger `.github/workflows/` set that would run whole-repo and fail here as fork-irrelevant noise. `main` deletes it, and `release.sh` syncs only the integration and its tests from core, so it does not return.

Kept alongside `teslemetry-test.yml` because they aren't PR/push CI noise: `release.yml` (posts the GitHub release to Discord) and the issue-automation bots `detect-duplicate-issues.yml`, `detect-non-english-issues.yml`, `stale.yml`, `lock.yml`, `restrict-task-creation.yml`.

- **`--skip-plugins manifest` is structural, not a workaround-of-convenience.** `manifest.json`'s `issue_tracker` key (this fork's own tracker) is deliberate, but hassfest's `manifest` plugin only permits it on integrations it treats as "custom", and it classifies anything under `homeassistant/components/` as core regardless of `--integration-path`. Skipping that one plugin avoids a permanent false positive; everything else hassfest checks still runs.
- **Test dependencies**: `requirements_all.txt` + `requirements_test.txt` (+ `requirements_test_pre_commit.txt` for ruff). There is no `requirements_test_all.txt` in this checkout — don't chase it if you see it referenced.
- **Compile translations for ALL integrations before `pytest`** (`python3 -m script.translations develop --all`, <1s, no network) or `check_translations` (`tests/components/conftest.py`) fails any test touching a platform teslemetry's entities inherit services from (e.g. `media_player`, `button`). `homeassistant/components/*/translations` is gitignored except teslemetry's own, so it is never pre-populated on a fresh checkout; a worktree with stale generated files from an earlier `--all` run falsely passes with only `--integration teslemetry` compiled — verify translation-dependent changes against a clean checkout.
- **This workflow cannot gate publishing** — `gh release create` is a manual command outside any workflow and this repo uses no branch-protection required-checks. The actual gate is `release.sh`'s `build_gate`, which runs the same tests locally before publishing.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Record current facts only — no dated entries, no release/incident history, no narrative.
Prefer rewriting or pruning existing entries over appending new ones, and keep the file bounded.

Editing this file trips the core-synced `gen_copilot_instructions` pre-commit hook, which fails here because this fork deliberately deletes `.github/PULL_REQUEST_TEMPLATE.md`. Commit AGENTS.md changes with `--no-verify`; do not regenerate `.github/copilot-instructions.md`, which is core-synced and would conflict every cut.
