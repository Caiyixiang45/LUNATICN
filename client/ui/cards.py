"""大标签卡片网格 / 详情对话框 / 程序化预览图 —— 四页共用的呈现层。

只负责“长什么样”：数据获取与业务动作仍由各页面自己提供（回调闭包）。
四页统一结构：预览图 → 大标题 → 副信息 → 简介（最多 2 行）→ 底部按钮行。
"""
from __future__ import annotations

import zlib
from typing import NamedTuple, Optional, Sequence

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter,
    QPainterPath, QPixmap,
)
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui import theme, widgets

CARD_MIN_WIDTH = 300      # 卡片最小宽度
CARD_MARGIN = 14          # 卡片内边距
GRID_SPACING = 14         # 卡片间距
COLS = 3                  # 每行卡片数
THUMB_H = 116             # 卡片预览区高度
THUMB_RADIUS = 10
DETAIL_W, DETAIL_H = 700, 540
DESC_LINES = 2            # 简介最多行数
DESC_MAX_CHARS = 90       # 简介最多字数

_TEXT_W = CARD_MIN_WIDTH - 2 * CARD_MARGIN   # 文本可用宽度（按最小卡宽算）

# 按名称 hash 选出的浅色系（两色）占位渐变
GRADIENTS: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((168, 199, 255), (236, 243, 255)),
    ((255, 206, 166), (255, 244, 232)),
    ((161, 224, 201), (233, 250, 243)),
    ((214, 187, 255), (245, 238, 255)),
    ((255, 188, 206), (255, 238, 244)),
    ((160, 219, 232), (233, 248, 251)),
)


# ---------- 预览图 ----------

def placeholder_image(seed_text: str = "", width: int = 300,
                      height: int = THUMB_H, overlay: str = "") -> QImage:
    """程序化渐变占位：按名称 hash 取两色，可叠加一行文字（如 gameid）。"""
    idx = zlib.crc32((seed_text or "lunaticn").encode("utf-8")) % len(GRADIENTS)
    top, bottom = GRADIENTS[idx]
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, width, height)
    grad.setColorAt(0.0, QColor(*top))
    grad.setColorAt(1.0, QColor(*bottom))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRect(0, 0, width, height)
    # 两团半透明白，增加层次
    p.setBrush(QColor(255, 255, 255, 78))
    p.drawEllipse(QRect(width - 96, -34, 130, 130))
    p.setBrush(QColor(255, 255, 255, 46))
    p.drawEllipse(QRect(18, height - 58, 92, 92))
    if overlay:
        font = QFont("Microsoft YaHei")
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        fm = QFontMetrics(font)
        text = fm.elidedText(overlay, Qt.TextElideMode.ElideRight, width - 40)
        tw = fm.horizontalAdvance(text)
        pill = QRect((width - tw - 18) // 2, (height - fm.height()) // 2 - 2,
                     tw + 18, fm.height() + 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 150))
        p.drawRoundedRect(pill, 9, 9)
        pal = theme.current()
        c = pal["text"]
        p.setPen(QColor(c[0], c[1], c[2], 230))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return img


class ThumbLabel(QLabel):
    """卡片/对话框预览区：持有 QImage 源，尺寸变化时自动重绘圆角图。"""

    def __init__(self, height: int = THUMB_H, radius: int = THUMB_RADIUS,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._src: Optional[QImage] = None
        self._radius = radius
        self._h = height
        self.setFixedHeight(height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    # 宽度由卡片决定，不要让 pixmap 反过来撑大网格列
    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, self._h)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(40, self._h)

    def set_image(self, image: Optional[QImage]) -> None:
        self._src = image if (image is not None and not image.isNull()) else None
        self._repaint()

    def set_placeholder(self, seed_text: str = "", overlay: str = "") -> None:
        self.set_image(placeholder_image(seed_text, overlay=overlay))

    def load_bytes(self, data: bytes) -> bool:
        """内存读图（不落盘）；解码失败保持原图。"""
        img = QImage()
        if not data or not img.loadFromData(data):
            return False
        self.set_image(img)
        return True

    def image(self) -> Optional[QImage]:
        return self._src

    def _repaint(self) -> None:
        w, h = self.width(), self.height()
        if w < 4 or h < 4:
            return
        if self._src is None:
            self.clear()
            return
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, self._radius, self._radius)
        p.setClipPath(path)
        src = self._src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        x = (src.width() - w) // 2
        y = (src.height() - h) // 2
        p.drawImage(QRect(-x, -y, src.width(), src.height()), src)
        p.end()
        self.setPixmap(pm)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._repaint()


