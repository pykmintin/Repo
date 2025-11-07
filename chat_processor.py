#!/usr/bin/env python3
"""
Chat History Reconstructor v3.0 - Memory Reconstruction Core
Handles: duplicate detection, topic extraction, keyword generation, uncertainty flagging
"""
import os, re, json, csv, uuid, hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
MANIFEST_CSV = "manifest_export_wide.csv"
PENDING_JSON = "pending_manifest.json"
INDEX_JSON = "conversations_index.json"
DISCARDED_LOG = "discarded_turns_log.json"
UNCERTAIN_LOG = "uncertain_classifications.json"

# Ensure files exist
for f in [PENDING_JSON, INDEX_JSON, DISCARDED_LOG, UNCERTAIN_LOG]:
    Path(f).touch(exist_ok=True)

# ──────────────────────────────────────────────────────────────
# DUPLICATE DETECTION ENGINE
# ──────────────────────────────────────────────────────────────
def generate_conversation_signature(text: str) -> List[str]:
    """Generate 10 unique signatures from chat turns (4-5 word snippets)"""
    # Extract User:Assistant turn pairs
    turns = re.findall(r'User:\s*(.+?)\nAssistant:\s*(.+?)(?:\n|$)', text[:3000])
    signatures = []
    
    for user_turn, assist_turn in turns[:10]:  # First 10 turns
        # Take first 4-5 words from each turn
        user_snippet = ' '.join(user_turn.split()[:5])
        assist_snippet = ' '.join(assist_turn.split()[:5])
        if user_snippet and assist_snippet:
            signature = f"{user_snippet}|{assist_snippet}"
            signatures.append(hashlib.md5(signature.encode()).hexdigest()[:16])
    
    return signatures[:10]  # Exactly 10 signatures

def check_strict_duplicate(raw_text: str, threshold: int = 3) -> Tuple[bool, str, int]:
    """
    Check if conversation is duplicate using multi-signature matching
    Returns: (is_duplicate, existing_id, match_count)
    """
    signatures = generate_conversation_signature(raw_text)
    if not signatures:
        return False, "", 0
    
    if os.path.getsize(INDEX_JSON) == 0:
        return False, "", 0
    
    with open(INDEX_JSON, 'r', encoding='utf-8') as f:
        index = json.load(f)
    
    for conv_id, meta in index.items():
        if 'signatures' in meta:
            existing_sigs = meta['signatures']
            match_count = len(set(signatures) & set(existing_sigs))
            if match_count >= threshold:
                return True, conv_id, match_count
    
    return False, "", 0

# ──────────────────────────────────────────────────────────────
# TOPIC & KEYWORD EXTRACTION (LM-Driven)
# ──────────────────────────────────────────────────────────────
def extract_topics_and_keywords(text: str, user_intervention: bool = False) -> Dict[str, Any]:
    """
    Extract topics and keywords with uncertainty flags
    Uses pattern matching + LM-style heuristics
    """
    # Technical patterns (high confidence)
    tech_patterns = {
        'canvas': r'\b(Canvas|CANVAS)\b',
        'workflow': r'\b(Workflow|workflow|process|routine)\b',
        'startup': r'\b(Startup|startup|boot|initialize)\b',
        'shutdown': r'\b(Shutdown|shutdown|finalize|archive)\b',
        'core': r'\b(Core|CORE|system_architecture)\b',
        'schema': r'\b(schema|pydantic|yaml|json)\b',
        'automation': r'\b(automation|script|batch|powershell)\b',
        'logging': r'\b(logging|log|Operational Log|chatlog)\b'
    }
    
    # Conceptual patterns (medium confidence)
    concept_patterns = {
        'learning': r'\b(learning|reference|L[1-5]|Level [1-5])\b',
        'priority': r'\b(priority|P[0-3]|high|low|normal)\b',
        'integration': r'\b(integration|sync|bridge|API)\b',
        'memory': r'\b(memory|reconstruction|archive|index)\b'
    }
    
    topics = []
    keywords = []
    uncertain_flags = []
    
    # High confidence extraction
    for topic, pattern in tech_patterns.items():
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            topics.append(topic)
            keywords.extend([m.lower() for m in matches])
    
    # Medium confidence (flag for review if found)
    for concept, pattern in concept_patterns.items():
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            topics.append(concept)
            keywords.extend([m.lower() for m in matches])
            uncertain_flags.append(concept)
    
    # Remove duplicates
    topics = list(set(topics))
    keywords = list(set(keywords))
    
    # If uncertainty threshold exceeded, flag for user
    needs_intervention = len(uncertain_flags) >= 3 and user_intervention
    
    return {
        "topics": topics,
        "keywords": keywords,
        "uncertain_flags": uncertain_flags,
        "needs_intervention": needs_intervention,
        "confidence_score": len([t for t in topics if t in tech_patterns]) / max(len(topics), 1)
    }

