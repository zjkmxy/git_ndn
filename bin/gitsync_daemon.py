import sys
import logging
from dotenv import load_dotenv
from gitsync.server import Server
from ndn.app import NDNApp


async def after_start(app: NDNApp):
    server = Server(app)
    await server.start()


def main():
    logging.basicConfig(format='[{asctime}]{levelname}:{message}',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=logging.DEBUG,
                            style='{',
                            stream=sys.stderr)
    load_dotenv()
    app = NDNApp()
    app.run_forever(after_start=after_start(app))


if __name__ == '__main__':
    main()
