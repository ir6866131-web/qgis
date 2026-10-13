# PyQGIS Agrimensura

Plugin para QGIS 3.16+ que calcula roteiro perimétrico, área, perímetro, azimutes e ângulos internos, gera memorial em Word (.docx) inspirado no modelo fornecido e cria uma planta no Gerenciador de Layouts.

## Instalação

1. Copie a pasta `pyqgis_agrimensura` para a pasta de plugins do perfil QGIS, normalmente `%APPDATA%\\QGIS\\QGIS3\\profiles\\default\\python\\plugins` no Windows.
2. No QGIS, abra **Complementos > Gerenciar e Instalar Complementos**, localize **PyQGIS Agrimensura** e habilite-o.
3. Abra **Agrimensura > Agrimensura: memorial e planta**.

## Uso seguro

- Desenhe ou carregue uma camada de polígonos; se houver feições selecionadas, a primeira selecionada será usada. Sem seleção, a primeira feição da camada será usada.
- Para criar a poligonal diretamente do levantamento, escolha a **Camada de pontos** e use **Gerar polígono e calcular**. O plugin prioriza os pontos selecionados; sem seleção, usa todos os pontos da camada. Antes de criar a camada, exibe uma prévia numerada: arraste os itens ou use as setas para corrigir a sequência e confirme quando o contorno estiver correto. Em seguida, adiciona a poligonal ao projeto e calcula distâncias, azimutes, área e perímetro.
- Informe um **campo de ordem dos pontos** (por exemplo, `ordem` ou `sequencia`) sempre que ele existir. Com a detecção automática, o plugin procura campos usuais como `ordem`, `sequencia`, `seq` e `numero`; um campo genérico `id` não é tratado como sequência. Se não houver campo de ordem, a sequência inicial é estimada pela posição dos pontos, o que só é confiável para contornos convexos ou aproximadamente convexos; confira e ajuste a prévia antes de emitir documentos.
- A poligonal gerada fica em memória por padrão. O plugin oferece salvá-la também em GeoPackage para manter uma cópia persistente após fechar o QGIS.
- Escolha um SRC **projetado, em metros e apropriado para o local**. O padrão `EPSG:31983` corresponde a SIRGAS 2000 / UTM zona 23S e não é adequado a todo o Brasil. SRCs em graus ou pés são recusados para evitar resultados incorretos.
- Por padrão, o plugin detecta a zona **SIRGAS 2000 / UTM** pelo centróide da poligonal (zonas brasileiras 17S a 25S). Desmarque a opção para informar o EPSG manualmente, especialmente perto da divisa entre zonas UTM.
- Preencha, quando disponíveis, matrícula/cadastro, município/UF e ART/RRT. Esses dados são adicionados ao memorial descritivo.
- Informe também as fontes cartográficas e a data de referência do levantamento; elas aparecem na prancha para deixar a procedência dos dados visível.
- O código de quatro caracteres do credenciado INCRA é opcional para calcular e gerar memorial/planta; informe-o, junto ao tipo de vértice e à sequência inicial, ao preparar peças de pré-submissão. Sem código, os vértices recebem identificadores locais (`V-01`, `V-02` etc.). Use **Editar limites e confrontantes** para preencher os dados de cada alinhamento antes de exportar.
- Use **Exportar CSV** para obter o roteiro perimétrico com vértices, coordenadas, azimutes e distâncias em formato compatível com Excel.
- Use **Gerar curvas de nível** para escolher um raster de elevação carregado no projeto, definir a equidistância vertical e criar uma camada vetorial de curvas. A equidistância usa as unidades dos valores do raster (normalmente metros); confira a banda e as unidades do MDE antes de gerar.
- A planta cadastral desenha uma cópia isolada da feição usada no cálculo, evitando exibir outras propriedades que estejam na mesma camada. Ao atualizar a planta, a cópia acompanha a feição original. O roteiro perimétrico inclui tipo de limite, confrontante, vértices, azimutes, distâncias e coordenadas; poligonais com mais de oito lados continuam o roteiro em uma segunda página.
- O plugin trata o anel externo de uma poligonal simples. Separe geometrias multiparte e valide topologia antes de emitir documentos técnicos.
- A planta usa uma barra de escala gráfica vinculada ao mapa e uma grade discreta do SRC projetado (UTM quando aplicável). A barra acompanha mudanças na escala do mapa; o valor numérico de escala no carimbo registra a escala inicial da composição.
- Escolha o formato A4, A3, A2, A1 ou A0 em paisagem antes de criar o layout. A composição e as tabelas acompanham o tamanho da folha; A3 ou maior é recomendado para manter legível o roteiro completo. Em A4, confira a impressão antes de protocolar.
- Para gerar uma prancha temática, prepare e salve um **Tema do Mapa** no QGIS com a camada do limite do imóvel e as camadas do assunto desejado. Se a camada do limite tiver mais de uma propriedade, filtre-a para a feição do imóvel. Ajuste simbologia, ordem e classes, mantendo o limite acima das camadas temáticas. Use **Criar mapa temático**, escolha o tema, informe título, fontes e data de referência; a prancha centra o imóvel, mostra legenda ligada ao tema, escala gráfica e grade de coordenadas anotada.
- **Exportar último layout PDF** exporta a última planta cadastral ou temática criada, em 300 dpi.
- Os mapas temáticos são configuráveis para estudos como uso e cobertura do solo, APP/reserva legal, hidrografia, declividade, solos e acessos. O conteúdo, as escalas e os estudos exigidos dependem do Termo de Referência e do órgão licenciador; o modelo não afirma conformidade automática com um protocolo específico.
- O quadro de referência cartográfica lê o SRC selecionado e gera automaticamente projeção/zona, datum, meridiano central, escala da planta e, no QGIS 3.20 ou superior, convergência meridiana e fator de escala local no centro do imóvel. O datum não é presumido como SIRGAS 2000 quando outro SRC é escolhido.
- O mapa de situação da planta cadastral guarda no layout a lista de camadas visíveis no momento da criação. Fontes remotas podem exigir conexão durante a exportação; o tema usado na prancha temática fica salvo no projeto QGIS.
- O plugin organiza dados para conferência, mas não substitui a planilha ODS, a validação de precisão, a ART/RRT ou a certificação pelo SIGEF. A planta certificada é emitida pelo próprio SIGEF após a submissão válida.
- Confirme os resultados e complete ART/RRT, dados cadastrais, datum e demais requisitos do órgão competente antes de assinar ou protocolar a peça.

## Verificações de geometria

Os testes em `tests/` cobrem azimutes cardinais, detecção do campo de sequência, ordenação numérica e uma poligonal quadrada com área, perímetro e azimutes conhecidos. Execute `python -m unittest discover -s tests` em um ambiente Python com PyQGIS configurado.

## Convenções

O azimute é calculado de acordo com `atan2(ΔE, ΔN)`: 0° aponta para o norte e aumenta no sentido horário. A área e o perímetro são calculados somente depois da transformação para o SRC projetado escolhido.

## Licença

O plugin é distribuído sob GNU GPL versão 2 ou, a critério de quem recebe, qualquer versão posterior. O texto completo está em `LICENSE`. O módulo `magnetic_model.py` contém código baseado em pyGeoMag, distribuído sob MIT; os termos correspondentes estão em `LICENSE-pygeomag.txt`.

