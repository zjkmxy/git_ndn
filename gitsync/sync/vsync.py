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


# class StateVector:
#     def __init__(self, states_serialized: bytes=None):
#         if not states_serialized:
#             self.states = dict() # str -> int
#         else:
#             self.states = pickle.loads(states_serialized)

#     def __getitem__(self, prefix: str) -> Optional[int]:
#         try:
#             return self.states[prefix]
#         except KeyError:
#             return None

#     def __setitem__(self, prefix: str, seq: int):
#         self.states[prefix] = seq

#     def __sub__(self, other) -> List[FormalName]:
#         """
#         Return a list of missing (prefix, seq) tuples when compared with other.
#         """
#         ret = []
#         for prefix, seq in self.states.items():
#             seq_other = None
#             if prefix in other.states:
#                 seq_other = other.states[prefix]
#             for seq in range((seq_other + 1) if seq_other else 0, seq + 1):
#                 ret.append((Name.from_str(prefix), seq))
#         return ret
    
#     def merge(self, other):
#         """
#         Merge with state vector other.
#         """
#         for prefix, seq_other in other.states.items():
#             if prefix not in self.states or self[prefix] < seq_other:
#                 self[prefix] = seq_other

#     def __str__(self):
#         return json.dumps(self.states)

#     def serialize(self):
#         return pickle.dumps(self.states)


# class VSync:
#     """
#     State Vector Sync.
#     TODO: signature verification on sync interests.
#     """
#     OnUpdateFunc = typing.Callable[[BinaryStr], None]

#     def __init__(self, app: NDNApp, on_update, prefix: FormalName, interval: int):
#         self.app = app
#         self.on_update = on_update
#         self.prefix = Name.to_str(prefix)
#         self.sync_prefix = prefix + ['sync']
#         self.data_prefix = prefix + ['data']
#         self.interval = interval
#         self.name_to_data = dict()
#         # self.name_to_data = NameTrie()
#         self.sv = StateVector()

#         # listen on sync and data prefix
#         self.app.route(self.sync_prefix)(self._on_sync_interest)
#         self.app.route(self.data_prefix)(self._on_data_interest)

#         # start retx sync interests
#         aio.ensure_future(self._retx_sync_interest())

#     def publish_update(self, content: BinaryStr):
#         seq = (self.sv[self.prefix] + 1) if self.sv[self.prefix] else 0
#         data_name = self.data_prefix + [Component.from_sequence_num(seq)]
#         data_name = Name.normalize(data_name)
#         logging.info('Publish data: ' + Name.to_str(data_name))
#         # save name to data packet mapping
#         packet  = self.app.prepare_data(data_name, content) 
#         self.name_to_data[Name.to_str(data_name)] = packet
#         # send sync interest after state changes
#         aio.ensure_future(self._send_sync_interest())

#     async def _retx_sync_interest(self):
#         while True:
#             await aio.sleep(self.interval)
#             aio.ensure_future(self._send_sync_interest())

#     async def _send_sync_interest(self):
#         """
#         Send sync interest /<prefix>/sync/<vector>.
#         Does not expect a sync reply.
#         """
#         logging.info(f'Send sync interest: {str(self.sv)}')
#         int_name = self.sync_prefix
#         app_param = Component.from_bytes(self.sv.serialize())
#         try:
#             await self.app.express_interest(int_name, lifetime=1000)
#         except InterestTimeout:
#             return
#         except InterestNack as e:
#             logging.warning(f'Sync interest nacked with reason={e.reason}')
#             return

#     def _on_sync_interest(self, int_name, _int_param, _app_param):
#         sv_other = StateVector(_app_param)
#         logging.info(f'Received sync interest with vector: {str(sv_other)}')
#         missing_states = sv_other - self.sv
#         for prefix, seq in missing_states:
#             data_name = prefix + ['data', Component.from_sequence_num(seq)]
#             aio.ensure_future(self._send_data_interest(data_name))
    
#     async def _send_data_interest(self, name):
#         logging.info(f'Send data interest: {Name.to_str(name)}')
#         try:
#             _, _, content, raw_packet = await self.app.express_interest(name, must_be_fresh=False, can_be_prefix=False, need_raw_packet=True)
#         except InterestTimeout:
#             logging.warning('Data interest timeout')
#             return
#         except InterestNack as e:
#             logging.warning(f'Data interest nacked with reason={e.reason}')
#             return
#         self.name_to_data[Name.to_bytes(name)] = raw_packet
#         self.on_update(content)

#     def _on_data_interest(self, int_name, _int_param, _app_param):
#         if int_name in self.name_to_data:
#             logging.info('Put raw packet: ', int_name)
#             self.app.put_raw_packet(self.name_to_data[int_name])


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