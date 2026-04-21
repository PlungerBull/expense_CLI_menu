# expense_CLI_menu

The Hands — a Python (Typer) CLI that talks to the [`expense_world_engine`](https://expense-world-engine.onrender.com) via its HTTPS API. Every command is a thin wrapper around one or more engine endpoints; zero business logic lives here.

See [CLAUDE.md](CLAUDE.md) for conventions, [docs/roadmap.md](docs/roadmap.md) for the build plan, and [docs/cli-spec.md](docs/cli-spec.md) for the command surface.

## Install (dev)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
expense --help
```

## Status

Pre-release. CLI work has started at Step 0; the engine is feature-complete.
