# -*- coding: utf-8 -*-
"""Standalone offline desensitization window. Opened only from the homepage."""

import os

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from gui.app_styles import (
    BOARD_WINDOW_QSS,
    HISTORY_BTN_STYLE,
    PRIMARY_BTN_STYLE,
    PRIMARY_CONTROL_H,
)
from utils.offline_desensitize import (
    DesensitizeCancelled,
    desensitize_file,
    ner_model_ready,
    output_path_for,
)


class DesensitizeThread(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, src_path, options, parent=None):
        super().__init__(parent)
        self.src_path = src_path
        self.options = dict(options or {})
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            dest = desensitize_file(
                self.src_path,
                self.options,
                progress_cb=lambda percent, message: self.progress.emit(percent, message),
                should_cancel=lambda: self._cancel,
            )
            self.finished_ok.emit(dest)
        except DesensitizeCancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class OfflineDesensitizeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("离线脱敏")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(
            BOARD_WINDOW_QSS
            + """
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
            """
        )
        self._thread = None
        self._busy = False
        self._last_output = ""
        self._init_ui()
        self._refresh_ready_hint()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "本页把表格或 Word 文档做成带 * 号的脱敏副本，全程离线、不联网。"
            "地址和人名用中文 NER 滚轮扫描识别；身份证匹配 18 位连续数字，"
            "或 17 位连续数字加末尾 X/x；手机号匹配连续 11 位数字；"
            "数字和字母按字符直接替换。"
            "人名保留姓氏，写成“张某*”这种形式（四个字则为“张某**”）。"
            "表格按每个格子处理，文档按全文处理。生成文件与原文件在同一文件夹，"
            "文件名为“脱敏”加原文件名。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("hintBody")
        layout.addWidget(intro)

        self.ready_label = QLabel("")
        self.ready_label.setWordWrap(True)
        self.ready_label.setObjectName("goalBody")
        layout.addWidget(self.ready_label)

        self.file_label = QLabel("尚未选择文件")
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("hintBody")
        layout.addWidget(self.file_label)

        option_tip = QLabel("脱敏内容（默认全选，至少勾选 1 项）")
        option_tip.setObjectName("sectionLabel")
        layout.addWidget(option_tip)

        option_row = QHBoxLayout()
        option_row.setSpacing(12)
        self.chk_address = QCheckBox("地址")
        self.chk_name = QCheckBox("人名")
        self.chk_idcard = QCheckBox("身份证")
        self.chk_phone = QCheckBox("手机号")
        self.chk_digit = QCheckBox("数字")
        self.chk_letter = QCheckBox("字母")
        self.chk_idcard.setToolTip("18 位连续数字，或 17 位连续数字加末尾 X/x。")
        self.chk_phone.setToolTip("连续 11 位数字。")
        for box in self._option_boxes():
            box.setChecked(True)
            box.toggled.connect(self._on_option_toggled)
            option_row.addWidget(box)
        option_row.addStretch(1)
        layout.addLayout(option_row)

        self.pick_btn = QPushButton("选择文件")
        self.pick_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.pick_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.clicked.connect(self._on_pick_file)
        layout.addWidget(self.pick_btn)

        self.start_btn = QPushButton("开始脱敏")
        self.start_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        self.start_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)
        layout.addWidget(self.start_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("等待选择文件")
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

        self._src_path = ""

    def _option_boxes(self):
        return (
            self.chk_address,
            self.chk_name,
            self.chk_idcard,
            self.chk_phone,
            self.chk_digit,
            self.chk_letter,
        )

    def _selected_options(self):
        return {
            "address": self.chk_address.isChecked(),
            "name": self.chk_name.isChecked(),
            "idcard": self.chk_idcard.isChecked(),
            "phone": self.chk_phone.isChecked(),
            "digit": self.chk_digit.isChecked(),
            "letter": self.chk_letter.isChecked(),
        }

    def _checked_count(self):
        return sum(1 for value in self._selected_options().values() if value)

    def _refresh_ready_hint(self):
        if ner_model_ready():
            self.ready_label.setText("中文 NER 权重已就绪（downloads\\chinese_ner）。")
        else:
            self.ready_label.setText(
                "尚未找到中文 NER 权重。若要脱敏地址或人名，请把模型文件放到 "
                "downloads\\chinese_ner（下载地址见 README）。"
                "只勾选数字、字母、身份证或手机号时不需要该权重。"
            )

    def _on_option_toggled(self, _checked):
        sender = self.sender()
        if self._checked_count() < 1 and sender is not None:
            sender.blockSignals(True)
            sender.setChecked(True)
            sender.blockSignals(False)
            QMessageBox.information(self, "提示", "至少勾选 1 项脱敏内容。")
        self._refresh_start_enabled()

    def _running(self):
        return self._busy or (self._thread is not None and self._thread.isRunning())

    def _refresh_start_enabled(self):
        busy = self._running()
        self.start_btn.setEnabled(
            bool(self._src_path) and not busy and self._checked_count() >= 1
        )
        self.pick_btn.setEnabled(not busy)
        self.open_folder_btn.setEnabled((not busy) and bool(self._last_output))
        for box in self._option_boxes():
            box.setEnabled(not busy)

    def _on_pick_file(self):
        if self._running():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择要脱敏的文件",
            "",
            "Excel 与 Word (*.xlsx *.xls *.docx);;Excel (*.xlsx *.xls);;Word (*.docx)",
        )
        if not path:
            return
        self._src_path = path
        self._last_output = ""
        self.open_folder_btn.setEnabled(False)
        self.file_label.setText("已选择：%s" % path)
        self.output_label.setText("输出将保存为：%s" % output_path_for(path))
        self.status_label.setText("文件已选定，点击“开始脱敏”。")
        self.progress_bar.setValue(0)
        self._refresh_start_enabled()

    def _on_start(self):
        if not self._src_path or self._running():
            return
        options = self._selected_options()
        if not any(options.values()):
            QMessageBox.information(self, "提示", "至少勾选 1 项脱敏内容。")
            return
        self.progress_bar.setValue(0)
        self.status_label.setText("正在脱敏，请稍候…")
        self.output_label.setText("输出将保存为：%s" % output_path_for(self._src_path))
        self._busy = True
        self._thread = DesensitizeThread(self._src_path, options, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.failed.connect(self._on_failed)
        self._refresh_start_enabled()
        self._thread.start()

    def _on_progress(self, percent, message):
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        self.status_label.setText(message)

    def _on_finished(self, dest_path):
        self._last_output = dest_path
        self.progress_bar.setValue(100)
        self.status_label.setText("脱敏完成。")
        self.output_label.setText("已生成：%s" % dest_path)
        self.open_folder_btn.setEnabled(True)
        self._thread = None
        self._busy = False
        self._refresh_start_enabled()

    def _on_failed(self, message):
        self.status_label.setText(message)
        self._thread = None
        self._busy = False
        self._refresh_start_enabled()
        if message != "已取消脱敏。":
            QMessageBox.warning(self, "脱敏失败", message)

    def _on_open_folder(self):
        if self._running() or not self._last_output:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self._last_output)))

    def closeEvent(self, event):
        if self._running():
            QMessageBox.warning(
                self,
                "脱敏进行中",
                "正在脱敏，请等待完成后再关闭。",
            )
            event.ignore()
            return
        super().closeEvent(event)
