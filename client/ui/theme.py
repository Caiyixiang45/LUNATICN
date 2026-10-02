"""LUNATICN 视觉系统（PySide6 + QSS）— 浅色毛玻璃 + PCL 风格（单一主题）。

设计要点：
- 底色不透明，其上容器用低 alpha 白/黑色叠加，与父背景混合成毛玻璃层次；
- 亮 1px 半透明边框模拟玻璃折射高光；
- 文本色一律走 QLabel[tone] 属性选择器，随 QSS 统一生效。
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# ---------- 色板（浅色，RGBA 分量 0-255） ----------
PAL: dict[str, tuple] = {
    "bg": (237, 241, 247, 255),
    "bg_side": (255, 255, 255, 255),
    "popup": (252, 253, 255, 255),
    "card": (255, 255, 255, 170),
    "card_hover": (255, 255, 255, 220),
    "sunken": (0, 0, 0, 26),
    "border": (0, 0, 0, 30),
    "border_soft": (0, 0, 0, 18),
    "text": (36, 42, 54, 255),
    "muted": (98, 110, 130, 255),
    "faint": (146, 158, 176, 255),
    "brand": (30, 136, 255, 255),
    "brand_deep": (16, 108, 220, 255),
    "brand_soft": (30, 136, 255, 36),
    "brand_hover": (30, 136, 255, 60),
    "on_brand": (255, 255, 255, 255),
    "input": (255, 255, 255, 210),
    "input_border": (0, 0, 0, 36),
    "hover": (0, 0, 0, 30),
    "active": (0, 0, 0, 46),
    "subtle": (0, 0, 0, 12),
    "success": (28, 158, 92, 255),
    "danger": (226, 68, 58, 255),
    "danger_bg": (255, 236, 234, 245),
    "danger_hover": (255, 226, 223, 255),
    "danger_text": (200, 52, 44, 255),
    "warning": (216, 148, 0, 255),
    "scroll": (0, 0, 0, 60),
    "scroll_hover": (0, 0, 0, 95),
    "alt_row": (0, 0, 0, 14),
}


def current() -> dict:
    return PAL


def _rgba(c: tuple) -> str:
    return f"rgba({c[0]}, {c[1]}, {c[2]}, {c[3]})"


def build_qss() -> str:
    p = PAL
    r = _rgba
    on_brand = r(p["on_brand"])
    return f"""
QMainWindow, #Root {{
    background-color: {r(p['bg'])};
}}
QFrame#sidebar {{
    background-color: {r(p['bg_side'])};
    border-right: 1px solid {r(p['border_soft'])};
}}
QFrame#card {{
    background-color: {r(p['card'])};
    border: 1px solid {r(p['border'])};
    border-radius: 10px;
}}
QFrame#card:hover {{
    background-color: {r(p['card_hover'])};
}}
QFrame#sunken {{
    background-color: {r(p['sunken'])};
    border: 1px solid {r(p['border_soft'])};
    border-radius: 8px;
}}
QFrame#banner {{
    background-color: {r(p['brand_soft'])};
    border: 1px solid {r(p['brand_hover'])};
    border-radius: 10px;
}}
QFrame#ItemCard {{
    background-color: rgba(255, 255, 255, 0.72);
    border: 1px solid rgba(255, 255, 255, 0.92);
    border-radius: 14px;
}}
QFrame#ItemCard:hover {{
    background-color: rgba(255, 255, 255, 0.88);
}}
QScrollArea#ItemScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#ItemScroll > QWidget {{
    background: transparent;
}}
QWidget#ItemScrollInner {{
    background: transparent;
}}

QLabel {{ background: transparent; color: {r(p['text'])}; }}
QLabel[tone="muted"] {{ color: {r(p['muted'])}; }}
QLabel[tone="faint"] {{ color: {r(p['faint'])}; }}
QLabel[tone="brand"] {{ color: {r(p['brand'])}; }}
QLabel[tone="success"] {{ color: {r(p['success'])}; }}
QLabel[tone="warning"] {{ color: {r(p['warning'])}; }}
QLabel[tone="danger"] {{ color: {r(p['danger'])}; }}
QLabel[tone="title"] {{ font-size: 20px; font-weight: 700; }}
QLabel[tone="big"] {{ font-size: 15px; font-weight: 700; }}
QLabel[tone="small"] {{ font-size: 12px; }}

