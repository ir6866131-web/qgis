"""Interface e lógica principal do processamento da poligonal."""
import math
import os
import re
import traceback
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QPushButton,
    QTextEdit, QFileDialog, QMessageBox, QDialogButtonBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    QgsProject, QgsWkbTypes, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsGeometry, QgsMessageLog, QgsPointXY, QgsUnitTypes,
    QgsVectorFileWriter, QgsVectorLayer, Qgis,
)
from .memorial_builder import construir_memorial, exportar_docx, exportar_roteiro_csv
from .polygon_preview import PolygonOrderPreviewDialog


def azimute_dms(delta_e, delta_n):
    """Azimute 0° no norte, positivo no sentido horário, com arredondamento a segundo."""
    graus = math.degrees(math.atan2(delta_e, delta_n)) % 360.0
    segundos_total = int(round(graus * 3600)) % (360 * 3600)
    g, resto = divmod(segundos_total, 3600)
    m, s = divmod(resto, 60)
    return graus, f'{g:03d}°{m:02d}\'{s:02d}"'


def processar_poligonal(
    feicao, crs_origem, crs_destino, prefixo="V", codigo_credenciado=None,
    tipo_vertice="V", sequencia_inicial=1,
):
    """Transforma e calcula geometria; espera uma única feição poligonal simples.

    Quando ``codigo_credenciado`` é informado, os vértices recebem o padrão
    ``CCCC-T-N`` usado pelo INCRA: código do credenciado, tipo e sequencial.
    O parâmetro ``prefixo`` é preservado para compatibilidade com chamadas
    antigas do plugin.
    """
    if not feicao or not feicao.hasGeometry() or feicao.geometry().isNull() or feicao.geometry().isEmpty():
        raise ValueError("A feição escolhida não possui uma geometria válida.")
    if QgsWkbTypes.geometryType(feicao.geometry().wkbType()) != QgsWkbTypes.PolygonGeometry:
        raise ValueError("A feição escolhida não é um polígono.")
    geometria = QgsGeometry(feicao.geometry())
    if crs_origem != crs_destino:
        transformacao = QgsCoordinateTransform(crs_origem, crs_destino, QgsProject.instance())
        geometria.transform(transformacao)
    if geometria.isMultipart():
        raise ValueError("Polígonos multiparte não são suportados; separe a área antes de processar.")
    if not geometria.isGeosValid():
        raise ValueError("A poligonal possui geometria inválida. Corrija a topologia antes de processar.")
    poligono = geometria.asPolygon()
    if len(poligono) != 1:
        raise ValueError("Polígonos com furos não são suportados; trate os anéis internos antes de processar.")
    anel = poligono[0]
    if len(anel) < 4:
        raise ValueError("A poligonal precisa ter ao menos três vértices.")
    pontos = anel[:-1] if anel[0] == anel[-1] else anel
    if codigo_credenciado:
        codigo_credenciado = codigo_credenciado.upper().strip()
        tipo_vertice = tipo_vertice.upper().strip()
        if not re.fullmatch(r"[A-Z0-9]{4}", codigo_credenciado):
            raise ValueError("O código do credenciado deve possuir exatamente quatro caracteres alfanuméricos.")
        if tipo_vertice not in {"M", "P", "V"}:
            raise ValueError("O tipo de vértice deve ser M, P ou V.")
        if sequencia_inicial < 1:
            raise ValueError("A sequência inicial dos vértices deve ser maior que zero.")
        vertices = [
            {
                "id": f"{codigo_credenciado}-{tipo_vertice}-{sequencia_inicial + indice}",
                "tipo": tipo_vertice,
                "norte": ponto.y(),
                "leste": ponto.x(),
            }
            for indice, ponto in enumerate(pontos)
        ]
    else:
        vertices = [
            {"id": f"{prefixo}-{i:02d}", "tipo": "", "norte": p.y(), "leste": p.x()}
            for i, p in enumerate(pontos, start=1)
        ]
    segmentos = []
    for i, inicio in enumerate(vertices):
        fim = vertices[(i + 1) % len(vertices)]
        de = fim["leste"] - inicio["leste"]
        dn = fim["norte"] - inicio["norte"]
        distancia = math.hypot(de, dn)
        if distancia <= 0:
            raise ValueError(f"Há vértices coincidentes: {inicio['id']} e {fim['id']}.")
        az, dms = azimute_dms(de, dn)
        segmentos.append({
            "inicio": inicio, "fim": fim, "distancia_m": distancia,
            "azimute_graus": az, "azimute_dms": dms,
            "tipo_limite": "", "confrontante": "",
        })
    # Ângulo interno no vértice inicial de cada alinhamento, respeitando o
    # sentido (horário/anti-horário) do anel e também vértices côncavos.
    area_assinada = sum(
        vertices[i]["leste"] * vertices[(i + 1) % len(vertices)]["norte"]
        - vertices[(i + 1) % len(vertices)]["leste"] * vertices[i]["norte"]
        for i in range(len(vertices))
    )
    sentido = 1 if area_assinada > 0 else -1
    for i, segmento in enumerate(segmentos):
        az_entrada = segmentos[i - 1]["azimute_graus"]
        diferenca = (segmento["azimute_graus"] - az_entrada + 180) % 360 - 180
        angulo = (180 + sentido * diferenca) % 360
        segundos = int(round(angulo * 3600)) % (360 * 3600)
        graus, resto = divmod(segundos, 3600)
        minutos, segundos = divmod(resto, 60)
        segmento["angulo_interno_graus"] = angulo
        segmento["angulo_interno_dms"] = f"{graus:03d}°{minutos:02d}'{segundos:02d}\""
    crs_geografico = QgsCoordinateReferenceSystem("EPSG:4674")
    transformacao_geo = QgsCoordinateTransform(crs_destino, crs_geografico, QgsProject.instance())
    for vertice in vertices:
        ponto_geo = transformacao_geo.transform(QgsPointXY(vertice["leste"], vertice["norte"]))
        vertice["latitude"] = ponto_geo.y()
        vertice["longitude"] = ponto_geo.x()
    area = geometria.area()
    if area <= 0:
        raise ValueError("A poligonal tem área nula e não pode gerar memorial ou planta.")
    return {
        "geometria": geometria, "vertices": vertices, "segmentos": segmentos,
        "area_m2": area, "area_ha": area / 10000.0, "perimetro_m": geometria.length(),
        "crs": crs_destino, "crs_authid": crs_destino.authid(), "crs_descricao": crs_destino.description(),
        "codigo_credenciado": codigo_credenciado or "", "sequencia_inicial": sequencia_inicial,
    }


