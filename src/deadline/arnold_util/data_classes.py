# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
import json

RENDER_SUBMITTER_SETTINGS_FILE_EXT = ".deadline_render_settings.arnold.json"

@dataclass
class ArnoldRenderUISettings:
    """
    Settings that the submitter UI will use
    """
    arnold_export: bool = field(default=False, metadata={"sticky": True})

    export_all_shading_groups: bool = field(default=True, metadata={"sticky": True})
    expand_procedurals: bool = field(default=True, metadata={"sticky": True})
    export_full_paths: bool = field(default=True, metadata={"sticky": True})

    light_linking: str = field(default="Maya Light Links", metadata={"sticky": True})
    shadow_linking: str = field(default="Follows Light Linking", metadata={"sticky": True})

    def load_sticky_settings(self, scene_filename: str):
        sticky_settings_filename = Path(scene_filename).with_suffix(
            RENDER_SUBMITTER_SETTINGS_FILE_EXT
        )
        if sticky_settings_filename.exists() and sticky_settings_filename.is_file():
            try:
                with open(sticky_settings_filename, encoding="utf8") as fh:
                    sticky_settings = json.load(fh)

                if isinstance(sticky_settings, dict):
                    sticky_fields = {
                        field.name: field
                        for field in dataclasses.fields(self)
                        if field.metadata.get("sticky")
                    }
                    for name, value in sticky_settings.items():
                        # Only set fields that are defined in the dataclass
                        if name in sticky_fields:
                            setattr(self, name, value)
            except (OSError, json.JSONDecodeError):
                # If something bad happened to the sticky settings file,
                # just use the defaults instead of producing an error.
                import traceback

                traceback.print_exc()
                print(
                    f"WARNING: Failed to load sticky settings file {sticky_settings_filename}, reverting to the default settings."
                )
                pass

    def save_sticky_settings(self, scene_filename: str):
        sticky_settings_filename = Path(scene_filename).with_suffix(
            RENDER_SUBMITTER_SETTINGS_FILE_EXT
        )
        with open(sticky_settings_filename, "w", encoding="utf8") as fh:
            obj = {
                field.name: getattr(self, field.name)
                for field in dataclasses.fields(self)
                if field.metadata.get("sticky")
            }
            json.dump(obj, fh, indent=1)
