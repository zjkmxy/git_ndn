import typing
from git import Commit
from ..repos import GitRepo

HASH_LENGTH = 20


class Merger:
    def __init__(self, repo: GitRepo):
        self.repo = repo

    def merge_step(self, base_sha: typing.Optional[bytes], ori_sha: bytes, new_sha: bytes) -> bytes:
        # If only one side changes it, pick that one
        if ori_sha == new_sha:
            return ori_sha
        elif base_sha is not None:
            if ori_sha == base_sha:
                return new_sha
            elif new_sha == base_sha:
                return ori_sha
        # Otherwise, this must be a tree (because file merge is not supported yet)
        ori_type, ori_tree = self.repo.read_obj(ori_sha)
        new_type, new_tree = self.repo.read_obj(new_sha)
        if any(True for t in [ori_type, new_type] if t != 'tree'):
            raise ValueError('Merge conflict')
        if base_sha:
            _, base_tree = self.repo.read_obj(base_sha)
            base_dict = self.parse_tree(base_tree)
        else:
            base_dict = {}
        ori_dict = self.parse_tree(ori_tree)
        new_dict = self.parse_tree(new_tree)
        # We may assume that either original or new agrees with base on any file
        # Recursively merge
        ret_dict = {}
        common_items = ori_dict.keys() & new_dict.keys()
        for bname in common_items:
            otype, osha = ori_dict[bname]
            ntype, nsha = new_dict[bname]
            if otype != ntype:
                raise ValueError('Merge conflict')
            bsha = base_dict[bname] if bname in base_dict else None
            ret_dict[bname] = (otype, self.merge_step(bsha, osha, nsha))
        # Add new files (Note: deletion is noe supported here)
        for oname, (otype, osha) in ori_dict.items():
            if oname not in ret_dict:
                ret_dict[oname] = (otype, osha)
        for nname, (ntype, nsha) in new_dict.items():
            if nname not in ret_dict:
                ret_dict[nname] = (ntype, nsha)
        # Create the tree object and write it
        ret_content = self.encode_tree(ret_dict)
        return self.repo.store_obj(b'tree', ret_content)

    @staticmethod
    def parse_tree(content: bytes):
        size = len(content)
        pos = 0
        ret = {}
        while pos < size:
            filename_start = content.find(b' ', pos)
            binsha_start = content.find(b'\x00', pos)
            item_type = content[pos:filename_start]
            filename = content[filename_start+1:binsha_start]
            binsha = content[binsha_start+1:binsha_start+HASH_LENGTH+1]
            ret[filename] = (item_type, binsha)
            pos = binsha_start + HASH_LENGTH + 1
        return ret

    @staticmethod
    def encode_tree(tree_dic: typing.Dict[bytes, typing.Tuple[bytes, bytes]]) -> bytes:
        tree_lst = list(tree_dic.items())
        tree_lst.sort(key=lambda item: item[0].upper())
        ret = b''.join(
            ftype + b' ' + fname + b'\x00' + fsha
            for fname, (ftype, fsha) in tree_lst
        )
        return ret

    def create_commit(self, base: Commit, lhs: Commit, rhs: Commit) -> bytes:
        ret_tree = self.merge_step(base.tree.binsha, lhs.tree.binsha, rhs.tree.binsha)
        ret = ''
        ret += f'tree {ret_tree.hex()}\n'
        ret += f'parent {lhs.hexsha}\n'
        ret += f'parent {rhs.hexsha}\n'
        ret += f'\n'
        ret += 'Automatic merge\n'
        return self.repo.store_obj(b'commit', ret.encode())
