# Shared slate + teal styles for the homepage and the edit board.

import os

PRIMARY_CONTROL_H = 50
RIGHT_TOOL_COL_W = 200
LEFT_HINT_COL_W = 248

_GUI_DIR = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
_CHECK_MARK_URL = 'url("%s/check_mark.png")' % _GUI_DIR

PRIMARY_BTN_STYLE = """
QPushButton {
    min-height: %dpx;
    max-height: %dpx;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 14px;
    background-color: #0f766e;
    color: #f0fdfa;
    padding: 0 16px;
    border: 1px solid #14b8a6;
}
QPushButton:hover:enabled {
    background-color: #0d9488;
    border: 1px solid #2dd4bf;
}
QPushButton:pressed:enabled {
    background-color: #115e59;
}
QPushButton:disabled {
    background-color: #334155;
    color: #94a3b8;
    border: 1px solid #475569;
}
""" % (PRIMARY_CONTROL_H, PRIMARY_CONTROL_H)

HISTORY_BTN_STYLE = """
QPushButton {
    min-height: %dpx;
    max-height: %dpx;
    font-size: 15px;
    font-weight: 600;
    border-radius: 14px;
    background-color: #1e293b;
    color: #e2e8f0;
    padding: 0 16px;
    border: 1px solid #334155;
}
QPushButton:hover:enabled {
    background-color: #243044;
    border: 1px solid #14b8a6;
    color: #f0fdfa;
}
QPushButton:pressed:enabled {
    background-color: #0f172a;
}
QPushButton:disabled {
    background-color: #1e293b;
    color: #64748b;
    border: 1px solid #334155;
}
""" % (PRIMARY_CONTROL_H, PRIMARY_CONTROL_H)

ADD_BTN_ACTIVE_STYLE = """
QPushButton {
    min-height: %dpx;
    max-height: %dpx;
    font-size: 15px;
    font-weight: 700;
    border-radius: 14px;
    background-color: #134e4a;
    color: #f0fdfa;
    padding: 0 16px;
    border: 2px solid #2dd4bf;
}
QPushButton:hover:enabled {
    background-color: #0f766e;
    border: 2px solid #5eead4;
}
""" % (PRIMARY_CONTROL_H, PRIMARY_CONTROL_H)

SAVE_EDIT_BTN_STYLE = """
QPushButton {
    min-height: %dpx;
    max-height: %dpx;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 14px;
    background-color: #fde68a;
    color: #422006;
    padding: 0 16px;
    border: 1px solid #fbbf24;
}
QPushButton:hover:enabled {
    background-color: #fcd34d;
    border: 1px solid #f59e0b;
    color: #422006;
}
QPushButton:pressed:enabled {
    background-color: #fbbf24;
}
QPushButton:disabled {
    background-color: #334155;
    color: #94a3b8;
    border: 1px solid #475569;
}
""" % (PRIMARY_CONTROL_H, PRIMARY_CONTROL_H)

BOARD_WINDOW_QSS = """
QDialog#resultBoard {
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #0b1220, stop:0.45 #111827, stop:1 #0f172a
    );
    color: #e2e8f0;
}
QDialog#resultBoard QLabel {
    background: transparent;
}
QFrame#hintPanel, QFrame#statusPanel, QFrame#goalPanel, QFrame#toolPanel, QFrame#confirmPanel {
    background-color: rgba(30, 41, 59, 0.82);
    border: 1px solid #334155;
    border-radius: 16px;
}
QFrame#modeSelectPanel {
    background-color: rgba(15, 23, 42, 0.96);
    border: 1px dashed #2dd4bf;
    border-radius: 10px;
}
QLabel#hintTitle {
    color: #2dd4bf;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#modeSelectCaption {
    color: #5eead4;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#hintBody {
    color: #e2e8f0;
    font-size: 13px;
}
QLabel#statusBody {
    color: #fecaca;
    font-size: 13px;
    font-weight: 700;
}
QLabel#goalBody {
    color: #cbd5e1;
    font-size: 13px;
}
QPushButton#modeItem {
    min-height: 32px;
    max-height: 32px;
    font-size: 14px;
    font-weight: 600;
    border-radius: 6px;
    background-color: transparent;
    color: #e2e8f0;
    padding: 0 10px;
    border: 1px solid transparent;
    text-align: left;
}
QPushButton#modeItem:hover:!checked {
    background-color: #0b1220;
    border: 1px solid #134e4a;
}
QPushButton#modeItem:checked {
    background-color: #020617;
    color: #e2e8f0;
    padding: 0 10px;
    border: 1px solid #2dd4bf;
}
QPushButton#modeItem:checked:hover {
    border: 1px solid #5eead4;
    background-color: #0b1220;
}
QPushButton#modeItem[requiredMode="true"] {
    color: #fca5a5;
}
QPushButton#modeItem[requiredMode="true"]:checked {
    color: #fca5a5;
    font-weight: 700;
    background-color: #020617;
    border: 1px solid #2dd4bf;
}
QCheckBox {
    color: #e2e8f0;
    font-size: 13px;
    font-weight: 600;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #94a3b8;
    background: #020617;
}
QCheckBox::indicator:hover {
    border: 1px solid #2dd4bf;
}
QCheckBox::indicator:checked {
    background: #0f766e;
    border: 1px solid #5eead4;
    image: %s;
}
QCheckBox::indicator:unchecked {
    image: none;
}
QCheckBox::indicator:disabled {
    background: #1e293b;
    border: 1px solid #334155;
}
QCheckBox:disabled {
    color: #64748b;
}
QGraphicsView#editBoard {
    border: 1px solid #334155;
    border-radius: 12px;
    background-color: #0b1220;
}
""" % (_CHECK_MARK_URL,)

STATUS_PANEL_IDLE_QSS = (
    "QFrame#statusPanel {"
    "background-color: rgba(30, 41, 59, 0.82);"
    "border: 1px solid #334155;"
    "border-radius: 16px;"
    "}"
)
STATUS_PANEL_SUCCESS_QSS = (
    "QFrame#statusPanel {"
    "background-color: rgba(15, 118, 110, 0.55);"
    "border: 1px solid #2dd4bf;"
    "border-radius: 16px;"
    "}"
)
STATUS_PANEL_ERROR_QSS = (
    "QFrame#statusPanel {"
    "background-color: rgba(127, 29, 29, 0.45);"
    "border: 1px solid #fca5a5;"
    "border-radius: 16px;"
    "}"
)
CACHE_BTN_FLASH_QSS = """
QPushButton {
    min-height: %dpx;
    max-height: %dpx;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 14px;
    background-color: #fffbeb;
    color: #422006;
    padding: 0 16px;
    border: 2px solid #ca8a04;
}
""" % (PRIMARY_CONTROL_H, PRIMARY_CONTROL_H)
