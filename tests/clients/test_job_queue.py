import asyncio

import fakeredis

from app.clients.job_queue import RedisJobQueue


def make_queue() -> RedisJobQueue:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return RedisJobQueue(redis, "test:queue")


def test_dequeue_is_fifo_and_ack_removes_from_processing() -> None:
    async def run_test() -> None:
        queue = make_queue()
        await queue.enqueue("a")
        await queue.enqueue("b")

        assert await queue.dequeue(0.1) == "a"
        assert await queue.contains("a")

        await queue.ack("a")

        assert not await queue.contains("a")
        assert await queue.dequeue(0.1) == "b"
        assert await queue.dequeue(0.1) is None

    asyncio.run(run_test())


def test_retry_later_waits_until_due() -> None:
    async def run_test() -> None:
        queue = make_queue()
        await queue.enqueue("a")
        await queue.dequeue(0.1)

        await queue.retry_later("a", 3600)
        assert await queue.promote_due() == 0
        assert await queue.contains("a")

        await queue.retry_later("a", 0)
        assert await queue.promote_due() == 1
        assert await queue.dequeue(0.1) == "a"

    asyncio.run(run_test())


def test_recover_processing_puts_ids_back_first() -> None:
    async def run_test() -> None:
        queue = make_queue()
        await queue.enqueue("crashed")
        await queue.enqueue("waiting")
        await queue.dequeue(0.1)

        assert await queue.recover_processing() == 1
        assert await queue.dequeue(0.1) == "crashed"
        assert await queue.dequeue(0.1) == "waiting"

    asyncio.run(run_test())


def test_promote_due_moves_only_due_ids_and_is_safe_to_rerun() -> None:
    async def run_test() -> None:
        queue = make_queue()
        for job_id in ("due-1", "due-2", "later"):
            await queue.enqueue(job_id)
            await queue.dequeue(0.1)
        await queue.retry_later("due-1", 0)
        await queue.retry_later("due-2", 0)
        await queue.retry_later("later", 3600)

        assert await queue.promote_due() == 2
        # A retried call after a lost reply must not push anything twice.
        assert await queue.promote_due() == 0

        assert await queue.dequeue(0.1) == "due-1"
        assert await queue.dequeue(0.1) == "due-2"
        assert await queue.dequeue(0.1) is None
        assert await queue.contains("later")

    asyncio.run(run_test())
