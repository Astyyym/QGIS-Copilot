"""QGIS Copilot plugin entry point."""


def classFactory(iface):
    """Load the plugin instance created by QGIS."""
    from .plugin import QgisCopilotPlugin

    return QgisCopilotPlugin(iface)
