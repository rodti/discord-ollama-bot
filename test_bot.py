import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from personalities import (
    load_default_model,
    load_discord_token,
    load_memory_size,
    load_ollama_url,
    load_personality,
    load_stream_update_interval,
)
from utils import split_message


class SplitMessageTests(unittest.TestCase):
    def test_short_message_is_unchanged(self) -> None:
        self.assertEqual(split_message("hello"), ["hello"])

    def test_long_message_respects_limit(self) -> None:
        chunks = split_message("word " * 100, limit=50)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 50 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), ("word " * 100).split())

    def test_empty_message_has_fallback(self) -> None:
        self.assertTrue(split_message(""))


class PersonalityTests(unittest.TestCase):
    def test_loads_selected_personality_with_default_model(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                'active_personality = "friendly"\n'
                '[personalities.friendly]\n'
                'system_prompt = "Be friendly."\n',
                encoding="utf-8",
            )
            personality = load_personality(path, "llama3.2")
        self.assertEqual(personality.name, "friendly")
        self.assertEqual(personality.system_prompt, "Be friendly.")
        self.assertEqual(personality.model, "llama3.2")

    def test_personality_can_override_model(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                'active_personality = "coder"\n'
                '[personalities.coder]\n'
                'model = "coder-model"\n'
                'system_prompt = "Write code."\n',
                encoding="utf-8",
            )
            personality = load_personality(path, "default-model")
        self.assertEqual(personality.model, "coder-model")

    def test_rejects_undefined_selection(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('active_personality = "missing"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not defined"):
                load_personality(path, "llama3.2")


class MemoryConfigTests(unittest.TestCase):
    def test_loads_memory_size(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("memory_size = 42\n", encoding="utf-8")
            self.assertEqual(load_memory_size(path), 42)

    def test_defaults_to_twenty_messages(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("", encoding="utf-8")
            self.assertEqual(load_memory_size(path), 20)

    def test_zero_disables_memory(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("memory_size = 0\n", encoding="utf-8")
            self.assertEqual(load_memory_size(path), 0)

    def test_rejects_negative_memory(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("memory_size = -1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "zero or greater"):
                load_memory_size(path)


class ModelConfigTests(unittest.TestCase):
    def test_loads_default_model(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('default_model = "mistral:7b"\n', encoding="utf-8")
            self.assertEqual(load_default_model(path), "mistral:7b")

    def test_rejects_missing_default_model(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "default_model"):
                load_default_model(path)


class DiscordTokenConfigTests(unittest.TestCase):
    def test_loads_token_from_config(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('discord_token = "config-token"\n', encoding="utf-8")
            self.assertEqual(load_discord_token(path), "config-token")

    def test_environment_token_takes_precedence(self) -> None:
        self.assertEqual(
            load_discord_token("file-does-not-need-to-exist.toml", "environment-token"),
            "environment-token",
        )

    def test_rejects_missing_token(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "discord_token"):
                load_discord_token(path)


class OllamaUrlConfigTests(unittest.TestCase):
    def test_loads_url_from_config_and_removes_trailing_slash(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                'ollama_url = "http://192.168.1.50:11434/"\n', encoding="utf-8"
            )
            self.assertEqual(load_ollama_url(path), "http://192.168.1.50:11434")

    def test_environment_url_takes_precedence(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                'ollama_url = "http://192.168.1.50:11434"\n', encoding="utf-8"
            )
            self.assertEqual(
                load_ollama_url(path, "http://10.0.0.20:11434"),
                "http://10.0.0.20:11434",
            )

    def test_rejects_url_with_api_path(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                'ollama_url = "http://localhost:11434/api/chat"\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "must not include"):
                load_ollama_url(path)


class StreamingConfigTests(unittest.TestCase):
    def test_loads_stream_update_interval(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("stream_update_interval = 0.5\n", encoding="utf-8")
            self.assertEqual(load_stream_update_interval(path), 0.5)

    def test_rejects_excessively_fast_updates(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("stream_update_interval = 0.1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least 0.25"):
                load_stream_update_interval(path)

    def test_rejects_incomplete_url(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('ollama_url = "192.168.1.50:11434"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complete"):
                load_ollama_url(path)


if __name__ == "__main__":
    unittest.main()
