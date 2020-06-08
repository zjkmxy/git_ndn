import logging
import typing as typ
import asyncio as aio
from git import GitCommandError, Commit
from ndn import encoding as enc
from ndn.types import InterestCanceled, InterestTimeout, InterestNack
from . import packet
from .fetch_queue import ObjectFetcher
from ..repos import GitRepo
from ..account.account import Accounts
from ..db import proto
from .merger import Merger


class RepoSyncPipeline:
    def __init__(self, fetcher: ObjectFetcher, repo: GitRepo, accounts: Accounts):
        self.fetcher = fetcher
        self.repo = repo
        self.accounts = accounts
        self.publish_update = None
        self.updated = False

    def on_update(self, data: enc.BinaryStr):
        try:
            update = packet.SyncUpdate.parse(data)
        except (enc.DecodeError, IndexError) as e:
            logging.warning(f'Invalid sync update - {e}')
            return
        ref_updates = {
            bytes(ref_info.ref_name).decode(): bytes(ref_info.ref_head)
            for ref_info in update.ref_into
        }
        logging.debug(f'On Sync Update {ref_updates}')
        aio.create_task(self.after_update(ref_updates))

    async def after_update(self, ref_updates: typ.Dict[str, bytes]):
        self.updated = False
        # TODO: Handle refs/changes-hash
        for name, head in ref_updates.items():
            # Fetch the head
            try:
                await self.fetcher.fetch('commit', head)
            except (ValueError, InterestCanceled, InterestTimeout, InterestNack) as e:
                logging.warning(f'Fetching error - {type(e)} {e}')
                continue
            # TODO: If this is bmeta, fetch refs/head/*
            pass
            # Linear update: compare history
            ret = await self.linear_update(name, head)
            # Merge update: for append-only branches
            if not ret and self.is_mergable_branch(name):
                ret = await self.merge_update(name, head)
            # TODO: If this is bmeta, reset refs/head/*
        # Set Sync update
        if self.updated:
            self.send_sync_update()

    async def linear_update(self, name: str, new_head: bytes) -> bool:
        # Try to get the original head
        try:
            ori_head = self.repo.get_head(name)
        except KeyError as e:
            # New ref, iteratively set it
            if e.args[0] == 1:
                ori_head = None
            else:
                # Not existing repo -> pass out and shutdown the program
                raise
        # Return if cannot set directly
        if ori_head:
            try:
                if not self.repo.is_ancestor(ori_head, new_head):
                    return False
            except GitCommandError as e:
                logging.error(f'Fetched commit is not recognized - {e}')
                return False
        # Immutable branch: ignore the change
        if self.is_immutable_branch(name) and ori_head:
            return True
        # Same commit
        if ori_head == new_head:
            return True
        # Update one by one and do security check
        commits = self.repo.list_commits(ori_head, new_head)
        for i, commit in enumerate(commits):
            if not await self.security_check(name, commit):
                break
            else:
                logging.debug(f'Set head -> {new_head.hex()}')
                # We have to write to the disk because new certs may be added here
                self.repo.set_head(name, commits[i].binsha)
        self.updated = True
        return True

    async def merge_update(self, name: str, new_head: bytes):
        ori_head = self.repo.get_head(name)
        ori_commit = self.repo.get_commit(ori_head)
        new_commit = self.repo.get_commit(new_head)
        # If they are equal, randomly pick one
        if ori_commit.tree.binsha == new_commit.tree.binsha:
            if ori_head < new_head:
                self.repo.set_head(name, new_head)
            self.updated = True
            return True
        # A common base is required (as XxxConfig.tlv is necessary)
        try:
            merge_base = self.repo.merge_base(ori_head, new_head)
        except ValueError as e:
            logging.warning(f'No common base for merge {name} {new_head}->{ori_head}: {e}')
            return False
        # Do security check one by one
        # We do not handle certs because it's too difficult
        last = ori_commit
        commits = self.repo.list_commits(merge_base.binsha, new_head)
        for i, commit in enumerate(commits):
            if not await self.security_check(name, commit):
                break
            elif not await self.mergability_check(merge_base, ori_commit, new_commit):
                break
            else:
                last = commit
        # If it is mergable, merge
        if last != ori_commit:
            logging.fatal(f'Not implemented: automerge {last.hexsha} {ori_commit.hexsha}')
        ret = Merger(self.repo).create_commit(merge_base, ori_commit, new_commit)
        self.repo.set_head(name, ret)
        self.updated = True
        return True

    async def security_check(self, name: str, commit: Commit) -> bool:
        # Signed tlv files
        if not self.check_signatures(name, commit):
            return False
        # Check user branch
        if name.startswith('refs/users/'):
            if not self.check_user_branch(name, commit):
                return False
        # Check change meta branch
        if self.is_change_meta_branch(name):
            if not self.check_change_meta_branch(name, commit):
                return False
        # TODO: Do we need more?
        return True

    async def mergability_check(self, merge_base: Commit, lhs: Commit, rhs: Commit):
        for file in merge_base.tree.traverse():
            if file.type != 'blob':
                continue
            path = file.path
            try:
                lfile = lhs.tree[path].binsha
                rfile = rhs.tree[path].binsha
            except KeyError:
                # A file is missing in one branch
                return False
            if lfile != file.binsha and rfile != file.binsha:
                # Both changed to a file
                return False
        return True

    @staticmethod
    def is_immutable_branch(name: str):
        # refs/changes/<__>/<Change-ID>/<PatchSet>
        return name.startswith('refs/changes/') and name.split('/')[-1] != 'meta'

    @staticmethod
    def is_code_branch(name: str):
        return RepoSyncPipeline.is_immutable_branch(name) or name.startswith('refs/heads/')

    @staticmethod
    def is_change_meta_branch(name: str):
        # refs/changes/<__>/<Change-ID>/<PatchSet>
        return name.startswith('refs/changes/') and name.split('/')[-1] == 'meta'

    @staticmethod
    def is_mergable_branch(name: str):
        # In this version we don't have time to handle catalog and group branch
        # For the two branches below, appending is adding files
        return name.startswith('refs/users/') or RepoSyncPipeline.is_change_meta_branch(name)

    def check_signatures(self, name: str, commit: Commit) -> bool:
        # No need to check signature for code branch
        if self.is_code_branch(name):
            return True
        # Verify every tlv file
        for file in commit.tree.traverse():
            # Verify tlv and cert files only
            is_tlv = file.name.endswith('.tlv')
            is_cert = file.name.endswith('.cert')
            if not is_tlv and not is_cert:
                continue
            # Verify the signature without considering the signer
            wire = file.data_stream.read()
            try:
                if is_tlv:
                    _, sig_ptrs = proto.parse_gitobj(wire)
                else:
                    _, _, _, sig_ptrs = enc.parse_data(wire, with_tl=True)
            except (ValueError, IndexError, TypeError, enc.DecodeError) as e:
                logging.error(f'Malformed file {name}@{file.name} - {e}')
                return False
            if not self.accounts.verify(sig_ptrs):
                logging.error(f'Unable to verify the signature {name}@{file.name}')
                return False
        return True

    def check_user_branch(self, name: str, commit: Commit) -> bool:
        # AccountConfig.tlv
        wire = commit.tree['account.tlv'].data_stream.read()
        config, _ = proto.parse(wire)
        if not isinstance(config, proto.AccountConfig):
            logging.error(f'File {name}@account.tlv is not of type AccountConfig')
            return False
        expected_user = name.split('/')[-1]
        if bytes(config.user_id).decode() != expected_user:
            logging.error(f'File {name}@account.tlv does not belong to user {expected_user}')
            return False
        # TODO: Signer privilege; certificates are immutable
        return True

    def check_change_meta_branch(self, name: str, commit: Commit) -> bool:
        # TODO: Check privilege; comments are immutable
        return True

    def send_sync_update(self):
        if not self.publish_update:
            return
        update = packet.SyncUpdate()
        update.ref_into = []
        heads = self.repo.get_ref_heads()
        for ref, head in heads.items():
            ref_info = packet.RefInfo()
            ref_info.ref_name = ref.encode()
            ref_info.ref_head = head
            update.ref_into.append(ref_info)
        self.publish_update(update.encode())
