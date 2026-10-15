"""GUI 맑은고딕 고정 회귀 테스트 (Tk 창 없이 AST/소스 수준 검증)."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "websync" / "gui"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dropdown_calls(tree: ast.Module) -> list[ast.Call]:
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name in ("CTkOptionMenu", "CTkComboBox"):
            out.append(node)
    return out


def test_font_family_is_malgun_gothic():
    from websync.gui.widgets import FONT_FAMILY

    assert FONT_FAMILY == "Malgun Gothic"


def test_ctk_theme_default_is_malgun_gothic():
    import websync.gui.widgets as widgets
    from customtkinter.windows.widgets.theme.theme_manager import ThemeManager

    assert ThemeManager.theme["CTkFont"]["family"] == "Malgun Gothic"
    assert widgets.FONT_FAMILY == "Malgun Gothic"


def test_dropdown_helpers_exist():
    import websync.gui.widgets as widgets

    for name in ("get_dropdown_font", "make_option_menu", "make_combobox", "apply_global_fonts"):
        assert callable(getattr(widgets, name, None)), name


def test_all_dropdowns_specify_dropdown_font():
    missing: list[str] = []
    for path in sorted(GUI.rglob("*.py")):
        if path.name == "widgets.py":
            continue
        tree = _parse(path)
        for call in _dropdown_calls(tree):
            keywords = {kw.arg for kw in call.keywords if kw.arg}
            if "dropdown_font" not in keywords:
                missing.append(f"{path.relative_to(ROOT)}:{call.lineno}")
    assert missing == [], f"dropdown_font 누락: {missing}"


def test_no_consolas_font_in_gui():
    offenders: list[str] = []
    for path in sorted(GUI.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "Consolas" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Consolas 잔존: {offenders}"


def test_site_context_menu_uses_malgun_font():
    tree = _parse(GUI / "sync_tab" / "sites.py")
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "Menu":
                keywords = {kw.arg for kw in node.keywords if kw.arg}
                assert "font" in keywords, "tk.Menu에 font 고정 필요"
                found = True
    assert found, "tk.Menu 호출을 찾지 못함"


def test_selector_dom_tree_uses_ctk_style():
    text = (GUI / "sync_tab" / "selector_wizard.py").read_text(encoding="utf-8")
    assert 'style="CTk.Treeview"' in text
    assert "apply_treeview_style" in text


def test_treeview_styles_cover_default_and_ctk():
    text = (GUI / "widgets.py").read_text(encoding="utf-8")
    assert '"Treeview"' in text
    assert '"CTk.Treeview"' in text
    assert '"Treeview.Heading"' in text


def test_app_applies_global_fonts():
    text = (GUI / "app_core" / "app.py").read_text(encoding="utf-8")
    assert "apply_global_fonts(self.root)" in text
