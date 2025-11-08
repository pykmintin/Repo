#!/usr/bin/env python3
"""CoreLink Bridge v3.18 - 3-Button Error Dialog"""

import os, sys, json, subprocess, pyperclip, datetime, tkinter as tk, traceback, shutil
from tkinter import messagebox, filedialog
from pathlib import Path

ROOT_DIR = r"C:\Soul_Algorithm"
SOUL_DIR = os.path.join(ROOT_DIR, "Soul_Algorithm")
BASE_DIR = os.path.join(SOUL_DIR, "Scripts")
ARCHIVE_DIR = os.path.join(SOUL_DIR, "Archive", "Backups")
TEMP_DIR = os.path.join(SOUL_DIR, "Archive", "CoreLink")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "corelink.log")
CHATLOG_DIR = os.path.join(BASE_DIR, "ChatLogs")
REPORTS_DIR = os.path.join(BASE_DIR, "Reports")
FLAG_FILE = os.path.join(BASE_DIR, "update.flag")
NOTEPADPP = r"C:\Program Files\Notepad++\notepad++.exe"

def write_log(message: str, data: dict = None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {"time": timestamp, "message": message}
    if data:
        log_entry["data"] = data
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

def archive_if_exists(target_path: str) -> dict:
    if not os.path.exists(target_path):
        return None
    try:
        original_size = os.path.getsize(target_path)
        original_name = os.path.basename(target_path)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name_parts = original_name.rsplit('.', 1)
        archive_name = f"{name_parts[0]}_{timestamp}.{name_parts[1]}" if len(name_parts) > 1 else f"{original_name}_{timestamp}"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        shutil.copy2(target_path, archive_path)
        archived_size = os.path.getsize(archive_path)
        if original_size != archived_size:
            os.remove(archive_path)
            raise Exception(f"Size mismatch: {original_size}b != {archived_size}b")
        undo_info = {"action": "ARCHIVE", "original_path": target_path, "archive_path": archive_path, "original_size": original_size, "archived_size": archived_size}
        write_log("ARCHIVE_SUCCESS", undo_info)
        return undo_info
    except Exception as e:
        write_log("ARCHIVE_FAILED", {"path": target_path, "error": str(e)})
        raise Exception(f"Archive failed: {e}")

action_queue = []
is_processing_queue = False

def process_queue():
    global is_processing_queue
    if not action_queue:
        is_processing_queue = False
        write_log("QUEUE_END")
        return
    is_processing_queue = True
    next_action = action_queue.pop(0)
    action_name = next_action.get('action', 'unknown')
    write_log("QUEUE_EXECUTE", {"action": action_name, "remaining": len(action_queue)})
    try:
        if next_action.get("action") == "checkpoint":
            msg = next_action.get("message", "Press OK to continue...")
            messagebox.showinfo("CoreLink Checkpoint", msg)
            write_log("CHECKPOINT_ACK", {"message": msg[:100]})
            process_queue()
        else:
            run_script(next_action, "queue")
            import time
            time.sleep(0.5)
            process_queue()
    except Exception as e:
        error_msg = str(e)
        write_log("QUEUE_FAILED", {"action": action_name, "error": error_msg})
        
        # 3-BUTTON DIALOG
        root = tk.Tk()
        root.withdraw()
        dialog = tk.Toplevel(root)
        dialog.title("❌ Action Failed")
        dialog.geometry("500x250")
        dialog.resizable(False, False)
        
        tk.Label(dialog, text=f"Action: {action_name}", font=("Segoe UI", 12, "bold"), fg="#DC143C").pack(pady=10)
        tk.Label(dialog, text="Error:", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=20)
        error_text = tk.Text(dialog, height=6, wrap="word", font=("Consolas", 9))
        error_text.pack(fill="both", expand=True, padx=20, pady=5)
        error_text.insert("1.0", error_msg)
        error_text.config(state="disabled")
        
        def abort_queue():
            global action_queue, is_processing_queue
            action_queue.clear()
            is_processing_queue = False
            write_log("QUEUE_ABORTED_BY_USER")
            dialog.destroy()
            root.quit()
        
        def copy_error():
            clipboard_data = f"Action: {action_name}\\nError: {error_msg}\\nTime: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            pyperclip.copy(clipboard_data)
            write_log("ERROR_COPIED_TO_CLIPBOARD", {"action": action_name})
        
        btn_frame = tk.Frame(dialog, pady=10)
        btn_frame.pack()
        
        tk.Button(btn_frame, text="Abort Queue", width=15, bg="#DC143C", fg="white", command=abort_queue).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Copy Error", width=15, bg="#4169E1", fg="white", command=copy_error).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Continue", width=15, bg="#32CD32", fg="white", command=lambda: [dialog.destroy(), root.quit(), process_queue()]).pack(side="left", padx=5)
        
        dialog.lift()
        dialog.grab_set()
        root.mainloop()

def handle_google_update(data):
    write_log("GOOGLE_UPDATE_START")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        raise Exception("Missing Google libs\\nInstall: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    doc_id = data.get("doc_id")
    section_title = data.get("section_title", "Update")
    content = data.get("content", "")
    creds_path = os.path.join(BASE_DIR, "credentials.json")
    try:
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=["https://www.googleapis.com/auth/documents"])
        service = build("docs", "v1", credentials=creds)
        service.documents().batchUpdate(documentId=doc_id, body={"requests": [{"deleteContentRange": {"range": {"segmentId": "", "startIndex": 1}}}, {"insertText": {"location": {"index": 1}, "text": f"{section_title}\\n{content}\\n"}}]}).execute()
        write_log("GOOGLE_UPDATE_SUCCESS", {"doc_id": doc_id})
        messagebox.showinfo("CoreLink", "Google Docs update successful.")
    except Exception as e:
        write_log("GOOGLE_UPDATE_ERROR", {"error": str(e)})
        raise Exception(f"Google Docs failed: {e}")

def build_from_blueprint(blueprint_data=None):
    write_log("BLUEPRINT_START")
    try:
        if isinstance(blueprint_data, str) and os.path.exists(blueprint_data):
            with open(blueprint_data, 'r', encoding='utf-8') as f:
                bp = json.load(f)
        elif isinstance(blueprint_data, dict):
            bp = blueprint_data
        else:
            raise ValueError("Invalid blueprint - must be file path or dict")
        filename = bp.get("filename")
        content = bp.get("content")
        if not filename or content is None:
            raise ValueError("Blueprint missing 'filename' or 'content'")
        output_path = os.path.join(TEMP_DIR, filename)
        undo_info = archive_if_exists(output_path)
        if undo_info:
            messagebox.showinfo("Archive Created", f"EXISTING FILE FOUND AND ARCHIVED:\\n\\nOriginal: {undo_info['original_path']}\\nArchive: {undo_info['archive_path']}\\nSize: {undo_info['original_size']} bytes\\n\\nPress OK to write new file...")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        write_log("BLUEPRINT_SUCCESS", {"path": output_path})
        messagebox.showinfo("Build Complete", f"✅ FILE CREATED:\\n{output_path}\\n\\nArchive: {undo_info['archive_path'] if undo_info else 'N/A (new file)'}\")
        return output_path
    except Exception as e:
        write_log("BLUEPRINT_ERROR", {"error": str(e)})
        raise Exception(f"Blueprint build failed: {e}")

def handle_save_file(data):
    filename = data.get("filename")
    content = data.get("content")
    write_log("SAVE_FILE_START", {"filename": filename})
    try:
        if not filename or content is None:
            raise ValueError("save_file requires 'filename' and 'content'")
        if os.path.isabs(filename):
            filepath = filename
        else:
            filepath = os.path.join(TEMP_DIR, filename)
        undo_info = archive_if_exists(filepath)
        if undo_info:
            messagebox.showinfo("Archive Created", f"EXISTING FILE FOUND AND ARCHIVED:\\n\\nOriginal: {undo_info['original_path']}\\nArchive: {undo_info['archive_path']}\\nSize: {undo_info['original_size']} bytes\\n\\nPress OK to write new file...")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        write_log("SAVE_FILE_SUCCESS", {"path": filepath, "size": len(content)})
        messagebox.showinfo("Save Complete", f"✅ FILE SAVED:\\n{filepath}\\n\\nArchive: {undo_info['archive_path'] if undo_info else 'N/A (new file)'}\")
    except Exception as e:
        write_log("SAVE_FILE_ERROR", {"error": str(e), "filename": filename})
        raise Exception(f"Save file failed: {e}")

def run_script(data, source="manual"):
    try:
        if isinstance(data, str):
            data = json.loads(data)
    except Exception as e:
        raise Exception(f"Invalid JSON:\\n{e}")
    action = data.get("action", "").lower()
    write_log("RUN_SCRIPT_START", {"action": action, "source": source})
    if action == "run_queue":
        global action_queue
        action_queue = data.get("queue", [])
        messagebox.showinfo("CoreLink", f"Loaded queue of {len(action_queue)} actions. Starting...")
        process_queue()
        return
    if action == "checkpoint":
        msg = data.get("message", "Checkpoint reached")
        messagebox.showinfo("CoreLink Checkpoint", msg)
        return
    if action == "google_update":
        handle_google_update(data)
    elif action == "self_update":
        try:
            with open(FLAG_FILE, "w", encoding="utf-8") as f:
                f.write(json.dumps({"version": data.get("version", ""), "ts": datetime.datetime.now().isoformat()}))
        except Exception as e:
            raise Exception(f"Flag write failed: {e}")
        os._exit(0)
    elif action == "save_file":
        handle_save_file(data)
    elif action == "run_python":
        script_path = data.get("script_path")
        args = data.get("args", [])
        if script_path and script_path.endswith("notepad++.exe"):
            try:
                subprocess.run([script_path] + args, check=True, timeout=10)
                messagebox.showinfo("CoreLink", f"Opened: {os.path.basename(args[0]) if args else script_path}")
            except Exception as e:
                raise Exception(f"Failed to open: {e}")
        elif script_path:
            if not os.path.isabs(script_path):
                script_path = os.path.join(ROOT_DIR, script_path)
            if os.path.exists(script_path):
                try:
                    if source == "queue":
                        result = subprocess.run([sys.executable, script_path] + args, capture_output=True, text=True, timeout=120)
                        if result.returncode != 0:
                            raise Exception(f"Exit {result.returncode}\\nSTDERR: {result.stderr}")
                        messagebox.showinfo("CoreLink", f"Script completed: {os.path.basename(script_path)}")
                    else:
                        subprocess.Popen([sys.executable, script_path] + args, creationflags=0x08000000)
                        messagebox.showinfo("CoreLink", f"Running {os.path.basename(script_path)}")
                except Exception as e:
                    raise Exception(f"Script failed: {e}")
            else:
                raise Exception(f"Script not found: {script_path}")
    elif action == "run_inline":
        code = data.get("code")
        if code:
            try:
                temp_path = os.path.join(BASE_DIR, "temp_inline.py")
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(code)
                subprocess.Popen([sys.executable, temp_path], creationflags=0x08000000)
            except Exception as e:
                raise Exception(f"Inline failed: {e}")
    else:
        raise ValueError(f"Unknown action: {action}")

def build_ui():
    root = tk.Tk()
    root.title("CoreLink v3.18 - 3-Button Error Dialog")
    root.geometry("520x320")
    root.resizable(False, False)
    frame_left = tk.Frame(root, padx=20, pady=20)
    frame_left.pack(side="left", fill="both", expand=True)
    frame_right = tk.Frame(root, padx=10, pady=20)
    frame_right.pack(side="right", fill="y")
    tk.Button(frame_left, text="▶ Play from Clipboard", width=30, command=lambda: run_script(pyperclip.paste(), "clipboard")).pack(pady=5)
    tk.Button(frame_left, text="💾 Save Payload", width=30, command=lambda: run_script(pyperclip.paste(), "save")).pack(pady=5)
    tk.Button(frame_left, text="📂 Run Grab", width=30, command=lambda: subprocess.Popen([sys.executable, os.path.join(BASE_DIR, "grab.py")], creationflags=0x08000000)).pack(pady=5)
    tk.Button(frame_left, text="🏗️ Build Blueprint", width=30, command=lambda: build_from_blueprint(filedialog.askopenfilename(title="Select Blueprint JSON"))).pack(pady=5)
    tk.Button(frame_left, text="📜 Open Log", width=30, command=lambda: subprocess.Popen([NOTEPADPP, LOG_FILE])).pack(pady=5)
    tk.Button(frame_left, text="❌ Exit", width=30, command=root.destroy).pack(pady=5)
    global btn_record
    btn_record = tk.Button(frame_right, text="🛑 OFF", width=10, height=4, bg="#DC143C", fg="white", font=("Segoe UI", 14, "bold"), command=toggle_record)
    btn_btn = tk.Button(frame_right, text="📊 Status", width=10, height=2, command=lambda: messagebox.showinfo("CoreLink", f"Version: v3.18\nTEMP: {TEMP_DIR}\nArchive: {ARCHIVE_DIR}\nLogs: {LOG_FILE}"))
    btn_btn.pack(pady=5)
    btn_record.pack(expand=True, fill="both")
    root.mainloop()

recording = False
def toggle_record():
    global recording
    recording = not recording
    btn_record.config(text="🎙 ON" if recording else "🛑 OFF", bg="#32CD32" if recording else "#DC143C")

if __name__ == "__main__":
    write_log("=== CoreLink v3.18 MAIN START ===")
    build_ui()