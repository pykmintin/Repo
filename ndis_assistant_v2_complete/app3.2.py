#!/usr/bin/env python3
"""
NDIS Expense Assistant v3.2 - Production Ready
Thread-safe, atomic transactions, correct bulk operations
"""

import os
import sys
import csv
import re
import hashlib
import json
import shutil
import logging
import logging.handlers
import traceback
import enum
import threading
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Any, Callable, Tuple, Set
from dataclasses import dataclass, asdict
from contextlib import contextmanager

# === VERSION & SCHEMA MANAGEMENT ===
APP_VERSION = "3.2.0"
SCHEMA_VERSION = "2.0"

# === LOGGING SETUP with Rotation ===
EXE_DIR = Path(__file__).parent.resolve()
LOG_FILE = EXE_DIR / "app.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        ),
        logging.StreamHandler()
    ]
)
logging.info(
    f"=== NDIS EXPENSE ASSISTANT v{APP_VERSION} STARTUP (Schema {SCHEMA_VERSION}) ===")

# === IMPORTS ===
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTableWidget, QTableWidgetItem, QLabel, QPushButton, QComboBox,
        QFileDialog, QMessageBox, QDialog, QLineEdit, QTextEdit,
        QDialogButtonBox, QCheckBox, QHeaderView, QProgressDialog,
        QMenu, QInputDialog
    )
    from PySide6.QtCore import Qt, QSettings, QTimer, QObject, Signal, QThread, QItemSelectionModel
    from PySide6.QtGui import QAction, QKeySequence, QCloseEvent
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

# === ENUMS & CONSTANTS ===


class ItemStatus(enum.Enum):
    PENDING = "pending"
    DONE = "done"


class ColumnIndex(enum.IntEnum):
    DATE = 0
    AMOUNT = 1
    MERCHANT = 2
    CATEGORY = 3
    DESCRIPTION = 4
    ACTIONS = 5


DEFAULT_DATE = "01012025"
DEFAULT_AMOUNT = "$0.00"
FALLBACK_CATEGORY = "Uncategorised"

# === DATACLASSES ===


@dataclass
class TransactionItem:
    file_hash: str
    filename: str
    filepath: Path
    date_raw: str
    amount_raw: str
    MerchantOCRValue: str
    category: str
    description: str
    status: str
    completed_timestamp: Optional[str] = None


@dataclass
class MerchantKnowledge:
    merchant: str
    category: str
    confirmations: int
    first_seen: str
    last_confirmed: str


@dataclass
class OCRCacheEntry:
    merchant: str
    amount: str
    date: str
    subcategory: str
    needs_attention: bool
    error: Optional[str] = None

# === VALIDATION LAYER (Define Early) ===


class ValidationError(Exception):
    pass


class Validator:
    """Central validation logic"""

    DATE_PATTERN = re.compile(r'^\d{8}$')
    AMOUNT_PATTERN = re.compile(r'^-\$\d+\.\d{2}$')

    @staticmethod
    def validate_date(date_str: str) -> str:
        """Validate DDMMYYYY format and logical date"""
        if not Validator.DATE_PATTERN.match(date_str):
            raise ValidationError(
                f"Invalid date format: {date_str}. Expected DDMMYYYY.")

        day, month, year = int(date_str[:2]), int(
            date_str[2:4]), int(date_str[4:])

        if not (1 <= day <= 31):
            raise ValidationError(f"Invalid day: {day}")
        if not (1 <= month <= 12):
            raise ValidationError(f"Invalid month: {month}")
        if year < 2020 or year > 2030:
            raise ValidationError(f"Suspicious year: {year}")

        return date_str

    @staticmethod
    def validate_amount(amount_str: str) -> str:
        """Validate amount format"""
        if not Validator.AMOUNT_PATTERN.match(amount_str):
            raise ValidationError(
                f"Invalid amount format: {amount_str}. Expected -$XX.XX")

        # Prevent default values
        if amount_str == DEFAULT_AMOUNT:
            raise ValidationError("Amount cannot be default value $0.00")

        return amount_str

    @staticmethod
    def validate_merchant(merchant: str) -> str:
        """Validate merchant name"""
        merchant = merchant.strip()
        if not merchant or merchant == "Unknown Merchant":
            raise ValidationError("Invalid merchant name")
        if len(merchant) < 2:
            raise ValidationError("Merchant name too short")
        return merchant

    @staticmethod
    def validate_category(category: str, allowed_categories: List[str]) -> str:
        """Validate category against allowed list"""
        if category not in allowed_categories:
            raise ValidationError(f"Category '{category}' not in allowed list")
        return category

# === LRU CACHE (Define Early) ===


