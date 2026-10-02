"""存档库 — 存档卡片网格 / 新建·复制·导入·分享·删除·进入。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QRadioButton, QVBoxLayout, QWidget,
)

from lunaticn import engine, packages, worlds
from lunaticn.api import api
from lunaticn.packages import build_from_world
from lunaticn.worlds import WORLDS_ROOT
from ui import cards, theme, widgets
from ui.bridge import async_task, ui_call


def _mode_text(w: dict) -> str:
    return "创造" if w.get("creative") else "生存"


def _last_text(w: dict) -> str:
    lm = w["last_played"]
    return (lm.strftime("%Y-%m-%d %H:%M") if lm.year > 1970 else "从未进入")


def _err_label(lay: QVBoxLayout) -> QLabel:
    lb = QLabel("")
    theme.set_tone(lb, "danger")
    lay.addWidget(lb)
    return lb


class WorldsPage(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._copy_src: str | None = None
        self._delete_src: dict | None = None
        self._share_src: dict | None = None
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 10)
        lay.setSpacing(8)
        widgets.page_header(lay, "存档库", "创建、导入并进入你的世界")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(widgets.button("新建存档", self._create_dialog,
                                     variant="primary"))
        row.addWidget(widgets.button("导入存档", self._import))
        row.addStretch(1)
        lay.addLayout(row)

        self.grid = cards.CardGrid()
        lay.addWidget(self.grid, stretch=1)

        self.dlg_detail = cards.ItemDetailDialog(self)
        self._build_create_dlg()
        self._build_copy_dlg()
        self._build_share_dlg()
        self._build_delete_dlg()

    # ---------- 对话框 ----------

    def _build_create_dlg(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("新建存档")
        d.setMinimumWidth(420)
        d.setModal(True)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        widgets.section_title("存档信息", lay)
        lay.addWidget(widgets.label("存档名", tone="muted", small=True))
        self.w_name = QLineEdit()
        self.w_name.setPlaceholderText("例如：冒险岛")
        lay.addWidget(self.w_name)
        lay.addWidget(widgets.label("游戏模式", tone="muted", small=True))
        mrow = QHBoxLayout()
        self.w_mode_survival = QRadioButton("生存")
        self.w_mode_creative = QRadioButton("创造")
        self.w_mode_survival.setChecked(True)
        mrow.addWidget(self.w_mode_survival)
        mrow.addWidget(self.w_mode_creative)
        mrow.addStretch(1)
        lay.addLayout(mrow)
        lay.addWidget(widgets.label("世界种子（可留空）", tone="muted",
                                    small=True))
        self.w_seed = QLineEdit()
        lay.addWidget(self.w_seed)
        self.err_create = _err_label(lay)
        widgets.hline(lay)
        brow = QHBoxLayout()
        brow.addWidget(widgets.button("创建", variant="primary", width=96,
                                      on_click=d.accept))
        brow.addWidget(widgets.button("取消", width=96, on_click=d.reject))
        brow.addStretch(1)
        lay.addLayout(brow)
        self.dlg_create = d

    def _build_copy_dlg(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("复制存档")
        d.setMinimumWidth(400)
        d.setModal(True)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        lay.addWidget(widgets.label("新存档名", tone="muted", small=True))
        self.copy_name = QLineEdit()
        lay.addWidget(self.copy_name)
        self.err_copy = _err_label(lay)
        widgets.hline(lay)
        brow = QHBoxLayout()
        brow.addWidget(widgets.button("复制", variant="primary", width=96,
                                      on_click=d.accept))
        brow.addWidget(widgets.button("取消", width=96, on_click=d.reject))
        brow.addStretch(1)
        lay.addLayout(brow)
        self.dlg_copy = d

    def _build_share_dlg(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("分享到工坊")
        d.setMinimumWidth(460)
        d.setModal(True)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        widgets.section_title("发布地图包 .lnpkg", lay)
        lay.addWidget(widgets.label("作品名", tone="muted", small=True))
        self.share_name = QLineEdit()
        lay.addWidget(self.share_name)
        hrow = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(widgets.label("版本", tone="muted", small=True))
        self.share_ver = QLineEdit("1.0.0")
        col.addWidget(self.share_ver)
        hrow.addLayout(col)
        hrow.addStretch(1)
        lay.addLayout(hrow)
        lay.addWidget(widgets.label("简介", tone="muted", small=True))
        self.share_desc = QPlainTextEdit()
        self.share_desc.setFixedHeight(80)
        lay.addWidget(self.share_desc)
        self.err_share = _err_label(lay)
        widgets.hline(lay)
        brow = QHBoxLayout()
        brow.addWidget(widgets.button("打包并上传", variant="primary",
                                      width=130, on_click=d.accept))
        brow.addWidget(widgets.button("取消", width=96, on_click=d.reject))
        brow.addStretch(1)
        lay.addLayout(brow)
        self.dlg_share = d

    def _build_delete_dlg(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("删除存档")
        d.setMinimumWidth(400)
        d.setModal(True)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        lb = QLabel("确定删除该存档？此操作不可恢复。")
        lb.setWordWrap(True)
        lay.addWidget(lb)
        self.delete_name = QLabel("")
        theme.set_tone(self.delete_name, "danger")
        lay.addWidget(self.delete_name)
        widgets.hline(lay)
        brow = QHBoxLayout()
        brow.addWidget(widgets.button("确认删除", variant="danger", width=110,
                                      on_click=d.accept))
        brow.addWidget(widgets.button("取消", width=96, on_click=d.reject))
        brow.addStretch(1)
        lay.addLayout(brow)
        self.dlg_delete = d

    # ---------- 数据 ----------

    def refresh(self) -> None:
        items = worlds.list_worlds()
        if not items:
            self.grid.set_empty("还没有存档 — 点击“新建存档”开始你的世界")
            return
        self.grid.set_cards([self._card(w) for w in items])

    # ---------- 卡片 ----------

    def _card(self, w: dict):
        box: dict = {}
        card = cards.build_card(
            title=w["name"],
            subtitle=f"{_mode_text(w)} · 模组 {len(w['enabled_mods'])}",
            desc=f"目录 {w['dir_name']} · 最后游玩 {_last_text(w)}",
            seed=w["name"],
            buttons=[
                {"text": "进入", "variant": "primary",
                 "on_click": lambda _x=False, ww=w: self._play(ww)},
                {"text": "详情",
                 "on_click": lambda _x=False, ww=w, b=box:
                 self._detail(ww, b.get("thumb"))},
                {"text": "删除", "variant": "danger",
                 "on_click": lambda _x=False, ww=w: self._delete(ww)},
            ])
        box["thumb"] = card.thumb
        return card.frame

    def _detail(self, w: dict, thumb) -> None:
        try:
            seed = worlds.read_settings(
                WORLDS_ROOT / w["dir_name"] / "world.mt").get("seed", "")
        except Exception:  # noqa: BLE001
            seed = ""
        self.dlg_detail.open_item(
            w["name"], cards.safe_image(thumb),
            [
                ("名称", w["name"]),
                ("目录名", w["dir_name"]),
                ("游戏", w["gameid"] or "-"),
                ("模式", _mode_text(w)),
                ("种子", seed or "-"),
                ("启用模组", "、".join(w["enabled_mods"]) or "无"),
            ],
            [
                {"text": "进入", "variant": "primary",
                 "on_click": lambda ww=w: self._play(ww)},
                {"text": "复制", "on_click": lambda ww=w: self._copy(ww)},
                {"text": "分享", "on_click": lambda ww=w: self._share(ww)},
                {"text": "删除", "variant": "danger",
                 "on_click": lambda ww=w: self._delete(ww)},
            ])


    # ---------- 操作 ----------

    def _create_dialog(self) -> None:
        # 游戏固定为默认游戏（不在 UI 显示游戏选择）
        self.w_name.setText("")
        self.w_seed.setText("")
        self.err_create.setText("")
        if self.dlg_create.exec() == QDialog.Accepted:
            self._create_submit()

    def _create_submit(self) -> None:
        name = self.w_name.text().strip()
        if not name:
            self.err_create.setText("存档名不能为空")
            self.dlg_create.exec()
            return
        gameid = engine.DEFAULT_GAME
        try:
            worlds.create_world(
                name, gameid,
                creative=self.w_mode_creative.isChecked(),
                seed=self.w_seed.text().strip())
            self.app.set_status(f"存档 {name} 创建成功")
            self.refresh()
        except Exception as ex:  # noqa: BLE001
            self.err_create.setText(str(ex))
            self.dlg_create.exec()

    def _copy(self, w: dict) -> None:
        self._copy_src = w["dir_name"]
        self.copy_name.setText(f"{w['name']} 副本")
        self.err_copy.setText("")
        if self.dlg_copy.exec() == QDialog.Accepted:
            self._copy_submit()

    def _copy_submit(self) -> None:
        name = self.copy_name.text().strip()
        if not self._copy_src or not name:
            self.err_copy.setText("名称无效")
            self.dlg_copy.exec()
            return
        try:
            worlds.copy_world(self._copy_src, name)
            self.app.set_status("复制完成")
            self.refresh()
        except Exception as ex:  # noqa: BLE001
            self.err_copy.setText(str(ex))
            self.dlg_copy.exec()

    def _share(self, w: dict) -> None:
        if not api.is_logged_in:
            self.app.set_status("请先登录再分享")
            return
        self._share_src = w
        self.share_name.setText(w["name"])
        self.share_desc.setPlainText("")
        self.err_share.setText("")
        if self.dlg_share.exec() == QDialog.Accepted:
            self._share_submit()

    def _share_submit(self) -> None:
        w = self._share_src
        if w is None:
            return
        self.app.set_status("正在打包地图…")
        name = self.share_name.text().strip() or w["name"]
        version = self.share_ver.text().strip() or "1.0.0"
        desc = self.share_desc.toPlainText().strip()

        def work():
            tmp = (Path(tempfile.gettempdir())
                   / f"lunaticn_share_{id(w)}.lnpkg")
            try:
                manifest = {
                    "type": "map", "name": name, "version": version,
                    "description": desc, "gameid": w["gameid"],
                    "engine": engine.installed_version() or "",
                    "author": (api.user or {}).get("nickname", ""),
                }
                build_from_world(WORLDS_ROOT / w["dir_name"], manifest,
                                 str(tmp))
                ui_call(self.app.set_status, "正在上传…")
                return api.upload_package(str(tmp))
            finally:
                tmp.unlink(missing_ok=True)

        def done(pkg, err):
            if err is not None:
                self.app.set_status(f"分享失败: {err}")
                return
            self.app.set_status(f"已发布到工坊：{pkg.get('name', name)}")

        async_task(work, done)

    def _delete(self, w: dict) -> None:
        self._delete_src = w
        self.delete_name.setText(f"{w['name']}  ·  {w['dir_name']}")
        if self.dlg_delete.exec() == QDialog.Accepted:
            self._delete_submit()

    def _delete_submit(self) -> None:
        w = self._delete_src
        if w is None:
            return
        try:
            worlds.delete_world(w["dir_name"])
            self.app.set_status("已删除存档")
            self.refresh()
        except Exception as ex:  # noqa: BLE001
            self.app.set_status(str(ex))

    def _play(self, w: dict) -> None:
        def work():
            engine.ensure_engine(status=lambda s: ui_call(
                self.app.set_status, s))
            engine.play_world(w["dir_name"], w["gameid"],
                              status=lambda s: ui_call(
                                  self.app.set_status, s))

        def done(_v, err):
            if err is not None:
                self.app.set_status(f"启动失败: {err}")
            else:
                self.app.set_status(f"正在启动 {w['name']}…")

        async_task(work, done)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择存档压缩包", "",
            "存档包 (*.zip *.lnpkg);;所有文件 (*)")
        if not path:
            return
        try:
            name = packages.import_world_zip(path, WORLDS_ROOT)
            self.app.set_status(f"已导入存档 {name}")
            self.refresh()
        except Exception as ex:  # noqa: BLE001
            self.app.set_status(f"导入失败: {ex}")
