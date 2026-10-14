# Contributing

Thanks for helping. Before you open a pull request:

1. Run `make dev`, then `make test`. Ruff, pytest and shellcheck must all pass.
2. Add tests for any gateway change. Security-sensitive paths each need a test that exercises the failing case.
3. If you touched `bin/`, compose or the Containerfiles, run `bin/check` and `bin/compose config -q`. Say which engine you tested with (Docker or Podman).
   If you touched `pyproject.toml` or `SCRIBUS_MCP_VERSION`, run `make lock` and commit `uv.lock` and `containers/*/requirements.txt`.
4. Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
5. Update `docs/` for any behaviour change, and update `memory-bank/` for any decision or change in progress.

Scribus features belong upstream in [caewa/scribus-mcp](https://github.com/caewa/scribus-mcp). This repo only exposes that MCP safely.

Read [AGENTS.md](AGENTS.md) for the layout and the rules.
