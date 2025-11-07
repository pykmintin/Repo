#!/usr/bin/env python3
"""
Chat History GUI v3.0 - Final Version
Dual-mode: Normalize (strict dedupe) + Extract (JSON→Human)
"""
import os, json, tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from chat_processor import process_chat_file, check_strict_duplicate, extract_from_manifest

class GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("CORE Memory Reconstructor")
        self.root.geometry("1000x800")
        self.create_widgets()
    
    def create_widgets(self):
        # Mode selector
        mode_frame = tk.LabelFrame(self.root, text="Mode", padx=10, pady=10)
        mode_frame.pack(fill="x", padx=10, pady=5)
        self.mode = tk.StringVar(value="normalize")
        tk.Radiobutton(mode_frame, text="📥 Normalize (Add to CORE)", variable=self.mode, 
                      value="normalize", command=self.update_ui).pack(side=tk.LEFT)
        tk.Radiobutton(mode_frame, text="📤 Extract (View JSON)", variable=self.mode, 
                      value="extract", command=self.update_ui).pack(side=tk.LEFT)
        
        # File/input section
        input_frame = tk.LabelFrame(self.root, text="Input", padx=10, pady=10)
        input_frame.pack(fill="x", padx=10, pady=5)
        self.file_entry = tk.Entry(input_frame, width=60)
        self.file_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(input_frame, text="Browse", command=self.browse_file).pack(side=tk.LEFT)
        
        # Search section (extract mode)
        self.search_frame = tk.LabelFrame(self.root, text="Search/ID", padx=10, pady=10)
        self.search_entry = tk.Entry(self.search_frame, width=50)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(self.search_frame, text="Lookup", command=self.search_index).pack(side=tk.LEFT)
        
        # Text display
        self.text = scrolledtext.ScrolledText(self.root, height=30, width=120)
        self.text.pack(pady=10, padx=10)
        
        # Status & duplicate warning
        status_frame = tk.Frame(self.root)
        status_frame.pack()
        self.status = tk.Label(status_frame, text="Ready", fg="green")
        self.status.pack(side=tk.LEFT)
        self.dupe_warn = tk.Label(status_frame, text="", fg="orange")
        self.dupe_warn.pack(side=tk.LEFT, padx=20)
        
        # Buttons
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)
        self.process_btn = tk.Button(btn_frame, text="Process to CORE", 
                                   command=self.process, bg="#4CAF50", fg="white", width=25)
        self.process_btn.pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Extract & Display", 
                 command=self.extract, bg="#2196F3", fg="white", width=25).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Run Diagnostic", 
                 command=self.run_diagnostics, bg="#FF9800", fg="white", width=25).pack(side=tk.LEFT, padx=5)
        
        self.update_ui()
    
    def update_ui(self):
        if self.mode.get() == "normalize":
            self.search_frame.pack_forget()
            self.process_btn.config(text="Process to CORE")
        else:
            self.search_frame.pack(fill="x", padx=10, pady=5)
            self.process_btn.config(text="Load JSON")
    
    def browse_file(self):
        f = filedialog.askopenfilename(filetypes=[("Text/JSON", "*.txt *.json"), ("All", "*.*")])
        if f:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, f)
            self.load_file()
    
    def load_file(self):
        path = self.file_entry.get()
        if not os.path.exists(path):
            return
        
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.text.delete('1.0', tk.END)
        self.text.insert('1.0', content)
        
        if self.mode.get() == "normalize":
            self.check_duplicates(content)
    
    def check_duplicates(self, text):
        is_dup, dup_id, matches = check_strict_duplicate(text)
        if is_dup:
            self.dupe_warn.config(text=f"⚠️ DUPLICATE ({matches} matches): {dup_id}", fg="red")
        else:
            self.dupe_warn.config(text="✅ No duplicates", fg="green")
    
    def process(self):
        if self.mode.get() == "normalize":
            text = self.text.get('1.0', tk.END)
            result = process_chat_file(self.file_entry.get(), user_review_mode=True)
            
            if result.get("status") == "duplicate_skipped":
                messagebox.showwarning("Duplicate", f"Skipped: {result['duplicate_id']}")
                return
            
            if result.get("status") in ["keep", "flag"]:
                self.text.delete('1.0', tk.END)
                self.text.insert('1.0', result['formatted'])
                self.status.config(text=f"✅ {result['status'].upper()}: {result['entry']['id']}")
                
                if result['classification']['needs_intervention']:
                    messagebox.showinfo("Review Needed", "This conversation was flagged for your review.")
            else:
                messagebox.showinfo("Archived", "Low relevance - moved to discard log")
    
    def extract(self):
        conv_id = self.search_entry.get().strip()
        if not conv_id:
            return
        
        result = extract_from_manifest(conv_id)
        if result:
            self.text.delete('1.0', tk.END)
            self.text.insert('1.0', result)
            self.status.config(text=f"✅ Extracted: {conv_id}")
        else:
            messagebox.showerror("Not Found", "Conversation ID not in manifest")
    
    def search_index(self):
        query = self.search_entry.get().strip().lower()
        if not query or not os.path.exists("conversations_index.json"):
            return
        
        with open("conversations_index.json", 'r') as f:
            index = json.load(f)
        
        matches = [f"{cid} | {meta['title']}" for cid, meta in index.items() 
                  if query in cid or any(query in k for k in meta.get('keywords', []))]
        
        self.text.delete('1.0', tk.END)
        self.text.insert('1.0', "\n".join(matches[:30]))

if __name__ == "__main__":
    root = tk.Tk()
    GUI(root).root.mainloop()