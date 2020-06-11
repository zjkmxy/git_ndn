import os
import typing
import logging
import asyncio as aio
from ndn.app import NDNApp
from ndn.types import InterestCanceled, InterestTimeout, InterestNack
from ndn.encoding import Name, Component, FormalName, InterestParam, BinaryStr
from ndn.utils import timestamp
from .sync import packet
from .sync.fetch_pipeline import RepoSyncPipeline
from . import repos


class Handler:
    def __init__(self, app: NDNApp, repo: repos.GitRepo, pipeline: RepoSyncPipeline):
        self.app = app
        self.repo = repo
        self.pipeline = pipeline
        self.prefix = Name.from_str(os.getenv("GIT_NDN_PREFIX") + f'/project/{repo.repo_name}')
        aio.create_task(self.app.register(self.prefix + [Component.from_str('refs_list')], self.refs_list))
        aio.create_task(self.app.register(self.prefix + [Component.from_str('push')], self.push))

    def refs_list(self, name: FormalName, _param: InterestParam, _app_param: typing.Optional[BinaryStr]):
        ref_heads = self.repo.get_ref_heads()
        result = '\n'.join(f'{head.hex()} {ref}' for ref, head in ref_heads.items())
        result += '\n'
        logging.debug(f'On refs_list: {repr(result)}')

        data_name = name + [Component.from_timestamp(timestamp())]
        self.app.put_data(data_name, result.encode(), freshness_period=1000)

    def push(self, name: FormalName, param: InterestParam, app_param: typing.Optional[BinaryStr]):
        try:
            push_info = packet.PushRequest.parse(app_param)
        except IndexError:
            logging.warning(f'Invalid push request {Name.to_str(name)}')
            return
        ref_name = bytes(push_info.ret_info.ref_name).decode()
        ref_head = bytes(push_info.ret_info.ref_head)
        force = push_info.force
        logging.info(f'On push request: {ref_name} {ref_head.hex()}')

        task = aio.create_task(self.process_push(ref_name, ref_head, force))

        async def send_response():
            try:
                ret = await aio.wait_for(task, timeout=param.lifetime/2000.0)
                data_content = b'SUCCEEDED' if ret else b'FAILED'
            except aio.TimeoutError:
                data_content = b'PENDING'
            self.app.put_data(name, data_content, freshness_period=1000)
        aio.create_task(send_response())

    async def process_push(self, ref_name: str, ref_head: bytes, force: bool) -> bool:
        # TODO: Virtual branch refs/for/XXX
        # TODO: Avoid conflict -> cancel pipeline
        # Fetch local objects
        try:
            await self.pipeline.fetcher.fetch('commit', ref_head)
        except (ValueError, InterestCanceled, InterestTimeout, InterestNack) as e:
            logging.warning(f'Fetching error - {type(e)} {e}')
            return False
        # Force update
        if force:
            self.repo.set_head(ref_name, ref_head)
        else:
            await self.pipeline.after_update({ref_name: ref_head})
        return True
