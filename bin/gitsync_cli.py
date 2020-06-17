import os
import sys
from dotenv import load_dotenv
from ndn.app import NDNApp
from ndn.types import InterestNack, InterestTimeout, InterestCanceled, ValidationFailure
from gitsync.sync import packet


load_dotenv()
if len(sys.argv) <= 1:
    print(f'Usage: {sys.argv[0]} <command-name> ...', file=sys.stderr)
    exit(-1)
app = NDNApp()
handlers = {}


def command_handler(func):
    handlers[func.__name__.replace('_', '-')] = func
    return func


@command_handler
async def create_repo(prefix, args):
    if len(args) < 1:
        print(f'Usage: {sys.argv[0]} create-repo <repo-name>', file=sys.stderr)
        return
    try:
        _, _, ret = await app.express_interest(
            name=prefix + '/create-project',
            app_param=args[0].encode(),
            must_be_fresh=True,
            can_be_prefix=False)
        print(bytes(ret).decode())
    except InterestNack as e:
        print(f'Nacked with reason={e.reason}')
    except InterestTimeout:
        print(f'Timeout')
    except InterestCanceled:
        print(f'NFD stopped')
    except ValidationFailure:
        print(f'Data failed to validate')


@command_handler
async def init_server(prefix, _args):
    try:
        _, _, ret = await app.express_interest(
            name=prefix + '/init-server',
            must_be_fresh=True,
            can_be_prefix=False)
        print(bytes(ret).decode())
    except InterestNack as e:
        print(f'Nacked with reason={e.reason}')
    except InterestTimeout:
        print(f'Timeout')
    except InterestCanceled:
        print(f'NFD stopped')
    except ValidationFailure:
        print(f'Data failed to validate')


@command_handler
async def add_user(prefix, args):
    if len(args) < 1:
        print(f'Usage: {sys.argv[0]} add-user <cert-file> [<email> [<full-name>]]', file=sys.stderr)
        return
    with open(args[0], 'rb') as f:
        cert = f.read()
    req = packet.AddUserReq()
    req.email = args[1] if len(args) >= 2 else None
    req.full_name = args[2] if len(args) >= 2 else None
    req.cert = cert
    try:
        _, _, ret = await app.express_interest(
            name=prefix + '/add-user',
            app_param=req.encode(),
            must_be_fresh=True,
            can_be_prefix=False)
        print(bytes(ret).decode())
    except InterestNack as e:
        print(f'Nacked with reason={e.reason}')
    except InterestTimeout:
        print(f'Timeout')
    except InterestCanceled:
        print(f'NFD stopped')
    except ValidationFailure:
        print(f'Data failed to validate')


async def main():
    prefix = os.getenv("GIT_NDN_PREFIX")
    cmd = sys.argv[1]
    try:
        await handlers[cmd](prefix, sys.argv[2:])
    except KeyError:
        print('Supported commands: create-repo init-server')
    finally:
        app.shutdown()


if __name__ == '__main__':
    app.run_forever(after_start=main())
