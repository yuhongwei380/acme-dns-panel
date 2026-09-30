import asyncio
import os

import uvicorn

from .config import Config
from .web import create_apps


async def serve():
    if os.name == "posix":
        os.umask(0o077)
    config = Config.load()
    # A second instance would run duplicate renewal jobs, so hold a process-level lock.
    lock = None
    if os.name == "posix":
        import fcntl
        config.prepare()
        lock = (config.root / "data" / "service.lock").open("w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("已有实例使用此数据目录")
    admin, public = create_apps(config)
    servers = [uvicorn.Server(uvicorn.Config(admin, host=config.admin_host, port=config.admin_port, access_log=False)),
               uvicorn.Server(uvicorn.Config(public, host=config.public_host, port=config.public_port, access_log=False))]
    # Both listeners share one lifecycle and stop together if either cannot bind.
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if lock:
            lock.close()


if __name__ == "__main__":
    asyncio.run(serve())
