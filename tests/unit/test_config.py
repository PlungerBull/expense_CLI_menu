import json
from uuid import uuid4

import pytest

from expense import config
from expense.errors import ConfigInvalidError, ConfigMissingError


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    yield config_path


def test_load_missing_file_returns_none(tmp_config):
    assert config.load() is None


def test_save_and_load_round_trip(tmp_config):
    cfg = config.Config(
        engine_url="https://example.com",
        token="ewe_pat_abc123",
        client_id=uuid4(),
        main_currency="USD",
    )
    config.save(cfg)

    loaded = config.load()
    assert loaded is not None
    assert loaded.engine_url == cfg.engine_url
    assert loaded.token == cfg.token
    assert loaded.client_id == cfg.client_id
    assert loaded.main_currency == cfg.main_currency


def test_save_chmod_600(tmp_config):
    cfg = config.Config(engine_url="https://example.com", client_id=uuid4())
    config.save(cfg)

    mode = tmp_config.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_load_corrupt_json_raises_config_invalid(tmp_config):
    tmp_config.write_text("{not valid json")
    with pytest.raises(ConfigInvalidError, match="not valid JSON") as exc:
        config.load()
    assert "config set" in str(exc.value)


def test_load_schema_invalid_raises_config_invalid(tmp_config):
    # Valid JSON, but missing required fields (engine_url, client_id).
    tmp_config.write_text(json.dumps({"token": "ewe_pat_abc"}))
    with pytest.raises(ConfigInvalidError, match="invalid") as exc:
        config.load()
    assert "config set" in str(exc.value)


def test_clear_removes_file(tmp_config):
    cfg = config.Config(engine_url="https://example.com", client_id=uuid4())
    config.save(cfg)
    assert tmp_config.exists()

    config.clear()
    assert not tmp_config.exists()


def test_clear_no_file_is_noop(tmp_config):
    config.clear()


def test_ensure_loaded_raises_if_missing(tmp_config):
    with pytest.raises(ConfigMissingError) as exc:
        config.ensure_loaded()
    assert "config set" in str(exc.value)


def test_ensure_loaded_returns_loaded_config(tmp_config):
    cfg = config.Config(engine_url="https://example.com", client_id=uuid4())
    config.save(cfg)

    loaded = config.ensure_loaded()
    assert loaded.engine_url == "https://example.com"


def test_client_id_preserved_across_saves(tmp_config):
    original_id = uuid4()
    cfg = config.Config(engine_url="https://a.com", client_id=original_id)
    config.save(cfg)

    loaded = config.load()
    loaded.token = "ewe_pat_new"
    config.save(loaded)

    again = config.load()
    assert again.client_id == original_id


def test_expense_config_env_var_honored(tmp_path, monkeypatch):
    custom = tmp_path / "custom-config-name.json"
    monkeypatch.setenv("EXPENSE_CONFIG", str(custom))

    cfg = config.Config(engine_url="https://x.com", client_id=uuid4())
    config.save(cfg)

    assert custom.exists()
    assert not (tmp_path / ".expense-config").exists()


def test_extra_fields_ignored(tmp_config):
    tmp_config.write_text(
        json.dumps(
            {
                "engine_url": "https://x.com",
                "client_id": str(uuid4()),
                "future_field": "not-a-thing",
            }
        )
    )
    loaded = config.load()
    assert loaded is not None
    assert loaded.engine_url == "https://x.com"
    assert not hasattr(loaded, "future_field")


def test_corrupt_config_renders_clean_cli_error(tmp_config):
    """A corrupt config exits 3 with the recovery hint — no traceback."""
    import typer
    from typer.testing import CliRunner

    from expense.commands.accounts_cmd import app as accounts_app
    from expense.context import AppContext

    cli_app = typer.Typer()

    @cli_app.callback()
    def _root(ctx: typer.Context, no_cache: bool = typer.Option(False, "--no-cache")) -> None:
        ctx.obj = AppContext(no_cache=no_cache)

    cli_app.add_typer(accounts_app, name="accounts")

    tmp_config.write_text("{not valid json")
    runner = CliRunner()
    result = runner.invoke(cli_app, ["--no-cache", "accounts", "list"])
    assert result.exit_code == 3
    assert "not valid JSON" in result.output
    assert "config set" in result.output
    assert "Traceback" not in result.output

    result = runner.invoke(cli_app, ["--no-cache", "accounts", "list", "--json"])
    assert result.exit_code == 3
    envelope = json.loads(result.output)
    assert envelope["error"]["code"] == "CONFIG_INVALID"
