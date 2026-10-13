import os
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from .main_dialog import AgrimensuraDialog


class AgrimensuraAutomaticaPlugin:
    """Controlador mínimo do plugin carregado pelo QGIS."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(QIcon(icon_path), "Agrimensura: memorial e planta", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&Agrimensura", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("&Agrimensura", self.action)
            self.iface.removeToolBarIcon(self.action)

    def run(self):
        dialog = AgrimensuraDialog(self.iface)
        dialog.exec_()

