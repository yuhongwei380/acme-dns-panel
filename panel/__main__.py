import asyncio
import os

import uvicorn

from .config import Config
from .web import create_apps
from .http_service import PublicHTTPService


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
    downloads = PublicHTTPService(config, public)
    admin.state.public_service = downloads
    server = uvicorn.Server(uvicorn.Config(admin, host=config.admin_host, port=config.admin_port, access_log=False))
    tasks = []
    try:
        await downloads.start()
        tasks = [asyncio.create_task(server.serve()), asyncio.create_task(downloads.failed.wait())]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        server.should_exit = True
        tasks[1].cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await downloads.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if lock:
            lock.close()


if __name__ == "__main__":
    asyncio.run(serve())
