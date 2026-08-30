"""Goal 1 UI regression tests updated for the real Goal 2 model boundary."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qgis.PyQt.QtWidgets import QApplication, QMainWindow

from qgis_copilot.application.controller import ApplicationController
from qgis_copilot.plugin import QgisCopilotPlugin
from qgis_copilot.ui.chat_dock import ChatDockWidget
from qgis_copilot.ui.view_models import ChatState


class FakeQgisInterface:
    """Minimal QGIS interface seam for lifecycle verification."""

    def __init__(self):
        self.window = QMainWindow()
        self.menu_actions = []
        self.toolbar_actions = []
        self.docks = []

    def mainWindow(self):
        return self.window

    def addPluginToMenu(self, _menu, action):
        self.menu_actions.append(action)

    def removePluginMenu(self, _menu, action):
        self.menu_actions.remove(action)

    def addToolBarIcon(self, action):
        self.toolbar_actions.append(action)

    def removeToolBarIcon(self, action):
        self.toolbar_actions.remove(action)

    def addDockWidget(self, _area, dock):
        self.docks.append(dock)
        self.window.addDockWidget(_area, dock)

    def removeDockWidget(self, dock):
        self.docks.remove(dock)
        self.window.removeDockWidget(dock)


class GoalOneWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QMainWindow()
        self.dock = ChatDockWidget(self.window)
        self.controller = ApplicationController(self.dock)
        self.controller.activate()

    def tearDown(self):
        self.controller.deactivate()
        self.dock.deleteLater()
        self.window.deleteLater()

    def test_blank_message_is_not_submitted(self):
        submitted = []
        self.dock.message_submitted.connect(submitted.append)
        self.dock.input.setText("   ")
        self.dock.send_button.click()
        self.assertEqual(submitted, [])

    def test_unconfigured_submission_opens_settings_without_fake_chat(self):
        self.dock.input.setText("当前项目有哪些图层？")
        self.dock.send_button.click()
        self.assertEqual(self.controller.view_model.messages, [])
        self.assertEqual(self.dock._state, ChatState.ERROR)
        self.assertIn("需要模型设置", self.dock.status_label.text())
        self.assertIsNotNone(self.controller._settings_dialog)
        self.controller._settings_dialog.reject()

    def test_settings_dialog_does_not_reveal_existing_secret(self):
        self.controller.show_settings()
        dialog = self.controller._settings_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.api_key.echoMode(), dialog.api_key.EchoMode.Password)
        self.assertEqual(dialog.api_key.text(), "")
        dialog.reject()

    def test_successful_save_closes_the_dialog(self):
        self.controller.show_settings()
        dialog = self.controller._settings_dialog
        dialog.set_feedback("已保存")
        dialog.accept()
        self.application.processEvents()
        self.assertIsNone(self.controller._settings_dialog)

    def test_plugin_registers_shows_and_cleans_up_actions_and_dock(self):
        iface = FakeQgisInterface()
        plugin = QgisCopilotPlugin(iface)
        plugin.initGui()
        self.assertEqual(len(iface.menu_actions), 1)
        self.assertEqual(len(iface.toolbar_actions), 1)
        plugin.action.trigger()
        self.assertEqual(len(iface.docks), 1)
        self.assertIsNotNone(plugin.dock)
        self.assertEqual(plugin.dock.objectName(), "QgisCopilotChatDock")
        plugin.dock.hide()
        plugin.show_dock()
        self.assertFalse(plugin.dock.isHidden())
        plugin.unload()
        self.assertEqual(iface.menu_actions, [])
        self.assertEqual(iface.toolbar_actions, [])
        self.assertEqual(iface.docks, [])
        iface.window.deleteLater()


if __name__ == "__main__":
    unittest.main()
