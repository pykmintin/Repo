````markdown
# Repository Agent Access Protocol v2.10 - Complete

## Document Evolution History

**Origin**: This protocol was collaboratively designed through 200+ turn conversation addressing critical failures in repository management automation. Key discoveries:

1. **Live Sync Risk**: Filesystem auto-commits to GitHub → re-fetching gives broken versions
2. **Turn Amnesia**: Couldn't track instruction boundaries → executed stale instructions
3. **Context Bleed**: No separation between historical and current instructions
4. **Subtask Confusion**: Flat context couldn't handle hierarchical work
5. **Manifest Corruption**: Lost track of WATCH_INDEX.csv evolution

**Solution**: Explicit state object + lifecycle management + chat history as version control

---

## First Turn Charter Declaration

**When User posts this README link, Assistant must:**

1. **Fetch and read** the raw README.md content
2. **Create `CONVERSATION_STATE.json`** with initial stack
3. **Reproduce this entire README verbatim** in output
4. **State operational mode**: "Assistant operates under Repository Agent Access Protocol v2.10, maintaining CONVERSATION_STATE.json for instruction lifecycle management. All suggestions await User authorization."

**Purpose**: Self-bootstrapping ensures protocol presence and demonstrates comprehension.

---

## Core Principle: Live Bidirectional Sync + Structured Version Control

**Critical Reality**: This repository auto-commits local saves to GitHub. Re-fetching raw links returns broken post-modification versions. **Chat history is the only source of truth for pre-modification states.**

---

## Context Object: CONVERSATION_STATE.json

**Mandatory live-context artifact** (never saved to repository):

```json
{
  "instruction_stack": [
    {
      "instruction": "string - current instruction or sub-instruction",
      "turn_started": "integer - turn number",
      "state": "ENUM: EXPLORATORY, APPROVED, DELIVERY_REQUESTED",
      "parent_index": "integer or null"
    }
  ],
  "files_in_context": {
    "file_path": {
      "original_turn": "integer",
      "current_version": "ENUM: ORIGINAL, STAGED, DELIVERED",
      "staged_changes": ["array"]
    }
  },
  "last_processed_turn": "integer",
  "manifest_version": "string"
}
```
````

**Why**: Forces explicit state tracking. Prevents instruction bleed-through. Enables hierarchical work.

---

## Master File: WATCH_INDEX.csv Management

**Original Problem**: 175 entries, all "pending", system files included.

**Solution**: Repository agent access protocol to collaboratively populate descriptions while maintaining complete manifest.

### **Manifest State Tracking**

- **Total entries**: 96 (after removing 11 system files)
- **Status fields**: file_path, description
- **Description lifecycle**: "pending" → User-approved description

**Collaborative workflow**:

1. Assistant fetches file
2. Proposes description for verification
3. Upon User approval, updates manifest
4. Delivers complete updated manifest on User request

**This ensures**: No partial updates, complete file always delivered, rollback preserved.

---

## Collaboration States with Instruction Stack

### **STATE 1: Exploratory Discussion**

- User asks questions, sub-instructions, explores tradeoffs
- Assistant analyzes, shows diffs, discusses
- **NO modifications to live context**
- **CONVERSATION_STATE.json: top.state = "EXPLORATORY"**

### **STATE 2: Changes Approved, Awaiting Delivery**

- User explicitly approves current instruction: "Yes, do it"
- Assistant stages changes
- **CONVERSATION_STATE.json: top.state = "APPROVED"**

**Required**: "Original preserved from Turn X for rollback."

### **STATE 3: Delivery Requested**

- User triggers delivery: "Give me updated file", "Checkpoint"
- **NOW** Assistant delivers complete file
- **CONVERSATION_STATE.json: top.state = "DELIVERY_REQUESTED"**

---

## State Transitions with Stack Management

**Rule 1: Exploratory → Approved** (current top)

- User approves current instruction
- Update top.state = "APPROVED"

**Rule 2: Approved → Delivery** (current top)

- User triggers delivery for current instruction
- Update top.state = "DELIVERY_REQUESTED", deliver file

**Rule 3: Sub-Instruction Creation**

- User asks new question under current work: Push new instruction onto stack
- Update files_in_context, last_processed_turn

**Rule 4: Sub-Instruction Completion**

- User satisfied with subtask: Pop stack, return to parent context

---

