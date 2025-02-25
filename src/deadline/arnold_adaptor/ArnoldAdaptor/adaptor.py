# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from deadline.client.api import get_deadline_cloud_library_telemetry_client, TelemetryClient
from openjd.adaptor_runtime._version import version as openjd_adaptor_version
from openjd.adaptor_runtime.adaptors import Adaptor, AdaptorDataValidators, SemanticVersion
from openjd.adaptor_runtime_client import Action
from openjd.adaptor_runtime.adaptors.configuration import AdaptorConfiguration
from openjd.adaptor_runtime.process import LoggingSubprocess
from openjd.adaptor_runtime.app_handlers import RegexCallback, RegexHandler
from openjd.adaptor_runtime.application_ipc import ActionsQueue, AdaptorServer
from openjd.adaptor_runtime._utils import secure_open

from .._version import version as adaptor_version

_logger = logging.getLogger(__name__)


class ArnoldNotRunningError(Exception):
    """Error that is raised when attempting to use Arnold while it is not running"""

    pass


_ARNOLD_INIT_KEYS = {
    "scene_file",
    "output_file_path",
    "error_on_arnold_license_fail",
}


def _check_for_exception(func: Callable) -> Callable:
    """
    Decorator that checks if an exception has been caught before calling the
    decorated function
    """

    def wrapped_func(self, *args, **kwargs):
        if not self._has_exception:  # Raises if there is an exception
            return func(self, *args, **kwargs)

    return wrapped_func


