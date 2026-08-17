# expense_CLI_menu

The Hands — a Python (Typer) CLI that talks to the `expense_world_engine` over its HTTP API. Since 2026-07-30 that engine runs locally at `http://127.0.0.1:8000` (the Render deployment is mothballed until iOS), so the CLI's only pointer to it is the `engine_url` in `~/.expense-config`. Every command is a thin wrapper around one or more engine endpoints; zero business logic lives here.

See [CLAUDE.md](CLAUDE.md) for conventions, [docs/roadmap.md](docs/roadmap.md) for the build plan and **live status**, [docs/cli-spec.md](docs/cli-spec.md) for the command surface, and [docs/decisions.md](docs/decisions.md) for why the big calls went the way they did.

> **Checkout layout:** the docs link into the engine repo by relative path — clone both as siblings or those links break:
>
> ```
> <anything>/
> ├── expense_world_CLI/      ← this repo
> └── expense_world_engine/   ← engine (specs referenced, not copied)
> ```

## Install (dev)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" -c constraints.txt
```

## Usage

```bash
expense --help    # flat commands
expense world     # interactive TUI
```

## Status

Pre-release. Status has one home: the step table in [docs/roadmap.md](docs/roadmap.md) (TUI detail in [docs/tui-plan.md](docs/tui-plan.md)) — this file deliberately carries no snapshot that can go stale.
