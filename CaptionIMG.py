from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Iterable, List

from PIL import Image, ImageOps
from PIL.ImageQt import ImageQt

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStatusBar,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def natural_sort(paths: Iterable[str]) -> List[str]:
    """
    Natural sort by basename (so file2 < file10).
    """
    def convert(text: str):
        return int(text) if text.isdigit() else text.lower()

    _re = re.compile(r"([0-9]+)")

    def alphanum_key(p: str):
        base = os.path.basename(p)
        return [convert(c) for c in _re.split(base)]

    return sorted(paths, key=alphanum_key)


class CaptionIMGMain(QMainWindow):
    SUPPORTED_EXT = (".bmp", ".jpg", ".jpeg", ".png", ".webp", ".tiff")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CaptionIMG (PySide6)")
        self.resize(1200, 800)

        self.file_map: dict[str, Path] = {}
        self.current_image_name: str | None = None
        self.current_image_path: Path | None = None
        self.unsaved = False

        self._build_ui()
        self._connect_shortcuts()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # Left: list
        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(300)
        main_layout.addWidget(self.list_widget, stretch=0)

        # Right: image + caption area
        right_v = QVBoxLayout()
        main_layout.addLayout(right_v, stretch=1)

        self.image_label = QLabel(alignment=Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet("border: 1px solid #999;")
        right_v.addWidget(self.image_label, stretch=3)

        self.caption_edit = QTextEdit()
        self.caption_edit.setPlaceholderText("Enter image caption / description here...")
        right_v.addWidget(self.caption_edit, stretch=1)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Open Images")
        self.save_btn = QPushButton("Save Caption")
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.save_btn)
        right_v.addLayout(btn_row)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("No images loaded")

        # Connections
        self.open_btn.clicked.connect(self.open_images)
        self.save_btn.clicked.connect(self.save_caption)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.caption_edit.textChanged.connect(self._on_text_changed)

    def _connect_shortcuts(self) -> None:
        # Ctrl+S to save
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_caption)
        # Left/Right navigation
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self._navigate(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self._navigate(1))

    def open_images(self) -> None:
        try:
            filters = "Images (*.bmp *.jpg *.jpeg *.png *.webp *.tiff);;All Files (*)"
            selected, _ = QFileDialog.getOpenFileNames(self, "Select images", str(Path.home()), filters)
            if not selected:
                return

            selected = natural_sort(selected)
            self.file_map.clear()
            self.list_widget.clear()

            for fp in selected:
                p = Path(fp)
                name = p.name
                self.file_map[name] = p
                self.list_widget.addItem(QListWidgetItem(name))

            self.status.showMessage(f"Loaded {len(selected)} image(s)")
            if self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
        except Exception as exc:
            logging.exception("Error while opening images")
            QMessageBox.critical(self, "Error", f"Failed to open images:\n{exc}")

    def _on_selection_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        try:
            if previous and self.unsaved:
                # Ask to save before switching
                resp = QMessageBox.question(
                    self,
                    "Unsaved changes",
                    "You have unsaved captions for the current image. Save before switching?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                )
                if resp == QMessageBox.Cancel:
                    # revert selection back to previous
                    prev_row = self.list_widget.row(previous)
                    self.list_widget.blockSignals(True)
                    self.list_widget.setCurrentRow(prev_row)
                    self.list_widget.blockSignals(False)
                    return
                elif resp == QMessageBox.Yes:
                    if not self.save_caption():
                        # If save failed, revert
                        prev_row = self.list_widget.row(previous)
                        self.list_widget.blockSignals(True)
                        self.list_widget.setCurrentRow(prev_row)
                        self.list_widget.blockSignals(False)
                        return
                else:
                    # Discard changes
                    self.unsaved = False

            if not current:
                self._clear_image_and_caption()
                return

            name = current.text()
            path = self.file_map.get(name)
            if not path:
                return

            self.current_image_name = name
            self.current_image_path = path
            self._display_image(path)
            self._load_caption(path)
            self.unsaved = False
        except Exception:
            logging.exception("Error on selection change")

    def _display_image(self, path: Path) -> None:
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                # scale to a reasonable size for display while preserving aspect
                screen_size = QApplication.primaryScreen().size()
                max_w = int(screen_size.width() * 0.5)
                max_h = int(screen_size.height() * 0.5)
                im.thumbnail((max_w, max_h), Image.LANCZOS)

                qim = ImageQt(im)  # ImageQt returns a QImage compatible object
                pix = QPixmap.fromImage(qim)

                # Further scale to the label size while keeping aspect ratio
                lbl_size = self.image_label.size()
                if not lbl_size.isEmpty():
                    pix = pix.scaled(lbl_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                self.image_label.setPixmap(pix)
                self.status.showMessage(f"{path.name} — {path}")
        except Exception:
            logging.exception("Unable to display image")
            QMessageBox.warning(self, "Warning", f"Could not open image:\n{path}")

    def _load_caption(self, path: Path) -> None:
        caption_file = path.with_suffix(".txt")
        if caption_file.exists():
            try:
                text = caption_file.read_text(encoding="utf-8")
            except Exception:
                logging.exception("Failed to read caption")
                QMessageBox.warning(self, "Warning", f"Failed to read caption file:\n{caption_file}")
                text = ""
        else:
            text = ""

        self.caption_edit.blockSignals(True)
        self.caption_edit.setPlainText(text)
        self.caption_edit.blockSignals(False)
        self.unsaved = False

    def save_caption(self) -> bool:
        """
        Save current caption. Returns True on success.
        """
        if not self.current_image_path:
            QMessageBox.information(self, "No image", "No image selected to save caption for.")
            return False
        caption_file = self.current_image_path.with_suffix(".txt")
        text = self.caption_edit.toPlainText()
        try:
            caption_file.write_text(text, encoding="utf-8")
            self.unsaved = False
            QMessageBox.information(self, "Saved", f"Caption saved:\n{caption_file}")
            return True
        except Exception:
            logging.exception("Failed to save caption")
            QMessageBox.critical(self, "Error", "There was an error while saving the caption.")
            return False

    def _on_text_changed(self) -> None:
        self.unsaved = True

    def _navigate(self, step: int) -> None:
        count = self.list_widget.count()
        if count == 0:
            return
        current_row = self.list_widget.currentRow()
        new_row = max(0, min(current_row + step, count - 1))
        if new_row != current_row:
            self.list_widget.setCurrentRow(new_row)

    def _clear_image_and_caption(self) -> None:
        self.image_label.clear()
        self.caption_edit.clear()
        self.current_image_name = None
        self.current_image_path = None
        self.status.showMessage("No image selected")
        self.unsaved = False


def main() -> None:
    app = QApplication([])
    win = CaptionIMGMain()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
