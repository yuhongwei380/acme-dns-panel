"""Small standard-library compatibility helpers for Python 3.8+."""
import asyncio
from functools import partial


async def run_blocking(function, *args):
    return await asyncio.get_running_loop().run_in_executor(None, partial(function, *args))
