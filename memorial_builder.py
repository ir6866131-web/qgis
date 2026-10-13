"""Montagem e exportação do memorial descritivo em texto UTF-8."""
import csv
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET


def numero_br(valor, casas=2):
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def construir_memorial(dados, identificacao):
    """Devolve um memorial perimétrico com base em dados de processar_poligonal()."""
    vertices = dados["vertices"]
    segmentos = dados["segmentos"]
    if not vertices:
        raise ValueError("Não há vértices para descrever.")

    imovel = identificacao.get("imovel") or "Não informado"
    proprietario = identificacao.get("proprietario") or "Não informado"
    responsavel = identificacao.get("responsavel") or "Não informado"
    matricula = identificacao.get("matricula") or "Não informado"
    municipio = identificacao.get("municipio") or "Não informado"
    art_rrt = identificacao.get("art_rrt") or "Não informado"
    src = dados["crs_authid"]
    nao_informado = "Não informado"
    meses = (
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    )
    hoje = date.today()
    data_emissao = f"{hoje.day} de {meses[hoje.month - 1]} de {hoje.year}"
    linhas = [
        "MEMORIAL DESCRITIVO",
        "",
        f"Proprietário: {proprietario}    CPF: {identificacao.get('cpf') or nao_informado}",
        f"Matrícula do imóvel: {matricula}    Cartório (CNS): {identificacao.get('cartorio') or nao_informado}",
        f"Município / UF: {municipio}    Código INCRA/SNCR: {identificacao.get('codigo_sncr') or nao_informado}",
        f"Responsável técnico: {responsavel}    CREA: {identificacao.get('crea') or nao_informado}",
        f"Formação: {identificacao.get('formacao') or nao_informado}    ART / RRT: {art_rrt}",
        f"Código de credenciamento: {identificacao.get('codigo_credenciado') or nao_informado}",
        f"Sistema geodésico de referência: SIRGAS 2000 ({src} — {dados['crs_descricao']})",
        "",
        f"Área (plana no SRC): {numero_br(dados['area_m2'], 2)} m² ({numero_br(dados['area_ha'], 4)} ha)",
        f"Perímetro: {numero_br(dados['perimetro_m'], 2)} m",
        "",
    ]

    primeiro = vertices[0]
    texto = (
        f"Inicia-se a descrição deste perímetro no vértice {primeiro['id']}, "
        f"de coordenadas N {numero_br(primeiro['norte'], 2)} m e "
        f"E {numero_br(primeiro['leste'], 2)} m, latitude {numero_br(primeiro['latitude'], 8)}° "
        f"e longitude {numero_br(primeiro['longitude'], 8)}°;"
    )
    for segmento in segmentos:
        destino = segmento["fim"]
        descricao_limite = segmento.get("tipo_limite") or "tipo de limite não informado"
        confrontante = segmento.get("confrontante") or "confrontante não informado"
        texto += (
            f" deste, segue pelo limite {descricao_limite}, confrontando com {confrontante}, "
            f"com azimute de {segmento['azimute_dms']} e distância de "
            f"{numero_br(segmento['distancia_m'], 2)} m, ângulo interno no vértice "
            f"{segmento['inicio']['id']} de {segmento['angulo_interno_dms']}, até o vértice {destino['id']}, "
            f"de coordenadas N {numero_br(destino['norte'], 2)} m e "
            f"E {numero_br(destino['leste'], 2)} m, latitude {numero_br(destino['latitude'], 8)}° "
            f"e longitude {numero_br(destino['longitude'], 8)}°;"
        )
    texto += " fechando assim o perímetro descrito."
    linhas.extend([
        texto, "",
        f"Sistema de coordenadas: {src} — {dados['crs_descricao']}",
        "",
        f"Local e data: {municipio}, {data_emissao}",
        "", "", "____________________________________________",
        f"Resp. Técnico: {responsavel}",
        f"{identificacao.get('formacao') or ''}  CREA: {identificacao.get('crea') or nao_informado}",
        f"ART / RRT nº {art_rrt}",
    ])
    return "\n".join(linhas)


def exportar_txt(conteudo, caminho):
    """Salva o memorial usando UTF-8, adequado para acentos em qualquer editor."""
    destino = Path(caminho)
    destino.write_text(conteudo, encoding="utf-8")
    return str(destino)


