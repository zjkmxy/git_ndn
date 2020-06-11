#!/usr/bin/env python3
import os
import io
import sys
import typing
from git import Repo, Reference
from gitdb.base import IStream
from ndn.encoding import Name
from ndn.app import NDNApp
from ndn.types import InterestNack, InterestTimeout, InterestCanceled, ValidationFailure
from gitsync.sync.fetch_queue import ObjectFetcher
from gitsync.sync import packet


class GitRepo:
    def __init__(self, repo_name: str, path: str):
        self.repo_name = repo_name
        self.repo = Repo(path)

    def has_obj(self, obj_name: bytes) -> bool:
        return self.repo.odb.has_object(obj_name)

    def store_obj(self, obj_type: bytes, data: bytes) -> bytes:
        istream = IStream(obj_type, len(data), io.BytesIO(data))
        self.repo.odb.store(istream)
        return istream.binsha

    def read_obj(self, obj_name: bytes) -> typing.Tuple[str, bytes]:
        ostream = self.repo.odb.stream(obj_name)
        return ostream.type.decode(), ostream.read()

    def set_head(self, ref_name: str, head: bytes) -> Reference:
        ref = Reference.create(self.repo, ref_name, head.hex(), force=True)
        return ref


def print_out(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def parse_push(arg: str, local_repo_path: str) -> typing.Tuple[str, str, bool]:
    src, dst = arg.split(":")
    forced = src[0] == "+"
    src = src.lstrip("+")
    filename = os.path.join(local_repo_path, src)
    with open(filename, "r") as f:
        commit = f.readline().strip()

    # Indirect ref
    while commit.startswith('ref:'):
        src = commit.split(" ")[1]
        filename = os.path.join(local_repo_path, src)
        with open(filename, "r") as f:
            commit = f.readline().strip()

    print_out("PARSE-PUSH:", dst, commit, forced)
    return dst, commit, forced


async def after_start(app: NDNApp, repo_prefix: str, repo_name: str, git_repo: GitRepo, local_repo_path: str):
    options = {'cloning': False}
    handlers = {}
    running = True
    empty_cnt = 0
    refs = {}

    class CommandHandler:
        def __init__(self, name=None):
            self.name = name

        def __call__(self, func):
            name = func.__name__.replace('_', '-') if not self.name else self.name
            handlers[name] = func
            return func

    @CommandHandler()
    async def capabilities(_args):
        print("push")
        print("fetch")
        print("option")
        print("")

    @CommandHandler()
    async def option(args):
        opt_name, opt_val = args
        if opt_name == "cloning":
            options['cloning'] = (opt_val == 'true')
            print("ok")
        else:
            print("unsupported")

    @CommandHandler(name='list')
    async def list_command(_args):
        nonlocal running, refs
        try:
            _, _, data = await app.express_interest(repo_prefix + '/ref-list', must_be_fresh=True, can_be_prefix=True)
        except (InterestNack, InterestTimeout, InterestTimeout, ValidationFailure) as e:
            print_out(f"error: Cannot connect to {repo_prefix} for {type(e)}")
            running = False
            print("")
            return
        reflist = bytes(data).decode()
        print(reflist)
        if reflist.strip() == "":
            refs = {}
        else:
            refs = {
                item.split(" ")[1]: item.split(" ")[0]
                for item in reflist.strip().split("\n")
            }

    @CommandHandler()
    async def fetch(args):
        nonlocal fetcher, running, cmd
        while True:
            hash_name, ref_name = args
            new_head = bytes.fromhex(hash_name)
            # Fetch files
            try:
                await fetcher.fetch('commit', new_head)
            except (ValueError, InterestCanceled, InterestTimeout, InterestNack, ValidationFailure) as e:
                print_out(f"error: Failed to fetch commit {hash_name} for {type(e)}")
                running = False
                return
            # Set refs file
            git_repo.set_head(ref_name, new_head)
            # Batched commands
            cmd = sys.stdin.readline().rstrip("\n\r")
            if not cmd.startswith("fetch"):
                break
            args = cmd.split()[1:]
        print("")

    @CommandHandler()
    async def push(args):
        nonlocal running, cmd
        while True:
            # Parse push request
            try:
                ref_name, commit, force = parse_push(args[0], local_repo_path)
            except FileNotFoundError:
                print_out(f"error: Specified local ref not found")
                running = False
                return
            # Push Interest
            pr = packet.PushRequest()
            pr.force = force
            pr.ret_info = packet.RefInfo()
            pr.ret_info.ref_name = ref_name.encode()
            pr.ret_info.ref_head = bytes.fromhex(commit)
            pr_wire = pr.encode()
            try:
                _, _, data = await app.express_interest(
                    repo_prefix + '/push',
                    app_param=pr_wire,
                    must_be_fresh=True,
                    lifetime=600000)
                if data == b'SUCCEEDED':
                    print_out(f"OK push succeeded {ref_name}->{commit}")
                    print(f"ok {ref_name}")
                elif data == b'FAILED':
                    print_out(f"ERROR push failed {ref_name}->{commit}")
                    print(f"error {ref_name} FAILED")
                elif data == b'PENDING':
                    print_out(f"PROCESSING push not finished {ref_name}->{commit}")
                    print(f"error {ref_name} PENDING")
                else:
                    print_out(f"error: Failed to send push request {ref_name}->{commit}, unknown response")
                    running = False
                    return
            except (InterestCanceled, InterestTimeout, InterestNack, ValidationFailure) as e:
                print_out(f"ERROR cannot send push interest {ref_name}->{commit}")
                print(f"error {ref_name} DISCONNECTED")
            # Batched commands
            cmd = sys.stdin.readline().rstrip("\n\r")
            if not cmd.startswith("push"):
                break
            args = cmd.split()[1:]
        print("")

    # after_start
    try:
        fetcher = ObjectFetcher(app, git_repo, Name.from_str(repo_prefix + '/objects'))
        while empty_cnt < 2 and running:
            cmd = sys.stdin.readline().rstrip("\n\r")
            if cmd == '':
                empty_cnt += 1
            else:
                cmd = cmd.split()
                cmd_name = cmd[0]
                cmd_args = cmd[1:]
                if cmd_name in handlers:
                    await handlers[cmd_name](cmd_args)
                    sys.stdout.flush()
    except BrokenPipeError:
        pass
    finally:
        app.shutdown()


def main():
    if len(sys.argv) < 3:
        print("Usage:", sys.argv[0], "remote-name url", file=sys.stderr)
        return -1

    if 'GIT_DIR' in os.environ:
        local_repo_path = os.environ['GIT_DIR']
    else:
        local_repo_path = os.path.join(os.getcwd(), ".git")
    repo_prefix = sys.argv[2]
    repo_name = repo_prefix.split('/')[-1]
    git_repo = GitRepo(repo_name, local_repo_path)
    app = NDNApp()
    app.run_forever(after_start=after_start(app, repo_prefix, repo_name, git_repo, local_repo_path))


if __name__ == '__main__':
    main()
