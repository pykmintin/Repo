#!/usr/bin/env python3
# NDIS Expense Assistant
# Robust version with error handling and logging

import os
import sys
import csv
import re
import traceback
import logging
from datetime import datetime
from pathlib import Path

# === CRITICAL: Setup logging BEFORE any other imports ===
EXE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(EXE_DIR, "app.log")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8'),
        logging.StreamHandler(sys.stderr)  # Also print to stderr for pythonw debugging
    ]
)

logging.info("=" * 50)
logging.info("NDIS ASSISTANT - STARTUP")

try:
    # Now safe to import GUI libraries
    from PySide6.QtWidgets import *
    from PySide6.QtCore import Qt, QSettings
    from PySide6.QtGui import QIcon
    
    # Import OCR libraries
    import pytesseract
    from PIL import Image
    
    logging.info("All imports successful")
    
except Exception as e:
    logging.critical(f"Import error: {e}")
    logging.critical(traceback.format_exc())
    # Try to show message box if possible
    try:
        from PySide6.QtWidgets import QMessageBox, QApplication
        app = QApplication([])
        QMessageBox.critical(None, "Fatal Import Error", str(e))
    except:
        pass
    sys.exit(1)

# === CONFIGURATION ===
CONFIG_PATH = os.path.join(EXE_DIR, "config.ini")
PENDING_PATH = os.path.join(EXE_DIR, "pending.csv")
COMPLETED_PATH = os.path.join(EXE_DIR, "completed.csv")
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Configure Tesseract
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
logging.info(f"Tesseract configured: {TESSERACT_CMD}")

# Validate Tesseract works
try:
    test_img = Image.new('RGB', (50, 20), color='white')
    test_text = pytesseract.image_to_string(test_img)
    logging.info("✓ Tesseract validation passed")
except Exception as e:
    logging.error(f"✗ Tesseract validation failed: {e}")
    QMessageBox.critical(None, "Tesseract Error", f"OCR engine not working:\n{e}")
    sys.exit(1)


