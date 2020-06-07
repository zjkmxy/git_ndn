import asyncio as aio
import json
import logging
from ndn.app import NDNApp
from ndn.encoding import Name, Component, BinaryStr, FormalName
from ndn.name_tree import NameTrie
from ndn.types import InterestNack, InterestTimeout
import pickle
import typing
from typing import List, Optional


class VSync:
    OnUpdateFunc = typing.Callable[[BinaryStr], None]

    def __init__(self, app: NDNApp, on_update, prefix: FormalName, interval: int):
        self.app = app
        self.on_update = on_update
        self.prefix = prefix
        self.interval = interval
        self.content_latest = None
        # listen for sync interests
        self.app.route(self.prefix)(self._on_sync_interest)
        # start retx sync interests
        aio.ensure_future(self._retx_sync_interest())

    def publish_update(self, content: BinaryStr):
        self.content_latest = content
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
    
    def _on_sync_interest(self, int_name, _int_param, _app_param):
        # do not update state, because not sure which one is newer
        if _app_param != self.content_latest:
            self.on_update(_app_param)