import json
from uuid import UUID

import pytest
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.config_cmd import app

runner = CliRunner()


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    yield config_path


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.sqlite3"
    monkeypatch.setenv("EXPENSE_CACHE", str(cache_path))
    yield cache_path


def test_set_creates_config_on_first_run(tmp_config):
    result = runner.invoke(
        app,
        ["set", "--engine-url", "https://api.example.com", "--token", "ewe_pat_abc"],
    )
    assert result.exit_code == 0, result.output
    assert "Config saved" in result.output

    cfg = config_module.load()
    assert cfg.engine_url == "https://api.example.com"
    assert cfg.token == "ewe_pat_abc"
    assert isinstance(cfg.client_id, UUID)


def test_set_requires_engine_url_on_first_run(tmp_config):
    result = runner.invoke(app, ["set", "--token", "ewe_pat_abc"])
    assert result.exit_code != 0


def test_set_preserves_client_id_on_update(tmp_config):
    runner.invoke(
        app,
        ["set", "--engine-url", "https://api.example.com", "--token", "ewe_pat_abc"],
    )
    first = config_module.load()

    runner.invoke(app, ["set", "--token", "ewe_pat_new"])
    second = config_module.load()

    assert second.client_id == first.client_id
    assert second.token == "ewe_pat_new"
    assert second.engine_url == "https://api.example.com"


def test_set_warns_on_non_pat_token(tmp_config):
    result = runner.invoke(app, ["set", "--engine-url", "https://x.com", "--token", "not_a_pat"])
    assert result.exit_code == 0
    assert "Warning" in result.output or "warning" in result.output.lower()


def test_get_redacts_token_by_default(tmp_config):
    runner.invoke(
        app,
        [
            "set",
            "--engine-url",
            "https://x.com",
            "--token",
            "ewe_pat_verysecret123456",
        ],
    )
    result = runner.invoke(app, ["get"])
    assert result.exit_code == 0
    assert "ewe_pat_" in result.output
    assert "verysecret" not in result.output
    assert "3456" in result.output


def test_get_shows_token_when_flag_passed(tmp_config):
    runner.invoke(
        app,
        [
            "set",
            "--engine-url",
            "https://x.com",
            "--token",
            "ewe_pat_verysecret123",
        ],
    )
    result = runner.invoke(app, ["get", "--show-token"])
    assert result.exit_code == 0
    assert "ewe_pat_verysecret123" in result.output


def test_get_json_mode(tmp_config):
    runner.invoke(
        app,
        [
            "set",
            "--engine-url",
            "https://x.com",
            "--token",
            "ewe_pat_abcdef1234",
        ],
    )
    result = runner.invoke(app, ["get", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["engine_url"] == "https://x.com"
    assert "ewe_pat_" in data["token"]
    assert "abcdef1234" not in data["token"]


def test_get_errors_cleanly_when_no_config(tmp_config):
    result = runner.invoke(app, ["get"])
    assert result.exit_code == 3
    assert "config set" in result.output


def test_clear_with_yes_flag(tmp_config):
    runner.invoke(app, ["set", "--engine-url", "https://x.com"])
    assert tmp_config.exists()

    result = runner.invoke(app, ["clear", "--yes"])
    assert result.exit_code == 0
    assert not tmp_config.exists()


def test_set_token_change_wipes_cache(tmp_config, tmp_cache):
    """A different PAT may be a different user — the replica must not survive (backlog 1.1)."""
    runner.invoke(app, ["set", "--engine-url", "https://x.com", "--token", "ewe_pat_a"])
    tmp_cache.touch()

    result = runner.invoke(app, ["set", "--token", "ewe_pat_b"])
    assert result.exit_code == 0, result.output
    assert "cache cleared" in result.output.lower()
    assert not tmp_cache.exists()


def test_set_engine_url_change_wipes_cache(tmp_config, tmp_cache):
    runner.invoke(app, ["set", "--engine-url", "https://x.com", "--token", "ewe_pat_a"])
    tmp_cache.touch()

    result = runner.invoke(app, ["set", "--engine-url", "https://y.com"])
    assert result.exit_code == 0, result.output
    assert not tmp_cache.exists()


def test_set_main_currency_only_preserves_cache(tmp_config, tmp_cache):
    runner.invoke(app, ["set", "--engine-url", "https://x.com", "--token", "ewe_pat_a"])
    tmp_cache.touch()

    result = runner.invoke(app, ["set", "--main-currency", "PEN"])
    assert result.exit_code == 0, result.output
    assert "cache cleared" not in result.output.lower()
    assert tmp_cache.exists()


def test_set_same_token_preserves_cache(tmp_config, tmp_cache):
    """Re-setting the identical token must not force a pointless cold start."""
    runner.invoke(app, ["set", "--engine-url", "https://x.com", "--token", "ewe_pat_a"])
    tmp_cache.touch()

    result = runner.invoke(app, ["set", "--token", "ewe_pat_a"])
    assert result.exit_code == 0, result.output
    assert tmp_cache.exists()


def test_clear_wipes_cache(tmp_config, tmp_cache):
    runner.invoke(app, ["set", "--engine-url", "https://x.com", "--token", "ewe_pat_a"])
    tmp_cache.touch()

    result = runner.invoke(app, ["clear", "--yes"])
    assert result.exit_code == 0, result.output
    assert "cache cleared" in result.output.lower()
    assert not tmp_cache.exists()


def test_clear_no_file_is_idempotent(tmp_config):
    result = runner.invoke(app, ["clear", "--yes"])
    assert result.exit_code == 0
    assert "No config file to clear" in result.output


def test_clear_without_yes_in_non_tty_errors(tmp_config):
    runner.invoke(app, ["set", "--engine-url", "https://x.com"])

    result = runner.invoke(app, ["clear"])
    assert result.exit_code == 1  # missing confirmation, not CONFIG_MISSING (3)
    assert "non-interactive" in result.output
