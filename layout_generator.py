"""Geração de planta técnica em QgsPrintLayout."""
from datetime import date
import math
import re
import textwrap
import uuid
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF
from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel,
    QgsLayoutItemPolygon, QgsLayoutItemShape, QgsLayoutItemScaleBar,
    QgsLayoutItemLegend, QgsLayoutItemMapGrid,
    QgsLayoutItemAttributeTable, QgsLayoutFrame, QgsLayoutItemPage,
    QgsLayoutMultiFrame, QgsLayoutItem, QgsLayoutPoint,
    QgsLayoutSize, QgsUnitTypes, QgsVectorLayer, QgsField, QgsFeature,
    QgsGeometry, QgsPoint, QgsPointXY, QgsRectangle, QgsLayoutExporter, QgsWkbTypes,
    QgsFillSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer,
    QgsLineSymbol, QgsTextFormat, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QPolygonF
from .magnetic_model import declinacao_magnetica

COR_PRIMARIA = QColor("#111111")
COR_DESTAQUE = QColor("#69B879")
COR_LIMITE = QColor("#D7191C")
COR_PAINEL = QColor("#FFFFFF")
COR_BORDA = QColor("#111111")
COR_MOLDURA_MAPA = QColor("#111111")
COR_TEXTO = QColor("#111111")
MARCADOR_CAMADA_TEMPORARIA = "agrimensura/layout_temporario"
LARGURA_MAPA_PRINCIPAL_MM = 245.0


def _remover_camadas_temporarias(projeto):
    """Remove as camadas auxiliares criadas pela planta anterior."""
    for camada in list(projeto.mapLayers().values()):
        if camada.customProperty(MARCADOR_CAMADA_TEMPORARIA, False):
            projeto.removeMapLayer(camada.id())


def _adicionar_rotulo(
    layout, texto, x, y, largura, altura, tamanho=9, negrito=False, moldura=False,
    alinhamento=Qt.AlignLeft, fundo=None, cor_texto=None,
    alinhamento_vertical=Qt.AlignVCenter,
):
    item = QgsLayoutItemLabel(layout)
    item.setText(texto)
    fonte = QFont("Arial")
    # A planta é um documento técnico: textos menores ficam difíceis de ler
    # quando impressos. Os quadros compactos abaixo acomodam este mínimo.
    fonte.setPointSizeF(max(float(tamanho), 7.0))
    fonte.setBold(negrito)
    item.setFont(fonte)
    item.setFontColor(cor_texto or COR_TEXTO)
    item.setHAlign(alinhamento)
    item.setVAlign(alinhamento_vertical)
    item.setMargin(0.3)
    item.adjustSizeToText()
    item.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    item.attemptResize(QgsLayoutSize(largura, altura, QgsUnitTypes.LayoutMillimeters))
    item.setFrameEnabled(moldura)
    if moldura:
        item.setFrameStrokeColor(COR_BORDA)
    if fundo:
        item.setBackgroundEnabled(True)
        item.setBackgroundColor(fundo)
    layout.addLayoutItem(item)
    return item


def _adicionar_cabecalho(layout, texto, x, y, largura, altura, tamanho=8):
    """Faixa visual padronizada para títulos de mapa, tabela e carimbo."""
    return _adicionar_rotulo(
        layout, texto, x, y, largura, altura, tamanho, True, True,
        Qt.AlignHCenter, COR_PAINEL, COR_PRIMARIA,
    )


def _quebrar_texto(texto, largura=66):
    """Insere quebras previsíveis para campos longos em carimbos estreitos."""
    valor = str(texto or "Não informado").strip()
    return "\n".join(textwrap.wrap(valor, width=largura, break_long_words=True)) or "Não informado"


def _adicionar_rotulo_alinhado(layout, texto, centro_x, centro_y, largura, altura, angulo, tamanho=4):
    """Adiciona uma anotação girada paralelamente ao lado correspondente."""
    item = QgsLayoutItemLabel(layout)
    item.setText(texto)
    fonte = QFont("Arial")
    fonte.setPointSizeF(tamanho)
    fonte.setBold(True)
    item.setFont(fonte)
    item.setFontColor(COR_TEXTO)
    item.setHAlign(Qt.AlignHCenter)
    item.setVAlign(Qt.AlignVCenter)
    item.setMargin(0.1)
    item.attemptMove(QgsLayoutPoint(
        centro_x - largura / 2, centro_y - altura / 2, QgsUnitTypes.LayoutMillimeters,
    ))
    item.attemptResize(QgsLayoutSize(largura, altura, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(item)
    item.setItemRotation(angulo, True)
    return item


def _largura_texto_milimetros(texto, fonte):
    """Estima largura física do texto a partir da proporção das métricas da fonte."""
    metricas = QFontMetricsF(fonte)
    altura_metricas = metricas.height()
    if altura_metricas <= 0:
        return 0.0
    return (
        metricas.horizontalAdvance(texto) / altura_metricas
        * fonte.pointSizeF() * 25.4 / 72.0
        + 0.8
    )


def _ponto_para_layout(extensao, leste, norte, mapa_x=10, mapa_y=25, mapa_largura=190, mapa_altura=140):
    """Converte coordenadas UTM para milímetros na moldura do mapa principal."""
    if extensao.width() == 0 or extensao.height() == 0:
        return mapa_x, mapa_y
    x = mapa_x + (leste - extensao.xMinimum()) / extensao.width() * mapa_largura
    y = mapa_y + (extensao.yMaximum() - norte) / extensao.height() * mapa_altura
    return x, y


def _retangulo(x, y, largura, altura):
    return x, y, x + largura, y + altura


def _intersecta(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _poligono_retangulo(caixa):
    x1, y1, x2, y2 = caixa
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def _poligono_rotacionado(centro_x, centro_y, largura, altura, angulo):
    radianos = math.radians(angulo)
    coseno, seno = math.cos(radianos), math.sin(radianos)
    pontos = []
    for dx, dy in (
        (-largura / 2, -altura / 2), (largura / 2, -altura / 2),
        (largura / 2, altura / 2), (-largura / 2, altura / 2),
    ):
        pontos.append((centro_x + dx * coseno - dy * seno,
                       centro_y + dx * seno + dy * coseno))
    return pontos


def _poligonos_sobrepostos(primeiro, segundo):
    """Testa sobreposição de caixas, inclusive quando os rótulos estão girados."""
    for poligono in (primeiro, segundo):
        for indice, ponto in enumerate(poligono):
            proximo = poligono[(indice + 1) % len(poligono)]
            eixo_x = -(proximo[1] - ponto[1])
            eixo_y = proximo[0] - ponto[0]
            modulo = math.hypot(eixo_x, eixo_y)
            if modulo == 0:
                continue
            eixo_x, eixo_y = eixo_x / modulo, eixo_y / modulo
            projecao_a = [x * eixo_x + y * eixo_y for x, y in primeiro]
            projecao_b = [x * eixo_x + y * eixo_y for x, y in segundo]
            if max(projecao_a) <= min(projecao_b) or max(projecao_b) <= min(projecao_a):
                return False
    return True


def _posicionar_rotulo(ocupados, ancora_x, ancora_y, largura, altura, candidatos, limites):
    """Escolhe a posição mais próxima da feição que não cubra outro texto.

    As coordenadas de um item de layout representam o seu canto superior
    esquerdo. Centralizar cada rótulo na âncora evita o deslocamento lateral
    que ocorria quando se somava uma distância fixa à coordenada do segmento.
    """
    melhor = None
    for ordem, (dx, dy) in enumerate(candidatos):
        esquerda, topo, direita, base = limites
        x = max(esquerda, min(direita - largura, ancora_x + dx - largura / 2))
        y = max(topo, min(base - altura, ancora_y + dy - altura / 2))
        caixa = _retangulo(x, y, largura, altura)
        colisões = sum(_intersecta(caixa, outra) for outra in ocupados)
        # Em empate, prioriza o primeiro candidato (o mais próximo da linha).
        nota = (colisões, ordem)
        if melhor is None or nota < melhor[0]:
            melhor = (nota, x, y, caixa)
            if colisões == 0 and ordem == 0:
                break
    ocupados.append(melhor[3])
    return melhor[1], melhor[2]


def _camada_vertices(vertices, crs):
    """Cria os marcadores de todos os vértices da poligonal para o mapa."""
    camada = QgsVectorLayer(f"Point?crs={crs.authid()}", "Vértices da planta", "memory")
    provedor = camada.dataProvider()
    provedor.addAttributes([QgsField("vertex_id", QVariant.String), QgsField("rotulo", QVariant.String)])
    camada.updateFields()

    feicoes = []
    for vertice in vertices:
        feicao = QgsFeature(camada.fields())
        feicao.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(vertice["leste"], vertice["norte"])))
        feicao.setAttributes([vertice["id"], vertice["id"]])
        feicoes.append(feicao)
    provedor.addFeatures(feicoes)
    camada.updateExtents()
    simbolo = QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": COR_PRIMARIA.name(),
        "outline_color": COR_DESTAQUE.name(),
        "outline_width": "0.25",
        "size": "1.7",
    })
    camada.setRenderer(QgsSingleSymbolRenderer(simbolo))
    camada.setCustomProperty(MARCADOR_CAMADA_TEMPORARIA, "vertices")
    return camada


