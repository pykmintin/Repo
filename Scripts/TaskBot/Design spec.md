**Authority Plan v1.6 - Plain Language Specification**

---

## **1. Intent Digest**

**Working Assumptions**: 
- User does <20 operations/day, volume is trivial
- No background sync needed - all actions are on-demand
- Bot must work standalone without Kimi voice thread (voice is optional enhancement)
- If user doesn't specify time in export command, bot must ask rather than assume
- Auto-archive triggered at 500 completed tasks (not 1000) for 50-day history window
- Schema files are final planning deliverable, not yet created

---

## **2. Authority Plan v1.6 - Final Specification**

### **Mission & Constraints**

**Goal**: Transform the existing single-list command-based Discord bot into a natural language task manager optimized for mobile use.

**Non-Negotiable Constraints**:
- **Python Version**: 3.14-slim (user-overridden from Dockerfile's 3.11)
- **Hosting**: Fly.io 256MB RAM, shared CPU, free tier only
- **Authentication**: Single authorized user ID: 367581971053805568. All messages from this user are bot commands - no prefix required
- **Storage**: GitHub API (pykmintin/Repo) is single source of truth. Single `tasks.json` file with two sections
- **No Background Sync**: Discord↔Fly.io communication is real-time message handling only. No daemons, no scheduled tasks
- **Google Calendar Export**: Manual, on-demand secondary target only. No automatic sync, no bidirectional updates
- **Volume**: User performs <20 operations/day. All operations are trivial performance-wise.

### **Current Reality (Before Changes)**

**Deployed System**:
- Fly.io app "taskbot" operational
- GitHub repo `pykmintin/Repo` contains `tasks.json`
- **Current Task Count**: 24 total tasks (8 high undo, 13 normal undo, 3 completed)
- **Current Behavior**:
  - Commands: `!add h/n [task]`, `!tasks`, `!done #`, `!delete #`
  - Authorization functional (ignores all users except 367581971053805568)
  - Reaction handler active (must be removed per user request)
  - Single list only (not the multi-list design we're implementing)

**Must Remove**: Reaction completion handler (`on_reaction_add` event)

### **Core Features (Implementation Ready)**

#### **Multi-List System**
- **Two Lists**: `personal` (default), `work`
- **VTT-Friendly Synonyms**: 
  - `work` = `calling` = `corelink`
  - No single-letter `c` synonym for work (reserved for `complete` action)
- **Data Model**: Single `tasks.json` with two sections:
  - `"personal": {"tasks": [...]}`
  - `"work": {"tasks": [...]}`
  - `"metadata": {"active_list": "personal", "google_token": null}`
- **ID Scope**: Task IDs are per-list (personal #1, work #1 can both exist). IDs are never reused after deletion
- **Context Persistence**: Bot remembers which list is active across restarts (stored in metadata)

#### **Task Creation**
**Natural Mode** (No action keyword):
- `dentist tomorrow` → Creates in personal list, normal priority
- `dentist tomorrow high` → Creates in personal list, high priority
- `work: call boss` → Creates in work list, normal priority
- `calling: dentist urgent` → Creates in work list, high priority
- Multi-line support: Each newline creates separate task

**Stacked Mode** (Explicit action):
- Format: `[action] [list] [priority] [text]`
- Example: `add w high dentist appointment` → work, high
- Shortcuts: `a w h dentist` or `+ w h dentist`
- Bot always confirms: `✅ #25 [high] dentist appointment (work list)`

**Ambiguity Handling**:
- Single number like `25` → Bot asks: `❌ Please specify action for #25 (e.g., "done 25" or "delete 25")`
- Unrecognized input → Bot asks: `❌ Could not parse: "input". Please use format: "list work" or "dentist tomorrow high"`
- Typos → Bot attempts fuzzy match: `Did you mean "delete 25"?`

#### **Task Operations**
- **Complete**: `c 25` or `finish 25` or `done 25` or `x 25` → marks done, removes from active list
- **Delete**: `d 25` or `delete 25` or `k 25` or `rm 25` → permanent deletion
- **Undo**: `undo` → reverses last action. `undo list` shows last 10 actions. `undo 3` reverses the 3rd action in list
- **Batch Operations**: `c 25,26,27` and `d 25,26,27` → applies operation to multiple IDs
- **Error Messages**: Specific and helpful
  - `❌ Task #25 already completed` (vs generic "not found")
  - `❌ Task #99 does not exist in work list`

#### **List Viewing**
- **Active Tasks**: `tasks` or `t` or `active` → Shows uncompleted tasks only
  - Sort: High priority first, then normal
  - Display: `🔴 #25 ⏳ dentist` (high) / `⚪ #26 ⏳ call mom` (normal)
  - IDs are renumbered 1-X for display, but bot accepts both display and storage IDs
- **Completed Tasks**: `history` or `h` → Shows completed tasks, chronologically sorted (oldest first)
  - Accepts count: `h 5` shows last 5 completed
  - Format: `✅ #15 (completed 2025-12-01) dentist appointment`
- **Current Context**: `current` → Shows active list (personal/work) and last 5 actions

#### **Google Calendar Export** (Lowest Development Priority)
- **Command**: `export 25 tonight 5pm` or `e 25 tomorrow 2pm`
- **Time Validation**: If time not specified, bot **must ask**:
  - `❌ Please specify time: "tonight 5pm"` (no defaults)
- **Behavior**: Creates Google Calendar event. Does not modify GitHub data
- **Idempotency**: Ignore duplicates (manual cleanup acceptable for single-user system)
- **Auth Storage**: Store `google_token` in GitHub JSON under `metadata.google_token`

#### **Utility Commands**
- **Current Context**: `current` → Shows active list and recent actions
- **Action Log**: `log [number]` → Shows last N actions (customizable)

### **Auto-Archive Strategy**
- **Trigger**: When completed task count >500, oldest tasks move to `tasks_archive.json`
- **Archive File Structure**: Separate JSON file with same format, holds old completed tasks
- **Purpose**: Keeps main `tasks.json` fast for daily operations
- **Manual Control**: `archive 100` command (optional) to manually archive

### **Data Schema (Conceptual)**

**Main File (tasks.json)**:
- Single file with three sections: `metadata`, `personal`, `work`
- Each task has: id, text, prio, done, created, completed, due_date (reserved)
- Metadata stores active list and Google auth token

**Archive File (tasks_archive.json)**:
- Created automatically when completed tasks exceed 500
- Mirrors same structure, holds historical completed tasks

### **Wishlist Features (Future, Not MVP)**
- **Search Filters**: `search high work` → find high priority work tasks
- **Subtasks**: Hierarchical task structure
- **Task Templates**: For recurring task types
- **Import/Export**: Bulk migrate from other systems
- **Time Tracking**: Track time spent on tasks
- **Stats Dashboard**: Completion rates, trends

### **Implementation Priority**
1. **Migrate current tasks.json** from single-list to two-list schema
2. **Implement auto-archive functionality** (trigger at 500 completed)
3. **Add expansive undo system** (`undo`, `undo list`, `undo [number]`)
4. **Implement dynamic ID system** (accept both display and storage IDs)
5. **Add new utility commands** (`current`, `log [number]`)
6. **Implement Google export** with time validation (no defaults, always ask if missing)
7. **Test complete system functionality** with all edge cases

### **Migration from Current System**

**Current Reality**: 
- Single list of 24 tasks in `tasks.json`
- Format: `{"tasks": [{"id": 1, "text": "...", "prio": "high/normal", "done": false/true, "created": "..."}]}`
- Must transform to new two-list format

**Migration Steps**:
1. **Read current `tasks.json`** from GitHub
2. **Create new structure**: Add `metadata` section (active_list: "personal")
3. **Move all tasks**: Place all current tasks into `personal.tasks` array
4. **Add new fields**: `completed` (null if not done), `due_date` (null, reserved)
5. **Preserve all data**: Keep original IDs, dates, text, priorities, status
6. **Write new structure**: Save as new `tasks.json` format
7. **Create archive file**: Initialize empty `tasks_archive.json`

**Testing**:
- Verify all 24 tasks migrated correctly
- Verify no data loss
- Verify new commands work with migrated data

---

## **3. Verification**

**Pending Items for Coding Agent**:
- Exact file paths (can be asked for from user)
- Google OAuth setup steps
- Discord developer portal configuration (if any changes needed)

