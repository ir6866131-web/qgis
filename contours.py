"""Geração de curvas de nível a partir de rasters de elevação no QGIS."""
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QLineEdit, QMessageBox, QVBoxLayout,
)
from qgis.core import QgsProcessing, QgsProject, QgsRasterLayer, QgsVectorLayer


class ContourDialog(QDialog):
    """Executa o algoritmo nativo de contorno e adiciona o resultado ao projeto."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Gerar curvas de nível")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.rasters = QComboBox()
        self.rasters.setToolTip(
            "Selecione um MDE/MDT ou outro raster que armazene cotas. "
            "Imagens de satélite não contêm elevação e não servem para gerar curvas de nível."
        )
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer) and layer.isValid():
                self.rasters.addItem(layer.name(), layer.id())
        if not self.rasters.count():
            self.rasters.addItem("Nenhum raster carregado", None)
        form.addRow("MDE/MDT (raster de elevação):", self.rasters)

        self.intervalo = QDoubleSpinBox()
        self.intervalo.setDecimals(3)
        self.intervalo.setRange(0.001, 1000000.0)
        self.intervalo.setValue(1.0)
        self.intervalo.setToolTip("Intervalo vertical nas unidades dos valores do raster (geralmente metros).")
        form.addRow("Equidistância (unidades do raster):", self.intervalo)

        self.campo = QLineEdit("ELEV")
        self.campo.setMaxLength(10)
        self.campo.setToolTip("Nome do campo que armazenará a cota de cada curva.")
        form.addRow("Campo de elevação:", self.campo)

        self.nome_saida = QLineEdit("Curvas de nível")
        form.addRow("Nome da camada de saída:", self.nome_saida)
        layout.addLayout(form)

        buttons = QDialogButtonBox()
        self.gerar_btn = buttons.addButton("Gerar", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        self.gerar_btn.clicked.connect(self.gerar)
        layout.addWidget(buttons)

    def gerar(self):
        layer = QgsProject.instance().mapLayer(self.rasters.currentData())
        if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
            QMessageBox.warning(self, "Raster necessário", "Carregue um raster válido de elevação no projeto.")
            return
        field = self.campo.text().strip()
        name = self.nome_saida.text().strip()
        if not field or not field.replace("_", "").isalnum() or not field[0].isalpha():
            QMessageBox.warning(self, "Campo inválido", "Use um nome de campo iniciado por letra e contendo letras, números ou _. ")
            return
        if not name:
            QMessageBox.warning(self, "Nome necessário", "Informe um nome para a camada de saída.")
            return
        try:
            import processing
            result = processing.run(
                # Curvas de nível são fornecidas pelo provedor GDAL do QGIS.
                "gdal:contour",
                {
                    "INPUT": layer,
                    "BAND": 1,
                    "INTERVAL": self.intervalo.value(),
                    "FIELD_NAME": field,
                    "CREATE_3D": False,
                    "IGNORE_NODATA": True,
                    "NODATA": None,
                    "OFFSET": 0.0,
                    "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT,
                },
            )
            output = result.get("OUTPUT")
            if isinstance(output, str):
                output = QgsVectorLayer(output, name, "ogr")
            if not isinstance(output, QgsVectorLayer) or not output.isValid():
                raise RuntimeError("O QGIS não retornou uma camada vetorial válida.")
            if output.featureCount() == 0:
                raise ValueError(
                    "Nenhuma curva foi criada. Confira se a banda selecionada contém cotas "
                    "e reduza a equidistância para ficar abaixo da variação de elevação do raster."
                )
            output.setName(name)
            QgsProject.instance().addMapLayer(output)
            self.iface.messageBar().pushSuccess(
                "Agrimensura", f"Curvas de nível geradas com intervalo de {self.intervalo.value():g}."
            )
            self.accept()
        except Exception as erro:
            QMessageBox.critical(
                self,
                "Falha na geração das curvas",
                f"{erro}\n\nConfira se o provedor Processing e o algoritmo nativo de contorno estão disponíveis.",
            )

