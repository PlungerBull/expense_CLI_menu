import json
import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from expense.errors import ConfigMissingError


def config_path() -> Path:
    return Path(os.environ.get("EXPENSE_CONFIG", "~/.expense-config")).expanduser()


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    engine_url: str
    token: str | None = None
    client_id: UUID
    main_currency: str | None = None


def load() -> Config | None:
    path = config_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Config file at {path} is not valid JSON: {exc}") from exc
    return Config.model_validate(raw)


def save(cfg: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = cfg.model_dump(mode="json")

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=".expense-config.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp_path = Path(tmp.name)

    if os.name != "nt":
        os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)


def clear() -> None:
    path = config_path()
    if path.exists():
        path.unlink()


def ensure_loaded() -> Config:
    cfg = load()
    if cfg is None:
        raise ConfigMissingError(
            "No config found. Run: expense config set --engine-url <url> --token <pat>"
        )
    return cfg


def generate_client_id() -> UUID:
    return uuid4()
