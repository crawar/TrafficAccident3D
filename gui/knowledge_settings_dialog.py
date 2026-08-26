# -*- coding: utf-8 -*-
"""Dedicated knowledge-base settings dialog (not part of system settings)."""

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from utils.ai_settings import load_ai_settings
from utils.knowledge_refine import KnowledgeRefineCancelled, refine_knowledge_from_excel
from utils.knowledge_store import (
    MAX_ACCIDENTS,
    MAX_PACK_NAME,
    delete_pack,
    delete_playbook,
    has_ai_api_key,
    list_pack_summaries,
    playbook_is_populated,
    playbook_status_text,
    prepare_example_table_readonly_copy,
    rename_pack,
    set_pack_enabled,
)

PLAYBOOK_DELETE_COUNTDOWN_SEC = 10


class KnowledgeRefineThread(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, xlsx_path, ai_settings, parent=None):
        super().__init__(parent)
        self.xlsx_path = xlsx_path
        self.ai_settings = dict(ai_settings or {})
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            pack = refine_knowledge_from_excel(
                self.xlsx_path,
                ai_settings=self.ai_settings,
                progress_cb=lambda percent, message: self.progress.emit(percent, message),
                should_cancel=lambda: self._cancel,
            )
            self.finished_ok.emit(pack)
        except KnowledgeRefineCancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class DeletePlaybookConfirmDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("删除手册")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._left = PLAYBOOK_DELETE_COUNTDOWN_SEC

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(16)

        warning = QLabel(
            "您正在删除AI重要事故智能手册，删除将丧失全部AI专家的专有智能，是否确定？"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color: #dc2626; font-size: 15px; font-weight: 700; line-height: 140%;"
        )
        layout.addWidget(warning)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setAutoDefault(True)
        self.cancel_btn.setDefault(True)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton(f"确定（{self._left}）")
        self.ok_btn.setEnabled(False)
        self.ok_btn.setAutoDefault(False)
        self.ok_btn.setDefault(False)
        self.ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)

    def _on_tick(self):
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.ok_btn.setEnabled(True)
            self.ok_btn.setText("确定")
            return
        self.ok_btn.setText(f"确定（{self._left}）")

    def closeEvent(self, event):
        if self._timer.isActive():
            self._timer.stop()
        super().closeEvent(event)


class KnowledgeSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("知识库设置")
        self.resize(760, 620)
        self.setWindowModality(Qt.ApplicationModal)
        self._thread = None
        self._loading_table = False
        self._init_ui()
        self._refresh_state()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("历史认定知识库")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        intro = QLabel(
            "选择事故 Excel（A 列为发生经过，B 列为人工认定）后精炼。"
            "可先点「查看精炼表格示例」对照格式；示例为只读，请另存为自己的表格后再填写并上传。"
            "口径手册全库只有一份，再次精炼会去重合并进手册。"
            "案件结果按列表保存，新结果不会覆盖旧结果；可勾选启用、重命名，删除某一份不会改手册。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #334155;")
        layout.addWidget(intro)

        self.api_warning = QLabel()
        self.api_warning.setWordWrap(True)
        self.api_warning.setStyleSheet(
            """
            color: #7f1d1d;
            background-color: #fee2e2;
            border: 1px solid #fca5a5;
            border-radius: 8px;
            padding: 10px 12px;
            font-weight: 600;
            """
        )
        layout.addWidget(self.api_warning)

        self.playbook_label = QLabel()
        self.playbook_label.setWordWrap(True)
        self.playbook_label.setStyleSheet(
            """
            background-color: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 12px;
            color: #0f172a;
            """
        )
        layout.addWidget(self.playbook_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "案件数", "精炼时间"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._refresh_row_actions)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("暂无精炼结果。选择 Excel 后会在此追加一条。")
        self.empty_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self.empty_label)

        self.example_btn = QPushButton("查看精炼表格示例")
        self.example_btn.setMinimumHeight(40)
        self.example_btn.setCursor(Qt.PointingHandCursor)
        self.example_btn.setAutoDefault(False)
        self.example_btn.setDefault(False)
        self.example_btn.clicked.connect(self._on_open_example_table)
        layout.addWidget(self.example_btn)

        self.refine_btn = QPushButton("选择 Excel 并精炼")
        self.refine_btn.setMinimumHeight(40)
        self.refine_btn.setCursor(Qt.PointingHandCursor)
        self.refine_btn.setAutoDefault(False)
        self.refine_btn.setDefault(False)
        self.refine_btn.clicked.connect(self._on_refine)
        layout.addWidget(self.refine_btn)

        hint = QLabel(
            f"每次最多精炼 {MAX_ACCIDENTS} 起事故。表格超过该数量时只取前 {MAX_ACCIDENTS} 行，"
            "以免接口调用等待过长。精炼约需十几到二十次接口调用，过程中会关闭思考模式以加快速度，请保持网络畅通。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(hint)

        self.progress_label = QLabel("等待开始")
        self.progress_label.setStyleSheet("color: #0f766e; font-weight: 600;")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.rename_btn = QPushButton("重命名")
        self.rename_btn.setAutoDefault(False)
        self.rename_btn.setDefault(False)
        self.rename_btn.clicked.connect(self._on_rename)
        btn_row.addWidget(self.rename_btn)
        self.delete_btn = QPushButton("删除所选")
        self.delete_btn.setAutoDefault(False)
        self.delete_btn.setDefault(False)
        self.delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self.delete_btn)
        self.delete_playbook_btn = QPushButton("删除手册")
        self.delete_playbook_btn.setAutoDefault(False)
        self.delete_playbook_btn.setDefault(False)
        self.delete_playbook_btn.clicked.connect(self._on_delete_playbook)
        btn_row.addWidget(self.delete_playbook_btn)
        btn_row.addStretch(1)
        self.close_btn = QPushButton("关闭")
        self.close_btn.setAutoDefault(False)
        self.close_btn.setDefault(False)
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    def _running(self):
        return self._thread is not None and self._thread.isRunning()

    def _selected_pack_id(self):
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _refresh_row_actions(self):
        running = self._running()
        has_row = bool(self._selected_pack_id())
        self.rename_btn.setEnabled((not running) and has_row)
        self.delete_btn.setEnabled((not running) and has_row)

    def _reload_table(self):
        self._loading_table = True
        summaries = list_pack_summaries()
        self.table.setRowCount(len(summaries))
        for row, item in enumerate(summaries):
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable
            )
            enabled_item.setCheckState(Qt.Checked if item.get("enabled") else Qt.Unchecked)
            enabled_item.setData(Qt.UserRole, item.get("id"))
            enabled_item.setToolTip(str(item.get("sourceFile") or ""))
            self.table.setItem(row, 0, enabled_item)

            name_item = QTableWidgetItem(str(item.get("name") or "未命名精炼结果"))
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            source = str(item.get("sourceFile") or "")
            if source:
                name_item.setToolTip(f"来源文件：{source}")
            self.table.setItem(row, 1, name_item)

            count_item = QTableWidgetItem(str(int(item.get("cardCount") or 0)))
            count_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            count_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, count_item)

            time_item = QTableWidgetItem(str(item.get("distilledAt") or ""))
            time_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 3, time_item)
        self.empty_label.setVisible(not summaries)
        self.table.setVisible(bool(summaries))
        self._loading_table = False
        if summaries and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._refresh_row_actions()

    def _refresh_state(self):
        running = self._running()
        has_key = has_ai_api_key()
        self.api_warning.setVisible(not has_key)
        if not has_key:
            self.api_warning.setText(
                "尚未配置 AI API 密钥，知识库无法精炼，也不会注入责任分析。"
                "请先打开「系统设置 → AI连接」，勾选启用并填写 API 密钥后再回来精炼。"
            )
        self.playbook_label.setText(playbook_status_text())
        self._reload_table()
        self.example_btn.setEnabled(not running)
        self.refine_btn.setEnabled(has_key and not running)
        self.delete_playbook_btn.setEnabled((not running) and playbook_is_populated())
        self.close_btn.setEnabled(not running)
        if not running and self.progress_bar.value() == 0:
            self.progress_label.setText("等待开始")
        self._refresh_row_actions()

    def _on_item_changed(self, item):
        if self._loading_table or item is None or item.column() != 0:
            return
        pack_id = str(item.data(Qt.UserRole) or "")
        if not pack_id:
            return
        try:
            set_pack_enabled(pack_id, item.checkState() == Qt.Checked)
        except Exception as exc:
            QMessageBox.warning(self, "无法更新", str(exc))
            self._refresh_state()
            return
        self.playbook_label.setText(playbook_status_text())

    def _on_open_example_table(self):
        try:
            dest = prepare_example_table_readonly_copy()
        except Exception as exc:
            QMessageBox.warning(self, "无法打开示例", str(exc))
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(dest))
        if not opened:
            QMessageBox.warning(
                self,
                "无法打开示例",
                "已生成只读副本，但未能用系统默认程序打开。请确认本机已安装 Excel 或 WPS。",
            )
            return
        self.progress_label.setText("已只读打开示例。请另存为自己的表格后再填写并上传。")

    def _on_refine(self):
        if not has_ai_api_key():
            QMessageBox.warning(
                self,
                "无法精炼",
                "请先在系统设置中配置 AI API 密钥。",
            )
            self._refresh_state()
            return
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择事故 Excel",
            "",
            "Excel (*.xlsx)",
        )
        if not file_name:
            return
        self._start_refine(file_name)

    def _start_refine(self, xlsx_path):
        self.progress_bar.setValue(0)
        self.progress_label.setText("准备精炼…")
        self._thread = KnowledgeRefineThread(
            xlsx_path, load_ai_settings(), parent=self
        )
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_refine_ok)
        self._thread.failed.connect(self._on_refine_failed)
        self._thread.finished.connect(self._on_thread_finished)
        self._refresh_state()
        self._thread.start()

    def _on_progress(self, percent, message):
        self.progress_bar.setValue(int(percent))
        self.progress_label.setText(message or "精炼中…")

    def _on_refine_ok(self, pack):
        used = int((pack or {}).get("usedRows") or 0)
        name = str((pack or {}).get("name") or "未命名精炼结果")
        truncated = bool((pack or {}).get("truncated"))
        extra = (
            f"原始表格超过 {MAX_ACCIDENTS} 起，已只精炼前 {used} 起。"
            if truncated
            else f"已精炼 {used} 起事故。"
        )
        if (pack or {}).get("playbookMerged", True):
            extra += "口径手册已去重合并。"
        else:
            extra += "案件结果已保存；口径手册合并失败，仍保留原手册。"
            err = str((pack or {}).get("playbookMergeError") or "")
            if err:
                extra += f"\n{err[:240]}"
        QMessageBox.information(
            self,
            "精炼完成",
            f"已新增「{name}」。{extra}责任分析会参考已勾选的结果。",
        )
        self.progress_bar.setValue(100)
        self.progress_label.setText("知识库精炼完成。")

    def _on_refine_failed(self, message):
        self.progress_label.setText("精炼失败")
        QMessageBox.critical(self, "精炼失败", str(message or "未知错误"))

    def _on_thread_finished(self):
        self._thread = None
        self._refresh_state()

    def _on_rename(self):
        pack_id = self._selected_pack_id()
        if not pack_id:
            return
        current = ""
        item = self.table.item(self.table.currentRow(), 1)
        if item is not None:
            current = item.text()
        name, ok = QInputDialog.getText(
            self,
            "重命名",
            "结果名称（便于区分来源）：",
            text=current,
        )
        if not ok:
            return
        name = str(name or "").strip()
        if not name:
            QMessageBox.warning(self, "无法重命名", "名称不能为空。")
            return
        if len(name) > MAX_PACK_NAME:
            name = name[:MAX_PACK_NAME]
        try:
            rename_pack(pack_id, name)
        except Exception as exc:
            QMessageBox.warning(self, "无法重命名", str(exc))
            return
        self._refresh_state()

    def _on_delete(self):
        pack_id = self._selected_pack_id()
        if not pack_id:
            return
        name = ""
        item = self.table.item(self.table.currentRow(), 1)
        if item is not None:
            name = item.text()
        answer = QMessageBox.question(
            self,
            "删除确认",
            f"删除「{name or '该结果'}」后，将无法再检索其中的相似案件。"
            "口径手册不会被删除或回退。是否删除？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_pack(pack_id)
        except Exception as exc:
            QMessageBox.warning(self, "无法删除", str(exc))
            return
        self.progress_bar.setValue(0)
        self.progress_label.setText("已删除所选精炼结果。")
        self._refresh_state()

    def _on_delete_playbook(self):
        if not playbook_is_populated():
            return
        dialog = DeletePlaybookConfirmDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            delete_playbook()
        except Exception as exc:
            QMessageBox.warning(self, "无法删除手册", str(exc))
            return
        self.progress_bar.setValue(0)
        self.progress_label.setText("口径手册已删除。")
        self._refresh_state()
        QMessageBox.information(self, "已删除", "口径手册已删除。案件精炼结果仍保留。")

    def closeEvent(self, event):
        if self._running():
            QMessageBox.warning(
                self,
                "精炼进行中",
                "正在调用接口精炼知识库，请等待完成后再关闭。",
            )
            event.ignore()
            return
        super().closeEvent(event)
