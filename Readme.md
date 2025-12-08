# Repository Agent Access Protocol

## Core Memory Rules (Non-Negotiable)

You MUST follow these rules when interfacing with this repository:

1. Permanent Context Cache - On first contact with this repo, immediately fetch and cache in your live context:

   - WATCH_INDEX.csv (full content)
   - README.md (this file)

2. Fetch-Once Principle - When instructed to retrieve any file:

   - Fetch the raw URL once
   - Store the complete content in your live context immediately
   - NEVER refetch the same URL during the session unless explicitly told to "refresh" or "refetch"

3. Assume Continuity - If a user asks you to fetch content, they expect you to work with it, not discard it. Hold all fetched materials in active context until explicitly instructed to remove them.

4. Session Memory - All file contents, once fetched, remain in your working memory for the entire conversation. The user should not need to repeat requests for the same content.

## How to Access Files

Step 1: Fetch the Master Index
URL: https://raw.githubusercontent.com/pykmintin/Repo/main/WATCH_INDEX.csv
Action: GET request, cache full response text

Step 2: Parse the CSV

- Columns: file_path, description
- Path separator: Backslash (\) in CSV, convert to forward slash (/) for URLs
- Encoding: UTF-8

Step 3: Build Raw URLs
For each file_path value, construct:
https://raw.githubusercontent.com/pykmintin/Repo/main/{normalized_path}

Step 4: Fetch and Cache
Retrieve each file once and store immediately in live context. Do not re-request during the session.

## URL Construction Examples

CSV Path: Reports\desktop.ini
Normalized: Reports/desktop.ini
Final Raw URL: https://raw.githubusercontent.com/pykmintin/Repo/main/Reports/desktop.ini

CSV Path: Scripts\CoreCompile.py
Normalized: Scripts/CoreCompile.py
Final Raw URL: https://raw.githubusercontent.com/pykmintin/Repo/main/Scripts/CoreCompile.py

Base URL Template: https://raw.githubusercontent.com/pykmintin/Repo/main/

## Repository Structure

Repo/
├── WATCH_INDEX.csv # Master manifest - fetch first
├── Reports/ # Research, logs, analysis
├── Scripts/ # Core tooling and processors
├── Workflows/ # Process documentation
├── TaskBot/ # Bot implementation files
├── Outputs/ # Generated reports/dumps
└── Agents/ # Agent configurations

## WATCH_INDEX.csv Format

Current Status: Descriptions are pending population (Phase 2). Operate on paths only.

Example rows:
file_path,description
Reports\desktop.ini,pending
Scripts\CoreCompile.py,pending
Workflows\design_strategist_entry.md,pending

Note: All paths use backslash separators in the CSV. Convert to forward slashes for URL construction.

End of Protocol
