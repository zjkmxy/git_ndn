import typing
from ndn.app import NDNApp
from ndn.encoding import BinaryStr, FormalName


class VSync:
    OnUpdateFunc = typing.Callable[[BinaryStr], None]

    def __init__(self, app: NDNApp, on_update, prefix: FormalName, interval: int):
        self.app = app
        self.on_update = on_update
        self.prefix = prefix
        self.interval = interval

    async def publish_update(self, content: BinaryStr):
        pass
