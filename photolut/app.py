"""PhotoLUT window: pick photos, choose a look and strength, preview, batch export."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPainter, QPen, QPixmap, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from . import __version__
from .lut import Cube, discover
from .photos import inspect, is_jpeg, load_rgb, process

PREVIEW_SIDE = 1600


def bundled_looks() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "looks"


def user_looks() -> Path:
    root = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "PhotoLUT" / "looks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_output() -> Path:
    return Path.home() / "Pictures" / "PhotoLUT"


def to_pixmap(rgb: np.ndarray) -> QPixmap:
    data = np.ascontiguousarray(np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8))
    h, w, _ = data.shape
    image = QImage(data.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


class Preview(QLabel):
    """Shows the original on the left of the split line and the look on the right."""

    def __init__(self):
        super().__init__("拖入照片或按「加入照片」開始")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#1e1e1e;color:#aaa;")
        self.before = self.after = None
        self.split = 0.5

    def show_images(self, before: QPixmap | None, after: QPixmap | None):
        self.before, self.after = before, after
        self.update()

    def set_split(self, value: float):
        self.split = value
        self.update()

    def paintEvent(self, event):
        if self.before is None or self.after is None:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        scaled = self.before.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x0 = (self.width() - scaled.width()) // 2
        y0 = (self.height() - scaled.height()) // 2
        cut = int(scaled.width() * self.split)
        src_cut = int(self.before.width() * self.split)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(x0, y0, cut, scaled.height(), self.before, 0, 0, src_cut, self.before.height())
        painter.drawPixmap(x0 + cut, y0, scaled.width() - cut, scaled.height(), self.after,
                           src_cut, 0, self.after.width() - src_cut, self.after.height())
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawLine(x0 + cut, y0, x0 + cut, y0 + scaled.height())
        painter.drawText(x0 + 8, y0 + 20, "原圖")
        painter.drawText(x0 + scaled.width() - 50, y0 + 20, "套用後")
        painter.end()


class Worker(QObject):
    progress = Signal(int, str)
    finished = Signal(int, list)

    def __init__(self, files, cube, strength, folder, suffix, quality):
        super().__init__()
        self.args = (files, cube, strength, folder, suffix, quality)
        self.cancelled = False

    def run(self):
        files, cube, strength, folder, suffix, quality = self.args
        done, errors = 0, []
        self.progress.emit(-1, "準備風格查找表")
        table = cube.table8(strength)
        for index, path in enumerate(files):
            if self.cancelled:
                break
            self.progress.emit(index, Path(path).name)
            try:
                process(path, cube, strength, folder, suffix, quality, table)
                done += 1
            except Exception as exc:  # report every file, keep going
                errors.append(f"{Path(path).name}：{exc}")
        self.finished.emit(done, errors)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PhotoLUT 照片風格套用 {__version__}")
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        self.settings = QSettings("PhotoLUT", "PhotoLUT")
        self.cache: dict[str, np.ndarray] = {}
        self.thread = self.worker = None

        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.currentItemChanged.connect(lambda *_: self.refresh_preview())
        add_files = QPushButton("加入照片…")
        add_files.clicked.connect(self.pick_files)
        add_folder = QPushButton("加入資料夾…")
        add_folder.clicked.connect(self.pick_folder)
        remove = QPushButton("移除")
        remove.clicked.connect(self.remove_selected)
        clear = QPushButton("清空")
        clear.clicked.connect(self.clear_files)
        buttons = QHBoxLayout()
        for b in (add_files, add_folder, remove, clear):
            buttons.addWidget(b)
        left = QVBoxLayout()
        left.addWidget(QLabel("照片（只支援 JPEG，原檔不會被修改）"))
        left.addWidget(self.files)
        left.addLayout(buttons)
        left_box = QWidget()
        left_box.setLayout(left)

        self.preview = Preview()
        self.split = QSlider(Qt.Orientation.Horizontal)
        self.split.setRange(0, 100)
        self.split.setValue(50)
        self.split.valueChanged.connect(lambda v: self.preview.set_split(v / 100))
        right = QVBoxLayout()
        right.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("前後對比位置"))
        row.addWidget(self.split)
        right.addLayout(row)
        right_box = QWidget()
        right_box.setLayout(right)

        splitter = QSplitter()
        splitter.addWidget(left_box)
        splitter.addWidget(right_box)
        splitter.setSizes([360, 920])

        self.look = QComboBox()
        self.look.currentIndexChanged.connect(self.look_changed)
        reload_looks = QPushButton("重新載入")
        reload_looks.clicked.connect(self.load_looks)
        open_looks = QPushButton("開啟風格資料夾")
        open_looks.setToolTip("把 .cube 檔放進這個資料夾，再按「重新載入」")
        open_looks.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_looks()))))
        look_row = QHBoxLayout()
        look_row.addWidget(self.look, 1)
        look_row.addWidget(reload_looks)
        look_row.addWidget(open_looks)

        self.strength = QSlider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength_label = QLabel()
        self.strength.valueChanged.connect(self.strength_changed)
        strength_row = QHBoxLayout()
        strength_row.addWidget(self.strength, 1)
        strength_row.addWidget(self.strength_label)

        self.quality = QSpinBox()
        self.quality.setRange(80, 100)
        self.quality.setValue(int(self.settings.value("quality", 95)))
        self.suffix = QLineEdit()
        self.output = QLineEdit(str(self.settings.value("output", str(default_output()))))
        browse = QPushButton("選擇…")
        browse.clicked.connect(self.pick_output)
        open_out = QPushButton("開啟")
        open_out.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.output.text())))
        out_row = QHBoxLayout()
        out_row.addWidget(self.output, 1)
        out_row.addWidget(browse)
        out_row.addWidget(open_out)

        form = QFormLayout()
        form.addRow("風格", look_row)
        form.addRow("強度", strength_row)
        form.addRow("JPEG 品質", self.quality)
        form.addRow("檔名後綴", self.suffix)
        form.addRow("輸出資料夾", out_row)
        settings_box = QGroupBox("設定")
        settings_box.setLayout(form)

        self.start = QPushButton("開始處理")
        self.start.setMinimumHeight(36)
        self.start.clicked.connect(self.start_batch)
        self.cancel = QPushButton("取消")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_batch)
        self.bar = QProgressBar()
        self.status = QLabel("提示：相機請用 ST 創意外觀（參數全部 0）、色彩空間 sRGB 拍攝的 JPEG")
        run_row = QHBoxLayout()
        run_row.addWidget(self.start)
        run_row.addWidget(self.cancel)
        run_row.addWidget(self.bar, 1)

        root = QVBoxLayout()
        root.addWidget(splitter, 1)
        root.addWidget(settings_box)
        root.addLayout(run_row)
        root.addWidget(self.status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(120)
        self.debounce.timeout.connect(self.refresh_preview)
        self.looks: list[Cube] = []
        self.strength.setValue(int(self.settings.value("strength", 50)))
        self.load_looks()

    # ---- looks ----
    def load_looks(self):
        previous = self.look.currentText() or self.settings.value("look", "")
        seen, looks = set(), []
        for cube in discover(bundled_looks()) + discover(user_looks()):
            if cube.title not in seen:
                seen.add(cube.title)
                looks.append(cube)
        self.looks = looks
        self.look.blockSignals(True)
        self.look.clear()
        for cube in looks:
            self.look.addItem(cube.title)
        index = self.look.findText(previous)
        self.look.setCurrentIndex(index if index >= 0 else 0)
        self.look.blockSignals(False)
        self.look_changed()
        if not looks:
            self.status.setText("找不到任何 .cube 風格檔，請按「開啟風格資料夾」放入檔案")

    def current_cube(self) -> Cube | None:
        i = self.look.currentIndex()
        return self.looks[i] if 0 <= i < len(self.looks) else None

    def look_changed(self, *_):
        cube = self.current_cube()
        if cube is not None:
            self.suffix.setText(cube.title.replace(" ", "_"))
        self.debounce.start()

    def strength_changed(self, value):
        self.strength_label.setText(f"{value}%")
        self.debounce.start()

    # ---- files ----
    def add_paths(self, paths):
        existing = {self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())}
        added = 0
        for path in paths:
            path = Path(path)
            candidates = sorted(p for p in path.iterdir() if p.is_file()) if path.is_dir() else [path]
            for p in candidates:
                if not is_jpeg(p) or str(p) in existing:
                    continue
                try:
                    info = inspect(p)
                except Exception as exc:
                    self.status.setText(f"無法讀取 {p.name}：{exc}")
                    continue
                item = QListWidgetItem(("⚠ " if info.warnings else "") + p.name)
                item.setData(Qt.ItemDataRole.UserRole, str(p))
                item.setToolTip("\n".join([f"{info.width}×{info.height}", *info.warnings]))
                self.files.addItem(item)
                existing.add(str(p))
                added += 1
        if added and self.files.currentRow() < 0:
            self.files.setCurrentRow(0)
        self.status.setText(f"已加入 {added} 張，共 {self.files.count()} 張")

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇照片", "", "JPEG (*.jpg *.jpeg *.JPG *.JPEG)")
        self.add_paths(paths)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇資料夾")
        if folder:
            self.add_paths([folder])

    def remove_selected(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))
        self.refresh_preview()

    def clear_files(self):
        self.files.clear()
        self.cache.clear()
        self.preview.show_images(None, None)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def pick_output(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾", self.output.text())
        if folder:
            self.output.setText(folder)

    # ---- preview ----
    def refresh_preview(self):
        item = self.files.currentItem()
        cube = self.current_cube()
        if item is None or cube is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        try:
            if path not in self.cache:
                if len(self.cache) > 8:
                    self.cache.clear()
                self.cache[path] = load_rgb(path, PREVIEW_SIDE, upright=True)
            before = self.cache[path]
            after = cube.apply(before, self.strength.value() / 100)
        except Exception as exc:
            self.status.setText(f"預覽失敗：{exc}")
            return
        self.preview.show_images(to_pixmap(before), to_pixmap(after))

    # ---- batch ----
    def start_batch(self):
        cube = self.current_cube()
        files = [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]
        if cube is None or not files:
            QMessageBox.information(self, "PhotoLUT", "請先加入照片並選擇風格")
            return
        suffix = self.suffix.text().strip()
        if not suffix:
            QMessageBox.warning(self, "PhotoLUT", "請填檔名後綴，避免和原檔名稱相同")
            return
        folder = Path(self.output.text().strip() or default_output())
        for key, value in (("output", str(folder)), ("look", cube.title),
                           ("strength", self.strength.value()), ("quality", self.quality.value())):
            self.settings.setValue(key, value)
        self.bar.setRange(0, len(files))
        self.bar.setValue(0)
        self.start.setEnabled(False)
        self.cancel.setEnabled(True)
        self.thread = QThread(self)
        self.worker = Worker(files, cube, self.strength.value() / 100, folder, suffix, self.quality.value())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

    def cancel_batch(self):
        if self.worker:
            self.worker.cancelled = True
            self.status.setText("正在取消（處理中的這張會完成）…")

    def on_progress(self, index, name):
        if index < 0:
            self.status.setText(f"{name}（約數秒）…")
            return
        self.bar.setValue(index)
        self.status.setText(f"處理中 {index + 1}/{self.bar.maximum()}：{name}")

    def on_finished(self, done, errors):
        self.bar.setValue(done + len(errors))
        self.start.setEnabled(True)
        self.cancel.setEnabled(False)
        message = f"完成 {done} 張，輸出到 {self.output.text()}"
        if errors:
            message += f"\n失敗 {len(errors)} 張：\n" + "\n".join(errors[:10])
            QMessageBox.warning(self, "PhotoLUT", message)
        self.status.setText(message.splitlines()[0])

    def closeEvent(self, event):
        if self.thread is not None and self.thread.isRunning():
            if self.worker:
                self.worker.cancelled = True
            self.thread.quit()
            self.thread.wait(30000)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoLUT")
    window = Window()
    window.show()
    return app.exec()
