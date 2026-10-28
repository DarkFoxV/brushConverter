"""GUI multilanguage support (English / Portuguese).

Lightweight approach: no Qt translation files, use key-value dictionaries + runtime redraw.
Current language stored at module level; switching language rebuilds UI text via MainWindow.
"""

from __future__ import annotations

import re

_LANG = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "window_title": "brushConverter — ABR → Krita Brush Converter",
        "open_abr": "Open ABR File…",
        "no_file": "No file selected",
        "brush_list": "Brush preview (check brushes to convert)",
        "select_all": "Select All",
        "select_none": "Select None",
        "count": "{total} brushes · {sel} selected",
        "output": "Output",
        "format": "Output format:",
        "kpp": ".kpp (one file per brush)",
        "bundle": ".bundle (Krita resource pack)",
        "out_dir": "Output directory:",
        "browse": "Browse…",
        "convert": "Start Conversion",
        "computed_brush": "Computed brush",
        "sampled_brush": "Sampled brush",
        "diameter": "Diameter {d}px",
        "warn_prefix": "⚠ Not mapped: ",
        "list_sep": ", ",
        "colon": ": ",
        "select_abr": "Select ABR file",
        "abr_filter": "Photoshop Brushes (*.abr);;All Files (*)",
        "parsing": "Parsing…",
        "parse_failed": "Parse Failed",
        "loaded": "Loaded {n} brushes",
        "select_out_dir": "Select output directory",
        "hint": "Notice",
        "need_select": "Please select at least one brush.",
        "unmapped_title": "Unmapped Parameters",
        "unmapped_body": "These brushes contain parameters that cannot be mapped and will be lost after conversion:\n\n{lines}\n\nContinue?",
        "texture_hint_title": "Texture Brightness/Contrast Notice",
        "texture_hint_body": "{n} brush(es) use a texture.\n\nThe texture \"Brightness/Contrast\" mapping is approximate and may not be accurate. After conversion, please fine-tune brightness and contrast in the Krita texture options.\n\nContinue?",
        "converting": "Converting…",
        "convert_failed": "Conversion Failed",
        "done_status": "Done: {n} brushes",
        "done_title": "Conversion Complete",
        "done_body": "Successfully converted {n} brushes.\n\nOutput location:\n{paths}",
    },
    "pt": {
        "window_title": "brushConverter — Conversor de pincéis ABR → Krita",
        "open_abr": "Abrir arquivo ABR…",
        "no_file": "Nenhum arquivo selecionado",
        "brush_list": "Pré-visualização de pincéis (marque os que deseja converter)",
        "select_all": "Selecionar tudo",
        "select_none": "Desmarcar tudo",
        "count": "{total} pincéis · {sel} selecionados",
        "output": "Saída",
        "format": "Formato de saída:",
        "kpp": ".kpp (um arquivo por pincel)",
        "bundle": ".bundle (pacote de recursos do Krita)",
        "out_dir": "Diretório de saída:",
        "browse": "Procurar…",
        "convert": "Iniciar conversão",
        "computed_brush": "Pincel calculado",
        "sampled_brush": "Pincel amostrado",
        "diameter": "Diâmetro {d}px",
        "warn_prefix": "⚠ Não mapeado: ",
        "list_sep": ", ",
        "colon": ": ",
        "select_abr": "Selecionar arquivo ABR",
        "abr_filter": "Pincéis Photoshop (*.abr);;Todos os arquivos (*)",
        "parsing": "Analisando…",
        "parse_failed": "Falha na análise",
        "loaded": "{n} pincéis carregados",
        "select_out_dir": "Selecionar diretório de saída",
        "hint": "Aviso",
        "need_select": "Selecione pelo menos um pincel.",
        "unmapped_title": "Parâmetros não mapeados",
        "unmapped_body": "Estes pincéis contêm parâmetros que não podem ser mapeados e serão perdidos após a conversão:\n\n{lines}\n\nContinuar?",
        "texture_hint_title": "Aviso de brilho/contraste de textura",
        "texture_hint_body": "{n} pincel(is) usam textura.\n\nO mapeamento de \"Brilho/Contraste\" da textura é aproximado e pode não ser preciso. Após a conversão, ajuste manualmente brilho e contraste nas opções de textura do Krita.\n\nContinuar?",
        "converting": "Convertendo…",
        "convert_failed": "Falha na conversão",
        "done_status": "Concluído: {n} pincéis",
        "done_title": "Conversão concluída",
        "done_body": "Convertidos com sucesso {n} pincéis.\n\nLocal de saída:\n{paths}",
    },
}

# mapping.py emits warnings in English; shown as-is in English, translated for Portuguese UI.
_WARNINGS_PT: dict[str, str] = {
    "Wet Edges": "Bordas úmidas",
    "Airbrush / Nozzle": "Aerógrafo / bico",
    "Brush Pose": "Postura do pincel",
    "Dual Brush": "Pincel duplo",
    "Texture (pattern missing)": "Textura (padrão ausente)",
    "Texture (protectTexture not mapped)": "Textura (protectTexture não mapeado)",
}


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in _STRINGS else "en"


def get_language() -> str:
    return _LANG


def tr(key: str, **kwargs) -> str:
    table = _STRINGS.get(_LANG, _STRINGS["en"])
    text = table.get(key, _STRINGS["en"].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def tr_warning(warning: str) -> str:
    """English warnings from mapping.py pass through; translated to Portuguese when the UI is pt."""
    if _LANG != "pt":
        return warning
    m = re.match(r"Texture blend mode \((.*)\)", warning)
    if m:
        inner = m.group(1).replace("falls back to Multiply", "recorre a Multiply")
        return f"Modo de mesclagem de textura ({inner})"
    m = re.match(r"Rotation control source \(bVTy=(\d+) not mapped\)", warning)
    if m:
        return f"Fonte de controle de rotação (bVTy={m.group(1)} não mapeado)"
    return _WARNINGS_PT.get(warning, warning)