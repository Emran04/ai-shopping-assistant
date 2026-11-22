import asyncio
import json
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlmodel import create_engine

from chatbot.quota import reset_usage
from main import CHAT_COOKIE, create_app
from models import ChatCustomer


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
        directory = stack.enter_context(TemporaryDirectory())
        self.engine = create_engine(f"sqlite:///{Path(directory) / 'chat.db'}")
        ChatCustomer.__table__.create(self.engine)
        stack.enter_context(patch("main.create_database_engine", return_value=self.engine))
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
        await self.client.post("/chat/session")
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
            "headers": [
                (b"content-type", b"application/json"),
                (b"cookie", f"{CHAT_COOKIE}={self.client.cookies[CHAT_COOKIE]}".encode()),
            ],
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

    async def test_quota_is_shared_by_threads_and_survives_restart_until_staff_reset(self):
        with patch.dict("os.environ", {"CHAT_MESSAGE_LIMIT": "2"}):
            async with self.app.router.lifespan_context(self.app):
                session = await self.client.post("/chat/session")
                self.assertEqual(session.status_code, 200, session.text)
                customer = session.json()["customer_id"]
                self.assertIn("HttpOnly", session.headers["set-cookie"])
                self.assertNotIn(customer, session.headers["set-cookie"])
                self.assertEqual(session.json()["messages_remaining"], 2)

                first = await self.send("first", message_id="one")
                self.assertEqual(first.headers["x-chat-messages-remaining"], "1")
                last = await self.send("last", path="/chat/stream", thread_id=str(uuid4()))
                self.assertEqual(last.headers["x-chat-messages-remaining"], "0")
                self.assertEqual(stream_events(last)[-1], {"type": "done"})
                self.assertEqual((await self.send("first", message_id="one")).json(), {"reply": "FIRST"})

            async with self.app.router.lifespan_context(self.app):
                session = await self.client.post("/chat/session")
                self.assertEqual(session.json()["customer_id"], customer)
                self.assertEqual(session.json()["messages_remaining"], 0)
                for path in ("/chat", "/chat/stream"):
                    blocked = await self.send("blocked", path=path, thread_id=str(uuid4()))
                    self.assertEqual(blocked.status_code, 429)
                    self.assertIn(customer, blocked.json()["detail"])
                self.assertEqual(self.model.calls, [["first"], ["last"]])

                async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as other:
                    response = await other.post("/chat", json={"message": "other", "thread_id": self.thread})
                    self.assertEqual(response.status_code, 200)
                    self.assertNotEqual(response.headers["x-chat-customer-id"], customer)

                self.assertTrue(reset_usage(self.engine, UUID(customer)))
                restored = await self.client.post("/chat/session")
                self.assertEqual(restored.json()["messages_remaining"], 2)
                self.assertEqual((await self.send("restored")).json(), {"reply": "RESTORED"})

    async def test_concurrent_threads_cannot_both_claim_the_last_message(self):
        self.app.state.chat_message_limit = 1
        await self.client.post("/chat/session")
        async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
            first = tasks.create_task(self.send("wait", path="/chat/stream"))
            await self.model.blocked.wait()
            blocked = await self.send("extra", thread_id=str(uuid4()))
            self.assertEqual(blocked.status_code, 429)
            self.model.release.set()
        self.assertEqual(stream_events(first.result())[-1], {"type": "done"})
        self.assertEqual(self.model.calls, [["wait"]])
