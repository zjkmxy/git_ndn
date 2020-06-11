import asyncio as aio
import logging
import hashlib
from ndn.app import NDNApp
from ndn.encoding import BinaryStr, FormalName
from ndn.types import InterestNack, InterestTimeout
import typing
from typing import Optional


class VSync:
    OnUpdateFunc = typing.Callable[[BinaryStr, Optional[bytes]], None]

    def __init__(self, app: NDNApp, on_update: OnUpdateFunc, prefix: FormalName, interval: int):
        self.app = app
        self.on_update = on_update
        self.prefix = prefix
        self.interval = interval
        self.content_latest = None
        self.bouncing_updates = set()
        # listen for sync interests
        self.app.route(self.prefix)(self._on_sync_interest)
        # start retx sync interests
        aio.ensure_future(self._retx_sync_interest())

    def publish_update(self, content: BinaryStr, respond_to: Optional[bytes] = None):
        if self.content_latest != content:
            self.content_latest = content
            self.bouncing_updates.clear()
        if respond_to is not None:
            if respond_to in self.bouncing_updates:
                return
            self.bouncing_updates.add(respond_to)
        # state change triggers sending sync interest
        aio.ensure_future(self._send_sync_interest())

    async def _retx_sync_interest(self):
        while True:
            await aio.sleep(self.interval)
            aio.ensure_future(self._send_sync_interest())

    async def _send_sync_interest(self):
        if self.content_latest == None:
            return
        try:
            await self.app.express_interest(self.prefix, app_param=self.content_latest)
        except InterestTimeout:
            # do not expect reply
            return
        except InterestNack as e:
            logging.warning(f'Data interest nacked with reason={e.reason}')
            return
    
    def _on_sync_interest(self, _int_name, _int_param, app_param):
        # do not update state, because not sure which one is newer
        if app_param != self.content_latest:
            content_hash = hashlib.sha256(app_param).digest()
            self.on_update(app_param, content_hash)