def safe_image(thumb: Optional[ThumbLabel]) -> Optional[QImage]:
    """取预览图（控件可能已被刷新销毁，异常时返回 None）。"""
    if thumb is None:
        return None
    try:
        return thumb.image()
    except RuntimeError:  # noqa: PLE0605 — C++ 对象已删除
        return None


# ---------- 文本截断 ----------

def _fit_chars(text: str, fm: QFontMetrics, budget: int) -> int:
    total = 0
    for i, ch in enumerate(text):
        total += fm.horizontalAdvance(ch)
        if total > budget:
            return i
    return len(text)


def clamp_line(lb: QLabel, width: int = _TEXT_W) -> None:
    """单行标题：超宽用 elidedText 收省略号。"""
    text = lb.text()
    if not text:
        return
    fm = QFontMetrics(lb.font())
    if fm.horizontalAdvance(text) > width:
        lb.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, width))


def clamp_desc(lb: QLabel, lines: int = DESC_LINES,
               width: int = _TEXT_W) -> None:
    """简介：最多 lines 行 / DESC_MAX_CHARS 字，超出补省略号并固定高度。"""
    text = lb.text()
    if not text:
        return
    fm = QFontMetrics(lb.font())
    budget = int(width * lines * 0.88)
    cut = _fit_chars(text, fm, budget)
    if len(text) > DESC_MAX_CHARS:
        cut = min(cut, DESC_MAX_CHARS)
    if cut < len(text):
        lb.setText(text[:cut] + "…")
    lb.setWordWrap(True)
    lb.setFixedHeight(fm.lineSpacing() * lines + 4)


# ---------- 卡片 ----------

class Card(NamedTuple):
    frame: QFrame
    thumb: ThumbLabel
    title: QLabel
    subtitle: Optional[QLabel]
    desc: Optional[QLabel]


def card_frame() -> tuple[QFrame, QVBoxLayout]:
    """白卡容器：QFrame#ItemCard（QSS 定义于 theme.py，四页共用）。"""
    fr = QFrame()
    fr.setObjectName("ItemCard")
    fr.setMinimumWidth(CARD_MIN_WIDTH)
    v = QVBoxLayout(fr)
    v.setContentsMargins(CARD_MARGIN, CARD_MARGIN, CARD_MARGIN, CARD_MARGIN)
    v.setSpacing(0)
    return fr, v


def build_card(*, title: str, subtitle: str = "", desc: str = "",
               seed: str = "", overlay: str = "",
               buttons: Sequence[dict]) -> Card:
    """按统一结构组装一张卡片。

    buttons: [{"text":…, "variant":…, "on_click":…}, …] 右对齐、高 26。
    """
    fr, v = card_frame()
    thumb = ThumbLabel()
    thumb.set_placeholder(seed or title, overlay=overlay)
    v.addWidget(thumb)
    v.addSpacing(8)
    lb_title = widgets.label(title, big=True)
    clamp_line(lb_title)
    v.addWidget(lb_title)
    lb_sub: Optional[QLabel] = None
    if subtitle:
        v.addSpacing(2)
        lb_sub = widgets.label(subtitle, tone="muted", small=True)
        clamp_line(lb_sub)
        v.addWidget(lb_sub)
    lb_desc: Optional[QLabel] = None
    if desc:
        v.addSpacing(3)
        lb_desc = widgets.label(desc, tone="faint", small=True)
        clamp_desc(lb_desc)
        v.addWidget(lb_desc)
    v.addStretch(1)
    v.addSpacing(8)
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addStretch(1)
    for spec in buttons:
        row.addWidget(widgets.button(
            spec["text"], spec.get("on_click"),
            variant=spec.get("variant", ""), fixed_h=26))
    v.addLayout(row)
    return Card(fr, thumb, lb_title, lb_sub, lb_desc)


