import asyncio
import unittest
from unittest import mock
from types import SimpleNamespace

import os

# The tests run against the example settings, not a real config.toml.
os.environ.setdefault("CONFIG_FILE", "config.example.toml")

import bot as bot_module  # noqa: E402


STREAM_LINES = [
    b'{"message":{"role":"assistant","content":"Mock "},"done":false}\n',
    b'{"message":{"role":"assistant","content":"reply"},"done":true}\n',
]


class FakeContent:
    def __aiter__(self):
        self.lines = iter(STREAM_LINES)
        return self

    async def __anext__(self):
        try:
            return next(self.lines)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeResponse:
    status = 200
    content = FakeContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class FakeSession:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def post(self, url: str, json: dict) -> FakeResponse:
        self.requests.append({"url": url, **json})
        return FakeResponse()


class FakeSentMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.edits: list[str] = []

    async def edit(self, *, content: str) -> None:
        self.content = content
        self.edits.append(content)


class FakeTyping:
    def __init__(self, channel: "FakeChannel") -> None:
        self.channel = channel

    def __await__(self):
        self.channel.events.append("typing")
        return iter(())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class FakeChannel:
    def __init__(self, previous_author_id: int | None = None) -> None:
        self.sent: list[FakeSentMessage] = []
        self.previous_author_id = previous_author_id
        self.events: list[str] = []

    def typing(self) -> FakeTyping:
        return FakeTyping(self)

    async def send(self, content: str) -> FakeSentMessage:
        message = FakeSentMessage(content)
        self.sent.append(message)
        self.events.append(content)
        return message

    async def history(self, **_kwargs):
        if self.previous_author_id is not None:
            yield SimpleNamespace(author=SimpleNamespace(id=self.previous_author_id))


class FakeSourceMessage:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel
        self.first_reply: FakeSentMessage | None = None

    async def reply(self, content: str, **_kwargs) -> FakeSentMessage:
        self.first_reply = FakeSentMessage(content)
        self.channel.events.append(content)
        return self.first_reply


class BotIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = bot_module.OllamaDiscordBot()
        self.session = FakeSession()
        self.bot.ollama_http = self.session  # type: ignore[assignment]

    async def test_client_starts_and_sends_streamed_history_to_ollama(self) -> None:
        self.assertIsNotNone(self.bot.http)
        self.assertIsNot(self.bot.http, self.bot.ollama_http)

        first = "".join(
            [part async for part in self.bot.stream_ollama(123, "First question")]
        )
        second = "".join(
            [part async for part in self.bot.stream_ollama(123, "Follow-up question")]
        )

        self.assertEqual(first, "Mock reply")
        self.assertEqual(second, "Mock reply")
        self.assertEqual(len(self.session.requests), 2)
        self.assertTrue(self.session.requests[0]["stream"])
        second_messages = self.session.requests[1]["messages"]
        self.assertEqual(second_messages[-3]["content"], "First question")
        self.assertEqual(second_messages[-2]["content"], "Mock reply")
        self.assertEqual(second_messages[-1]["content"], "Follow-up question")

    async def test_stream_is_rendered_as_progressive_edits(self) -> None:
        async def chunks():
            yield "Hello"
            yield " there"

        source = FakeSourceMessage(FakeChannel())
        await self.bot.render_as_edits(source, chunks())  # type: ignore[arg-type]

        assert source.first_reply is not None
        self.assertEqual(source.first_reply.content, "Hello there")
        self.assertEqual(source.first_reply.edits, ["Hello there"])
        self.assertNotIn("…", [source.first_reply.content, *source.first_reply.edits])

    async def test_no_reply_is_created_before_the_first_chunk(self) -> None:
        source = FakeSourceMessage(FakeChannel())

        async def delayed_chunks():
            self.assertIsNone(source.first_reply)
            yield "Actual response"

        await self.bot.render_as_edits(source, delayed_chunks())  # type: ignore[arg-type]
        assert source.first_reply is not None
        self.assertEqual(source.first_reply.content, "Actual response")

    async def test_streaming_error_shows_only_generic_message(self) -> None:
        async def broken_stream():
            yield "Partial technical details"
            raise RuntimeError("secret internal error")

        source = FakeSourceMessage(FakeChannel())
        with self.assertRaises(bot_module.StreamFailureShown):
            await self.bot.render_as_edits(source, broken_stream())  # type: ignore[arg-type]

        assert source.first_reply is not None
        self.assertEqual(source.first_reply.content, bot_module.FAILURE_MESSAGE)
        self.assertNotIn("secret internal error", source.first_reply.content)

    async def test_immediately_following_message_is_a_continuation(self) -> None:
        self.bot._connection.user = SimpleNamespace(id=999)
        message = SimpleNamespace(
            channel=FakeChannel(previous_author_id=999),
            mentions=[],
            reference=None,
        )
        self.assertTrue(await self.bot.should_respond(message))

    async def test_timeout_limits_silence_not_the_whole_reply(self) -> None:
        bot = bot_module.OllamaDiscordBot()
        await bot.setup_hook()
        try:
            timeout = bot.ollama_http.timeout
            self.assertIsNone(timeout.total)
            self.assertEqual(timeout.sock_read, bot_module.REQUEST_TIMEOUT)
        finally:
            await bot.ollama_http.close()

    async def test_a_timeout_is_logged_as_one_warning_line(self) -> None:
        class TimingOutSession:
            def post(self, *_args, **_kwargs):
                raise asyncio.TimeoutError

        channel = FakeChannel()
        channel.id = 123
        source = FakeSourceMessage(channel)
        source.author = SimpleNamespace(bot=False)
        source.content = "hello"

        async def respond(_message):
            return True

        self.bot.should_respond = respond
        self.bot.ollama_http = TimingOutSession()  # type: ignore[assignment]
        with self.assertLogs("ollama-discord-bot", level="WARNING") as logs:
            await self.bot.on_message(source)  # type: ignore[arg-type]

        self.assertEqual(len(logs.records), 1)
        self.assertIn("Ollama sent nothing for", logs.output[0])
        self.assertIsNone(logs.records[0].exc_info)
        assert source.first_reply is not None
        self.assertEqual(source.first_reply.content, bot_module.FAILURE_MESSAGE)


