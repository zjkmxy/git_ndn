import os
import typing
import logging
import asyncio as aio
from ndn.app import NDNApp
from ndn.encoding import Name, Component, FormalName, InterestParam, BinaryStr
from ndn.app_support.segment_fetcher import segment_fetcher
from .packet import SyncObject
from .. import repos


HASH_LENGTH = 20
SEGMENTATION_SIZE = 4000


class ObjectFetcher:
    def __init__(self, app: NDNApp, repo: repos.GitRepo):
        self.app = app
        self.repo = repo
        self.prefix = Name.from_str(os.getenv("GIT_NDN_PREFIX") + f'/project/{repo.repo_name}/objects')
        aio.create_task(self.app.register(self.prefix, self.on_interest))

    def close(self):
        self.app.unregister(self.prefix)

    async def fetch(self, obj_type: str, obj_name: bytes):
        # Return if it exists
        if self.repo.has_obj(obj_name):
            return False
        # TODO: If the fetch fails, mark those objects
        # Fetch object
        packet_name = self.prefix + [Component.from_bytes(obj_name)]
        wire = b''.join([bytes(seg) async for seg in segment_fetcher(self.app, packet_name, must_be_fresh=False)])
        pack = SyncObject.parse(wire, ignore_critical=True)
        fetched_obj_type = bytes(pack.obj_type).decode()
        # Check type
        if obj_type and obj_type != fetched_obj_type:
            raise ValueError(f'{obj_type} is expected but get {fetched_obj_type}')
        # Write into repo TODO: Check name
        self.repo.store_obj(bytes(pack.obj_type), bytes(pack.obj_data))
        # Trigger recurisve fetching
        if obj_type == "commit":
            await self.traverse_commit(bytes(pack.obj_data))
        elif obj_type == "tree":
            await self.traverse_tree(bytes(pack.obj_data))
        elif obj_type != "blob":
            raise ValueError(f'Unknown data type {obj_type}')

    async def traverse_commit(self, content: bytes):
        lines = content.decode("utf-8").split("\n")
        for ln in lines:
            if not ln.startswith("tree") and not ln.startswith("parent"):
                break
            expect_type, hash_name = ln.split(" ")
            if expect_type == "parent":
                expect_type = "commit"
            await self.fetch(expect_type, bytes.fromhex(hash_name))

    async def traverse_tree(self, content: bytes):
        size = len(content)
        pos = 0
        while pos < size:
            name_start = content.find(b'\x00', pos)
            hash_name = content[name_start+1:name_start+HASH_LENGTH+1]
            if content[pos] == ord('1'):
                expect_type = "blob"
            else:
                expect_type = "tree"
            await self.fetch(expect_type, hash_name)
            pos = name_start + HASH_LENGTH + 1

    def on_interest(self, name: FormalName, _param: InterestParam, _app_param: typing.Optional[BinaryStr]):
        # Get the name and segment number
        if Component.get_type(name[-1]) == Component.TYPE_SEGMENT:
            obj_name = Component.get_value(name[-2])
            seg_no = Component.to_number(name[-1])
        else:
            obj_name = Component.get_value(name[-1])
            seg_no = 0
        # Read the data
        # Git objects are small so we can read the whole object
        try:
            obj_type, data = self.repo.read_obj(bytes(obj_name))
        except ValueError:
            logging.warning(f'Requested file {obj_name} does not exist in repo {self.repo.repo_name}')
            return
        # Extract the segment and calculate Name
        data_name = self.prefix + [Component.from_bytes(obj_name), Component.from_segment(seg_no)]
        start_pos = seg_no * SEGMENTATION_SIZE
        data_seg = data[start_pos:start_pos + SEGMENTATION_SIZE]
        packet_obj = SyncObject()
        packet_obj.obj_type = obj_type.encode()
        packet_obj.obj_data = data_seg
        wire = packet_obj.encode()
        final_block = (len(data) + SEGMENTATION_SIZE - 1) // SEGMENTATION_SIZE
        self.app.put_data(data_name, wire,
                          freshness_period=3600000,
                          final_block_id=Component.from_segment(final_block))
        logging.info(f'Responded {obj_name} segment {final_block} in repo {self.repo.repo_name}')
