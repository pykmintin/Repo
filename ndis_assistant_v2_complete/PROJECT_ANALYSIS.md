# NDIS Expense Assistant v3.2 - Project Analysis

## Overview
The **NDIS Expense Assistant v3.2** is a production-ready desktop application designed for processing and categorizing expense screenshots, particularly for NDIS (National Disability Insurance Scheme) expense tracking. It combines OCR technology with machine learning to automate expense categorization.

## Application Details
- **Version**: 3.2.0
- **Schema Version**: 2.0
- **Total Lines of Code**: 1,827
- **Framework**: PySide6 (Qt-based GUI)
- **License**: Production-ready, enterprise-grade

## Key Features

### 1. OCR Processing Engine
- **Technology**: pytesseract + OpenCV + Pillow
- **Target**: Westpac banking screenshots
- **Processing**: Advanced image preprocessing and text extraction
- **Validation**: Multi-layer data validation system

### 2. Machine Learning System
- **Learning Type**: Merchant-based categorization learning
- **Algorithm**: Confirmation-based frequency learning
- **Capacity**: 10,000 knowledge entries with LRU eviction
- **Threshold**: Configurable confirmation threshold (default: 2)

### 3. Data Management
- **Storage**: CSV files for transactions, JSON for caches
- **Threading**: Thread-safe data operations with RLock
- **Transactions**: Atomic file operations (CSV + file moves)
- **Caching**: LRU cache for OCR results (1,000 entries)

### 4. User Interface
- **Framework**: PySide6 with modern Qt widgets
- **Features**: Search, filtering, bulk operations
- **Views**: Pending vs Completed transaction views
- **Workflow**: Manual entry for failed OCR items

## Technical Architecture

### Core Components
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   GUI Layer     │    │   Business      │    │   Data          │
│   (PySide6)     │───▶│   Logic         │───▶│   Storage       │
│                 │    │   (OCR+ML)      │    │   (CSV+JSON)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Data Flow
1. **Discovery**: ScanWorker finds screenshot files
2. **Processing**: OCR extracts transaction data
3. **Validation**: Validator checks data integrity
4. **Learning**: ML system suggests categories
5. **Review**: User reviews and categorizes
6. **Commit**: Atomic transactions save changes
7. **Archive**: Files organized by date/category

### File Structure
```
Working Directory/
├── Screenshots/
│   ├── NEEDS_ATTENTION/     # Manual entry required
│   ├── BACKUPS/            # Data backups
│   ├── 2024-01/           # Date-organized files
│   └── Organized/          # Uncategorized files
├── pending.csv             # Pending transactions
├── completed.csv           # Completed transactions
├── merchant_knowledge.json # ML learning data
├── ocr_cache.json         # OCR result cache
└── config.ini             # Application settings
```

## Dependencies

### Core Dependencies
- **PySide6** (>=6.5.0) - GUI framework
- **pytesseract** (>=0.3.13) - OCR engine
- **Pillow** (>=10.0.0) - Image processing
- **opencv-python** (>=4.8.0) - Computer vision
- **numpy** (>=1.24.0) - Numerical operations

### Python Standard Library
- `os`, `sys`, `csv`, `re`, `hashlib`, `json`
- `shutil`, `logging`, `traceback`, `enum`
- `threading`, `datetime`, `pathlib`, `collections`
- `typing`, `dataclasses`, `contextlib`

### System Requirements
- **Python**: >=3.8
- **Tesseract OCR**: System package required
- **GUI Environment**: Desktop environment required

## Configuration

### config.ini Settings
```ini
[Paths]
screenshot_folder = ./Screenshots
search_root = ./

[Categories]
list = Food;Transport;Medical;Client Session;Supplies;Other

[Learning]
threshold = 2

[UI]
auto_refresh = true
debounce_ms = 500

[Logging]
level = INFO
```

## Data Models

### TransactionItem
- `file_hash`: SHA256 hash for deduplication
- `filename`: Original screenshot filename
- `filepath`: Path to organized file
- `date_raw`: Transaction date (DDMMYYYY format)
- `amount_raw`: Transaction amount (-$XX.XX format)
- `MerchantOCRValue`: Extracted merchant name
- `category`: User-assigned category
- `description`: Category + user notes
- `status`: "pending" or "done"

