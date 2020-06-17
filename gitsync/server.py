import os
import typing
import logging
import dataclasses
from ndn.app import NDNApp
from ndn.encoding import Name, FormalName, InterestParam, BinaryStr
from ndn.security import TpmFile
from .repos import GitRepos
from .account.account import Accounts
from .sync.fetch_queue import ObjectFetcher
from .sync.fetch_pipeline import RepoSyncPipeline
from .sync.vsync import VSync
from .sync import packet
from .handler import Handler


class Server:
    @dataclasses.dataclass
    class Repo:
        vsync: VSync
        fetcher: ObjectFetcher
        pipeline: RepoSyncPipeline
        handler: Handler

    def __init__(self, app: NDNApp):
        self.app = app
        tpm = TpmFile(os.path.abspath(os.getenv('GIT_NDN_TPM')))
        self.signer = tpm.get_signer(os.getenv('GIT_NDN_KEY'))
        repo_path = os.path.join(os.path.abspath(os.getenv('GIT_NDN_BASEDIR')), 'git')
        if not os.path.exists(repo_path):
            os.makedirs(repo_path)
            self.git_repos = GitRepos(repo_path, bootstrap=True)
        else:
            self.git_repos = GitRepos(repo_path, bootstrap=False)
        self.accounts = Accounts(self.git_repos)
        self.accounts.read_trust_anchor()
        self.repos = {}
        for name in self.git_repos.repos.keys():
            self.repos[name] = self.init_repo_pipelines(name)

    async def start(self):
        await self.app.register(os.getenv("GIT_NDN_PREFIX") + '/create-project', self.create_project)
        await self.app.register(os.getenv("GIT_NDN_PREFIX") + '/init-server', self.init_server)
        await self.app.register(os.getenv("GIT_NDN_PREFIX") + '/add-user', self.add_user)
        for _, repo in self.repos.items():
            repo.pipeline.send_sync_update()

    def init_repo_pipelines(self, name: str):
        objects_prefix = Name.from_str(os.getenv("GIT_NDN_PREFIX") + f'/project/{name}/objects')
        fetcher = ObjectFetcher(self.app, self.git_repos[name], objects_prefix)
        pipeline = RepoSyncPipeline(fetcher, self.git_repos[name], self.accounts)
        sync_prefix = Name.from_str(os.getenv("GIT_NDN_PREFIX") + f'/project/{name}/sync')
        # TODO: Parse the config and change to real time
        vsync = VSync(self.app, pipeline.on_update, sync_prefix, 10)
        pipeline.publish_update = vsync.publish_update
        logging.info(f'Start sync on repo: {name}')
        handler = Handler(self.app, self.git_repos[name], pipeline)
        return Server.Repo(vsync, fetcher, pipeline, handler)

    def create_project(self, name: FormalName, _param: InterestParam, app_param: typing.Optional[BinaryStr]):
        repo_name = bytes(app_param).decode()
        logging.info(f'Create repo: {repo_name} ...')
        ret = self.git_repos.create_repo(repo_name)
        if ret:
            self.repos[repo_name] = self.init_repo_pipelines(repo_name)
        data_content = b'SUCCEEDED' if ret else b'FAILED'
        self.app.put_data(name, data_content, freshness_period=1000)

    def init_server(self, name: FormalName, _param: InterestParam, _app_param: typing.Optional[BinaryStr]):
        ret = self.git_repos.init_server(self.signer)
        data_content = b'SUCCEEDED' if ret else b'FAILED'
        self.app.put_data(name, data_content, freshness_period=10000)

    def add_user(self, name: FormalName, _param: InterestParam, app_param: typing.Optional[BinaryStr]):
        try:
            req = packet.AddUserReq.parse(app_param)
        except IndexError:
            logging.warning(f'Invalid add user request {Name.to_str(name)}')
            return
        if not req.cert:
            logging.warning(f'Invalid add user request {Name.to_str(name)}')
            return
        ret = self.git_repos.add_account(self.signer, req.cert, req.email, req.full_name)
        data_content = b'SUCCEEDED' if ret else b'FAILED'
        self.app.put_data(name, data_content, freshness_period=10000)
