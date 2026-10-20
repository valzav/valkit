# AGENTS.md

Instructions for coding agents working in this repository. `CLAUDE.md` is a symlink to this file.

## Purpose

valkit holds personal utility scripts for day-to-day work. Most utilities are written in Python.

## Layout

```
src/valkit/            # the single installable package
  <utility_name>/      # one subpackage per utility
    __init__.py
    cli.py             # command-line entry point (main function)
tests/                 # pytest tests, mirroring src/valkit/
.data/                 # private input files (gitignored)
.local/                # local scratch, output, and plans (gitignored)
```

## Commands

Run every command through `uv`:

- Install or update the environment: `uv sync`
- Run a utility: `uv run <command-name>`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Type-check: `uv run pyright`
- Test: `uv run pytest`
- Build the nix package: `nix build` (new files must be `git add`ed first; the flake sees only tracked files)

## Adding a utility

1. Create `src/valkit/<utility_name>/` with a `cli.py` that defines `main()`.
2. Register the command in `pyproject.toml` under `[project.scripts]`, using a kebab-case name.
3. Add tests under `tests/<utility_name>/`.
4. Add the utility to the table in `README.md`.
5. Add dependencies with `uv add <package>`. Never edit `uv.lock` by hand.

## Rules

- Never commit, read into tests, or copy anything from `.data/` or `.local/`. These folders hold private data.
- Write test fixtures as small synthetic files under `tests/`.
- Write plans in `.local/plans/<name>.md` before building a non-trivial utility. Plans stay local and are never committed.
- Use the standard library `argparse` for CLIs unless a utility needs more.
- Before claiming a change is done, run lint, format, type-check, and tests. All must pass.
