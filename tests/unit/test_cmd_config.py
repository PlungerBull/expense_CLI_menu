import json
from uuid import uuid4

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


def test_set_requires_engine_url_on_first_run(tmp_config):
    result = runner.invoke(app, ["set", "--token", "ewe_pat_abc"])
    assert result.exit_code != 0


def test_set_preserves_untouched_fields_on_update(tmp_config):
    runner.invoke(
        app,
        [
            "set",
            "--engine-url",
            "https://api.example.com",
            "--token",
            "ewe_pat_abc",
            "--main-currency",
            "PEN",
        ],
    )

    runner.invoke(app, ["set", "--token", "ewe_pat_new"])
    second = config_module.load()

    assert second.token == "ewe_pat_new"
    assert second.engine_url == "https://api.example.com"
    assert second.main_currency == "PEN"


def test_set_over_a_legacy_client_id_config(tmp_config):
    """Configs written before the sync deletion still carry client_id — `set`
    must update them, not choke, and must not write the dead key back."""
    tmp_config.write_text(
        json.dumps(
            {
                "engine_url": "https://api.example.com",
                "token": "ewe_pat_old",
                "client_id": str(uuid4()),
            }
        )
    )

    result = runner.invoke(app, ["set", "--token", "ewe_pat_new"])
    assert result.exit_code == 0, result.output
    assert config_module.load().token == "ewe_pat_new"
    assert "client_id" not in json.loads(tmp_config.read_text())


@pytest.mark.parametrize("bad_url", ["example.com", "ftp://example.com", "https://"])
def test_set_rejects_engine_url_without_http_scheme(tmp_config, bad_url):
    """A scheme-less/non-HTTP URL must fail at set time, not on the next command (backlog 3.4)."""
    result = runner.invoke(app, ["set", "--engine-url", bad_url, "--token", "ewe_pat_abc"])
    assert result.exit_code != 0
    assert "scheme" in result.output
    assert config_module.load() is None  # nothing was saved


def test_set_rejects_bad_engine_url_on_update_too(tmp_config):
    runner.invoke(app, ["set", "--engine-url", "https://x.com", "--token", "ewe_pat_abc"])

    result = runner.invoke(app, ["set", "--engine-url", "not-a-url"])
    assert result.exit_code != 0
    assert config_module.load().engine_url == "https://x.com"


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


def test_set_with_corrupt_config_renders_clean_error(tmp_config):
    """A corrupted config file must render on set like it does on get (backlog 3.6)."""
    tmp_config.write_text("{not json")
    result = runner.invoke(app, ["set", "--token", "ewe_pat_abc"])
    assert result.exit_code == 3
    assert "not valid JSON" in result.output
    assert "Traceback" not in result.output


def test_clear_with_yes_flag(tmp_config):
    runner.invoke(app, ["set", "--engine-url", "https://x.com"])
    assert tmp_config.exists()

    result = runner.invoke(app, ["clear", "--yes"])
    assert result.exit_code == 0
    assert not tmp_config.exists()


def test_clear_no_file_is_idempotent(tmp_config):
    result = runner.invoke(app, ["clear", "--yes"])
    assert result.exit_code == 0
    assert "No config file to clear" in result.output


def test_clear_without_yes_in_non_tty_errors(tmp_config):
    runner.invoke(app, ["set", "--engine-url", "https://x.com"])

    result = runner.invoke(app, ["clear"])
    assert result.exit_code == 1  # missing confirmation, not CONFIG_MISSING (3)
    assert "non-interactive" in result.output