class MessagesStyleTests(unittest.IsolatedAsyncioTestCase):
    """Replies posted a paragraph at a time, like someone typing."""

    async def asyncSetUp(self) -> None:
        self.bot = bot_module.OllamaDiscordBot()
        self.pauses: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            self.pauses.append(seconds)

        self.patches = [
            mock.patch.object(bot_module, "REPLY_STYLE", "messages"),
            mock.patch.object(bot_module, "TYPING_SPEED", 0),
            mock.patch.object(bot_module.asyncio, "sleep", fake_sleep),
        ]
        for patch in self.patches:
            patch.start()

    async def asyncTearDown(self) -> None:
        for patch in self.patches:
            patch.stop()

    async def render(self, *parts: str) -> FakeChannel:
        async def chunks():
            for part in parts:
                yield part

        channel = FakeChannel()
        await self.bot.render_stream(FakeSourceMessage(channel), chunks())  # type: ignore[arg-type]
        return channel

    async def test_each_paragraph_is_its_own_message_with_typing_between(self) -> None:
        channel = await self.render("Hello there", "!\n\nSecond para", "graph.\n\nThird.")
        self.assertEqual(
            channel.events,
            ["Hello there!", "typing", "Second paragraph.", "typing", "Third."],
        )

    async def test_the_first_message_is_a_reply_and_the_rest_are_sent(self) -> None:
        channel = FakeChannel()
        source = FakeSourceMessage(channel)

        async def chunks():
            yield "One.\n\nTwo."

        await self.bot.render_stream(source, chunks())  # type: ignore[arg-type]
        assert source.first_reply is not None
        self.assertEqual(source.first_reply.content, "One.")
        self.assertEqual([m.content for m in channel.sent], ["Two."])

    async def test_a_code_block_with_blank_lines_stays_in_one_message(self) -> None:
        code = "```python\nx = 1\n\ny = 2\n```"
        channel = await self.render("Here:\n\n", code, "\n\nDone.")
        posts = [event for event in channel.events if event != "typing"]
        self.assertEqual(posts, ["Here:", code, "Done."])

    async def test_pauses_suit_the_length_of_each_message(self) -> None:
        with mock.patch.object(bot_module, "TYPING_SPEED", 10):
            await self.render("x" * 30 + "\n\n" + "y" * 40 + "\n\n" + "z" * 500)
        self.assertEqual(len(self.pauses), 2)  # none before the first message
        self.assertAlmostEqual(self.pauses[0], 4.0, delta=0.1)
        self.assertAlmostEqual(self.pauses[1], bot_module.MAX_TYPING_PAUSE, delta=0.1)

    async def test_the_first_message_is_posted_without_a_pause(self) -> None:
        with mock.patch.object(bot_module, "TYPING_SPEED", 10):
            await self.render("A long first paragraph that would take a while to type.")
        self.assertEqual(self.pauses, [])

    async def test_no_pauses_when_typing_speed_is_zero(self) -> None:
        await self.render("One.\n\nTwo.")
        self.assertEqual(self.pauses, [])

    async def test_a_failure_after_some_messages_adds_the_generic_message(self) -> None:
        async def broken():
            yield "Fine so far.\n\n"
            raise RuntimeError("secret internal error")

        channel = FakeChannel()
        with self.assertRaises(bot_module.StreamFailureShown):
            await self.bot.render_stream(FakeSourceMessage(channel), broken())  # type: ignore[arg-type]
        posts = [event for event in channel.events if event != "typing"]
        self.assertEqual(posts, ["Fine so far.", bot_module.FAILURE_MESSAGE])


if __name__ == "__main__":
    unittest.main()
