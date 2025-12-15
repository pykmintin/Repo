#!/usr/bin/env python3
"""
NDIS Expense Assistant v3.0
Synthesized from both versions: Threaded architecture + clean system separation
"""

import os
import sys
import csv
import re
import hashlib
import json
import shutil
import logging
import traceback
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Any, Callable

# === LOGGING SETUP ===
EXE_DIR = Path(__file__).parent.resolve()
LOG_FILE = EXE_DIR / "app.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logging.info("=== NDIS EXPENSE ASSISTANT v3.0 STARTUP ===")

# === IMPORTS ===
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTableWidget, QTableWidgetItem, QLabel, QPushButton, QComboBox,
        QFileDialog, QMessageBox, QDialog, QLineEdit, QTextEdit,
        QDialogButtonBox, QCheckBox, QHeaderView
    )
    from PySide6.QtCore import Qt, QSettings, QTimer, QObject, Signal, QThread
    from PySide6.QtGui import QCloseEvent
    from PIL import Image
    logging.info("✅ All GUI imports successful")
except ImportError as e:
    logging.critical(f"Import error: {e}\n{traceback.format_exc()}")
    sys.exit(1)

try:
    import cv2
    import numpy as np
    import pytesseract
    logging.info("✅ OCR engine imports successful")
except ImportError as e:
    logging.error(f"OCR dependency missing: {e}")
    sys.exit(1)


# === SYSTEM CLASSES (From v2's clean architecture) ===

class LearningSystem:
    """Handles merchant-to-category learning with frequency-based confidence"""

    def __init__(self, knowledge_file: Path):
        self.knowledge_file = knowledge_file
        self.knowledge_file_bak = knowledge_file.with_suffix('.json.bak')
        self.knowledge_file_tmp = knowledge_file.with_suffix('.json.tmp')
        self.merchant_knowledge: List[Dict] = []
        self.load_knowledge()

    def load_knowledge(self) -> None:
        """Load merchant knowledge from JSON file"""
        if self.knowledge_file.exists():
            try:
                with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                    self.merchant_knowledge = json.load(f)
                logging.info(
                    f"📚 Loaded {len(self.merchant_knowledge)} knowledge entries")
            except Exception as e:
                logging.error(f"Failed to load knowledge: {e}")
                self.merchant_knowledge = []
        else:
            self.merchant_knowledge = []

    def save_knowledge_atomic(self) -> bool:
        """Atomic write for knowledge base"""
        try:
            if self.knowledge_file.exists():
                shutil.copy2(self.knowledge_file, self.knowledge_file_bak)

            with open(self.knowledge_file_tmp, 'w', encoding='utf-8') as f:
                json.dump(self.merchant_knowledge, f, indent=2)

            os.replace(self.knowledge_file_tmp, self.knowledge_file)

            if self.knowledge_file_bak.exists():
                self.knowledge_file_bak.unlink()

            logging.info(
                f"💾 Saved {len(self.merchant_knowledge)} knowledge entries")
            return True
        except Exception as e:
            logging.error(f"Save failed: {e}")
            if self.knowledge_file_bak.exists():
                shutil.copy2(self.knowledge_file_bak, self.knowledge_file)
            return False

    def learn_confirmation(self, merchant: str, category: str) -> None:
        """Record merchant-category confirmation (append-only with frequency tracking)"""
        normalized = merchant.lower().strip()
        category = category.strip()

        if not normalized or not category:
            return

        # Find existing entry for this pair
        for entry in self.merchant_knowledge:
            if entry['merchant'] == normalized and entry['category'] == category:
                entry['confirmations'] = entry.get('confirmations', 1) + 1
                entry['last_confirmed'] = datetime.utcnow().isoformat() + 'Z'
                logging.info(
                    f"⬆️  Updated {normalized} -> {category} (count: {entry['confirmations']})")
                self.save_knowledge_atomic()
                return

        # New entry
        self.merchant_knowledge.append({
            "merchant": normalized,
            "category": category,
            "confirmations": 1,
            "first_seen": datetime.utcnow().isoformat() + 'Z',
            "last_confirmed": datetime.utcnow().isoformat() + 'Z'
        })
        logging.info(f"✏️  Learned {normalized} -> {category}")
        self.save_knowledge_atomic()

    def get_suggested_category(self, merchant: str, threshold: int = 2) -> Optional[str]:
        """Get suggested category if confidence meets threshold"""
        normalized = merchant.lower().strip()
        if not normalized:
            return None

        # Count frequencies
        category_counts = defaultdict(int)
        for entry in self.merchant_knowledge:
            if entry['merchant'] == normalized:
                category_counts[entry['category']
                                ] += entry.get('confirmations', 1)

        if category_counts:
            most_frequent, count = max(
                category_counts.items(), key=lambda x: x[1])
            if count >= threshold:
                logging.debug(
                    f"💡 Suggesting '{most_frequent}' for '{merchant}' (confidence: {count})")
                return most_frequent

        return None


