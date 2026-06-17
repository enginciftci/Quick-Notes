import sys
import json
import os
import uuid
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QTextEdit, QLabel, QScrollArea, QFrame, 
                             QPushButton, QColorDialog, QDateTimeEdit, QSystemTrayIcon,
                             QMenu, QLineEdit, QFileDialog, QGraphicsDropShadowEffect,
                             QCalendarWidget)
from PyQt6.QtCore import Qt, QEvent, QPropertyAnimation, pyqtSignal, QThread, QMutex, QEasingCurve, QMimeData, QPoint, QRect
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QBrush, QPen, QCursor, QDrag

STORAGE_FILE = "notes.json"
RESIZE_MARGIN = 8  # Border width for resize detection

# Custom Auto-Resizing Text Edit
class AutoResizingTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self.adjust_height)
        self.setMinimumHeight(60)
        self.max_height = 200
        
    def adjust_height(self):
        doc = self.document()
        doc_layout = doc.documentLayout()
        h = doc_layout.documentSize().height()
        
        margins = self.contentsMargins()
        total_h = h + margins.top() + margins.bottom() + 15
        
        target_h = max(60, min(total_h, self.max_height))
        
        if total_h > self.max_height:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            
        self.setFixedHeight(int(target_h))
        
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'update_layout_size'):
                parent.update_layout_size()
                break
            parent = parent.parent()

# Background thread for checking reminders
class ReminderWorker(QThread):
    reminder_triggered = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reminders = []
        self.lock = QMutex()
        self.running = True

    def set_reminders(self, notes):
        self.lock.lock()
        self.reminders = []
        for note in notes:
            r_time = note.get("reminder_time")
            if r_time:
                try:
                    dt = datetime.fromisoformat(r_time)
                    if dt > datetime.now():
                        self.reminders.append((note["id"], dt, note))
                except Exception:
                    pass
        self.lock.unlock()

    def run(self):
        while self.running:
            self.msleep(1000)
            self.lock.lock()
            now = datetime.now()
            triggered = []
            for item in self.reminders:
                note_id, dt, note_data = item
                if now >= dt:
                    triggered.append(note_data)
            
            for t in triggered:
                self.reminders = [r for r in self.reminders if r[0] != t["id"]]
            self.lock.unlock()

            for note_data in triggered:
                self.reminder_triggered.emit(note_data)

    def stop(self):
        self.running = False
        self.wait()