def _camada_limite_selecionado(camada_origem, dados):
    """Cria uma cópia de layout com somente a feição usada nos cálculos."""
    feicao_origem = camada_origem.getFeature(dados["feicao_origem_id"])
    if not feicao_origem.isValid() or not feicao_origem.hasGeometry():
        raise RuntimeError("A feição selecionada não está mais disponível para desenhar a planta.")
    crs = camada_origem.crs()
    tipo_geometria = QgsWkbTypes.displayString(camada_origem.wkbType())
    uri = tipo_geometria + (f"?crs={crs.authid()}" if crs.authid() else "")
    camada = QgsVectorLayer(uri, f"Limite do imóvel — {camada_origem.name()}", "memory")
    if not camada.isValid():
        raise RuntimeError("Não foi possível preparar a camada isolada do limite do imóvel.")
    if not crs.authid():
        camada.setCrs(crs)
    provedor = camada.dataProvider()
    provedor.addAttributes(list(camada_origem.fields()))
    camada.updateFields()
    feicao = QgsFeature(camada.fields())
    feicao.setGeometry(QgsGeometry(feicao_origem.geometry()))
    feicao.setAttributes(feicao_origem.attributes())
    if not provedor.addFeatures([feicao])[0]:
        raise RuntimeError("Não foi possível copiar a feição para a camada de desenho da planta.")
    renderer = camada_origem.renderer()
    if renderer:
        camada.setRenderer(renderer.clone())
    # Padroniza o limite cadastral no layout para que sua cor corresponda à
    # convenção impressa, sem alterar a simbologia da camada original do projeto.
    if camada.geometryType() == QgsWkbTypes.PolygonGeometry:
        simbolo_limite = QgsFillSymbol.createSimple({
            "style": "no", "outline_style": "solid",
            "outline_color": COR_LIMITE.name(), "outline_width": "0.55",
        })
        camada.setRenderer(QgsSingleSymbolRenderer(simbolo_limite))
    elif camada.geometryType() == QgsWkbTypes.LineGeometry:
        simbolo_limite = QgsLineSymbol.createSimple({
            "line_color": COR_LIMITE.name(), "line_width": "0.55",
        })
        camada.setRenderer(QgsSingleSymbolRenderer(simbolo_limite))
    camada.setOpacity(camada_origem.opacity())
    camada.setBlendMode(camada_origem.blendMode())
    camada.setLabelsEnabled(False)
    camada.setCustomProperty(MARCADOR_CAMADA_TEMPORARIA, "limite_planta")
    camada.setCustomProperty("agrimensura/camada_origem_id", camada_origem.id())
    camada.setCustomProperty("agrimensura/feicao_origem_id", int(feicao_origem.id()))
    camada.updateExtents()
    return camada


def _adicionar_anotacoes_perimetricas(layout, mapa, dados, extensao_mapa):
    """Identifica os vértices e alinha azimute/distância a cada lado legível."""
    extensao = extensao_mapa
    ocupados = []
    pontos_layout = {}
    mapa_x, mapa_y, mapa_largura, mapa_altura = 10, 10, 245, 225
    limites = (mapa_x, mapa_y, mapa_x + mapa_largura, mapa_y + mapa_altura)
    centro_leste = sum(v["leste"] for v in dados["vertices"]) / len(dados["vertices"])
    centro_norte = sum(v["norte"] for v in dados["vertices"]) / len(dados["vertices"])
    angulos_vertices = {
        segmento["inicio"]["id"]: segmento.get("angulo_interno_dms", "—")
        for segmento in dados["segmentos"]
    }
    largura_rotulo_vertice, altura_rotulo_vertice = 20, 9

    for indice, vertice in enumerate(dados["vertices"]):
        x, y = _ponto_para_layout(extensao, vertice["leste"], vertice["norte"], mapa_x, mapa_y, mapa_largura, mapa_altura)
        pontos_layout[vertice["id"]] = (x, y)
        cx, cy = _ponto_para_layout(extensao, centro_leste, centro_norte, mapa_x, mapa_y, mapa_largura, mapa_altura)
        vx, vy = x - cx, y - cy
        modulo = math.hypot(vx, vy) or 1
        # Mantém as identificações junto aos marcadores. A caixa mais estreita
        # permite aproximar o texto sem afastá-lo para resolver colisões.
        candidatos = [(vx / modulo * d, vy / modulo * d) for d in (5.5, 7, 8.5)]
        candidatos += [(-vy / modulo * d, vx / modulo * d) for d in (5.5, 7, 8.5)]
        candidatos += [(vy / modulo * d, -vx / modulo * d) for d in (5.5, 7, 8.5)]
        rx, ry = _posicionar_rotulo(
            ocupados, x, y, largura_rotulo_vertice, altura_rotulo_vertice, candidatos, limites,
        )
        texto_vertice = f"{vertice['id']}\n∠ {angulos_vertices.get(vertice['id'], '—')}"
        item_vertice = _adicionar_rotulo(
            layout, texto_vertice, rx, ry, largura_rotulo_vertice, altura_rotulo_vertice, 8, True,
        )
        item_vertice.setId(f"vertex_label_{indice + 1}")
        item_vertice.setCustomProperty("agrimensura/vertex_id", vertice["id"])
        item_vertice.setCustomProperty("agrimensura/anchor_x", rx)
        item_vertice.setCustomProperty("agrimensura/anchor_y", ry)
        item_vertice.setCustomProperty("agrimensura/offset_x", rx - x)
        item_vertice.setCustomProperty("agrimensura/offset_y", ry - y)

    caixas_vertices = [_poligono_retangulo(caixa) for caixa in ocupados]
    obstaculos_rotulos = [
        _poligono_retangulo(_retangulo(16, 16, 18, 22)),  # seta norte
    ]
    if extensao_mapa.width() > 0:
        metros_segmento = _passo_agradavel(
            extensao_mapa.width() * 15.0 / LARGURA_MAPA_PRINCIPAL_MM,
        )
        largura_barra = (
            metros_segmento * 4 * LARGURA_MAPA_PRINCIPAL_MM / extensao_mapa.width()
        )
        obstaculos_rotulos.append(
            _poligono_retangulo(_retangulo(13, 217, largura_barra + 20, 8)),
        )
    poligonos_rotulos_alinhados = []
    coordenadas_anel = [pontos_layout[v["id"]] for v in dados["vertices"]]
    area_dobrada = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(
            coordenadas_anel, coordenadas_anel[1:] + coordenadas_anel[:1],
        )
    )
    sinal_area = 1 if area_dobrada >= 0 else -1

    for segmento in dados["segmentos"]:
        inicio, fim = segmento["inicio"], segmento["fim"]
        x1, y1 = pontos_layout[inicio["id"]]
        x2, y2 = pontos_layout[fim["id"]]
        dx, dy = x2 - x1, y2 - y1
        comprimento = math.hypot(dx, dy)
        if comprimento <= 0:
            continue

        distancia = f"{segmento['distancia_m']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        linha_azimute = f"Az. {segmento['azimute_dms']}"
        linha_distancia = f"D: {distancia} m"
        texto = f"{linha_azimute}\n{linha_distancia}"
        tamanho_fonte = 7.0
        fonte = QFont("Arial")
        fonte.setPointSizeF(tamanho_fonte)
        fonte.setBold(True)
        largura_texto = max(
            _largura_texto_milimetros(linha_azimute, fonte),
            _largura_texto_milimetros(linha_distancia, fonte),
        )
        largura_disponivel = comprimento - 1.5
        if largura_disponivel <= 0:
            continue
        if largura_texto > largura_disponivel:
            tamanho_fonte *= largura_disponivel / largura_texto
            if tamanho_fonte < 7.0:
                continue
            fonte.setPointSizeF(tamanho_fonte)
            largura_texto = max(
                _largura_texto_milimetros(linha_azimute, fonte),
                _largura_texto_milimetros(linha_distancia, fonte),
            )
        largura = min(largura_disponivel, largura_texto)
        altura = max(5.4, tamanho_fonte * 25.4 / 72.0 * 2.8)

        angulo = math.degrees(math.atan2(dy, dx))
        # Mantém a leitura da esquerda para a direita, sem texto de cabeça para baixo.
        if angulo > 90:
            angulo -= 180
        elif angulo < -90:
            angulo += 180

        # O sinal da área do anel indica qual lado de cada segmento é o exterior.
        nx, ny = sinal_area * dy / comprimento, -sinal_area * dx / comprimento
        centro_x_base, centro_y_base = (x1 + x2) / 2, (y1 + y2) / 2
        deslocamento_maximo = max(0, (comprimento - largura) / 2)
        deslocamentos_linha = (0, -min(3, deslocamento_maximo), min(3, deslocamento_maximo))
        deslocamentos_normais = (altura / 2 + 1.2, altura / 2 + 2.5, -(altura / 2 + 1.2))
        melhor = None
        ordem = 0
        for deslocamento_linha in deslocamentos_linha:
            for deslocamento_normal in deslocamentos_normais:
                centro_x = centro_x_base + dx / comprimento * deslocamento_linha + nx * deslocamento_normal
                centro_y = centro_y_base + dy / comprimento * deslocamento_linha + ny * deslocamento_normal
                caixa = _poligono_rotacionado(centro_x, centro_y, largura, altura, angulo)
                fora_do_mapa = any(
                    x < limites[0] or y < limites[1] or x > limites[2] or y > limites[3]
                    for x, y in caixa
                )
                obstaculos = caixas_vertices + obstaculos_rotulos + poligonos_rotulos_alinhados
                colisões = sum(_poligonos_sobrepostos(caixa, outra) for outra in obstaculos)
                nota = (colisões, fora_do_mapa, ordem)
                if melhor is None or nota < melhor[0]:
                    melhor = (nota, centro_x, centro_y, caixa)
                    if nota == (0, False, 0):
                        break
                ordem += 1
            if melhor[0] == (0, False, 0):
                break
        if melhor[0][0] or melhor[0][1]:
            # Os valores continuam completos no roteiro quando o trecho é curto
            # ou o rótulo colidiria com outro elemento do desenho.
            continue
        _, centro_x, centro_y, caixa = melhor
        poligonos_rotulos_alinhados.append(caixa)
        item_segmento = _adicionar_rotulo_alinhado(
            layout, texto, centro_x, centro_y, largura, altura, angulo, tamanho_fonte,
        )
        item_segmento.setId(f"segment_label_{inicio['id']}_{fim['id']}")
        item_segmento.setCustomProperty("agrimensura/segment_id", f"{inicio['id']}|{fim['id']}")
        item_segmento.setCustomProperty("agrimensura/anchor_x", centro_x - largura / 2)
        item_segmento.setCustomProperty("agrimensura/anchor_y", centro_y - altura / 2)


