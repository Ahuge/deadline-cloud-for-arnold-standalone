from qtpy import QtWidgets, QtCore

from ..data_classes import ArnoldRenderUISettings


class ArnoldSubmitterPluginWidget(QtWidgets.QWidget):
    _CHECKBOX_GROUPBOX_STYLESHEET = """QGroupBox { 
    font: bold; 
    border: 1px solid silver; 
    border-radius: 6px; 
    margin-top: 6px; 
} 
QGroupBox::title { 
    subcontrol-origin: margin; 
    left: 7px; 
    padding: 0px 5px 0px 5px; 
}"""

    _EXPORT_ALL_SHADING_GROUPS_TOOLTIP = (
        "When enabled, all shading groups are exported (or only the selected ones "
        "during export selected), even if they're not assigned to any geometry in the scene. "
        "This prevents assignment of shaders to dummy objects."
    )
    _EXPAND_PROCEDURALS_TOOLTIP = (
        "Internally, Arnold creates shape nodes from procedural nodes (usually on demand). "
        "'Expand procedurals' expands the nodes before doing the Ass export. Therefore when saving .ass file, "
        "you will get all of the nodes that have been created by the procedural."
    )
    _EXPORT_FULL_PATHS_TOOLTIP = (
        "Exports the node names with the full Maya path. For example, pSphere1|pSphereShape1 will "
        "be used instead of pSphereShape1."
    )
    _LIGHT_LINKING_TOOLTIP = (
        "Turn off light linking ('None') or use Maya's light links ('Maya Light Links'). "
        "Ensure that Light Linking is set to none when instancing lights. "
        "Otherwise, the instanced light will not render."
    )
    _SHADOW_LINKING_TOOLTIP = (
        "Shadow linking can be set to be the same as the setting for light linking ('Follows Light Linking') or you "
        "can specify explicitly that shadow linking should be turned off ('None') or use Maya's shadow "
        "linking ('Maya Shadow Links')."
    )
    _NONE = "None"
    LIGHT_LINKING_MAYA = "Maya Light Links"
    SHADOW_LINKING_FOLLOW_LIGHT = "Follows Light Linking"
    SHADOW_LINKING_MAYA = "Maya Shadow Links"

    def __init__(self, parent=None, settings=None, scene_file=None):
        super(ArnoldSubmitterPluginWidget, self).__init__(parent)
        self.settings = settings
        self._label_container = None
        self._label = None
        self._checkbox_groupbox = None

        self._export_all_shading_groups_checkbox = None
        self._expand_procedurals_checkbox = None
        self._export_full_paths_checkbox = None

        self._line = None

        self._light_Linking_label = None
        self._light_linking_combobox = None

        self._shadow_linking_label = None
        self._shadow_linking_combobox = None

        self.settings.plugins.arnold_plugin = ArnoldRenderUISettings()
        self.settings.plugins.arnold_plugin.load_sticky_settings(scene_file)

        self.build_ui()

    def get_settings(self):
        return self.settings.plugins.arnold_plugin

    @property
    def checkbox(self):
        return self._checkbox_groupbox

    def build_ui(self):
        self.setWindowTitle("Arnold Plugin")
        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(0)

        self._label_container = self._build_header_label()

        self._checkbox_groupbox = self._build_groupbox()

        self.layout().addWidget(self._label_container)
        self.layout().addWidget(self._checkbox_groupbox)

    def _build_header_label(self):
        self._label_container = QtWidgets.QWidget(self)
        self._label_container.setLayout(QtWidgets.QHBoxLayout())
        self._label_container.layout().setContentsMargins(0, 0, 0, 0)
        self._label_container.layout().setSpacing(0)
        self._label_container.layout().addStretch()
        self._label = QtWidgets.QLabel("<h2>Arnold Settings</h2>")
        self._label_container.layout().addWidget(self._label)
        self._label_container.layout().addStretch()
        return self._label_container

    def _build_groupbox(self):
        self._checkbox_groupbox = QtWidgets.QGroupBox("Export Arnold Standalone", self)
        self._checkbox_groupbox.setCheckable(True)
        self._checkbox_groupbox.setChecked(False)
        self._checkbox_groupbox.clicked.connect(self._handle_checkbox_groupbox_clicked)
        self._checkbox_groupbox.setLayout(QtWidgets.QGridLayout())
        self._checkbox_groupbox.setFlat(False)
        self._checkbox_groupbox.setStyleSheet(self._CHECKBOX_GROUPBOX_STYLESHEET)

        self._export_all_shading_groups_checkbox = self._build_shading_groups_checkbox()
        self._expand_procedurals_checkbox = self._build_expand_procedurals_checkbox()
        self._export_full_paths_checkbox = self._build_export_full_paths_checkbox()

        self._light_Linking_label, self._light_linking_combobox = self._build_light_Linking_combobox()
        self._shadow_linking_label, self._shadow_linking_combobox = self._build_shadow_Linking_combobox()

        self._line = QtWidgets.QFrame(self._checkbox_groupbox)
        self._line.setFrameShape(QtWidgets.QFrame.HLine)
        self._line.setFrameShadow(QtWidgets.QFrame.Sunken)

        _widget = QtWidgets.QWidget(self._checkbox_groupbox)
        self._checkbox_groupbox.layout().addWidget(_widget, 0, 0, 1, -1)

        self._checkbox_groupbox.layout().addWidget(self._export_all_shading_groups_checkbox, 1, 0, 1, 2)
        self._checkbox_groupbox.layout().addWidget(self._expand_procedurals_checkbox, 1, 3, 1, 2)
        self._checkbox_groupbox.layout().addWidget(self._export_full_paths_checkbox, 2, 0, 1, 2)
        self._checkbox_groupbox.layout().addWidget(self._export_full_paths_checkbox, 2, 0, 1, 2)

        self._checkbox_groupbox.layout().addWidget(self._line, 3, 0, 1, -1)

        self._checkbox_groupbox.layout().addWidget(self._light_Linking_label, 4, 0, 1, 1)
        self._checkbox_groupbox.layout().addWidget(self._light_linking_combobox, 4, 1, 1, -1)
        self._checkbox_groupbox.layout().addWidget(self._shadow_linking_label, 5, 0, 1, 1)
        self._checkbox_groupbox.layout().addWidget(self._shadow_linking_combobox, 5, 1, 1, -1)
        return self._checkbox_groupbox

    def _build_shading_groups_checkbox(self):
        self._export_all_shading_groups_checkbox = QtWidgets.QCheckBox("Export All Shading Groups", self._checkbox_groupbox)
        self._export_all_shading_groups_checkbox.setChecked(True)
        self._export_all_shading_groups_checkbox.clicked.connect(self._handle_export_all_shading_groups_clicked)
        self._export_all_shading_groups_checkbox.setToolTip(self._EXPORT_ALL_SHADING_GROUPS_TOOLTIP)
        return self._export_all_shading_groups_checkbox

    def _build_expand_procedurals_checkbox(self):
        self._expand_procedurals_checkbox = QtWidgets.QCheckBox("Expand Procedurals", self._checkbox_groupbox)
        self._expand_procedurals_checkbox.setChecked(True)
        self._expand_procedurals_checkbox.clicked.connect(self._handle_expand_procedurals_clicked)
        self._expand_procedurals_checkbox.setToolTip(self._EXPAND_PROCEDURALS_TOOLTIP)
        return self._expand_procedurals_checkbox

    def _build_export_full_paths_checkbox(self):
        self._export_full_paths_checkbox = QtWidgets.QCheckBox("Export Full Paths", self._checkbox_groupbox)
        self._export_full_paths_checkbox.setChecked(True)
        self._export_full_paths_checkbox.clicked.connect(self._handle_export_full_paths_clicked)
        self._export_full_paths_checkbox.setToolTip(self._EXPORT_FULL_PATHS_TOOLTIP)
        return self._export_full_paths_checkbox

    def _build_light_Linking_combobox(self):
        self._light_Linking_label = QtWidgets.QLabel("Light Linking")
        self._light_linking_combobox = QtWidgets.QComboBox(self._checkbox_groupbox)
        self._light_linking_combobox.addItems([self._NONE, self.LIGHT_LINKING_MAYA])
        self._light_linking_combobox.setCurrentIndex(self._light_linking_combobox.findText(self.LIGHT_LINKING_MAYA))
        self._light_linking_combobox.currentTextChanged.connect(self._handle_light_linking_currentTextChanged)
        self._light_linking_combobox.setToolTip(self._LIGHT_LINKING_TOOLTIP)
        return self._light_Linking_label, self._light_linking_combobox

    def _build_shadow_Linking_combobox(self):
        self._shadow_linking_label = QtWidgets.QLabel("Shadow Linking")
        self._shadow_linking_combobox = QtWidgets.QComboBox(self._checkbox_groupbox)
        self._shadow_linking_combobox.addItems([self._NONE, self.SHADOW_LINKING_FOLLOW_LIGHT, self.SHADOW_LINKING_MAYA])
        self._shadow_linking_combobox.setCurrentIndex(self._shadow_linking_combobox.findText(self.SHADOW_LINKING_FOLLOW_LIGHT))
        self._shadow_linking_combobox.currentTextChanged.connect(self._handle_shadow_linking_currentTextChanged)
        self._shadow_linking_combobox.setToolTip(self._SHADOW_LINKING_TOOLTIP)
        return self._shadow_linking_label, self._shadow_linking_combobox

    def _handle_checkbox_groupbox_clicked(self, checked: bool):
        self.get_settings().arnold_export = checked

    def _handle_export_all_shading_groups_clicked(self, checked: bool):
        self.get_settings().export_all_shading_groups = checked

    def _handle_expand_procedurals_clicked(self, checked: bool):
        self.get_settings().expand_procedurals = checked

    def _handle_export_full_paths_clicked(self, checked: bool):
        self.get_settings().export_full_paths = checked

    def _handle_light_linking_currentTextChanged(self, text: str):
        self.get_settings().light_linking = text

    def _handle_shadow_linking_currentTextChanged(self, text: str):
        self.get_settings().shadow_linking = text
