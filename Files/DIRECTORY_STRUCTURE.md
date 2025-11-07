# Directory Structure Map
*Generated: 2025-11-07 20:50:48*

## 📍 Path Explanations

### Working-DIR Repository (CRITICAL)
**`C:\Users\JoshMain\Documents\Working-DIR`**
- **Purpose**: Git repository = repo- primary development
- **Action**: ✅ROOT = PRIVATE Edit files here
- **Contents**: `Files/`, `README.md`, version controlled code

### Soul_Algorithm GoogleDrive Mirror (RUNTIME)
**`C:\Soul_Algorithm\`**  
- **Purpose**: Live environment
- **WARNING**: ❌ DO NOT edit directly without archiving
- **Action**: Use CoreLink.pyw update mechanism
- **Mirror of**: `Working-DIR\Files\`

### Backup Storage (FINAL BACKUP ARCHIVE)
**`C:\Backups_Soul`**
- **Purpose**: Historical data and snapshots
- **Action**: Store backups here

---

## 📂 Detailed Structure


### C:\\Users\\JoshMain\\Documents\\Working-DIR
Git repository - Working-DIR
Primary development location
Version controlled

- **.git/**
  - COMMIT_EDITMSG
  - FETCH_HEAD
  - HEAD
  - ORIG_HEAD
  - config
  - ... (2 more)
  - **hooks/**
    - applypatch-msg.sample
    - commit-msg.sample
    - fsmonitor-watchman.sample
    - post-update.sample
    - pre-applypatch.sample
    - ... (9 more)
  - **info/**
    - exclude
  - **logs/**
    - HEAD
  - **objects/**
  - **refs/**
- **Files/**
  - CORELINKSCHEMAMUSTREAD.json
  - CoreLink.py
  - CoreLink.pyw
  - DupeChecker.py
  - PROMPT.txt
  - ... (8 more)
- **__pycache__/**
  - chat_processor.cpython-314.pyc
  - csv.cpython-314.pyc
- **logs/**
  - cleanup_directory.log
  - conversations_index.json
  - discarded_turns_log.json
  - file_status_check.log
  - filename_matching.log
  - ... (2 more)

### C:\\Soul_Algorithm\\Scripts
Live execution environment
Mirror of repo Files folder
DO NOT edit directly - use update mechanism

- **ChatLogs/**
  - desktop.ini
- **Files/**
  - DupeChecker.py
- **Reports/**
  - desktop.ini
- **__pycache__/**
  - desktop.ini
- **logs/**
  - cache_clear_log.txt
  - corelink.log
  - desktop.ini
  - grab_log.txt

### C:\\Backups_Soul
Backup location
Historical data and snapshots

- **Dont need sync symlinks/**
  - Phase1_Stable_Set.zip
  - desktop.ini
  - **Phase1_Stable_Set/**
    - Phase1_Stable_Set.zip
    - chat_catalog.csv
    - desktop.ini
    - phase1_catalog_build_selfcontained.py
    - phase1_extract.py
    - ... (2 more)
  - **handoff_bundle_phase3/**
    - INITIAL_ONLYFORREF.zip
    - Phase1_Stable_Set.zip
    - canvas_seed.md
    - conversations.json
    - desktop.ini
    - ... (6 more)
- **Soul_Algorithm/**
  - core_pipeline.schema.v1.json
  - core_system_definition.append.v1.json
  - core_system_definition.append4.v1.json
  - core_system_definition.update.v1.json
  - core_workflows.append.2v1.json
  - ... (5 more)
  - **Archive/**
    - Backups_Soul - Shortcut.lnk
    - Phase1_Stable_Set.zip
    - checkpoint_pre_integration.zip
    - desktop.ini
    - handoff_bundle_phase3.zip
  - **Core/**
    - core_doctrine.json
    - core_index.json
    - core_system_definition.json
    - desktop.ini
    - opt_pipeline.json
    - ... (2 more)
  - **MemoryReconDATA - MASTER DIR/**
    - FINAL_PROMPT_v5.txt
    - README.txt
    - desktop.ini
  - **Scripts/**
    - AniList.py
    - ComicScript.py
    - CoreLink.py
    - CoreLink.pyw
    - cacheclearedge.py
    - ... (7 more)
  - **Webhook/**
    - Mirror Mode Viewer.gsheet
    - TODO.json
    - desktop.ini
    - instructions.gdoc
    - instructions.txt
    - ... (2 more)
- **Windows_Docs_Core/**
  - Windows_Docs_Core.zip