# Circular Color Button
class ColorCircle(QPushButton):
    def __init__(self, color_hex, parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {color_hex};
                border: 2px solid #2a2a3d;
                border-radius: 12px;
            }}
            QPushButton:hover {{
                border: 2px solid #ffffff;
            }}
        """)

# Custom Note Widget
class NoteItem(QFrame):
    note_updated = pyqtSignal(str, dict)
    note_deleted = pyqtSignal(str)

    def __init__(self, note_data, parent_list):
        super().__init__()
        self.data = note_data
        self.parent_list = parent_list
        self.is_expanded = False
        self.is_editing = False
        self.is_hovered = False
        
        self.init_ui()

    def init_ui(self):
        self.setObjectName("NoteItem")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(8)
        self.shadow.setColor(QColor(0, 0, 0, 100))
        self.shadow.setOffset(0, 2)
        self.setGraphicsEffect(self.shadow)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(8)

        # Header Row Layout
        self.header_widget = QWidget()
        self.header_widget.setStyleSheet("background: transparent; border: none;")
        self.header_layout = QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(6)

        # Drag Handle
        self.drag_handle = QLabel("⋮⋮")
        self.drag_handle.setObjectName("DragHandle")
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.setStyleSheet("color: #4e4e70; font-weight: bold; font-size: 14px; padding-right: 4px; background: transparent;")
        self.drag_handle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.header_layout.addWidget(self.drag_handle)

        # Important Star Icon
        self.star_icon = QLabel("★")
        self.star_icon.setStyleSheet("color: #ffbd2e; font-size: 14px; background: transparent;")
        self.star_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.star_icon.setVisible(self.data.get("is_important", False))
        self.header_layout.addWidget(self.star_icon)

        # Header Label (Title)
        self.header_label = QLabel()
        self.header_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px; border: none; background: transparent;")
        self.header_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.header_layout.addWidget(self.header_label)

        # Reminder Bell Icon
        self.bell_icon = QLabel("🔔")
        self.bell_icon.setStyleSheet("color: #4bacff; font-size: 12px; background: transparent;")
        self.bell_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.header_layout.addWidget(self.bell_icon)
        self.header_layout.addStretch()

        self.main_layout.addWidget(self.header_widget)

        # Body & Controls Container
        self.body_container = QWidget()
        self.body_container.setStyleSheet("background: transparent; border: none;")
        self.body_layout = QVBoxLayout(self.body_container)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        
        # Read-Only View
        self.body_label = QLabel()
        self.body_label.setWordWrap(True)
        self.body_label.setStyleSheet("color: #a0a0b0; font-size: 12px; line-height: 1.4; border: none; background: transparent;")
        self.body_layout.addWidget(self.body_label)

        # Edit Mode Editor
        self.text_editor = AutoResizingTextEdit(self)
        self.text_editor.setStyleSheet("""
            QTextEdit {
                background-color: #0d0d11;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
            }
        """)
        self.text_editor.setVisible(False)
        self.body_layout.addWidget(self.text_editor)

        # Inline Reminder Editor
        self.reminder_editor = QWidget()
        self.reminder_editor.setStyleSheet("background: transparent; border: none;")
        self.reminder_layout = QHBoxLayout(self.reminder_editor)
        self.reminder_layout.setContentsMargins(0, 0, 0, 0)
        self.reminder_layout.setSpacing(6)
        
        self.reminder_dt = QDateTimeEdit(datetime.now())
        self.reminder_dt.setCalendarPopup(True)
        self.reminder_dt.setStyleSheet("""
            QDateTimeEdit {
                background-color: #0d0d11;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        self.reminder_layout.addWidget(self.reminder_dt)
        
        self.save_rem_btn = QPushButton("Set")
        self.save_rem_btn.setStyleSheet("""
            QPushButton {
                background-color: #27c93f;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #22a835; }
        """)
        self.save_rem_btn.clicked.connect(self.save_reminder)
        self.reminder_layout.addWidget(self.save_rem_btn)

        self.clear_rem_btn = QPushButton("Clear")
        self.clear_rem_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff5f56;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #e04e46; }
        """)
        self.clear_rem_btn.clicked.connect(self.clear_reminder)
        self.reminder_layout.addWidget(self.clear_rem_btn)

        self.reminder_editor.setVisible(False)
        self.body_layout.addWidget(self.reminder_editor)

        # Color Palette Panel
        self.color_panel = QWidget()
        self.color_panel.setStyleSheet("background: transparent; border: none;")
        self.color_panel_layout = QHBoxLayout(self.color_panel)
        self.color_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.color_panel_layout.setSpacing(6)
        
        colors = ["#ff5f56", "#27c93f", "#007aff", "#ffbd2e", "#af52de", "#8e8e93"]
        for c in colors:
            btn = ColorCircle(c, self)
            btn.clicked.connect(lambda checked, color=c: self.change_color(color))
            self.color_panel_layout.addWidget(btn)
            
        self.custom_color_btn = QPushButton("+ Custom")
        self.custom_color_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a24;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #3d3d5c; }
        """)
        self.custom_color_btn.clicked.connect(self.pick_custom_color)
        self.color_panel_layout.addWidget(self.custom_color_btn)
        self.color_panel_layout.addStretch()
        
        self.color_panel.setVisible(False)
        self.body_layout.addWidget(self.color_panel)

        # Toolbar Buttons Row (Space Saving Icon-Only Layout)
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setStyleSheet("background: transparent; border: none;")
        self.toolbar_layout = QHBoxLayout(self.toolbar_widget)
        self.toolbar_layout.setContentsMargins(0, 4, 0, 0)
        self.toolbar_layout.setSpacing(6)

        # Icon-only buttons
        self.edit_btn = QPushButton("✎")
        self.edit_btn.setToolTip("Edit Note")
        
        self.important_btn = QPushButton("★")
        self.important_btn.setToolTip("Pin to Top (Important)")
        
        self.color_btn = QPushButton("🎨")
        self.color_btn.setToolTip("Change Border Color")
        
        self.reminder_btn = QPushButton("🔔")
        self.reminder_btn.setToolTip("Set Reminder Alert")
        
        self.export_btn = QPushButton("📁")
        self.export_btn.setToolTip("Export to Markdown")
        
        self.delete_btn = QPushButton("🗑")
        self.delete_btn.setToolTip("Delete Note")

        self.save_btn = QPushButton("✔ Save")
        self.cancel_btn = QPushButton("✖ Cancel")

        self.all_buttons = [
            self.edit_btn, self.important_btn, self.color_btn, 
            self.reminder_btn, self.export_btn, self.delete_btn,
            self.save_btn, self.cancel_btn
        ]

        for btn in self.all_buttons:
            if btn in [self.save_btn, self.save_rem_btn]:
                bg_color, hover_color = "#27c93f", "#22a835"
                padding = "4px 8px"
            elif btn in [self.cancel_btn, self.delete_btn]:
                bg_color, hover_color = "#ff5f56", "#e04e46"
                padding = "4px 8px"
            else:
                bg_color, hover_color = "#1a1a24", "#2c2c3e"
                padding = "4px 10px"

            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    color: #ffffff;
                    border: none;
                    border-radius: 4px;
                    padding: {padding};
                    font-size: 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                }}
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self.toolbar_layout.addWidget(self.edit_btn)
        self.toolbar_layout.addWidget(self.important_btn)
        self.toolbar_layout.addWidget(self.color_btn)
        self.toolbar_layout.addWidget(self.reminder_btn)
        self.toolbar_layout.addWidget(self.export_btn)
        self.toolbar_layout.addWidget(self.delete_btn)
        
        self.toolbar_layout.addWidget(self.save_btn)
        self.toolbar_layout.addWidget(self.cancel_btn)
        self.toolbar_layout.addStretch()

        self.body_layout.addWidget(self.toolbar_widget)
        self.main_layout.addWidget(self.body_container)

        self.edit_btn.clicked.connect(self.start_edit)
        self.important_btn.clicked.connect(self.toggle_important)
        self.color_btn.clicked.connect(self.toggle_color_panel)
        self.reminder_btn.clicked.connect(self.toggle_reminder_editor)
        self.export_btn.clicked.connect(self.export_note_markdown)
        self.delete_btn.clicked.connect(self.delete_note)
        self.save_btn.clicked.connect(self.save_edit)
        self.cancel_btn.clicked.connect(self.cancel_edit)

        self.update_content_display()
        self.update_style()

        self.body_container.setMaximumHeight(0)
        self.body_container.setVisible(False)
        self.save_btn.setVisible(False)
        self.cancel_btn.setVisible(False)

        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if not self.is_editing and not self.parent_list.parent_window.is_any_note_editing():
            if event.type() == QEvent.Type.HoverEnter:
                self.is_hovered = True
                self.parent_list.expand_note(self)
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            local_handle_pos = self.drag_handle.mapFrom(self, event.pos())
            if self.drag_handle.rect().contains(local_handle_pos):
                self.drag_start_pos = event.pos()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if hasattr(self, 'drag_start_pos') and self.drag_start_pos is not None:
            if (event.pos() - self.drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                self.start_drag()
                self.drag_start_pos = None
                return
        super().mouseMoveEvent(event)

    def start_drag(self):
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(self.data["id"])
        drag.setMimeData(mime_data)

        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(self.drag_handle.pos())

        self.parent_list.dragged_widget = self
        self.setStyleSheet(self.styleSheet() + " #NoteItem { background-color: #121217; border-style: dashed; }")
        
        drag.exec(Qt.DropAction.MoveAction)
        
        self.parent_list.dragged_widget = None
        self.update_style()
        self.parent_list.save_order_after_drag()

    def update_content_display(self):
        content = self.data.get("content", "")
        lines = content.split('\n')
        
        header = lines[0] if lines else "Untitled Note"
        self.header_label.setText(header)
        
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        if not body.strip():
            body = "*(No body text)*"
        self.body_label.setText(body)

        rem_time = self.data.get("reminder_time")
        if rem_time:
            self.bell_icon.setVisible(True)
            self.bell_icon.setToolTip(f"Reminder set for: {rem_time.replace('T', ' ')}")
        else:
            self.bell_icon.setVisible(False)

        self.star_icon.setVisible(self.data.get("is_important", False))

    def update_style(self):
        color = self.data.get("frame_color", "#8e8e93")
        is_important = self.data.get("is_important", False)
        border_width = "2px" if is_important else "1px"
        
        self.setStyleSheet(f"""
            #NoteItem {{
                background-color: #161620;
                border: {border_width} solid {color};
                border-radius: 8px;
            }}
            #NoteItem QPushButton {{
                background-color: #1a1a24;
            }}
            #NoteItem QPushButton:hover {{
                background-color: #2c2c3e;
            }}
            #NoteItem QTextEdit {{
                background-color: #0d0d11;
            }}
            #NoteItem QDateTimeEdit {{
                background-color: #0d0d11;
            }}
        """)

    def update_layout_size(self):
        if self.is_expanded:
            target_h = self.body_container.layout().sizeHint().height()
            self.body_container.setMaximumHeight(target_h + 30)

    def expand(self):
        if self.is_expanded:
            return
        self.is_expanded = True
        self.body_container.setVisible(True)
        
        self.animation = QPropertyAnimation(self.body_container, b"maximumHeight")
        self.animation.setDuration(200)
        self.animation.setStartValue(0)
        
        target_h = self.body_container.layout().sizeHint().height()
        self.animation.setEndValue(target_h + 30)
        self.animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.animation.start()

    def collapse(self):
        if not self.is_expanded or self.is_editing:
            return
        self.is_expanded = False
        
        self.animation = QPropertyAnimation(self.body_container, b"maximumHeight")
        self.animation.setDuration(200)
        self.animation.setStartValue(self.body_container.height())
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.animation.finished.connect(self._on_collapse_finished)
        self.animation.start()

    def _on_collapse_finished(self):
        if not self.is_expanded:
            self.body_container.setVisible(False)

    def start_edit(self):
        self.is_editing = True
        self.text_editor.setPlainText(self.data.get("content", ""))
        self.text_editor.setVisible(True)
        self.body_label.setVisible(False)

        self.edit_btn.setVisible(False)
        self.important_btn.setVisible(False)
        self.color_btn.setVisible(False)
        self.reminder_btn.setVisible(False)
        self.export_btn.setVisible(False)
        self.delete_btn.setVisible(False)

        self.save_btn.setVisible(True)
        self.cancel_btn.setVisible(True)
        
        self.text_editor.adjust_height()

    def save_edit(self):
        new_content = self.text_editor.toPlainText()
        self.data["content"] = new_content
        
        self.is_editing = False
        self.text_editor.setVisible(False)
        self.body_label.setVisible(True)

        self.edit_btn.setVisible(True)
        self.important_btn.setVisible(True)
        self.color_btn.setVisible(True)
        self.reminder_btn.setVisible(True)
        self.export_btn.setVisible(True)
        self.delete_btn.setVisible(True)

        self.save_btn.setVisible(False)
        self.cancel_btn.setVisible(False)

        self.update_content_display()
        self.note_updated.emit(self.data["id"], self.data)

    def cancel_edit(self):
        self.is_editing = False
        self.text_editor.setVisible(False)
        self.body_label.setVisible(True)

        self.edit_btn.setVisible(True)
        self.important_btn.setVisible(True)
        self.color_btn.setVisible(True)
        self.reminder_btn.setVisible(True)
        self.export_btn.setVisible(True)
        self.delete_btn.setVisible(True)

        self.save_btn.setVisible(False)
        self.cancel_btn.setVisible(False)
        
        self.update_layout_size()

    def toggle_important(self):
        self.data["is_important"] = not self.data.get("is_important", False)
        self.update_content_display()
        self.update_style()
        self.note_updated.emit(self.data["id"], self.data)
        self.parent_list.re_render_notes()

    def toggle_color_panel(self):
        self.color_panel.setVisible(not self.color_panel.isVisible())
        self.update_layout_size()

    def change_color(self, hex_color):
        self.data["frame_color"] = hex_color
        self.update_style()
        self.note_updated.emit(self.data["id"], self.data)
        self.color_panel.setVisible(False)
        self.update_layout_size()

    def pick_custom_color(self):
        current_color = QColor(self.data.get("frame_color", "#8e8e93"))
        color = QColorDialog.getColor(current_color, self, "Pick Custom Frame Color")
        if color.isValid():
            self.change_color(color.name())

    def toggle_reminder_editor(self):
        self.reminder_editor.setVisible(not self.reminder_editor.isVisible())
        rem_time = self.data.get("reminder_time")
        if rem_time:
            self.reminder_dt.setDateTime(datetime.fromisoformat(rem_time))
        else:
            self.reminder_dt.setDateTime(datetime.now())
        self.update_layout_size()

    def save_reminder(self):
        dt = self.reminder_dt.dateTime().toPyDateTime()
        self.data["reminder_time"] = dt.isoformat()
        self.update_content_display()
        self.note_updated.emit(self.data["id"], self.data)
        self.reminder_editor.setVisible(False)
        self.update_layout_size()

    def clear_reminder(self):
        self.data["reminder_time"] = None
        self.update_content_display()
        self.note_updated.emit(self.data["id"], self.data)
        self.reminder_editor.setVisible(False)
        self.update_layout_size()

    def export_note_markdown(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Note to Markdown", 
            f"{self.header_label.text().replace(' ', '_')}.md", 
            "Markdown Files (*.md)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {self.header_label.text()}\n\n")
                    lines = self.data["content"].split('\n')
                    body_content = "\n".join(lines[1:]) if len(lines) > 1 else ""
                    f.write(body_content)
                self.parent_list.parent_window.show_in_app_notification("Exported note successfully!")
            except Exception as e:
                self.parent_list.parent_window.show_in_app_notification(f"Export failed: {e}")

    def delete_note(self):
        self.note_deleted.emit(self.data["id"])

# Custom Note List Widget
class NoteListWidget(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.dragged_widget = None
        
        self.list_layout = QVBoxLayout(self)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.list_layout.setSpacing(10)
        self.list_layout.setContentsMargins(6, 6, 6, 6)
        
        self.setAcceptDrops(True)
        self.setStyleSheet("background-color: transparent;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if not self.dragged_widget:
            return
            
        event.acceptProposedAction()
        
        y = event.position().y()
        new_index = 0
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if widget and widget != self.dragged_widget:
                widget_y = widget.geometry().y()
                widget_h = widget.geometry().height()
                if y > widget_y + widget_h / 2:
                    new_index = i + 1
                else:
                    break
        
        current_index = self.list_layout.indexOf(self.dragged_widget)
        if current_index != -1 and current_index != new_index:
            if new_index > current_index:
                new_index -= 1
            self.list_layout.removeWidget(self.dragged_widget)
            self.list_layout.insertWidget(new_index, self.dragged_widget)

    def dropEvent(self, event):
        event.acceptProposedAction()

    def save_order_after_drag(self):
        widgets = []
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, NoteItem):
                widgets.append(widget)
        
        new_notes_data = []
        for idx, widget in enumerate(widgets):
            widget.data["order_index"] = idx
            new_notes_data.append(widget.data)
            
        was_important_count = sum(1 for n in new_notes_data if n.get("is_important", False))
        
        for idx, note in enumerate(new_notes_data):
            if idx < was_important_count:
                if not note.get("is_important", False):
                    note["is_important"] = True
                    for w in widgets:
                        if w.data["id"] == note["id"]:
                            w.data["is_important"] = True
                            w.update_content_display()
                            w.update_style()
            else:
                if note.get("is_important", False):
                    note["is_important"] = False
                    for w in widgets:
                        if w.data["id"] == note["id"]:
                            w.data["is_important"] = False
                            w.update_content_display()
                            w.update_style()

        self.parent_window.notes_db = new_notes_data
        self.parent_window.save_notes_to_file()
        self.re_render_notes()

    def expand_note(self, current_note):
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, NoteItem):
                if widget == current_note:
                    widget.expand()
                else:
                    widget.collapse()

    def collapse_all(self):
        for i in range(self.list_layout.count()):
            widget = self.list_layout.itemAt(i).widget()
            if isinstance(widget, NoteItem):
                widget.collapse()

    def re_render_notes(self):
        self.parent_window.load_and_render_notes()


# In-App Notification
class InAppNotification(QFrame):
    def __init__(self, message, parent):
        super().__init__(parent)
        self.setObjectName("Notification")
        self.setStyleSheet("""
            #Notification {
                background-color: #007aff;
                border-radius: 6px;
                padding: 10px 16px;
            }
            QLabel {
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                background-color: transparent;
            }
        """)
        
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(10)
        self.shadow.setColor(QColor(0, 0, 0, 150))
        self.shadow.setOffset(0, 4)
        self.setGraphicsEffect(self.shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        
        self.label = QLabel(message)
        layout.addWidget(self.label)
        
        self.adjustSize()
        self.hide()

    def show_notification(self):
        parent_rect = self.parent().rect()
        self.move(parent_rect.width() - self.width() - 20, 50)
        self.show()
        
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, self.fade_out)

    def fade_out(self):
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()


# Main Application Window (Frameless & Custom Resizable)
class ReminderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.notes_db = []
        self.search_query = ""
        self.drag_position = None
        self.resize_dir = None
        
        # Rename to "Quick Notes"
        self.setWindowTitle("Quick Notes")
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(450, 700)
        self.setMinimumSize(360, 500)
        
        self.setMouseTracking(True)
        
        # Set Program Icon
        self.setup_app_icon()
        
        # Global Ultra Dark Theme QSS Stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0c0c0f;
            }
            QWidget#CentralWidget {
                background-color: #0c0c0f;
                border: 1px solid #2a2a35;
                border-radius: 12px;
            }
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
                border: none;
                background-color: #060608;
                border-radius: 8px;
            }
            QScrollBar:vertical {
                border: none;
                background: #0c0c0f;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #3d3d52;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4e4e66;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: #060608;
                color: #ffffff;
                border: 1px solid #2a2a35;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #007aff;
            }
            
            /* Global QPushButton & QToolButton styling (mainly for dialog windows like QColorDialog, QFileDialog) */
            QPushButton {
                background-color: #1a1a24;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c2c3e;
                border: 1px solid #007aff;
            }
            QToolButton {
                background-color: #1a1a24;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                font-weight: bold;
            }
            QToolButton:hover {
                background-color: #2c2c3e;
                border: 1px solid #007aff;
            }
            
            /* QToolTip styling to prevent black-on-black tooltip texts */
            QToolTip {
                background-color: #1a1a24;
                color: #ffffff;
                border: 1px solid #3d3d5c;
                border-radius: 4px;
                padding: 4px;
            }
            
            /* QCalendarWidget Beautiful Dark Theme */
            QCalendarWidget {
                border: 1px solid #2a2a35;
                border-radius: 8px;
            }
            QCalendarWidget QWidget {
                alternate-background-color: #121216;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: #14141a;
                border-bottom: 1px solid #2a2a35;
            }
            QCalendarWidget QToolButton {
                color: #ffffff;
                background-color: transparent;
                border: none;
                font-weight: bold;
            }
            QCalendarWidget QToolButton:hover {
                background-color: #2c2c3e;
                border-radius: 4px;
            }
            QCalendarWidget QAbstractItemView {
                background-color: #15151e;
                color: #ffffff;
                selection-background-color: #007aff;
                selection-color: #ffffff;
                outline: 0;
            }
            QCalendarWidget QAbstractItemView:enabled {
                color: #ffffff;
            }
            QCalendarWidget QAbstractItemView:disabled {
                color: #444444;
            }
            
            /* QColorDialog & generic dialog windows dark theme styling */
            QColorDialog, QFileDialog, QDialog {
                background-color: #14141a;
                color: #ffffff;
            }
            QColorDialog QLabel, QFileDialog QLabel, QDialog QLabel {
                color: #ffffff;
                background-color: transparent;
            }
            QColorDialog QAbstractItemView, QFileDialog QAbstractItemView, QDialog QAbstractItemView {
                background-color: #15151e;
                color: #ffffff;
            }
        """)

        self.init_ui()
        self.setup_system_tray()
        
        self.load_notes_from_file()
        self.load_and_render_notes()
        self.start_reminder_worker()

    def setup_app_icon(self):
        # Resolve path to bundled resource directory or local script directory
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        self.icon_path = os.path.join(base_path, "icon.png")
        if os.path.exists(self.icon_path):
            self.setWindowIcon(QIcon(self.icon_path))
        elif os.path.exists("icon.png"):
            self.setWindowIcon(QIcon("icon.png"))

    def init_ui(self):
        self.central_widget = QWidget()
        self.central_widget.setObjectName("CentralWidget")
        self.central_widget.setMouseTracking(True)
        self.setCentralWidget(self.central_widget)
        
        self.window_layout = QVBoxLayout(self.central_widget)
        self.window_layout.setContentsMargins(6, 6, 6, 6)
        self.window_layout.setSpacing(0)

        # Custom Title Bar
        self.title_bar = QWidget()
        self.title_bar.setObjectName("TitleBar")
        self.title_bar.setFixedHeight(40)
        self.title_bar.setMouseTracking(True)
        self.title_bar.setStyleSheet("""
            QWidget#TitleBar {
                background-color: #14141a;
                border-top-left-radius: 11px;
                border-top-right-radius: 11px;
                border-bottom: 1px solid #22222c;
            }
            QLabel {
                background-color: transparent;
            }
        """)
        
        self.title_layout = QHBoxLayout(self.title_bar)
        self.title_layout.setContentsMargins(14, 0, 10, 0)
        self.title_layout.setSpacing(10)

        # Renamed Title
        self.app_title = QLabel("📌 Quick Notes")
        self.app_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 12px;")
        self.title_layout.addWidget(self.app_title)
        self.title_layout.addStretch()

        self.min_btn = QPushButton("─")
        self.min_btn.setObjectName("TitleMinButton")
        self.min_btn.setFixedSize(28, 28)
        self.min_btn.setStyleSheet("""
            QPushButton#TitleMinButton {
                background: transparent;
                color: #d1d1d6;
                border: none;
                border-radius: 14px;
                font-weight: bold;
                font-size: 12px;
                padding: 0px;
            }
            QPushButton#TitleMinButton:hover {
                background-color: #2c2c3e;
                color: #ffffff;
                border: none;
            }
        """)
        self.min_btn.clicked.connect(self.showMinimized)
        self.title_layout.addWidget(self.min_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("TitleCloseButton")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet("""
            QPushButton#TitleCloseButton {
                background: transparent;
                color: #d1d1d6;
                border: none;
                border-radius: 14px;
                font-weight: bold;
                font-size: 12px;
                padding: 0px;
            }
            QPushButton#TitleCloseButton:hover {
                background-color: #ff5f56;
                color: #ffffff;
                border: none;
            }
        """)
        self.close_btn.clicked.connect(self.close)
        self.title_layout.addWidget(self.close_btn)

        self.window_layout.addWidget(self.title_bar)

        # Main Client Content Area
        self.content_widget = QWidget()
        self.content_widget.setMouseTracking(True)
        self.main_layout = QVBoxLayout(self.content_widget)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(12)

        self.header_title_layout = QHBoxLayout()
        self.header_title_layout.setContentsMargins(0, 0, 0, 0)
        
        # Renamed section
        self.section_title = QLabel("Quick Notes")
        self.section_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold; background-color: transparent;")
        self.header_title_layout.addWidget(self.section_title)
        self.header_title_layout.addStretch()

        self.export_all_btn = QPushButton("Export All")
        self.export_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #161622;
                color: #ffffff;
                border: 1px solid #2a2a35;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2a2a3d; }
        """)
        self.export_all_btn.clicked.connect(self.export_all_markdown)
        self.header_title_layout.addWidget(self.export_all_btn)
        self.main_layout.addLayout(self.header_title_layout)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search notes...")
        self.search_bar.textChanged.connect(self.handle_search)
        self.main_layout.addWidget(self.search_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.list_widget = NoteListWidget(self)
        self.scroll.setWidget(self.list_widget)
        self.main_layout.addWidget(self.scroll)

        self.add_note_btn = QPushButton("+ Create New Note")
        self.add_note_btn.setStyleSheet("""
            QPushButton {
                background-color: #007aff;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0069d9;
            }
        """)
        self.add_note_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_note_btn.clicked.connect(self.create_new_note)
        self.main_layout.addWidget(self.add_note_btn)

        self.window_layout.addWidget(self.content_widget)

    # Custom Resizing Mechanics
    def get_resize_direction(self, pos):
        w = self.width()
        h = self.height()
        x = pos.x()
        y = pos.y()
        
        direction = ""
        if y < RESIZE_MARGIN:
            direction += "top"
        elif y > h - RESIZE_MARGIN:
            direction += "bottom"
            
        if x < RESIZE_MARGIN:
            direction += "left"
        elif x > w - RESIZE_MARGIN:
            direction += "right"
            
        return direction

    def update_cursor_shape(self, direction):
        if direction in ["topleft", "bottomright"]:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif direction in ["topright", "bottomleft"]:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif direction in ["left", "right"]:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif direction in ["top", "bottom"]:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            local_pos = event.position().toPoint()
            direction = self.get_resize_direction(local_pos)
            
            if direction:
                self.resize_dir = direction
                self.drag_start_global = event.globalPosition().toPoint()
                self.initial_geom = self.geometry()
                event.accept()
                return
                
            title_bar_pos = self.title_bar.mapFrom(self, event.pos())
            if self.title_bar.rect().contains(title_bar_pos):
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
                
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        global_pos = event.globalPosition().toPoint()
        local_pos = event.position().toPoint()
        
        if self.resize_dir:
            delta = global_pos - self.drag_start_global
            new_geom = QRect(self.initial_geom)
            
            if "top" in self.resize_dir:
                new_geom.setTop(self.initial_geom.top() + delta.y())
            elif "bottom" in self.resize_dir:
                new_geom.setBottom(self.initial_geom.bottom() + delta.y())
                
            if "left" in self.resize_dir:
                new_geom.setLeft(self.initial_geom.left() + delta.x())
            elif "right" in self.resize_dir:
                new_geom.setRight(self.initial_geom.right() + delta.x())
            
            if new_geom.width() >= self.minimumWidth() and new_geom.height() >= self.minimumHeight():
                self.setGeometry(new_geom)
            event.accept()
            return

        if hasattr(self, 'drag_position') and self.drag_position is not None:
            self.move(global_pos - self.drag_position)
            event.accept()
            return
            
        direction = self.get_resize_direction(local_pos)
        self.update_cursor_shape(direction)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_position = None
        self.resize_dir = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def setup_system_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists(self.icon_path):
            self.tray_icon.setIcon(QIcon(self.icon_path))
        elif os.path.exists("icon.png"):
            self.tray_icon.setIcon(QIcon("icon.png"))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QApplication.style().StandardPixmap.SP_ComputerIcon))
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.showNormal)
        
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(QApplication.instance().quit)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def start_reminder_worker(self):
        self.reminder_worker = ReminderWorker(self)
        self.reminder_worker.reminder_triggered.connect(self.handle_triggered_reminder)
        self.reminder_worker.set_reminders(self.notes_db)
        self.reminder_worker.start()

    def handle_triggered_reminder(self, note_data):
        title = note_data.get("content", "").split('\n')[0]
        msg = "Reminder Alert!"
        
        self.tray_icon.showMessage(
            f"Note Reminder: {title}", 
            msg, 
            QSystemTrayIcon.MessageIcon.Information, 
            5000
        )
        
        self.show_in_app_notification(f"🔔 Reminder: {title}")

        for note in self.notes_db:
            if note["id"] == note_data["id"]:
                note["reminder_time"] = None
                break
        
        self.save_notes_to_file()
        self.list_widget.re_render_notes()

    def show_in_app_notification(self, message):
        toast = InAppNotification(message, self.central_widget)
        toast.show_notification()

    def is_any_note_editing(self):
        for i in range(self.list_widget.list_layout.count()):
            widget = self.list_widget.list_layout.itemAt(i).widget()
            if isinstance(widget, NoteItem) and widget.is_editing:
                return True
        return False

    def load_notes_from_file(self):
        if not os.path.exists(STORAGE_FILE):
            self.notes_db = [
                {
                    "id": "dummy-1",
                    "content": "Welcome to Quick Notes!\nHover over a note to expand it.\nClick 'Pin' to keep important notes at the top.\nDrag and drop items to reorder them manually.",
                    "is_important": True,
                    "frame_color": "#007aff",
                    "reminder_time": None,
                    "order_index": 0
                },
                {
                    "id": "dummy-2",
                    "content": "Create a New Note\nClick the large blue button at the bottom to write a custom reminder.",
                    "is_important": False,
                    "frame_color": "#27c93f",
                    "reminder_time": None,
                    "order_index": 1
                }
            ]
            self.save_notes_to_file()
        else:
            try:
                with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
                    self.notes_db = json.load(f)
            except Exception as e:
                self.notes_db = []
                self.show_in_app_notification("Failed to load notes.json!")

    def save_notes_to_file(self):
        try:
            with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.notes_db, f, indent=2)
            if hasattr(self, 'reminder_worker'):
                self.reminder_worker.set_reminders(self.notes_db)
        except Exception as e:
            self.show_in_app_notification(f"Failed to save notes: {e}")

    def load_and_render_notes(self):
        while self.list_widget.list_layout.count():
            item = self.list_widget.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        sorted_notes = sorted(
            self.notes_db, 
            key=lambda x: (not x.get("is_important", False), x.get("order_index", 0))
        )

        for note in sorted_notes:
            if self.search_query:
                if self.search_query.lower() not in note.get("content", "").lower():
                    continue

            item_widget = NoteItem(note, self.list_widget)
            item_widget.note_updated.connect(self.handle_note_update)
            item_widget.note_deleted.connect(self.handle_note_deletion)
            self.list_widget.list_layout.addWidget(item_widget)

    def handle_search(self, text):
        self.search_query = text
        self.load_and_render_notes()

    def create_new_note(self):
        if self.is_any_note_editing():
            self.show_in_app_notification("Please save current edits first!")
            return

        new_id = str(uuid.uuid4())
        new_note = {
            "id": new_id,
            "content": "New Note Header\nAdd details here.",
            "is_important": False,
            "frame_color": "#8e8e93",
            "reminder_time": None,
            "order_index": len(self.notes_db)
        }
        
        self.notes_db.append(new_note)
        self.save_notes_to_file()
        self.load_and_render_notes()

        for i in range(self.list_widget.list_layout.count()):
            widget = self.list_widget.list_layout.itemAt(i).widget()
            if isinstance(widget, NoteItem) and widget.data["id"] == new_id:
                widget.expand()
                widget.start_edit()
                break

    def handle_note_update(self, note_id, updated_data):
        for idx, note in enumerate(self.notes_db):
            if note["id"] == note_id:
                self.notes_db[idx] = updated_data
                break
        self.save_notes_to_file()

    def handle_note_deletion(self, note_id):
        self.notes_db = [n for n in self.notes_db if n["id"] != note_id]
        for idx, note in enumerate(self.notes_db):
            note["order_index"] = idx
        self.save_notes_to_file()
        self.load_and_render_notes()
        self.show_in_app_notification("Note deleted.")

    def export_all_markdown(self):
        if not self.notes_db:
            self.show_in_app_notification("No notes to export!")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export All Notes to Markdown", 
            "All_Notes.md", 
            "Markdown Files (*.md)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("# Quick Notes Backup\n\n")
                    sorted_notes = sorted(
                        self.notes_db, 
                        key=lambda x: (not x.get("is_important", False), x.get("order_index", 0))
                    )
                    for note in sorted_notes:
                        content = note.get("content", "")
                        lines = content.split('\n')
                        header = lines[0] if lines else "Untitled Note"
                        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
                        
                        f.write(f"## {header}\n")
                        if note.get("is_important"):
                            f.write("*(Pinned)*\n")
                        if note.get("reminder_time"):
                            f.write(f"**Reminder:** {note.get('reminder_time').replace('T', ' ')}\n")
                        f.write("\n")
                        f.write(body)
                        f.write("\n\n---\n\n")
                self.show_in_app_notification("All notes exported successfully!")
            except Exception as e:
                self.show_in_app_notification(f"Export failed: {e}")

    def closeEvent(self, event):
        if hasattr(self, 'reminder_worker'):
            self.reminder_worker.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ReminderApp()
    window.show()
    sys.exit(app.exec())