def exportar_docx(conteudo, caminho):
    """Salva o memorial em Word com quadros e hierarquia visual discreta."""
    destino = Path(caminho)
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", ns)

    def tag(nome):
        return f"{{{ns}}}{nome}"

    def elemento(pai, nome, atributos=None):
        return ET.SubElement(pai, tag(nome), atributos or {})

    def paragrafo(pai, texto="", alinhar="both", negrito=False, depois=100):
        p = elemento(pai, "p")
        props = elemento(p, "pPr")
        elemento(props, "jc", {"val": alinhar})
        elemento(props, "spacing", {"after": str(depois), "line": "276", "lineRule": "auto"})
        run = elemento(p, "r")
        rp = elemento(run, "rPr")
        elemento(rp, "rFonts", {"ascii": "Times New Roman", "hAnsi": "Times New Roman", "eastAsia": "Times New Roman"})
        if negrito:
            elemento(rp, "b")
        elemento(rp, "sz", {"val": "24"})
        elemento(rp, "szCs", {"val": "24"})
        elemento(run, "t").text = texto
        return p

    def celula_texto(celula, texto, destaque=False):
        tcpr = elemento(celula, "tcPr")
        elemento(tcpr, "tcW", {"w": "4500", "type": "dxa"})
        if destaque:
            elemento(tcpr, "shd", {"fill": "EAF0F5", "val": "clear"})
        paragrafo(celula, texto, "left", destaque, 40)

    def tabela(pai, linhas, duas_colunas=False):
        tbl = elemento(pai, "tbl")
        props = elemento(tbl, "tblPr")
        elemento(props, "tblW", {"w": "9000", "type": "dxa"})
        bordas = elemento(props, "tblBorders")
        for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
            elemento(bordas, lado, {"val": "single", "sz": "4", "space": "0", "color": "C8D1DA"})
        elemento(props, "tblCellMar")
        grade = elemento(tbl, "tblGrid")
        elemento(grade, "gridCol", {"w": "4500"})
        if duas_colunas:
            elemento(grade, "gridCol", {"w": "4500"})
        for esquerda, direita in linhas:
            tr = elemento(tbl, "tr")
            c1 = elemento(tr, "tc")
            celula_texto(c1, esquerda, True)
            c2 = elemento(tr, "tc")
            celula_texto(c2, direita, False)
        return tbl

    linhas = conteudo.splitlines()
    corpo = ET.Element(tag("document"))
    body = elemento(corpo, "body")
    paragrafo(body, "MEMORIAL DESCRITIVO", "center", True, 180)
    metadados = []
    resumo = []
    narrativa = ""
    rodape = []
    secao = "metadados"
    for linha in linhas[1:]:
        if linha.startswith("Área ("):
            secao = "resumo"
        if linha.startswith("Inicia-se a descrição"):
            secao = "corpo"
        if secao == "metadados" and linha.strip():
            if "    " in linha:
                esquerda, direita = linha.split("    ", 1)
                metadados.append((esquerda, direita))
            else:
                metadados.append((linha, ""))
        elif secao == "resumo" and (linha.startswith("Área (") or linha.startswith("Perímetro:")):
            rotulo, valor = linha.split(":", 1)
            resumo.append((rotulo, valor.strip()))
        elif secao == "corpo" and linha.startswith("Inicia-se a descrição"):
            narrativa = linha
            secao = "rodape"
        elif secao == "rodape" and linha.strip():
            rodape.append(linha)

    if metadados:
        tabela(body, metadados, True)
    if resumo:
        paragrafo(body, "RESUMO DA POLIGONAL", "left", True, 60)
        tabela(body, resumo, True)
    paragrafo(body, "", "left", False, 60)
    if narrativa:
        paragrafo(body, narrativa, "both", False, 180)
    for linha in rodape:
        if linha.startswith("Local e data:"):
            paragrafo(body, linha, "center", False, 300)
        elif linha.startswith("___"):
            paragrafo(body, linha, "center", False, 40)
        elif linha.startswith("Sistema de coordenadas:"):
            paragrafo(body, linha, "left", False, 100)
        else:
            paragrafo(body, linha, "center", False, 40)

    sect = elemento(body, "sectPr")
    elemento(sect, "pgSz", {"w": "11906", "h": "16838"})
    elemento(sect, "pgMar", {"top": "1134", "right": "1134", "bottom": "1134", "left": "1134", "header": "600", "footer": "600", "gutter": "0"})
    document = ET.tostring(corpo, encoding="utf-8", xml_declaration=True)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    with ZipFile(destino, "w", ZIP_DEFLATED) as arquivo:
        arquivo.writestr("[Content_Types].xml", content_types)
        arquivo.writestr("_rels/.rels", rels)
        arquivo.writestr("word/document.xml", document)
    return str(destino)


def exportar_roteiro_csv(dados, caminho):
    """Exporta vértices e alinhamentos em CSV UTF-8 compatível com Excel."""
    destino = Path(caminho)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow([
            "Vértice inicial", "Vértice final", "Norte final (m)", "Leste final (m)",
            "Azimute", "Distância (m)", "Tipo de limite", "Confrontante",
        ])
        for segmento in dados["segmentos"]:
            fim = segmento["fim"]
            escritor.writerow([
                segmento["inicio"]["id"], fim["id"],
                numero_br(fim["norte"], 3), numero_br(fim["leste"], 3),
                segmento["azimute_dms"], numero_br(segmento["distancia_m"], 3),
                segmento.get("tipo_limite", ""), segmento.get("confrontante", ""),
            ])
    return str(destino)

