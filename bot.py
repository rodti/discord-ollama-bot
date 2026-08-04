import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator

import aiohttp
import discord
from dotenv import load_dotenv

from personalities import (
    load_default_model,
    load_discord_token,
    load_memory_size,
    load_ollama_url,
    load_personality,
    load_stream_update_interval,
)
from utils import split_message


load_dotenv()

CONFIG_FILE = os.getenv("CONFIG_FILE", "config.toml")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "120"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ollama-discord-bot")
FAILURE_MESSAGE = "I'm not working properly at the moment. Please try again later."


class StreamFailureShown(Exception):
    """Signals that a streaming failure was already represented in Discord."""

try:
    DISCORD_TOKEN = load_discord_token(CONFIG_FILE, os.getenv("DISCORD_TOKEN", ""))
    OLLAMA_URL = load_ollama_url(CONFIG_FILE, os.getenv("OLLAMA_URL", ""))
    DEFAULT_OLLAMA_MODEL = load_default_model(CONFIG_FILE)
    PERSONALITY = load_personality(CONFIG_FILE, DEFAULT_OLLAMA_MODEL)
    MEMORY_SIZE = load_memory_size(CONFIG_FILE)
    STREAM_UPDATE_INTERVAL = load_stream_update_interval(CONFIG_FILE)
except ValueError as exc:
    raise SystemExit(f"Configuration error: {exc}") from exc


class OllamaDiscordBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.histories: dict[int, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=MEMORY_SIZE)
        )
        self.channel_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        # discord.Client owns `self.http`; use a distinct name for Ollama.
        self.ollama_http: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        self.ollama_http = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self.ollama_http is not None:
            await self.ollama_http.close()
        await super().close()

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info(
            "Logged in as %s (%s), personality %s, Ollama model %s",
            self.user,
            self.user.id,
            PERSONALITY.name,
            PERSONALITY.model,
        )
        log.info("Conversation memory is %s messages per channel", MEMORY_SIZE)

    async def should_respond(self, message: discord.Message) -> bool:
        if isinstance(message.channel, discord.DMChannel):
            return True
        if self.user is None:
            return False
        mentioned = self.user in message.mentions
        replied_to_bot = (
            message.reference is not None
            and isinstance(message.reference.resolved, discord.Message)
            and message.reference.resolved.author.id == self.user.id
        )
        if mentioned or replied_to_bot:
            return True

        # Treat a message immediately following one of the bot's posts as a
        # natural continuation, even without a mention or Discord reply.
        try:
            async for previous in message.channel.history(limit=1, before=message):
                return previous.author.id == self.user.id
        except (discord.Forbidden, discord.HTTPException):
            log.exception("Could not inspect channel history for a continuation")
        return False

    def clean_prompt(self, message: discord.Message) -> str:
        content = message.content
        if self.user is not None:
            content = content.replace(f"<@{self.user.id}>", "")
            content = content.replace(f"<@!{self.user.id}>", "")
        return content.strip()

    async def stream_ollama(
        self, channel_id: int, prompt: str
    ) -> AsyncIterator[str]:
        if self.ollama_http is None:
            raise RuntimeError("HTTP client is not ready")

        history = self.histories[channel_id]
        messages = [{"role": "system", "content": PERSONALITY.system_prompt}, *history]
        messages.append({"role": "user", "content": prompt})
        payload = {"model": PERSONALITY.model, "messages": messages, "stream": True}

        async with self.ollama_http.post(f"{OLLAMA_URL}/api/chat", json=payload) as response:
            if response.status != 200:
                detail = (await response.text())[:500]
                raise RuntimeError(f"Ollama returned HTTP {response.status}: {detail}")
            answer_parts: list[str] = []
            async for raw_line in response.content:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Ollama returned an invalid streaming response") from exc
                if data.get("error"):
                    raise RuntimeError(f"Ollama error: {data['error']}")
                content = data.get("message", {}).get("content", "")
                if content:
                    answer_parts.append(content)
                    yield content

        answer = "".join(answer_parts).strip()
        if not answer:
            raise RuntimeError("Ollama returned an empty response")
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": answer})

    async def render_stream(
        self, source: discord.Message, chunks: AsyncIterator[str]
    ) -> None:
        response_messages: list[discord.Message] = []
        rendered_texts: list[str] = []
        answer = ""
        last_update = 0.0

        async def update_discord() -> None:
            nonlocal rendered_texts
            visible_chunks = split_message(answer)
            for index, visible in enumerate(visible_chunks):
                if index < len(response_messages):
                    if rendered_texts[index] != visible:
                        await response_messages[index].edit(content=visible)
                        rendered_texts[index] = visible
                elif index == 0:
                    response_messages.append(
                        await source.reply(visible, mention_author=False)
                    )
                    rendered_texts.append(visible)
                else:
                    response_messages.append(await source.channel.send(visible))
                    rendered_texts.append(visible)

        try:
            async for content in chunks:
                answer += content
                now = time.monotonic()
                if now - last_update >= STREAM_UPDATE_INTERVAL:
                    await update_discord()
                    last_update = now
            await update_discord()
        except Exception as exc:
            try:
                if response_messages:
                    await response_messages[0].edit(content=FAILURE_MESSAGE)
                else:
                    await source.reply(FAILURE_MESSAGE, mention_author=False)
            except discord.DiscordException:
                log.exception("Could not show the generic streaming failure message")
            raise StreamFailureShown from exc

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not await self.should_respond(message):
            return

        prompt = self.clean_prompt(message)
        if prompt.lower() == "!reset":
            self.histories.pop(message.channel.id, None)
            await message.reply("Conversation history cleared.", mention_author=False)
            return
        if prompt.lower() == "!personality":
            await message.reply(
                f"Active personality: **{PERSONALITY.name}** (model: `{PERSONALITY.model}`)",
                mention_author=False,
            )
            return
        if prompt.lower() == "!memory":
            remembered = len(self.histories[message.channel.id])
            await message.reply(
                f"Memory: **{remembered}/{MEMORY_SIZE}** previous messages in this channel.",
                mention_author=False,
            )
            return
        if not prompt:
            await message.reply("What would you like to ask?", mention_author=False)
            return

        lock = self.channel_locks[message.channel.id]
        async with lock:
            try:
                async with message.channel.typing():
                    await self.render_stream(
                        message, self.stream_ollama(message.channel.id, prompt)
                    )
            except StreamFailureShown:
                log.exception("Ollama streaming failed after the Discord reply started")
            except asyncio.TimeoutError:
                log.warning("Ollama request timed out for channel %s", message.channel.id)
                await self.send_generic_failure(message)
            except Exception:
                log.exception("Ollama request failed")
                await self.send_generic_failure(message)

    async def send_generic_failure(self, message: discord.Message) -> None:
        try:
            await message.reply(FAILURE_MESSAGE, mention_author=False)
        except discord.DiscordException:
            log.exception("Could not send the generic failure message to Discord")


def main() -> None:
    OllamaDiscordBot().run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