# ──────────────────────────────────────────────────────────────
# DISCARD & UNCERTAINTY LOGGING
# ──────────────────────────────────────────────────────────────
def log_classification_decision(
    conv_id: str, 
    decision: str,  # "keep", "flag", "discard"
    reason: str,
    topics: List[str],
    confidence: float
):
    """Log every classification decision for audit trail"""
    log_file = UNCERTAIN_LOG if decision == "flag" else DISCARDED_LOG
    
    entry = {
        "conv_id": conv_id,
        "timestamp": datetime.now().isoformat(),
        "decision": decision,
        "reason": reason,
        "topics": topics,
        "confidence": confidence,
        "user_overridden": False  # Set to True if user changes decision
    }
    
    existing = []
    if os.path.getsize(log_file) > 0:
        with open(log_file, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    
    existing.append(entry)
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2)

# ──────────────────────────────────────────────────────────────
# STRICT FORMATTING ENGINE
# ──────────────────────────────────────────────────────────────
def format_strict_human_readable(entry: Dict) -> str:
    """Format with strict turn-by-turn structure"""
    output = f"{{Header: {entry['title']}}}\n"
    output += f"ID: {entry['id']}\n"
    output += f"Timestamp: {datetime.now().isoformat()}\n"
    output += f"Topics: {', '.join(entry.get('topics', []))}\n"
    output += f"Keywords: {', '.join(entry.get('keywords', []))}\n\n"
    
    if 'messages' in entry:
        for i, msg in enumerate(entry['messages'], 1):
            role = msg.get('role', 'unknown').upper()
            content = msg.get('content', '').strip()
            
            # Wrap turns clearly
            output += f"## Turn {i}\n"
            output += f"{role}: {content}\n\n"
    
    # Add code refs if present
    if 'code_blocks' in entry and entry['code_blocks']:
        output += "###[REF]###\n"
        for ref_id, block in entry['code_blocks'].items():
            output += f"###{ref_id}###\n"
            output += f"Language: {block['language']}\n"
            output += f"Lines: {block['line_count']}\n"
            output += f"Description: {block['description']}\n\n"
    
    return output

# ──────────────────────────────────────────────────────────────
# MAIN PROCESSING PIPELINE
# ──────────────────────────────────────────────────────────────
def process_chat_file(filepath: str, user_review_mode: bool = False) -> Dict[str, Any]:
    """
    Full pipeline: load → dedupe → extract topics → classify → format → log
    Returns result dict with classification decision
    """
    if not os.path.exists(filepath):
        return {"error": "File not found"}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        raw_text = f.read()
    
    # Skip if too short
    if len(raw_text) < 500:
        return {"error": "Content too short"}
    
    # Check for duplicates
    is_dup, dup_id, match_count = check_strict_duplicate(raw_text)
    if is_dup:
        log_classification_decision(
            conv_id=str(uuid.uuid4()),
            decision="discard",
            reason=f"Duplicate of {dup_id} ({match_count} signature matches)",
            topics=[],
            confidence=1.0
        )
        return {"status": "duplicate_skipped", "duplicate_id": dup_id}
    
    # Extract topics and keywords
    extraction = extract_topics_and_keywords(raw_text, user_intervention=user_review_mode)
    
    # Classify relevance to CORE
    relevance_score = extraction['confidence_score']
    core_keywords = ['canvas', 'core', 'workflow', 'startup', 'shutdown', 'schema', 'automation']
    core_match = len([k for k in extraction['keywords'] if k in core_keywords])
    
    # Decision logic
    if core_match >= 3 and relevance_score >= 0.6:
        decision = "keep"
        reason = "High CORE relevance"
    elif extraction['needs_intervention']:
        decision = "flag"
        reason = "Uncertain classification - needs review"
    elif core_match == 0 and relevance_score < 0.3:
        decision = "discard"
        reason = "Low CORE relevance"
    else:
        decision = "flag"
        reason = "Borderline relevance"
    
    # Generate manifest entry
    entry, formatted, code_blocks = generate_manifest_entry(raw_text)
    entry.update({
        "topics": extraction['topics'],
        "keywords": extraction['keywords'],
        "relevance_score": relevance_score,
        "core_matches": core_match,
        "classification": {
            "decision": decision,
            "reason": reason,
            "confidence": relevance_score
        }
    })
    entry['code_blocks'] = code_blocks
    
    # Log decision
    log_classification_decision(
        conv_id=entry['id'],
        decision=decision,
        reason=reason,
        topics=extraction['topics'],
        confidence=relevance_score
    )
    
    return {
        "status": decision,
        "entry": entry,
        "formatted": formatted,
        "duplicate_check": {"is_duplicate": False}
    }

# ──────────────────────────────────────────────────────────────
# COMMAND-LINE INTERFACE
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python chat_processor.py <chat_file.txt> [--review]")
        sys.exit(1)
    
    filepath = sys.argv[1]
    review_mode = "--review" in sys.argv
    
    result = process_chat_file(filepath, user_review_mode=review_mode)
    
    print(json.dumps(result, indent=2, default=str))