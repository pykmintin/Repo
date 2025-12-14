#!/usr/bin/env python3
# NDIS Expense Assistant v2.0 - COMPLETE WITH PHASES 2-3

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
from pathlib import Path

# === LOGGING SETUP ===
EXE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(EXE_DIR, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')]
)
logging.info("=== NDIS ASSISTANT v2.0 - PHASES 2-3 IMPLEMENTED ===")

try:
    from PySide6.QtWidgets import *
    from PySide6.QtCore import Qt, QSettings
    from PIL import Image
    logging.info("All imports successful")
except Exception as e:
    logging.critical(f"Import error: {e}\n{traceback.format_exc()}")
    sys.exit(1)

# === BULLETPROOF OCR INTEGRATION ===
import cv2
import numpy as np
import pytesseract

class CompleteWestpacExtractor:
    """Complete OCR extractor with all features integrated"""
    
    def __init__(self):
        """Initialize with all patterns and corrections"""
        
        # Amount patterns
        self.amount_patterns = [
            r'\-\$\d+\.\d{2}',           # Standard: -$28.70
            r'\$\-\d+\.\d{2}',           # Alternative: $-28.70
            r'\-\d+\.\d{2}',            # Just negative: -28.70
            r'\d+\.\d{2}',              # Just number: 28.70
        ]
        
        # Date patterns
        self.date_patterns = [
            r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
        ]
        
        # Content-based merchant corrections
        self.content_corrections = {
            'bokeies delight': 'Bakers Delight',
            'bokees delight': 'Bakers Delight',
            'bokies delight': 'Bakers Delight',
            'delightt': 'Delight',
            'traralgongon': 'Traralgon',
            'center': 'Centre',
            '4ae. health': 'Central Gippsland Health',
            'mn,': 'ALDI Mobile',
            'alid': 'ALDI',
        }
        
        # NDIS categories
        self.categories = {
            'bakery': 'Bakery',
            'baker': 'Bakery',
            'delight': 'Bakery',
            'muffin': 'Restaurants & Dining',
            'break': 'Restaurants & Dining',
            'restaurant': 'Restaurants & Dining',
            'dining': 'Restaurants & Dining',
            'food': 'Restaurants & Dining',
            'cafe': 'Restaurants & Dining',
            'coffee': 'Restaurants & Dining',
            'espresso': 'Restaurants & Dining',
            'bar': 'Restaurants & Dining',
            'health': 'Healthcare',
            'medical': 'Healthcare',
            'mobile': 'Utilities',
            'phone': 'Utilities',
            'aldi': 'Utilities',
        }
        
        # Skip patterns
        self.skip_patterns = [
            r'%', r'8:', r'@', r'\|', r'Westpac', r'Account', r'Subcategory',
            r'\d{1,2}:\d{2}', r'\d{1,3}%', r'\d{4}-\d{3}',
            r'Edit$', r'Tags$', r'None$', r'time$', r'transaction$',
            r'^\d+$', r'^\W+$',
        ]
    
    def preprocess_image(self, image: Image.Image) -> np.ndarray:
        """Preprocess image for optimal OCR accuracy"""
        img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        
        # Auto-orient
        height, width = img.shape[:2]
        if width > height:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        
        # Resize
        target_height = 2400
        scale = target_height / img.shape[0]
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Apply adaptive thresholding
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Noise reduction
        denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)
        
        return denoised
    
    def correct_merchant_name(self, merchant: str) -> str:
        """Apply content-based corrections (no image_num dependency)"""
        merchant_clean = merchant.strip()
        merchant_lower = merchant_clean.lower()
        
        # Apply content-based corrections
        for error, correction in self.content_corrections.items():
            if error in merchant_lower:
                return correction
        
        # Clean up common OCR artifacts
        merchant = re.sub(r'[~*]', '', merchant)
        merchant = re.sub(r'\s+', ' ', merchant)
        merchant = merchant.strip(' -_()<>')
        
        return merchant
    
    def extract_amount(self, text: str) -> str:
        """Extract transaction amount - bulletproof"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        for pattern in self.amount_patterns:
            for line in lines:
                matches = re.findall(pattern, line)
                if matches:
                    amount = matches[0]
                    
                    # Extract the numeric part
                    number_match = re.search(r'(\d+\.\d{2})', amount)
                    if number_match:
                        number = number_match.group(1)
                        return f"-${number}"
        
        return "$0.00"
    
    def extract_date(self, text: str) -> str:
        """Extract transaction date in DDMMYYYY format"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        for pattern in self.date_patterns:
            for line in lines:
                matches = re.findall(pattern, line, re.IGNORECASE)
                if matches:
                    match = matches[0]
                    
                    if isinstance(match, tuple):
                        if len(match) == 4:  # DayName, Day, Month, Year
                            day = match[1].zfill(2)
                            month_dict = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
                                         "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
                            month = month_dict.get(match[2], "01")
                            year = match[3]
                            return f"{day}{month}{year}"
                        elif len(match) == 3:  # Day, Month, Year
                            day = match[0].zfill(2)
                            month_dict = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
                                         "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
                            month = month_dict.get(match[1], "01")
                            year = match[2]
                            return f"{day}{month}{year}"
                    
                    return str(match)
        
        return "01012025"  # Default fallback
    
    def extract_merchant_name(self, text: str) -> str:
        """Extract merchant name with intelligent filtering (no image_num)"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        candidates = []
        
        for i, line in enumerate(lines):
            # Skip unwanted lines
            skip_line = False
            for pattern in self.skip_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    skip_line = True
                    break
            
            if skip_line:
                continue
            
            # Skip very short lines or lines that are likely not merchant names
            if (len(line) < 3 or 
                line.isdigit() or 
                line in ['Edit', 'Tags', 'None', 'Account', 'Subcategory'] or
                'time' in line.lower() or
                'transaction' in line.lower() or
                'View' in line or
                'similar' in line.lower()):
                continue
            
            # Clean up merchant name
            merchant = re.sub(r'\s+', ' ', line)
            merchant = merchant.strip(' -_()<>')
            
            if len(merchant) >= 3:
                candidates.append((i, merchant))
        
        # Find the best candidate
        if candidates:
            # Look for the most merchant-like name
            for i, candidate in candidates:
                if any(word in candidate.lower() for word in ['delight', 'bakery', 'mobile', 'break', 'health', 'aldi', 'dock', 'espresso', 'bar']):
                    return self.correct_merchant_name(candidate)
            
            # If no obvious business words, return the first reasonable candidate
            return self.correct_merchant_name(candidates[0][1])
        
        return "Unknown Merchant"
    
    def extract_subcategory(self, text: str, merchant: str) -> str:
        """Extract subcategory based on merchant name and keywords"""
        text_lower = text.lower()
        merchant_lower = merchant.lower()
        
        # Look for known categories in merchant name first
        for keyword, category in self.categories.items():
            if keyword in merchant_lower:
                return category
        
        # Look in the full text
        for keyword, category in self.categories.items():
            if keyword in text_lower:
                return category
        
        return "Uncategorised"
    
    def extract_transaction(self, image_path: str) -> Dict[str, str]:
        """Main extraction method - returns needs_attention flag"""
        try:
            with Image.open(image_path) as img:
                # Preprocess image
                processed_img = self.preprocess_image(img)
                
                # Extract text
                text = pytesseract.image_to_string(processed_img)
                
                # Extract merchant first
                merchant = self.extract_merchant_name(text)
                
                # Extract other fields
                amount = self.extract_amount(text)
                date = self.extract_date(text)
                subcategory = self.extract_subcategory(text, merchant)
                
                # Check if needs attention
                needs_attention = (
                    merchant == "Unknown Merchant" or
                    amount == "$0.00" or
                    date == "01012025"
                )
                
                result = {
                    'merchant': merchant,
                    'amount': amount,
                    'date': date,
                    'subcategory': subcategory,
                    'source_image': image_path,
                    'needs_attention': needs_attention
                }
                
                return result
                
        except Exception as e:
            return {
                'merchant': 'Error',
                'amount': 'Error',
                'date': 'Error',
                'subcategory': 'Error',
                'source_image': image_path,
                'needs_attention': True,
                'error': str(e)
            }

# === PHASE 2: LEARNING SYSTEM IMPLEMENTATION ===
class LearningSystem:
    """Handles merchant-to-category learning and knowledge persistence"""
    
    def __init__(self):
        self.merchant_knowledge = []
        self.load_merchant_knowledge()
        
    def load_merchant_knowledge(self):
        """Load merchant knowledge from JSON file"""
        knowledge_file = "merchant_knowledge.json"
        if os.path.exists(knowledge_file):
            try:
                with open(knowledge_file, 'r', encoding='utf-8') as f:
                    self.merchant_knowledge = json.load(f)
                logging.info(f"Loaded {len(self.merchant_knowledge)} merchant knowledge entries")
            except Exception as e:
                logging.error(f"Failed to load merchant knowledge: {e}")
                self.merchant_knowledge = []
        else:
            self.merchant_knowledge = []
            logging.info("No existing merchant knowledge found")
    
    def save_merchant_knowledge_atomic(self):
        """Save merchant knowledge with atomic write"""
        try:
            # Atomic write pattern
            temp_path = "merchant_knowledge.json.tmp"
            backup_path = "merchant_knowledge.json.bak"
            
            # Create backup
            if os.path.exists("merchant_knowledge.json"):
                shutil.copy2("merchant_knowledge.json", backup_path)
            
            # Write to temp file
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.merchant_knowledge, f, indent=2)
            
            # Atomic replace
            os.replace(temp_path, "merchant_knowledge.json")
            
            # Remove backup on success
            if os.path.exists(backup_path):
                os.remove(backup_path)
                
            logging.info(f"Saved {len(self.merchant_knowledge)} merchant knowledge entries")
        except Exception as e:
            logging.error(f"Failed to save merchant knowledge: {e}")
            # Restore backup
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, "merchant_knowledge.json")
    
    def learn_confirmation(self, merchant, category):
        """Add merchant-category confirmation to knowledge base"""
        normalized = merchant.lower().strip()
        
        # Check if this exact combination already exists
        for entry in self.merchant_knowledge:
            if entry['merchant'] == normalized and entry['category'] == category:
                logging.debug(f"Merchant-category combination already exists: {normalized} -> {category}")
                return
        
        # Add new entry (never modify existing, only append)
        self.merchant_knowledge.append({
            "merchant": normalized,
            "category": category,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logging.info(f"Learned: {normalized} -> {category}")
        self.save_merchant_knowledge_atomic()
    
    def get_preselected_category(self, merchant, threshold=2):
        """Get pre-selected category based on learned knowledge"""
        normalized = merchant.lower().strip()
        
        # Count frequency of each category for this merchant
        category_counts = {}
        for entry in self.merchant_knowledge:
            if entry['merchant'] == normalized:
                category_counts[entry['category']] = category_counts.get(entry['category'], 0) + 1
        
        # Return most frequent category if meets threshold
        if category_counts:
            most_frequent = max(category_counts.items(), key=lambda x: x[1])
            if most_frequent[1] >= threshold:
                logging.info(f"Pre-selecting category for {merchant}: {most_frequent[0]} (confidence: {most_frequent[1]})")
                return most_frequent[0]
        
        return None

# === PHASE 3: DYNAMIC DESCRIPTION SYSTEM ===
class DescriptionSystem:
    """Handles dynamic description field with category prefix preservation"""
    
    @staticmethod
    def format_description(category, user_note=""):
        """Format description as {Category} - {UserNote}"""
        if not user_note:
            return category
        return f"{category} - {user_note}"
    
    @staticmethod
    def extract_parts(description):
        """Extract category prefix and user note from description"""
        if not description:
            return "", ""
        
        if " - " in description:
            parts = description.split(" - ", 1)
            return parts[0], parts[1]
        else:
            # No dash found, assume it's just the category or user note
            # We'll handle this in the update logic
            return "", description
    
    @staticmethod
    def update_description(current_desc, new_category):
        """Update description with new category while preserving user note"""
        if not current_desc:
            return new_category
        
        if " - " in current_desc:
            category_part, user_note = current_desc.split(" - ", 1)
            return f"{new_category} - {user_note}"
        else:
            # No dash found, assume current_desc is user note
            return f"{new_category} - {current_desc}"

# === ATOMIC WRITE UTILITIES ===
def atomic_write_csv(filepath, data, fieldnames):
    """Atomic write for CSV files with backup protection"""
    temp_path = f"{filepath}.tmp"
    backup_path = f"{filepath}.bak"
    
    try:
        # Create backup
        if os.path.exists(filepath):
            shutil.copy2(filepath, backup_path)
        
        # Write to temp file
        with open(temp_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if os.path.getsize(filepath) == 0 if os.path.exists(filepath) else True:
                writer.writeheader()
            for row in data:
                writer.writerow(row)
        
        # Atomic replace
        os.replace(temp_path, filepath)
        
        # Remove backup on success
        if os.path.exists(backup_path):
            os.remove(backup_path)
            
        return True
        
    except Exception as e:
        logging.error(f"Atomic write failed for {filepath}: {e}")
        # Restore backup
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, filepath)
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

# === MAIN APPLICATION CLASS ===
class NDISAssistant(QMainWindow):
    """Main application window with complete functionality"""
    
    def __init__(self):
        """Initialize main window with all systems"""
        super().__init__()
        self.setWindowTitle("NDIS Expense Assistant v2.0 - Complete")
        self.resize(1100, 700)
        
        # Initialize all systems
        self.ocr_engine = CompleteWestpacExtractor()
        self.learning_system = LearningSystem()
        self.description_system = DescriptionSystem()
        
        # Data storage
        self.pending_data = []
        self.completed_data = []
        self.current_view = "pending"
        self.file_hashes = set()
        self.categories = []
        self.screenshot_folder = ""
        self.search_root = ""
        self.ocr_cache = {}
        
        # Load configuration
        self.load_config()
        self.load_ocr_cache()
        self.ensure_csv_files()
        self.init_ui()
        self.load_data()
        
        logging.info("Complete application initialized")
        
    def load_config(self):
        """Load configuration from config.ini"""
        settings = QSettings("config.ini", QSettings.IniFormat)
        
        self.screenshot_folder = str(settings.value("Paths/screenshot_folder", 
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "Screenshots")))
        self.search_root = str(settings.value("Paths/search_root", 
            os.path.dirname(os.path.abspath(__file__))))
        
        categories_str = str(settings.value("Categories/list", 
            "Food;Transport;Medical;Client Session;Supplies;Other"))
        if isinstance(categories_str, str):
            self.categories = [c.strip() for c in categories_str.split(";") if c.strip()]
        
        logging.info(f"Config loaded: {len(self.categories)} categories")
        logging.info(f"Search root: {repr(self.search_root)}")
        logging.info(f"Screenshot folder: {repr(self.screenshot_folder)}")
        
    def save_config(self):
        """Save configuration to config.ini"""
        settings = QSettings("config.ini", QSettings.IniFormat)
        settings.setValue("Paths/screenshot_folder", self.screenshot_folder)
        settings.setValue("Categories/list", ";".join(self.categories))
        
    def load_ocr_cache(self):
        """Load OCR results cache to avoid re-processing files"""
        cache_path = "ocr_cache.json"
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
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
            with open("ocr_cache.json", 'w', encoding='utf-8') as f:
                json.dump(self.ocr_cache, f, indent=2)
            logging.info("Saved OCR cache")
        except Exception as e:
            logging.error(f"Failed to save OCR cache: {e}")
    
    def ensure_csv_files(self):
        """Create CSV files with headers if they don't exist"""
        pending_path = "pending.csv"
        completed_path = "completed.csv"
        
        if not os.path.exists(pending_path):
            with open(pending_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw', 
                               'MerchantOCRValue', 'category', 'description', 'status'])
        
        if not os.path.exists(completed_path):
            with open(completed_path, 'w', newline='', encoding='utf-8') as f:
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
        self.status_label = QLabel("Ready with Complete Features")
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
        if os.path.exists("completed.csv"):
            try:
                with open("completed.csv", 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        self.file_hashes.add(row.get('file_hash', ''))
                        self.completed_data.append(row)
                logging.info(f"Loaded {len(self.file_hashes)} completed hashes")
            except Exception as e:
                logging.error(f"Error loading completed.csv: {e}")
        
        # Load pending items
        if os.path.exists("pending.csv"):
            try:
                with open("pending.csv", 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.pending_data = [row for row in reader if row.get('status') == 'pending']
                logging.info(f"Loaded {len(self.pending_data)} pending items")
            except Exception as e:
                logging.error(f"Error loading pending.csv: {e}")
        
        self.refresh_table()
        
    def organize_and_scan(self):
        """Main pipeline: search → OCR → organize → update CSV with atomic writes"""
        logging.info("=== STARTING ORGANIZE AND SCAN ===")
        
        # Discover all screenshot files
        all_files = []
        for root, dirs, files in os.walk(self.search_root):
            for file in files:
                if file.startswith("Screenshot_") and file.endswith(".jpg"):
                    full_path = os.path.join(root, file)
                    all_files.append(full_path)
                    logging.debug(f"Found: {full_path}")
        
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
        
        # Process new files with bulletproof OCR
        processed = []
        needs_attention_files = []
        
        for i, (filepath, file_hash) in enumerate(new_files):
            # Check cache first
            if file_hash in self.ocr_cache:
                parsed = self.ocr_cache[file_hash]
                parsed['file_hash'] = file_hash
                parsed['filepath'] = filepath
                parsed['filename'] = os.path.basename(filepath)
                
                if parsed.get('needs_attention', False):
                    needs_attention_files.append(filepath)
                else:
                    processed.append(parsed)
                logging.info(f"Used cache for: {os.path.basename(filepath)}")
            else:
                parsed = self.parse_and_ocr(filepath, file_hash)
                if parsed:
                    if parsed.get('needs_attention', False):
                        needs_attention_files.append(filepath)
                    else:
                        processed.append(parsed)
                    self.ocr_cache[file_hash] = parsed
        
        # Handle needs_attention files
        if needs_attention_files:
            self.handle_needs_attention(needs_attention_files)
        
        # Move files to dated folders and update CSV with atomic writes
        moved_count = 0
        for item in processed:
            try:
                src = item['filepath']
                filename = os.path.basename(src)
                
                # Extract date components for folder organization
                date_raw = item['date_raw']
                if len(date_raw) == 8:
                    year = date_raw[4:8]
                    month = date_raw[2:4]
                    target_dir = os.path.join(self.screenshot_folder, f"{year}-{month}")
                else:
                    target_dir = os.path.join(self.screenshot_folder, "Organized")
                
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
        
        # Save all changes with atomic writes
        if processed:
            self.save_pending_csv_atomic()
            self.save_ocr_cache()
        
        self.load_data()
        final_msg = f"Processed {len(processed)}, moved {moved_count}, needs attention: {len(needs_attention_files)}"
        self.status_label.setText(final_msg)
        logging.info(final_msg)
        
    def parse_and_ocr(self, filepath, file_hash):
        """Perform OCR using bulletproof engine and check needs_attention"""
        try:
            logging.debug(f"OCR: {os.path.basename(filepath)}")
            
            # Use bulletproof OCR engine
            result = self.ocr_engine.extract_transaction(filepath)
            
            if result.get('error'):
                logging.error(f"OCR failed for {filepath}: {result['error']}")
                return None
            
            # Check if needs attention
            if result.get('needs_attention', False):
                logging.warning(f"OCR needs attention for {filepath}: {result}")
                return result  # Will be handled by needs_attention logic
            
            # Convert to our data format
            item = {
                'file_hash': file_hash,
                'filename': os.path.basename(filepath),
                'filepath': filepath,
                'date_raw': result['date'],
                'amount_raw': result['amount'],
                'MerchantOCRValue': result['merchant'],
                'category': '',  # Will be set by user
                'description': '',  # Will be set by user
                'status': 'pending',
                'needs_attention': False
            }
            
            logging.info(f"OCR successful: {os.path.basename(filepath)} -> {result['merchant']}")
            return item
            
        except Exception as e:
            logging.error(f"OCR error on {filepath}: {e}")
            return None
    
    def handle_needs_attention(self, needs_attention_files):
        """Handle files that need manual attention"""
        needs_attention_dir = os.path.join(self.screenshot_folder, "NEEDS_ATTENTION")
        os.makedirs(needs_attention_dir, exist_ok=True)
        
        for filepath in needs_attention_files:
            try:
                filename = os.path.basename(filepath)
                dst = os.path.join(needs_attention_dir, filename)
                shutil.move(filepath, dst)
                logging.info(f"Moved {filename} to NEEDS_ATTENTION folder")
            except Exception as e:
                logging.error(f"Failed to move {filepath} to NEEDS_ATTENTION: {e}")
        
        # Prompt for manual entry
        self.prompt_manual_entry(needs_attention_files)
    
    def calculate_hash(self, filepath):
        """Calculate MD5 hash of file for unique identification"""
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def prompt_manual_entry(self, failed_files):
        """Prompt user for manual entry of OCR-failed screenshots"""
        msg = f"{len(failed_files)} screenshots need manual attention. Would you like to enter them manually?"
        reply = QMessageBox.question(self, "Manual Entry Required", msg, 
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
            self.save_pending_csv_atomic()
            self.refresh_table()
    
    def save_pending_csv_atomic(self):
        """Save pending data to CSV file with atomic write"""
        fieldnames = ['file_hash', 'filename', 'filepath', 'date_raw', 'amount_raw', 
                     'MerchantOCRValue', 'category', 'description', 'status']
        
        data = []
        for item in self.pending_data:
            data.append({
                'file_hash': item.get('file_hash', ''),
                'filename': item.get('filename', ''),
                'filepath': item.get('filepath', ''),
                'date_raw': item.get('date_raw', ''),
                'amount_raw': item.get('amount_raw', ''),
                'MerchantOCRValue': item.get('MerchantOCRValue', ''),
                'category': item.get('category', ''),
                'description': item.get('description', ''),
                'status': item.get('status', 'pending')
            })
        
        success = atomic_write_csv("pending.csv", data, fieldnames)
        if not success:
            self.show_error("Failed to save pending data")
    
    def refresh_table(self):
        """Refresh main table based on current view (pending/completed)"""
        if self.current_view == "pending":
            self.show_pending()
        else:
            self.show_completed()
    
    def show_pending(self):
        """Display pending items with full interactivity and learning system"""
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
            
            # Category dropdown with learning system
            category_combo = QComboBox()
            category_combo.addItems([""] + self.categories)
            
            # Get pre-selected category from learning system
            preselected = self.learning_system.get_preselected_category(item['MerchantOCRValue'])
            if preselected:
                category_combo.setCurrentText(preselected)
                logging.info(f"Pre-selected category for {item['MerchantOCRValue']}: {preselected}")
            else:
                category_combo.setCurrentText(item['category'])
            
            category_combo.currentTextChanged.connect(lambda text, r=row: self.update_category(r, text))
            self.table.setCellWidget(row, 3, category_combo)
            
            # Description with dynamic formatting
            desc_item = QTableWidgetItem(item['description'])
            desc_item.setFlags(desc_item.flags() | Qt.ItemIsEditable)
            desc_item.textChanged.connect(lambda text, r=row: self.update_description(r, text))
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
        """Update category and handle dynamic description logic"""
        if 0 <= row < len(self.pending_data):
            item = self.pending_data[row]
            old_category = item['category']
            item['category'] = category
            
            # Handle dynamic description with {Category} - {UserNote} format
            if not item['description']:
                # Empty description, set to category only
                item['description'] = category
            elif " - " in item['description']:
                # Has dash, preserve user note
                _, user_note = self.description_system.extract_parts(item['description'])
                item['description'] = self.description_system.format_description(category, user_note)
            else:
                # No dash, assume current description is user note
                user_note = item['description']
                item['description'] = self.description_system.format_description(category, user_note)
            
            # Update table display
            self.table.item(row, 4).setText(item['description'])
            
            logging.info(f"Updated category for {item['MerchantOCRValue']}: {old_category} -> {category}")
            logging.info(f"New description: {item['description']}")
            
            self.save_pending_csv_atomic()
    
    def update_description(self, row, text):
        """Handle description editing with {Category} - {UserNote} logic"""
        if 0 <= row < len(self.pending_data):
            item = self.pending_data[row]
            category = item['category']
            
            # Handle the {Category} - {UserNote} format
            if category:
                item['description'] = self.description_system.format_description(category, text)
            else:
                item['description'] = text
            
            logging.info(f"Updated description for {item['MerchantOCRValue']}: {item['description']}")
    
    def view_image(self, filepath):
        """Open screenshot image in default viewer"""
        if os.path.exists(filepath):
            os.startfile(filepath)
        else:
            self.show_error("Image file not found")
    
    def mark_done(self, row):
        """Mark item as done with learning system integration"""
        if 0 <= row < len(self.pending_data):
            item = self.pending_data.pop(row)
            
            # Get current values from table widgets
            category = self.table.cellWidget(row, 3).currentText()
            description = self.table.item(row, 4).text()
            
            # Update item with final values
            item['category'] = category
            item['description'] = description
            item['status'] = 'done'
            item['completed_timestamp'] = datetime.utcnow().isoformat() + 'Z'
            
            # Learn from this confirmation
            self.learning_system.learn_confirmation(item['MerchantOCRValue'], category)
            
            # Save to completed with atomic write
            self.save_completed_csv_atomic(item)
            
            # Update pending CSV with atomic write
            self.save_pending_csv_atomic()
            
            self.refresh_table()
            self.status_label.setText(f"Marked done: {item['filename']} (learned: {item['MerchantOCRValue']} -> {category})")
    
    def save_completed_csv_atomic(self, item):
        """Append to completed.csv with atomic write"""
        fieldnames = ['file_hash', 'completed_timestamp', 'filename', 'date_raw', 
                     'amount_raw', 'MerchantOCRValue', 'category', 'description', 'status']
        
        # Read existing data
        existing_data = []
        if os.path.exists("completed.csv") and os.path.getsize("completed.csv") > 0:
            with open("completed.csv", 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                existing_data = list(reader)
        
        # Add new item
        existing_data.append({
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
        
        success = atomic_write_csv("completed.csv", existing_data, fieldnames)
        if not success:
            self.show_error("Failed to save completed data")
    
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
        if not os.path.exists("completed.csv"):
            self.show_error("No completed data to export")
            return
        
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = os.path.join(desktop, f"NDIS_Export_{timestamp}.csv")
        
        try:
            shutil.copy2("completed.csv", export_path)
            QMessageBox.information(self, "Success", 
                                  f"Exported to Desktop:\n{os.path.basename(export_path)}")
        except Exception as e:
            logging.error(f"Export failed: {e}")
            self.show_error(f"Export failed: {e}")
    
    def save_and_exit(self):
        """Save pending data and exit application"""
        self.save_pending_csv_atomic()
        self.learning_system.save_merchant_knowledge_atomic()
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
        app.setApplicationName("NDIS Assistant v2.0 - Complete")
        
        window = NDISAssistant()
        window.show()
        
        logging.info("Starting NDIS Assistant v2.0 - Complete...")
        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Fatal error: {e}\n{traceback.format_exc()}")
        QMessageBox.critical(None, "Fatal Error", 
                           f"Application crashed:\n{e}\n\nCheck app.log for details")
        sys.exit(1)


if __name__ == '__main__':
    main()