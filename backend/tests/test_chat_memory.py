import asyncio
import json
import unittest
from contextlib import AsyncExitStack
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from main import create_app


class FakeModel:
    def __init__(self):
        self.calls = []
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()

    async def ainvoke(self, messages):
        history = [message.content for message in messages[1:]]
        self.calls.append(history)
        if history[-1] == "timeout":
            raise TimeoutError
        if history[-1] == "empty":
            return AIMessage(content=" ")
        if history[-1] == "wait":
            self.blocked.set()
            await self.release.wait()
        return AIMessage(content=history[-1].upper())


def stream_events(response):
    return [json.loads(line) for line in response.text.splitlines()]


class ChatMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.model = FakeModel()
        self.app = create_app(self.model)
        stack = AsyncExitStack()
        self.addAsyncCleanup(stack.aclose)
        await stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.client = await stack.enter_async_context(
            AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")
        )
        self.thread = str(uuid4())

    async def send(self, message, *, path="/chat", **fields):
        return await self.client.post(
            path, json={"message": message, "thread_id": self.thread, **fields}
        )

    async def test_streaming_and_json_share_history_and_isolate_threads(self):
        response = await self.send("first", path="/chat/stream")
        self.assertEqual(stream_events(response), [
            {"type": "delta", "text": "FIRST"}, {"type": "done"},
        ])
        self.assertEqual((await self.send("second")).json(), {"reply": "SECOND"})
        await self.send("third", path="/chat/stream")
        await self.send("other shopper", thread_id=str(uuid4()))
        await self.client.post("/chat", json={"message": "legacy JSON"})
        await self.client.post("/chat/stream", json={"message": "legacy stream"})
        self.assertEqual(self.model.calls, [
            ["first"],
            ["first", "FIRST", "second"],
            ["first", "FIRST", "second", "SECOND", "third"],
            ["other shopper"],
            ["legacy JSON"],
            ["legacy stream"],
        ])

    async def test_retry_replays_original_reply_without_writing_another_turn(self):
        await self.send("first", message_id="one")
        await self.send("second", message_id="two", path="/chat/stream")
        retry = await self.send("first", message_id="one", path="/chat/stream")
        self.assertEqual(stream_events(retry), [
            {"type": "delta", "text": "FIRST"}, {"type": "done"},
        ])
        self.assertEqual((await self.send("second", message_id="two")).json(), {"reply": "SECOND"})
        self.assertEqual(len(self.model.calls), 2)
        await self.send("third", message_id="three")
        self.assertEqual(self.model.calls[-1], ["first", "FIRST", "second", "SECOND", "third"])

    async def test_timed_out_and_empty_turns_stay_out_of_history(self):
        await self.send("first")
        self.assertEqual((await self.send("timeout")).status_code, 504)
        self.assertEqual(stream_events(await self.send("timeout", path="/chat/stream")), [
            {"type": "error", "detail": "Model request timed out."},
        ])
        self.assertEqual((await self.send("empty")).json(), {"reply": " "})
        await self.send("next")
        self.assertEqual(self.model.calls[-1], ["first", "FIRST", "next"])

    async def test_same_thread_waits_without_blocking_other_threads(self):
        async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
            first = tasks.create_task(self.send("wait", path="/chat/stream"))
            await self.model.blocked.wait()
            second = tasks.create_task(self.send("next"))
            await self.send("independent", thread_id=str(uuid4()))
            self.assertFalse(second.done())
            self.model.release.set()
        self.assertEqual(stream_events(first.result())[-1], {"type": "done"})
        self.assertEqual(second.result().json(), {"reply": "NEXT"})
        self.assertEqual(self.model.calls, [["wait"], ["independent"], ["wait", "WAIT", "next"]])

    async def test_stream_disconnect_releases_thread_and_keeps_previous_turns(self):
        await self.send("first")
        events = []

        async def send(event):
            events.append(event)

        requests = asyncio.Queue()
        requests.put_nowait({
            "type": "http.request",
            "body": json.dumps({"message": "wait", "thread_id": self.thread}).encode(),
        })
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/chat/stream",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "scheme": "http",
        }
        async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
            tasks.create_task(self.app(scope, requests.get, send))
            await self.model.blocked.wait()
            requests.put_nowait({"type": "http.disconnect"})
        self.assertEqual([event["type"] for event in events], ["http.response.start"])
        await asyncio.wait_for(self.send("next"), timeout=5)
        self.assertEqual(self.model.calls[-1], ["first", "FIRST", "next"])

    async def test_new_app_lifespan_starts_with_empty_memory(self):
        await self.send("first")
        async with self.app.router.lifespan_context(self.app):
            await self.send("next")
        self.assertEqual(self.model.calls[-1], ["next"])
