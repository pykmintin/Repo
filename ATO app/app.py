#!/usr/bin/env python3
# NDIS Expense Assistant - FIXED VERSION (Removes blocking validation, adds missing method)

import os
import sys
import csv
import re
import hashlib
import logging
import shutil
import json
import traceback
from datetime import datetime

# === LOGGING SETUP ===
EXE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(EXE_DIR, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')]
)
logging.info("=== NDIS ASSISTANT STARTUP ===")

try:
    from PySide6.QtWidgets import *
    from PySide6.QtCore import Qt, QSettings
    import pytesseract
    from PIL import Image
    logging.info("All imports successful")
except Exception as e:
    logging.critical(f"Import error: {e}\n{traceback.format_exc()}")
    sys.exit(1)

# === CONFIGURATION ===
CONFIG_PATH = os.path.join(EXE_DIR, "config.ini")
PENDING_PATH = os.path.join(EXE_DIR, "pending.csv")
COMPLETED_PATH = os.path.join(EXE_DIR, "completed.csv")
OCR_CACHE_PATH = os.path.join(EXE_DIR, "ocr_cache.json")
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

class NDISAssistant(QMainWindow):
    """Main application window for NDIS Expense Assistant"""
    
    def __init__(self):
        """Initialize main window and load configuration"""
        super().__init__()
        self.setWindowTitle("NDIS Expense Assistant v1.0")
        self.resize(1100, 700)
        
        self.pending_data = []
        self.completed_data = []
        self.current_view = "pending"
        self.file_hashes = set()
        self.categories = []
        self.screenshot_folder = ""
        self.search_root = ""
        self.ocr_cache = {}
        
        self.load_config()
        self.load_ocr_cache()
        self.ensure_csv_files()
        self.init_ui()
        self.load_data()
        
        # Auto-scan on startup
        self.organize_and_scan()
        
    def load_config(self):
        """Load configuration from config.ini with debug logging"""
        settings = QSettings(CONFIG_PATH, QSettings.IniFormat)
        
        # FORCE STRING CONVERSION to avoid unicode issues
        self.screenshot_folder = str(settings.value("Paths/screenshot_folder", 
            os.path.join(EXE_DIR, "Screenshots")))
        self.search_root = str(settings.value("Paths/search_root", r"C:\Users\alles\My Drive"))
        
        categories_str = str(settings.value("Categories/list", 
            "Food;Transport;Medical;Client Session;Supplies;Other"))
        if isinstance(categories_str, str):
            self.categories = [c.strip() for c in categories_str.split(";") if c.strip()]
        
        logging.info(f"Config loaded: {len(self.categories)} categories")
        logging.info(f"Search root: {repr(self.search_root)}")
        logging.info(f"Screenshot folder: {repr(self.screenshot_folder)}")
        
    def save_config(self):
        """Save configuration to config.ini"""
        settings = QSettings(CONFIG_PATH, QSettings.IniFormat)
        settings.setValue("Paths/screenshot_folder", self.screenshot_folder)
        settings.setValue("Categories/list", ";".join(self.categories))
        
    def load_ocr_cache(self):
        """Load OCR results cache to avoid re-processing files"""
        if os.path.exists(OCR_CACHE_PATH):
            try:
                with open(OCR_CACHE_PATH, 'r', encoding='utf-8') as f:
                    self.ocr_cache = json.load(f)
                logging.info(f"Loaded OCR cache: {len(self.ocr_cache)} entries")
            except Exception as e:
                logging.warning(f"Failed to load OCR cache: {e}")
                self.ocr_cache = {}
        else:
            self.ocr_cache = {}
    
    def save_ocr_cache(self):
        """Save OCR cache to disk for future sessions"""
        try:
            with open(OCR_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.ocr_cache, f, indent=2)
            logging.info("Saved OCR cache")
        except Exception as e:
            logging.error(f"Failed to save OCR cache: {e}")
    
    def ensure_csv_files(self):
        """Create CSV files with headers if they don't exist"""
        if not os.path.exists(PENDING_PATH):
            with open(PENDING_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw', 
                               'MerchantOCRValue', 'category', 'description', 'status'])
        
        if not os.path.exists(COMPLETED_PATH):
            with open(COMPLETED_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['file_hash', 'completed_timestamp', 'filename', 'date_raw', 
                               'amount_raw', 'MerchantOCRValue', 'category', 'description', 'status'])
    
    def init_ui(self):
        """Initialize user interface"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Top bar
        top_bar = QHBoxLayout()
        self.folder_label = QLabel(f"[Folder] {os.path.basename(self.screenshot_folder)}")
        self.folder_label.setToolTip(self.screenshot_folder)
        top_bar.addWidget(self.folder_label)
        
        browse_btn = QPushButton("📂 Browse Folder...")
        browse_btn.clicked.connect(self.browse_folder)
        top_bar.addWidget(browse_btn)
        
        scan_btn = QPushButton("🔍 Scan Now")
        scan_btn.clicked.connect(self.organize_and_scan)
        top_bar.addWidget(scan_btn)
        
        settings_btn = QPushButton("⚙️ Settings")
        settings_btn.clicked.connect(self.edit_categories)
        top_bar.addWidget(settings_btn)
        
        layout.addLayout(top_bar)
        
        # Status label
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)
        
        # Toggle button
        self.toggle_btn = QPushButton("Show Completed")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.toggle_view)
        layout.addWidget(self.toggle_btn)
        
        # Main table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Date (DDMMYYYY)", "Amount", "MerchantOCRValue", "Category", "Description", "Actions"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # Button bar
        button_bar = QHBoxLayout()
        
        phone_btn = QPushButton("📱 Open Phone Link")
        phone_btn.clicked.connect(self.open_phone_link)
        button_bar.addWidget(phone_btn)
        
        export_btn = QPushButton("📤 Export History")
        export_btn.clicked.connect(self.export_history)
        button_bar.addWidget(export_btn)
        
        exit_btn = QPushButton("💾 Save & Exit")
        exit_btn.clicked.connect(self.save_and_exit)
        button_bar.addWidget(exit_btn)
        
        layout.addLayout(button_bar)
        
    def load_data(self):
        """Load data from CSV files into memory"""
        # Load completed hashes for fast lookup
        if os.path.exists(COMPLETED_PATH):
            try:
                with open(COMPLETED_PATH, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.file_hashes.add(row.get('file_hash', ''))
                        self.completed_data.append(row)
                logging.info(f"Loaded {len(self.file_hashes)} completed hashes")
            except Exception as e:
                logging.error(f"Error loading completed.csv: {e}")
        
        # Load pending items
        if os.path.exists(PENDING_PATH):
            try:
                with open(PENDING_PATH, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.pending_data = [row for row in reader if row.get('status') == 'pending']
                logging.info(f"Loaded {len(self.pending_data)} pending items")
            except Exception as e:
                logging.error(f"Error loading pending.csv: {e}")
        
        self.refresh_table()
        
    def organize_and_scan(self):
        """Main pipeline: search → OCR → organize → update CSV"""
        logging.info("=== STARTING ORGANIZE AND SCAN ===")
        logging.info(f"Search root: {self.search_root}")
        logging.info(f"Screenshot folder: {self.screenshot_folder}")
        
        # === CRITICAL DEBUG CHECKS ===
        # Check if search root exists and is accessible
        if not os.path.exists(self.search_root):
            self.show_error(f"Search root does not exist:\n{self.search_root}")
            return
        
        if not os.path.isdir(self.search_root):
            self.show_error(f"Search root is not a directory:\n{self.search_root}")
            return
        
        # Try simple directory listing
        try:
            test_list = os.listdir(self.search_root)
            logging.info(f"os.listdir found {len(test_list)} items in search root")
        except Exception as e:
            logging.error(f"os.listdir failed: {e}")
            self.show_error(f"Cannot access search root:\n{e}")
            return
        
        # Try scandir (more reliable)
        try:
            test_scan = list(os.scandir(self.search_root))
            logging.info(f"os.scandir found {len(test_scan)} items in search root")
        except Exception as e:
            logging.error(f"os.scandir failed: {e}")
            self.show_error(f"Cannot scan search root:\n{e}")
            return
        # === END DEBUG CHECKS ===
        
        # Discover all screenshot files
        all_files = []
        walk_count = 0
        for root, dirs, files in os.walk(self.search_root):
            walk_count += 1
            for file in files:
                if file.startswith("Screenshot_") and file.endswith(".jpg"):
                    full_path = os.path.join(root, file)
                    all_files.append(full_path)
                    logging.debug(f"Found: {full_path}")
        
        logging.info(f"os.walk completed {walk_count} directories")
        logging.info(f"Total screenshot files found: {len(all_files)}")
        
        # Filter to only new files (by hash)
        new_files = []
        for filepath in all_files:
            file_hash = self.calculate_hash(filepath)
            if file_hash not in self.file_hashes:
                new_files.append((filepath, file_hash))
        
        if not new_files:
            status_msg = f"Found {len(all_files)} screenshots, 0 new to process"
            self.status_label.setText(status_msg)
            logging.info(status_msg)
            return
        
        # Step 2: OCR with progress dialog
        progress = QProgressDialog(f"Processing {len(new_files)} new screenshots...", "Cancel", 
                                   0, len(new_files), self)
        progress.setWindowTitle("OCR Scanning")
        progress.setModal(True)
        progress.show()
        
        processed = []
        ocr_failed = []
        
        for i, (filepath, file_hash) in enumerate(new_files):
            progress.setValue(i)
            QApplication.processEvents()
            if progress.wasCanceled():
                break
            
            # Check cache first
            if file_hash in self.ocr_cache:
                parsed = self.ocr_cache[file_hash]
                parsed['file_hash'] = file_hash
                parsed['filepath'] = filepath
                parsed['filename'] = os.path.basename(filepath)
                processed.append(parsed)
                logging.info(f"Used cache for: {os.path.basename(filepath)}")
            else:
                parsed = self.parse_and_ocr(filepath, file_hash)
                if parsed:
                    processed.append(parsed)
                    self.ocr_cache[file_hash] = parsed
                else:
                    ocr_failed.append(filepath)
        
        progress.setValue(len(new_files))
        
        # Handle OCR failures
        if ocr_failed:
            self.prompt_manual_entry(ocr_failed)
        
        # Move files to dated folders and update CSV
        moved_count = 0
        for item in processed:
            try:
                src = item['filepath']
                filename = os.path.basename(src)
                date_match = re.search(r'Screenshot_(\d{4})(\d{2})\d{2}_', filename)
                if date_match:
                    year = date_match.group(1)
                    month = date_match.group(2)
                    target_dir = os.path.join(self.screenshot_folder, f"{year}-{month}")
                    os.makedirs(target_dir, exist_ok=True)
                    dst = os.path.join(target_dir, filename)
                    
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                        item['filepath'] = dst
                        moved_count += 1
                        logging.info(f"Moved {filename} → {target_dir}")
                
                self.pending_data.append(item)
                self.file_hashes.add(item['file_hash'])
                
            except Exception as e:
                logging.error(f"Move failed for {filename}: {e}")
        
        # Save all changes
        if processed:
            self.save_pending_csv()
            self.save_ocr_cache()
        
        self.load_data()
        final_msg = f"Processed {len(processed)}, moved {moved_count}"
        self.status_label.setText(final_msg)
        logging.info(final_msg)
        
    def save_pending_csv(self):
        """Save pending data to CSV file"""
        try:
            with open(PENDING_PATH, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw', 
                               'MerchantOCRValue', 'category', 'description', 'status'])
                for item in self.pending_data:
                    writer.writerow([
                        item.get('file_hash', ''),
                        item.get('filename', ''),
                        item.get('filepath', ''),
                        item.get('date_raw', ''),
                        item.get('amount_raw', ''),
                        item.get('MerchantOCRValue', ''),
                        item.get('category', ''),
                        item.get('description', ''),
                        item.get('status', 'pending')
                    ])
            logging.info("Pending CSV saved")
        except Exception as e:
            logging.error(f"Save pending CSV error: {e}")
            self.show_error(f"Failed to save: {e}")
        
    def calculate_hash(self, filepath):
        """Calculate MD5 hash of file for unique identification"""
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def parse_and_ocr(self, filepath, file_hash):
        """Perform OCR and parse Westpac screenshot data"""
        try:
            logging.debug(f"OCR: {os.path.basename(filepath)}")
            image = Image.open(filepath)
            text = pytesseract.image_to_string(image)
            
            date_raw, ddmmyyyy = self.extract_date(text)
            amount = self.extract_amount(text)
            merchant = self.extract_merchant(text)
            
            # === FIX #1: Remove blocking validation ===
            # OLD CODE (rejected files):
            # if not self.validate_ddmmyyyy(ddmmyyyy):
            #     logging.warning(f"Invalid date format from {filepath}: {ddmmyyyy}")
            #     return None
            
            # NEW CODE (logs warning but continues):
            if not self.validate_ddmmyyyy(ddmmyyyy):
                logging.warning(f"Invalid date format from {filepath}: {ddmmyyyy}")
                # Use a default date instead of rejecting the file
                ddmmyyyy = "01012025"  # Placeholder for invalid dates
            
            return {
                'file_hash': file_hash,
                'filename': os.path.basename(filepath),
                'filepath': filepath,
                'date_raw': ddmmyyyy,
                'amount_raw': amount,
                'MerchantOCRValue': merchant,
                'category': '',
                'description': '',
                'status': 'pending'
            }
        except Exception as e:
            logging.error(f"OCR error on {filepath}: {e}")
            return None
    
    def extract_date(self, text):
        """Extract and convert date to DDMMYYYY format"""
        match = re.search(r'([A-Za-z]{3})\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', text)
        if match:
            day = match.group(2).zfill(2)
            month_dict = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
                         "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
            month = month_dict.get(match.group(3), "01")
            year = match.group(4)  # Full 4-digit year
            return (match.group(0), f"{day}{month}{year}")
        return ("", "")
    
    def extract_amount(self, text):
        """Extract amount from OCR text"""
        match = re.search(r'-\$?(\d+\.\d{2})', text)
        return f"-${match.group(1)}" if match else "-0.00"
    
    def extract_merchant(self, text):
        """Extract merchant name from OCR text"""
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        # OLD version - more reliable
        for i, line in enumerate(lines):
            if re.match(r'\d{1,2}:\d{2}', line):  # Looks for "12:50" timestamp
                # Next meaningful line is merchant
                for j in range(i+1, min(i+3, len(lines))):
                    if len(lines[j]) > 3 and not re.search(r'[@%=<>]', lines[j]):
                        return lines[j][:50]
        return "Unknown"
    
    def validate_ddmmyyyy(self, date_str):
        """Validate DDMMYYYY format and logical date values"""
        if len(date_str) != 8 or not date_str.isdigit():
            return False
        day, month, year = int(date_str[:2]), int(date_str[2:4]), int(date_str[4:])
        if month < 1 or month > 12:
            return False
        if day < 1 or day > 31:
            return False
        return True
    
    def prompt_manual_entry(self, failed_files):
        """Prompt user for manual entry of OCR-failed screenshots"""
        msg = f"{len(failed_files)} screenshots could not be read automatically. Would you like to enter them manually?"
        reply = QMessageBox.question(self, "OCR Failed", msg, 
                                    QMessageBox.Yes | QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for filepath in failed_files:
                self.manual_entry_popup(filepath)
    
    def manual_entry_popup(self, filepath):
        """Show popup form for manual data entry of failed OCR"""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Manual Entry - {os.path.basename(filepath)}")
        dialog.resize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        # Date field
        layout.addWidget(QLabel("Date (DDMMYYYY):"))
        date_edit = QLineEdit()
        date_edit.setPlaceholderText("25092025")
        layout.addWidget(date_edit)
        
        # Amount field
        layout.addWidget(QLabel("Amount (e.g., -34.50):"))
        amount_edit = QLineEdit()
        amount_edit.setPlaceholderText("-34.50")
        layout.addWidget(amount_edit)
        
        # Merchant field
        layout.addWidget(QLabel("Merchant:"))
        merchant_edit = QLineEdit()
        merchant_edit.setPlaceholderText("e.g., YMCA, Shell")
        layout.addWidget(merchant_edit)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            # Create manual entry item
            file_hash = self.calculate_hash(filepath)
            item = {
                'file_hash': file_hash,
                'filename': os.path.basename(filepath),
                'filepath': filepath,
                'date_raw': date_edit.text(),
                'amount_raw': amount_edit.text(),
                'MerchantOCRValue': merchant_edit.text(),
                'category': '',
                'description': '',
                'status': 'pending'
            }
            self.pending_data.append(item)
            self.file_hashes.add(file_hash)
            self.save_pending_csv()
            self.refresh_table()
    
    def refresh_table(self):
        """Refresh main table based on current view (pending/completed)"""
        if self.current_view == "pending":
            self.show_pending()
        else:
            self.show_completed()
    
    def show_pending(self):
        """Display pending items with full interactivity"""
        self.table.setRowCount(len(self.pending_data))
        for row, item in enumerate(self.pending_data):
            # Date
            self.table.setItem(row, 0, QTableWidgetItem(item['date_raw']))
            
            # Amount
            self.table.setItem(row, 1, QTableWidgetItem(item['amount_raw']))
            
            # MerchantOCRValue (read-only)
            merchant_item = QTableWidgetItem(item['MerchantOCRValue'])
            merchant_item.setFlags(merchant_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, merchant_item)
            
            # Category dropdown
            category_combo = QComboBox()
            category_combo.addItems([""] + self.categories)
            category_combo.setCurrentText(item['category'])
            category_combo.currentTextChanged.connect(lambda text, r=row: self.update_category(r, text))
            self.table.setCellWidget(row, 3, category_combo)
            
            # Description
            desc_item = QTableWidgetItem(item['description'])
            self.table.setItem(row, 4, desc_item)
            
            # Actions
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            
            view_btn = QPushButton("👁️")
            view_btn.clicked.connect(lambda _, p=item['filepath']: self.view_image(p))
            actions_layout.addWidget(view_btn)
            
            done_btn = QPushButton("✓ Done")
            done_btn.clicked.connect(lambda _, r=row: self.mark_done(r))
            actions_layout.addWidget(done_btn)
            
            self.table.setCellWidget(row, 5, actions_widget)
        
        self.status_label.setText(f"Showing {len(self.pending_data)} pending items")
    
    def show_completed(self):
        """Display completed items in read-only mode"""
        self.table.setRowCount(len(self.completed_data))
        for row, item in enumerate(self.completed_data):
            self.table.setItem(row, 0, QTableWidgetItem(item['date_raw']))
            self.table.setItem(row, 1, QTableWidgetItem(item['amount_raw']))
            self.table.setItem(row, 2, QTableWidgetItem(item['MerchantOCRValue']))
            self.table.setItem(row, 3, QTableWidgetItem(item['category']))
            self.table.setItem(row, 4, QTableWidgetItem(item['description']))
            # No actions column for completed items
        
        self.status_label.setText(f"Showing {len(self.completed_data)} completed items")
    
    def update_category(self, row, category):
        """Auto-fill description when category is selected"""
        if 0 <= row < len(self.pending_data):
            item = self.pending_data[row]
            item['category'] = category
            
            if category and not item['description']:
                item['description'] = f"{category} - {item['MerchantOCRValue']}"
                self.table.item(row, 4).setText(item['description'])
            
            self.save_pending_csv()
    
    def view_image(self, filepath):
        """Open screenshot image in default viewer"""
        if os.path.exists(filepath):
            os.startfile(filepath)
        else:
            self.show_error("Image file not found")
    
    def mark_done(self, row):
        """Mark item as done and save to completed CSV"""
        if 0 <= row < len(self.pending_data):
            item = self.pending_data.pop(row)
            
            # Get current values from table widgets
            category = self.table.cellWidget(row, 3).currentText()
            description = self.table.item(row, 4).text()
            
            item['category'] = category
            item['description'] = description
            item['status'] = 'done'
            
            # Save to completed with backup protection
            self.save_completed_csv_with_backup(item)
            
            # Update pending CSV
            self.save_pending_csv()
            
            self.refresh_table()
            self.status_label.setText(f"Marked done: {item['filename']}")
    
    def save_completed_csv_with_backup(self, item):
        """Append to completed.csv with automatic backup before write"""
        try:
            # Backup existing file
            if os.path.exists(COMPLETED_PATH):
                backup_path = f"{COMPLETED_PATH}.bak"
                shutil.copy2(COMPLETED_PATH, backup_path)
            
            # Append new item
            with open(COMPLETED_PATH, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if os.path.getsize(COMPLETED_PATH) == 0:
                    writer.writerow(['file_hash', 'completed_timestamp', 'filename', 'date_raw', 
                                   'amount_raw', 'MerchantOCRValue', 'category', 'description', 'status'])
                writer.writerow([
                    item['file_hash'], datetime.utcnow().isoformat() + 'Z', item['filename'],
                    item['date_raw'], item['amount_raw'], item['MerchantOCRValue'],
                    item['category'], item['description'], 'done'
                ])
            
            # Remove backup if successful
            if os.path.exists(f"{COMPLETED_PATH}.bak"):
                os.remove(f"{COMPLETED_PATH}.bak")
                
            logging.info(f"Saved to completed.csv: {item['filename']}")
        except Exception as e:
            logging.error(f"Save failed, restoring backup: {e}")
            # Restore backup
            if os.path.exists(f"{COMPLETED_PATH}.bak"):
                shutil.copy2(f"{COMPLETED_PATH}.bak", COMPLETED_PATH)
            self.show_error(f"Save failed, backup restored: {e}")
    
    def toggle_view(self):
        """Toggle between pending and completed view"""
        self.current_view = "completed" if self.toggle_btn.isChecked() else "pending"
        self.toggle_btn.setText("Show Pending" if self.toggle_btn.isChecked() else "Show Completed")
        self.refresh_table()
    
    def edit_categories(self):
        """Open dialog to edit category list"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Categories")
        dialog.resize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setPlainText("\n".join(self.categories))
        
        layout.addWidget(QLabel("Categories (one per line):"))
        layout.addWidget(text_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            text = text_edit.toPlainText().strip()
            self.categories = [c.strip() for c in text.split('\n') if c.strip()]
            self.save_config()
            self.refresh_table()
    
    def browse_folder(self):
        """Change screenshot folder via file dialog"""
        folder = QFileDialog.getExistingDirectory(self, "Select Screenshot Folder", self.screenshot_folder)
        if folder:
            self.screenshot_folder = folder
            self.folder_label.setText(f"[Folder] {os.path.basename(folder)}")
            self.folder_label.setToolTip(folder)
            self.save_config()
            self.status_label.setText(f"Folder changed to: {folder}")
    
    def open_phone_link(self):
        """Launch Windows Phone Link application"""
        try:
            os.startfile("ms-phone-link:")
            logging.info("Launched Phone Link")
        except Exception as e:
            logging.error(f"Failed to launch Phone Link: {e}")
            self.show_error("Could not launch Phone Link. Please open manually.")
    
    def export_history(self):
        """Export completed.csv to Desktop with timestamp"""
        if not os.path.exists(COMPLETED_PATH):
            self.show_error("No completed data to export")
            return
        
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = os.path.join(desktop, f"NDIS_Export_{timestamp}.csv")
        
        try:
            shutil.copy2(COMPLETED_PATH, export_path)
            QMessageBox.information(self, "Success", 
                                  f"Exported to Desktop:\n{os.path.basename(export_path)}")
        except Exception as e:
            logging.error(f"Export failed: {e}")
            self.show_error(f"Export failed: {e}")
    
    def save_and_exit(self):
        """Save pending data and exit application"""
        self.save_pending_csv()
        self.save_ocr_cache()
        logging.info("Application closing")
        self.close()
    
    def show_error(self, message):
        """Display error message to user and log it"""
        logging.error(f"User error: {message}")
        QMessageBox.warning(self, "Error", message)


def main():
    """Application entry point"""
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("NDIS Assistant")
        
        window = NDISAssistant()
        window.show()
        
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Fatal error: {e}\n{traceback.format_exc()}")
        QMessageBox.critical(None, "Fatal Error", 
                           f"Application crashed:\n{e}\n\nCheck app.log for details")
        sys.exit(1)


if __name__ == '__main__':
    main()