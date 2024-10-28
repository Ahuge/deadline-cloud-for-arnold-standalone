# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

from __future__ import annotations

import re
import os
import subprocess
from typing import TYPE_CHECKING, Any, Callable, Dict, List
from openjd.adaptor_runtime.process import LoggingSubprocess
from openjd.adaptor_runtime.app_handlers import RegexCallback, RegexHandler
# try:
#     import arnold
# except ImportError:  # pragma: no cover
#     raise OSError("Could not find the arnold module. Are you running this inside of arnold?")


class ArnoldHandler:
    action_dict: Dict[str, Callable[[Dict[str, Any]], None]] = {}

    @property
    def continue_on_error(self) -> bool:
        return self.render_kwargs["continueOnError"]

    def __init__(self, map_path: Callable[[str], str]) -> None:
        """
        Constructor for the arnold handler. Initializes action_dict and render variables
        """
        self.action_dict = {
            "error_on_arnold_license_fail": self.set_error_on_arnold_license_fail,
            "start_render": self.start_render,
            "scene_file": self.set_scene_file,
            "output_file_path": self.set_output_file_path,
        }
        self.render_kwargs = {"continueOnError": True}
        self.scene_file = None
        self.output_path = None
        self.error_on_arnold_license_fail = "true"
        self.map_path = map_path

    def set_scene_file(self, data: dict):
        """
        Set scene file for Arnold

        :param data: The data given from the Adaptor. Keys expected: ['project_file']

        :raises: FileNotFoundError: If the file provided in the data dictionary does not exist.
        """
        self.scene_file = data.get("scene_file", "")
        if os.path.isfile(self.scene_file):
            return

        self.scene_file = self.map_path(self.scene_file)
        if not os.path.isfile(self.scene_file):
            raise FileNotFoundError(f"Error: The scene file '{self.scene_file}' does not exist")

    def set_output_file_path(self, data: dict) -> None:
        """
        Sets the output file path.

        :param data: The data given from the Adaptor. Keys expected: ['output_file_path']
        :type data: dict
        """
        self.output_path = data.get("output_file_path")
        if os.path.isfile(self.output_path):
            return

        self.output_path = self.map_path(self.output_path)

    # "kick.exe
    #       -nstdin
    #       -dw                                         Disable render and error report windows (recommended for batch rendering)
    #       -dp                                         Disable progressive rendering (recommended for batch rendering)
    #       -i <filename>                               Input scene file
    #       -o <output>                                 Output filename
    #       -v 6                                        Verbose level (0..6)
    #       -set options.abort_on_license_fail true
    def start_render(self, data: dict) -> None:
        """
        Args:
            data (dict): The data given from the Adaptor. Keys expected: ['frame']

        Raises:
            RuntimeError: If start render is called without a frame number.
        """

        frame = data.get("frame")
        kick_exe = os.environ.get("ARNOLD_ADAPTOR_KICK_EXECUTABLE", "kick")
        arguments = [
            "-nstdin",
            "-dw",
            "-dp",
            "-i", self.scene_file,
            "-o", self.output_path,
            "-frame", str(frame),
            "-v", "6",
            "-set", "options.abort_on_license_fail", self.error_on_arnold_license_fail,
        ]

        print("Calling: %s" % ([kick_exe,] + arguments))
        print(f"Rendering Frame: {frame}", flush=True)
        result = subprocess.run([kick_exe] + arguments)
        if result.returncode != 0:
            print("ArnoldClient: Error rendering with kick executable: %s" % kick_exe, flush=True)
            return
        print(f"ArnoldClient: Finished Rendering Frame {frame}\n", flush=True)

    def set_error_on_arnold_license_fail(self, data: dict) -> None:
        """
        Sets the error_on_arnold_license_fail flag to be used at render time.

        Args:
            data (dict): The data given from the Adaptor. Keys expected: ['error_on_arnold_license_fail']
        """
        self.error_on_arnold_license_fail = str(data.get("error_on_arnold_license_fail", True)).lower()
