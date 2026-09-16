# -*- coding: utf-8 -*-
"""Offline judgment-analysis window. Opened from the homepage."""

import os

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from gui.app_styles import (
    BOARD_WINDOW_QSS,
    HISTORY_BTN_STYLE,
    PRIMARY_BTN_STYLE,
    PRIMARY_CONTROL_H,
)
from judgment_analysis.excel_io import (
    HEADER_CANDIDATE_LIMIT,
    ExcelLoadError,
    apply_header_row,
    header_row_preview,
    load_sheet,
    resolve_header_row,
)
from judgment_analysis.fields import (
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    field_tooltip,
)
from judgment_analysis.mapping import (
    load_mapping_state,
    missing_required,
    save_mapping_state,
)
from judgment_analysis.report import ReportCancelled, generate_report

COUNTDOWN_SEC = 5
HEADER_WARNING_TEXT = (
    "请确认表格中有一行是列名表头。表头以下每一行都应是事故信息；"
    "如有合计行、统计行请删除。"
)
PREVIEW_ROW_LIMIT = 100
UNMAPPED_LABEL = "（未映射）"
SUSPICIOUS_PROMPT_LIMIT = 30

DIALOG_EXTRA_QSS = """
QDialog {
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #0b1220, stop:0.45 #111827, stop:1 #0f172a
    );
    color: #e2e8f0;
}
QDialog QLabel {
    background: transparent;
}
QLabel#sectionLabel {
    color: #64748b;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
QProgressBar {
    border: none;
    border-radius: 5px;
    background-color: #1e293b;
}
QProgressBar::chunk {
    border-radius: 5px;
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #0f766e, stop:1 #2dd4bf
    );
}
QComboBox {
    min-height: 36px;
    font-size: 13px;
    color: #e2e8f0;
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 0 10px;
}
QComboBox:hover {
    border: 1px solid #14b8a6;
}
QComboBox:disabled {
    color: #64748b;
    background-color: #1e293b;
}
QComboBox QAbstractItemView {
    background-color: #0f172a;
    color: #e2e8f0;
    selection-background-color: #0f766e;
    border: 1px solid #334155;
}
QTableWidget {
    background-color: #0f172a;
    color: #e2e8f0;
    gridline-color: #334155;
    border: 1px solid #334155;
    border-radius: 8px;
    font-size: 12px;
}
QTableWidget::item {
    padding: 4px;
}
QHeaderView::section {
    background-color: #1e293b;
    color: #2dd4bf;
    font-weight: 700;
    border: none;
    border-right: 1px solid #334155;
    border-bottom: 1px solid #334155;
    padding: 6px 8px;
}
QTableCornerButton::section {
    background-color: #1e293b;
    border: none;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: #0f172a;
    border: none;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #334155;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
"""


class HeaderWarningDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("表格格式提示")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        self.setWindowModality(Qt.ApplicationModal)
        self._left = COUNTDOWN_SEC
        self._allow_close = False
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0f172a;
                color: #e2e8f0;
            }
            QDialog QLabel {
                background: transparent;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(18)

        warning = QLabel(HEADER_WARNING_TEXT)
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color: #fecaca; font-size: 15px; font-weight: 700; line-height: 140%;"
        )
        layout.addWidget(warning)

        self.ok_btn = QPushButton("确定（%d）" % self._left)
        self.ok_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        self.ok_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setEnabled(False)
        self.ok_btn.setAutoDefault(False)
        self.ok_btn.setDefault(False)
        self.ok_btn.clicked.connect(self._on_confirm)
        layout.addWidget(self.ok_btn)

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
        self.ok_btn.setText("确定（%d）" % self._left)

    def _on_confirm(self):
        self._allow_close = True
        if self._timer.isActive():
            self._timer.stop()
        self.accept()

    def reject(self):
        return

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Cancel):
            event.ignore()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._allow_close:
            event.ignore()
            return
        if self._timer.isActive():
            self._timer.stop()
        super().closeEvent(event)


