import os
import sys
import logging
from dotenv import load_dotenv
import gitsync.db.json_encoder as json_encoder
import gitsync.db.proto as proto
from gitsync.account.account import Accounts
from gitsync.repos import GitRepos


def main():
    logging.basicConfig(format='[{asctime}]{levelname}:{message}',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.DEBUG,
                        style='{',
                        stream=sys.stderr)

    load_dotenv()
    if len(sys.argv) <= 1:
        print(f'Usage: {sys.argv[0]} <filename>', file=sys.stderr)
        exit(-1)
    filename = sys.argv[1]
    if not os.path.exists(filename):
        print(f'File does not exist: {filename}', file=sys.stderr)
        exit(-2)

    repo_path = os.path.join(os.path.abspath(os.getenv('GIT_NDN_BASEDIR')), 'git')
    git_repos = GitRepos(repo_path)
    accounts = Accounts(git_repos)

    with open(filename, 'rb') as f:
        content = f.read()
        obj, sig_ptrs = proto.parse_gitobj(content)
        if accounts.verify(sig_ptrs):
            print(json_encoder.json_encode(obj), file=sys.stdout)
        else:
            print('Unable to verify signature', file=sys.stdout)


if __name__ == '__main__':
    main()
