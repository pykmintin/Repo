#!/usr/bin/env python3
"""
Diagnostic Stress Test Suite for CORE Memory Reconstructor
Run: python test_suite.py
"""
import os, json, tempfile, shutil
from chat_processor import process_chat_file, check_strict_duplicate, extract_topics_and_keywords

def run_all_tests():
    print("🧪 Running Diagnostic Tests...\n")
    
    # Test 1: Duplicate Detection
    print("Test 1: Duplicate Detection")
    test_text = "User: Test message about canvas design\nAssistant: Here's the schema\n" * 5
    result1 = process_chat_file("dummy.txt", user_review_mode=False)
    result2 = process_chat_file("dummy.txt", user_review_mode=False)
    assert result2['status'] == 'duplicate_skipped', "Duplicate detection failed"
    print("✅ PASS: Duplicates caught correctly\n")
    
    # Test 2: Topic Extraction Accuracy
    print("Test 2: Topic Extraction")
    core_text = """
    User: Can we design a canvas system with pydantic schemas?
    Assistant: Yes, startup and shutdown workflows can be automated.
    User: What about core memory reconstruction?
    """
    topics = extract_topics_and_keywords(core_text)
    assert 'canvas' in topics['topics'], "Canvas topic missing"
    assert topics['confidence_score'] > 0.5, "Confidence too low"
    print("✅ PASS: Topics extracted accurately\n")
    
    # Test 3: Strict Formatting
    print("Test 3: Strict Turn Formatting")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(test_text)
        f.flush()
        result = process_chat_file(f.name)
        formatted = result['formatted']
        assert "## Turn 1" in formatted, "Turn formatting missing"
        assert "USER:" in formatted, "USER label missing"
        assert "ASSISTANT:" in formatted, "ASSISTANT label missing"
        os.unlink(f.name)
    print("✅ PASS: Strict formatting enforced\n")
    
    # Test 4: Discard Logging
    print("Test 4: Discard Logging")
    assert os.path.exists("discarded_turns_log.json"), "Discard log not created"
    with open("discarded_turns_log.json", 'r') as f:
        log = json.load(f)
    assert len(log) > 0, "No discard decisions logged"
    print("✅ PASS: Discard decisions logged\n")
    
    # Test 5: Uncertain Classification Flagging
    print("Test 5: Uncertain Classification")
    borderline_text = "User: Random question about anime\nAssistant: Some helpful response"
    topics = extract_topics_and_keywords(borderline_text)
    # Should trigger flag due to low CORE relevance
    assert topics['needs_intervention'] == True, "Should flag uncertain classification"
    print("✅ PASS: Uncertain classifications flagged\n")
    
    # Test 6: Signature Stability
    print("Test 6: Signature Stability")
    sig1 = generate_conversation_signature(test_text)
    sig2 = generate_conversation_signature(test_text)
    assert sig1 == sig2, "Signatures not stable"
    assert len(sig1) == 10, "Not exactly 10 signatures"
    print("✅ PASS: Signatures stable and correct length\n")
    
    print("🎉 All tests passed! System ready for production.")

if __name__ == "__main__":
    run_all_tests()