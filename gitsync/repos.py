import os
import typing
from git import Repo


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

    def read_file(self, repo_name, ref_name, file_name) -> bytes:
        try:
            repo = self.repos[repo_name]
        except KeyError:
            raise KeyError(0, repo_name)
        # assert repo.bare
        user_ref = None
        for ref in repo.refs:
            if ref.path == ref_name:
                user_ref = ref
                break
        if user_ref is None:
            raise KeyError(1, ref_name)  # Use enum

        try:
            tree = user_ref.commit.tree
            cert_file = tree[file_name]
        except KeyError:
            raise KeyError(2, file_name)

        return cert_file.data_stream.read()
