from __future__ import annotations

import logging
import os
from pathlib import Path
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional
import yaml

from typing import Any, Optional

from deadline.client.ui.dialogs.submit_job_to_deadline_dialog import (  # type: ignore
    SubmitJobToDeadlineDialog,
    JobBundlePurpose,
)
from deadline.client.exceptions import DeadlineOperationError
from deadline.client.job_bundle._yaml import deadline_yaml_dump

from deadline.client.job_bundle.submission import AssetReferences
from deadline.client.util.ui_callback import UICallbackResponse
from deadline.client.util.callback_type import DeadlineCloudCallbackType

from deadline.maya_submitter.data_classes import RenderSubmitterUISettings

from deadline import arnold_util

from qtpy import QtWidgets, QtCore

import maya.cmds


from deadline.maya_submitter import Animation, Scene  # type: ignore
from deadline.maya_submitter.assets import AssetIntrospector
from deadline.maya_submitter.renderers import get_output_prefix_with_tokens, get_height, get_width
from deadline.maya_submitter.data_classes import (
    RenderSubmitterUISettings,
)
from deadline.maya_submitter.render_layers import (
    saved_current_render_layer,
    get_current_render_layer_name,
    get_render_layer_display_name,
    set_current_render_layer,
    get_all_renderable_render_layer_names,
    render_setup_include_all_lights,
    LayerSelection,
)
from deadline.maya_submitter.cameras import get_renderable_camera_names, ALL_CAMERAS
from deadline.maya_submitter._version import version, version_tuple as adaptor_version_tuple
from deadline.maya_submitter.ui.components.scene_settings_tab import SceneSettingsWidget
from deadline.client.job_bundle.submission import AssetReferences

from deadline.maya_submitter import logger

_LOG = logger()

@dataclass
class RenderLayerData:
    name: str
    display_name: str
    renderer_name: str
    ui_group_label: str
    frames_parameter_name: Optional[str]
    frame_range: str
    renderable_camera_names: list[str]
    output_directories: set[str]
    output_file_prefix_parameter_name: Optional[str]
    output_file_prefix: str
    image_width_parameter_name: Optional[str]
    image_height_parameter_name: Optional[str]
    image_resolution: tuple[int, int]


