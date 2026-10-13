"""Verificações de geometria; executar em um Python com PyQGIS disponível."""
import importlib
import atexit
import os
import sys
import unittest
from pathlib import Path

_DLL_DIR_HANDLES = []
if os.name == "nt" and hasattr(os, "add_dll_directory"):
    raiz_qgis = Path(sys.prefix).parent.parent
    for diretorio in (
        raiz_qgis / "bin",
        raiz_qgis / "apps" / "qt5" / "bin",
        raiz_qgis / "apps" / "qgis-ltr" / "bin",
    ):
        if diretorio.is_dir():
            _DLL_DIR_HANDLES.append(os.add_dll_directory(str(diretorio)))

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsField,
    QgsGeometry, QgsPointXY, QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant


RAIZ_PLUGIN = Path(__file__).resolve().parents[1]
prefixo_qgis = os.environ.get("QGIS_PREFIX_PATH")
if not prefixo_qgis:
    candidato_prefixo = Path(sys.prefix).parent.parent / "apps" / "qgis-ltr"
    if candidato_prefixo.is_dir():
        prefixo_qgis = str(candidato_prefixo)
if prefixo_qgis:
    QgsApplication.setPrefixPath(prefixo_qgis, True)
QGIS_APP = QgsApplication([], False)
QGIS_APP.initQgis()
atexit.register(QGIS_APP.exitQgis)

sys.path.insert(0, str(RAIZ_PLUGIN.parent))
modulo_dialogo = importlib.import_module(f"{RAIZ_PLUGIN.name}.main_dialog")


class GeometryLogicTests(unittest.TestCase):
    def test_azimutes_cardinais(self):
        esperado = (
            (0, 10, '000°00\'00"'),
            (10, 0, '090°00\'00"'),
            (0, -10, '180°00\'00"'),
            (-10, 0, '270°00\'00"'),
        )
        for delta_e, delta_n, dms in esperado:
            with self.subTest(delta_e=delta_e, delta_n=delta_n):
                _, resultado = modulo_dialogo.azimute_dms(delta_e, delta_n)
                self.assertEqual(resultado, dms)

    def test_id_generico_nao_e_detectado_como_sequencia(self):
        camada = QgsVectorLayer("Point?crs=EPSG:31983", "pontos", "memory")
        camada.dataProvider().addAttributes([QgsField("id", QVariant.Int)])
        camada.updateFields()
        self.assertIsNone(modulo_dialogo.campo_ordem_automatico(camada))

    def test_campo_numerico_preserva_ordem_de_levantamento(self):
        camada = QgsVectorLayer("Point?crs=EPSG:31983", "pontos", "memory")
        camada.dataProvider().addAttributes([QgsField("ordem", QVariant.Int)])
        camada.updateFields()
        feicoes = []
        for sequencia, leste in ((3, 30), (1, 10), (2, 20)):
            feicao = QgsFeature(camada.fields())
            feicao.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(leste, 100)))
            feicao.setAttributes([sequencia])
            feicoes.append(feicao)
        self.assertTrue(camada.dataProvider().addFeatures(feicoes)[0])
        pontos, campo = modulo_dialogo.ordenar_pontos_para_poligono(
            list(camada.getFeatures()), "ordem"
        )
        self.assertEqual(campo, "ordem")
        self.assertEqual([p.x() for p in pontos], [10, 20, 30])

    def test_quadrado_tem_area_perimetro_e_azimutes_conhecidos(self):
        crs = QgsCoordinateReferenceSystem("EPSG:31983")
        pontos = [
            QgsPointXY(500000, 7000000),
            QgsPointXY(500000, 7000010),
            QgsPointXY(500010, 7000010),
            QgsPointXY(500010, 7000000),
            QgsPointXY(500000, 7000000),
        ]
        feicao = QgsFeature()
        feicao.setGeometry(QgsGeometry.fromPolygonXY([pontos]))
        dados = modulo_dialogo.processar_poligonal(feicao, crs, crs)
        self.assertAlmostEqual(dados["area_m2"], 100.0, places=6)
        self.assertAlmostEqual(dados["perimetro_m"], 40.0, places=6)
        self.assertEqual(
            [segmento["azimute_dms"] for segmento in dados["segmentos"]],
            ['000°00\'00"', '090°00\'00"', '180°00\'00"', '270°00\'00"'],
        )


if __name__ == "__main__":
    unittest.main()

