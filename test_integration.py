import unittest
from types import SimpleNamespace

import bot as bot_module


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


class FakeChannel:
    def __init__(self, previous_author_id: int | None = None) -> None:
        self.sent: list[FakeSentMessage] = []
        self.previous_author_id = previous_author_id

    async def send(self, content: str) -> FakeSentMessage:
        message = FakeSentMessage(content)
        self.sent.append(message)
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
        await self.bot.render_stream(source, chunks())  # type: ignore[arg-type]

        assert source.first_reply is not None
        self.assertEqual(source.first_reply.content, "Hello there")
        self.assertEqual(source.first_reply.edits, ["Hello there"])
        self.assertNotIn("…", [source.first_reply.content, *source.first_reply.edits])

    async def test_no_reply_is_created_before_the_first_chunk(self) -> None:
        source = FakeSourceMessage(FakeChannel())

        async def delayed_chunks():
            self.assertIsNone(source.first_reply)
            yield "Actual response"

        await self.bot.render_stream(source, delayed_chunks())  # type: ignore[arg-type]
        assert source.first_reply is not None
        self.assertEqual(source.first_reply.content, "Actual response")

    async def test_streaming_error_shows_only_generic_message(self) -> None:
        async def broken_stream():
            yield "Partial technical details"
            raise RuntimeError("secret internal error")

        source = FakeSourceMessage(FakeChannel())
        with self.assertRaises(bot_module.StreamFailureShown):
            await self.bot.render_stream(source, broken_stream())  # type: ignore[arg-type]

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


if __name__ == "__main__":
    unittest.main()