class HeaderMappingDialog(QDialog):
    def __init__(self, raw_rows, current_index, parent=None):
        super().__init__(parent)
        self.setWindowTitle("表头映射")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(BOARD_WINDOW_QSS + DIALOG_EXTRA_QSS)
        self._raw_rows = list(raw_rows or [])
        self._current_index = current_index
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "请选择真正的列名表头所在行。该行会显示在预览表最上方，不再出现在预览内容里。"
            "表头之前的行在分析时会被忽略。不设置表头映射则无法列映射，也无法开始分析。"
            "下拉仅列出前 %d 行，表头一般就在这一段。"
            % HEADER_CANDIDATE_LIMIT
        )
        intro.setWordWrap(True)
        intro.setObjectName("hintBody")
        layout.addWidget(intro)

        caption = QLabel("表头所在行")
        caption.setObjectName("sectionLabel")
        layout.addWidget(caption)

        self.row_combo = QComboBox()
        self.row_combo.setCursor(Qt.PointingHandCursor)
        self.row_combo.addItem("请选择表头所在行", -1)
        limit = min(len(self._raw_rows), HEADER_CANDIDATE_LIMIT)
        for index in range(limit):
            label = "第 %d 行：%s" % (
                index + 1,
                header_row_preview(self._raw_rows[index]),
            )
            self.row_combo.addItem(label, index)
        if self._current_index is not None:
            found = self.row_combo.findData(self._current_index)
            if found >= 0:
                self.row_combo.setCurrentIndex(found)
        layout.addWidget(self.row_combo)

        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        ok_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.clicked.connect(self._on_confirm)
        layout.addWidget(ok_btn)

    def selected_row_index(self):
        value = self.row_combo.currentData()
        try:
            index = int(value)
        except (TypeError, ValueError):
            return None
        if index < 0:
            return None
        return index

    def _on_confirm(self):
        if self.selected_row_index() is None:
            QMessageBox.warning(self, "提示", "请选择表头所在行。")
            return
        self.accept()


class ColumnMappingDialog(QDialog):
    def __init__(self, headers, mapping, parent=None):
        super().__init__(parent)
        self.setWindowTitle("列映射")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(BOARD_WINDOW_QSS + DIALOG_EXTRA_QSS)
        self._headers = list(headers or [])
        self._mapping = dict(mapping or {})
        self._combos = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "把表头行里的列名对应到系统要分析的字段。下拉项就是您刚选定的表头内容。"
            "必填项开始分析前必须全部选到。鼠标移到字段名上可查看含义和影响章节。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("hintBody")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for field, required in (
            [(item, True) for item in REQUIRED_FIELDS]
            + [(item, False) for item in OPTIONAL_FIELDS]
        ):
            label_text = "%s*" % field["label"] if required else field["label"]
            caption = QLabel(label_text)
            caption.setToolTip(field_tooltip(field, required))
            caption.setObjectName("hintBody")
            combo = QComboBox()
            combo.setCursor(Qt.PointingHandCursor)
            combo.addItem(UNMAPPED_LABEL, "")
            for header in self._headers:
                combo.addItem(header, header)
            current = str(self._mapping.get(field["key"]) or "").strip()
            index = combo.findData(current)
            if index < 0:
                index = 0
            combo.setCurrentIndex(index)
            combo.setToolTip(field_tooltip(field, required))
            self._combos[field["key"]] = combo
            form.addRow(caption, combo)
        layout.addLayout(form)

        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        ok_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.clicked.connect(self._on_confirm)
        layout.addWidget(ok_btn)

    def selected_mapping(self):
        result = {}
        for key, combo in self._combos.items():
            result[key] = str(combo.currentData() or "").strip()
        return result

    def _on_confirm(self):
        self.accept()


