import typing
from ndn.app import NDNApp
from ndn.encoding import BinaryStr


class VSync:
    OnUpdateFunc = typing.Callable[[BinaryStr], None]

    def __init__(self, app: NDNApp, on_update):
        self.app = app
        self.on_update = on_update

    async def publish_update(self, content: BinaryStr):
        pass