def epsg_utm_sirgas_automatico(feicao, crs_origem):
    """Retorna o EPSG SIRGAS 2000 / UTM adequado ao centro da poligonal no Brasil.

    A zona é definida pela longitude do centróide. Para imóveis muito próximos
    à divisa entre zonas UTM, o responsável técnico pode desmarcar a opção
    automática e definir manualmente o SRC de cálculo.
    """
    geometria = feicao.geometry()
    if geometria.isEmpty():
        raise ValueError("Não foi possível identificar o centro de uma geometria vazia.")
    sirgas_geografico = QgsCoordinateReferenceSystem("EPSG:4674")
    transformacao = QgsCoordinateTransform(crs_origem, sirgas_geografico, QgsProject.instance())
    centro = transformacao.transform(QgsPointXY(geometria.centroid().asPoint()))
    zona = int((centro.x() + 180) / 6) + 1
    if centro.y() >= 0 or not 17 <= zona <= 25:
        raise ValueError(
            "A detecção automática SIRGAS 2000 / UTM atende às zonas 17S a 25S do Brasil. "
            "Informe o SRC projetado manualmente para esta localização."
        )
    return f"EPSG:{31960 + zona}"


def campo_ordem_automatico(camada):
    """Encontra o campo mais provável para ordenar os vértices de uma camada."""
    nomes = {campo.name().casefold(): campo.name() for campo in camada.fields()}
    for candidato in ("ordem", "sequencia", "sequência", "seq", "numero", "número", "num", "vertice", "vértice"):
        if candidato in nomes:
            return nomes[candidato]
    return None


def ordenar_pontos_para_poligono(feicoes, campo_ordem=None):
    """Extrai e ordena pontos para formar o anel de uma poligonal.

    Um campo de ordem é a forma confiável de preservar o levantamento. Sem ele,
    a ordem é estimada pelo ângulo em torno do centróide, adequada apenas para
    contornos convexos ou aproximadamente convexos.
    """
    pontos = []
    for feicao in feicoes:
        if not feicao.hasGeometry() or feicao.geometry().isNull() or feicao.geometry().isEmpty():
            raise ValueError("Há uma feição de ponto sem geometria válida.")
        if QgsWkbTypes.geometryType(feicao.geometry().wkbType()) != QgsWkbTypes.PointGeometry:
            raise ValueError("A camada escolhida deve conter apenas geometrias de ponto.")
        if feicao.geometry().isMultipart():
            raise ValueError("Pontos multiparte não são suportados para criar a poligonal.")
        ponto = QgsPointXY(feicao.geometry().asPoint())
        pontos.append((feicao, ponto))
    if len(pontos) < 3:
        raise ValueError("Selecione ou carregue pelo menos três pontos para criar a poligonal.")
    coordenadas = [(ponto.x(), ponto.y()) for _, ponto in pontos]
    if len(set(coordenadas)) != len(coordenadas):
        raise ValueError("Há pontos coincidentes. Remova ou corrija as duplicidades antes de criar a poligonal.")

    if campo_ordem:
        def chave(item):
            valor = item[0][campo_ordem]
            if valor is None or str(valor).strip() == "":
                raise ValueError(f"O campo de ordem '{campo_ordem}' possui valor vazio.")
            try:
                return (0, float(str(valor).replace(",", ".")))
            except (TypeError, ValueError):
                return (1, str(valor).casefold())
        ordenados = sorted(pontos, key=chave)
        chaves = [chave(item) for item in ordenados]
        if len(set(chaves)) != len(chaves):
            raise ValueError(f"O campo de ordem '{campo_ordem}' possui valores repetidos.")
        return [ponto for _, ponto in ordenados], campo_ordem

    centro_x = sum(ponto.x() for _, ponto in pontos) / len(pontos)
    centro_y = sum(ponto.y() for _, ponto in pontos) / len(pontos)
    ordenados = sorted(
        pontos,
        key=lambda item: math.atan2(item[1].y() - centro_y, item[1].x() - centro_x),
    )
    return [ponto for _, ponto in ordenados], None


class AgrimensuraDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface, self.dados, self.layout_gerado = iface, None, None
        self.layout_tematico = None
        self.layout_para_pdf = None
        self.formato_layout_pdf = None
        self.setWindowTitle("Agrimensura — Memorial e Planta")
        self.resize(820, 700)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.camadas = QComboBox()
        for camada in QgsProject.instance().mapLayers().values():
            if camada.type() == camada.VectorLayer and QgsWkbTypes.geometryType(camada.wkbType()) == QgsWkbTypes.PolygonGeometry:
                self.camadas.addItem(camada.name(), camada.id())
        form.addRow("Camada de polígono:", self.camadas)
        self.camadas_pontos = QComboBox()
        for camada in QgsProject.instance().mapLayers().values():
            if camada.type() == camada.VectorLayer and QgsWkbTypes.geometryType(camada.wkbType()) == QgsWkbTypes.PointGeometry:
                self.camadas_pontos.addItem(camada.name(), camada.id())
        self.campo_ordem = QComboBox()
        self.atualizar_campos_ordem()
        self.gerar_poligono_btn = QPushButton("Gerar polígono e calcular")
        self.gerar_poligono_btn.setToolTip(
            "Usa os pontos selecionados (ou todos os pontos da camada) e cria uma nova camada poligonal. "
            "Confira e, se necessário, reordene os pontos na prévia antes de confirmar."
        )
        form.addRow("Camada de pontos:", self.camadas_pontos)
        form.addRow("Campo de ordem dos pontos:", self.campo_ordem)
        form.addRow("Poligonal automática:", self.gerar_poligono_btn)
        self.epsg = QLineEdit("EPSG:31983")
        self.epsg.setToolTip("Use um SRC projetado em metros. Escolha a zona UTM correta para seu imóvel.")
        form.addRow("SRC projetado de cálculo:", self.epsg)
        self.utm_automatico = QCheckBox("Detectar automaticamente a zona UTM (SIRGAS 2000)")
        self.utm_automatico.setChecked(True)
        self.utm_automatico.setToolTip("Usa o centróide da poligonal para escolher a zona UTM brasileira adequada.")
        form.addRow("Projeção automática:", self.utm_automatico)
        self.imovel, self.proprietario, self.responsavel = QLineEdit(), QLineEdit(), QLineEdit()
        form.addRow("Imóvel:", self.imovel); form.addRow("Proprietário:", self.proprietario); form.addRow("Responsável técnico:", self.responsavel)
        self.matricula, self.municipio, self.art_rrt = QLineEdit(), QLineEdit(), QLineEdit()
        self.cpf = QLineEdit()
        self.cartorio = QLineEdit()
        self.codigo_sncr = QLineEdit()
        self.crea = QLineEdit()
        self.formacao = QLineEdit()
        self.matricula.setPlaceholderText("Opcional: matrícula, CCIR ou código interno")
        self.municipio.setPlaceholderText("Opcional: município / UF")
        self.art_rrt.setPlaceholderText("Opcional: número da ART ou RRT")
        self.fontes_dados = QLineEdit()
        self.fontes_dados.setPlaceholderText("Ex.: GNSS RTK, CAR/SICAR, MDE, imagem orbital")
        self.data_referencia = QLineEdit()
        self.data_referencia.setPlaceholderText("Ex.: 15/09/2026")
        form.addRow("Matrícula / cadastro:", self.matricula)
        form.addRow("Município / UF:", self.municipio)
        form.addRow("ART / RRT:", self.art_rrt)
        form.addRow("CPF do proprietário:", self.cpf)
        form.addRow("Cartório (CNS):", self.cartorio)
        form.addRow("Código INCRA / SNCR:", self.codigo_sncr)
        form.addRow("CREA:", self.crea)
        form.addRow("Formação:", self.formacao)
        form.addRow("Fontes cartográficas:", self.fontes_dados)
        form.addRow("Data de referência:", self.data_referencia)
        self.formato_folha = QComboBox()
        for formato in ("A4", "A3", "A2", "A1", "A0"):
            self.formato_folha.addItem(f"{formato} — Paisagem", formato)
        self.formato_folha.setCurrentIndex(self.formato_folha.findData("A3"))
        self.formato_folha.setToolTip(
            "Redimensiona a planta e o roteiro para a folha escolhida. A3 mantém o modelo de referência; "
            "A3 ou maior é recomendado para leitura confortável do roteiro completo."
        )
        form.addRow("Formato da folha:", self.formato_folha)
        self.codigo_credenciado = QLineEdit()
        self.codigo_credenciado.setMaxLength(4)
        self.codigo_credenciado.setPlaceholderText("Ex.: ABCD")
        self.codigo_credenciado.setToolTip("Código de quatro caracteres atribuído pelo INCRA ao profissional credenciado.")
        self.tipo_vertice = QComboBox()
        self.tipo_vertice.addItem("V - Virtual", "V")
        self.tipo_vertice.addItem("M - Marco", "M")
        self.tipo_vertice.addItem("P - Ponto", "P")
        self.sequencia_inicial = QLineEdit("1")
        self.sequencia_inicial.setToolTip("Primeiro número disponível na sequência de vértices do credenciado.")
        form.addRow("Código do credenciado INCRA (opcional):", self.codigo_credenciado)
        form.addRow("Tipo inicial dos vértices:", self.tipo_vertice)
        form.addRow("Sequência inicial:", self.sequencia_inicial)
        layout.addLayout(form)
        self.tematico_btn = QPushButton("Criar mapa temático")
        self.tematico_btn.setToolTip(
            "Cria uma prancha a partir de um tema salvo no QGIS, mantendo as camadas e a simbologia do tema."
        )
        self.tematico_btn.clicked.connect(self.criar_layout_tematico)
        layout.addWidget(self.tematico_btn)
        botoes = QDialogButtonBox()
        self.calcular_btn = botoes.addButton("Calcular", QDialogButtonBox.ActionRole)
        self.txt_btn = botoes.addButton("Exportar memorial Word", QDialogButtonBox.ActionRole)
        self.csv_btn = botoes.addButton("Exportar CSV", QDialogButtonBox.ActionRole)
        self.limites_btn = botoes.addButton("Editar limites e confrontantes", QDialogButtonBox.ActionRole)
        self.layout_btn = botoes.addButton("Criar planta no Layout", QDialogButtonBox.ActionRole)
        self.atualizar_planta_btn = botoes.addButton("Atualizar Planta", QDialogButtonBox.ActionRole)
        self.pdf_btn = botoes.addButton("Exportar último layout PDF (300 dpi)", QDialogButtonBox.ActionRole)
        self.curvas_btn = botoes.addButton("Gerar curvas de nível", QDialogButtonBox.ActionRole)
        botoes.addButton(QDialogButtonBox.Close)
        botoes.rejected.connect(self.reject)
        self.calcular_btn.clicked.connect(self.calcular)
        self.gerar_poligono_btn.clicked.connect(self.gerar_poligono_dos_pontos)
        self.camadas_pontos.currentIndexChanged.connect(self.atualizar_campos_ordem)
        self.txt_btn.clicked.connect(self.exportar_memorial)
        self.csv_btn.clicked.connect(self.exportar_roteiro)
        self.limites_btn.clicked.connect(self.editar_limites_confrontantes)
        self.layout_btn.clicked.connect(self.criar_layout)
        self.atualizar_planta_btn.clicked.connect(self.atualizar_planta)
        self.pdf_btn.clicked.connect(self.exportar_pdf)
        self.curvas_btn.clicked.connect(self.gerar_curvas_nivel)
        layout.addWidget(botoes)
        self.saida = QTextEdit(); self.saida.setReadOnly(True); layout.addWidget(self.saida)

    def gerar_curvas_nivel(self):
        """Abre a ferramenta independente de geração de curvas a partir de um raster."""
        try:
            from .contours import ContourDialog
            ContourDialog(self.iface, self).exec_()
        except Exception as erro:
            QMessageBox.critical(self, "Erro ao gerar curvas de nível", str(erro))

    def _identificacao(self):
        return {
            "imovel": self.imovel.text().strip(),
            "proprietario": self.proprietario.text().strip(),
            "responsavel": self.responsavel.text().strip(),
            "matricula": self.matricula.text().strip(),
            "municipio": self.municipio.text().strip(),
            "art_rrt": self.art_rrt.text().strip(),
            "cpf": self.cpf.text().strip(),
            "cartorio": self.cartorio.text().strip(),
            "codigo_sncr": self.codigo_sncr.text().strip(),
            "crea": self.crea.text().strip(),
            "formacao": self.formacao.text().strip(),
            "codigo_credenciado": self.codigo_credenciado.text().upper().strip(),
            "fontes": self.fontes_dados.text().strip(),
            "data_referencia": self.data_referencia.text().strip(),
        }

    def atualizar_campos_ordem(self):
        """Mostra somente atributos existentes na camada de pontos escolhida."""
        self.campo_ordem.clear()
        self.campo_ordem.addItem("Detectar automaticamente", None)
        camada = QgsProject.instance().mapLayer(self.camadas_pontos.currentData())
        if camada:
            for campo in camada.fields():
                self.campo_ordem.addItem(campo.name(), campo.name())

    def gerar_poligono_dos_pontos(self):
        """Cria uma camada temporária de polígono a partir dos pontos levantados."""
        try:
            camada = QgsProject.instance().mapLayer(self.camadas_pontos.currentData())
            if not camada:
                raise ValueError("Selecione uma camada de pontos.")
            feicoes = camada.selectedFeatures() or list(camada.getFeatures())
            campo = self.campo_ordem.currentData()
            if campo is None:
                campo = campo_ordem_automatico(camada)
            pontos, campo_usado = ordenar_pontos_para_poligono(feicoes, campo)
            if campo_usado:
                nota_previa = f"Ordem inicial pelo campo '{campo_usado}'. Confira e ajuste se necessário."
            else:
                nota_previa = (
                    "Ordem inicial estimada pela posição dos pontos. Essa estimativa pode falhar "
                    "em contornos côncavos; confira a sequência com o levantamento."
                )
            previa = PolygonOrderPreviewDialog(pontos, nota_previa, self)
            if previa.exec_() != QDialog.Accepted:
                return
            pontos = previa.pontos_ordenados()
            anel = pontos + [pontos[0]]
            geometria = QgsGeometry.fromPolygonXY([anel])
            if geometria.isNull() or geometria.isEmpty() or not geometria.isGeosValid() or geometria.area() <= 0:
                raise ValueError(
                    "Os pontos não formam uma poligonal válida. Confira a ordem dos vértices "
                    "e informe um campo de sequência quando o contorno não for convexo."
                )
            nome = f"Poligonal de {camada.name()}"
            poligonal = QgsVectorLayer(f"Polygon?crs={camada.crs().authid()}", nome, "memory")
            if not poligonal.isValid():
                raise RuntimeError("Não foi possível criar a camada temporária da poligonal.")
            feicao = QgsFeature(poligonal.fields())
            feicao.setGeometry(geometria)
            resultado = poligonal.dataProvider().addFeatures([feicao])
            sucesso = resultado[0] if isinstance(resultado, tuple) else resultado
            if not sucesso:
                raise RuntimeError("Não foi possível gravar a poligonal gerada.")
            poligonal.updateExtents()
            camada_saida = poligonal
            salvamento = self._oferecer_salvamento_geopackage(poligonal, nome)
            caminho_salvo = None
            if salvamento:
                caminho_salvo, nome_camada_salva = salvamento
                camada_persistente = QgsVectorLayer(
                    f"{caminho_salvo}|layername={nome_camada_salva}", nome, "ogr"
                )
                if camada_persistente.isValid():
                    camada_saida = camada_persistente
                else:
                    caminho_salvo = None
            QgsProject.instance().addMapLayer(camada_saida)
            self.camadas.addItem(camada_saida.name(), camada_saida.id())
            self.camadas.setCurrentIndex(self.camadas.count() - 1)
            self.iface.setActiveLayer(camada_saida)
            origem_ordem = f"ordem inicial pelo campo '{campo_usado}'" if campo_usado else "estimativa espacial"
            mensagem = (
                f"Poligonal criada com {len(pontos)} pontos, conferidos na prévia "
                f"({origem_ordem})."
            )
            if self.calcular():
                mensagem += " Distâncias, azimutes, área e perímetro foram calculados."
            if caminho_salvo:
                mensagem += f" Camada salva em {caminho_salvo}."
            self.iface.messageBar().pushSuccess("Agrimensura", mensagem)
        except Exception as erro:
            QMessageBox.critical(self, "Não foi possível criar a poligonal", str(erro))

    def _oferecer_salvamento_geopackage(self, camada, nome):
        """Salva uma cópia durável da poligonal se o usuário escolher."""
        resposta = QMessageBox.question(
            self,
            "Salvar poligonal",
            "A camada gerada fica temporária enquanto estiver em memória. "
            "Deseja salvar uma cópia em GeoPackage?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resposta != QMessageBox.Yes:
            return None

        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar poligonal em GeoPackage", "poligonal_agrimensura.gpkg",
            "GeoPackage (*.gpkg)",
        )
        if not caminho:
            return None
        if not caminho.lower().endswith(".gpkg"):
            caminho += ".gpkg"

        try:
            nome_camada = "poligonal_agrimensura"
            if os.path.exists(caminho):
                sufixo = 2
                while QgsVectorFileWriter.targetLayerExists(caminho, nome_camada):
                    nome_camada = f"poligonal_agrimensura_{sufixo}"
                    sufixo += 1

            opcoes = QgsVectorFileWriter.SaveVectorOptions()
            opcoes.driverName = "GPKG"
            opcoes.layerName = nome_camada
            if os.path.exists(caminho) and hasattr(opcoes, "actionOnExistingFile"):
                acao = getattr(QgsVectorFileWriter, "CreateOrOverwriteLayer", None)
                if acao is not None:
                    opcoes.actionOnExistingFile = acao
            resultado = QgsVectorFileWriter.writeAsVectorFormatV2(
                camada, caminho, QgsProject.instance().transformContext(), opcoes
            )
            if resultado[0] != QgsVectorFileWriter.NoError:
                detalhe = resultado[1] if len(resultado) > 1 else "Erro desconhecido do provedor OGR."
                raise RuntimeError(detalhe)
            uri = f"{caminho}|layername={nome_camada}"
            teste_camada = QgsVectorLayer(uri, nome, "ogr")
            if not teste_camada.isValid():
                raise RuntimeError("O GeoPackage foi escrito, mas o QGIS não conseguiu abrir a camada salva.")
        except Exception as erro:
            QMessageBox.warning(
                self, "Falha ao salvar GeoPackage",
                f"A poligonal será mantida temporariamente no projeto.\n\n{erro}",
            )
            return None
        return caminho, nome_camada

    def calcular(self):
        try:
            camada = QgsProject.instance().mapLayer(self.camadas.currentData())
            if not camada:
                raise ValueError("Selecione uma camada poligonal.")
            feicoes = camada.selectedFeatures() or list(camada.getFeatures())
            if not feicoes:
                raise ValueError("A camada não possui feições. Selecione uma feição ou desenhe a poligonal antes.")
            if self.utm_automatico.isChecked():
                self.epsg.setText(epsg_utm_sirgas_automatico(feicoes[0], camada.crs()))
            destino = QgsCoordinateReferenceSystem(self.epsg.text().strip())
            # isGeographic() está disponível em toda a série QGIS 3; isProjected()
            # não está exposto em todas as versões das bindings Python.
            if (
                not destino.isValid()
                or destino.isGeographic()
                or destino.mapUnits() != QgsUnitTypes.DistanceMeters
            ):
                raise ValueError("Informe um SRC projetado válido (por exemplo, EPSG:31983), com unidade em metros.")
            codigo = self.codigo_credenciado.text().upper().strip()
            if codigo and not re.fullmatch(r"[A-Z0-9]{4}", codigo):
                raise ValueError("Informe o código INCRA de quatro caracteres do profissional credenciado.")
            sequencia = 1
            if codigo:
                try:
                    sequencia = int(self.sequencia_inicial.text().strip())
                except ValueError as erro:
                    raise ValueError("A sequência inicial deve ser um número inteiro.") from erro
            self.dados = processar_poligonal(
                feicoes[0], camada.crs(), destino, codigo_credenciado=codigo,
                tipo_vertice=self.tipo_vertice.currentData(), sequencia_inicial=sequencia,
            )
            # Guarda a origem para que o layout possa acompanhar edições feitas
            # diretamente na camada do mapa.
            self.dados["camada_origem_id"] = camada.id()
            self.dados["feicao_origem_id"] = feicoes[0].id()
            memorial = construir_memorial(self.dados, self._identificacao())
            self.saida.setPlainText(memorial)
            return True
        except Exception as erro:
            QMessageBox.critical(self, "Não foi possível processar", str(erro))
            return False

    def atualizar_planta(self):
        """Relê a feição atual e sincroniza os dados e itens ligados à geometria."""
        if not self.dados:
            if not self.calcular():
                return False
        projeto = QgsProject.instance()
        camada = projeto.mapLayer(self.dados.get("camada_origem_id", ""))
        if not camada or not camada.isValid():
            QMessageBox.warning(self, "Atualizar Planta", "A camada original da poligonal não está mais disponível.")
            return False
        feicao = camada.getFeature(self.dados.get("feicao_origem_id"))
        if not feicao.isValid():
            QMessageBox.warning(self, "Atualizar Planta", "A feição da poligonal não foi encontrada na camada original.")
            return False
        try:
            destino = QgsCoordinateReferenceSystem(self.dados["crs_authid"])
            codigo = self.dados.get("codigo_credenciado") or None
            novos_dados = processar_poligonal(
                feicao, camada.crs(), destino,
                codigo_credenciado=codigo,
                tipo_vertice=self.tipo_vertice.currentData(),
                sequencia_inicial=self.dados.get("sequencia_inicial", 1),
            )
            # A identidade vem da ordem da poligonal, não da coordenada. Também
            # preservamos tipos individuais configurados em "Editar limites".
            for indice, vertice in enumerate(novos_dados["vertices"]):
                if indice < len(self.dados.get("vertices", [])):
                    antigo = self.dados["vertices"][indice]
                    vertice["id"] = antigo["id"]
                    vertice["tipo"] = antigo.get("tipo", "")
            for indice, segmento in enumerate(novos_dados["segmentos"]):
                segmento["inicio"] = novos_dados["vertices"][indice]
                segmento["fim"] = novos_dados["vertices"][(indice + 1) % len(novos_dados["vertices"])]
            novos_dados.update({
                "camada_origem_id": camada.id(),
                "feicao_origem_id": feicao.id(),
            })
            # Mantém os atributos descritivos por alinhamento quando os IDs persistem.
            anteriores = {
                (s["inicio"]["id"], s["fim"]["id"]): s
                for s in self.dados.get("segmentos", [])
            }
            for segmento in novos_dados["segmentos"]:
                anterior = anteriores.get((segmento["inicio"]["id"], segmento["fim"]["id"]), {})
                segmento["tipo_limite"] = anterior.get("tipo_limite", "")
                segmento["confrontante"] = anterior.get("confrontante", "")
            # Só troca o estado atual depois de validar e calcular toda a geometria.
            self.dados = novos_dados
            self.saida.setPlainText(construir_memorial(self.dados, self._identificacao()))
            if self.layout_gerado:
                from .layout_generator import atualizar_layout
                atualizar_layout(self.layout_gerado, self.dados)
            self.iface.messageBar().pushSuccess("Agrimensura", "Dados da poligonal e elementos vinculados atualizados.")
            return True
        except Exception as erro:
            QMessageBox.warning(self, "Não foi possível atualizar a planta", str(erro))
            return False

    def editar_limites_confrontantes(self):
        """Registra, por alinhamento, os dados exigidos para a pré-submissão."""
        if not self.dados:
            self.calcular()
        if not self.dados:
            return
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Limites e confrontantes por alinhamento")
        dialogo.resize(820, 320)
        layout = QVBoxLayout(dialogo)
        tabela = QTableWidget(len(self.dados["segmentos"]), 5, dialogo)
        tabela.setHorizontalHeaderLabels([
            "Vértice inicial", "Vértice final", "Tipo do vértice", "Tipo de limite", "Confrontante",
        ])
        tabela.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for linha, segmento in enumerate(self.dados["segmentos"]):
            for coluna, valor in ((0, segmento["inicio"]["id"]), (1, segmento["fim"]["id"]),
                                  (3, segmento.get("tipo_limite", "")), (4, segmento.get("confrontante", ""))):
                item = QTableWidgetItem(valor)
                if coluna < 2:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                tabela.setItem(linha, coluna, item)
            tipo = QComboBox(tabela)
            for codigo, descricao in (("M", "M - Marco"), ("P", "P - Ponto"), ("V", "V - Virtual")):
                tipo.addItem(descricao, codigo)
            tipo.setCurrentIndex(max(0, tipo.findData(segmento["inicio"].get("tipo") or "V")))
            tabela.setCellWidget(linha, 2, tipo)
        layout.addWidget(tabela)
        aviso = QTextEdit("Defina o tipo de cada vértice e informe o tipo de limite (por exemplo: cerca, estrada, linha ideal, curso d'água) e o imóvel confrontante.")
        aviso.setReadOnly(True)
        aviso.setMaximumHeight(44)
        layout.addWidget(aviso)
        botoes = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botoes.accepted.connect(dialogo.accept)
        botoes.rejected.connect(dialogo.reject)
        layout.addWidget(botoes)
        if dialogo.exec_() != QDialog.Accepted:
            return
        codigo = self.dados["codigo_credenciado"]
        sequencia = self.dados["sequencia_inicial"]
        for linha, segmento in enumerate(self.dados["segmentos"]):
            vertice = segmento["inicio"]
            tipo = tabela.cellWidget(linha, 2).currentData()
            vertice["tipo"] = tipo
            if codigo:
                vertice["id"] = f"{codigo}-{tipo}-{sequencia + linha}"
            segmento["tipo_limite"] = tabela.item(linha, 3).text().strip()
            segmento["confrontante"] = tabela.item(linha, 4).text().strip()
        self.saida.setPlainText(construir_memorial(self.dados, self._identificacao()))

    def exportar_memorial(self):
        if not self.dados:
            self.calcular()
        if not self.dados:
            return
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar memorial", "memorial_descritivo.docx", "Documento Word (*.docx)"
        )
        if caminho:
            if not caminho.lower().endswith(".docx"):
                caminho += ".docx"
            try:
                exportar_docx(construir_memorial(self.dados, self._identificacao()), caminho)
                self.iface.messageBar().pushSuccess("Agrimensura", f"Memorial salvo em {caminho}")
            except Exception as erro:
                QMessageBox.critical(
                    self,
                    "Erro ao exportar memorial",
                    f"Não foi possível salvar o documento. Feche o arquivo se ele estiver aberto "
                    f"e confira a permissão da pasta.\n\n{erro}",
                )

    def exportar_roteiro(self):
        """Salva uma tabela de conferência para planilhas e sistemas técnicos."""
        if not self.dados:
            self.calcular()
        if not self.dados:
            return
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar roteiro perimétrico", "roteiro_perimetrico.csv", "CSV (*.csv)"
        )
        if caminho:
            if not caminho.lower().endswith(".csv"):
                caminho += ".csv"
            try:
                exportar_roteiro_csv(self.dados, caminho)
                self.iface.messageBar().pushSuccess("Agrimensura", f"Roteiro CSV salvo em {caminho}")
            except Exception as erro:
                QMessageBox.critical(
                    self,
                    "Erro ao exportar roteiro",
                    f"Não foi possível salvar o CSV. Feche o arquivo se ele estiver aberto "
                    f"e confira a permissão da pasta.\n\n{erro}",
                )

    def criar_layout(self):
        if not self.dados:
            self.calcular()
        if self.dados:
            try:
                # Importação tardia: incompatibilidades no Composer não impedem o
                # carregamento do plugin nem a geração do memorial.
                from .layout_generator import gerar_layout
                self.layout_gerado = gerar_layout(
                    self.dados,
                    self._identificacao(),
                    formato_folha=self.formato_folha.currentData(),
                )
                self.layout_para_pdf = self.layout_gerado
                self.formato_layout_pdf = self.formato_folha.currentData()
                self.iface.openLayoutDesigner(self.layout_gerado)
            except Exception as erro:
                detalhes = traceback.format_exc()
                QgsMessageLog.logMessage(detalhes, "Agrimensura", Qgis.Critical)
                QMessageBox.critical(
                    self,
                    "Erro ao criar a planta",
                    f"{erro}\n\nDetalhe técnico (envie esta mensagem):\n{detalhes}",
                )

    def criar_layout_tematico(self):
        projeto = QgsProject.instance()
        temas = list(projeto.mapThemeCollection().mapThemes())
        if not temas:
            QMessageBox.information(
                self,
                "Nenhum tema salvo",
                "No QGIS, prepare a visibilidade e a simbologia das camadas, salve um Tema do Mapa "
                "incluindo o limite do imóvel e tente novamente.",
            )
            return

        dialogo = QDialog(self)
        dialogo.setWindowTitle("Configurar mapa temático")
        dialogo.resize(520, 250)
        conteudo = QVBoxLayout(dialogo)
        instrucao = QLabel(
            "O tema controla as camadas, a ordem e a simbologia da prancha. Inclua nele o limite "
            "do imóvel e as camadas do assunto (por exemplo, uso do solo, APP, hidrografia, "
            "declividade ou acesso). Se a camada de limite tiver várias propriedades, filtre-a para "
            "a feição deste imóvel antes de salvar o tema. Mantenha o limite acima das camadas "
            "temáticas e confira a legenda antes de exportar.",
            dialogo,
        )
        instrucao.setWordWrap(True)
        conteudo.addWidget(instrucao)
        form = QFormLayout()
        tema_combo = QComboBox(dialogo)
        for tema in temas:
            tema_combo.addItem(tema, tema)
        titulo = QLineEdit(temas[0], dialogo)
        fontes = QLineEdit(self.fontes_dados.text(), dialogo)
        fontes.setPlaceholderText("Informe origem, órgão/base, escala ou resolução")
        data = QLineEdit(self.data_referencia.text(), dialogo)
        data.setPlaceholderText("Ex.: 15/09/2026")
        form.addRow("Tema do QGIS:", tema_combo)
        form.addRow("Título do mapa:", titulo)
        form.addRow("Fontes / resolução:", fontes)
        form.addRow("Data de referência:", data)
        conteudo.addLayout(form)
        tema_combo.currentTextChanged.connect(lambda valor: titulo.setText(valor))
        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialogo)
        botoes.accepted.connect(dialogo.accept)
        botoes.rejected.connect(dialogo.reject)
        conteudo.addWidget(botoes)
        if dialogo.exec_() != QDialog.Accepted:
            return

        if not self.dados:
            self.calcular()
        if not self.dados:
            return
        try:
            from .layout_generator import gerar_layout_tematico
            layout_tematico = gerar_layout_tematico(
                self.dados,
                self._identificacao(),
                tema=tema_combo.currentData(),
                titulo=titulo.text().strip() or tema_combo.currentText(),
                fontes=fontes.text().strip(),
                data_referencia=data.text().strip(),
                formato_folha=self.formato_folha.currentData(),
            )
            self.layout_tematico = layout_tematico
            self.layout_para_pdf = layout_tematico
            self.formato_layout_pdf = self.formato_folha.currentData()
            self.iface.openLayoutDesigner(layout_tematico)
        except Exception as erro:
            detalhes = traceback.format_exc()
            QgsMessageLog.logMessage(detalhes, "Agrimensura", Qgis.Critical)
            QMessageBox.critical(
                self,
                "Erro ao criar o mapa temático",
                f"{erro}\n\nDetalhe técnico (envie esta mensagem):\n{detalhes}",
            )

    def exportar_pdf(self):
        if not self.layout_para_pdf:
            self.criar_layout()
        if not self.layout_para_pdf:
            return
        nome_padrao = "mapa_tematico.pdf" if self.layout_para_pdf is self.layout_tematico else "planta_agrimensura.pdf"
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar layout em PDF", nome_padrao, "PDF (*.pdf)"
        )
        if not caminho:
            return
        try:
            from .layout_generator import exportar_pdf_alta_resolucao
            exportar_pdf_alta_resolucao(self.layout_para_pdf, caminho)
            formato = self.formato_layout_pdf or self.formato_folha.currentData()
            self.iface.messageBar().pushSuccess(
                "Agrimensura", f"PDF do layout {formato} exportado em 300 dpi."
            )
        except Exception as erro:
            QMessageBox.critical(self, "Erro ao exportar PDF", str(erro))