### MerchantKnowledge
- `merchant`: Normalized merchant name
- `category`: Associated category
- `confirmations`: Number of user confirmations
- `first_seen`: First occurrence timestamp
- `last_confirmed`: Last confirmation timestamp

## Key Classes

### WestpacOCREngine
- **Purpose**: Extracts transaction data from screenshots
- **Features**: Image preprocessing, pattern matching, merchant correction
- **Output**: OCRCacheEntry with merchant, amount, date, subcategory

### LearningSystem
- **Purpose**: Learns merchant-category relationships
- **Algorithm**: Frequency-based with confirmation threshold
- **Capacity**: 10,000 entries with LRU eviction
- **Persistence**: JSON file storage

### DataManager
- **Purpose**: Thread-safe data operations
- **Features**: RLock protection, copy-based access
- **Storage**: Separate pending and completed lists

### TransactionManager
- **Purpose**: Atomic file operations
- **Workflow**: CSV update first, then file moves
- **Rollback**: Automatic rollback on failure

### ScanWorker
- **Purpose**: Background file scanning
- **Threading**: QThread-based with signals
- **Features**: Progress tracking, cancellation support

## Validation System

### Date Validation
- **Format**: DDMMYYYY (8 digits)
- **Range**: 2020-2030 for year
- **Logic**: Valid day/month ranges

### Amount Validation
- **Format**: -$XX.XX (negative, 2 decimal places)
- **Default**: Rejects $0.00
- **Pattern**: Regex-based validation

### Merchant Validation
- **Length**: Minimum 2 characters
- **Default**: Rejects "Unknown Merchant"
- **Whitespace**: Trimmed and validated

## Security & Reliability

### Thread Safety
- **Mechanism**: RLock for all shared data
- **Access**: Copy-based data retrieval
- **Updates**: Atomic operations only

### Data Integrity
- **Hashing**: SHA256 for file deduplication
- **Transactions**: All-or-nothing operations
- **Backups**: Automatic backup system
- **Validation**: Multi-layer validation

### Error Handling
- **Logging**: Comprehensive logging with rotation
- **Exception Handling**: Graceful degradation
- **User Feedback**: Clear error messages
- **Recovery**: Automatic rollback on failure

## Performance Optimizations

### Caching
- **OCR Cache**: LRU cache for OCR results
- **Knowledge Cache**: In-memory merchant knowledge
- **File Hashing**: SHA256 for deduplication

### Threading
- **Background Processing**: QThread for scanning
- **Non-blocking UI**: Signal-based updates
- **Cancellation**: Support for operation cancellation

### Memory Management
- **LRU Eviction**: Automatic cache management
- **Copy Semantics**: Prevent data corruption
- **Resource Cleanup**: Proper object deletion

## Usage Workflow

### Initial Setup
1. Configure screenshot folder in settings
2. Set up expense categories
3. Adjust learning threshold if needed
4. Create initial backup

### Daily Usage
1. Take screenshots of transactions
2. Click "Scan Now" to process new files
3. Review categorized items
4. Manually categorize items in NEEDS_ATTENTION
5. Mark completed items as "Done"
6. Export completed transactions

### Maintenance
1. Regular backups (recommended daily)
2. Review and adjust categories
3. Monitor learning system accuracy
4. Clean up old backup files

## Development Notes

### Code Quality
- **Type Hints**: Full type annotation
- **Documentation**: Comprehensive docstrings
- **Error Handling**: Robust exception handling
- **Logging**: Structured logging with levels

### Testing Considerations
- **GUI Testing**: Requires desktop environment
- **OCR Testing**: Needs sample screenshots
- **Data Testing**: CSV and JSON file handling
- **Threading**: Concurrent operation testing

### Extension Points
- **New OCR Sources**: Extend WestpacOCREngine
- **New Categories**: Modify category system
- **Export Formats**: Add new export formats
- **Learning Algorithms**: Enhance LearningSystem

## Conclusion

The NDIS Expense Assistant v3.2 represents a mature, production-ready application with sophisticated OCR capabilities, machine learning-based categorization, and robust data management. Its thread-safe architecture, atomic transactions, and comprehensive error handling make it suitable for enterprise deployment.

The application's modular design allows for easy extension and customization, while its learning system improves accuracy over time through user feedback.