class DescriptionSystem:
    """Handles dynamic {Category} - {UserNote} description format"""

    @staticmethod
    def format_description(category: str, user_note: str = "") -> str:
        """Format as 'Category - UserNote' or just 'Category' if note empty"""
        if not user_note or user_note.strip() == category.strip():
            return category
        return f"{category} - {user_note}"

    @staticmethod
    def extract_parts(description: str) -> tuple[str, str]:
        """Extract (category, user_note) from description"""
        if not description:
            return "", ""

        if " - " in description:
            parts = description.split(" - ", 1)
            return parts[0], parts[1]
        return "", description

    @staticmethod
    def update_description(current_desc: str, new_category: str) -> str:
        """Update category while preserving user note"""
        if not current_desc:
            return new_category

        if " - " in current_desc:
            _, user_note = current_desc.split(" - ", 1)
            return f"{new_category} - {user_note}"
        else:
            # Assume current_desc is user note
            return f"{new_category} - {current_desc}"


class WestpacOCREngine:
    """Production-grade OCR engine for Westpac screenshots"""

    def __init__(self):
        # Amount patterns
        self.amount_patterns = [
            r'\-\$\d+\.\d{2}',  # -$28.70
            r'\$\-\d+\.\d{2}',  # $-28.70
            r'\-\d+\.\d{2}',    # -28.70
            r'\d+\.\d{2}',      # 28.70
        ]

        # Date patterns
        self.date_patterns = [
            r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
        ]

        # Merchant name corrections
        self.merchant_corrections = {
            'bokeies delight': 'Bakers Delight',
            'bokees delight': 'Bakers Delight',
            'bokies delight': 'Bakers Delight',
            'delightt': 'Delight',
            'traralgongon': 'Traralgon',
            '4ae. health': 'Central Gippsland Health',
            'mn,': 'ALDI Mobile',
            'alid': 'ALDI',
        }

        # Keyword to category mapping
        self.keyword_categories = {
            'bakery': 'Bakery', 'baker': 'Bakery', 'delight': 'Bakery',
            'muffin': 'Restaurants & Dining', 'break': 'Restaurants & Dining',
            'restaurant': 'Restaurants & Dining', 'dining': 'Restaurants & Dining',
            'food': 'Restaurants & Dining', 'cafe': 'Restaurants & Dining',
            'coffee': 'Restaurants & Dining', 'espresso': 'Restaurants & Dining',
            'health': 'Healthcare', 'medical': 'Healthcare',
            'mobile': 'Utilities', 'phone': 'Utilities', 'aldi': 'Utilities',
        }

        # Lines to skip
        self.skip_patterns = [
            r'%', r'8:', r'@', r'\|', r'Westpac', r'Account', r'Subcategory',
            r'\d{1,2}:\d{2}', r'\d{1,3}%', r'\d{4}-\d{3}',
            r'Edit$', r'Tags$', r'None$', r'time$', r'transaction$',
            r'^\d+$', r'^\W+$',
        ]

    def preprocess_image(self, image: Image.Image) -> np.ndarray:
        """Preprocess image for optimal OCR"""
        img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Auto-orient
        height, width = img.shape[:2]
        if width > height:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

        # Resize
        target_height = 2400
        scale = target_height / img.shape[0]
        img = cv2.resize(img, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)

        # Grayscale and threshold
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)

        return denoised

    def correct_merchant_name(self, merchant: str) -> str:
        """Apply content-based corrections"""
        merchant_clean = merchant.strip()
        merchant_lower = merchant_clean.lower()

        for error, correction in self.merchant_corrections.items():
            if error in merchant_lower:
                return correction

        # Clean artifacts
        merchant = re.sub(r'[~*]', '', merchant)
        merchant = re.sub(r'\s+', ' ', merchant)
        merchant = merchant.strip(' -_()<>')

        return merchant

    def extract_amount(self, text: str) -> str:
        """Extract transaction amount"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        for pattern in self.amount_patterns:
            for line in lines:
                matches = re.findall(pattern, line)
                if matches:
                    amount = matches[0]
                    number_match = re.search(r'(\d+\.\d{2})', amount)
                    if number_match:
                        number = number_match.group(1)
                        return f"-${number}"

        return "$0.00"

    def extract_date(self, text: str) -> str:
        """Extract date in DDMMYYYY format"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        month_dict = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
        }

        for pattern in self.date_patterns:
            for line in lines:
                matches = re.findall(pattern, line, re.IGNORECASE)
                if matches:
                    match = matches[0]
                    if isinstance(match, tuple):
                        if len(match) == 4:  # DayName, Day, Month, Year
                            day = match[1].zfill(2)
                            month = month_dict.get(match[2], "01")
                            year = match[3]
                            return f"{day}{month}{year}"
                        elif len(match) == 3:  # Day, Month, Year
                            day = match[0].zfill(2)
                            month = month_dict.get(match[1], "01")
                            year = match[2]
                            return f"{day}{month}{year}"

        return "01012025"  # Fallback

    def extract_merchant_name(self, text: str) -> str:
        """Extract merchant name with intelligent filtering"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        candidates = []

        for line in lines:
            # Skip patterns
            skip = any(re.search(pattern, line, re.IGNORECASE)
                       for pattern in self.skip_patterns)
            if skip:
                continue

            # Skip invalid
            if (len(line) < 3 or line.isdigit() or
                line in ['Edit', 'Tags', 'None', 'Account', 'Subcategory'] or
                    'time' in line.lower() or 'transaction' in line.lower()):
                continue

            merchant = re.sub(r'\s+', ' ', line).strip(' -_()<>')
            if len(merchant) >= 3:
                candidates.append(merchant)

        # Find best candidate
        if candidates:
            for candidate in candidates:
                if any(word in candidate.lower() for word in self.keyword_categories.keys()):
                    return self.correct_merchant_name(candidate)
            return self.correct_merchant_name(candidates[0])

        return "Unknown Merchant"

    def extract_subcategory(self, text: str, merchant: str) -> str:
        """Extract subcategory based on keywords"""
        text_lower = text.lower()
        merchant_lower = merchant.lower()

        # Check merchant first
        for keyword, category in self.keyword_categories.items():
            if keyword in merchant_lower:
                return category

        # Check full text
        for keyword, category in self.keyword_categories.items():
            if keyword in text_lower:
                return category

        return "Uncategorised"

    def extract_transaction(self, image_path: Path) -> Dict[str, Any]:
        """Main extraction method"""
        try:
            with Image.open(image_path) as img:
                processed = self.preprocess_image(img)
                text = pytesseract.image_to_string(processed)

                merchant = self.extract_merchant_name(text)
                amount = self.extract_amount(text)
                date = self.extract_date(text)
                subcategory = self.extract_subcategory(text, merchant)

                needs_attention = (
                    merchant == "Unknown Merchant" or
                    amount == "$0.00" or
                    date == "01012025"
                )

                return {
                    'merchant': merchant,
                    'amount': amount,
                    'date': date,
                    'subcategory': subcategory,
                    'needs_attention': needs_attention
                }
        except Exception as e:
            logging.error(f"OCR failed on {image_path}: {e}")
            return {
                'merchant': 'Error',
                'amount': 'Error',
                'date': 'Error',
                'subcategory': 'Error',
                'needs_attention': True,
                'error': str(e)
            }


# === ATOMIC WRITE UTILITIES ===
def atomic_write_file(filepath: Path, data: Any, serializer: Callable) -> bool:
    """Generic atomic write with backup protection"""
    bak_path = filepath.with_suffix(filepath.suffix + '.bak')
    tmp_path = filepath.with_suffix(filepath.suffix + '.tmp')

    try:
        if filepath.exists():
            shutil.copy2(filepath, bak_path)

        serializer(tmp_path, data)

        os.replace(tmp_path, filepath)

        if bak_path.exists():
            bak_path.unlink()

        return True
    except Exception as e:
        logging.error(f"Atomic write failed for {filepath}: {e}")
        if bak_path.exists():
            shutil.copy2(bak_path, filepath)
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def atomic_serialize_json(tmp_path: Path, data: Any):
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def atomic_serialize_csv(tmp_path: Path, rows: List[Dict], fieldnames: List[str]):
    with open(tmp_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# === BACKGROUND WORKER (From v1's threading model) ===
class ScanWorker(QObject):
    """Background worker for non-blocking OCR processing"""
    progress = Signal(str)
    finished = Signal()
    item_processed = Signal(dict)
    error = Signal(str)
    scan_complete = Signal(int, int, int)

    def __init__(self, search_root: Path, screenshot_folder: Path, ocr_engine: WestpacOCREngine, file_hashes: set):
        super().__init__()
        self.search_root = search_root
        self.screenshot_folder = screenshot_folder
        self.ocr_engine = ocr_engine
        self.file_hashes = file_hashes
        self.should_stop = False
        self.ocr_cache_file = EXE_DIR / "ocr_cache.json"

    def stop(self):
        self.should_stop = True

    def load_ocr_cache(self) -> Dict[str, Any]:
        if self.ocr_cache_file.exists():
            try:
                with open(self.ocr_cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_ocr_cache(self, cache: Dict[str, Any]):
        atomic_write_file(self.ocr_cache_file, cache, atomic_serialize_json)

    @staticmethod
    def calculate_hash(filepath: Path) -> str:
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def run(self):
        """Main scanning loop with progress reporting"""
        try:
            logging.info("=== BEGINNING SCAN ===")

            # Discover files
            all_files = []
            for root, dirs, files in os.walk(self.search_root):
                for file in files:
                    if file.startswith("Screenshot_") and file.endswith((".jpg", ".jpeg")):
                        all_files.append(Path(root) / file)

            if not all_files:
                self.progress.emit("No screenshots found")
                self.scan_complete.emit(0, 0, 0)
                self.finished.emit()
                return

            # Filter new files
            new_files = []
            for filepath in all_files:
                file_hash = self.calculate_hash(filepath)
                if file_hash not in self.file_hashes:
                    new_files.append((filepath, file_hash))

            if not new_files:
                self.progress.emit("No new files to process")
                self.scan_complete.emit(0, 0, 0)
                self.finished.emit()
                return

            total = len(new_files)
            self.progress.emit(f"Found {total} new files")

            # Load cache
            ocr_cache = self.load_ocr_cache()

            processed = 0
            attention = 0

            # Process each file
            for i, (filepath, file_hash) in enumerate(new_files):
                if self.should_stop:
                    break

                try:
                    self.progress.emit(
                        f"Processing ({i+1}/{total}): {filepath.name}")

                    # Check cache first
                    if file_hash in ocr_cache:
                        result = ocr_cache[file_hash].copy()
                        result['file_hash'] = file_hash
                        result['filepath'] = str(filepath)
                        result['filename'] = filepath.name
                    else:
                        # Perform OCR
                        result = self.ocr_engine.extract_transaction(filepath)
                        result['file_hash'] = file_hash
                        result['filepath'] = str(filepath)
                        result['filename'] = filepath.name
                        ocr_cache[file_hash] = result

                    # Check quality gate
                    if result.get('needs_attention', False):
                        attention += 1
                        self.item_processed.emit({
                            'file_hash': file_hash,
                            'filepath': str(filepath),
                            'needs_attention': True
                        })
                        continue

                    # Emit for processing
                    self.item_processed.emit(result)
                    processed += 1

                except Exception as e:
                    logging.error(f"Failed to process {filepath}: {e}")
                    self.error.emit(f"Error on {filepath.name}")

            # Save cache updates
            self.save_ocr_cache(ocr_cache)

            # Final progress
            self.progress.emit(
                f"Scan complete: {processed} processed, {attention} need attention")
            self.scan_complete.emit(processed, attention, total)
            self.finished.emit()

        except Exception as e:
            logging.critical(
                f"Scan worker critical error: {e}\n{traceback.format_exc()}")
            self.error.emit(f"Critical error: {e}")
            self.finished.emit()


# === MAIN APPLICATION ===
class NDISAssistant(QMainWindow):
    """Main application with threaded scanning and clean system separation"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NDIS Expense Assistant v3.0")
        self.resize(1300, 800)

        # Initialize systems
        self.ocr_engine = WestpacOCREngine()
        self.learning_system = LearningSystem(
            EXE_DIR / "merchant_knowledge.json")
        self.description_system = DescriptionSystem()

        # Data storage
        self.pending_data: List[Dict] = []
        self.completed_data: List[Dict] = []
        self.file_hashes: set = set()
        self.categories: List[str] = []

        # Config paths
        self.config_file = EXE_DIR / "config.ini"
        self.pending_csv = EXE_DIR / "pending.csv"
        self.completed_csv = EXE_DIR / "completed.csv"
        self.ocr_cache_file = EXE_DIR / "ocr_cache.json"

        # Worker thread
        self.scan_thread: Optional[QThread] = None
        self.scan_worker: Optional[ScanWorker] = None

        # UI timer for debounced saves
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_pending_csv)

        # Load everything
        self.load_config()
        self.ensure_data_files()
        self.load_data()

        # Build UI
        self.init_ui()

        logging.info("✅ Application fully initialized")

    def load_config(self):
        """Load configuration from QSettings"""
        settings = QSettings(str(self.config_file), QSettings.IniFormat)

        self.screenshot_folder = Path(settings.value(
            "Paths/screenshot_folder", str(EXE_DIR / "Screenshots")))
        self.search_root = Path(settings.value(
            "Paths/search_root", str(EXE_DIR)))

        categories_str = settings.value(
            "Categories/list", "Food;Transport;Medical;Client Session;Supplies;Other")
        self.categories = [c.strip()
                           for c in categories_str.split(";") if c.strip()]

        self.learning_threshold = int(settings.value("Learning/threshold", 2))

        logging.info(f"📁 Screenshot folder: {self.screenshot_folder}")
        logging.info(f"🔍 Search root: {self.search_root}")
        logging.info(f"🏷️  {len(self.categories)} categories loaded")
        logging.info(f"🎯 Learning threshold: {self.learning_threshold}")

    def save_config(self):
        """Save configuration via QSettings"""
        settings = QSettings(str(self.config_file), QSettings.IniFormat)
        settings.setValue("Paths/screenshot_folder",
                          str(self.screenshot_folder))
        settings.setValue("Paths/search_root", str(self.search_root))
        settings.setValue("Categories/list", ";".join(self.categories))
        settings.setValue("Learning/threshold", self.learning_threshold)

    def ensure_data_files(self):
        """Create CSV files and directories if missing"""
        # Create directories
        self.screenshot_folder.mkdir(parents=True, exist_ok=True)
        (self.screenshot_folder / "NEEDS_ATTENTION").mkdir(exist_ok=True)

        # Create CSV files with headers
        if not self.pending_csv.exists():
            with open(self.pending_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw',
                    'MerchantOCRValue', 'category', 'description', 'status'
                ])

        if not self.completed_csv.exists():
            with open(self.completed_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'file_hash', 'completed_timestamp', 'filename', 'date_raw',
                    'amount_raw', 'MerchantOCRValue', 'category', 'description', 'status'
                ])

    def load_data(self):
        """Load all data from storage"""
        # Load completed data and hashes
        if self.completed_csv.exists() and self.completed_csv.stat().st_size > 0:
            try:
                with open(self.completed_csv, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.completed_data = [row for row in reader]
                self.file_hashes.update(row['file_hash']
                                        for row in self.completed_data)
                logging.info(
                    f"✅ Loaded {len(self.completed_data)} completed items")
            except Exception as e:
                logging.error(f"Failed to load completed.csv: {e}")

        # Load pending data
        if self.pending_csv.exists() and self.pending_csv.stat().st_size > 0:
            try:
                with open(self.pending_csv, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.pending_data = [
                        row for row in reader if row.get('status') == 'pending']
                self.file_hashes.update(row['file_hash']
                                        for row in self.pending_data)
                logging.info(
                    f"✅ Loaded {len(self.pending_data)} pending items")
            except Exception as e:
                logging.error(f"Failed to load pending.csv: {e}")

    def init_ui(self):
        """Initialize user interface"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # === TOP BAR ===
        top_bar = QHBoxLayout()

        self.folder_label = QLabel(f"📁 {self.screenshot_folder.name}")
        self.folder_label.setToolTip(str(self.screenshot_folder))
        top_bar.addWidget(self.folder_label)

        browse_btn = QPushButton("📂 Browse Folder...")
        browse_btn.clicked.connect(self.browse_folder)
        top_bar.addWidget(browse_btn)

        self.scan_btn = QPushButton("🔍 Scan Now")
        self.scan_btn.clicked.connect(self.start_scan)
        top_bar.addWidget(self.scan_btn)

        settings_btn = QPushButton("⚙️ Settings")
        settings_btn.clicked.connect(self.edit_settings)
        top_bar.addWidget(settings_btn)

        layout.addLayout(top_bar)

        # === STATUS BAR ===
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-weight: bold; padding: 5px;")
        status_layout.addWidget(self.status_label, stretch=1)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #666; padding: 5px;")
        status_layout.addWidget(self.progress_label)

        layout.addWidget(status_widget)

        # === TOGGLE BUTTON ===
        self.toggle_btn = QPushButton("Show Completed")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.toggle_view)
        layout.addWidget(self.toggle_btn)

        # === MAIN TABLE ===
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Date (DDMMYYYY)", "Amount", "Merchant", "Category", "Description", "Actions"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        # === BUTTON BAR ===
        button_bar = QHBoxLayout()

        export_btn = QPushButton("📤 Export Completed")
        export_btn.clicked.connect(self.export_history)
        button_bar.addWidget(export_btn)

        button_bar.addStretch()

        exit_btn = QPushButton("💾 Save & Exit")
        exit_btn.clicked.connect(self.save_and_exit)
        button_bar.addWidget(exit_btn)

        layout.addLayout(button_bar)

        # === INITIAL LOAD ===
        self.refresh_table()

    def start_scan(self):
        """Start background scan thread"""
        self.scan_btn.setEnabled(False)
        self.status_label.setText("⏳ Scanning in background...")
        self.progress_label.setText("")

        # Create worker and thread
        self.scan_thread = QThread()
        self.scan_worker = ScanWorker(
            self.search_root,
            self.screenshot_folder,
            self.ocr_engine,
            self.file_hashes
        )
        self.scan_worker.moveToThread(self.scan_thread)

        # Connect signals
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress.connect(self.progress_label.setText)
        self.scan_worker.item_processed.connect(self.on_item_processed)
        self.scan_worker.scan_complete.connect(self.on_scan_complete)
        self.scan_worker.error.connect(self.show_error)
        self.scan_worker.finished.connect(self.scan_thread.quit)

        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.finished.connect(self.scan_worker.deleteLater)

        self.scan_thread.start()

    def on_item_processed(self, result: dict):
        """Handle processed item from worker thread"""
        if result.get('needs_attention'):
            # Move to attention folder
            src = Path(result['filepath'])
            dst = self.screenshot_folder / "NEEDS_ATTENTION" / src.name
            try:
                shutil.move(src, dst)
                logging.warning(f"⚠️  Moved {src.name} to NEEDS_ATTENTION")
            except Exception as e:
                logging.error(f"Failed to move {src}: {e}")
        else:
            # Suggest category from learning system
            merchant = result['MerchantOCRValue']
            suggested = self.learning_system.get_suggested_category(
                merchant, self.learning_threshold)

            item = {
                'file_hash': result['file_hash'],
                'filename': result['filename'],
                'filepath': result['filepath'],
                'date_raw': result['date'],
                'amount_raw': result['amount'],
                'MerchantOCRValue': merchant,
                'category': suggested or "",
                'description': self.description_system.format_description(suggested or "", ""),
                'status': 'pending'
            }

            self.pending_data.append(item)
            self.file_hashes.add(item['file_hash'])

            # Auto-save every 10 items
            if len(self.pending_data) % 10 == 0:
                self.save_pending_csv()

    def on_scan_complete(self, processed: int, attention: int, total: int):
        """Handle scan completion"""
        self.scan_btn.setEnabled(True)
        self.save_pending_csv()
        self.refresh_table()

        msg = f"✅ Scan complete | Processed: {processed} | Needs Attention: {attention}"
        self.status_label.setText(msg)
        self.progress_label.setText("")

        if attention > 0:
            QMessageBox.information(
                self, "Scan Complete",
                f"Processed {processed} screenshots.\n\n"
                f"{attention} files require manual attention and were moved to:\n"
                f"{self.screenshot_folder / 'NEEDS_ATTENTION'}"
            )

    def refresh_table(self):
        """Refresh table based on current view"""
        self.table.setRowCount(0)

        if self.toggle_btn.isChecked():
            self.show_completed()
        else:
            self.show_pending()

    def show_pending(self):
        """Display pending items with full interactivity"""
        self.table.setRowCount(len(self.pending_data))

        for row, item in enumerate(self.pending_data):
            # Date (editable)
            date_item = QTableWidgetItem(item['date_raw'])
            self.table.setItem(row, 0, date_item)

            # Amount (editable)
            amount_item = QTableWidgetItem(item['amount_raw'])
            self.table.setItem(row, 1, amount_item)

            # Merchant (read-only)
            merchant_item = QTableWidgetItem(item['MerchantOCRValue'])
            merchant_item.setFlags(merchant_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, merchant_item)

            # Category dropdown with learning
            category_combo = QComboBox()
            category_combo.addItems([""] + self.categories)

            # Set suggested category if exists
            current_cat = item.get('category', '')
            if not current_cat:
                suggested = self.learning_system.get_suggested_category(
                    item['MerchantOCRValue'],
                    self.learning_threshold
                )
                if suggested:
                    current_cat = suggested
                    item['category'] = suggested
                    # Auto-update description
                    item['description'] = self.description_system.format_description(
                        suggested, "")

            category_combo.setCurrentText(current_cat)
            category_combo.currentTextChanged.connect(
                lambda text, r=row: self.update_category(r, text)
            )
            self.table.setCellWidget(row, 3, category_combo)

            # Description (editable)
            desc_item = QTableWidgetItem(item['description'])
            desc_item.setFlags(desc_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 4, desc_item)

            # Actions
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)

            view_btn = QPushButton("👁️")
            view_btn.setToolTip("View screenshot")
            view_btn.clicked.connect(
                lambda _, p=item['filepath']: self.view_image(p))
            actions_layout.addWidget(view_btn)

            done_btn = QPushButton("✓ Done")
            done_btn.setToolTip("Mark as completed")
            done_btn.clicked.connect(lambda _, r=row: self.mark_done(r))
            actions_layout.addWidget(done_btn)

            self.table.setCellWidget(row, 5, actions_widget)

        self.status_label.setText(
            f"📋 Showing {len(self.pending_data)} pending items")

    def show_completed(self):
        """Display completed items (read-only)"""
        self.table.setRowCount(len(self.completed_data))

        for row, item in enumerate(self.completed_data):
            self.table.setItem(row, 0, QTableWidgetItem(item['date_raw']))
            self.table.setItem(row, 1, QTableWidgetItem(item['amount_raw']))
            self.table.setItem(row, 2, QTableWidgetItem(
                item['MerchantOCRValue']))
            self.table.setItem(row, 3, QTableWidgetItem(item['category']))
            self.table.setItem(row, 4, QTableWidgetItem(item['description']))

            # No actions for completed items
            self.table.setCellWidget(row, 5, QWidget())

        self.status_label.setText(
            f"✅ Showing {len(self.completed_data)} completed items")

    def update_category(self, row: int, category: str):
        """Update category and preserve description user note"""
        if 0 <= row < len(self.pending_data):
            item = self.pending_data[row]
            old_category = item['category']
            item['category'] = category

            # Update description preserving user note
            if category:
                item['description'] = self.description_system.update_description(
                    item['description'],
                    category
                )
                self.table.item(row, 4).setText(item['description'])

            logging.info(
                f"🏷️  {item['MerchantOCRValue']}: {old_category} → {category}")
            self.save_timer.start(500)  # Debounced save

    def view_image(self, filepath: str):
        """Open image in default viewer (cross-platform)"""
        path = Path(filepath)
        if path.exists():
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":  # macOS
                os.system(f"open '{path}'")
            else:  # Linux
                os.system(f"xdg-open '{path}'")
        else:
            self.show_error(f"Image not found:\n{path}")

    def mark_done(self, row: int):
        """Mark item as done and trigger learning"""
        if 0 <= row < len(self.pending_data):
            # Cancel any pending save
            self.save_timer.stop()

            item = self.pending_data.pop(row)

            # Get final values from UI
            category = self.table.cellWidget(row, 3).currentText()
            description = self.table.item(row, 4).text()

            # Update item
            item['category'] = category
            item['description'] = description
            item['status'] = 'done'
            item['completed_timestamp'] = datetime.utcnow().isoformat() + 'Z'

            # Record learning
            self.learning_system.learn_confirmation(
                item['MerchantOCRValue'], category)

            # Save to completed
            self.save_completed(item)

            # Update pending CSV
            self.save_pending_csv()

            # Refresh table
            self.refresh_table()

            self.status_label.setText(f"✓ Marked done: {item['filename']}")

    def save_pending_csv(self):
        """Atomic save of pending data"""
        fieldnames = [
            'file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw',
            'MerchantOCRValue', 'category', 'description', 'status'
        ]

        rows = []
        for item in self.pending_data:
            rows.append({
                'file_hash': item['file_hash'],
                'filename': item['filename'],
                'filepath': item['filepath'],
                'date_raw': item['date_raw'],
                'amount_raw': item['amount_raw'],
                'MerchantOCRValue': item['MerchantOCRValue'],
                'category': item.get('category', ''),
                'description': item.get('description', ''),
                'status': 'pending'
            })

        success = atomic_write_file(self.pending_csv, rows,
                                    lambda p, d: atomic_serialize_csv(p, d, fieldnames))
        if not success:
            self.show_error("Failed to save pending data")

    def save_completed(self, item: dict):
        """Append completed item atomically"""
        fieldnames = [
            'file_hash', 'completed_timestamp', 'filename', 'date_raw',
            'amount_raw', 'MerchantOCRValue', 'category', 'description', 'status'
        ]

        # Load existing
        rows = []
        if self.completed_csv.exists() and self.completed_csv.stat().st_size > 0:
            with open(self.completed_csv, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        # Add new item
        rows.append({
            'file_hash': item['file_hash'],
            'completed_timestamp': item['completed_timestamp'],
            'filename': item['filename'],
            'date_raw': item['date_raw'],
            'amount_raw': item['amount_raw'],
            'MerchantOCRValue': item['MerchantOCRValue'],
            'category': item['category'],
            'description': item['description'],
            'status': 'done'
        })

        success = atomic_write_file(self.completed_csv, rows,
                                    lambda p, d: atomic_serialize_csv(p, d, fieldnames))
        if not success:
            self.show_error("Failed to save completed data")

    def toggle_view(self):
        """Toggle between pending and completed view"""
        is_completed = self.toggle_btn.isChecked()
        self.toggle_btn.setText(
            "Show Pending" if is_completed else "Show Completed")
        self.refresh_table()

    def browse_folder(self):
        """Browse for screenshot folder"""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Screenshot Folder", str(self.screenshot_folder)
        )
        if folder:
            self.screenshot_folder = Path(folder)
            self.folder_label.setText(f"📁 {self.screenshot_folder.name}")
            self.folder_label.setToolTip(str(self.screenshot_folder))
            self.save_config()
            self.status_label.setText(f"📁 Folder changed: {folder}")

    def edit_settings(self):
        """Edit categories and learning threshold"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.resize(500, 400)

        layout = QVBoxLayout(dialog)

        # Categories
        layout.addWidget(QLabel("Categories (one per line):"))
        categories_edit = QTextEdit()
        categories_edit.setPlainText("\n".join(self.categories))
        layout.addWidget(categories_edit)

        # Learning threshold
        layout.addWidget(
            QLabel("Learning Threshold (confirmations needed for auto-suggest):"))
        threshold_edit = QLineEdit(str(self.learning_threshold))
        layout.addWidget(threshold_edit)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            # Save categories
            text = categories_edit.toPlainText().strip()
            self.categories = [c.strip()
                               for c in text.split("\n") if c.strip()]

            # Save threshold
            try:
                self.learning_threshold = int(threshold_edit.text())
            except:
                self.learning_threshold = 2

            self.save_config()
            self.refresh_table()
            self.status_label.setText("⚙️ Settings saved")

    def export_history(self):
        """Export completed.csv to user's home directory"""
        if not self.completed_csv.exists() or self.completed_csv.stat().st_size == 0:
            self.show_error("No completed data to export")
            return

        # Cross-platform desktop/home directory
        if sys.platform == "win32":
            export_dir = Path(os.path.expanduser("~/Desktop"))
        else:
            export_dir = Path.home()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = export_dir / f"NDIS_Export_{timestamp}.csv"

        try:
            shutil.copy2(self.completed_csv, export_path)
            QMessageBox.information(
                self, "Export Success",
                f"📤 Exported to:\n{export_path}\n\n{len(self.completed_data)} records"
            )
            logging.info(
                f"Exported {len(self.completed_data)} records to {export_path}")
        except Exception as e:
            self.show_error(f"Export failed: {e}")

    def show_error(self, message: str):
        """Show error dialog and log"""
        logging.error(f"❌ User error: {message}")
        QMessageBox.warning(self, "Error", message)

    def save_and_exit(self):
        """Clean shutdown"""
        # Stop any pending save
        self.save_timer.stop()

        # Save current state
        self.save_pending_csv()
        self.learning_system.save_knowledge_atomic()

        # Wait for thread
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_worker.stop()
            self.scan_thread.quit()
            self.scan_thread.wait()

        logging.info("👋 Application closing normally")
        self.close()

    def closeEvent(self, event: QCloseEvent):
        """Handle window close"""
        self.save_and_exit()
        event.accept()


# === MAIN ENTRY POINT ===
def main():
    """Application entry point"""
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("NDIS Expense Assistant v3.0")

        window = NDISAssistant()
        window.show()

        logging.info("🚀 Application started")
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"💥 Fatal error: {e}\n{traceback.format_exc()}")
        QMessageBox.critical(
            None,
            "Fatal Error",
            f"Application crashed:\n{e}\n\nCheck {LOG_FILE} for details"
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