def _get_job_template(
    default_job_template: dict[str, Any],
    settings: RenderSubmitterUISettings,
    renderers: set[str],
    render_layers: list[RenderLayerData],
    all_layer_selectable_cameras: list[str],
    current_layer_selectable_cameras: list[str],
) -> dict[str, Any]:
    job_template = deepcopy(default_job_template)

    # Set the job's name
    job_template["name"] = settings.name

    # If there are multiple frame ranges, split up the Frames parameter by layer
    if render_layers[0].frames_parameter_name:
        # Extract the Frames parameter definition
        frame_param = [
            param for param in job_template["parameterDefinitions"] if param["name"] == "Frames"
        ][0]
        job_template["parameterDefinitions"] = [
            param for param in job_template["parameterDefinitions"] if param["name"] != "Frames"
        ]

        # Create layer-specific Frames parameters
        for layer_data in render_layers:
            layer_frame_param = deepcopy(frame_param)
            layer_frame_param["name"] = layer_data.frames_parameter_name
            layer_frame_param["userInterface"]["groupLabel"] = layer_data.ui_group_label
            job_template["parameterDefinitions"].append(layer_frame_param)

    # # If there are multiple output image formats, split that up by layer
    # if render_layers[0].output_file_prefix_parameter_name:
    #     for layer_data in render_layers:
    #         job_template["parameterDefinitions"].append(
    #             {
    #                 "name": layer_data.output_file_prefix_parameter_name,
    #                 "type": "STRING",
    #                 "userInterface": {
    #                     "control": "LINE_EDIT",
    #                     "label": "Output File Prefix",
    #                     "groupLabel": layer_data.ui_group_label,
    #                 },
    #                 "description": f"The output filename prefix for layer {layer_data.display_name}",
    #             }
    #         )
    # else:
    #     job_template["parameterDefinitions"].append(
    #         {
    #             "name": "OutputFilePrefix",
    #             "type": "STRING",
    #             "userInterface": {
    #                 "control": "LINE_EDIT",
    #                 "label": "Output File Prefix",
    #                 "groupLabel": "Arnold Settings",
    #             },
    #             "description": "The output filename prefix.",
    #         }
    #     )

    # If there are multiple output image resolutions, split that up by layer
    # if render_layers[0].image_width_parameter_name:
    #     for layer_data in render_layers:
    #         job_template["parameterDefinitions"].append(
    #             {
    #                 "name": layer_data.image_width_parameter_name,
    #                 "type": "INT",
    #                 "userInterface": {
    #                     "control": "SPIN_BOX",
    #                     "label": "Image Width",
    #                     "groupLabel": layer_data.ui_group_label,
    #                 },
    #                 "minValue": 1,
    #                 "description": f"The image width for layer {layer_data.display_name}.",
    #             }
    #         )
    #         job_template["parameterDefinitions"].append(
    #             {
    #                 "name": layer_data.image_height_parameter_name,
    #                 "type": "INT",
    #                 "userInterface": {
    #                     "control": "SPIN_BOX",
    #                     "label": "Image Height",
    #                     "groupLabel": layer_data.ui_group_label,
    #                 },
    #                 "minValue": 1,
    #                 "description": f"The image height for layer {layer_data.display_name}.",
    #             }
    #         )
    # else:
    #     job_template["parameterDefinitions"].append(
    #         {
    #             "name": "ImageWidth",
    #             "type": "INT",
    #             "userInterface": {
    #                 "control": "SPIN_BOX",
    #                 "label": "Image Width",
    #                 "groupLabel": "Arnold Settings",
    #             },
    #             "minValue": 1,
    #             "description": "The image width of the output.",
    #         }
    #     )
    #     job_template["parameterDefinitions"].append(
    #         {
    #             "name": "ImageHeight",
    #             "type": "INT",
    #             "userInterface": {
    #                 "control": "SPIN_BOX",
    #                 "label": "Image Height",
    #                 "groupLabel": "Arnold Settings",
    #             },
    #             "minValue": 1,
    #             "description": "The image height of the output.",
    #         }
    #     )

    # If we're rendering a specific camera, add the Camera job parameter
    # if settings.camera_selection != ALL_CAMERAS:
    #     selectable_cameras: list[str]
    #     if settings.render_layer_selection == LayerSelection.ALL:
    #         selectable_cameras = all_layer_selectable_cameras
    #     else:
    #         selectable_cameras = current_layer_selectable_cameras
    #
    #     camera_param = {
    #         "name": "Camera",
    #         "type": "STRING",
    #         "userInterface": {
    #             "control": "DROPDOWN_LIST",
    #             "groupLabel": "Arnold Settings",
    #         },
    #         "description": "Select which camera to render.",
    #         "allowedValues": selectable_cameras,
    #     }
    #     job_template["parameterDefinitions"].append(camera_param)

    # Replicate the default step, once per render layer, and adjust its settings
    # default_step = job_template["steps"][0]
    # job_template["steps"] = []
    # for layer_data in render_layers:
    #     step = deepcopy(default_step)
    #     job_template["steps"].append(step)
    #
    #     step["name"] = layer_data.display_name
    #
    #     parameter_space = step["parameterSpace"]
    #     # Update the 'Param.Frames' reference in the Frame task parameter
    #     if layer_data.frames_parameter_name:
    #         parameter_space["taskParameterDefinitions"][0]["range"] = (
    #             "{{Param." + layer_data.frames_parameter_name + "}}"
    #         )
    #     # # If we're submitting all cameras, create another parameter space dimension
    #     # if settings.camera_selection == ALL_CAMERAS:
    #     #     parameter_space["taskParameterDefinitions"].append(
    #     #         {
    #     #             "name": "Camera",
    #     #             "type": "STRING",
    #     #             "range": layer_data.renderable_camera_names,
    #     #         }
    #     #     )
    #     #     run_data = step["script"]["embeddedFiles"][0]
    #     #     run_data["data"] += "camera: '{{Task.Param.Camera}}'\n"
    #
    #     # Update the init data of the step
    #     init_data = step["stepEnvironments"][0]["script"]["embeddedFiles"][0]
    #     init_data["data"] = (
    #         f"render_layer: {layer_data.display_name}\n"
    #         + init_data["data"]
    #         + "output_file_prefix: '{{Param."
    #         + (layer_data.output_file_prefix_parameter_name or "OutputFilePrefix")
    #         + "}}'\n"
    #         + "image_width: {{Param."
    #         + (layer_data.image_width_parameter_name or "ImageWidth")
    #         + "}}\n"
    #         + "image_height: {{Param."
    #         + (layer_data.image_height_parameter_name or "ImageHeight")
    #         + "}}\n"
    #     )
    #     # If a specific camera is selected, link to the Camera parameter
    #     if settings.camera_selection != ALL_CAMERAS:
    #         init_data["data"] += "camera: '{{Param.Camera}}'\n"

    return job_template


