from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils.ai_experts import (
    MAX_EXPERTS,
    MAX_ROLE_CHARS,
    avatar_path_for,
    create_custom_expert,
    delete_expert,
    list_experts,
    load_ai_experts,
    update_expert,
    validate_avatar_file,
)


class AddExpertDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增专家")
        self.setModal(True)
        self._avatar_path = ""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(40)
        self.name_edit.setPlaceholderText("专家名称")
        form.addRow("专家名称", self.name_edit)

        self.role_edit = QTextEdit()
        self.role_edit.setPlaceholderText(f"角色定位（不超过 {MAX_ROLE_CHARS} 字）")
        self.role_edit.setFixedHeight(120)
        form.addRow("角色定位", self.role_edit)

        avatar_row = QHBoxLayout()
        self.avatar_label = QLabel("未选择（将使用默认问号头像）")
        self.avatar_label.setWordWrap(True)
        pick_btn = QPushButton("选择头像")
        pick_btn.clicked.connect(self._pick_avatar)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._clear_avatar)
        avatar_row.addWidget(self.avatar_label, 1)
        avatar_row.addWidget(pick_btn)
        avatar_row.addWidget(clear_btn)
        form.addRow("头像", avatar_row)
        layout.addLayout(form)

        tip = QLabel("头像可选；若上传须为 1:1 正方形且不超过 500KB。新增专家默认启用。")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择头像",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        ok, message = validate_avatar_file(path)
        if not ok:
            QMessageBox.warning(self, "头像无效", message)
            return
        self._avatar_path = path
        self.avatar_label.setText(path)

    def _clear_avatar(self):
        self._avatar_path = ""
        self.avatar_label.setText("未选择（将使用默认问号头像）")

    def values(self):
        return {
            "name": self.name_edit.text().strip(),
            "rolePrompt": self.role_edit.toPlainText().strip(),
            "avatarPath": self._avatar_path,
        }


class AiExpertSettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._payload = load_ai_experts()
        self._current_id = ""
        self._pending_avatar = ""
        self._init_ui()
        self._reload_combo(select_id=None)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tip = QLabel(
            "在此管理 AI 事故报告专家。默认四位专家不可删除/停用，但可编辑角色定位。"
            "启用 AI 分析后，启用中的专家角色定位会一次性注入提示词。"
            f"专家总数上限 {MAX_EXPERTS} 人。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        top = QHBoxLayout()
        self.expert_combo = QComboBox()
        self.expert_combo.currentIndexChanged.connect(self._on_combo_changed)
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedWidth(36)
        self.add_btn.setToolTip("新增专家")
        self.add_btn.clicked.connect(self._on_add)
        top.addWidget(QLabel("选择专家"), 0)
        top.addWidget(self.expert_combo, 1)
        top.addWidget(self.add_btn, 0)
        layout.addLayout(top)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(40)
        form.addRow("专家名称", self.name_edit)

        self.enabled_check = QCheckBox("启用该专家")
        form.addRow("状态", self.enabled_check)

        self.avatar_preview = QLabel()
        self.avatar_preview.setFixedSize(96, 96)
        self.avatar_preview.setAlignment(Qt.AlignCenter)
        self.avatar_preview.setStyleSheet(
            "border: 1px solid #ccc; background: #f5f5f5; border-radius: 48px;"
        )
        avatar_row = QHBoxLayout()
        avatar_row.addWidget(self.avatar_preview)
        self.change_avatar_btn = QPushButton("更换头像")
        self.change_avatar_btn.clicked.connect(self._on_change_avatar)
        avatar_row.addWidget(self.change_avatar_btn)
        avatar_row.addStretch(1)
        form.addRow("头像", avatar_row)

        self.role_edit = QTextEdit()
        self.role_edit.setPlaceholderText(f"角色定位（不超过 {MAX_ROLE_CHARS} 字）")
        self.role_edit.setFixedHeight(160)
        form.addRow("角色定位", self.role_edit)

        self.role_count_label = QLabel(f"0 / {MAX_ROLE_CHARS}")
        form.addRow("", self.role_count_label)
        self.role_edit.textChanged.connect(self._update_role_count)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._on_save_current)
        self.delete_btn = QPushButton("删除")
        self.delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    def _experts(self):
        return list_experts(self._payload)

    def _find_expert(self, expert_id):
        for expert in self._experts():
            if expert.get("id") == expert_id:
                return expert
        return None

    def _reload_combo(self, select_id=None):
        self._payload = load_ai_experts()
        experts = self._experts()
        self.expert_combo.blockSignals(True)
        self.expert_combo.clear()
        for expert in experts:
            label = expert.get("name", expert.get("id", ""))
            if expert.get("isDefault"):
                label = f"{label}（默认）"
            elif not expert.get("enabled"):
                label = f"{label}（停用）"
            self.expert_combo.addItem(label, expert.get("id"))
        self.expert_combo.blockSignals(False)
        self.add_btn.setEnabled(len(experts) < MAX_EXPERTS)
        self.add_btn.setToolTip(
            "新增专家" if len(experts) < MAX_EXPERTS else f"已达上限 {MAX_EXPERTS} 人"
        )
        if not experts:
            self._current_id = ""
            return
        target = select_id or self._current_id or experts[0]["id"]
        index = max(0, self.expert_combo.findData(target))
        self.expert_combo.setCurrentIndex(index)
        self._load_expert(self.expert_combo.currentData())

    def _on_combo_changed(self, _index):
        self._load_expert(self.expert_combo.currentData())

    def _set_avatar_preview(self, expert):
        path = avatar_path_for(expert)
        pix = QPixmap(path)
        if pix.isNull():
            self.avatar_preview.setText("?")
            return
        scaled = pix.scaled(
            96,
            96,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.avatar_preview.setPixmap(scaled)
        self.avatar_preview.setText("")

    def _load_expert(self, expert_id):
        expert = self._find_expert(expert_id)
        self._current_id = expert_id or ""
        self._pending_avatar = ""
        if not expert:
            return
        is_default = bool(expert.get("isDefault"))
        self.name_edit.setText(expert.get("name", ""))
        self.name_edit.setEnabled(not is_default)
        self.enabled_check.setChecked(bool(expert.get("enabled", True)))
        self.enabled_check.setEnabled(not is_default)
        self.delete_btn.setEnabled(not is_default)
        self.change_avatar_btn.setEnabled(not is_default)
        self.role_edit.setPlainText(expert.get("rolePrompt", ""))
        self._set_avatar_preview(expert)
        self._update_role_count()

    def _update_role_count(self):
        text = self.role_edit.toPlainText()
        if len(text) > MAX_ROLE_CHARS:
            cursor = self.role_edit.textCursor()
            pos = cursor.position()
            self.role_edit.blockSignals(True)
            self.role_edit.setPlainText(text[:MAX_ROLE_CHARS])
            self.role_edit.blockSignals(False)
            cursor.setPosition(min(pos, MAX_ROLE_CHARS))
            self.role_edit.setTextCursor(cursor)
            text = self.role_edit.toPlainText()
        self.role_count_label.setText(f"{len(text)} / {MAX_ROLE_CHARS}")

    def _on_add(self):
        if len(self._experts()) >= MAX_EXPERTS:
            QMessageBox.information(self, "提示", f"专家总数不能超过 {MAX_EXPERTS} 人。")
            return
        dialog = AddExpertDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        try:
            self._payload, expert = create_custom_expert(
                values["name"],
                values["rolePrompt"],
                avatar_source_path=values["avatarPath"] or None,
                payload=self._payload,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "新增失败", str(exc))
            return
        self._reload_combo(select_id=expert["id"])
        QMessageBox.information(self, "成功", "专家已新增并启用。")

    def _on_change_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择头像",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        ok, message = validate_avatar_file(path)
        if not ok:
            QMessageBox.warning(self, "头像无效", message)
            return
        self._pending_avatar = path
        pix = QPixmap(path).scaled(
            96,
            96,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self.avatar_preview.setPixmap(pix)

    def _on_save_current(self):
        if not self._current_id:
            return False
        try:
            self._payload, _expert = update_expert(
                self._current_id,
                name=self.name_edit.text().strip(),
                role_prompt=self.role_edit.toPlainText().strip(),
                enabled=self.enabled_check.isChecked(),
                avatar_source_path=self._pending_avatar or None,
                payload=self._payload,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        self._pending_avatar = ""
        self._reload_combo(select_id=self._current_id)
        return True

    def _on_delete(self):
        if not self._current_id:
            return
        expert = self._find_expert(self._current_id)
        if not expert or expert.get("isDefault"):
            QMessageBox.information(self, "提示", "默认专家无法删除。")
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除专家「{expert.get('name', '')}」吗？",
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._payload = delete_expert(self._current_id, payload=self._payload)
        except ValueError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self._reload_combo(select_id=None)
        QMessageBox.information(self, "成功", "专家已删除。")

    def save_settings(self):
        ok = self._on_save_current()
        if ok:
            return load_ai_experts()
        return None
