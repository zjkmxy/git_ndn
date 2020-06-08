import os
import dataclasses
from ndn.app import NDNApp
from ndn.encoding import Name
from .repos import GitRepos
from .account.account import Accounts
from .sync.fetch_queue import ObjectFetcher
from .sync.fetch_pipeline import RepoSyncPipeline
from .sync.vsync import VSync


class Server:
    @dataclasses.dataclass
    class Repo:
        vsync: VSync
        fetcher: ObjectFetcher
        pipeline: RepoSyncPipeline

    def __init__(self, app: NDNApp):
        self.app = app
        repo_path = os.path.join(os.path.abspath(os.getenv('GIT_NDN_BASEDIR')), 'git')
        self.git_repos = GitRepos(repo_path)
        self.accounts = Accounts(self.git_repos)
        self.repos = {}
        for name in self.git_repos.repos.keys():
            fetcher = ObjectFetcher(self.app, self.git_repos[name])
            pipeline = RepoSyncPipeline(fetcher, self.git_repos[name], self.accounts)
            prefix = Name.from_str(os.getenv("GIT_NDN_PREFIX") + f'/project/{name}/sync')
            vsync = VSync(self.app, pipeline.on_update, prefix, 10)
            self.repos[name] = Server.Repo(vsync, fetcher, pipeline)
            pipeline.publish_update = vsync.publish_update

    def start(self):
        for _, repo in self.repos.items():
            repo.pipeline.send_sync_update()