def _get_parameter_values(
    settings: RenderSubmitterUISettings,
    render_layers: list[RenderLayerData],
    queue_parameters: list[dict[str, Any]],
    arnold_exported_file: str,
) -> list[dict[str, Any]]:
    parameter_values: list[dict[str, Any]] = []

    # Set the Maya scene file value
    parameter_values.append({"name": "ArnoldSceneFile", "value": arnold_exported_file})

    if render_layers[0].frames_parameter_name:
        for layer_data in render_layers:
            parameter_values.append(
                {
                    "name": layer_data.frames_parameter_name,
                    "value": layer_data.frame_range,
                }
            )
    else:
        if settings.override_frame_range:
            frame_list = settings.frame_list
        else:
            frame_list = render_layers[0].frame_range
        parameter_values.append({"name": "Frames", "value": frame_list})

    # if render_layers[0].output_file_prefix_parameter_name:
    #     for layer_data in render_layers:
    #         parameter_values.append(
    #             {
    #                 "name": layer_data.output_file_prefix_parameter_name,
    #                 "value": layer_data.output_file_prefix,
    #             }
    #         )
    # else:
    #     parameter_values.append(
    #         {"name": "OutputFilePrefix", "value": render_layers[0].output_file_prefix}
    #     )

    # if render_layers[0].image_width_parameter_name:
    #     for layer_data in render_layers:
    #         parameter_values.append(
    #             {
    #                 "name": layer_data.image_width_parameter_name,
    #                 "value": layer_data.image_resolution[0],
    #             }
    #         )
    #         parameter_values.append(
    #             {
    #                 "name": layer_data.image_height_parameter_name,
    #                 "value": layer_data.image_resolution[1],
    #             }
    #         )
    # else:
    #     parameter_values.append(
    #         {
    #             "name": "ImageWidth",
    #             "value": render_layers[0].image_resolution[0],
    #         }
    #     )
    #     parameter_values.append(
    #         {
    #             "name": "ImageHeight",
    #             "value": render_layers[0].image_resolution[1],
    #         }
    #     )

    # If we're rendering a specific camera, set the Camera parameter value
    # if settings.camera_selection != ALL_CAMERAS:
    #     parameter_values.append({"name": "Camera", "value": settings.camera_selection})

    # parameter_values.append({"name": "ProjectPath", "value": settings.project_path})
    parameter_values.append({"name": "OutputFilePath", "value": settings.output_path})
    # parameter_values.append(
    #     {
    #         "name": "RenderSetupIncludeLights",
    #         "value": "true" if render_setup_include_all_lights() else "false",
    #     }
    # )

    def ensure_arnold_options_loaded() -> None:
        try:
            maya.cmds.listAttr("defaultArnoldRenderOptions")
        except ValueError:
            try:
                from mtoa.core import createOptions

                createOptions()  # defaultArnoldRenderOptions are not created until this is called
            except ModuleNotFoundError:
                # This shouldn't be possible but we should handle it in case a customer figures out
                # a way of loading an arnold scene without mtoa
                maya.cmds.confirmDialog(
                    title="mtoa not loaded",
                    message=(
                        "Renderer is set to Arnold but mtoa is not loaded. Please load the mtoa "
                        "plugin before continuing to ensure all assets are submitted."
                    ),
                )
    ensure_arnold_options_loaded()
    parameter_values.append({
        "name": "ArnoldErrorOnLicenseFailure",
        "value": maya.cmds.getAttr("defaultArnoldRenderOptions.abortOnLicenseFail")
    })

    # Check for any overlap between the job parameters we've defined and the
    # queue parameters. This is an error, as we weren't synchronizing the values
    # between the two different tabs where they came from.
    parameter_names = {param["name"] for param in parameter_values}
    queue_parameter_names = {param["name"] for param in queue_parameters}
    parameter_overlap = parameter_names.intersection(queue_parameter_names)
    if parameter_overlap:
        raise DeadlineOperationError(
            "The following queue parameters conflict with the Arnold job parameters:\n"
            + f"{', '.join(parameter_overlap)}"
        )

    parameter_values.extend(
        {"name": param["name"], "value": param["value"]} for param in queue_parameters
    )

    return parameter_values


