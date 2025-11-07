import os
import json
from datetime import datetime
from collections import defaultdict

# Force UTF-8 everywhere
os.environ["PYTHONUTF8"] = "1"

EXPORT_DIR = os.getcwd()
JSON_OUTPUT_DIR = os.path.join(EXPORT_DIR, "rebuilt_json")
os.makedirs(JSON_OUTPUT_DIR, exist_ok=True)

# === CORE FUNCTIONS ===

def normalize(text: str) -> str:
    """Strict normalization: lowercase, remove special chars, spaces to underscores."""
    if not text:
        return "untitled"
    # Keep alphanumerics only, convert spaces to underscores
    cleaned = ''.join(c if c.isalnum() else '_' for c in text.lower().strip())
    # Collapse multiple underscores
    return '_'.join(filter(None, cleaned.split('_')))[:100]  # Limit length

def safe_load_json(filepath):
    """Load JSON with strict validation."""
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        
        convs = data if isinstance(data, list) else data.get("conversations", [])
        valid_convs = [
            c for c in convs 
            if isinstance(c, dict) and c.get("title") and c.get("id")
        ]
        print(f"✅ {filepath}: {len(valid_convs)} valid conversations")
        return valid_convs
    except Exception as e:
        print(f"❌ Error loading {filepath}: {e}")
        return []

def extract_text(msg: dict) -> str:
    """Extract text from message content."""
    if not msg or not isinstance(msg, dict):
        return ""
    
    content = msg.get("content", {})
    if not content:
        return ""
    
    ctype = content.get("content_type", "text")
    
    if ctype == "text":
        parts = content.get("parts", [])
        return str(parts[0]) if parts else ""
    
    if ctype in ("code", "execution_output", "tether_quote"):
        return content.get("text", "")
    
    return ""

def traverse_linear(conv: dict) -> list[tuple[str, str]]:
    """Extract linear conversation using current_node."""
    mapping = conv.get("mapping", {})
    if not mapping:
        return []
    
    # Primary: current_node traversal
    current_id = conv.get("current_node")
    if current_id and current_id in mapping:
        msgs = []
        node_id = current_id
        steps = 0
        
        while node_id and steps < 1000:
            node = mapping[node_id]
            if msg := node.get("message"):
                role = msg["author"]["role"]
                if role in ("user", "assistant", "tool"):
                    if text := extract_text(msg):
                        msgs.append((role, text))
            
            parent_id = node.get("parent")
            if parent_id == node_id:
                break
            node_id = parent_id
            steps += 1
        
        return list(reversed(msgs))
    
    # Fallback: first-child chain
    root_id = next((k for k, v in mapping.items() if v.get("parent") is None), None)
    if not root_id:
        return []
    
    msgs = []
    visited = set()
    
    def walk_first_child(nid: str):
        if nid in visited:
            return
        visited.add(nid)
        node = mapping[nid]
        if msg := node.get("message"):
            role = msg["author"]["role"]
            if role in ("user", "assistant", "tool"):
                if text := extract_text(msg):
                    msgs.append((role, text))
        children = node.get("children", []) or []
        if children:
            walk_first_child(children[-1])
    
    walk_first_child(root_id)
    return msgs

