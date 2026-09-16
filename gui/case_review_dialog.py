# -*- coding: utf-8 -*-
"""Accident-document review window. Opened from the homepage."""

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
    QSlider,
    QVBoxLayout,
)

from gui.app_styles import (
    BOARD_WINDOW_QSS,
    HISTORY_BTN_STYLE,
    PRIMARY_CONTROL_H,
)
from gui.desensitize_warning_dialog import DesensitizeWarningDialog
from utils.case_review import (
    ADVERSARIAL_GUIDE,
    DEFAULT_ADVERSARIAL_LEVEL,
    CaseReviewCancelled,
    review_accident_document,
)


class CaseReviewThread(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        src_path,
        ai_settings,
        adversarial_level,
        discipline_review,
        parent=None,
    ):
        super().__init__(parent)
        self.src_path = src_path
        self.ai_settings = dict(ai_settings or {})
        self.adversarial_level = adversarial_level
        self.discipline_review = bool(discipline_review)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            dest = review_accident_document(
                self.src_path,
                self.ai_settings,
                progress_cb=lambda percent, message: self.progress.emit(percent, message),
                should_cancel=lambda: self._cancel,
                adversarial_level=self.adversarial_level,
                discipline_review=self.discipline_review,
            )
            self.finished_ok.emit(dest)
        except CaseReviewCancelled as extra:
            self.failed.emit(str(extra))
        except Exception as extra:
            self.failed.emit(str(extra))


class CaseReviewDialog(QDialog):
    def __init__(self, ai_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("事故复核")
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
            QSlider::groove:horizontal {
                height: 6px;
                background: #1e293b;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
                background: #2dd4bf;
                border: 1px solid #14b8a6;
            }
            QSlider::sub-page:horizontal {
                background: #0f766e;
                border-radius: 3px;
            }
            QSlider::tick-mark:horizontal {
                background: #94a3b8;
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
        self._ai_settings = dict(ai_settings or {})
        self._src_path = ""
        self._thread = None
        self._busy = False
        self._last_output = ""
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        intro = QLabel(
            "事故复核用于审查已经写成的事故决定书或事故调查报告是否站得住。"
            "请选择一份 Word（.docx）。系统会用隐藏的案件复核角色做对抗性分析："
            "事实是否调查清晰、法律依据是否完整、责任划分是否合理、结论是否合理。"
            "下方滑条可调节对抗程度：越靠左越包容，越靠右质疑越严，默认“较包容”。"
            "勾选“纪律审查”后，还会从纪委视角评估报告人是否可能因收受贿赂导致认定偏差，"
            "该部分力度同样随滑条变化。"
            "分析时会参考系统设置中的 AI 提示词、知识库中的口径手册和已启用案件索引，"
            "不会使用专家角色定位。"
            "完成后会在原文件同目录生成“复核”加原文件名的 Word，第一行写明复核结果，"
            "文末注明上述为 AI 意见、仅供参考。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("hintBody")
        layout.addWidget(intro)

        level_caption = QLabel("对抗程度")
        level_caption.setObjectName("sectionLabel")
        layout.addWidget(level_caption)

        self.level_slider = QSlider(Qt.Horizontal)
        self.level_slider.setRange(1, 5)
        self.level_slider.setValue(DEFAULT_ADVERSARIAL_LEVEL)
        self.level_slider.setTickPosition(QSlider.TicksBelow)
        self.level_slider.setTickInterval(1)
        self.level_slider.setPageStep(1)
        self.level_slider.setSingleStep(1)
        self.level_slider.valueChanged.connect(self._on_level_changed)
        layout.addWidget(self.level_slider)

        scale_row = QHBoxLayout()
        left_tip = QLabel("包容")
        left_tip.setObjectName("sectionLabel")
        self.level_value_label = QLabel("")
        self.level_value_label.setAlignment(Qt.AlignCenter)
        self.level_value_label.setObjectName("hintBody")
        right_tip = QLabel("对抗")
        right_tip.setObjectName("sectionLabel")
        right_tip.setAlignment(Qt.AlignRight)
        scale_row.addWidget(left_tip, 1)
        scale_row.addWidget(self.level_value_label, 2)
        scale_row.addWidget(right_tip, 1)
        layout.addLayout(scale_row)
        self._on_level_changed(self.level_slider.value())

        self.discipline_checkbox = QCheckBox("纪律审查")
        self.discipline_checkbox.setChecked(True)
        self.discipline_checkbox.setToolTip(
            "勾选后增加纪委审查内容，怀疑报告人是否因收受贿赂导致认定偏差；力度随对抗程度滑条变化。"
        )
        layout.addWidget(self.discipline_checkbox)

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

    def _on_level_changed(self, value):
        guide = ADVERSARIAL_GUIDE.get(int(value), ADVERSARIAL_GUIDE[DEFAULT_ADVERSARIAL_LEVEL])
        self.level_value_label.setText("%d/5  %s" % (int(value), guide["name"]))

    def _running(self):
        return self._busy or (self._thread is not None and self._thread.isRunning())

    def _refresh_busy(self):
        busy = self._running()
        self.pick_btn.setEnabled(not busy)
        self.level_slider.setEnabled(not busy)
        self.discipline_checkbox.setEnabled(not busy)
        self.open_folder_btn.setEnabled((not busy) and bool(self._last_output))

    def _on_pick_file(self):
        if self._running():
            return
        warn = DesensitizeWarningDialog(self)
        if warn.exec() != DesensitizeWarningDialog.Accepted:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择事故决定书或调查报告",
            "",
            "Word (*.docx)",
        )
        if not path:
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "所选文件不存在。")
            return
        self._src_path = path
        self._last_output = ""
        self.file_label.setText("已选择：%s" % path)
        self.output_label.setText("")
        self._start()

    def _start(self):
        if not self._src_path or self._running():
            return
        self.progress_bar.setValue(0)
        self.status_label.setText("正在准备复核…")
        self._busy = True
        self._refresh_busy()
        self._thread = CaseReviewThread(
            self._src_path,
            self._ai_settings,
            self.level_slider.value(),
            self.discipline_checkbox.isChecked(),
            self,
        )
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_progress(self, percent, message):
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        self.status_label.setText(message or "审查中…")

    def _on_finished(self, dest_path):
        self._last_output = dest_path
        self.progress_bar.setValue(100)
        self.status_label.setText("复核完成。")
        self.output_label.setText("已生成：%s" % dest_path)
        self._thread = None
        self._busy = False
        self._refresh_busy()

    def _on_failed(self, message):
        self.status_label.setText(message or "复核失败")
        self._thread = None
        self._busy = False
        self._refresh_busy()
        if message != "已取消事故复核。":
            QMessageBox.warning(self, "复核失败", str(message or "未知错误"))

    def _on_open_folder(self):
        if self._running() or not self._last_output:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self._last_output)))

    def reject(self):
        if self._running():
            return
        super().reject()

    def closeEvent(self, event):
        if self._running():
            QMessageBox.warning(
                self,
                "复核进行中",
                "正在调用接口审查文书，请等待完成后再关闭。",
            )
            event.ignore()
            return
        super().closeEvent(event)