# ---------- 卡片网格 ----------

class CardGrid(QWidget):
    """QScrollArea + 内层 QWidget + QGridLayout，每行 COLS 张卡。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ItemScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inner = QWidget()
        self.inner.setObjectName("ItemScrollInner")
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(2, 6, 2, 8)
        self.grid.setHorizontalSpacing(GRID_SPACING)
        self.grid.setVerticalSpacing(GRID_SPACING)
        for c in range(COLS):
            self.grid.setColumnStretch(c, 1)
        self.scroll.setWidget(self.inner)
        outer.addWidget(self.scroll)

        self._cards: list[QFrame] = []
        self._rows = 0
        self._empty = widgets.label("", big=True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.hide()

    @property
    def cards(self) -> list[QFrame]:
        return list(self._cards)

    def _clear(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is None:
                continue
            if w is self._empty:
                w.hide()
                continue
            w.deleteLater()
        for r in range(self._rows + 1):
            self.grid.setRowStretch(r, 0)
        self._cards.clear()
        self._rows = 0

    def set_empty(self, text: str) -> None:
        """空态：scroll 区中央的大字提示。"""
        self._clear()
        self._empty.setText(text)
        self.grid.addWidget(self._empty, 0, 0, 1, COLS,
                            Qt.AlignmentFlag.AlignCenter)
        self.grid.setRowStretch(1, 1)
        self._rows = 1
        self._empty.show()

    def set_cards(self, cards: Sequence[QFrame]) -> None:
        self._clear()
        if not cards:
            self.set_empty("")
            return
        for i, fr in enumerate(cards):
            self.grid.addWidget(fr, i // COLS, i % COLS)
            self._cards.append(fr)
        rows = (len(cards) + COLS - 1) // COLS
        self.grid.setRowStretch(rows, 1)
        self._rows = rows


# ---------- 详情对话框 ----------

class ItemDetailDialog(QDialog):
    """四页共用的详情对话框：大预览 + 标题 + 表单字段 + 操作按钮。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("详情")
        self.resize(DETAIL_W, DETAIL_H)
        self.setMinimumSize(560, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        self.thumb = ThumbLabel(height=240, radius=12)
        lay.addWidget(self.thumb)
        self.title = widgets.label("", title=True)
        lay.addWidget(self.title)

        form_host = QWidget()
        self.form = QFormLayout(form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(7)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft |
                                    Qt.AlignmentFlag.AlignTop)
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        lay.addWidget(form_host, stretch=1)

        widgets.hline(lay)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.addStretch(1)
        lay.addLayout(self.actions)

    # ---------- 填充 ----------

    def open_item(self, title: str, image: Optional[QImage],
                  fields: Sequence[tuple[str, str]],
                  actions: Sequence[dict]) -> None:
        self.setWindowTitle(title or "详情")
        self.title.setText(title or "")
        if image is not None and not image.isNull():
            self.thumb.set_image(image)
        else:
            self.thumb.set_placeholder(title or "")

        while self.form.rowCount():
            self.form.removeRow(0)
        for name, value in fields:
            lb_name = widgets.label(name, tone="muted", small=True)
            lb_val = widgets.label(value if value else "—")
            lb_val.setWordWrap(True)
            self.form.addRow(lb_name, lb_val)

        while self.actions.count():
            item = self.actions.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.actions.addStretch(1)
        for spec in actions:
            fn = spec.get("on_click")
            btn = widgets.button(
                spec["text"],
                (lambda _checked=False, f=fn: (f(), self.close()))
                if fn else None,
                variant=spec.get("variant", ""), fixed_h=26)
            self.actions.addWidget(btn)
        self.actions.addWidget(widgets.button("关闭", self.close,
                                              width=84, fixed_h=26))
        self.show()
        self.raise_()
        self.activateWindow()
