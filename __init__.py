def classFactory(iface):
    """Ponto de entrada exigido pelo carregador de plugins do QGIS."""
    from .agrimensura_automatica import AgrimensuraAutomaticaPlugin
    return AgrimensuraAutomaticaPlugin(iface)