def _adicionar_escala_grafica(layout, mapa, x, y, extensao_mapa, largura_segmento=15.0):
    """Adiciona uma barra QGIS vinculada ao mapa e atualizada com sua escala."""
    largura_mapa = _largura_mapa_layout_mm(mapa)
    largura_extensao = extensao_mapa.width()
    if largura_mapa <= 0 or largura_extensao <= 0:
        return None
    metros_por_segmento = _passo_agradavel(largura_extensao * largura_segmento / largura_mapa)
    barra = QgsLayoutItemScaleBar(layout)
    barra.setStyle("Single Box")
    barra.setLinkedMap(mapa)
    barra.setUnits(QgsUnitTypes.DistanceMeters)
    barra.setMapUnitsPerScaleBarUnit(1.0)
    barra.setUnitsPerSegment(float(metros_por_segmento))
    barra.setNumberOfSegments(4)
    barra.setNumberOfSegmentsLeft(0)
    barra.setUnitLabel("m")
    barra.setHeight(2.5)
    barra.setLineSymbol(QgsLineSymbol.createSimple({
        "line_color": "#222222", "line_width": "0.2", "line_style": "solid",
    }))
    barra.setFillSymbol(QgsFillSymbol.createSimple({
        "color": "#222222", "outline_color": "#222222", "outline_width": "0.2",
    }))
    barra.setAlternateFillSymbol(QgsFillSymbol.createSimple({
        "color": "#FFFFFF", "outline_color": "#222222", "outline_width": "0.2",
    }))
    fonte = QFont("Arial")
    fonte.setPointSizeF(5.3)
    formato_texto = QgsTextFormat()
    formato_texto.setFont(fonte)
    formato_texto.setSize(5.3)
    formato_texto.setSizeUnit(QgsUnitTypes.RenderPoints)
    formato_texto.setColor(COR_TEXTO)
    barra.setTextFormat(formato_texto)
    layout.addLayoutItem(barra)
    barra.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    barra.update()
    return barra


def _configurar_grade_coordenadas(mapa, extensao_mapa, anotacoes=False):
    """Configura uma grade discreta no SRC projetado usado pelo mapa."""
    if extensao_mapa.width() <= 0 or extensao_mapa.height() <= 0:
        return None
    intervalo = _passo_agradavel(max(extensao_mapa.width(), extensao_mapa.height()) / 5.0)
    grade = mapa.grid()
    grade.setEnabled(True)
    grade.setCrs(mapa.crs())
    grade.setUnits(QgsLayoutItemMapGrid.MapUnit)
    grade.setIntervalX(intervalo)
    grade.setIntervalY(intervalo)
    grade.setStyle(QgsLayoutItemMapGrid.Cross)
    grade.setCrossLength(1.6)
    grade.setGridLineColor(QColor("#626C68"))
    grade.setGridLineWidth(0.12)
    grade.setAnnotationEnabled(bool(anotacoes))
    if anotacoes:
        grade.setAnnotationFormat(QgsLayoutItemMapGrid.Decimal)
        grade.setAnnotationPrecision(0)
        fonte_grade = QFont("Arial")
        fonte_grade.setPointSizeF(7.0)
        formato_grade = QgsTextFormat()
        formato_grade.setFont(fonte_grade)
        formato_grade.setSize(5.0)
        formato_grade.setSizeUnit(QgsUnitTypes.RenderPoints)
        formato_grade.setColor(QColor("#34403A"))
        grade.setAnnotationTextFormat(formato_grade)
        grade.setAnnotationFrameDistance(1.2)
        for lado in (
            QgsLayoutItemMapGrid.Left, QgsLayoutItemMapGrid.Right,
            QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.Bottom,
        ):
            grade.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, lado)
        grade.setAnnotationDisplay(QgsLayoutItemMapGrid.LongitudeOnly, QgsLayoutItemMapGrid.Bottom)
        grade.setAnnotationDisplay(QgsLayoutItemMapGrid.LatitudeOnly, QgsLayoutItemMapGrid.Left)
        grade.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, QgsLayoutItemMapGrid.Right)
        grade.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, QgsLayoutItemMapGrid.Top)
    return intervalo


def _denominador_escala(mapa, extensao_mapa):
    """Calcula escala nominal usando a largura real ou a largura conhecida do mapa."""
    largura_pagina_mm = _largura_mapa_layout_mm(mapa)
    if largura_pagina_mm <= 0 or extensao_mapa.width() <= 0:
        return None
    return extensao_mapa.width() * 1000.0 / largura_pagina_mm


def _largura_mapa_layout_mm(mapa):
    """Obtém a largura em milímetros, mesmo antes do primeiro render do item."""
    try:
        largura = float(mapa.sizeWithUnits().width())
        if math.isfinite(largura) and largura > 0:
            return largura
    except (AttributeError, TypeError, ValueError):
        pass
    try:
        largura = float(mapa.rect().width())
        if math.isfinite(largura) and largura > 0:
            return largura
    except (AttributeError, TypeError, ValueError):
        pass
    # O quadro principal do modelo A3 tem 245 mm de largura.
    return LARGURA_MAPA_PRINCIPAL_MM


def _fator_folha(formato_folha):
    """Retorna a proporção entre a largura ISO escolhida e a prancha A3-base."""
    larguras_iso = {"A4": 297.0, "A3": 420.0, "A2": 594.0, "A1": 841.0, "A0": 1189.0}
    formato = str(formato_folha or "A3").upper()
    if formato not in larguras_iso:
        formato = "A3"
    return larguras_iso[formato] / 420.0, formato


def _ajustar_layout_a_folha(layout, formato_folha, fator):
    """Redimensiona todos os itens da prancha A3-base para outro formato ISO."""
    if math.isclose(fator, 1.0, rel_tol=0, abs_tol=1e-9):
        return

    itens = []
    for item in layout.items():
        if not isinstance(item, QgsLayoutItem) or isinstance(item, QgsLayoutItemPage):
            continue
        itens.append((
            item, item.page(), item.pagePositionWithUnits(), item.sizeWithUnits(),
        ))

    for pagina in layout.pageCollection().pages():
        pagina.setPageSize(formato_folha, QgsLayoutItemPage.Landscape)

    for item, numero_pagina, posicao, tamanho in itens:
        item.attemptMove(QgsLayoutPoint(
            posicao.x() * fator, posicao.y() * fator, QgsUnitTypes.LayoutMillimeters,
        ), True, False, numero_pagina)
        item.attemptResize(QgsLayoutSize(
            tamanho.width() * fator, tamanho.height() * fator, QgsUnitTypes.LayoutMillimeters,
        ))
        if isinstance(item, QgsLayoutItemLabel):
            fonte = item.font()
            # Não reduzir abaixo do mínimo de leitura, inclusive em A4.
            fonte.setPointSizeF(max(fonte.pointSizeF() * fator, 7.0))
            item.setFont(fonte)


def _texto_escala(mapa, extensao_mapa, fator_layout=1.0):
    denominador = _denominador_escala(mapa, extensao_mapa)
    if denominador is None:
        return "não calculada"
    if fator_layout > 0:
        denominador /= fator_layout
    if not math.isfinite(denominador) or denominador <= 0:
        return "não calculada"
    return f"1:{denominador:,.0f}".replace(",", ".")