class NDISAssistant(QMainWindow):
    def __init__(self):
        super().__init__()
        logging.info("Initializing main window")
        
        self.setWindowTitle("NDIS Expense Assistant v1.0")
        self.resize(950, 750)
        
        # Data storage
        self.pending_data = []
        self.completed_session = []
        self.processed_filenames = set()  # Optimized lookup
        
        # Load configuration
        try:
            self.load_config()
            logging.info("Configuration loaded")
        except Exception as e:
            logging.error(f"Config load error: {e}")
            self.show_error(f"Configuration error: {e}")
            sys.exit(1)
        
        # Build UI
        self.init_ui()
        
        # Load existing data
        self.load_data()
        
        # Initial scan (optional - uncomment to auto-scan on startup)
        # self.scan_screenshots()
        
    def load_config(self):
        """Load settings from INI file"""
        settings = QSettings(CONFIG_PATH, QSettings.IniFormat)
        
        # Screenshot folder (default to \Screenshots subfolder)
        default_screenshots = os.path.join(EXE_DIR, "Screenshots")
        self.screenshot_folder = settings.value("Paths/screenshot_folder", default_screenshots)
        
        # Client names
        default_clients = ["Sarah Mitchell", "Johnson Family", "Williams Group", "Transport - General"]
        self.client_names = settings.value("Clients/names", default_clients)
        if isinstance(self.client_names, str):
            self.client_names = [n.strip() for n in self.client_names.split(";") if n.strip()]
            
    def save_config(self):
        """Save settings to INI file"""
        settings = QSettings(CONFIG_PATH, QSettings.IniFormat)
        settings.setValue("Paths/screenshot_folder", self.screenshot_folder)
        settings.setValue("Clients/names", "; ".join(self.client_names))
        
    def init_ui(self):
        """Create user interface"""
        logging.debug("Building UI")
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # TOP BAR
        top = QHBoxLayout()
        
        self.folder_label = QLabel(f"📁 {os.path.basename(self.screenshot_folder)}")
        self.folder_label.setToolTip(self.screenshot_folder)
        top.addWidget(self.folder_label)
        
        browse_btn = QPushButton("📂 Browse...")
        browse_btn.clicked.connect(self.browse_folder)
        top.addWidget(browse_btn)
        
        scan_btn = QPushButton("🔍 Scan Screenshots")
        scan_btn.clicked.connect(self.scan_screenshots)
        top.addWidget(scan_btn)
        
        settings_btn = QPushButton("⚙️ Settings")
        settings_btn.clicked.connect(self.open_settings)
        top.addWidget(settings_btn)
        
        layout.addLayout(top)
        
        # STATUS BAR
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        
        # TODO TABLE
        todo_box = QGroupBox(f"📋 TODO (0 items)")
        todo_layout = QVBoxLayout(todo_box)
        
        self.todo_table = QTableWidget(0, 5)
        self.todo_table.setHorizontalHeaderLabels(["Date", "Amount", "Merchant", "Client", "Actions"])
        self.todo_table.horizontalHeader().setStretchLastSection(True)
        todo_layout.addWidget(self.todo_table)
        layout.addWidget(todo_box)
        self.todo_group = todo_box
        
        # COMPLETED TABLE
        completed_box = QGroupBox("✅ Completed (This Session)")
        completed_layout = QVBoxLayout(completed_box)
        
        self.completed_table = QTableWidget(0, 5)
        self.completed_table.setHorizontalHeaderLabels(["Date", "Amount", "Merchant", "Client", "Status"])
        self.completed_table.horizontalHeader().setStretchLastSection(True)
        completed_layout.addWidget(self.completed_table)
        layout.addWidget(completed_box)
        
        # BUTTON BAR
        buttons = QHBoxLayout()
        
        mydec_btn = QPushButton("📱 Open myDeductions")
        mydec_btn.clicked.connect(self.open_mydeductions)
        buttons.addWidget(mydec_btn)
        
        export_btn = QPushButton("📤 Export History")
        export_btn.clicked.connect(self.export_csv)
        buttons.addWidget(export_btn)
        
        exit_btn = QPushButton("💾 Save & Exit")
        exit_btn.clicked.connect(self.save_and_exit)
        buttons.addWidget(exit_btn)
        
        layout.addLayout(buttons)
        
    def load_data(self):
        """Load pending items and build processed set"""
        logging.info("Loading data files")
        
        # Load processed filenames for fast lookup
        self.processed_filenames = set()
        if os.path.exists(COMPLETED_PATH):
            try:
                with open(COMPLETED_PATH, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Skip header
                    for row in reader:
                        if len(row) > 1:
                            self.processed_filenames.add(row[1])
                logging.info(f"Loaded {len(self.processed_filenames)} processed filenames")
            except Exception as e:
                logging.warning(f"Error reading completed.csv: {e}")
        
        # Load pending items
        self.pending_data = []
        if os.path.exists(PENDING_PATH):
            try:
                with open(PENDING_PATH, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Only add if not already completed
                        if row.get('filename') not in self.processed_filenames:
                            self.pending_data.append(row)
                logging.info(f"Loaded {len(self.pending_data)} pending items")
            except Exception as e:
                logging.error(f"Error reading pending.csv: {e}")
                self.show_error(f"Failed to load pending data: {e}")
        
        self.refresh_tables()
        
    def scan_screenshots(self):
        """Scan screenshot folder for new files"""
        logging.info(f"Scanning folder: {self.screenshot_folder}")
        
        if not os.path.exists(self.screenshot_folder):
            self.show_error("Screenshot folder does not exist")
            return
            
        # Find screenshot files
        screenshots = []
        for root, dirs, files in os.walk(self.screenshot_folder):
            for file in files:
                if file.startswith("Screenshot_") and file.endswith(".jpg"):
                    screenshots.append(os.path.join(root, file))
                    
        if not screenshots:
            self.show_error("No screenshots found")
            return
            
        # Progress dialog
        progress = QProgressDialog("Processing screenshots...", "Cancel", 0, len(screenshots), self)
        progress.setWindowTitle("Scanning")
        progress.setModal(True)
        progress.show()
        
        new_count = 0
        for i, screenshot_path in enumerate(sorted(screenshots)):
            progress.setValue(i)
            QApplication.processEvents()
            if progress.wasCanceled():
                break
                
            filename = os.path.basename(screenshot_path)
            if filename in self.processed_filenames:
                continue
                
            try:
                parsed = self.parse_screenshot(screenshot_path)
                if parsed:
                    parsed['filename'] = filename
                    parsed['filepath'] = screenshot_path
                    self.pending_data.append(parsed)
                    new_count += 1
            except Exception as e:
                logging.error(f"Failed to parse {filename}: {e}")
                continue
        
        progress.setValue(len(screenshots))
        
        if new_count > 0:
            self.save_pending_csv()
            
        self.refresh_tables()
        self.status_label.setText(f"Scan complete - {new_count} new items found")
        logging.info(f"Scan complete: {new_count} new items")
        
    def parse_screenshot(self, filepath):
        """Extract data from Westpac screenshot using OCR"""
        try:
            image = Image.open(filepath)
            text = pytesseract.image_to_string(image)
            logging.debug(f"OCR text for {os.path.basename(filepath)}:\n{text[:200]}...")
            
            # Parse with regex
            date_match = re.search(r'([A-Za-z]{3})\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text)
            amount_match = re.search(r'[\-\$]?([0-9]+\.[0-9]{2})', text)
            
            if date_match and amount_match:
                return {
                    'date_raw': f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)} {date_match.group(4)}",
                    'amount_raw': f"-${amount_match.group(1)}",
                    'merchant_raw': self.extract_merchant(text),
                    'client_name': '',
                    'notes': ''
                }
            else:
                logging.warning(f"Could not parse date/amount from {filepath}")
                return None
        except Exception as e:
            logging.error(f"OCR error on {filepath}: {e}")
            return None
            
    def extract_merchant(self, text):
        """Extract merchant name from OCR text"""
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for i, line in enumerate(lines):
            if re.match(r'\d{1,2}:\d{2}', line):
                # Next meaningful line is merchant
                for j in range(i+1, min(i+3, len(lines))):
                    if len(lines[j]) > 3 and not re.search(r'[@%=<>]', lines[j]):
                        return lines[j][:50]
        return "Unknown Merchant"
        
    def refresh_tables(self):
        """Update both tables"""
        # Update TODO
        self.todo_table.setRowCount(len(self.pending_data))
        for row, item in enumerate(self.pending_data):
            self.todo_table.setItem(row, 0, QTableWidgetItem(item.get('date_raw', '')))
            self.todo_table.setItem(row, 1, QTableWidgetItem(item.get('amount_raw', '')))
            self.todo_table.setItem(row, 2, QTableWidgetItem(item.get('merchant_raw', '')))
            
            # Client dropdown
            combo = QComboBox()
            combo.addItems([""] + self.client_names)
            combo.setCurrentText(item.get('client_name', ''))
            combo.currentTextChanged.connect(lambda text, r=row: self.update_client(r, text))
            self.todo_table.setCellWidget(row, 3, combo)
            
            # Actions
            actions = QWidget()
            layout = QHBoxLayout(actions)
            layout.setContentsMargins(0,0,0,0)
            
            view_btn = QPushButton("👁️")
            view_btn.clicked.connect(lambda _, p=item['filepath']: self.view_image(p))
            layout.addWidget(view_btn)
            
            done_btn = QPushButton("✓ Done")
            done_btn.clicked.connect(lambda _, r=row: self.mark_done(r))
            layout.addWidget(done_btn)
            
            skip_btn = QPushButton("✗")
            skip_btn.clicked.connect(lambda _, r=row: self.skip_item(r))
            layout.addWidget(skip_btn)
            
            self.todo_table.setCellWidget(row, 4, actions)
            
        self.todo_group.setTitle(f"📋 TODO ({len(self.pending_data)} items)")
        
        # Update COMPLETED
        self.completed_table.setRowCount(len(self.completed_session))
        for row, item in enumerate(self.completed_session):
            self.completed_table.setItem(row, 0, QTableWidgetItem(item.get('date_raw', '')))
            self.completed_table.setItem(row, 1, QTableWidgetItem(item.get('amount_raw', '')))
            self.completed_table.setItem(row, 2, QTableWidgetItem(item.get('merchant_raw', '')))
            self.completed_table.setItem(row, 3, QTableWidgetItem(item.get('client_name', '')))
            self.completed_table.setItem(row, 4, QTableWidgetItem("✓ Saved"))
            
    def update_client(self, row, text):
        if 0 <= row < len(self.pending_data):
            self.pending_data[row]['client_name'] = text
            
    def view_image(self, path):
        if os.path.exists(path):
            os.startfile(path)
        else:
            self.show_error("Image file not found")
            
    def mark_done(self, row):
        if 0 <= row < len(self.pending_data):
            item = self.pending_data.pop(row)
            item['completed_timestamp'] = datetime.utcnow().isoformat() + 'Z'
            self.completed_session.append(item)
            self.append_to_completed_csv(item)
            self.refresh_tables()
            self.status_label.setText(f"Marked complete: {item.get('merchant_raw', '')}")
            
    def skip_item(self, row):
        if 0 <= row < len(self.pending_data):
            self.pending_data.pop(row)
            self.refresh_tables()
            
    def append_to_completed_csv(self, item):
        try:
            file_exists = os.path.exists(COMPLETED_PATH)
            with open(COMPLETED_PATH, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(['completed_timestamp', 'filename', 'date_raw', 'amount_raw', 
                                   'merchant_raw', 'client_name', 'notes', 'mydeductions_entered'])
                writer.writerow([
                    item.get('completed_timestamp', ''),
                    item.get('filename', ''),
                    item.get('date_raw', ''),
                    item.get('amount_raw', ''),
                    item.get('merchant_raw', ''),
                    item.get('client_name', ''),
                    item.get('notes', ''),
                    ''
                ])
        except Exception as e:
            logging.error(f"CSV append error: {e}")
            self.show_error(f"Failed to save: {e}")
            
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", self.screenshot_folder)
        if folder:
            self.screenshot_folder = folder
            self.folder_label.setText(f"📁 {os.path.basename(folder)}")
            self.folder_label.setToolTip(folder)
            self.save_config()
            
    def open_settings(self):
        dialog = SettingsDialog(self.client_names, self)
        if dialog.exec() == QDialog.Accepted:
            self.client_names = dialog.get_client_names()
            self.save_config()
            self.refresh_tables()
            
    def open_mydeductions(self):
        try:
            os.startfile("ms-phone-link:")
        except:
            QMessageBox.information(self, "Manual", "Open Phone Link manually")
            
    def export_csv(self):
        try:
            if not os.path.exists(COMPLETED_PATH):
                self.show_error("No data to export")
                return
                
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            timestamp = datetime.now().strftime("%Y-%m-%d")
            export_path = os.path.join(desktop, f"NDIS_Export_{timestamp}.csv")
            
            # Copy file
            with open(COMPLETED_PATH, 'r', encoding='utf-8') as src:
                with open(export_path, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
                    
            QMessageBox.information(self, "Done", f"Exported to:\n{export_path}")
            os.startfile(desktop)
        except Exception as e:
            self.show_error(f"Export failed: {e}")
            
    def save_pending_csv(self):
        """Save pending data to CSV"""
        try:
            with open(PENDING_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['filename', 'filepath', 'date_raw', 'amount_raw', 
                               'merchant_raw', 'client_name', 'notes'])
                for item in self.pending_data:
                    writer.writerow([
                        item.get('filename', ''),
                        item.get('filepath', ''),
                        item.get('date_raw', ''),
                        item.get('amount_raw', ''),
                        item.get('merchant_raw', ''),
                        item.get('client_name', ''),
                        item.get('notes', '')
                    ])
            logging.info("Pending CSV saved")
        except Exception as e:
            logging.error(f"Save pending CSV error: {e}")
            
    def save_and_exit(self):
        self.save_pending_csv()
        self.close()
        
    def show_error(self, message):
        """Show error dialog and log it"""
        logging.error(f"User error: {message}")
        QMessageBox.warning(self, "Error", message)


class SettingsDialog(QDialog):
    def __init__(self, client_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Client Names (one per line):"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText("\n".join(client_names))
        layout.addWidget(self.text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def get_client_names(self):
        text = self.text_edit.toPlainText().strip()
        return [name.strip() for name in text.split('\n') if name.strip()]


def main():
    """Main entry point with error handling"""
    try:
        logging.info("Creating QApplication")
        app = QApplication(sys.argv)
        app.setApplicationName("NDIS Assistant")
        
        logging.info("Creating main window")
        window = NDISAssistant()
        window.show()
        
        logging.info("Entering event loop")
        sys.exit(app.exec())
        
    except Exception as e:
        logging.critical(f"Unhandled exception: {e}")
        logging.critical(traceback.format_exc())
        
        # Try to show error dialog
        try:
            error_app = QApplication([])
            QMessageBox.critical(None, "Fatal Error", 
                               f"The application crashed:\n\n{e}\n\nCheck app.log for details")
        except:
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()