QPushButton {{
    background-color: {r(p['subtle'])};
    color: {r(p['muted'])};
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 14px;
    min-height: 18px;
}}
QPushButton:hover {{ background-color: {r(p['hover'])}; color: {r(p['text'])}; }}
QPushButton:pressed {{ background-color: {r(p['active'])}; }}
QPushButton:disabled {{ color: {r(p['faint'])}; background-color: transparent; }}

QPushButton[variant="primary"] {{
    background-color: {r(p['brand'])};
    color: {on_brand};
    font-weight: 700;
}}
QPushButton[variant="primary"]:hover {{ background-color: {r(p['brand_hover'])}; }}
QPushButton[variant="primary"]:pressed {{ background-color: {r(p['brand_deep'])}; }}
QPushButton[variant="primary"]:disabled {{
    background-color: {r(p['brand_soft'])}; color: {r(p['faint'])};
}}

QPushButton[variant="brand"] {{
    background-color: {r(p['brand_soft'])};
    color: {r(p['brand'])};
    border: 1px solid {r(p['brand_hover'])};
}}
QPushButton[variant="brand"]:hover {{ background-color: {r(p['brand_hover'])}; }}

QPushButton[variant="danger"] {{
    background-color: {r(p['danger_bg'])};
    color: {r(p['danger_text'])};
    border: 1px solid {r(p['danger_hover'])};
}}
QPushButton[variant="danger"]:hover {{ background-color: {r(p['danger_hover'])}; }}

QPushButton#nav {{
    background-color: transparent;
    color: {r(p['muted'])};
    border: none;
    border-radius: 9px;
    padding: 9px 14px;
    text-align: left;
    font-size: 14px;
}}
QPushButton#nav:hover {{ background-color: {r(p['hover'])}; color: {r(p['text'])}; }}
QPushButton#nav:checked {{
    background-color: {r(p['brand_soft'])};
    color: {r(p['brand'])};
    font-weight: 700;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    background-color: {r(p['input'])};
    color: {r(p['text'])};
    border: 1px solid {r(p['input_border'])};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {r(p['brand_soft'])};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {r(p['brand_hover'])};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {r(p['faint'])};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {r(p['popup'])};
    color: {r(p['text'])};
    border: 1px solid {r(p['border'])};
    border-radius: 8px;
    selection-background-color: {r(p['brand_soft'])};
    selection-color: {r(p['brand'])};
    outline: 0;
}}
QCheckBox {{ background: transparent; color: {r(p['text'])}; spacing: 7px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {r(p['input_border'])};
    background: {r(p['input'])};
}}
QCheckBox::indicator:checked {{
    background: {r(p['brand'])}; border: 1px solid {r(p['brand'])};
}}

QTableWidget {{
    background-color: transparent;
    alternate-background-color: {r(p['alt_row'])};
    color: {r(p['text'])};
    border: 1px solid {r(p['border_soft'])};
    border-radius: 9px;
    gridline-color: transparent;
    selection-background-color: {r(p['brand_soft'])};
    selection-color: {r(p['brand'])};
    outline: 0;
}}
QTableWidget::item {{ padding: 6px 8px; border: none; }}
QHeaderView::section {{
    background-color: transparent;
    color: {r(p['faint'])};
    border: none;
    border-bottom: 1px solid {r(p['border_soft'])};
    padding: 7px 8px;
    font-size: 12px;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {r(p['scroll'])}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {r(p['scroll_hover'])}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {r(p['scroll'])}; border-radius: 4px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{
    background-color: {r(p['subtle'])};
    border: none; border-radius: 6px;
    height: 12px; text-align: center;
    color: {r(p['text'])}; font-size: 11px;
}}
QProgressBar::chunk {{ background-color: {r(p['brand'])}; border-radius: 6px; }}

QToolTip {{
    background-color: {r(p['popup'])};
    color: {r(p['text'])};
    border: 1px solid {r(p['border'])};
    padding: 5px 8px;
}}
QStatusBar {{ background: transparent; color: {r(p['faint'])}; }}
QStatusBar::item {{ border: none; }}
QMessageBox {{ background-color: {r(p['popup'])}; }}
QDialog {{ background-color: {r(p['bg'])}; }}
"""


def apply(app: QApplication) -> None:
    font = QFont("Microsoft YaHei")
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(build_qss())


def set_tone(widget, tone: str) -> None:
    widget.setProperty("tone", tone)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