class LRUCache:
    """Least Recently Used cache for OCR results"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: Dict[str, OCRCacheEntry] = {}
        self.access_order: List[str] = []

    def get(self, file_hash: str) -> Optional[OCRCacheEntry]:
        if file_hash in self.cache:
            self.access_order.remove(file_hash)
            self.access_order.insert(0, file_hash)
            return self.cache[file_hash]
        return None

    def put(self, file_hash: str, entry: OCRCacheEntry):
        if file_hash in self.cache:
            self.access_order.remove(file_hash)
        elif len(self.cache) >= self.max_size:
            lru_hash = self.access_order.pop()
            del self.cache[lru_hash]

        self.cache[file_hash] = entry
        self.access_order.insert(0, file_hash)

    def load_from_file(self, filepath: Path):
        if not filepath.exists():
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, dict) and 'entries' in data:
                for file_hash, entry_data in data['entries'].items():
                    self.put(file_hash, OCRCacheEntry(**entry_data))

            logging.info(f"📦 Loaded OCR cache: {len(self.cache)} entries")

        except Exception as e:
            logging.error(f"Failed to load OCR cache: {e}")

    def save_to_file(self, filepath: Path) -> bool:
        try:
            data = {
                'schema_version': SCHEMA_VERSION,
                'entries': {h: asdict(e) for h, e in self.cache.items()}
            }

            tmp_path = filepath.with_suffix('.json.tmp')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            os.replace(tmp_path, filepath)
            return True

        except Exception as e:
            logging.error(f"Failed to save OCR cache: {e}")
            return False

# === SEARCH & FILTER (Define Early) ===


class SearchFilter:
    """Handles table search and filtering"""

    def __init__(self):
        self.query = ""
        self.category_filter = ""

    def matches(self, item: TransactionItem) -> bool:
        if self.query:
            query_lower = self.query.lower()
            if not (
                query_lower in item.MerchantOCRValue.lower() or
                query_lower in item.description.lower() or
                query_lower in item.category.lower()
            ):
                return False

        if self.category_filter and item.category != self.category_filter:
            return False

        return True

# === DESCRIPTION SYSTEM (Define Early) ===


class DescriptionSystem:
    @staticmethod
    def format_description(category: str, user_note: str = "") -> str:
        if not user_note or user_note.strip() == category.strip():
            return category
        return f"{category} - {user_note}"

    @staticmethod
    def extract_parts(description: str) -> Tuple[str, str]:
        if not description:
            return "", ""
        if " - " in description:
            parts = description.split(" - ", 1)
            return parts[0], parts[1]
        return "", description

    @staticmethod
    def update_description(current_desc: str, new_category: str) -> str:
        if not current_desc:
            return new_category
        if " - " in current_desc:
            _, user_note = current_desc.split(" - ", 1)
            return f"{new_category} - {user_note}"
        else:
            return f"{new_category} - {current_desc}"

# === LEARNING SYSTEM (Define Early) ===


class LearningSystem:
    """Enhanced learning with LRU eviction and better persistence"""

    MAX_KNOWLEDGE_ENTRIES = 10000

    def __init__(self, knowledge_file: Path):
        self.knowledge_file = knowledge_file
        self.knowledge_file_bak = knowledge_file.with_suffix('.json.bak')
        self.knowledge_file_tmp = knowledge_file.with_suffix('.json.tmp')
        self.merchant_knowledge: List[MerchantKnowledge] = []
        self.load_knowledge()

    def load_knowledge(self) -> None:
        if not self.knowledge_file.exists():
            self.merchant_knowledge = []
            return

        try:
            with open(self.knowledge_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, dict) and data.get('schema_version') == SCHEMA_VERSION:
                self.merchant_knowledge = [
                    MerchantKnowledge(**entry) for entry in data.get('entries', [])
                ]
            else:
                self.merchant_knowledge = [
                    MerchantKnowledge(
                        merchant=entry['merchant'],
                        category=entry['category'],
                        confirmations=entry.get('confirmations', 1),
                        first_seen=entry.get(
                            'first_seen', datetime.utcnow().isoformat() + 'Z'),
                        last_confirmed=entry.get(
                            'last_confirmed', datetime.utcnow().isoformat() + 'Z')
                    ) for entry in data
                ]
                self.save_knowledge_atomic()

            logging.info(
                f"📚 Loaded {len(self.merchant_knowledge)} knowledge entries")

        except Exception as e:
            logging.error(f"Failed to load knowledge: {e}")
            self.merchant_knowledge = []

    def save_knowledge_atomic(self) -> bool:
        try:
            if self.knowledge_file.exists():
                shutil.copy2(self.knowledge_file, self.knowledge_file_bak)

            data = {
                'schema_version': SCHEMA_VERSION,
                'entries': [asdict(entry) for entry in self.merchant_knowledge]
            }

            with open(self.knowledge_file_tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            os.replace(self.knowledge_file_tmp, self.knowledge_file)

            if self.knowledge_file_bak.exists():
                self.knowledge_file_bak.unlink()

            return True
        except Exception as e:
            logging.error(f"Save failed: {e}")
            if self.knowledge_file_bak.exists():
                shutil.copy2(self.knowledge_file_bak, self.knowledge_file)
            return False

    def learn_confirmation(self, merchant: str, category: str) -> None:
        normalized = merchant.lower().strip()
        category = category.strip()

        if not normalized or not category:
            return

        for entry in self.merchant_knowledge:
            if entry.merchant == normalized and entry.category == category:
                entry.confirmations += 1
                entry.last_confirmed = datetime.utcnow().isoformat() + 'Z'
                logging.info(
                    f"⬆️  Updated {normalized} -> {category} ({entry.confirmations}x)")
                self.save_knowledge_atomic()
                return

        if len(self.merchant_knowledge) >= self.MAX_KNOWLEDGE_ENTRIES:
            self.merchant_knowledge.sort(key=lambda x: x.last_confirmed)
            removed = self.merchant_knowledge.pop(0)
            logging.warning(f"🗑️  Evicted old knowledge: {removed.merchant}")

        self.merchant_knowledge.append(MerchantKnowledge(
            merchant=normalized,
            category=category,
            confirmations=1,
            first_seen=datetime.utcnow().isoformat() + 'Z',
            last_confirmed=datetime.utcnow().isoformat() + 'Z'
        ))
        logging.info(f"✏️  Learned {normalized} -> {category}")
        self.save_knowledge_atomic()

    def get_suggested_category(self, merchant: str, threshold: int = 2) -> Optional[str]:
        normalized = merchant.lower().strip()
        if not normalized:
            return None

        category_counts = defaultdict(int)
        for entry in self.merchant_knowledge:
            if entry.merchant == normalized:
                category_counts[entry.category] += entry.confirmations

        if category_counts:
            most_frequent, count = max(
                category_counts.items(), key=lambda x: x[1])
            if count >= threshold:
                logging.debug(
                    f"💡 Suggesting '{most_frequent}' for '{merchant}' (confidence: {count})")
                return most_frequent

        return None

# === WESTPAC OCR ENGINE (Define Early) ===


class WestpacOCREngine:
    """Production-grade OCR engine for Westpac screenshots"""

    def __init__(self):
        self.amount_patterns = [re.compile(p) for p in [
            r'\-\$\d+\.\d{2}', r'\$\-\d+\.\d{2}', r'\-\d+\.\d{2}', r'\d+\.\d{2}'
        ]]

        self.date_patterns = [re.compile(p, re.IGNORECASE) for p in [
            r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})'
        ]]

        self.merchant_corrections = {
            'bokeies delight': 'Bakers Delight', 'bokees delight': 'Bakers Delight',
            'bokies delight': 'Bakers Delight', 'delightt': 'Delight',
            'traralgongon': 'Traralgon', '4ae. health': 'Central Gippsland Health',
            'mn,': 'ALDI Mobile', 'alid': 'ALDI',
        }

        self.keyword_categories = {
            'bakery': 'Bakery', 'baker': 'Bakery', 'delight': 'Bakery',
            'muffin': 'Restaurants & Dining', 'break': 'Restaurants & Dining',
            'restaurant': 'Restaurants & Dining', 'dining': 'Restaurants & Dining',
            'food': 'Restaurants & Dining', 'cafe': 'Restaurants & Dining',
            'coffee': 'Restaurants & Dining', 'espresso': 'Restaurants & Dining',
            'health': 'Healthcare', 'medical': 'Healthcare',
            'mobile': 'Utilities', 'phone': 'Utilities', 'aldi': 'Utilities',
        }


        self.skip_patterns = [re.compile(p, re.IGNORECASE) for p in [
            r'%', r'8:', r'@', r'[|]', r'Westpac', r'Account', r'Subcategory',
            r'\d{1,2}:\d{2}', r'\d{1,3}%', r'\d{4}-\d{3}',
            r'Edit$', r'Tags$', r'None$', r'time$', r'transaction$',
            r'^\d+$', r'^\W+$',
        ]]

    def extract_transaction(self, image_path: Path) -> OCRCacheEntry:
        try:
            with Image.open(image_path) as img:
                processed = self.preprocess_image(img)
                text = pytesseract.image_to_string(processed, config='--psm 6')

                merchant = self._extract_merchant(text)
                amount = self._extract_amount(text)
                date = self._extract_date(text)
                subcategory = self._extract_subcategory(text, merchant)

                needs_attention = False
                try:
                    Validator.validate_merchant(merchant)
                except ValidationError:
                    needs_attention = True

                try:
                    Validator.validate_amount(amount)
                except ValidationError:
                    needs_attention = True

                try:
                    Validator.validate_date(date)
                except ValidationError:
                    needs_attention = True

                return OCRCacheEntry(
                    merchant=merchant,
                    amount=amount,
                    date=date,
                    subcategory=subcategory,
                    needs_attention=needs_attention
                )

        except Exception as e:
            logging.error(f"OCR failed on {image_path}: {e}")
            return OCRCacheEntry(
                merchant='Error',
                amount=DEFAULT_AMOUNT,
                date=DEFAULT_DATE,
                subcategory=FALLBACK_CATEGORY,
                needs_attention=True,
                error=str(e)
            )

    def preprocess_image(self, image: Image.Image) -> np.ndarray:
        try:
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

            height, width = img.shape[:2]
            if width > height:
                img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

            target_height = 2400
            scale = target_height / img.shape[0]
            img = cv2.resize(img, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_LANCZOS4)

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)

            return denoised

        except Exception as e:
            logging.error(f"Preprocessing failed: {e}")
            raise

    def _extract_merchant(self, text: str) -> str:
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        candidates = []

        for line in lines:
            if any(pattern.search(line) for pattern in self.skip_patterns):
                continue

            if (len(line) < 3 or line.isdigit() or
                line in ['Edit', 'Tags', 'None', 'Account', 'Subcategory'] or
                    'time' in line.lower() or 'transaction' in line.lower()):
                continue

            merchant = re.sub(r'\s+', ' ', line).strip(' -_()<>')
            if len(merchant) >= 3:
                candidates.append(merchant)

        if candidates:
            for candidate in candidates:
                if any(word in candidate.lower() for word in self.keyword_categories.keys()):
                    return self._correct_merchant(candidate)
            return self._correct_merchant(candidates[0])

        return "Unknown Merchant"

    def _extract_amount(self, text: str) -> str:
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for pattern in self.amount_patterns:
            for line in lines:
                if match := pattern.search(line):
                    amount = match.group()
                    if number_match := re.search(r'(\d+\.\d{2})', amount):
                        number = number_match.group(1)
                        return f"-${number}"
        return DEFAULT_AMOUNT

    def _extract_date(self, text: str) -> str:
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        month_dict = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
        }

        for pattern in self.date_patterns:
            for line in lines:
                if matches := pattern.findall(line):
                    match = matches[0]
                    if isinstance(match, tuple):
                        if len(match) == 4:
                            day = match[1].zfill(2)
                            month = month_dict.get(match[2], "01")
                            year = match[3]
                            return f"{day}{month}{year}"
                        elif len(match) == 3:
                            day = match[0].zfill(2)
                            month = month_dict.get(match[1], "01")
                            year = match[2]
                            return f"{day}{month}{year}"

        return DEFAULT_DATE

    def _extract_subcategory(self, text: str, merchant: str) -> str:
        text_lower = text.lower()
        merchant_lower = merchant.lower()

        for keyword, category in self.keyword_categories.items():
            if keyword in merchant_lower or keyword in text_lower:
                return category

        return FALLBACK_CATEGORY

    def _correct_merchant(self, merchant: str) -> str:
        merchant_lower = merchant.lower()
        for error, correction in self.merchant_corrections.items():
            if error in merchant_lower:
                return correction

        merchant = re.sub(r'[~*]', '', merchant)
        merchant = re.sub(r'\s+', ' ', merchant)
        return merchant.strip(' -_()<>')

# === THREAD-SAFE DATA MANAGER ===


class DataManager:
    """Thread-safe wrapper for all shared data structures"""

    def __init__(self):
        self._lock = threading.RLock()
        self._pending: List[TransactionItem] = []
        self._completed: List[TransactionItem] = []
        self._hashes: Set[str] = set()

    @contextmanager
    def access(self):
        """Thread-safe context for data operations"""
        with self._lock:
            yield self

    @property
    def pending(self) -> List[TransactionItem]:
        """Get copy of pending data"""
        with self._lock:
            return self._pending.copy()

    @property
    def completed(self) -> List[TransactionItem]:
        """Get copy of completed data"""
        with self._lock:
            return self._completed.copy()

    @property
    def hashes(self) -> Set[str]:
        """Get copy of file hashes"""
        with self._lock:
            return self._hashes.copy()

    def add_pending(self, item: TransactionItem):
        """Add pending item (thread-safe)"""
        with self._lock:
            self._pending.append(item)
            self._hashes.add(item.file_hash)

    def remove_pending(self, index: int) -> TransactionItem:
        """Remove pending item by index (thread-safe)"""
        with self._lock:
            return self._pending.pop(index)

    def append_completed(self, item: TransactionItem):
        """Append completed item (thread-safe)"""
        with self._lock:
            self._completed.append(item)
            self._hashes.add(item.file_hash)

# === TRANSACTION MANAGER (Integrated) ===


class TransactionManager:
    """Ensures atomic: CSV update succeeds, THEN files move"""

    def __init__(self, data_manager: DataManager):
        self.data_manager = data_manager
        self.staged_moves: List[Tuple[Path, Path]] = []

    def stage_file_move(self, src: Path, dst_dir: Path) -> Optional[Path]:
        """Stage a file move operation"""
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            self.staged_moves.append((src, dst))
            return dst
        except Exception as e:
            logging.error(f"Failed to stage move: {e}")
            return None

    def commit(self, csv_callback: Callable[[], bool]) -> bool:
        """Execute: CSV first, then all staged file moves"""
        try:
            if not csv_callback():
                raise Exception("CSV callback failed")

            for src, dst in self.staged_moves:
                shutil.move(src, dst)
                logging.info(f"📁 Moved {src.name} -> {dst.parent.name}")

            self.staged_moves.clear()
            logging.info("✅ Transaction committed")
            return True
        except Exception as e:
            logging.error(f"❌ Transaction failed: {e}")
            self.rollback()
            return False

    def rollback(self):
        """Clear staged moves without executing"""
        self.staged_moves.clear()
        logging.warning("🔄 Transaction rolled back")

# === BACKGROUND WORKER (Thread-Safe) ===


class ScanWorker(QObject):
    progress = Signal(str)
    finished = Signal()
    item_processed = Signal(dict)
    scan_complete = Signal(int, int, int)
    error = Signal(str)

    def __init__(self, search_root: Path, screenshot_folder: Path,
                 ocr_engine: WestpacOCREngine, data_manager: DataManager,
                 lru_cache: LRUCache):
        super().__init__()
        self.search_root = search_root
        self.screenshot_folder = screenshot_folder
        self.ocr_engine = ocr_engine
        self.data_manager = data_manager
        self.lru_cache = lru_cache
        self.should_stop = False
        self.transaction_manager = TransactionManager(data_manager)

    def stop(self):
        self.should_stop = True

    @staticmethod
    def calculate_hash(filepath: Path) -> str:
        """SHA256 for deduplication"""
        hasher = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def run(self):
        """Main scanning loop with transactions"""
        try:
            logging.info("=== BEGINNING SCAN ===")

            all_files = []
            for root, dirs, files in os.walk(self.search_root):
                for file in files:
                    if file.startswith("Screenshot_") and file.endswith((".jpg", ".jpeg")):
                        all_files.append(Path(root) / file)

            if not all_files:
                self.scan_complete.emit(0, 0, 0)
                self.finished.emit()
                return

            data_hashes = self.data_manager.hashes
            new_files = []
            for filepath in all_files:
                file_hash = self.calculate_hash(filepath)
                if file_hash not in data_hashes:
                    new_files.append((filepath, file_hash))

            if not new_files:
                self.scan_complete.emit(0, 0, 0)
                self.finished.emit()
                return

            total = len(new_files)
            self.progress.emit(f"Found {total} new files")

            processed = 0
            attention = 0

            for i, (filepath, file_hash) in enumerate(new_files):
                if self.should_stop:
                    break

                try:
                    self.progress.emit(
                        f"Processing ({i+1}/{total}): {filepath.name}")

                    cached = self.lru_cache.get(file_hash)
                    if cached:
                        result = cached
                    else:
                        result = self.ocr_engine.extract_transaction(filepath)
                        self.lru_cache.put(file_hash, result)

                    if result.needs_attention:
                        dst_dir = self.screenshot_folder / "NEEDS_ATTENTION"
                    else:
                        date_raw = result.date
                        if len(date_raw) == 8:
                            year = date_raw[4:8]
                            month = date_raw[2:4]
                            dst_dir = self.screenshot_folder / \
                                f"{year}-{month}"
                        else:
                            dst_dir = self.screenshot_folder / "Organized"

                    final_path = self.transaction_manager.stage_file_move(
                        filepath, dst_dir)

                    if final_path:
                        def csv_callback():
                            self.data_manager.add_pending(TransactionItem(
                                file_hash=file_hash,
                                filename=filepath.name,
                                filepath=final_path,
                                date_raw=result.date,
                                amount_raw=result.amount,
                                MerchantOCRValue=result.merchant,
                                category="",
                                description="",
                                status=ItemStatus.PENDING.value
                            ))
                            return True

                        if self.transaction_manager.commit(csv_callback):
                            self.item_processed.emit({
                                'file_hash': file_hash,
                                'filename': filepath.name,
                                'filepath': str(final_path),
                                'date': result.date,
                                'amount': result.amount,
                                'merchant': result.merchant,
                                'subcategory': result.subcategory,
                                'needs_attention': result.needs_attention
                            })

                            if result.needs_attention:
                                attention += 1
                            else:
                                processed += 1
                        else:
                            attention += 1
                    else:
                        attention += 1

                except Exception as e:
                    logging.error(f"Failed to process {filepath}: {e}")
                    self.error.emit(f"Error on {filepath.name}")

            self.progress.emit(
                f"Scan complete: {processed} processed, {attention} need attention")
            self.scan_complete.emit(processed, attention, total)
            self.finished.emit()

        except Exception as e:
            logging.critical(
                f"Scan worker error: {e}\n{traceback.format_exc()}")
            self.error.emit(f"Critical error: {e}")
            self.finished.emit()

# === MANUAL ENTRY DIALOG ===


class ManualEntryDialog(QDialog):
    def __init__(self, filepath: Path, categories: List[str], parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.categories = categories
        self.setWindowTitle(f"Manual Entry: {filepath.name}")
        self.resize(450, 350)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Date (DDMMYYYY):"))
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("25092025")
        self.date_edit.setMaxLength(8)
        layout.addWidget(self.date_edit)

        layout.addWidget(QLabel("Amount (e.g., -34.50):"))
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("-34.50")
        layout.addWidget(self.amount_edit)

        layout.addWidget(QLabel("Merchant:"))
        self.merchant_edit = QLineEdit()
        self.merchant_edit.setPlaceholderText("e.g., YMCA, Shell")
        layout.addWidget(self.merchant_edit)

        layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(categories)
        layout.addWidget(self.category_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate_and_accept(self):
        try:
            Validator.validate_date(self.date_edit.text())
            Validator.validate_amount(self.amount_edit.text())
            Validator.validate_merchant(self.merchant_edit.text())
            if not self.category_combo.currentText():
                raise ValidationError("Category is required")
            self.accept()
        except ValidationError as e:
            QMessageBox.warning(self, "Validation Error", str(e))

    def get_result(self) -> dict:
        return {
            'date': self.date_edit.text(),
            'amount': self.amount_edit.text(),
            'merchant': self.merchant_edit.text(),
            'category': self.category_combo.currentText()
        }

# === MAIN APPLICATION ===


class NDISAssistant(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"NDIS Expense Assistant v{APP_VERSION}")
        self.resize(1400, 900)

        # Initialize systems
        self.ocr_engine = WestpacOCREngine()
        self.learning_system = LearningSystem(
            EXE_DIR / "merchant_knowledge.json")
        self.description_system = DescriptionSystem()
        self.validator = Validator()
        self.data_manager = DataManager()
        self.search_filter = SearchFilter()
        self.lru_cache = LRUCache(max_size=1000)

        # Data storage
        self.categories: List[str] = []
        self.screenshot_folder = EXE_DIR / "Screenshots"
        self.search_root = EXE_DIR

        # File paths
        self.pending_csv = EXE_DIR / "pending.csv"
        self.completed_csv = EXE_DIR / "completed.csv"

        # Worker
        self.scan_thread: Optional[QThread] = None
        self.scan_worker: Optional[ScanWorker] = None

        # UI state
        self.current_view = "pending"
        self.selected_rows: Set[int] = set()

        # Timers
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.debounce_ms = 500
        self.save_timer.setInterval(self.debounce_ms)
        self.save_timer.timeout.connect(self.save_pending_csv)

        # Load everything
        self.load_config()
        self.ensure_data_files()
        self.load_data()

        # Build UI
        self.init_ui()

        logging.info("✅ Application fully initialized")

    def load_config(self):
        settings = QSettings(str(EXE_DIR / "config.ini"), QSettings.IniFormat)

        self.screenshot_folder = Path(settings.value(
            "Paths/screenshot_folder", str(EXE_DIR / "Screenshots")))
        self.search_root = Path(settings.value(
            "Paths/search_root", str(EXE_DIR)))

        categories_str = settings.value(
            "Categories/list", "Food;Transport;Medical;Client Session;Supplies;Other")
        self.categories = [c.strip()
                           for c in categories_str.split(";") if c.strip()]

        self.learning_threshold = int(settings.value("Learning/threshold", 2))
        self.debounce_ms = int(settings.value("UI/debounce_ms", 500))
        self.save_timer.setInterval(self.debounce_ms)

        logging.info(f"📁 Screenshot folder: {self.screenshot_folder}")
        logging.info(f"🔍 Search root: {self.search_root}")
        logging.info(f"🏷️  {len(self.categories)} categories")
        logging.info(f"🎯 Learning threshold: {self.learning_threshold}")

    def save_config(self):
        settings = QSettings(str(EXE_DIR / "config.ini"), QSettings.IniFormat)
        settings.setValue("Version/schema", SCHEMA_VERSION)
        settings.setValue("Paths/screenshot_folder",
                          str(self.screenshot_folder))
        settings.setValue("Paths/search_root", str(self.search_root))
        settings.setValue("Categories/list", ";".join(self.categories))
        settings.setValue("Learning/threshold", self.learning_threshold)
        settings.setValue("UI/debounce_ms", self.debounce_ms)

    def ensure_data_files(self):
        self.screenshot_folder.mkdir(parents=True, exist_ok=True)
        (self.screenshot_folder / "NEEDS_ATTENTION").mkdir(exist_ok=True)
        (self.screenshot_folder / "BACKUPS").mkdir(exist_ok=True)

        for csv_file, headers in [
            (self.pending_csv, [
                'file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw',
                'MerchantOCRValue', 'category', 'description', 'status'
            ]),
            (self.completed_csv, [
                'file_hash', 'completed_timestamp', 'filename', 'date_raw',
                'amount_raw', 'MerchantOCRValue', 'category', 'description', 'status'
            ])
        ]:
            if not csv_file.exists():
                with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)

    def load_data(self):
        # Load completed
        if self.completed_csv.exists() and self.completed_csv.stat().st_size > 0:
            try:
                with open(self.completed_csv, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.data_manager.append_completed(
                            TransactionItem(**row))
                logging.info(
                    f"✅ Loaded {len(self.data_manager.completed)} completed items")
            except Exception as e:
                logging.error(
                    f"Failed to load completed.csv: {e}\n{traceback.format_exc()}")

        # Load pending
        if self.pending_csv.exists() and self.pending_csv.stat().st_size > 0:
            try:
                with open(self.pending_csv, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get('status') == ItemStatus.PENDING.value:
                            self.data_manager.add_pending(
                                TransactionItem(**row))
                logging.info(
                    f"✅ Loaded {len(self.data_manager.pending)} pending items")
            except Exception as e:
                logging.error(
                    f"Failed to load pending.csv: {e}\n{traceback.format_exc()}")

        self.lru_cache.load_from_file(EXE_DIR / "ocr_cache.json")

    def init_ui(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")

        scan_action = QAction("&Scan", self)
        scan_action.setShortcut(QKeySequence("Ctrl+S"))
        scan_action.triggered.connect(self.start_scan)
        file_menu.addAction(scan_action)

        export_action = QAction("&Export", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self.export_history)
        file_menu.addAction(export_action)

        backup_action = QAction("&Backup", self)
        backup_action.setShortcut(QKeySequence("Ctrl+B"))
        backup_action.triggered.connect(self.create_backup)
        file_menu.addAction(backup_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.save_and_exit)
        file_menu.addAction(exit_action)

        edit_menu = menubar.addMenu("&View")

        toggle_action = QAction("&Toggle View", self)
        toggle_action.setShortcut(QKeySequence("Ctrl+T"))
        toggle_action.triggered.connect(self.toggle_view)
        edit_menu.addAction(toggle_action)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        search_bar = QHBoxLayout()
        search_bar.addWidget(QLabel("🔍 Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search merchants, descriptions...")
        self.search_input.textChanged.connect(self.apply_search)
        search_bar.addWidget(self.search_input, stretch=2)
        search_bar.addWidget(QLabel("Category:"))
        self.category_filter_combo = QComboBox()
        self.category_filter_combo.addItem("All Categories")
        self.category_filter_combo.addItems(self.categories)
        self.category_filter_combo.currentTextChanged.connect(
            self.apply_filters)
        search_bar.addWidget(self.category_filter_combo, stretch=1)
        self.clear_filters_btn = QPushButton("Clear Filters")
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        search_bar.addWidget(self.clear_filters_btn)
        layout.addLayout(search_bar)

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

        bulk_bar = QHBoxLayout()
        bulk_bar.addWidget(QLabel("Bulk Actions:"))
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all)
        bulk_bar.addWidget(self.select_all_btn)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        bulk_bar.addWidget(self.deselect_all_btn)
        self.bulk_done_btn = QPushButton("✓ Mark Selected Done")
        self.bulk_done_btn.clicked.connect(self.bulk_mark_done)
        bulk_bar.addWidget(self.bulk_done_btn)
        self.bulk_delete_btn = QPushButton("🗑️ Delete Selected")
        self.bulk_delete_btn.clicked.connect(self.bulk_delete)
        bulk_bar.addWidget(self.bulk_delete_btn)
        bulk_bar.addStretch()
        self.toggle_btn = QPushButton("Show Completed")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.toggle_view)
        bulk_bar.addWidget(self.toggle_btn)
        layout.addLayout(bulk_bar)

        self.table = QTableWidget(0, len(ColumnIndex))
        self.table.setHorizontalHeaderLabels([
            "Date (DDMMYYYY)", "Amount", "Merchant", "Category", "Description", "Actions"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            ColumnIndex.ACTIONS, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self.update_selection)
        layout.addWidget(self.table)

        button_bar = QHBoxLayout()
        self.export_btn = QPushButton("📤 Export Completed")
        self.export_btn.clicked.connect(self.export_history)
        button_bar.addWidget(self.export_btn)
        self.backup_btn = QPushButton("💾 Backup All Data")
        self.backup_btn.clicked.connect(self.create_backup)
        button_bar.addWidget(self.backup_btn)
        self.needs_attention_btn = QPushButton("⚠️ Process NEEDS_ATTENTION")
        self.needs_attention_btn.clicked.connect(self.process_needs_attention)
        button_bar.addWidget(self.needs_attention_btn)
        button_bar.addStretch()
        exit_btn = QPushButton("🚪 Save & Exit")
        exit_btn.clicked.connect(self.save_and_exit)
        button_bar.addWidget(exit_btn)
        layout.addLayout(button_bar)

        self.refresh_table()

    def update_selection(self):
        self.selected_rows = {
            index.row() for index in self.table.selectionModel().selectedRows()}
        self.bulk_done_btn.setEnabled(len(self.selected_rows) > 0)
        self.bulk_delete_btn.setEnabled(len(self.selected_rows) > 0)

    def select_all(self):
        self.table.selectAll()

    def deselect_all(self):
        self.table.clearSelection()

    def apply_search(self, query: str):
        self.search_filter.query = query
        self.refresh_table()

    def apply_filters(self):
        self.search_filter.category_filter = self.category_filter_combo.currentText()
        if self.search_filter.category_filter == "All Categories":
            self.search_filter.category_filter = ""
        self.refresh_table()

    def clear_filters(self):
        self.search_input.clear()
        self.category_filter_combo.setCurrentIndex(0)
        self.search_filter.query = ""
        self.search_filter.category_filter = ""
        self.refresh_table()

    def start_scan(self):
        self.scan_btn.setEnabled(False)
        self.status_label.setText("⏳ Scanning in background...")

        self.progress_dialog = QProgressDialog(
            "Scanning screenshots...", "Cancel", 0, 0, self)
        self.progress_dialog.setWindowTitle("Scanning")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        self.scan_thread = QThread()
        self.scan_worker = ScanWorker(
            self.search_root,
            self.screenshot_folder,
            self.ocr_engine,
            self.data_manager,
            self.lru_cache
        )
        self.scan_worker.moveToThread(self.scan_thread)

        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress.connect(self.progress_dialog.setLabelText)
        self.scan_worker.scan_complete.connect(self.on_scan_complete)
        self.scan_worker.item_processed.connect(self.on_item_processed)
        self.scan_worker.error.connect(self.show_error)
        self.scan_worker.finished.connect(self.scan_thread.quit)

        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.finished.connect(self.scan_worker.deleteLater)

        self.progress_dialog.canceled.connect(self.cancel_scan)

        self.scan_thread.start()

    def cancel_scan(self):
        if self.scan_worker:
            self.scan_worker.stop()
        self.scan_btn.setEnabled(True)

    def on_item_processed(self, result: dict):
        pass

    def on_scan_complete(self, processed: int, attention: int, total: int):
        self.scan_btn.setEnabled(True)
        self.progress_dialog.close()

        self.lru_cache.save_to_file(EXE_DIR / "ocr_cache.json")
        self.save_pending_csv()

        self.refresh_table()

        msg = f"✅ Scan complete | Processed: {processed} | Needs Attention: {attention}"
        self.status_label.setText(msg)

        if attention > 0:
            QMessageBox.information(
                self, "Scan Complete",
                f"Processed {processed} screenshots.\n\n"
                f"{attention} files require manual entry and were moved to:\n"
                f"{self.screenshot_folder / 'NEEDS_ATTENTION'}\n\n"
                f"Click 'Process NEEDS_ATTENTION' to handle them."
            )

    def process_needs_attention(self):
        attention_dir = self.screenshot_folder / "NEEDS_ATTENTION"
        if not attention_dir.exists():
            QMessageBox.information(
                self, "No Attention Files", "No files need manual attention.")
            return

        attention_files = list(attention_dir.glob("Screenshot_*.jpg"))
        if not attention_files:
            QMessageBox.information(
                self, "No Attention Files", "No files need manual attention.")
            return

        reply = QMessageBox.question(
            self, "Manual Entry",
            f"{len(attention_files)} files need manual entry. Process them now?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        for filepath in attention_files:
            dialog = ManualEntryDialog(filepath, self.categories, self)
            if dialog.exec() == QDialog.Accepted:
                result = dialog.get_result()

                try:
                    self.validator.validate_date(result['date'])
                    self.validator.validate_amount(result['amount'])
                    self.validator.validate_merchant(result['merchant'])
                except ValidationError as e:
                    QMessageBox.warning(self, "Validation Error", str(e))
                    continue

                date_raw = result['date']
                if len(date_raw) == 8:
                    year = date_raw[4:8]
                    month = date_raw[2:4]
                    target_dir = self.screenshot_folder / f"{year}-{month}"
                else:
                    target_dir = self.screenshot_folder / "Organized"

                final_path = target_dir / filepath.name

                item = TransactionItem(
                    file_hash=ScanWorker.calculate_hash(filepath),
                    filename=filepath.name,
                    filepath=final_path,
                    date_raw=result['date'],
                    amount_raw=result['amount'],
                    MerchantOCRValue=result['merchant'],
                    category=result['category'],
                    description=self.description_system.format_description(
                        result['category'], ""),
                    status=ItemStatus.PENDING.value
                )

                def csv_callback():
                    self.data_manager.add_pending(item)
                    self.save_pending_csv()
                    return True

                tm = TransactionManager(self.data_manager)
                tm.staged_moves = [(filepath, final_path)]
                if tm.commit(csv_callback):
                    self.refresh_table()

        self.status_label.setText(
            f"✅ Processed {len(attention_files)} NEEDS_ATTENTION files")

    def refresh_table(self):
        if self.toggle_btn.isChecked():
            self.show_completed()
        else:
            self.show_pending()

    def show_pending(self):
        with self.data_manager.access() as dm:
            filtered_items = [
                (idx, item) for idx, item in enumerate(dm.pending)
                if self.search_filter.matches(item)
            ]

        self.table.setRowCount(len(filtered_items))

        for row, (orig_idx, item) in enumerate(filtered_items):
            date_item = QTableWidgetItem(item.date_raw)
            date_item.setData(Qt.UserRole, orig_idx)
            self.table.setItem(row, ColumnIndex.DATE, date_item)

            amount_item = QTableWidgetItem(item.amount_raw)
            amount_item.setData(Qt.UserRole, orig_idx)
            self.table.setItem(row, ColumnIndex.AMOUNT, amount_item)

            merchant_item = QTableWidgetItem(item.MerchantOCRValue)
            merchant_item.setFlags(merchant_item.flags() & ~Qt.ItemIsEditable)
            merchant_item.setData(Qt.UserRole, orig_idx)
            self.table.setItem(row, ColumnIndex.MERCHANT, merchant_item)

            category_combo = QComboBox()
            category_combo.addItems([""] + self.categories)

            suggested = self.learning_system.get_suggested_category(
                item.MerchantOCRValue, self.learning_threshold)
            current_cat = item.category or suggested or ""
            if suggested and not item.category:
                item.category = suggested
                item.description = self.description_system.format_description(
                    suggested, "")

            category_combo.setCurrentText(current_cat)
            category_combo.currentTextChanged.connect(
                lambda text, r=row: self.update_category(r, text))
            self.table.setCellWidget(row, ColumnIndex.CATEGORY, category_combo)

            desc_item = QTableWidgetItem(item.description)
            desc_item.setData(Qt.UserRole, orig_idx)
            desc_item.textChanged.connect(
                lambda text, r=row: self.update_description_text(r, text))
            self.table.setItem(row, ColumnIndex.DESCRIPTION, desc_item)

            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)

            view_btn = QPushButton("👁️")
            view_btn.clicked.connect(lambda _, p=str(
                item.filepath): self.view_image(p))
            actions_layout.addWidget(view_btn)

            done_btn = QPushButton("✓ Done")
            done_btn.clicked.connect(lambda _, r=row: self.mark_done(r))
            actions_layout.addWidget(done_btn)

            self.table.setCellWidget(row, ColumnIndex.ACTIONS, actions_widget)

        self.status_label.setText(
            f"📋 Showing {len(filtered_items)} of {len(self.data_manager.pending)} pending items")

    def show_completed(self):
        with self.data_manager.access() as dm:
            filtered_items = [
                item for item in dm.completed if self.search_filter.matches(item)]

        self.table.setRowCount(len(filtered_items))

        for row, item in enumerate(filtered_items):
            self.table.setItem(row, ColumnIndex.DATE,
                               QTableWidgetItem(item.date_raw))
            self.table.setItem(row, ColumnIndex.AMOUNT,
                               QTableWidgetItem(item.amount_raw))
            self.table.setItem(row, ColumnIndex.MERCHANT,
                               QTableWidgetItem(item.MerchantOCRValue))
            self.table.setItem(row, ColumnIndex.CATEGORY,
                               QTableWidgetItem(item.category))
            self.table.setItem(row, ColumnIndex.DESCRIPTION,
                               QTableWidgetItem(item.description))
            self.table.setCellWidget(row, ColumnIndex.ACTIONS, QWidget())

        self.status_label.setText(
            f"✅ Showing {len(filtered_items)} of {len(self.data_manager.completed)} completed items")

    def update_category(self, row: int, category: str):
        if 0 <= row < self.table.rowCount():
            orig_idx = self.table.item(row, ColumnIndex.DATE).data(Qt.UserRole)
            with self.data_manager.access() as dm:
                item = dm.pending[orig_idx]
                old_category = item.category
                item.category = category

                if category:
                    item.description = self.description_system.update_description(
                        item.description, category)
                    self.table.item(row, ColumnIndex.DESCRIPTION).setText(
                        item.description)

            logging.info(
                f"🏷️  {item.MerchantOCRValue}: {old_category} → {category}")
            self.save_timer.start()

    def update_description_text(self, row: int, text: str):
        if 0 <= row < self.table.rowCount():
            orig_idx = self.table.item(row, ColumnIndex.DATE).data(Qt.UserRole)
            with self.data_manager.access() as dm:
                item = dm.pending[orig_idx]
                item.description = text
                logging.debug(
                    f"📝 Description updated for {item.MerchantOCRValue}")
            self.save_timer.start()

    def view_image(self, filepath: str):
        path = Path(filepath)
        if path.exists():
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f"open '{path}'")
            else:
                os.system(f"xdg-open '{path}'")
        else:
            self.show_error(f"❌ Image not found:\n{path}")

    def mark_done(self, row: int):
        if 0 <= row < self.table.rowCount():
            self.save_timer.stop()

            orig_idx = self.table.item(row, ColumnIndex.DATE).data(Qt.UserRole)
            with self.data_manager.access() as dm:
                item = dm.remove_pending(orig_idx)

            item.status = ItemStatus.DONE.value
            item.completed_timestamp = datetime.utcnow().isoformat() + 'Z'

            category = self.table.cellWidget(
                row, ColumnIndex.CATEGORY).currentText()
            item.category = category or item.category

            self.learning_system.learn_confirmation(
                item.MerchantOCRValue, category)
            self.append_completed(item)
            self.save_pending_csv()

            self.refresh_table()
            self.status_label.setText(f"✓ Marked done: {item.filename}")
            logging.info(f"✓ Completed: {item.MerchantOCRValue} -> {category}")

    def bulk_mark_done(self):
        if not self.selected_rows:
            return

        reply = QMessageBox.question(
            self, "Bulk Mark Done",
            f"Mark {len(self.selected_rows)} selected items as done?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        original_indices = {
            self.table.item(row, ColumnIndex.DATE).data(Qt.UserRole)
            for row in self.selected_rows
        }

        for index in sorted(original_indices, reverse=True):
            self._mark_done_by_index(index)

    def _mark_done_by_index(self, index: int):
        with self.data_manager.access() as dm:
            item = dm.remove_pending(index)

        item.status = ItemStatus.DONE.value
        item.completed_timestamp = datetime.utcnow().isoformat() + 'Z'

        self.learning_system.learn_confirmation(
            item.MerchantOCRValue, item.category)
        self.append_completed(item)

    def bulk_delete(self):
        if not self.selected_rows:
            return

        reply = QMessageBox.question(
            self, "Bulk Delete",
            f"Delete {len(self.selected_rows)} selected items?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        original_indices = {
            self.table.item(row, ColumnIndex.DATE).data(Qt.UserRole)
            for row in self.selected_rows
        }

        for index in sorted(original_indices, reverse=True):
            with self.data_manager.access() as dm:
                item = dm.remove_pending(index)
                dm.hashes.discard(item.file_hash)

            try:
                if item.filepath.exists():
                    item.filepath.unlink()
            except Exception as e:
                logging.error(f"Failed to delete file {item.filepath}: {e}")

        self.save_pending_csv()
        self.refresh_table()
        self.status_label.setText(
            f"🗑️ Deleted {len(self.selected_rows)} items")

    def refresh_table(self):
        if self.toggle_btn.isChecked():
            self.show_completed()
        else:
            self.show_pending()

    def append_completed(self, item: TransactionItem):
        try:
            with open(self.completed_csv, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    item.file_hash,
                    item.completed_timestamp,
                    item.filename,
                    item.date_raw,
                    item.amount_raw,
                    item.MerchantOCRValue,
                    item.category,
                    item.description,
                    item.status
                ])

            with self.data_manager.access() as dm:
                dm.append_completed(item)

        except Exception as e:
            logging.error(f"Failed to append to completed.csv: {e}")
            self.show_error(f"Failed to save completed item: {e}")

    def save_pending_csv(self):
        fieldnames = [
            'file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw',
            'MerchantOCRValue', 'category', 'description', 'status'
        ]

        with self.data_manager.access() as dm:
            rows = [asdict(item) for item in dm.pending]

        def serialize(p: Path, d: List[Dict]):
            with open(p, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(d)

        bak_path = self.pending_csv.with_suffix('.csv.bak')
        tmp_path = self.pending_csv.with_suffix('.csv.tmp')

        try:
            if self.pending_csv.exists():
                shutil.copy2(self.pending_csv, bak_path)

            serialize(tmp_path, rows)
            os.replace(tmp_path, self.pending_csv)

            if bak_path.exists():
                bak_path.unlink()

        except Exception as e:
            logging.error(f"Save failed: {e}")
            if bak_path.exists():
                shutil.copy2(bak_path, self.pending_csv)
            if tmp_path.exists():
                tmp_path.unlink()

    def browse_folder(self):
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
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.resize(600, 500)

        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("Categories (one per line):"))
        categories_edit = QTextEdit()
        categories_edit.setPlainText("\n".join(self.categories))
        layout.addWidget(categories_edit)

        layout.addWidget(
            QLabel("Learning Threshold (confirmations for auto-suggest):"))
        threshold_spin = QLineEdit(str(self.learning_threshold))
        layout.addWidget(threshold_spin)

        layout.addWidget(QLabel("Auto-save delay (ms):"))
        debounce_spin = QLineEdit(str(self.debounce_ms))
        layout.addWidget(debounce_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(lambda: self.save_settings(
            categories_edit.toPlainText(),
            threshold_spin.text(),
            debounce_spin.text(),
            dialog
        ))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec()

    def save_settings(self, categories_text: str, threshold: str, debounce: str, dialog: QDialog):
        try:
            new_categories = [c.strip()
                              for c in categories_text.split("\n") if c.strip()]
            if not new_categories:
                raise ValueError("At least one category required")

            new_threshold = int(threshold)
            if new_threshold < 1:
                raise ValueError("Threshold must be >= 1")

            new_debounce = int(debounce)
            if new_debounce < 100 or new_debounce > 5000:
                raise ValueError("Debounce must be 100-5000ms")

            self.categories = new_categories
            self.learning_threshold = new_threshold
            self.debounce_ms = new_debounce
            self.save_timer.setInterval(self.debounce_ms)

            self.category_filter_combo.clear()
            self.category_filter_combo.addItem("All Categories")
            self.category_filter_combo.addItems(self.categories)

            self.save_config()
            dialog.accept()
            self.refresh_table()
            self.status_label.setText("⚙️ Settings saved")

        except Exception as e:
            QMessageBox.warning(self, "Invalid Settings", str(e))

    def create_backup(self):
        backup_dir = self.screenshot_folder / "BACKUPS" / \
            datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)

        try:
            files_to_backup = [
                self.pending_csv,
                self.completed_csv,
                EXE_DIR / "merchant_knowledge.json",
                EXE_DIR / "config.ini",
                EXE_DIR / "ocr_cache.json"
            ]

            for src in files_to_backup:
                if src.exists():
                    dst = backup_dir / src.name
                    shutil.copy2(src, dst)

            QMessageBox.information(
                self, "Backup Success",
                f"💾 Backup created at:\n{backup_dir}"
            )
            logging.info(f"Backup created at {backup_dir}")

        except Exception as e:
            self.show_error(f"Backup failed: {e}")

    def save_and_exit(self):
        backup_marker = EXE_DIR / ".last_backup_date"
        today = datetime.now().strftime("%Y-%m-%d")

        if not backup_marker.exists() or backup_marker.read_text().strip() != today:
            reply = QMessageBox.question(
                self, "Backup Reminder",
                "Create backup before exiting?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.create_backup()
                backup_marker.write_text(today)

        self.save_timer.stop()
        self.save_pending_csv()
        self.learning_system.save_knowledge_atomic()
        self.lru_cache.save_to_file(EXE_DIR / "ocr_cache.json")
        self.save_config()

        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_worker.stop()
            self.scan_thread.quit()
            self.scan_thread.wait()

        logging.info("👋 Application closing normally")
        self.close()

    def closeEvent(self, event: QCloseEvent):
        self.save_and_exit()
        event.accept()

# === MAIN ENTRY POINT ===


def main():
    try:
        app = QApplication(sys.argv)
        app.setApplicationName(f"NDIS Expense Assistant v{APP_VERSION}")

        def handle_exception(exc_type, exc_value, exc_traceback):
            if not issubclass(exc_type, KeyboardInterrupt):
                logging.critical("Uncaught exception", exc_info=(
                    exc_type, exc_value, exc_traceback))
                QMessageBox.critical(
                    None,
                    "Fatal Error",
                    f"Uncaught exception:\n{exc_value}\n\nApplication will exit."
                )
            sys.exit(1)

        sys.excepthook = handle_exception

        window = NDISAssistant()
        window.show()

        logging.info(f"🚀 Application started (PID: {os.getpid()})")
        sys.exit(app.exec())

    except Exception as e:
        logging.critical(
            f"💥 Fatal startup error: {e}\n{traceback.format_exc()}")
        QMessageBox.critical(
            None,
            "Fatal Error",
            f"Application failed to start:\n{e}\n\nCheck {LOG_FILE} for details"
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
