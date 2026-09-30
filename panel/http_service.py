import asyncio
from contextlib import contextmanager
import logging
import os
import socket

import uvicorn

logger = logging.getLogger("uvicorn.error")


class DownloadServer(uvicorn.Server):
    # The admin listener owns process signals; reloading downloads must not replace them.
    def install_signal_handlers(self):
        pass

    @contextmanager
    def capture_signals(self):
        yield


class PublicHTTPService:
    def __init__(self, config, app):
        self.config = config
        self.app = app
        self.server = None
        self.task = None
        self.lock = asyncio.Lock()
        self.failed = asyncio.Event()
        self.closing = False

    async def launch(self, port):
        addresses = socket.getaddrinfo(self.config.public_host, port, type=socket.SOCK_STREAM)
        family, kind, protocol, _, address = addresses[0]
        sock = socket.socket(family, kind, protocol)
        try:
            if os.name != "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(address)
            sock.listen(128)
            sock.setblocking(False)
            server = DownloadServer(uvicorn.Config(
                self.app, host=self.config.public_host, port=port,
                access_log=False, timeout_graceful_shutdown=15,
            ))
            task = asyncio.create_task(server.serve(sockets=[sock]))
            try:
                async def ready():
                    while not server.started:
                        if task.done():
                            await task
                            raise RuntimeError("下载服务启动失败")
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(ready(), timeout=10)
            except BaseException:
                server.should_exit = True
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
            return server, task
        except BaseException:
            sock.close()
            raise

    def watch(self, task):
        def completed(done):
            if done is self.task and not self.closing:
                logger.error("下载 HTTP 服务意外停止")
                self.failed.set()
        task.add_done_callback(completed)

    async def start(self):
        self.server, self.task = await self.launch(self.config.public_port)
        self.watch(self.task)
        logger.info("下载 HTTP 服务监听于 http://%s:%s", self.config.public_host, self.config.public_port)

    async def reload(self, port):
        async with self.lock:
            if self.closing:
                raise RuntimeError("服务正在关闭，请稍后重试")
            if port == self.config.admin_port:
                raise ValueError("下载端口不能与管理端口相同")
            if port == self.config.public_port:
                # No interruption is necessary when the running configuration matches.
                return
            new_server, new_task = await self.launch(port)
            try:
                self.config.save_public_port(port)
            except BaseException:
                new_server.should_exit = True
                await asyncio.gather(new_task, return_exceptions=True)
                raise
            old_server, old_task = self.server, self.task
            self.server, self.task = new_server, new_task
            self.config.public_port = port
            self.watch(new_task)
            old_server.should_exit = True
            await asyncio.gather(old_task, return_exceptions=True)
            logger.info("下载 HTTP 服务已重载：%s:%s", self.config.public_host, port)

    async def close(self):
        async with self.lock:
            self.closing = True
            if self.server:
                self.server.should_exit = True
                await asyncio.gather(self.task, return_exceptions=True)
