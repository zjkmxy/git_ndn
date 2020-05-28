import os
import io
import typing
from git import Repo
from gitdb.base import IStream, OStream


class GitRepos:
    base_dir: str
    repos: typing.Dict[str, Repo]  # Note: memory leak, refer to doc

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.repos = {
            f: Repo(os.path.join(base_dir, f))
            for f in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, f))
        }

    def __getitem__(self, item):
        if item not in self.repos:
            raise KeyError(0, item)
        return GitRepo(self, item)


class GitRepo:
    def __init__(self, repos, repo_name):
        self.repos = repos
        self.repo_name = repo_name

    def _get_repo(self):
        try:
            return self.repos[self.repo_name]
            # assert repo.bare
        except KeyError:
            raise KeyError(0, self.repo_name)  # Note: Use enum

    def read_file(self, ref_name, file_name) -> bytes:
        repo = self._get_repo()
        user_ref = None
        for ref in repo.refs:
            if ref.path == ref_name:
                user_ref = ref
                break
        if user_ref is None:
            raise KeyError(1, ref_name)

        try:
            tree = user_ref.commit.tree
            cert_file = tree[file_name]
        except KeyError:
            raise KeyError(2, file_name)

        return cert_file.data_stream.read()

    # This does not work for big object
    def read_obj(self, obj_name: bytes) -> typing.Tuple[str, bytes]:
        # Throws: KeyError, ValueError
        repo = self._get_repo()
        ostream = repo.odb.stream(obj_name)
        return ostream.type.decode(), ostream.read()

    def has_obj(self, obj_name: bytes) -> bool:
        repo = self._get_repo()
        return repo.odb.has_object(obj_name)

    def store_obj(self, obj_type: bytes, data: bytes):
        repo = self._get_repo()
        istream = IStream(obj_type, len(data), io.BytesIO(data))
        repo.odb.store(istream)

