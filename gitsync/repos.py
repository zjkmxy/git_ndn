import os
import io
import typing
from git import Repo, Reference, Commit
from gitdb.base import IStream
from .db import proto
from ndn import encoding as enc


class GitRepos:
    base_dir: str
    repos: typing.Dict[str, Repo]  # Note: memory leak, refer to doc

    def __init__(self, base_dir: str, bootstrap: bool = False):
        self.base_dir = base_dir
        if bootstrap:
            self.repos = {
                f: Repo.init(os.path.join(base_dir, f), bare=True)
                for f in ['All-Users.git', 'All-Projects.git']
            }
        else:
            self.repos = {
                f: Repo(os.path.join(base_dir, f))
                for f in os.listdir(base_dir)
                if os.path.isdir(os.path.join(base_dir, f))
            }

    def __getitem__(self, item):
        if item not in self.repos:
            raise KeyError(0, item)
        return GitRepo(self, item)

    def create_repo(self, name: str) -> bool:
        # TODO: Check name validity
        if name in self.repos:
            return False
        self.repos[name] = Repo.init(os.path.join(self.base_dir, name), bare=True)

    def init_server(self, signer) -> bool:
        if self.repos['All-Users.git'].refs or self.repos['All-Projects.git'].refs:
            return False
        # All-Projects.git@refs/meta/config:project.tlv
        repo = self['All-Projects.git']
        project_config = proto.ProjectConfig()
        project_config.project_id = b'All-Projects.git'
        project_config.description = b'Access inherited by all other projects.'
        project_config.sync_interval = 10
        pc_data = proto.encode(project_config, signer)
        tree = {
            'project.tlv': pc_data
        }
        commit = repo.create_init_commit(tree)
        repo.set_head('refs/meta/config', commit)
        # All-Users.git@refs/meta/config:project.tlv
        repo = self['All-Users.git']
        project_config = proto.ProjectConfig()
        project_config.project_id = b'All-Users.git'
        project_config.description = b'Individual user settings and preferences.'
        project_config.inherit_from = b'All-Projects.git'
        project_config.sync_interval = 10
        pc_data = proto.encode(project_config, signer)
        tree = {
            'project.tlv': pc_data
        }
        commit = repo.create_init_commit(tree)
        repo.set_head('refs/meta/config', commit)
        # Read trust anchor
        ta_path = os.path.abspath(os.getenv('GIT_NDN_TRUST_ANCHOR'))
        with open(ta_path, 'rb') as f:
            trust_anchor = f.read()
        # Add admin account
        self.add_account(signer, trust_anchor, None, None)
        return True

    def add_account(self, signer, cert: bytes, email: typing.Optional[str], full_name: typing.Optional[str]):
        repo = self['All-Users.git']
        # Read the cert
        ta_name, _, _, _ = enc.parse_data(cert, with_tl=True)
        user_name = bytes(enc.Component.get_value(ta_name[-5])).decode()
        key_name = bytes(enc.Component.get_value(ta_name[-3])).hex()
        # All-Users.git@refs/users/ad/admin:account.tlv+KEY
        account = proto.AccountConfig()
        account.user_id = user_name.encode()
        account.email = email.encode() if email else None
        account.full_name = full_name.encode() if full_name else None
        account_data = proto.encode(account, signer)
        tree = {
            'account.tlv': account_data,
            'KEY': {
                key_name + '.cert': cert
            }
        }
        commit = repo.create_init_commit(tree)
        repo.set_head(f'refs/users/{user_name[:2]}/{user_name}', commit)


class GitRepo:
    def __init__(self, repos, repo_name):
        self.repos = repos
        self.repo_name = repo_name

    def _get_repo(self) -> Repo:
        try:
            return self.repos.repos[self.repo_name]
            # assert repo.bare
        except KeyError:
            raise KeyError(0, self.repo_name)  # Note: Use enum

    def _get_ref(self, ref_name: str) -> Reference:
        repo = self._get_repo()
        user_ref = None
        for ref in repo.refs:
            if ref.path == ref_name:
                user_ref = ref
                break
        if user_ref is None:
            raise KeyError(1, ref_name)
        return user_ref

    def read_file(self, ref_name, file_name) -> bytes:
        user_ref = self._get_ref(ref_name)

        try:
            tree = user_ref.commit.tree
            file = tree[file_name]
        except KeyError:
            raise KeyError(2, file_name)

        return file.data_stream.read()

    # This does not work for big object
    def read_obj(self, obj_name: bytes) -> typing.Tuple[str, bytes]:
        # Throws: KeyError, ValueError
        repo = self._get_repo()
        ostream = repo.odb.stream(obj_name)
        return ostream.type.decode(), ostream.read()

    def has_obj(self, obj_name: bytes) -> bool:
        repo = self._get_repo()
        return repo.odb.has_object(obj_name)

    def store_obj(self, obj_type: bytes, data: bytes) -> bytes:
        repo = self._get_repo()
        istream = IStream(obj_type, len(data), io.BytesIO(data))
        repo.odb.store(istream)
        return istream.binsha

    def get_head(self, ref_name: str) -> bytes:
        return self._get_ref(ref_name).commit.binsha

    def set_head(self, ref_name: str, head: bytes) -> Reference:
        repo = self._get_repo()
        ref = Reference.create(repo, ref_name, head.hex(), force=True)
        return ref

    def del_ref(self, ref_name: str):
        repo = self._get_repo()
        # No exception will be thrown
        Reference.delete(repo, ref_name)

    def is_ancestor(self, ancestor: bytes, head: bytes):
        return self._get_repo().is_ancestor(ancestor.hex(), head.hex())

    def merge_base(self, head1: bytes, head2: bytes) -> Commit:
        base_list = self._get_repo().merge_base(head1.hex(), head2.hex())
        if len(base_list) != 1:
            raise ValueError('Multiple merge bases')
        else:
            return base_list[0]

    def list_commits(self, ancestor: bytes, head: bytes):
        repo = self._get_repo()
        if ancestor:
            ret = list(repo.iter_commits(f'{ancestor.hex()}..{head.hex()}'))
        else:
            ret = list(repo.iter_commits(f'{head.hex()}'))
        ret.reverse()
        return ret

    def get_commit(self, head: bytes) -> Commit:
        return Commit(self._get_repo(), head)

    def get_ref_heads(self) -> typing.Dict[str, bytes]:
        repo = self._get_repo()
        ret = {
            ref.path: ref.commit.binsha
            for ref in repo.refs
        }
        return ret

    def create_init_commit(self, tree: typing.Dict[str, typing.Union[typing.Dict, bytes]]) -> bytes:
        def generate_tree(data) -> typing.Tuple[bytes, bytes]:
            if isinstance(data, bytes):
                # Is file content
                obj_type = b'blob'
                file_mode = b'100644'
            else:
                # Is tree, first we make it into a tree file
                obj_type = b'tree'
                file_mode = b'40000'
                tree_lst = [
                    (name.encode(), generate_tree(val))
                    for name, val in data.items()
                ]
                assert isinstance(data, dict)
                tree_lst.sort(key=lambda item: item[0].upper())
                data = b''.join(
                    ftype + b' ' + fname + b'\x00' + fsha
                    for fname, (ftype, fsha) in tree_lst
                )
            return file_mode, self.store_obj(obj_type, data)
        _, tree_sha = generate_tree(tree)
        ret = ''
        ret += f'tree {tree_sha.hex()}\n'
        ret += f'\n'
        ret += 'Initial commit\n'
        return self.store_obj(b'commit', ret.encode())