## Critical Operational Rules

### **Live Context Lock**

**Rule**: Once file fetched and modified, Assistant must retain complete file + original version in live context throughout session.

**Prohibition**: Re-fetching from GitHub after modification (gives broken version).

### **Rollback Preservation**

**Every staging/delivery**: Must state "Original preserved from Turn X for rollback if needed."

**Why**: Chat history is only source of working versions when auto-sync breaks.

### **Change Visibility for Large Files**

**Format**: "Lines 45-48: [old] → [new]"

**Prevents**: Missing changes in full output.

### **Stale Context Detection**

**When**: User references file not in files_in_context or original_turn >5 turns old

**Action**: "Has [filename] been modified since Turn [X]?"

**Why**: Auto-sync breaks continuity.

### **Explicit Delivery Triggers**

**Triggers**: "Give me updated file", "Confirm changes", "Checkpoint"

**Critical**: Discussion + approval ≠ delivery. Must explicitly request file.

### **Reports Handling**

- Keep all Reports/ entries in manifest with descriptions
- Suggest one PDF at a time when relevant
- Never auto-fetch (10,000+ token cost per PDF)

**Rationale**: Descriptions enable selective fetching at minimal token cost.

---

## Error Recovery Flow

**When propagated change breaks system**:

1. Assistant references CONVERSATION_STATE.json → files_in_context.original_turn
2. Retrieves pre-modification version from live context (not broken GitHub)
3. Proposes rollback: "Revert to original from Turn X?"
4. If approved, delivers complete reverted file

**Why**: Re-fetching gives broken version (auto-commit). Chat history holds working version.

---

## What This Protocol Prevents

**Our Historical Failures**:

1. **Auto-delivery without request** → User missed errors
2. **Re-fetch after auto-commit** → Got broken version, lost working state
3. **Assuming approval** → Applied changes still being discussed
4. **Lost context** → Couldn't reconstruct what changed
5. **Instruction bleed-through** → Executed 10-turn-old instructions
6. **Subtask confusion** → Flat context couldn't handle hierarchy

**Result**: Hierarchical fault-tolerant collaboration with explicit state objects and chat history as version control.

---

## Example Interaction with Full Protocol

**Turn 5**: User: "[INSTRUCTION_START] Improve the task bot script [INSTRUCTION_END]"  
**Assistant**: Creates CONVERSATION_STATE.json, pushes "Improve task bot script" to stack, state = EXPLORATORY

**Turn 6**: User: "What if we change priority logic?"  
**Assistant**: Pushes "Change priority logic" as sub-instruction, shows diffs, state = EXPLORATORY

**Turn 7**: User: "Good idea, do it"  
**Assistant**: Updates stack[1].state = APPROVED, stages changes: "Original at Turn 6 preserved"

**Turn 8**: User: "Also add a new command"  
**Assistant**: Pushes "Add new command" as new sub-instruction

**Turn 9**: User: "Checkpoint the priority changes"  
**Assistant**: Delivers priority changes (original at Turn 6), pops completed sub-instruction

**Turn 10**: User: "[INSTRUCTION_START] Give me complete updated file [INSTRUCTION_END]"  
**Assistant**: Updates WATCH_INDEX.csv with new descriptions, delivers complete file + manifest

**Later, Turn 20**: User: "Rollback priority changes"  
**Assistant**: References CONVERSATION_STATE.json, finds original_turn = 6, retrieves from live context

---

## Protocol Enforcement with State Object

**User detects violation**: "Protocol violation: [rule]"  
**Assistant must**:

1. Halt immediately
2. Acknowledge violation
3. Review CONVERSATION_STATE.json for error source
4. Revert to compliant state

**Hard constraints**:

- No re-fetching after modification
- No partial delivery of files
- No silent updates
- Must update CONVERSATION_STATE.json every turn
- Must preserve originals for rollback
- Must maintain explicit instruction stack

---

## Session State Recovery

**If Assistant detects context loss**:

1. Declares: "Assistant: Context synchronization error detected"
2. Requests permission: "Should Assistant re-fetch [file]?"
3. Only re-fetches with explicit authorization
4. Updates CONVERSATION_STATE.json with new state

---

**Purpose**: This protocol captures complete evolution from flat context failures to explicit state management, enabling reliable hierarchical collaboration with chat history as comprehensive version control audit trail.

```

```
