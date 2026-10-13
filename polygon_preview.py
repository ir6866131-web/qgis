"""Prévia e ajuste da sequência dos pontos antes de criar uma poligonal."""
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
from qgis.core import QgsGeometry, QgsPointXY


class PolygonPreviewCanvas(QWidget):
    """Desenha a poligonal e numera os pontos na ordem atual da lista."""

    def __init__(self, points, parent=None):
        super().__init__(parent)
        self.points = list(points)
        self.setMinimumSize(360, 300)

    def set_points(self, points):
        self.points = list(points)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f7f8fa"))
        if not self.points:
            return

        margem = 42.0
        largura = max(1.0, self.width() - 2 * margem)
        altura = max(1.0, self.height() - 2 * margem)
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        minimo_x, maximo_x = min(xs), max(xs)
        minimo_y, maximo_y = min(ys), max(ys)
        span_x = max(maximo_x - minimo_x, 1e-12)
        span_y = max(maximo_y - minimo_y, 1e-12)
        escala = min(largura / span_x, altura / span_y)
        desenho_largura, desenho_altura = span_x * escala, span_y * escala
        origem_x = (self.width() - desenho_largura) / 2
        origem_y = (self.height() - desenho_altura) / 2
        tela = [
            QPointF(origem_x + (p.x() - minimo_x) * escala,
                    self.height() - origem_y - (p.y() - minimo_y) * escala)
            for p in self.points
        ]

        painter.setPen(QPen(QColor("#276b3c"), 2.2))
        painter.setBrush(QColor(105, 184, 121, 55))
        painter.drawPolygon(QPolygonF(tela))

        for indice, ponto in enumerate(tela, start=1):
            painter.setPen(QPen(QColor("#174a2a"), 1.2))
            painter.setBrush(QColor("#69b879" if indice == 1 else "#ffffff"))
            painter.drawEllipse(ponto, 5.5, 5.5)
            painter.setPen(QColor("#111111"))
            painter.drawText(
                QRectF(ponto.x() - 24, ponto.y() - 26, 48, 18),
                Qt.AlignCenter, str(indice),
            )


class PolygonOrderPreviewDialog(QDialog):
    """Permite conferir e reordenar os pontos por arraste ou botões."""

    def __init__(self, points, note, parent=None):
        super().__init__(parent)
        self._points = [QgsPointXY(point) for point in points]
        self.setWindowTitle("Conferir ordem dos vértices")
        self.resize(780, 490)

        layout = QVBoxLayout(self)
        descricao = QLabel(
            note + "\nArraste os itens ou use as setas para corrigir a sequência. "
            "O vértice 1 inicia o contorno."
        )
        descricao.setWordWrap(True)
        layout.addWidget(descricao)

        corpo = QHBoxLayout()
        coluna_lista = QVBoxLayout()
        coluna_lista.addWidget(QLabel("Sequência dos pontos:"))
        self.lista = QListWidget()
        self.lista.setDragDropMode(QAbstractItemView.InternalMove)
        self.lista.setDefaultDropAction(Qt.MoveAction)
        self.lista.setDropIndicatorShown(True)
        for indice, ponto in enumerate(self._points):
            item = QListWidgetItem(
                f"Vértice {indice + 1}  |  X {ponto.x():.6f}  Y {ponto.y():.6f}"
            )
            item.setData(Qt.UserRole, indice)
            self.lista.addItem(item)
        self.lista.setCurrentRow(0)
        self.lista.model().rowsMoved.connect(self._atualizar_previa)
        coluna_lista.addWidget(self.lista)

        controles = QHBoxLayout()
        self.subir_btn = QPushButton("↑ Subir")
        self.descer_btn = QPushButton("↓ Descer")
        self.subir_btn.clicked.connect(lambda: self._mover_selecionado(-1))
        self.descer_btn.clicked.connect(lambda: self._mover_selecionado(1))
        controles.addWidget(self.subir_btn)
        controles.addWidget(self.descer_btn)
        coluna_lista.addLayout(controles)
        corpo.addLayout(coluna_lista, 1)

        self.previa = PolygonPreviewCanvas(self._points)
        corpo.addWidget(self.previa, 1)
        layout.addLayout(corpo, 1)

        botoes = QDialogButtonBox()
        usar_btn = botoes.addButton("Usar esta ordem", QDialogButtonBox.AcceptRole)
        botoes.addButton(QDialogButtonBox.Cancel)
        usar_btn.clicked.connect(self._confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def pontos_ordenados(self):
        return [
            self._points[self.lista.item(indice).data(Qt.UserRole)]
            for indice in range(self.lista.count())
        ]

    def _mover_selecionado(self, deslocamento):
        origem = self.lista.currentRow()
        destino = origem + deslocamento
        if origem < 0 or not 0 <= destino < self.lista.count():
            return
        item = self.lista.takeItem(origem)
        self.lista.insertItem(destino, item)
        self.lista.setCurrentRow(destino)
        self._atualizar_previa()

    def _atualizar_previa(self, *args):
        pontos = self.pontos_ordenados()
        for indice, ponto in enumerate(pontos, start=1):
            item = self.lista.item(indice - 1)
            item.setText(f"Vértice {indice}  |  X {ponto.x():.6f}  Y {ponto.y():.6f}")
        self.previa.set_points(pontos)

    def _confirmar(self):
        pontos = self.pontos_ordenados()
        geometria = QgsGeometry.fromPolygonXY([pontos + [pontos[0]]])
        if geometria.isNull() or geometria.isEmpty() or not geometria.isGeosValid() or geometria.area() <= 0:
            QMessageBox.warning(
                self,
                "Ordem inválida",
                "A sequência atual não forma um polígono válido. Reordene os pontos "
                "e confira o desenho antes de confirmar.",
            )
            return
        self.accept()

