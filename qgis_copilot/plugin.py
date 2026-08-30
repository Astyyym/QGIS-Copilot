"""QGIS plugin lifecycle and top-level UI registration."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction

from .application.controller import ApplicationController
from .ui.chat_dock import ChatDockWidget


class QgisCopilotPlugin:
    """Register and clean up the QGIS Copilot dock widget and actions."""

    MENU_NAME = "QGIS Copilot"

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.controller = None

    def initGui(self):
        self.action = QAction("打开 QGIS Copilot", self.iface.mainWindow())
        self.action.setObjectName("QgisCopilotOpenAction")
        self.action.setStatusTip("打开 QGIS Copilot 聊天工作台")
        self.action.triggered.connect(self.show_dock)
        self.iface.addPluginToMenu(self.MENU_NAME, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.controller:
            self.controller.deactivate()
        if self.dock:
            self.dock.hide()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
        self.dock = None
        self.controller = None
        if self.action:
            self.action.triggered.disconnect(self.show_dock)
            self.iface.removePluginMenu(self.MENU_NAME, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
        self.action = None

    def show_dock(self):
        if self.dock is None:
            self.dock = ChatDockWidget(self.iface.mainWindow())
            self.dock.visibilityChanged.connect(self._on_dock_visibility_changed)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self.controller = ApplicationController(self.dock)
            self.controller.activate()
        self.dock.show()
        self.dock.raise_()

    def _on_dock_visibility_changed(self, visible: bool):
        if visible and self.controller:
            self.controller.activate()
