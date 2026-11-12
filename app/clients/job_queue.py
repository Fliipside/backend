import time

from redis.asyncio import Redis


_PROMOTE_DUE_LUA = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
for _, job_id in ipairs(due) do
    redis.call('ZREM', KEYS[1], job_id)
    redis.call('LPUSH', KEYS[2], job_id)
end
return #due
"""


class RedisJobQueue:
    """Reliable FIFO queue holding only job ids. The DB row is the source of truth.

    - pending: list. API pushes on the left, the worker takes from the right.
    - processing: list. BLMOVE moves an id here while it is being handled, so an
      id survives a worker crash and is put back by recover_processing().
    - delayed: sorted set scored by the unix time when a retry may run.
    """

    def __init__(self, redis: Redis, name: str) -> None:
        self._redis = redis
        self.pending_key = f"{name}:pending"
        self.processing_key = f"{name}:processing"
        self.delayed_key = f"{name}:delayed"
        self._promote_due_script = redis.register_script(_PROMOTE_DUE_LUA)

    async def enqueue(self, job_id: str) -> None:
        await self._redis.lpush(self.pending_key, job_id)

    async def dequeue(self, timeout_seconds: float) -> str | None:
        return await self._redis.blmove(
            self.pending_key,
            self.processing_key,
            timeout_seconds,
            "RIGHT",
            "LEFT",
        )

    async def ack(self, job_id: str) -> None:
        await self._redis.lrem(self.processing_key, 0, job_id)

    async def retry_later(self, job_id: str, delay_seconds: float) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lrem(self.processing_key, 0, job_id)
            pipe.zadd(self.delayed_key, {job_id: time.time() + delay_seconds})
            await pipe.execute()

    async def promote_due(self) -> int:
        """Move delayed ids whose time has come back to pending.

        Runs as one Lua script so the remove from delayed and the push to pending
        happen together. Re-running it after a lost reply finds nothing left to move.
        """
        return int(await self._promote_due_script(
            keys=[self.delayed_key, self.pending_key],
            args=[time.time()],
        ))

    async def recover_processing(self) -> int:
        """Put ids left in processing by a stopped worker back to pending."""
        moved = 0
        while await self._redis.lmove(
            self.processing_key,
            self.pending_key,
            "RIGHT",
            "RIGHT",
        ):
            moved += 1
        return moved

    async def contains(self, job_id: str) -> bool:
        if await self._redis.lpos(self.pending_key, job_id) is not None:
            return True
        if await self._redis.lpos(self.processing_key, job_id) is not None:
            return True
        return await self._redis.zscore(self.delayed_key, job_id) is not None