class ArnoldAdaptor(Adaptor[AdaptorConfiguration]):
    """
    Adaptor that creates a session in Arnold Kick to Render interactively.
    """

    _SERVER_START_TIMEOUT_SECONDS = 30
    _SERVER_END_TIMEOUT_SECONDS = 30
    _ARNOLD_START_TIMEOUT_SECONDS = 86400
    _ARNOLD_END_TIMEOUT_SECONDS = 30

    _server: AdaptorServer | None = None
    _server_thread: threading.Thread | None = None
    _arnold_client: LoggingSubprocess | None = None
    _action_queue = ActionsQueue()
    _is_rendering: bool = False

    # If a thread raises an exception we will update this to raise in the main thread
    _exc_info: Exception | None = None
    _performing_cleanup = False

    @property
    def integration_data_interface_version(self) -> SemanticVersion:
        return SemanticVersion(major=0, minor=1)

    @staticmethod
    def _get_timer(timeout: int | float) -> Callable[[], bool]:
        """
        Given a timeout length, returns a lambda which returns True until the timeout occurs
        """
        timeout_time = time.time() + timeout
        return lambda: time.time() < timeout_time

    @property
    def _has_exception(self) -> bool:
        """
        Property which checks the private _exc_info property for an exception

        :raises: self._exc_info: An exception if there is one

        :returns: False there is no exception waiting to be raised
        :return type: bool
        """
        if self._exc_info and not self._performing_cleanup:
            raise self._exc_info
        return False

    @property
    def _arnold_is_running(self) -> bool:
        """
        Property which indicates that the arnold client is running

        :returns: True if the arnold client is running, false otherwise
        :return type: bool
        """
        return self._arnold_client is not None and self._arnold_client.is_running

    @property
    def _arnold_is_rendering(self) -> bool:
        """
        Property which indicates if Arnold Kick is rendering

        :returns: True if Arnold Kick is rendering, false otherwise
        :return type: bool
        """
        return self._arnold_is_running and self._is_rendering

    @_arnold_is_rendering.setter
    def _arnold_is_rendering(self, value: bool) -> None:
        """
        Property setter which updates the private _is_rendering boolean.

        :param value: A boolean indicated if Arnold Kick is rendering.
        :type value: bool
        """
        self._is_rendering = value

    def _wait_for_socket(self) -> str:
        """
        Performs a busy wait for the socket path that the adaptor server is running on, then returns it.

        :raises: RuntimeError: If the server does not finish initializing

        :returns: The socket path the adaptor server is running on.
        :return type: str
        """
        is_not_timed_out = self._get_timer(self._SERVER_START_TIMEOUT_SECONDS)
        while (self._server is None or self._server.server_path is None) and is_not_timed_out():
            time.sleep(0.01)

        if self._server is not None and self._server.server_path is not None:
            return self._server.server_path

        raise RuntimeError(
            "Could not find a socket path because the server did not finish " "initializing"
        )

    def _start_arnold_server(self) -> None:
        """
        Starts a server with the given ActionsQueue, attaches the server to the adaptor and serves forever in a
        blocking call.
        """
        self._server = AdaptorServer(self._action_queue, self)
        _logger.debug("start arnold server")
        self._server.serve_forever()

    def _start_arnold_server_thread(self) -> None:
        """
        Starts the Arnold Kick adaptor server in a thread. Sets the environment variable "ARNOLD_ADAPTOR_SERVER_PATH" to the socket
        the server is running on after the server has finished starting.
        """
        self._server_thread = threading.Thread(
            target=self._start_arnold_server, name="ArnoldAdaptorServerThread"
        )
        self._server_thread.start()
        _logger.debug("start arnold kick server thread")
        os.environ["ARNOLD_ADAPTOR_SERVER_PATH"] = self._wait_for_socket()

    def _get_regex_callbacks(self) -> list[RegexCallback]:
        """
        Returns a list of RegexCallbacks used by the Arnold Kick Adaptor.

        :returns: List of Regex Callbacks to add
        :return type: list[RegexCallback]
        """
        callback_list = []
        completed_regexes = [re.compile("ArnoldClient: Finished Rendering Frame [0-9]+")]
        progress_regexes = [re.compile("\\[PROGRESS\\] ([0-9]+) percent")]
        error_regexes = [re.compile(".*Exception:.*|.*Error:.*|.*Warning.*")]

        callback_list.append(RegexCallback(completed_regexes, self._handle_complete))
        callback_list.append(RegexCallback(progress_regexes, self._handle_progress))
        if self.init_data.get("strict_error_checking", True):
            _logger.info("Enabling strict error checking")
            callback_list.append(RegexCallback(error_regexes, self._handle_error))

        return callback_list

    @_check_for_exception
    def _handle_complete(self, match: re.Match) -> None:
        """
        Callback for stdout that indicate completeness of a render. Updates progress to 100

        :param match: The match object from the regex pattern that has matched
        the message
        :type match: (re.Match)
        """
        self._arnold_is_rendering = False
        self.update_status(progress=100)

    @_check_for_exception
    def _handle_progress(self, match: re.Match) -> None:
        """
        Callback for stdout that indicate progress of a render.

        :param match: The match object from the regex pattern that has matched
        the message
        :type match: (re.Match)
        """
        progress = int(match.groups()[0])
        self.update_status(progress=progress)

    def _handle_error(self, match: re.Match) -> None:
        """
        Callback for stdout that indicates an error or warning.

        :param match: The match object from the regex pattern that has matched the message
        :type match: (re.Match)

        :raises: RuntimeError: Always raises a runtime error to halt the
        adaptor.
        """
        self._exc_info = RuntimeError(f"Arnold Kick Encountered an Error: {match.group(0)}")

    @property
    def arnold_client_path(self) -> str:
        """
        Obtains the arnold_client.py path by searching directories in sys.path

        :raises: FileNotFoundError: If the arnold_client.py file could not be found.

        :returns: The path to the arnold_client.py file.
        :return type: str
        """
        for dir_ in sys.path:
            path = os.path.join(dir_, "deadline", "arnold_adaptor", "ArnoldClient", "arnold_client.py")
            if os.path.isfile(path):
                return path
        raise FileNotFoundError(
            "Could not find arnold_client.py. Check that the ArnoldClient package is in one of the following directories: "
            f"{sys.path[1:]}"
        )

    def _start_arnold_client(self) -> None:
        """
        Starts the Arnold Kick client by launching Arnold Kick with the arnold_client.py file.

        Arnold Kick must be on the system PATH, for example due to a Rez environment being active.

        :raises: FileNotFoundError: If the arnold_client.py file could not be found.
        """
        regexhandler = RegexHandler(self._get_regex_callbacks())

        # Add the openjd namespace directory to PYTHONPATH, so that adaptor_runtime_client will be available
        # directly to the adaptor client.
        import openjd.adaptor_runtime_client
        import deadline.arnold_adaptor

        openjd_namespace_dir = os.path.dirname(
            os.path.dirname(openjd.adaptor_runtime_client.__file__)
        )
        deadline_namespace_dir = os.path.dirname(os.path.dirname(deadline.arnold_adaptor.__file__))
        python_path_addition = f"{openjd_namespace_dir}{os.pathsep}{deadline_namespace_dir}"
        if "PYTHONPATH" in os.environ:
            os.environ["PYTHONPATH"] = (
                f"{os.environ['PYTHONPATH']}{os.pathsep}{python_path_addition}"
            )
        else:
            os.environ["PYTHONPATH"] = python_path_addition

        # start arnold client python script
        self._arnold_client = LoggingSubprocess(
            args=["python", self.arnold_client_path],
            stdout_handler=regexhandler,
            stderr_handler=regexhandler,
        )

    def _populate_action_queue(self) -> None:
        """
        Populates the adaptor server's action queue with actions from the init_data that the Arnold Kick Client will
        request and perform. The action must be present in the _FIRST_ARNOLD_ACTIONS or _ARNOLD_INIT_KEYS set to be
        added to the action queue.
        """
        for action_name in _ARNOLD_INIT_KEYS:
            if action_name in self.init_data:
                self._action_queue.enqueue_action(self._action_from_action_item(action_name))

        # self._action_queue.enqueue_action(
        #     Action(
        #         "path_mapping",
        #         {
        #             "path_mapping_rules": {
        #                 rule.source_path: rule.destination_path for rule in self.path_mapping_rules
        #             }
        #         },
        #     )
        # )

    def on_start(self) -> None:
        """
        For job stickiness. Will start everything required for the Task.

        :raises:
          - jsonschema.ValidationError: When init_data fails validation against the adaptor schema.
          - jsonschema.SchemaError: When the adaptor schema itself is nonvalid.
          - RuntimeError: If Arnold Kick did not complete initialization actions due to an exception
          - TimeoutError: If Arnold Kick did not complete initialization actions due to timing out.
          - FileNotFoundError: If the arnold_client.py file could not be found.
        """
        # Validate init data against schema
        cur_dir = os.path.dirname(__file__)
        schema_dir = os.path.join(cur_dir, "schemas")
        validators = AdaptorDataValidators.for_adaptor(schema_dir)
        validators.init_data.validate(self.init_data)
        self.update_status(progress=0, status_message="Initializing Arnold Kick")
        self._start_arnold_server_thread()
        self._populate_action_queue()
        self._start_arnold_client()

        is_not_timed_out = self._get_timer(self._ARNOLD_START_TIMEOUT_SECONDS)
        while (
            self._arnold_is_running
            and not self._has_exception
            and len(self._action_queue) > 0
            and is_not_timed_out()
        ):
            time.sleep(0.1)  # Busy wait for Arnold Kick to finish initialization

        if len(self._action_queue) > 0:
            if is_not_timed_out():
                raise RuntimeError(
                    "Arnold Kick encountered an error and was not able to complete initialization actions."
                )
            else:
                raise TimeoutError(
                    f"Arnold Kick did not complete initialization actions in {self._ARNOLD_START_TIMEOUT_SECONDS} seconds and "
                    "failed to start."
                )

    def on_run(self, run_data: dict) -> None:
        """
        This starts a render in Arnold Kick for the given frame and performs a busy wait until the render completes.
        """
        if not self._arnold_is_running:
            raise ArnoldNotRunningError("Cannot render because Arnold Kick is not running.")

        # Validate run data against schema
        cur_dir = os.path.dirname(__file__)
        schema_dir = os.path.join(cur_dir, "schemas")
        validators = AdaptorDataValidators.for_adaptor(schema_dir)
        validators.run_data.validate(run_data)

        self._arnold_is_rendering = True
        self._action_queue.enqueue_action(Action("start_render", run_data))

        while self._arnold_is_rendering and not self._has_exception:
            time.sleep(0.1)  # wait for the render to finish

        if (
            not self._arnold_is_running and self._arnold_client
        ):  # Arnold Kick Client will always exist here. This is always
            # an error case because the Arnold Kick Client should still be running and waiting for the next command.
            # If the thread finished, then we cannot continue
            exit_code = self._arnold_client.returncode
            raise RuntimeError(
                f"Arnold Kick exited early and did not render successfully, please check render logs. Exit code {exit_code}"
            )

    def on_stop(self) -> None:
        """
        No action needed but this function must be implemented
        """
        return

    def on_cleanup(self):
        """
        Cleans up the adaptor by closing the Arnold Kick client and adaptor server.
        """
        self._performing_cleanup = True

        self._action_queue.enqueue_action(Action("close"), front=True)
        is_not_timed_out = self._get_timer(self._ARNOLD_END_TIMEOUT_SECONDS)
        while self._arnold_is_running and is_not_timed_out():
            time.sleep(0.1)
        if self._arnold_is_running and self._arnold_client:
            _logger.error(
                "Arnold Kick did not complete cleanup actions and failed to gracefully shutdown. Terminating."
            )
            self._arnold_client.terminate()

        if self._server:
            self._server.shutdown()

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=self._SERVER_END_TIMEOUT_SECONDS)
            if self._server_thread.is_alive():
                _logger.error("Failed to shutdown the Arnold Kick Adaptor server.")
        self._performing_cleanup = False

    def on_cancel(self):
        """
        Cancels the current render if Arnold Kick is rendering.
        """
        _logger.info("CANCEL REQUESTED")
        if not self._arnold_client or not self._arnold_is_running:
            _logger.info("Nothing to cancel because Arnold Kick is not running")
            return

        # Terminate immediately since the Arnold Kick client does not have a graceful shutdown
        self._arnold_client.terminate(grace_time_s=0)

    def _action_from_action_item(self, item_name: str) -> Action:
        _logger.debug(f"____action made for {item_name}_______")
        return Action(
            item_name,
            {item_name: self.init_data[item_name]},
        )
