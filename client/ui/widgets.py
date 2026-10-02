"""通用 UI 组件：页头、卡片、按钮、表格、徽章（PCL 风格，Qt 版）。"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLayout, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from . import theme


def label(text: str = "", tone: str = "", *, big: bool = False,
          small: bool = False, title: bool = False,
          layout: Optional[QLayout] = None) -> QLabel:
    lb = QLabel(text)
    tone = "title" if title else ("big" if big else ("small" if small else tone))
    if tone:
        theme.set_tone(lb, tone)
    if layout is not None:
        layout.addWidget(lb)
    return lb


def button(text: str, on_click: Optional[Callable] = None, *,
           variant: str = "", width: int = 0, fixed_h: Optional[int] = None,
           checkable: bool = False, name: str = "") -> QPushButton:
    """variant: primary/brand/danger/空(默认幽灵)。"""
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if name:
        btn.setObjectName(name)
    if width:
        btn.setFixedWidth(width)
    if fixed_h:
        btn.setFixedHeight(fixed_h)
    btn.setCheckable(checkable)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def card(layout: Optional[QLayout] = None, *, sunken: bool = False,
         banner: bool = False) -> QFrame:
    fr = QFrame()
    fr.setObjectName("banner" if banner else ("sunken" if sunken else "card"))
    inner = QVBoxLayout(fr)
    inner.setContentsMargins(16, 14, 16, 14)
    inner.setSpacing(8)
    if layout is not None:
        layout.addWidget(fr)
    return fr


def section_title(text: str, layout: Optional[QLayout] = None) -> QLabel:
    return label(text.upper() if text.isascii() else text, tone="faint",
                 small=True, layout=layout)


def page_header(layout: QLayout, title: str, subtitle: str = "") -> None:
    label(title, title=True, layout=layout)
    if subtitle:
        label(subtitle, tone="muted", small=True, layout=layout)


def hline(layout: QLayout) -> None:
    fr = QFrame()
    fr.setFixedHeight(1)
    fr.setStyleSheet("background: rgba(128,128,128,40);")
    layout.addWidget(fr)


def hbox(layout: QLayout, spacing: int = 8) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(spacing)
    layout.addLayout(row)
    return row


def table(headers: Sequence[tuple[str, int]], *, flex: Sequence[int] = (0,),
          min_height: int = 160) -> QTableWidget:
    """标准数据表：headers=(列名, 初始像素宽)。

    响应式策略：
    - flex 列（默认首列）：Stretch，随窗口宽度伸缩；
    - 其余列（含末尾按钮列）：Interactive，按声明宽度渲染。
      按钮是单元格组件（setCellWidget），ResizeToContents 测不到它、
      会把列压到最小宽度导致按钮文字被裁掉，故一律不用。
    """
    n = len(headers)
    tb = QTableWidget(0, n)
    for i, (name, w) in enumerate(headers):
        tb.setHorizontalHeaderItem(i, QTableWidgetItem(name))
        tb.setColumnWidth(i, w)
        mode = QHeaderView.Stretch if i in flex else QHeaderView.Interactive
        tb.horizontalHeader().setSectionResizeMode(i, mode)
    tb.horizontalHeader().setMinimumSectionSize(60)
    tb.verticalHeader().setVisible(False)
    tb.verticalHeader().setDefaultSectionSize(34)
    tb.setSelectionBehavior(QAbstractItemView.SelectRows)
    tb.setSelectionMode(QAbstractItemView.SingleSelection)
    tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tb.setShowGrid(False)
    tb.setAlternatingRowColors(True)
    tb.setFocusPolicy(Qt.NoFocus)
    tb.setMinimumHeight(min_height)
    tb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return tb


def fill_table(tb: QTableWidget, rows: Sequence[tuple[str, dict]],
               empty_text: str = "") -> None:
    """rows: [(单元格文本, {"tone":…} 或 {列序: {"widget":…,"tone":…}})]。

    每行第一元素是该行首列文本；row_meta 用列序号覆盖样式/widget。
    简化：每行 = (cols: list[str], meta: dict[int, dict])。
    """
    tb.setRowCount(0)
    if not rows and empty_text:
        tb.setRowCount(1)
        item = QTableWidgetItem(empty_text)
        item.setForeground(Qt.gray)
        tb.setItem(0, 0, item)
        tb.setSpan(0, 0, 1, tb.columnCount())
        return
    for r, (cols, meta) in enumerate(rows):
        tb.insertRow(r)
        for c, text in enumerate(cols):
            if c in meta and "widget" in meta[c]:
                w = meta[c]["widget"]
                tb.setCellWidget(r, c, w)
                # 单元格组件可能比默认行高（34）高（QSS padding 决定按钮
                # 实际高度，setFixedHeight 压不过样式表），按需撑开避免下裁。
                need = w.sizeHint().height()
                if need > tb.rowHeight(r):
                    tb.setRowHeight(r, need)
                continue
            item = QTableWidgetItem(str(text))
            tone = meta.get(c, {}).get("tone")
            if tone:
                from PySide6.QtGui import QBrush, QColor
                pal = theme.current()
                item.setForeground(QBrush(QColor(*pal.get(tone, pal["text"]))))
            tb.setItem(r, c, item)


def row_buttons(*btns: QPushButton, spacing: int = 6) -> QWidget:
    """表格单元格内的按钮行。"""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(4, 2, 4, 2)
    row.setSpacing(spacing)
    for b in btns:
        row.addWidget(b)
    return w
