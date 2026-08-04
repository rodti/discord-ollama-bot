from dataclasses import dataclass
from pathlib import Path
import tomllib
from urllib.parse import urlparse


@dataclass(frozen=True)
class Personality:
    name: str
    system_prompt: str
    model: str


def load_config(config_path: str | Path) -> dict:
    path = Path(config_path)
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except FileNotFoundError as exc:
        raise ValueError(f"Configuration file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc


def load_memory_size(config_path: str | Path) -> int:
    config = load_config(config_path)
    memory_size = config.get("memory_size", 20)
    if not isinstance(memory_size, int) or isinstance(memory_size, bool) or memory_size < 0:
        raise ValueError("memory_size must be a whole number of zero or greater")
    return memory_size


def load_stream_update_interval(config_path: str | Path) -> float:
    config = load_config(config_path)
    interval = config.get("stream_update_interval", 0.75)
    if (
        not isinstance(interval, (int, float))
        or isinstance(interval, bool)
        or interval < 0.25
    ):
        raise ValueError("stream_update_interval must be a number of at least 0.25")
    return float(interval)


def load_default_model(config_path: str | Path) -> str:
    config = load_config(config_path)
    model = config.get("default_model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("default_model must be a non-empty Ollama model name")
    return model.strip()


def load_discord_token(config_path: str | Path, environment_token: str = "") -> str:
    if environment_token.strip():
        return environment_token.strip()
    config = load_config(config_path)
    token = config.get("discord_token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError(
            "discord_token must be set in config.toml or provided as DISCORD_TOKEN"
        )
    return token.strip()


def load_ollama_url(config_path: str | Path, environment_url: str = "") -> str:
    config = load_config(config_path)
    configured_url = environment_url.strip() or config.get("ollama_url")
    if not isinstance(configured_url, str) or not configured_url.strip():
        raise ValueError("ollama_url must be set in config.toml or provided as OLLAMA_URL")

    url = configured_url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ollama_url must be a complete http:// or https:// URL")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("ollama_url must not include an API path, query, or fragment")
    return url


def load_personality(config_path: str | Path, default_model: str) -> Personality:
    config = load_config(config_path)

    selected = config.get("active_personality")
    personalities = config.get("personalities")
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError("config.toml must define a non-empty active_personality")
    if not isinstance(personalities, dict) or selected not in personalities:
        raise ValueError(f"Active personality {selected!r} is not defined")

    settings = personalities[selected]
    if not isinstance(settings, dict):
        raise ValueError(f"Personality {selected!r} must be a TOML table")
    prompt = settings.get("system_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Personality {selected!r} needs a non-empty system_prompt")
    model = settings.get("model", default_model)
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"Personality {selected!r} has an invalid model")

    return Personality(name=selected, system_prompt=prompt.strip(), model=model.strip())
