

## Project Specification: Standalone Accordion Reminder App

### 1. Project Overview & Architecture

- **Target OS:** Windows 11 (Standalone Executable)

- **Tech Stack:** Python 3.11+, PyQt6 (or PySide6), PyInstaller (for standalone `.exe` bundling)

- **Storage:** Local `notes.json` file in the application directory. No external dependencies or DB instances required.

### 2. Core UI Component Behavior (The Accordion List)

The main window consists of a vertically scrollable list of notes acting like an advanced accordion panel.

| **Feature / Action**  | **Expected Behavior**                                                                                     |
| --------------------- | --------------------------------------------------------------------------------------------------------- |
| **Idle State**        | Only the **first line (Header)** of each note is visible in a compact list view.                          |
| **Mouse Hover (On)**  | Hovering over a note header automatically **expands** that note's body and **collapses** all other notes. |
| **Mouse Scroll**      | The list scrolls vertically via the mouse wheel or by dragging the scrollbar.                             |
| **Manual Reordering** | Notes can be manually reordered by clicking and **dragging-and-dropping** them up or down the list.       |

### 3. Note Creation & Editing Dynamics

When a note is clicked for editing, or when a new note is created:

- **Sizing & Expansion:** The text area expands to a default editing size. As the user types, the box dynamically expands vertically until it hits a `max-height` (e.g., 10 lines). Once `max-height` is breached, an internal scrollbar appears.

- **Header Generation:** The first line of the input text is automatically parsed and saved as the note's header.

- **Important Flag:** A checkbox or toggle button to mark the note as "Important".

- **Custom Framing:** A color picker or dropdown to select a custom border/frame color for that specific note.

### 4. Logic, Sorting & Reminders

Data handling must follow these strict prioritization and storage rules:

```
[Default Sorting Logic]
1. Important Notes (Pinned to top)
2. Manually Dragged Order (User preference)
3. Standard Notes
```

- **Reminder System:** Users can assign a date and time to a note. The app runs a background timer thread checking every second. When a reminder hits, it triggers a native Windows 11 toast notification or a non-blocking popup.

- **Markdown Export:** A button allowing the user to export the currently selected note (or all notes) into a clean `.md` file.

### 5. Data Schema (`notes.json`)

The application will read/write to a local JSON file structured as follows:

JSON

```
[
  {
    "id": "string-uuid",
    "content": "Header Line Here\nThis is the body of the note which contains details.",
    "is_important": true,
    "frame_color": "#FF5733",
    "reminder_time": "2026-06-16T10:00:00",
    "order_index": 0
  }
]
```

### 6. Code Blueprint (`main.py`)

This foundational Python script implements the dynamic hover expansion, custom borders, and JSON storage.

Python

```
import sys
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                             QTextEdit, QLabel, QScrollArea, QFrame)
from PyQt6.QtCore import Qt, QEvent

STORAGE_FILE = "notes.json"

class NoteItem(QFrame):
    def __init__(self, note_data, parent_list):
        super().__init__()
        self.data = note_data
        self.parent_list = parent_list
        self.init_ui()

    def init_ui(self):
        # Apply custom frame color from JSON
        color = self.data.get("frame_color", "#cccccc")
        self.setStyleSheet(f"QFrame {{ border: 2px solid {color}; border-radius: 5px; background: #ffffff; }}")

        self.layout = QVBoxLayout(self)

        # Header (First line)
        lines = self.data["content"].split('\n')
        self.header_label = QLabel(lines[0] if lines else "Untitled Note")
        self.header_label.setStyleSheet("border: none; font-weight: bold;")
        self.layout.addWidget(self.header_label)

        # Body (Hidden by default, expands to max-height)
        self.body_edit = QTextEdit()
        self.body_edit.setPlainText(self.data["content"])
        self.body_edit.setStyleSheet("border: none;")
        self.body_edit.setVisible(False)
        self.body_edit.setMaximumHeight(200) # Max lines constraint
        self.layout.addWidget(self.body_edit)

        # Enable hover tracking
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        # Hover expansion logic
        if event.type() == QEvent.Type.HoverEnter:
            self.parent_list.collapse_all_except(self)
            self.body_edit.setVisible(True)
        return super().eventFilter(obj, event)

    def collapse(self):
        self.body_edit.setVisible(False)

class ReminderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Standalone Accordion Reminders")
        self.resize(400, 600)
        self.init_ui()

    def init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # Scrollable Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.list_layout = QVBoxLayout(self.scroll_content)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll)

        self.notes_widgets = []
        self.load_and_render_notes()

    def load_and_render_notes(self):
        # Fallback dummy data if file doesn't exist
        if not os.path.exists(STORAGE_FILE):
            dummy_data = [
                {"id": "1", "content": "Important Meeting\nDiscuss project deadlines.", "is_important": True, "frame_color": "#FF0000"},
                {"id": "2", "content": "Buy Groceries\nMilk, Eggs, Bread.", "is_important": False, "frame_color": "#00FF00"}
            ]
            with open(STORAGE_FILE, 'w') as f:
                json.dump(dummy_data, f)

        with open(STORAGE_FILE, 'r') as f:
            notes = json.load(f)

        # Sort: Important first
        notes.sort(key=lambda x: x.get("is_important", False), reverse=True)

        for note in notes:
            item = NoteItem(note, self)
            self.list_layout.addWidget(item)
            self.notes_widgets.append(item)

    def collapse_all_except(self, current_item):
        for item in self.notes_widgets:
            if item != current_item:
                item.collapse()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ReminderApp()
    window.show()
    sys.exit(app.exec())
```

### 7. Compilation to Standalone `.exe`

To compile this into a single, independent executable file for Windows 11, run the following command in the project terminal:

Bash

```
pip install pyinstaller pyqt6
pyinstaller --noconsole --onefile main.py
```

The production-ready app will be generated inside the `dist/` directory as `main.exe`.