def rebuild_all_conversations():
    """Process EVERY conversation from all part files directly."""
    
    print(f"🔥 PROCESSING ALL 158 CONVERSATIONS TO JSON")
    print(f"📁 Output: {JSON_OUTPUT_DIR}")
    print("=" * 80)
    
    # Load all part files
    all_conversations = []
    for i in range(1, 5):
        part_file = f"part_{i}.json"
        if os.path.exists(part_file):
            convs = safe_load_json(part_file)
            for conv in convs:
                conv["source_part"] = part_file  # Tag with source
            all_conversations.extend(convs)
    
    if not all_conversations:
        print("❌ No conversations found!")
        return [], []
    
    print(f"\n📊 Total conversations to process: {len(all_conversations)}\n")
    
    results = []
    failed = []
    
    for idx, conv in enumerate(all_conversations, 1):
        title = conv.get("title", "").strip()
        if not title:
            failed.append({"reason": "Missing title", "id": conv.get("id")})
            continue
        
        # Extract messages
        msgs = traverse_linear(conv)
        
        if not msgs:
            failed.append({"title": title, "reason": "No messages extracted", "id": conv.get("id")})
            continue
        
        # Calculate metrics
        user_messages = [m for m in msgs if m[0] == "user"]
        assistant_messages = [m for m in msgs if m[0] == "assistant"]
        
        # Build previews (exactly 100 chars or full text)
        first_preview = msgs[0][1][:100] if msgs else ""
        last_preview = msgs[-1][1][-100:] if msgs else ""
        
        # Normalize filename (STRICT lowercase)
        normalized_title = normalize(title)
        
        # Create result object with strict schema
        result = {
            "title": title,
            "normalized_title": normalized_title,
            "id": str(conv.get("id", "")),
            "create_time": float(conv.get("create_time", 0)),
            "update_time": float(conv.get("update_time", 0)),
            "source_part": conv.get("source_part", ""),
            "part_source": int(conv["source_part"].replace("part_", "").replace(".json", "")) if conv.get("source_part") else 0,
            "mapping_entries": len(conv.get("mapping", {})),
            "turns": len(user_messages),
            "first_preview": first_preview.strip(),
            "last_preview": last_preview.strip(),
            "messages": [{"role": role, "text": text} for role, text in msgs],
            "status": "success",
            "validation": {
                "has_user_messages": len(user_messages) > 0,
                "has_assistant_messages": len(assistant_messages) > 0,
                "total_messages": len(msgs),
                "exchanges": min(len(user_messages), len(assistant_messages))
            }
        }
        
        # Strict validation
        validation_errors = []
        if not result["id"]:
            validation_errors.append("ERROR: Missing ID")
        if not result["first_preview"]:
            validation_errors.append("ERROR: Empty first preview")
        if not result["last_preview"]:
            validation_errors.append("ERROR: Empty last preview")
        if result["turns"] == 0:
            validation_errors.append("ERROR: No user messages")
        
        if validation_errors:
            result["status"] = "validation_failed"
            result["validation_errors"] = validation_errors
            failed.append(result)
        else:
            results.append(result)
        
        # Write individual JSON file (STRICT lowercase filename)
        fname = f"{normalized_title}.json"
        json_path = os.path.join(JSON_OUTPUT_DIR, fname)
        
        try:
            with open(json_path, "w", encoding="utf-8") as out:
                json.dump(result, out, indent=2, ensure_ascii=False)
            
            if idx % 20 == 0 or idx == len(all_conversations):
                print(f"✅ ({idx}/{len(all_conversations)}) {title[:50]}... → {fname}")
        except Exception as e:
            print(f"❌ Write error: {e}")
            failed.append({"title": title, "reason": f"write_failed: {e}"})
    
    # Final summary
    print(f"\n{'='*80}")
    print("📊 FINAL SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successfully processed: {len(results)} conversations")
    if failed:
        print(f"❌ Failed/Validation errors: {len(failed)}")
    
    # Save comprehensive master manifest
    master_manifest = {
        "manifest_version": "2.1",
        "source_exports": [f"part_{i}.json" for i in range(1, 5)],
        "conversations": results,
        "failed_conversations": failed,
        "total_conversations": len(results),
        "failed_count": len(failed),
        "generated_on": datetime.now().isoformat(),
        "stats": {
            "success_rate": f"{(len(results)/len(all_conversations)*100):.1f}%",
            "total_processed": len(all_conversations),
            "total_expected": 158
        }
    }
    
    with open("rebuild_manifest_complete.json", "w", encoding="utf-8") as out:
        json.dump(master_manifest, out, indent=2, ensure_ascii=False)
    
    # Save validation report
    with open("rebuild_validation_report.txt", "w", encoding="utf-8") as out:
        out.write("VALIDATION REPORT\n")
        out.write("="*80 + "\n\n")
        out.write(f"Total processed: {len(all_conversations)}\n")
        out.write(f"Successful: {len(results)}\n")
        out.write(f"Failed: {len(failed)}\n\n")
        
        if failed:
            out.write("FAILED ENTRIES:\n")
            for f in failed:
                out.write(f"\n- {f.get('title', 'Unknown')}\n")
                out.write(f"  ID: {f.get('id', 'N/A')}\n")
                if 'validation_errors' in f:
                    for err in f['validation_errors']:
                        out.write(f"  {err}\n")
                elif 'reason' in f:
                    out.write(f"  Reason: {f['reason']}\n")
    
    print(f"\n💾 Master manifest: rebuild_manifest_complete.json")
    print(f"📁 JSON files: {JSON_OUTPUT_DIR}")
    print(f"📄 Validation report: rebuild_validation_report.txt")
    
    return results, failed

if __name__ == "__main__":
    results, failed = rebuild_all_conversations()
    
    if results:
        print(f"\n🎯 Sample entry:")
        preview = json.dumps(results[0], indent=2, ensure_ascii=False)
        print(preview[:600] + "..." if len(preview) > 600 else preview)