class ArnoldPlugin(DeadlineCloudCallbackType):
    """
    This plugin will
    """

    def __init__(self):
        super(ArnoldPlugin, self).__init__()
        self.checkbox = None
        self.label = None

    def on_ui_callback(
            self,
            dialog: SubmitJobToDeadlineDialog,
            settings: object,
            asset_references: AssetReferences,
            host_requirements: Optional[dict[str, Any]] = None,
    ) -> UICallbackResponse:
        widget = QtWidgets.QWidget(dialog)
        widget.setWindowTitle("Arnold Plugin")
        widget.setLayout(QtWidgets.QVBoxLayout())
        widget.layout().setContentsMargins(0, 0, 0, 0)
        widget.layout().setSpacing(0)

        self._label_widget = QtWidgets.QWidget(widget)
        self._label_widget.setLayout(QtWidgets.QHBoxLayout())
        self._label_widget.layout().setContentsMargins(0, 0, 0, 0)
        self._label_widget.layout().setSpacing(0)
        self._label_widget.layout().addStretch()
        self.label = QtWidgets.QLabel("<h1>Arnold Settings</h1>")
        self._label_widget.layout().addWidget(self.label)
        self._label_widget.layout().addStretch()

        self.checkbox = QtWidgets.QCheckBox("Export Arnold Standalone", widget)

        widget.layout().addWidget(self._label_widget)
        widget.layout().addWidget(self.checkbox)
        return UICallbackResponse(
            settings=settings,
            asset_references=asset_references,
            host_requirements=host_requirements,
            job_specific_ui=widget,
        )

    def on_create_job_bundle_callback(
        self,
        widget: SubmitJobToDeadlineDialog,
        job_bundle_dir: str,
        settings: RenderSubmitterUISettings,
        queue_parameters: list[dict[str, Any]],
        asset_references: AssetReferences,
        host_requirements: Optional[dict[str, Any]] = None,
        purpose: JobBundlePurpose = JobBundlePurpose.SUBMISSION,
    ) -> None:
        if not self.checkbox.isChecked():
            _LOG.info("Arnold Export checkbox is not checked. Nothing to do...")
            return

        with open(Path(arnold_util.__file__).parent / "default_arnold_job_template.yaml") as fh:
            default_job_template = yaml.safe_load(fh)

        # Create a dictionary for the layers, and accumulate data about each layer
        render_layer_names = get_all_renderable_render_layer_names()
        if not render_layer_names:
            raise DeadlineOperationError(
                "No render layer is set as renderable. At least one must be renderable to submit a job."
            )

        render_layers: list[RenderLayerData] = []
        with saved_current_render_layer():
            for render_layer_name in render_layer_names:
                set_current_render_layer(render_layer_name)

                display_name = get_render_layer_display_name(render_layer_name)
                renderer_name = Scene.renderer()
                renderable_camera_names = get_renderable_camera_names()
                output_directories: set[str] = set()
                for camera_name in renderable_camera_names:
                    output_directories.update(
                        Scene.get_output_directories(render_layer_name, camera_name)
                    )
                output_file_prefix = get_output_prefix_with_tokens()
                image_resolution = (get_width(), get_height())

                render_layers.append(
                    RenderLayerData(
                        name=render_layer_name,
                        display_name=display_name,
                        renderer_name=renderer_name,
                        ui_group_label=f"Layer {display_name} Settings ({renderer_name} renderer)",
                        frames_parameter_name=None,
                        frame_range=str(Animation.frame_list()),
                        renderable_camera_names=renderable_camera_names,
                        output_directories=output_directories,
                        output_file_prefix_parameter_name=None,
                        output_file_prefix=output_file_prefix,
                        image_width_parameter_name=None,
                        image_height_parameter_name=None,
                        image_resolution=image_resolution,
                    )
                )

        # Sort the layers by name
        render_layers.sort(key=lambda layer: layer.display_name)
        # Tell the settings tab the selectable cameras when only the current layer is in the job
        current_layer_selectable_cameras: list[str] = get_renderable_camera_names()
        # Tell the settings tab the selectable cameras when all layers are in the job
        all_layer_selectable_cameras_set: set[str] = set(render_layers[0].renderable_camera_names)
        for layer in render_layers:
            all_layer_selectable_cameras_set = all_layer_selectable_cameras_set.intersection(
                layer.renderable_camera_names
            )
        all_layer_selectable_cameras: list[str] = list(sorted(all_layer_selectable_cameras_set))

        # if submitting, warn if the current scene has been modified
        scene_modified = maya.cmds.file(q=True, mf=True) == 1
        if scene_modified and purpose == JobBundlePurpose.SUBMISSION:
            scene_name = maya.cmds.file(q=True, sn=True)
            button = maya.cmds.confirmDialog(
                title="Warning: Scene Changes not Saved",
                message=("Save scene to %s before submitting?" % scene_name),
                button=["Yes", "No"],
                defaultButton="No",
                cancelButton="No",
                dismissString="No",
            )
            if button == "Yes":
                maya.cmds.file(save=True)

        job_bundle_path = Path(job_bundle_dir)

        # If we're only submitting the current layer, filter our list of layers by that
        if settings.render_layer_selection == LayerSelection.CURRENT:
            current_render_layer_name = get_current_render_layer_name()
            submit_render_layers = [
                layer for layer in render_layers if layer.name == current_render_layer_name
            ]
            if not submit_render_layers:
                raise DeadlineOperationError(
                    f"The current render layer, {current_render_layer_name}, is not set as renderable. It must be renderable to submit as a job."
                )
        else:
            submit_render_layers = render_layers

        # Check if there are multiple frame ranges across the layers
        first_frame_range = submit_render_layers[0].frame_range
        per_layer_frames_parameters = not settings.override_frame_range and any(
            layer.frame_range != first_frame_range for layer in submit_render_layers
        )

        # If there are multiple frame ranges and we're not overriding the range,
        # then we create per-layer Frames parameters.
        if per_layer_frames_parameters:
            for layer_data in submit_render_layers:
                layer_data.frames_parameter_name = f"{layer_data.display_name}Frames"

        first_output_file_prefix = submit_render_layers[0].output_file_prefix
        per_layer_output_file_prefix = any(
            layer.output_file_prefix != first_output_file_prefix for layer in submit_render_layers
        )

        if per_layer_output_file_prefix:
            for layer_data in submit_render_layers:
                layer_data.output_file_prefix_parameter_name = (
                    f"{layer_data.display_name}OutputFilePrefix"
                )

        first_image_resolution = submit_render_layers[0].image_resolution
        per_layer_image_resolution = any(
            layer.image_resolution != first_image_resolution for layer in submit_render_layers
        )

        if per_layer_image_resolution:
            for layer_data in submit_render_layers:
                layer_data.image_width_parameter_name = f"{layer_data.display_name}ImageWidth"
                layer_data.image_height_parameter_name = f"{layer_data.display_name}ImageHeight"

        renderers: set[str] = {layer_data.renderer_name for layer_data in submit_render_layers}

        from maya import cmds
        tempdir = tempfile.mkdtemp()
        sceneNameLong = cmds.file(q=True, sn=True)

        temp_path = os.path.join(
            tempdir, os.path.splitext(os.path.basename(sceneNameLong))[0] + ".ass"
        )
        arnold_ass_path = os.path.join(
            tempdir, os.path.splitext(os.path.basename(sceneNameLong))[0] + ".ass"
        )
        _LOG.info("     Camera Selection: %s" % settings.camera_selection)
        if settings.camera_selection == "ALL_CAMERAS":
            raise DeadlineOperationError(
                "Arnold Plugin currently does not support ALL_CAMERAS. Please pick a single camera."
            )
        _LOG.info("     Render Layer Selection: %s" % settings.render_layer_selection)
        if settings.render_layer_selection != LayerSelection.CURRENT:
            raise DeadlineOperationError(
                "Arnold Plugin currently does not support all render layers. Please pick a CURRENT."
            )

        cmds.arnoldExportAss(
            filename=arnold_ass_path,
            exportAllSharingGroups=True,
            mask=14591,
            lightLinks=True,
            shadowLinks=True,
            expandProdcedurals=True,
            fullPath=True,
            cam=settings.camera_selection
        )

        job_template = _get_job_template(
            default_job_template=default_job_template,
            settings=settings,
            renderers=renderers,
            render_layers=submit_render_layers,
            all_layer_selectable_cameras=all_layer_selectable_cameras,
            current_layer_selectable_cameras=current_layer_selectable_cameras,
        )
        parameter_values = _get_parameter_values(
            settings=settings,
            render_layers=submit_render_layers,
            queue_parameters=queue_parameters,
            arnold_exported_file=arnold_ass_path,
        )

        # If "HostRequirements" is provided, inject it into each of the "Step"
        if host_requirements:
            # for each step in the template, append the same host requirements.
            for step in job_template["steps"]:
                step["hostRequirements"] = host_requirements

        with open(job_bundle_path / "template.yaml", "w", encoding="utf8") as f:
            deadline_yaml_dump(job_template, f, indent=1)

        with open(job_bundle_path / "parameter_values.yaml", "w", encoding="utf8") as f:
            deadline_yaml_dump({"parameterValues": parameter_values}, f, indent=1)

        with open(job_bundle_path / "asset_references.yaml", "w", encoding="utf8") as f:
            deadline_yaml_dump(asset_references.to_dict(), f, indent=1)

        # Save Sticky Settings
        attachments: AssetReferences = widget.job_attachments.attachments
        settings.input_filenames = sorted(attachments.input_filenames)
        settings.input_directories = sorted(attachments.input_directories)
        settings.input_filenames = sorted(attachments.input_filenames)

        settings.save_sticky_settings(Scene.name())

    def on_create_job_bundle_callback_old(
            self,
            widget: SubmitJobToDeadlineDialog,
            job_bundle_dir: str,
            settings: object,
            queue_parameters: list[dict[str, Any]],
            asset_references: AssetReferences,
            host_requirements: Optional[dict[str, Any]] = None,
            purpose: JobBundlePurpose = JobBundlePurpose.SUBMISSION,
    ) -> None:
        if not self.checkbox.isChecked():
            return

        from maya import cmds
        tempdir = tempfile.mkdtemp()
        sceneNameLong = cmds.file(q=True, sn=True)

        arnold_ass_path = os.path.join(
            tempdir, os.path.splitext(os.path.basename(sceneNameLong))[0] + ".ass"
        )
        arnold_ass_path = os.path.splitext(sceneNameLong)[0] + ".ass"
        cmds.arnoldExportAss(
            filename=arnold_ass_path,
            exportAllSharingGroups=True,
            mask=14591,
            lightLinks=True,
            shadowLinks=True,
            expandProdcedurals=True,
            fullPath=True,
            # cam="perspShape"
        )

        job_bundle_path = Path(job_bundle_dir)
        job_template = _get_job_template(settings)

        # If "HostRequirements" is provided, inject it into each of the "Step"
        if host_requirements:
            # for each step in the template, append the same host requirements.
            for step in job_template["steps"]:
                step["hostRequirements"] = host_requirements

        parameter_values = _get_parameter_values(
            settings=settings,
            render_layers=render_layter_date,
            queue_parameters=queue_parameters,
            arnold_exported_file=arnold_ass_path
        )

        with open(job_bundle_path / "template.yaml", "w", encoding="utf8") as f:
            deadline_yaml_dump(job_template, f, indent=1)

        with open(job_bundle_path / "parameter_values.yaml", "w", encoding="utf8") as f:
            deadline_yaml_dump({"parameterValues": parameter_values}, f, indent=1)

        with open(job_bundle_path / "asset_references.yaml", "w", encoding="utf8") as f:
            deadline_yaml_dump(asset_references.to_dict(), f, indent=1)

        # Save Sticky Settings
        attachments: AssetReferences = widget.job_attachments.attachments
        settings.input_filenames = sorted(attachments.input_filenames)
        settings.input_directories = sorted(attachments.input_directories)
        settings.output_directories = sorted(attachments.output_directories)

    def on_post_submit_callback(self, job_id: str) -> None:
        pass