class LoadThread(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, path, sheet_name=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.sheet_name = sheet_name

    def run(self):
        try:
            data = load_sheet(
                self.path,
                self.sheet_name,
                progress_cb=lambda percent, message: self.progress.emit(percent, message),
            )
            self.finished_ok.emit(data)
        except ExcelLoadError as extra:
            self.failed.emit(str(extra))
        except Exception as extra:
            self.failed.emit(str(extra))


class ReportThread(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, headers, rows, mapping, src_path, parent=None):
        super().__init__(parent)
        self.headers = list(headers or [])
        self.rows = [list(row) for row in (rows or [])]
        self.mapping = dict(mapping or {})
        self.src_path = src_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            dest = generate_report(
                self.headers,
                self.rows,
                self.mapping,
                self.src_path,
                progress_cb=lambda percent, message: self.progress.emit(percent, message),
                should_cancel=lambda: self._cancel,
            )
            self.finished_ok.emit(dest)
        except ReportCancelled as extra:
            self.failed.emit(str(extra))
        except Exception as extra:
            self.failed.emit(str(extra))


class JudgmentAnalysisDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("研判分析")
        self.setModal(True)
        self.setMinimumSize(900, 640)
        self.setStyleSheet(BOARD_WINDOW_QSS + DIALOG_EXTRA_QSS)
        self._src_path = ""
        self._sheet_names = []
        self._active_name = ""
        self._sheet_name = ""
        self._raw_rows = []
        self._header_row_index = None
        self._headers = []
        self._rows = []
        saved = load_mapping_state()
        self._mapping = dict(saved["columns"])
        self._saved_header_row = saved["header_row_index"]
        self._saved_header_labels = list(saved["header_labels"] or [])
        self._thread = None
        self._busy = False
        self._last_output = ""
        self._suppress_sheet = False
        self._pending_suspicious = []
        self._init_ui()
        self._refresh_busy()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "研判分析用于把事故台账 Excel 离线汇总成 Word「事故分析报告」，不调用 AI、不联网。"
            "载入后请先做「表头映射」，再做「列映射」。可用「保存映射」记住表头和列，下次载入会自动带回。"
            "报告生成在所选 Excel 的同一文件夹，文件名带生成时间。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("hintBody")
        layout.addWidget(intro)

        self.file_label = QLabel("尚未选择文件")
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.file_label.setObjectName("hintBody")
        layout.addWidget(self.file_label)

        self.pick_btn = QPushButton("选择文件")
        self.pick_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.pick_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.clicked.connect(self._on_pick_file)
        layout.addWidget(self.pick_btn)

        sheet_row = QHBoxLayout()
        self.sheet_caption = QLabel("工作表")
        self.sheet_caption.setObjectName("sectionLabel")
        self.sheet_combo = QComboBox()
        self.sheet_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sheet_combo.setMinimumHeight(36)
        self.sheet_combo.addItem("尚未加载工作表")
        self.sheet_combo.currentTextChanged.connect(self._on_sheet_changed)
        sheet_row.addWidget(self.sheet_caption)
        sheet_row.addWidget(self.sheet_combo, 1)
        layout.addLayout(sheet_row)

        action_row = QHBoxLayout()
        self.header_map_btn = QPushButton("表头映射")
        self.header_map_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.header_map_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.header_map_btn.setCursor(Qt.PointingHandCursor)
        self.header_map_btn.setToolTip("指定哪一行是列名表头。必须先设置表头，才能做列映射。")
        self.header_map_btn.clicked.connect(self._on_map_header)
        self.map_btn = QPushButton("列映射")
        self.map_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.map_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.map_btn.setCursor(Qt.PointingHandCursor)
        self.map_btn.setToolTip("把表头列名对应到系统字段。需要先完成表头映射。")
        self.map_btn.clicked.connect(self._on_map_columns)
        self.save_map_btn = QPushButton("保存映射")
        self.save_map_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.save_map_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.save_map_btn.setCursor(Qt.PointingHandCursor)
        self.save_map_btn.setToolTip("保存当前表头映射和列映射，不必开始分析。下次载入会自动带回。")
        self.save_map_btn.clicked.connect(self._on_save_mapping)
        self.analyze_btn = QPushButton("开始分析")
        self.analyze_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        self.analyze_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.analyze_btn.setCursor(Qt.PointingHandCursor)
        self.analyze_btn.clicked.connect(self._on_analyze)
        action_row.addWidget(self.header_map_btn, 1)
        action_row.addWidget(self.map_btn, 1)
        action_row.addWidget(self.save_map_btn, 1)
        action_row.addWidget(self.analyze_btn, 1)
        layout.addLayout(action_row)

        preview_caption = QLabel("数据预览")
        preview_caption.setObjectName("sectionLabel")
        layout.addWidget(preview_caption)

        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setVisible(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.table, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("hintBody")
        layout.addWidget(self.status_label)

        self.output_label = QLabel("")
        self.output_label.setWordWrap(True)
        self.output_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.output_label.setObjectName("goalBody")
        layout.addWidget(self.output_label)

        self.open_folder_btn = QPushButton("打开输出文件夹")
        self.open_folder_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.open_folder_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.open_folder_btn.setCursor(Qt.PointingHandCursor)
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        layout.addWidget(self.open_folder_btn)

    def _running(self):
        return self._busy or (self._thread is not None and self._thread.isRunning())

    def _has_raw(self):
        return bool(self._src_path and self._raw_rows)

    def _has_header(self):
        return self._header_row_index is not None and bool(self._headers)

    def _refresh_busy(self):
        busy = self._running()
        has_raw = self._has_raw()
        has_header = self._has_header()
        self.pick_btn.setEnabled(not busy)
        self.sheet_combo.setEnabled((not busy) and has_raw)
        self.header_map_btn.setEnabled((not busy) and has_raw)
        self.map_btn.setEnabled((not busy) and has_header)
        self.save_map_btn.setEnabled((not busy) and has_raw)
        self.analyze_btn.setEnabled((not busy) and has_raw)
        self.open_folder_btn.setEnabled((not busy) and bool(self._last_output))

    def _set_status(self, text):
        self.status_label.setText(text or "")

    def _cell_display(self, value):
        if value is None:
            return ""
        return str(value)

    def _fill_preview(self):
        if self._has_header():
            headers = list(self._headers or [])
            rows = list(self._rows or [])[:PREVIEW_ROW_LIMIT]
            start_excel_row = self._header_row_index + 2
        else:
            raw = list(self._raw_rows or [])
            width = max((len(row) for row in raw), default=0)
            headers = ["列%d" % (index + 1) for index in range(width)]
            rows = raw[:PREVIEW_ROW_LIMIT]
            start_excel_row = 1
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(headers)
        labels = [str(start_excel_row + index) for index in range(len(rows))]
        self.table.setVerticalHeaderLabels(labels)
        for row_index, row in enumerate(rows):
            for col_index in range(len(headers)):
                value = row[col_index] if col_index < len(row) else ""
                item = QTableWidgetItem(self._cell_display(value))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(row_index, col_index, item)
        if headers:
            self.table.resizeColumnsToContents()

    def _apply_loaded_data(self, data):
        self._src_path = data.get("path") or self._src_path
        self._sheet_names = list(data.get("sheet_names") or [])
        self._active_name = data.get("active_name") or ""
        self._sheet_name = data.get("sheet_name") or self._active_name
        self._raw_rows = [list(row) for row in (data.get("raw_rows") or [])]
        self._header_row_index = None
        self._headers = []
        self._rows = []
        self._pending_suspicious = list(data.get("suspicious_rows") or [])
        self._suppress_sheet = True
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        if self._sheet_names:
            self.sheet_combo.addItems(self._sheet_names)
            index = self.sheet_combo.findText(self._sheet_name)
            if index >= 0:
                self.sheet_combo.setCurrentIndex(index)
        else:
            self.sheet_combo.addItem("尚未加载工作表")
        self.sheet_combo.blockSignals(False)
        self._suppress_sheet = False
        name = os.path.basename(self._src_path)
        self.file_label.setText("已加载：%s" % self._src_path)
        restored = self._restore_saved_header()
        extra = ""
        if len(self._raw_rows) > PREVIEW_ROW_LIMIT:
            extra = "，预览前 %d 行" % PREVIEW_ROW_LIMIT
        if restored:
            extra = ""
            if len(self._rows) > PREVIEW_ROW_LIMIT:
                extra = "，预览前 %d 行" % PREVIEW_ROW_LIMIT
            self._set_status(
                "已加载 %s（%s，共 %d 行）。已按上次表头映射（第 %d 行）载入，数据 %d 行%s。"
                % (
                    name,
                    self._sheet_name,
                    len(self._raw_rows),
                    self._header_row_index + 1,
                    len(self._rows),
                    extra,
                )
            )
        else:
            self._fill_preview()
            self._set_status(
                "已加载 %s（%s，共 %d 行%s）。请先设置表头映射。"
                % (name, self._sheet_name, len(self._raw_rows), extra)
            )
        self._last_output = ""
        self.output_label.setText("")
        self._refresh_busy()

    def _format_suspicious_rows(self, rows):
        numbers = [int(item) for item in rows]
        if len(numbers) <= SUSPICIOUS_PROMPT_LIMIT:
            return "、".join(str(item) for item in numbers)
        shown = "、".join(str(item) for item in numbers[:SUSPICIOUS_PROMPT_LIMIT])
        return "%s……等共%d" % (shown, len(numbers))

    def _warn_suspicious_if_needed(self):
        rows = list(self._pending_suspicious or [])
        self._pending_suspicious = []
        if not rows:
            return
        formatted = self._format_suspicious_rows(rows)
        QMessageBox.warning(
            self,
            "可能存在非事故信息行",
            "检测到可能存在非事故信息行，位于表格第%s行，可能会影响事故研判，"
            "建议删除后重新加载表格。"
            % formatted,
        )

    def _start_load(self, path, sheet_name=None):
        if self._running():
            return
        self.progress_bar.setValue(0)
        self._set_status("正在载入表格…")
        self._busy = True
        self._refresh_busy()
        self._thread = LoadThread(path, sheet_name, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_load_finished)
        self._thread.failed.connect(self._on_load_failed)
        self._thread.start()

    def _on_pick_file(self):
        if self._running():
            return
        warn = HeaderWarningDialog(self)
        if warn.exec() != HeaderWarningDialog.Accepted:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择事故台账表格",
            "",
            "Excel (*.xlsx *.xls)",
        )
        if not path:
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "所选文件不存在。")
            return
        self._start_load(path)

    def _on_sheet_changed(self, name):
        if self._suppress_sheet or self._running() or not self._src_path:
            return
        name = str(name or "").strip()
        if not name:
            return
        self._start_load(self._src_path, name)

    def _on_load_finished(self, data):
        self._thread = None
        self._busy = False
        self.progress_bar.setValue(100)
        try:
            self._apply_loaded_data(data or {})
        except Exception as extra:
            self._refresh_busy()
            QMessageBox.warning(self, "无法加载", str(extra))
            self._set_status(str(extra))
            return
        self._refresh_busy()
        self._warn_suspicious_if_needed()

    def _on_load_failed(self, message):
        self._thread = None
        self._busy = False
        self._refresh_busy()
        self._set_status(message or "载入失败")
        QMessageBox.warning(self, "无法加载", str(message or "未知错误"))

    def _persist_mapping(self, status_text="映射已保存"):
        labels = list(self._headers) if self._has_header() else list(self._saved_header_labels or [])
        saved = save_mapping_state(self._mapping, self._header_row_index, labels)
        self._mapping = dict(saved["columns"])
        self._saved_header_row = saved["header_row_index"]
        self._saved_header_labels = list(saved["header_labels"] or [])
        if status_text:
            self._set_status(status_text)
        return saved

    def _restore_saved_header(self):
        resolved = resolve_header_row(
            self._raw_rows,
            self._saved_header_row,
            self._saved_header_labels,
        )
        if resolved is None:
            return False
        try:
            self._apply_header_index(resolved, persist=False, status_text="")
        except ExcelLoadError:
            return False
        return self._has_header()

    def _apply_header_index(self, header_row_index, persist=True, status_text=None):
        headers, rows = apply_header_row(self._raw_rows, header_row_index)
        self._header_row_index = header_row_index
        self._headers = headers
        self._rows = rows
        self._fill_preview()
        extra = ""
        if len(self._rows) > PREVIEW_ROW_LIMIT:
            extra = "，预览前 %d 行" % PREVIEW_ROW_LIMIT
        if persist:
            self._persist_mapping(
                "表头映射已保存（第 %d 行），数据 %d 行%s。请继续设置列映射。"
                % (header_row_index + 1, len(self._rows), extra)
            )
        elif status_text:
            self._set_status(status_text)
        self._refresh_busy()

    def _on_map_header(self):
        if self._running() or not self._has_raw():
            return
        dialog = HeaderMappingDialog(self._raw_rows, self._header_row_index, self)
        if dialog.exec() != HeaderMappingDialog.Accepted:
            return
        index = dialog.selected_row_index()
        try:
            self._apply_header_index(index)
        except ExcelLoadError as extra:
            QMessageBox.warning(self, "表头映射失败", str(extra))

    def _on_map_columns(self):
        if self._running():
            return
        if not self._has_header():
            QMessageBox.warning(self, "请先设置表头", "必须先完成表头映射，才能设置列映射。")
            self._on_map_header()
            if not self._has_header():
                return
        dialog = ColumnMappingDialog(self._headers, self._mapping, self)
        if dialog.exec() != ColumnMappingDialog.Accepted:
            return
        self._mapping = dict(dialog.selected_mapping())
        self._persist_mapping("列映射已保存")

    def _ensure_header(self):
        if self._has_header():
            return True
        QMessageBox.warning(
            self,
            "缺少表头映射",
            "开始分析前必须先设置表头映射。",
        )
        self._on_map_header()
        return self._has_header()

    def _ensure_mapping(self):
        if not self._ensure_header():
            return False
        missing = missing_required(self._mapping, self._headers)
        if not missing:
            return True
        QMessageBox.warning(
            self,
            "缺少必要映射",
            "开始分析前必须映射：%s。" % "、".join(missing),
        )
        dialog = ColumnMappingDialog(self._headers, self._mapping, self)
        if dialog.exec() != ColumnMappingDialog.Accepted:
            return False
        self._mapping = dict(dialog.selected_mapping())
        self._persist_mapping("列映射已保存")
        missing = missing_required(self._mapping, self._headers)
        if missing:
            QMessageBox.warning(
                self,
                "缺少必要映射",
                "仍缺少：%s。" % "、".join(missing),
            )
            return False
        return True

    def _on_save_mapping(self):
        if self._running() or not self._has_raw():
            return
        if not self._has_header():
            QMessageBox.warning(self, "请先设置表头", "请先完成表头映射，再保存映射。")
            self._on_map_header()
            if not self._has_header():
                return
        self._persist_mapping("映射已保存。下次载入将自动带回表头和列映射。")

    def _on_analyze(self):
        if self._running() or not self._has_raw():
            return
        if not self._ensure_mapping():
            return
        self._persist_mapping(status_text="")
        self.progress_bar.setValue(0)
        self._set_status("正在准备分析…")
        self.output_label.setText("")
        self._busy = True
        self._refresh_busy()
        self._thread = ReportThread(
            self._headers,
            self._rows,
            self._mapping,
            self._src_path,
            self,
        )
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_progress(self, percent, message):
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        self._set_status(message or "处理中…")

    def _on_finished(self, dest_path):
        self._last_output = dest_path
        self.progress_bar.setValue(100)
        self._set_status("报告生成完成")
        self.output_label.setText("已生成：%s" % dest_path)
        self._thread = None
        self._busy = False
        self._refresh_busy()

    def _on_failed(self, message):
        self._set_status(message or "分析失败")
        self._thread = None
        self._busy = False
        self._refresh_busy()
        if message != "已取消研判分析。":
            QMessageBox.warning(self, "分析失败", str(message or "未知错误"))

    def _on_open_folder(self):
        if self._running():
            return
        folder = ""
        if self._last_output:
            folder = os.path.dirname(self._last_output)
        elif self._src_path:
            folder = os.path.dirname(os.path.abspath(self._src_path))
        if not folder:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def reject(self):
        if self._running():
            return
        super().reject()

    def closeEvent(self, event):
        if self._running():
            QMessageBox.warning(
                self,
                "处理进行中",
                "正在载入表格或生成报告，请等待完成后再关闭。",
            )
            event.ignore()
            return
        super().closeEvent(event)
