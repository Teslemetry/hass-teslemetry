# Claude Code instructions

This repository is the **HACS beta release** of the Teslemetry integration for Home Assistant.

## Scope

The only code that matters is in `homeassistant/components/teslemetry/`. Everything else is upstream Home Assistant core scaffolding used for testing.

## Release workflow

New versions are built by `release.sh`, which:
1. Rebases `main` onto `upstream/dev` (home-assistant/core)
2. Applies patches from open PRs on `home-assistant/core` authored by `@Bre77` with the `integration: teslemetry` label
3. Each PR patch is applied with `git apply -3`, which may produce merge conflicts
4. Updates the version in `manifest.json`, runs tests, tags, and publishes a GitHub release

## Conflict resolution

When applying PR patches fails, conflicts typically arise because:
- Upstream `dev` has refactored shared code (entity base classes, coordinator patterns, config entry APIs)
- Multiple PRs touch the same files (commonly `sensor.py`, `binary_sensor.py`, `const.py`, `coordinator.py`, `__init__.py`)
- New entities or keys were added in nearby lines

When resolving conflicts:
- Preserve the intent of both the upstream change and the PR change
- Follow Home Assistant coding conventions (see below)
- Keep try blocks minimal; process data after the try/catch
- Use f-strings, type hints, and Python 3.13+ features
- Use American English, sentence case
- Lazy logging: `_LOGGER.debug("Message with %s", variable)`
- No periods at end of log messages, no integration name in log messages
- Entity names should use `_attr_translation_key`, not hardcoded strings

## Development commands

```bash
source .venv/bin/activate
script/setup
uv pip install -r requirements_test_all.txt
pytest tests/components/teslemetry
```

## HA coding patterns (quick reference)

- **Async**: All external I/O must be async; never block the event loop
- **Error handling**: Use specific exceptions (`ConfigEntryNotReady`, `ConfigEntryAuthFailed`, `UpdateFailed`); bare `except Exception` only in config flows and background tasks
- **Type hints**: Required on all functions and methods
- **Docstrings**: Required on all functions and methods
- **Formatting**: Ruff handles formatting; don't comment on formatting issues
