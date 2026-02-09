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
