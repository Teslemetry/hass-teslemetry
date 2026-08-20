# Cutting the 6.1 "art of the possible" showcase line

This is the repeatable process for the **6.1 features-preview line**, which is
deliberately **not** built with the normal `release.sh` sync-and-cut flow. Read
this alongside `release.sh` (the normal HACS beta pipeline) and `CLAUDE.md`.

## What the 6.1 line is

A features-preview line published as a GitHub **pre-release** on the HACS beta
channel, the same shape v6.0.x betas ship in. It carries the full Bre77/core
open stack plus follow-up work, refined for this branch. It **does not promise
backwards compatibility** with the core versions those features eventually merge
into: where a choice exists between "best for this branch" and "most mergeable
upstream", 6.1 chooses best for this branch.

The vehicle and Powerwall keys stay in the **config root** (a settled captain
ruling, so the key can be shared with `tesla_fleet`). Do not relocate,
namespace, or migrate them.

## How the branch is based

6.1 is based on the latest **6.0.x release tag** (`v6.0.13` for 6.1.0), not on a
fresh `upstream/dev` sync. That tag already carries the reconciled seven-PR
compose and a full day of cross-PR conflict work, so basing on it inherits that
instead of re-fixing it:

```bash
git checkout -b <work-branch> v6.0.13
```

`release.sh` is a fork-only file that rides `main`; the 6.1 branch adopts the
**current** `release.sh` (with line-aware `--line` selection) so version
resolution and the gates use current tooling even though the tree is v6.0.x.

## Normal-flow steps deliberately SKIPPED (and why)

The normal pipeline is `preflight → determine_version → sync_dev →
create_release_branch → apply_prs → update_version → gates → build_gate →
approve_and_publish`. For 6.1:

- **`sync_dev` — SKIPPED.** It merges `upstream/dev`, strips core CI, and pushes
  `main`. 6.1 is based on the v6.0.13 tree, not a dev sync, and must not pull in
  newer dev that would undo the reconciled compose or the divergent refinements.
- **`create_release_branch` — SKIPPED.** That cuts off the just-synced `main`;
  the 6.1 branch is cut off the v6.0.13 tag instead.
- **`apply_prs` — SKIPPED.** The Bre77 PRs are already composed into v6.0.13.
  6.1 instead **re-takes** the PRs that moved on since the cut, by hand, so their
  current head shape and any superseded compose fixes are reconciled
  deliberately (see the branch's commit history).
- **`update_version` — REPLACED.** It stamps the manifests and auto-writes
  `release_notes.txt` from the PR note lines that `apply_prs` collected. 6.1 runs
  neither, so both the manifest stamp and the release notes are done by hand at
  publish time (below).

## Steps KEPT / reused

- **`determine_version`** with an explicit line: `./release.sh minor --line 6.0`
  bumps the minor off the highest `v6.0.*` tag, i.e. `v6.0.13 → 6.1.0`. The
  `--line 6.0` is **mandatory**: it filters candidate tags to the `v6.0.*` series
  before taking the version-sorted max, so a stray non-semver or newer tag can
  never hijack the number. Confirm it prints `6.1.0` before anything is tagged.
- **The four standing gates** — `device_tracker_gate`, `subentry_migration_gate`,
  `aiopowerwall_pin_gate`, `subentry_translations_gate` — run against the
  composed tree. The gate discipline is what caught the v6.0.11/12 losses; keep
  it even though 6.1 diverges.
- **`build_gate`** — the real publish gate (`translations develop --all`,
  `hassfest --skip-plugins manifest`, `ruff check`/`format --check`, `pytest`).
- **`approve_and_publish`** — the tag / zip / `gh release create --prerelease` /
  typed `PATCH prerelease=true` / push sequence.

## Running the gates without the sync/branch steps

`release.sh` ends in `main "$@"`, so it cannot be sourced as-is. Strip that line,
source the rest, and call the gate functions directly:

```bash
sed '/^main "\$@"$/d' release.sh > /tmp/release_sourceable.sh
for g in device_tracker_gate subentry_migration_gate \
         aiopowerwall_pin_gate subentry_translations_gate; do
  bash -c "source /tmp/release_sourceable.sh; $g" || echo "FAIL: $g"
done
```

Then run the build gate steps (its `.venv`/`uv pip install` bootstrap is the same
as `release.sh`'s `build_gate`):

```bash
source .venv/bin/activate
python3 -m script.translations develop --all
python3 -m script.hassfest --integration-path homeassistant/components/teslemetry --skip-plugins manifest
ruff check homeassistant/components/teslemetry tests/components/teslemetry
ruff format --check homeassistant/components/teslemetry tests/components/teslemetry
pytest tests/components/teslemetry
```

## Publishing (manual, because `update_version` is skipped)

Only after the gates and build gate are green. The version tag is a **plain
`v6.1.0`** (the version tooling parses only `major.minor.patch`, so no
pre-release suffix in the tag) published as a GitHub **pre-release**.

1. **Confirm the version**: `./release.sh minor --line 6.0` resolves to `6.1.0`.
2. **Stamp both manifests** to `6.1.0`:
   ```bash
   yq -i -o json '.version="6.1.0"' homeassistant/components/teslemetry/manifest.json
   cp homeassistant/components/teslemetry/manifest.json custom_components/teslemetry/manifest.json
   git commit -am "v6.1.0" --no-verify
   ```
   Re-run `aiopowerwall_pin_gate` after stamping (it reads the manifest).
3. **Write `release_notes.txt`** by hand (see the draft in the branch report).
   Keep the standing `tesla-fleet-api`/Tessie/Tesla Fleet compatibility note, and
   state the no-backwards-compatibility posture plainly for beta users.
4. **Tag, release (pre-release), and push the release branch**:
   ```bash
   git tag -a v6.1.0 -m "Release 6.1.0"
   git push origin v6.1.0
   ( cd homeassistant/components/teslemetry && rm -rf __pycache__ && rm -f ./*.orig \
       && zip -r ../../../teslemetry.zip ./* >/dev/null )
   gh release create v6.1.0 -F release_notes.txt --repo Teslemetry/hass-teslemetry \
       -t "Beta v6.1.0" --prerelease
   gh release upload v6.1.0 teslemetry.zip --repo Teslemetry/hass-teslemetry
   rm -f teslemetry.zip
   # Guarantee the pre-release flag with a typed API PATCH (never `gh release edit`).
   rel_id=$(gh release view v6.1.0 --repo Teslemetry/hass-teslemetry --json databaseId --jq '.databaseId')
   gh api --method PATCH "repos/Teslemetry/hass-teslemetry/releases/$rel_id" -F prerelease=true
   git push --set-upstream origin release-6.1.0
   ```

## Caveats for the next cut

- A stray non-release tag (`v6013check`) exists on the v6.0.13 tree. It is the
  version-sorted newest `v*` tag, so a **no-line** cut (`release.sh minor` with no
  `--line`) would try to bump off it and die on the semver parse. Always pass
  `--line`. It is harmless to `--line 6.0` (excluded by the `v6.0.*` filter) and
  the `aiopowerwall_pin_gate` floors against its manifest, which is the same
  0.3.0 pin, so the gate passes.
- Never force-push, never `git checkout main`. The whole flow is safe from an
  isolated worktree.
