# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

from __future__ import annotations

import os
from types import FrameType
from typing import Optional

# The Arnold Adaptor adds the `openjd` namespace directory to PYTHONPATH,
# so that importing just the adaptor_runtime_client should work.

try:
    from adaptor_runtime_client import ClientInterface  # type: ignore[import]
    from adaptor_runtime.process import LoggingSubprocess
    from adaptor_runtime.app_handlers import RegexHandler
except (ImportError, ModuleNotFoundError):
    from openjd.adaptor_runtime_client import ClientInterface  # type: ignore[import]
    from openjd.adaptor_runtime.process import LoggingSubprocess
    from openjd.adaptor_runtime.app_handlers import RegexHandler


from openjd.adaptor_runtime_client import (
    ClientInterface,
)

from deadline.arnold_adaptor.ArnoldClient.arnold_handler import ArnoldHandler


class ArnoldClient(ClientInterface):
    def __init__(self, server_path: str) -> None:
        super().__init__(server_path)
        # List of actions that can be performed by the action queue
        handler = ArnoldHandler(lambda path: self.map_path(path))
        self.actions.update(handler.action_dict)

    def close(self, args: Optional[dict] = None) -> None:
        pass

    def graceful_shutdown(self, signum: int, frame: FrameType | None):
        pass

# "kick.exe
#       -nstdin
#       -dw                                         Disable render and error report windows (recommended for batch rendering)
#       -dp                                         Disable progressive rendering (recommended for batch rendering)
#       -i <filename>                               Input scene file
#       -o <output>                                 Output filename
#       -v 6                                        Verbose level (0..6)
#       -set options.abort_on_license_fail true
# "
#
def main():
    server_path = os.environ.get("ARNOLD_ADAPTOR_SERVER_PATH")
    if not server_path:
        raise OSError(
            "ArnoldClient cannot connect to the Adaptor because the environment variable "
            "ARNOLD_ADAPTOR_SERVER_PATH does not exist"
        )

    if not os.path.exists(server_path):
        raise OSError(
            "ArnoldClient cannot connect to the Adaptor because the socket at the path defined by "
            "the environment variable ARNOLD_ADAPTOR_SERVER_PATH does not exist. Got: "
            f"{os.environ['ARNOLD_ADAPTOR_SERVER_PATH']}"
        )

    client = ArnoldClient(server_path)
    client.poll()


if __name__ == "__main__":  # pragma: no cover
    main()