def _angulo_assinado_dms(valor):
    """Formata um ângulo com sinal e precisão de segundos."""
    sinal = "−" if valor < 0 else "+"
    total_segundos = int(round(abs(valor) * 3600))
    graus, resto = divmod(total_segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    return f'{sinal}{graus:02d}°{minutos:02d}\'{segundos:02d}"'


def _parametro_proj(texto_proj, nome):
    correspondencia = re.search(
        rf"(?:^|\s)\+{re.escape(nome)}=([-+]?(?:\d+(?:\.\d*)?|\.\d+))",
        texto_proj,
    )
    return float(correspondencia.group(1)) if correspondencia else None


def _informacoes_cartograficas(dados, escala_mapa):
    """Monta os dados do quadro pelo SRC e pelo centroide do imóvel."""
    crs = dados["crs"]
    proj = crs.toProj() if hasattr(crs, "toProj") else ""
    projecao_utm = bool(re.search(r"(?:^|\s)\+proj=utm(?:\s|$)", proj))
    zona = _parametro_proj(proj, "zone") if projecao_utm else None
    if projecao_utm and zona:
        zona = int(zona)
        descricao_projecao = f"UTM zona {zona}{'S' if re.search(r'(?:^|\s)\+south(?:\s|$)', proj) else 'N'}"
        meridiano_central = float(zona * 6 - 183)
        fator_origem = 0.9996
    else:
        descricao_projecao = crs.description() or "Projeção do SRC"
        meridiano_central = _parametro_proj(proj, "lon_0")
        fator_origem = _parametro_proj(proj, "k_0")
        if fator_origem is None:
            fator_origem = _parametro_proj(proj, "k")

    crs_geografico_id = crs.geographicCrsAuthId() if hasattr(crs, "geographicCrsAuthId") else ""
    if crs_geografico_id == "EPSG:4674":
        datum = "SIRGAS 2000"
    elif crs_geografico_id == "EPSG:4326":
        datum = "WGS 84"
    else:
        datum = crs_geografico_id or "conforme SRC"

    convergencia = None
    fator_local = None
    try:
        crs_geografico = crs.toGeographicCrs()
        if crs_geografico.isValid():
            centro = dados["geometria"].centroid().asPoint()
            ponto_geografico = QgsCoordinateTransform(
                crs, crs_geografico, QgsProject.instance(),
            ).transform(QgsPointXY(centro.x(), centro.y()))
            if hasattr(crs, "factors"):
                fatores = crs.factors(QgsPoint(ponto_geografico.x(), ponto_geografico.y()))
                if fatores.isValid():
                    valor_convergencia = float(fatores.meridianConvergence())
                    if math.isfinite(valor_convergencia):
                        convergencia = valor_convergencia
                    escalas = (float(fatores.meridionalScale()), float(fatores.parallelScale()))
                    escalas = [valor for valor in escalas if math.isfinite(valor) and valor > 0]
                    if escalas:
                        fator_local = sum(escalas) / len(escalas)
    except Exception:
        # A ficha ainda mostra os parâmetros do SRC se a transformação local falhar.
        pass

    linhas = [
        f"Projeção: {descricao_projecao}",
        f"Datum: {datum}",
    ]
    if meridiano_central is not None:
        linhas.append(
            f"Meridiano central: {_coordenada_geografica_dms(meridiano_central, False)}",
        )
    if convergencia is not None:
        linhas.append(f"Convergência: {_angulo_assinado_dms(convergencia)}")
    else:
        linhas.append("Convergência: indisponível")
    if fator_local is not None:
        linhas.append(f"Fator local K: {fator_local:.6f}")
    elif fator_origem is not None:
        linhas.append(f"Fator na origem k₀: {fator_origem:.6f}")
    else:
        linhas.append("Fator de escala: indisponível")
    linhas.extend((
        f"SRC: {dados['crs_authid']} | Unidade: m",
        f"Escala inicial: {escala_mapa}",
    ))
    return linhas


def _dados_diagrama_orientacao(dados):
    """Calcula os ângulos locais dos nortes de quadrícula, geográfico e magnético."""
    crs = dados["crs"]
    centro = dados["geometria"].centroid().asPoint()
    crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    para_geografico = QgsCoordinateTransform(crs, crs_wgs84, QgsProject.instance())
    para_projetado = QgsCoordinateTransform(crs_wgs84, crs, QgsProject.instance())
    geografico = para_geografico.transform(QgsPointXY(centro.x(), centro.y()))
    latitude, longitude = float(geografico.y()), float(geografico.x())

    # Projeta um pequeno deslocamento ao norte geodésico para medir a direção
    # verdadeira no plano da quadrícula, sem depender do sinal da convergência.
    deslocamento_latitude = 0.001 if latitude < 89.999 else -0.001
    ponto_norte = para_projetado.transform(
        QgsPointXY(longitude, latitude + deslocamento_latitude),
    )
    gamma = math.degrees(math.atan2(ponto_norte.x() - centro.x(), ponto_norte.y() - centro.y()))
    gamma = (gamma + 180.0) % 360.0 - 180.0

    data_calculo = date.today()
    primeiro_dia = date(data_calculo.year, 1, 1)
    dias_ano = 366 if (date(data_calculo.year + 1, 1, 1) - primeiro_dia).days == 366 else 365
    ano_decimal = data_calculo.year + (data_calculo - primeiro_dia).days / dias_ano
    try:
        declinacao, intensidade_horizontal = declinacao_magnetica(
            latitude, longitude, ano_decimal,
        )
        if intensidade_horizontal < 2000:
            declinacao = None
            aviso = "Zona de baixa confiabilidade magnética"
        elif intensidade_horizontal < 6000:
            aviso = "Atenção: intensidade magnética reduzida"
        else:
            aviso = ""
    except (ValueError, ArithmeticError, OverflowError):
        declinacao, aviso = None, "NM indisponível (fora da validade do WMM-2025)"
    return {
        "convergencia": gamma,
        "declinacao": declinacao,
        "latitude": latitude,
        "longitude": longitude,
        "data": data_calculo,
        "aviso": aviso,
    }


def _angulo_com_ponto_cardinal(valor):
    """Formata ângulo assinado em DMS com a indicação leste/oeste."""
    if valor is None:
        return "indisponível"
    total_segundos = int(round(abs(valor) * 3600))
    graus, resto = divmod(total_segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    cardinal = "E" if valor >= 0 else "W"
    return f"{graus:02d}°{minutos:02d}′{segundos:02d}″ {cardinal}"


def _adicionar_seta_norte(layout, origem_x, origem_y, angulo, comprimento, rotulo, cor):
    """Desenha uma seta vetorial preenchida, com ponta gráfica (não caractere)."""
    radianos = math.radians(angulo)
    vx, vy = math.sin(radianos), -math.cos(radianos)
    nx, ny = math.cos(radianos), math.sin(radianos)
    ponta = (origem_x + vx * comprimento, origem_y + vy * comprimento)
    base_ponta = (ponta[0] - vx * 2.3, ponta[1] - vy * 2.3)
    meia_haste, meia_ponta = 0.24, 1.15
    coordenadas = [
        (origem_x + nx * meia_haste, origem_y + ny * meia_haste),
        (base_ponta[0] + nx * meia_haste, base_ponta[1] + ny * meia_haste),
        (base_ponta[0] + nx * meia_ponta, base_ponta[1] + ny * meia_ponta),
        ponta,
        (base_ponta[0] - nx * meia_ponta, base_ponta[1] - ny * meia_ponta),
        (base_ponta[0] - nx * meia_haste, base_ponta[1] - ny * meia_haste),
        (origem_x - nx * meia_haste, origem_y - ny * meia_haste),
    ]
    minimo_x = min(x for x, _ in coordenadas)
    minimo_y = min(y for _, y in coordenadas)
    poligono = QPolygonF([
        QPointF(x - minimo_x, y - minimo_y) for x, y in coordenadas
    ])
    item = QgsLayoutItemPolygon(poligono, layout)
    item.setSymbol(QgsFillSymbol.createSimple({
        "color": cor.name(), "outline_color": cor.name(), "outline_width": "0.15",
        "joinstyle": "round",
    }))
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(minimo_x, minimo_y, QgsUnitTypes.LayoutMillimeters), False)

    # Rótulos curtos junto às pontas permitem identificar cada direção mesmo
    # quando os ângulos ficam muito próximos.
    rotulo_x = ponta[0] - 6.0 if vx >= 0 else ponta[0] + 0.8
    rotulo_y = ponta[1] - 2.0
    _adicionar_rotulo(
        layout, rotulo, rotulo_x, rotulo_y, 8.0, 5.0, 7.0, True,
        alinhamento=Qt.AlignHCenter, cor_texto=cor,
    )


def _adicionar_diagrama_orientacao(layout, dados, escala_mapa, mapa, extensao_mapa):
    """Compõe o diagrama técnico no quadro de referência da folha."""
    orientacao = _dados_diagrama_orientacao(dados)
    _adicionar_cabecalho(layout, "DIAGRAMA DE ORIENTAÇÃO", 262, 19, 48, 6, 5.6)
    _adicionar_rotulo(layout, "", 262, 25, 48, 59, 5, False, True, fundo=COR_PAINEL)

    # O eixo vertical da moldura do mapa representa o norte da quadrícula UTM.
    origem_x, origem_y = 273.5, 76.0
    cor_quadr = QColor("#333333")
    cor_geografico = QColor("#238A48")
    cor_magnetico = QColor("#B83B36")
    _adicionar_seta_norte(layout, origem_x, origem_y, 0.0, 14.0, "NQ", cor_quadr)
    _adicionar_seta_norte(
        layout, origem_x, origem_y, orientacao["convergencia"], 19.0, "NG", cor_geografico,
    )
    if orientacao["declinacao"] is not None:
        angulo_magnetico = orientacao["convergencia"] + orientacao["declinacao"]
        _adicionar_seta_norte(
            layout, origem_x, origem_y, angulo_magnetico, 24.0, "NM", cor_magnetico,
        )

    cartografia = _informacoes_cartograficas(dados, escala_mapa)
    zona = cartografia[0].replace("Projeção: ", "")
    datum = cartografia[1].replace("Datum: ", "")
    meridiano = cartografia[2].replace("Meridiano central: ", "MC: ") if len(cartografia) > 2 else ""
    linhas = [
        zona,
        datum,
        meridiano,
        f"γ NG/NQ: {_angulo_com_ponto_cardinal(orientacao['convergencia'])}",
        f"D NM/NG: {_angulo_com_ponto_cardinal(orientacao['declinacao'])}",
        "Modelo: WMM-2025",
        f"Data: {orientacao['data'].strftime('%d/%m/%Y')}",
    ]
    if orientacao["aviso"]:
        linhas.append(orientacao["aviso"])
    _adicionar_rotulo(
        layout, "\n".join(linhas), 285, 29, 24, 51, 4.2, False, False,
        alinhamento_vertical=Qt.AlignTop,
    )
    _adicionar_escala_grafica(layout, mapa, 267, 80, extensao_mapa, largura_segmento=8.0)


def _coordenada_geografica_dms(valor, latitude):
    hemisferio = ("S" if valor < 0 else "N") if latitude else ("W" if valor < 0 else "E")
    total_segundos = round(abs(valor) * 3600)
    graus, resto = divmod(total_segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    return f'{graus:02d}°{minutos:02d}\'{segundos:02d}" {hemisferio}'


def _numero_tabela(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _passo_agradavel(valor):
    """Arredonda para 1, 2 ou 5 × potência de dez, apropriado à escala gráfica."""
    if valor <= 0:
        return 1
    potencia = 10 ** math.floor(math.log10(valor))
    mantissa = valor / potencia
    base = 1 if mantissa <= 1 else 2 if mantissa <= 2 else 5 if mantissa <= 5 else 10
    return base * potencia


def _extensao_centralizada(geometria, largura_mm, altura_mm, margem=1.18):
    """Enquadra a geometria com folga para nunca tocar a moldura do mapa.

    A margem é aplicada antes de ajustar a proporção do quadro; assim, mesmo
    após o QGIS adequar a extensão ao retângulo do mapa, toda a poligonal fica
    dentro da grade, com espaço também para os rótulos dos vértices.
    """
    ext = QgsRectangle(geometria.boundingBox())
    ext.scale(margem)
    proporcao_quadro = largura_mm / altura_mm
    proporcao_ext = ext.width() / ext.height()
    cx, cy = ext.center().x(), ext.center().y()
    largura, altura = ext.width(), ext.height()
    if proporcao_ext > proporcao_quadro:
        altura = largura / proporcao_quadro
    else:
        largura = altura * proporcao_quadro
    return QgsRectangle(cx - largura / 2, cy - altura / 2, cx + largura / 2, cy + altura / 2)


def _texto_roteiro(segmentos):
    """Tabela textual estável, evitando a paginação automática de multiframes."""
    linhas = ["INICIAL | FINAL | AZIMUTE | DISTÂNCIA (m) | LIMITE | CONFRONTANTE"]
    for segmento in segmentos:
        inicio, fim = segmento["inicio"], segmento["fim"]
        linhas.append(
            f"{inicio['id']} | {fim['id']} | {segmento['azimute_dms']} | "
            f"{_numero_tabela(segmento['distancia_m'])} | "
            f"{segmento.get('tipo_limite') or '—'} | {segmento.get('confrontante') or '—'}"
        )
    return "\n".join(linhas)


def _camada_roteiro(segmentos, crs):
    """Camada temporária apenas para alimentar a tabela de atributos do layout."""
    camada = QgsVectorLayer(f"LineString?crs={crs.authid()}", "Roteiro perimétrico", "memory")
    provedor = camada.dataProvider()
    provedor.addAttributes([
        QgsField("Linha", QVariant.String), QgsField("Azimute", QVariant.String),
        QgsField("Dist_m", QVariant.String), QgsField("Norte_Y", QVariant.String),
        QgsField("Leste_X", QVariant.String), QgsField("Limite", QVariant.String),
        QgsField("Confront", QVariant.String),
    ])
    camada.updateFields()
    feicoes = []
    for s in segmentos:
        f = QgsFeature(camada.fields())
        ini, fim = s["inicio"], s["fim"]
        f.setGeometry(QgsGeometry.fromPolylineXY([
            QgsPointXY(ini["leste"], ini["norte"]), QgsPointXY(fim["leste"], fim["norte"])
        ]))
        f.setAttributes([
            f"{ini['id']} - {fim['id']}", s["azimute_dms"], _numero_tabela(s["distancia_m"]),
            _numero_tabela(fim["norte"]), _numero_tabela(fim["leste"]),
            s.get("tipo_limite") or "—", s.get("confrontante") or "—",
        ])
        feicoes.append(f)
    provedor.addFeatures(feicoes)
    camada.updateExtents()
    camada.setCustomProperty(MARCADOR_CAMADA_TEMPORARIA, "roteiro")
    QgsProject.instance().addMapLayer(camada, False)  # permanece somente no projeto, sem legenda
    return camada


def _camada_roteiro_completo(segmentos, crs):
    """Monta a tabela de rodapé com coordenadas planas e geográficas."""
    projeto = QgsProject.instance()
    geografico = QgsCoordinateReferenceSystem("EPSG:4674")
    transformar = QgsCoordinateTransform(crs, geografico, projeto)
    camada = QgsVectorLayer(f"LineString?crs={crs.authid()}", "Roteiro perimétrico", "memory")
    campos = [
        QgsField("Ini", QVariant.String), QgsField("Fim", QVariant.String),
        QgsField("Azimute", QVariant.String), QgsField("Angulo", QVariant.String),
        QgsField("Dist_m", QVariant.String),
        QgsField("Norte_m", QVariant.String), QgsField("Leste_m", QVariant.String),
        QgsField("Latitude", QVariant.String), QgsField("Longitude", QVariant.String),
        QgsField("Limite", QVariant.String), QgsField("Confront", QVariant.String),
    ]
    provedor = camada.dataProvider()
    provedor.addAttributes(campos)
    camada.updateFields()
    feicoes = []
    for segmento in segmentos:
        inicio, fim = segmento["inicio"], segmento["fim"]
        geo = transformar.transform(QgsPointXY(fim["leste"], fim["norte"]))
        f = QgsFeature(camada.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY([
            QgsPointXY(inicio["leste"], inicio["norte"]),
            QgsPointXY(fim["leste"], fim["norte"]),
        ]))
        f.setAttributes([
            inicio["id"], fim["id"], segmento["azimute_dms"],
            segmento.get("angulo_interno_dms", "—"),
            _numero_tabela(segmento["distancia_m"]), _numero_tabela(fim["norte"]),
            _numero_tabela(fim["leste"]),
            _coordenada_geografica_dms(geo.y(), True),
            _coordenada_geografica_dms(geo.x(), False),
            segmento.get("tipo_limite") or "—",
            segmento.get("confrontante") or "—",
        ])
        feicoes.append(f)
    provedor.addFeatures(feicoes)
    camada.updateExtents()
    camada.setCustomProperty(MARCADOR_CAMADA_TEMPORARIA, "roteiro_completo")
    projeto.addMapLayer(camada, False)
    return camada


def gerar_layout(dados, identificacao, nome="Planta_Agrimensura", formato_folha="A3"):
    """Cria uma planta em folha ISO paisagem, adaptada ao formato escolhido."""
    projeto = QgsProject.instance()
    fator_folha, formato_folha = _fator_folha(formato_folha)
    gerente = projeto.layoutManager()
    for existente in gerente.printLayouts():
        if existente.name() == nome:
            gerente.removeLayout(existente)
    _remover_camadas_temporarias(projeto)

    layout = QgsPrintLayout(projeto)
    layout.initializeDefaults()
    layout.pageCollection().page(0).setPageSize("A3", QgsLayoutItemPage.Landscape)
    layout.setName(nome)
    gerente.addLayout(layout)

    moldura_pagina = QgsLayoutItemShape(layout)
    moldura_pagina.setShapeType(QgsLayoutItemShape.Rectangle)
    moldura_pagina.setSymbol(QgsFillSymbol.createSimple({
        "style": "no", "outline_style": "solid",
        "outline_color": COR_BORDA.name(), "outline_width": "0.35",
    }))
    moldura_pagina.attemptMove(QgsLayoutPoint(8, 8, QgsUnitTypes.LayoutMillimeters), False)
    moldura_pagina.attemptResize(QgsLayoutSize(404, 281, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(moldura_pagina)

    mapa = QgsLayoutItemMap(layout)
    mapa.setId("agrimensura_mapa_principal")
    layout.addLayoutItem(mapa)
    mapa.setCrs(dados["crs"])
    extensao_mapa = _extensao_centralizada(dados["geometria"], 245, 225)
    mapa.attemptMove(QgsLayoutPoint(10, 10, QgsUnitTypes.LayoutMillimeters))
    mapa.attemptResize(QgsLayoutSize(245, 225, QgsUnitTypes.LayoutMillimeters))
    mapa.setBackgroundEnabled(True)
    mapa.setBackgroundColor(COR_PAINEL)
    mapa.setFrameEnabled(True)
    mapa.setFrameStrokeColor(COR_MOLDURA_MAPA)

    # O item de mapa usa a própria camada de trabalho do projeto. A geometria
    # não é copiada nem desenhada como um elemento gráfico do layout.
    camada_origem = projeto.mapLayer(dados.get("camada_origem_id", ""))
    if not camada_origem or not camada_origem.isValid():
        raise RuntimeError("A camada original da poligonal não está mais disponível no projeto.")
    camada_limite = _camada_limite_selecionado(camada_origem, dados)
    projeto.addMapLayer(camada_limite, False)
    vertices_planta = _camada_vertices(dados["vertices"], dados["crs"])
    QgsProject.instance().addMapLayer(vertices_planta, False)
    # Os marcadores ficam à frente da poligonal original, desenhada pelo mapa QGIS.
    mapa.setLayers([vertices_planta, camada_limite])
    mapa.setKeepLayerSet(True)
    mapa.setFollowVisibilityPreset(False)
    mapa.setExtent(extensao_mapa)
    _configurar_grade_coordenadas(mapa, extensao_mapa)
    mapa.refresh()

    # Mapa de situação: usa as camadas atualmente visíveis, além do limite do imóvel.
    situacao = QgsLayoutItemMap(layout)
    layout.addLayoutItem(situacao)
    situacao.attemptMove(QgsLayoutPoint(314, 27, QgsUnitTypes.LayoutMillimeters))
    situacao.attemptResize(QgsLayoutSize(96, 59, QgsUnitTypes.LayoutMillimeters))
    situacao.setCrs(dados["crs"])
    situacao.setFollowVisibilityPreset(False)
    camadas_contexto = [
        camada for camada in projeto.layerTreeRoot().checkedLayers()
        if camada.isValid()
        and not camada.customProperty(MARCADOR_CAMADA_TEMPORARIA, False)
        and camada.id() != camada_origem.id()
    ]
    situacao.setLayers([camada_limite] + camadas_contexto)
    ext_situacao = _extensao_centralizada(dados["geometria"], 96, 59, margem=2.5)
    situacao.setKeepLayerSet(True)
    situacao.setExtent(ext_situacao)
    situacao.setFrameEnabled(True)
    situacao.setFrameStrokeColor(COR_BORDA)
    _adicionar_cabecalho(layout, "LEVANTAMENTO TOPOGRÁFICO CADASTRAL", 262, 10, 148, 7, 8)
    escala_referencia = _texto_escala(mapa, extensao_mapa, fator_folha)
    _adicionar_diagrama_orientacao(layout, dados, escala_referencia, mapa, extensao_mapa)
    _adicionar_cabecalho(layout, "PLANTA DE SITUAÇÃO", 314, 19, 96, 6, 6)

    _adicionar_cabecalho(layout, "PLANTA DO IMÓVEL GEORREFERENCIADO", 262, 90, 116, 8, 8)
    _adicionar_cabecalho(layout, "FOLHA ÚNICA", 380, 90, 30, 8, 6)
    _adicionar_rotulo(
        layout,
        f"Imóvel: {identificacao.get('imovel') or 'Não informado'}\n"
        f"Proprietário: {identificacao.get('proprietario') or 'Não informado'}\n"
        f"Matrícula/cadastro: {identificacao.get('matricula') or 'Não informado'}\n"
        f"Município/UF: {identificacao.get('municipio') or 'Não informado'}\n"
        f"Responsável técnico: {identificacao.get('responsavel') or 'Não informado'}\n"
        f"Código INCRA: {identificacao.get('codigo_credenciado') or 'Não informado'}\n"
        f"ART/RRT: {identificacao.get('art_rrt') or 'Não informado'}\n"
        f"Fontes cartográficas:\n{_quebrar_texto(identificacao.get('fontes'), 72)}\n"
        f"Data de referência: {identificacao.get('data_referencia') or 'Não informada'}\n"
        f"Data: {date.today().strftime('%d/%m/%Y')}",
        262, 98, 148, 43, 6, False, True, fundo=COR_PAINEL,
        alinhamento_vertical=Qt.AlignTop,
    )

    _adicionar_cabecalho(layout, "ÁREAS E PERÍMETROS", 262, 144, 72, 7, 7)
    item_area = _adicionar_rotulo(layout,
        f"Área: {_numero_tabela(dados['area_m2'])} m²\n{_numero_tabela(dados['area_ha'])} ha\n"
        f"Perímetro: {_numero_tabela(dados['perimetro_m'])} m",
        262, 151, 72, 34, 8, True, True, fundo=COR_PAINEL,
        alinhamento_vertical=Qt.AlignTop)
    item_area.setId("agrimensura_area_perimetro")
    _adicionar_cabecalho(layout, "ASSINATURAS", 338, 144, 72, 7, 7)
    _adicionar_rotulo(layout,
        f"________________________________\n"
        f"Proprietário: {identificacao.get('proprietario') or 'Não informado'}\n\n"
        f"________________________________\n"
        f"Resp. técnico: {identificacao.get('responsavel') or 'Não informado'}\n"
        f"ART/RRT: {identificacao.get('art_rrt') or 'Não informado'}",
        338, 151, 72, 34, 5, False, True, fundo=COR_PAINEL,
        alinhamento_vertical=Qt.AlignTop)

    _adicionar_anotacoes_perimetricas(layout, mapa, dados, extensao_mapa)

    _adicionar_cabecalho(layout, "ROTEIRO PERIMÉTRICO", 10, 239, 380, 6, 8)
    _adicionar_cabecalho(layout, "LADOS, AZIMUTES E ÂNGULOS", 10, 245, 156, 5, 5)
    _adicionar_cabecalho(layout, "COORDENADAS UTM", 166, 245, 96, 5, 5)
    _adicionar_cabecalho(layout, "COORDENADAS GEOGRÁFICAS", 262, 245, 128, 5, 5)
    roteiro = _camada_roteiro_completo(dados["segmentos"], dados["crs"])
    tabela = QgsLayoutItemAttributeTable(layout)
    layout.addMultiFrame(tabela)
    tabela.setResizeMode(QgsLayoutMultiFrame.UseExistingFrames)
    tabela.setVectorLayer(roteiro)
    tabela.setMaximumNumberOfFeatures(min(len(dados["segmentos"]), 8))
    campos_roteiro = [
        "Ini", "Fim", "Azimute", "Angulo", "Dist_m", "Norte_m", "Leste_m",
        "Latitude", "Longitude", "Limite", "Confront",
    ]
    tabela.setDisplayedFields(campos_roteiro)
    # Mantém a tabela dentro da faixa imprimível, com margem extra à direita.
    aliases_roteiro = {
        "Ini": "Vértice inicial", "Fim": "Vértice final",
        "Azimute": "Azimute", "Angulo": "Ângulo interno", "Dist_m": "Distância (m)",
        "Norte_m": "Norte (m)", "Leste_m": "Leste (m)",
        "Latitude": "Latitude", "Longitude": "Longitude",
        "Limite": "Tipo de limite", "Confront": "Confrontante",
    }
    # As duas últimas colunas reservam espaço explícito para os dados
    # preenchidos em "Editar limites e confrontantes".
    larguras_roteiro = [largura * fator_folha for largura in (23, 23, 28, 23, 22, 30, 30, 24, 24, 45, 85)]
    colunas_roteiro = tabela.columns()
    for indice, campo in enumerate(campos_roteiro):
        colunas_roteiro[indice].setHeading(aliases_roteiro[campo])
        colunas_roteiro[indice].setWidth(larguras_roteiro[indice])
    tabela.setColumns(colunas_roteiro)
    # Um pequeno aumento melhora a leitura da tabela impressa sem comprometer
    # as colunas mais longas (confrontante e tipo de limite).
    tamanho_fonte_tabela = 8.0 * fator_folha
    fonte_corpo_tabela = QFont("Arial")
    fonte_corpo_tabela.setPointSizeF(tamanho_fonte_tabela)
    fonte_cabecalho_tabela = QFont(fonte_corpo_tabela)
    fonte_cabecalho_tabela.setBold(True)
    tabela.setContentFont(fonte_corpo_tabela)
    tabela.setHeaderFont(fonte_cabecalho_tabela)
    tabela.setCellMargin(0.6 * fator_folha)
    quadro_tabela = QgsLayoutFrame(layout, tabela)
    quadro_tabela.attemptMove(QgsLayoutPoint(10, 250, QgsUnitTypes.LayoutMillimeters))
    quadro_tabela.attemptResize(QgsLayoutSize(380, 37, QgsUnitTypes.LayoutMillimeters))
    quadro_tabela.setFrameEnabled(True)
    quadro_tabela.setFrameStrokeColor(COR_BORDA)
    tabela.addFrame(quadro_tabela)

    if len(dados["segmentos"]) > 8:
        pagina_roteiro = QgsLayoutItemPage(layout)
        pagina_roteiro.setPageSize("A3", QgsLayoutItemPage.Landscape)
        layout.pageCollection().addPage(pagina_roteiro)
        y = pagina_roteiro.pos().y()
        _adicionar_cabecalho(layout, "ROTEIRO PERIMÉTRICO — CONTINUAÇÃO", 10, y + 10, 400, 10, 13)
        tabela.setMaximumNumberOfFeatures(len(dados["segmentos"]))
        quadro_continuacao = QgsLayoutFrame(layout, tabela)
        quadro_continuacao.attemptMove(QgsLayoutPoint(10, y + 25, QgsUnitTypes.LayoutMillimeters))
        quadro_continuacao.attemptResize(QgsLayoutSize(380, 250, QgsUnitTypes.LayoutMillimeters))
        quadro_continuacao.setFrameEnabled(True)
        quadro_continuacao.setFrameStrokeColor(COR_BORDA)
        tabela.addFrame(quadro_continuacao)

    _adicionar_cabecalho(layout, "PROJEÇÃO CARTOGRÁFICA", 262, 190, 148, 7, 9)
    _adicionar_rotulo(layout,
        f"Sistema: {dados['crs_descricao']}\n"
        f"Identificação: {dados['crs_authid']}  |  Unidade: metro\n"
        f"Escala aproximada: {_texto_escala(mapa, extensao_mapa, fator_folha)}\n"
        "Peça de conferência técnica; certificação oficial pelo SIGEF.",
        262, 197, 148, 20, 6, False, True, fundo=COR_PAINEL,
        alinhamento_vertical=Qt.AlignTop)

    _adicionar_cabecalho(layout, "CONVENÇÕES", 262, 220, 148, 7, 9)
    _adicionar_rotulo(layout, "", 262, 227, 148, 11, 6, False, True, fundo=COR_PAINEL)
    _adicionar_rotulo(layout, "━━  Limite do imóvel", 266, 227, 68, 4.5, 7,
                      cor_texto=COR_LIMITE)
    _adicionar_rotulo(layout, "●  Vértice identificado", 338, 227, 70, 4.5, 7,
                      cor_texto=COR_PRIMARIA)
    legenda_grade = "UTM" if "+proj=utm" in (dados["crs"].toProj() or "") else "SRC"
    _adicionar_rotulo(layout, f"┼  Grade de coordenadas ({legenda_grade})", 266, 233, 68, 4.5, 7,
                      cor_texto=COR_DESTAQUE)
    _adicionar_rotulo(layout, "Folha 1 — Planta georreferenciada", 338, 233, 70, 4.5, 7,
                      alinhamento=Qt.AlignRight, cor_texto=COR_TEXTO)

    _ajustar_layout_a_folha(layout, formato_folha, fator_folha)
    return layout


def gerar_layout_tematico(
    dados, identificacao, tema, titulo, fontes="", data_referencia="", formato_folha="A3",
):
    """Cria prancha temática a partir de um tema salvo no projeto QGIS."""
    projeto = QgsProject.instance()
    colecao_temas = projeto.mapThemeCollection()
    if not colecao_temas.hasMapTheme(tema):
        raise ValueError(f'O tema "{tema}" não existe mais neste projeto.')

    camada_origem = projeto.mapLayer(dados.get("camada_origem_id", ""))
    if not camada_origem or not camada_origem.isValid():
        raise RuntimeError("A camada da poligonal não está mais disponível no projeto.")
    camadas_tema = colecao_temas.mapThemeVisibleLayers(tema)
    ids_visiveis = {camada.id() for camada in camadas_tema if camada and camada.isValid()}
    if camada_origem.id() not in ids_visiveis:
        raise ValueError(
            f'O tema "{tema}" precisa incluir a camada "{camada_origem.name()}" '
            "para mostrar o limite do imóvel. Ative essa camada e atualize o tema no QGIS."
        )

    fator_folha, formato_folha = _fator_folha(formato_folha)
    identificador = re.sub(r"[^A-Za-z0-9_-]+", "_", str(tema)).strip("_")[:32] or "Tema"
    nome_layout = f"Mapa_Tematico_{identificador}_{uuid.uuid4().hex[:8]}"
    gerente = projeto.layoutManager()
    layout = QgsPrintLayout(projeto)
    layout.initializeDefaults()
    layout.pageCollection().page(0).setPageSize("A3", QgsLayoutItemPage.Landscape)
    layout.setName(nome_layout)
    gerente.addLayout(layout)

    moldura = QgsLayoutItemShape(layout)
    moldura.setShapeType(QgsLayoutItemShape.Rectangle)
    moldura.setSymbol(QgsFillSymbol.createSimple({
        "style": "no", "outline_style": "solid",
        "outline_color": COR_BORDA.name(), "outline_width": "0.35",
    }))
    moldura.attemptMove(QgsLayoutPoint(8, 8, QgsUnitTypes.LayoutMillimeters), False)
    moldura.attemptResize(QgsLayoutSize(404, 281, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(moldura)

    largura_mapa, altura_mapa = 254.0, 209.0
    extensao_mapa = _extensao_centralizada(
        dados["geometria"], largura_mapa, altura_mapa, margem=1.55,
    )
    mapa = QgsLayoutItemMap(layout)
    mapa.setId("agrimensura_mapa_tematico")
    layout.addLayoutItem(mapa)
    mapa.setCrs(dados["crs"])
    mapa.attemptMove(QgsLayoutPoint(24, 38, QgsUnitTypes.LayoutMillimeters))
    mapa.attemptResize(QgsLayoutSize(largura_mapa, altura_mapa, QgsUnitTypes.LayoutMillimeters))
    mapa.setBackgroundEnabled(True)
    mapa.setBackgroundColor(COR_PAINEL)
    mapa.setFrameEnabled(True)
    mapa.setFrameStrokeColor(COR_MOLDURA_MAPA)
    mapa.setFollowVisibilityPresetName(tema)
    mapa.setFollowVisibilityPreset(True)
    mapa.setKeepLayerSet(False)
    mapa.setExtent(extensao_mapa)
    _configurar_grade_coordenadas(mapa, extensao_mapa, anotacoes=True)

    _adicionar_cabecalho(layout, str(titulo).strip() or tema, 10, 9, 400, 13, 14)
    local = identificacao.get("municipio") or "Município não informado"
    imovel = identificacao.get("imovel") or "Imóvel não informado"
    _adicionar_rotulo(
        layout,
        f"{imovel}  |  {local}  |  Tema do QGIS: {tema}",
        12, 24, 396, 8, 7, alinhamento=Qt.AlignHCenter,
    )

    legenda = QgsLayoutItemLegend(layout)
    legenda.setId("agrimensura_legenda_tematico")
    legenda.setTitle("LEGENDA")
    legenda.setLinkedMap(mapa)
    legenda.setAutoUpdateModel(True)
    legenda.setColumnCount(1)
    legenda.setSymbolWidth(7.0)
    legenda.setSymbolHeight(4.0)
    legenda.setBackgroundEnabled(True)
    legenda.setBackgroundColor(COR_PAINEL)
    legenda.setFrameEnabled(True)
    legenda.setFrameStrokeColor(COR_BORDA)
    layout.addLayoutItem(legenda)
    legenda.attemptMove(QgsLayoutPoint(286, 38, QgsUnitTypes.LayoutMillimeters))
    legenda.attemptResize(QgsLayoutSize(124, 112, QgsUnitTypes.LayoutMillimeters))

    area_ha = _numero_tabela(dados["area_ha"])
    perimetro_m = _numero_tabela(dados["perimetro_m"])
    _adicionar_cabecalho(layout, "IMÓVEL E ÁREA DE ESTUDO", 286, 155, 124, 7, 7)
    _adicionar_rotulo(
        layout,
        f"Imóvel: {imovel}\nMunicípio/UF: {local}\nÁrea: {area_ha} ha ({_numero_tabela(dados['area_m2'])} m²)\n"
        f"Perímetro: {perimetro_m} m\nResponsável técnico: {identificacao.get('responsavel') or 'Não informado'}",
        286, 162, 124, 48, 6.2, False, True, fundo=COR_PAINEL,
        alinhamento_vertical=Qt.AlignTop,
    )

    _adicionar_cabecalho(layout, "REFERÊNCIA CARTOGRÁFICA", 286, 215, 124, 7, 7)
    _adicionar_rotulo(
        layout,
        f"SRC: {dados['crs_authid']}\nProjeção: {dados['crs_descricao']}\n"
        f"Escala inicial: {_texto_escala(mapa, extensao_mapa, fator_folha)}\n"
        f"Fontes:\n{_quebrar_texto(fontes or identificacao.get('fontes'), 45)}\n"
        f"Data de referência: {data_referencia or identificacao.get('data_referencia') or 'Não informada'}",
        286, 222, 124, 34, 5.6, False, True, fundo=COR_PAINEL,
        alinhamento_vertical=Qt.AlignTop,
    )
    _adicionar_escala_grafica(layout, mapa, 288, 261, extensao_mapa, largura_segmento=15.0)
    _adicionar_seta_norte(layout, 398, 272, 0.0, 13.0, "N", QColor("#222222"))

    _adicionar_rotulo(
        layout,
        f"Elaborado em {date.today().strftime('%d/%m/%Y')}  |  "
        "Mapa de apoio à análise técnica; confira fontes, escala e escopo definidos pelo órgão licenciador.",
        10, 273, 380, 9, 5.4, alinhamento=Qt.AlignLeft,
    )
    _ajustar_layout_a_folha(layout, formato_folha, fator_folha)
    return layout


def atualizar_layout(layout, dados):
    """Atualiza somente os elementos ligados à poligonal no layout existente.

    Moldura, carimbo, escalas e demais itens gráficos são preservados. Os
    deslocamentos feitos manualmente nos rótulos são mantidos relativamente
    ao vértice ou segmento correspondente.
    """
    projeto = QgsProject.instance()
    camadas = list(projeto.mapLayers().values())
    camada_vertices = next((c for c in camadas if c.customProperty(MARCADOR_CAMADA_TEMPORARIA, "") == "vertices"), None)
    camada_limite = next((c for c in camadas if c.customProperty(MARCADOR_CAMADA_TEMPORARIA, "") == "limite_planta"), None)
    camada_roteiro = next((c for c in camadas if c.customProperty(MARCADOR_CAMADA_TEMPORARIA, "") == "roteiro_completo"), None)
    if camada_vertices is None or camada_roteiro is None:
        raise RuntimeError("As camadas vinculadas à planta não foram encontradas; recrie a planta uma vez.")

    mapa = layout.itemById("agrimensura_mapa_principal")
    if mapa is None:
        raise RuntimeError("O mapa principal não foi encontrado no layout atual.")
    itens = layout.items()
    labels_vertices = {
        item.customProperty("agrimensura/vertex_id", ""): item
        for item in itens if isinstance(item, QgsLayoutItemLabel)
        and item.customProperty("agrimensura/vertex_id", "")
    }
    faltantes = [v["id"] for v in dados["vertices"] if v["id"] not in labels_vertices]
    if faltantes:
        raise RuntimeError(
            "O layout atual não possui rótulos para: " + ", ".join(faltantes) +
            ". A quantidade ou identidade dos vértices mudou; recrie a planta para incluir os novos rótulos."
        )
    extensao = mapa.extent()
    if extensao.width() <= 0 or extensao.height() <= 0:
        raise ValueError("A extensão atual do mapa é inválida; os itens da prancha foram preservados.")

    if camada_limite is not None:
        camada_origem = projeto.mapLayer(dados.get("camada_origem_id", ""))
        feicao_origem = (
            camada_origem.getFeature(dados.get("feicao_origem_id"))
            if camada_origem and camada_origem.isValid() else None
        )
        if feicao_origem and feicao_origem.isValid() and feicao_origem.hasGeometry():
            geometria_limite = QgsGeometry(feicao_origem.geometry())
            crs_geometria = camada_origem.crs()
            atributos_limite = feicao_origem.attributes()
        else:
            geometria_limite = QgsGeometry(dados["geometria"])
            crs_geometria = dados["crs"]
            atributos_limite = []
        if crs_geometria != camada_limite.crs():
            geometria_limite.transform(QgsCoordinateTransform(crs_geometria, camada_limite.crs(), projeto))
        feicoes_limite = list(camada_limite.getFeatures())
        if not feicoes_limite:
            raise RuntimeError("A feição isolada do limite não foi encontrada; recrie a planta.")
        feicao_limite = feicoes_limite[0]
        provedor_limite = camada_limite.dataProvider()
        if not provedor_limite.changeGeometry(feicao_limite.id(), geometria_limite):
            raise RuntimeError("Não foi possível atualizar o limite isolado no layout.")
        if atributos_limite:
            valores = {
                indice: valor for indice, valor in enumerate(atributos_limite)
                if indice < len(camada_limite.fields())
            }
            provedor_limite.changeAttributeValues({feicao_limite.id(): valores})
        camada_limite.updateExtents()

    # Atualizar os pontos na mesma camada mantém a referência e a ordem de desenho do mapa.
    provedor = camada_vertices.dataProvider()
    provedor.deleteFeatures([f.id() for f in camada_vertices.getFeatures()])
    feicoes = []
    for vertice in dados["vertices"]:
        f = QgsFeature(camada_vertices.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(vertice["leste"], vertice["norte"])))
        f.setAttributes([vertice["id"], vertice["id"]])
        feicoes.append(f)
    if feicoes:
        provedor.addFeatures(feicoes)
    camada_vertices.updateExtents()

    # Atualizar as feições da tabela no datasource já ligado ao QgsLayoutItemAttributeTable.
    crs_geo = QgsCoordinateReferenceSystem("EPSG:4674")
    transformar = QgsCoordinateTransform(dados["crs"], crs_geo, projeto)
    provedor = camada_roteiro.dataProvider()
    provedor.deleteFeatures([f.id() for f in camada_roteiro.getFeatures()])
    feicoes = []
    for segmento in dados["segmentos"]:
        inicio, fim = segmento["inicio"], segmento["fim"]
        geo = transformar.transform(QgsPointXY(fim["leste"], fim["norte"]))
        f = QgsFeature(camada_roteiro.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY([
            QgsPointXY(inicio["leste"], inicio["norte"]),
            QgsPointXY(fim["leste"], fim["norte"]),
        ]))
        f.setAttributes([
            inicio["id"], fim["id"], segmento["azimute_dms"],
            segmento.get("angulo_interno_dms", "—"),
            _numero_tabela(segmento["distancia_m"]), _numero_tabela(fim["norte"]),
            _numero_tabela(fim["leste"]), _coordenada_geografica_dms(geo.y(), True),
            _coordenada_geografica_dms(geo.x(), False),
            segmento.get("tipo_limite") or "—", segmento.get("confrontante") or "—",
        ])
        feicoes.append(f)
    if feicoes:
        provedor.addFeatures(feicoes)
    camada_roteiro.updateExtents()

    posicao, tamanho = mapa.positionWithUnits(), mapa.sizeWithUnits()
    largura, altura = tamanho.width(), tamanho.height()

    def ponto_layout(vertice):
        return (
            posicao.x() + (vertice["leste"] - extensao.xMinimum()) / extensao.width() * largura,
            posicao.y() + (extensao.yMaximum() - vertice["norte"]) / extensao.height() * altura,
        )

    for indice, vertice in enumerate(dados["vertices"], start=1):
        item = labels_vertices.get(vertice["id"])
        if item is None:
            raise RuntimeError(
                f"O rótulo do vértice {vertice['id']} não existe no layout atual. "
                "Os dados foram recalculados; recrie a planta para refletir a nova quantidade de vértices."
            )
        base_x, base_y = item.customProperty("agrimensura/anchor_x", item.pos().x()), item.customProperty("agrimensura/anchor_y", item.pos().y())
        desloc_x, desloc_y = item.pos().x() - float(base_x), item.pos().y() - float(base_y)
        x, y = ponto_layout(vertice)
        # O deslocamento inicial da identificação é mantido em unidades da prancha.
        offset_x = float(item.customProperty("agrimensura/offset_x", 5.5))
        offset_y = float(item.customProperty("agrimensura/offset_y", -1.75))
        item.attemptMove(QgsLayoutPoint(x + offset_x + desloc_x, y + offset_y + desloc_y, QgsUnitTypes.LayoutMillimeters))
        angulo_vertice = next(
            (s.get("angulo_interno_dms", "—") for s in dados["segmentos"]
             if s["inicio"]["id"] == vertice["id"]),
            "—",
        )
        item.setText(f"{vertice['id']}\n∠ {angulo_vertice}")
        item.attemptResize(QgsLayoutSize(20, 9, QgsUnitTypes.LayoutMillimeters))
        item.setCustomProperty("agrimensura/anchor_x", x + offset_x)
        item.setCustomProperty("agrimensura/anchor_y", y + offset_y)

    por_id = {v["id"]: v for v in dados["vertices"]}
    segmentos_por_id = {
        f"{s['inicio']['id']}|{s['fim']['id']}": s for s in dados["segmentos"]
    }
    for item in itens:
        if not isinstance(item, QgsLayoutItemLabel):
            continue
        chave = item.customProperty("agrimensura/segment_id", "")
        if not chave:
            continue
        segmento = segmentos_por_id.get(chave)
        if segmento is None:
            continue
        inicio, fim = segmento["inicio"], segmento["fim"]
        x1, y1 = ponto_layout(inicio)
        x2, y2 = ponto_layout(fim)
        centro_x, centro_y = (x1 + x2) / 2, (y1 + y2) / 2
        base_x, base_y = float(item.customProperty("agrimensura/anchor_x", centro_x)), float(item.customProperty("agrimensura/anchor_y", centro_y))
        antigo_x, antigo_y = float(item.pos().x()), float(item.pos().y())
        dx, dy = antigo_x - base_x, antigo_y - base_y
        largura_item, altura_item = item.sizeWithUnits().width(), item.sizeWithUnits().height()
        item.attemptMove(QgsLayoutPoint(centro_x - largura_item / 2 + dx, centro_y - altura_item / 2 + dy, QgsUnitTypes.LayoutMillimeters))
        distancia = f"{segmento['distancia_m']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        item.setText(f"Az. {segmento['azimute_dms']}\nD: {distancia} m")
        angulo = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if angulo > 90:
            angulo -= 180
        elif angulo < -90:
            angulo += 180
        item.setItemRotation(angulo, True)
        item.setCustomProperty("agrimensura/anchor_x", centro_x - largura_item / 2)
        item.setCustomProperty("agrimensura/anchor_y", centro_y - altura_item / 2)

    area_item = layout.itemById("agrimensura_area_perimetro")
    if area_item:
        area_item.setText(
            f"Área: {_numero_tabela(dados['area_m2'])} m²\n{_numero_tabela(dados['area_ha'])} ha\n"
            f"Perímetro: {_numero_tabela(dados['perimetro_m'])} m"
        )
    mapa.refresh()
    layout.refresh()
    return True


def exportar_pdf_alta_resolucao(layout, caminho):
    """Exporta PDF em alta resolução e saída vetorial sempre que possível."""
    configuracao = QgsLayoutExporter.PdfExportSettings()
    configuracao.dpi = 300
    # Mantém a saída vetorial padrão quando suportada, mas permite ao QGIS
    # rasterizar apenas os itens que não conseguem ser renderizados em vetor.
    configuracao.forceVectorOutput = False
    configuracao.rasterizeWholeImage = False
    resultado = QgsLayoutExporter(layout).exportToPdf(caminho, configuracao)
    if resultado != QgsLayoutExporter.Success:
        raise RuntimeError("O QGIS não conseguiu exportar o PDF da planta.")
    return caminho

