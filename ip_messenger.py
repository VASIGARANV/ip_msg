import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import socket
import threading
import datetime
import json
import os
import base64
from PIL import Image, ImageGrab, ImageTk
import tempfile
from main_settings import MainSettingsDialog
import message_db

# ── IPMsg-style message log file ───────────────────────────────────────────────
_LOG_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ip_messenger.log")
_log_lock  = threading.Lock()

def _write_log(direction, sender, recipient, message, timestamp=None, has_attach=False):
    """
    Append one message entry to ip_messenger.log in IPMsg LogViewer style:

        2026/03/14 18:14 (Sat)  →  Admin (HOST/192.168.1.5)
        Hello world
        ----------------------------------------------------------------
    """
    try:
        dt = datetime.datetime.fromisoformat(timestamp) if timestamp else datetime.datetime.now()
    except Exception:
        dt = datetime.datetime.now()

    weekday  = dt.strftime("%a")
    date_str = dt.strftime(f"%Y/%m/%d %H:%M ({weekday})")
    arrow    = "→" if direction == "sent" else "←"
    # Attach marker
    attach_marker = "  📎" if has_attach else ""
    header = f"{date_str}  {arrow}  {sender}{attach_marker}"
    body   = message.strip() if message.strip() else "(empty)"
    sep    = "-" * 64

    entry = f"{header}\n{body}\n{sep}\n"

    with _log_lock:
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception:
            pass  # Never crash the app because of logging


class SnippingTool:
    def __init__(self, parent, callback):
        self.parent = parent
        self.callback = callback
        self.start_x = None
        self.start_y = None
        self.rect = None
        
        self.top = tk.Toplevel(parent)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-alpha", 0.3)
        self.top.attributes("-topmost", True)
        self.top.configure(bg="black", cursor="cross")
        
        self.canvas = tk.Canvas(self.top, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        # Escape to cancel
        self.top.bind("<Escape>", lambda e: self.top.destroy())

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y

    def on_drag(self, event):
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, event.x, event.y, 
            outline="red", width=2, fill="white", stipple="gray12"
        )

    def on_release(self, event):
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        
        # Ensure we have a valid area
        if x2 - x1 > 5 and y2 - y1 > 5:
            # Hide window before capture to avoid capturing the overlay
            self.top.withdraw() 
            # Give the window manager a moment to clear the window
            self.parent.after(200, lambda: self.capture(x1, y1, x2, y2))
        else:
            self.top.destroy()
            
    def capture(self, x1, y1, x2, y2):
        try:
            # Grab the screen area
            image = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            self.top.destroy()
            self.callback(image)
        except Exception as e:
            self.top.destroy()
            messagebox.showerror("Capture Error", str(e))

class AttachmentManager:
    def __init__(self, parent, attached_files, callback):
        self.parent = parent
        self.attached_files = list(attached_files)  # Copy of list
        self.callback = callback
        
        self.window = tk.Toplevel(parent)
        self.window.title("Attached Files")
        self.window.geometry("550x300")
        
        # Set icon
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "messenger.png")
            if os.path.exists(icon_path):
                img = tk.PhotoImage(file=icon_path)
                self.window.iconphoto(True, img)
        except:
            pass

        # Main frame
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Treeview
        columns = ("filename", "size", "location")
        self.tree = ttk.Treeview(main_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("filename", text="filename")
        self.tree.heading("size", text="size")
        self.tree.heading("location", text="location")
        
        self.tree.column("filename", width=150)
        self.tree.column("size", width=80)
        self.tree.column("location", width=250)
        
        self.tree.pack(fill=tk.BOTH, expand=True)
        
        # Bind double click to open file
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-3>", self.show_context_menu)
        
        # Context menu
        self.context_menu = tk.Menu(self.window, tearoff=0)
        self.context_menu.add_command(label="Open File", command=self.open_current_selection)
        self.context_menu.add_command(label="Open Folder", command=self.open_current_folder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Delete", command=self.delete_file)

        # Buttons
        btn_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        btn_frame.pack(fill=tk.X)
        
        # Left side buttons
        ttk.Button(btn_frame, text="File/Folder Add", command=self.add_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Open", command=self.open_current_selection).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Folder", command=self.open_current_folder).pack(side=tk.LEFT, padx=5)
        
        # Right side buttons
        ttk.Button(btn_frame, text="Close", command=self.close_window).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Delete", command=self.delete_file).pack(side=tk.RIGHT, padx=5)
        
        self.populate_tree()

    def populate_tree(self):
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for path in self.attached_files:
            name = os.path.basename(path)
            directory = os.path.dirname(path)
            if os.path.isdir(path):
                size = "(DIR)"
            else:
                try:
                    size_bytes = os.path.getsize(path)
                    if size_bytes < 1024:
                        size = f"{size_bytes} B"
                    elif size_bytes < 1024 * 1024:
                        size = f"{size_bytes // 1024} KB"
                    else:
                        size = f"{size_bytes // (1024 * 1024)} MB"
                except:
                    size = "Unknown"
            
            self.tree.insert("", tk.END, values=(name, size, directory), tags=(path,))

    def on_double_click(self, event):
        self.open_current_selection()

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def open_current_selection(self):
        selection = self.tree.selection()
        if selection:
            path = self.tree.item(selection[0], "tags")[0]
            if os.path.exists(path):
                try:
                     os.startfile(path)
                except Exception as e:
                    messagebox.showerror("Error", f"Could not open file: {str(e)}")
            else:
                messagebox.showwarning("Not Found", "File not found.")

    def open_current_folder(self):
        selection = self.tree.selection()
        if selection:
            path = self.tree.item(selection[0], "tags")[0]
            if os.path.exists(path):
                folder_path = path if os.path.isdir(path) else os.path.dirname(path)
                try:
                    os.startfile(folder_path)
                except Exception as e:
                    messagebox.showerror("Error", f"Could not open folder: {str(e)}")
            else:
                 messagebox.showwarning("Not Found", "Path not found.")

    def add_file(self):
        file_path = filedialog.askopenfilename(title="Select File")
        if file_path and file_path not in self.attached_files:
            self.attached_files.append(file_path)
            self.populate_tree()
            self.callback(self.attached_files)

    def delete_file(self):
        selection = self.tree.selection()
        if selection:
            for item in selection:
                # Get the path from tags (we stored it there)
                 # tag is a tuple
                path = self.tree.item(item, "tags")[0]
                if path in self.attached_files:
                    self.attached_files.remove(path)
            self.populate_tree()
            self.callback(self.attached_files)

    def close_window(self):
        self.window.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  IPMsg-style Log Viewer  –  reads from message_db (SQLite)
# ══════════════════════════════════════════════════════════════════════════════
class LogViewerWindow:
    """IPMsg LogViewer window that reads messages from the SQLite database."""

    # ── header background colour matching the screenshot grey ────────────────
    HDR_BG  = "#d4d0c8"
    HDR_FG  = "#000000"
    BODY_BG = "#ffffff"
    STAR_ON = "★"
    STAR_OFF = "☆"

    def __init__(self, messenger):
        self.messenger = messenger          # IPMessenger instance
        self.root      = messenger.root

        self.win = tk.Toplevel(self.root)
        self.win.title("IPMsg LogViewer")
        self.win.geometry("640x680")
        self.win.minsize(520, 400)

        # Icon
        if messenger.icon_image:
            try:
                self.win.iconphoto(True, messenger.icon_image)
            except Exception:
                pass

        self._build_menu()
        self._build_toolbar()
        self._build_tab_bar()
        self._build_message_area()
        self._build_status_bar()

        self.load_messages()

    # ── Menu bar ─────────────────────────────────────────────────────────────
    def _build_menu(self):
        mb = tk.Menu(self.win)
        self.win.config(menu=mb)

        file_m = tk.Menu(mb, tearoff=0)
        file_m.add_command(label="Refresh",       command=self.load_messages)
        file_m.add_separator()
        file_m.add_command(label="Clear All Logs",
                           command=self._clear_all)
        file_m.add_separator()
        file_m.add_command(label="Close",         command=self.win.destroy)
        mb.add_cascade(label="File",     menu=file_m)

        set_m = tk.Menu(mb, tearoff=0)
        set_m.add_command(label="Search Messages…", command=self._open_search)
        mb.add_cascade(label="Settings", menu=set_m)

        win_m = tk.Menu(mb, tearoff=0)
        win_m.add_command(label="Refresh", command=self.load_messages)
        mb.add_cascade(label="Window", menu=win_m)

    # ── Toolbar (filter row) ──────────────────────────────────────────────────
    def _build_toolbar(self):
        bar = tk.Frame(self.win, bd=1, relief=tk.RAISED)
        bar.pack(fill=tk.X)

        # User filter
        tk.Label(bar, text="All Users", width=10).pack(side=tk.LEFT, padx=4)

        self.user_var = tk.StringVar(value="All Users")
        self.user_cb  = ttk.Combobox(bar, textvariable=self.user_var,
                                     width=14, state="readonly")
        self.user_cb.pack(side=tk.LEFT, padx=2, pady=3)
        self.user_cb.bind("<<ComboboxSelected>>", lambda e: self.load_messages())

        # Period filter
        self.period_var = tk.StringVar(value="Entire period")
        period_cb = ttk.Combobox(bar, textvariable=self.period_var, width=14,
                                 values=["Entire period", "Today",
                                         "Last 7 days", "Last 30 days"],
                                 state="readonly")
        period_cb.pack(side=tk.LEFT, padx=2)
        period_cb.bind("<<ComboboxSelected>>", lambda e: self.load_messages())

        # Icon-style filter buttons (★  ✉  📎 …)
        for icon, tip, cmd in [
            (self.STAR_ON, "Starred only",    self._filter_starred),
            ("✉",          "All messages",    self._show_all_messages),
            ("🔍",         "Search",          self._open_search),
        ]:
            b = tk.Button(bar, text=icon, relief=tk.FLAT, padx=6,
                          command=cmd)
            b.pack(side=tk.LEFT, padx=1)

        # Refresh button
        tk.Button(bar, text="⟳", relief=tk.FLAT,
                  command=self.load_messages).pack(side=tk.RIGHT, padx=4)

    # ── Tab bar ("All" and "Starred" tabs) ───────────────────────────────────
    def _build_tab_bar(self):
        tab_frame = tk.Frame(self.win, bg="#c0c0c0", height=24)
        tab_frame.pack(fill=tk.X)

        self.current_view = "all"  # default active view

        self.all_tab = tk.Label(tab_frame, text="  All  ",
                                bg="white", relief=tk.RIDGE,
                                padx=6, pady=2, cursor="hand2")
        self.all_tab.pack(side=tk.LEFT, padx=(4, 0), pady=2)
        self.all_tab.bind("<Button-1>", lambda e: self.switch_view("all"))

        self.starred_tab = tk.Label(tab_frame, text="  Starred  ",
                                    bg="#c0c0c0", relief=tk.FLAT,
                                    padx=6, pady=2, cursor="hand2")
        self.starred_tab.pack(side=tk.LEFT, padx=(2, 0), pady=2)
        self.starred_tab.bind("<Button-1>", lambda e: self.switch_view("starred"))

        tk.Label(tab_frame, text=" + ", bg="#c0c0c0",
                 padx=4).pack(side=tk.LEFT)

    # ── Scrollable message canvas ─────────────────────────────────────────────
    def _build_message_area(self):
        container = tk.Frame(self.win)
        container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(container, bg=self.BODY_BG,
                                highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL,
                             command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # inner frame that holds all message blocks
        self.inner = tk.Frame(self.canvas, bg=self.BODY_BG)
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse-wheel scroll
        self.canvas.bind_all("<MouseWheel>",
            lambda e: self.canvas.yview_scroll(
                int(-1 * (e.delta / 120)), "units"))

    def _on_inner_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_status_bar(self):
        self.status_var = tk.StringVar(value="Dbl-click: Reply (with Shift, no quote)")
        sb = tk.Label(self.win, textvariable=self.status_var,
                      bd=1, relief=tk.SUNKEN, anchor=tk.W,
                      font=("Segoe UI", 8))
        sb.pack(fill=tk.X, side=tk.BOTTOM)

    # ── Load / render messages ────────────────────────────────────────────────
    def load_messages(self, rows=None):
        """Fetch from DB and re-render the message list."""
        # Fetch
        if rows is None:
            period = self.period_var.get()
            user   = self.user_var.get()

            today = datetime.date.today()
            if period == "Today":
                start = today.strftime("%Y-%m-%d")
                end   = today.strftime("%Y-%m-%d")
                rows  = message_db.get_messages_by_date_range(start, end)
            elif period == "Last 7 days":
                start = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
                end   = today.strftime("%Y-%m-%d")
                rows  = message_db.get_messages_by_date_range(start, end)
            elif period == "Last 30 days":
                start = (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
                end   = today.strftime("%Y-%m-%d")
                rows  = message_db.get_messages_by_date_range(start, end)
            else:
                rows = message_db.get_all_messages(limit=1000)

            # User filter
            if user and user != "All Users":
                rows = [r for r in rows
                        if r["sender"] == user or r["recipient"] == user]

            # Starred filter
            if getattr(self, "current_view", "all") == "starred":
                rows = [r for r in rows if r.get("starred")]

        # Rebuild user combobox values (most recently messaged users first)
        recent_names = message_db.get_recent_users()
        self.user_cb["values"] = ["All Users"] + recent_names

        # Clear inner frame
        for widget in self.inner.winfo_children():
            widget.destroy()

        if not rows:
            tk.Label(self.inner, text="No messages found.",
                     bg=self.BODY_BG, fg="gray",
                     font=("Segoe UI", 10)).pack(pady=20)
            self.status_var.set(f"0 messages")
            return

        for row in rows:
            self._render_row(row)

        self.status_var.set(
            f"{len(rows)} message{'s' if len(rows) != 1 else ''}  |  "
            "Dbl-click: Reply (with Shift, no quote)")

        # Reset scroll region and scroll to top so content is always visible
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0.0)

    def _render_row(self, row):
        """Render one message block exactly like the IPMsg LogViewer."""
        # ── Header strip ────────────────────────────────────────────────────
        hdr = tk.Frame(self.inner, bg=self.HDR_BG, bd=0)
        hdr.pack(fill=tk.X, pady=(2, 0))

        # Format timestamp
        try:
            dt = datetime.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.datetime.now()
        weekday  = dt.strftime("%a")
        date_str = dt.strftime(f"%Y/%m/%d %H:%M ({weekday})")

        # Direction arrow
        arrow = "→" if row["direction"] == "sent" else "←"
        name  = row["sender"]

        # Date label (left)
        tk.Label(hdr, text=date_str, bg=self.HDR_BG,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(8, 4), pady=3)

        # Arrow + name badge
        name_lbl = tk.Label(hdr,
                            text=f" {arrow} {name} ",
                            bg=self.HDR_BG,
                            font=("Segoe UI", 9, "bold"),
                            relief=tk.RAISED, padx=4)
        name_lbl.pack(side=tk.LEFT, pady=3)

        # Attachment icon
        if row.get("has_attach"):
            tk.Label(hdr, text="📎", bg=self.HDR_BG).pack(side=tk.LEFT, padx=2)

        # Star button (right-aligned)
        star_state = [bool(row.get("starred"))]
        star_btn   = [None]

        def toggle(msg_id=row["id"], state=star_state, btn=star_btn):
            new = message_db.toggle_star(msg_id)
            state[0] = new
            btn[0].config(text=self.STAR_ON if new else self.STAR_OFF,
                          fg="#f5a623" if new else "gray")
            # Refresh if we are in the starred view to immediately update list
            if getattr(self, "current_view", "all") == "starred":
                self._filter_starred()

        sb = tk.Button(hdr,
                       text=self.STAR_ON if row.get("starred") else self.STAR_OFF,
                       fg="#f5a623" if row.get("starred") else "gray",
                       bg=self.HDR_BG, relief=tk.FLAT, bd=0,
                       font=("Segoe UI", 11),
                       command=toggle)
        sb.pack(side=tk.RIGHT, padx=6)
        star_btn[0] = sb

        # ⋯ context menu button
        ctx_btn = tk.Button(hdr, text="⋯", bg=self.HDR_BG,
                            relief=tk.FLAT, bd=0,
                            font=("Segoe UI", 10))
        ctx_btn.pack(side=tk.RIGHT, padx=2)
        ctx_btn.bind("<Button-1>",
                     lambda e, r=row: self._show_ctx_menu(e, r))

        # ── Message body ─────────────────────────────────────────────────────
        body = tk.Label(self.inner,
                        text=row["message"],
                        bg=self.BODY_BG, fg="#111111",
                        font=("Segoe UI", 10),
                        justify=tk.LEFT, anchor="w",
                        wraplength=580, padx=16, pady=4)
        body.pack(fill=tk.X)

        # Divider line
        tk.Frame(self.inner, bg="#cccccc", height=1).pack(fill=tk.X)

        # Double-click on body → reply
        for widget in (hdr, name_lbl, body):
            widget.bind("<Double-Button-1>",
                        lambda e, r=row: self._reply(e, r, quote=True))
            widget.bind("<Shift-Double-Button-1>",
                        lambda e, r=row: self._reply(e, r, quote=False))

    # ── Context menu ──────────────────────────────────────────────────────────
    def _show_ctx_menu(self, event, row):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label="Reply",
                      command=lambda: self._reply(None, row, quote=True))
        m.add_command(label="Reply (no quote)",
                      command=lambda: self._reply(None, row, quote=False))
        m.add_separator()
        star_lbl = "Unstar" if row.get("starred") else "Star"
        m.add_command(label=star_lbl,
                      command=lambda: (message_db.toggle_star(row["id"]),
                                       self.load_messages()))
        m.add_separator()
        m.add_command(label="Delete this message",
                      command=lambda: self._delete_row(row["id"]))
        m.post(event.x_root, event.y_root)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _reply(self, event, row, quote=True):
        """Focus main window and pre-fill the message box."""
        self.root.lift()
        self.root.focus_force()
        msg_widget = self.messenger.message_text
        msg_widget.focus_set()
        if quote:
            sender = row["sender"]
            quoted = "\n".join(f"> {l}" for l in row["message"].splitlines())
            prefix = f"--- {sender} wrote ---\n{quoted}\n\n"
            msg_widget.insert(self.messenger.message_insert_point, prefix)

    def _show_all_messages(self):
        if hasattr(self, "all_tab") and hasattr(self, "starred_tab"):
            self.all_tab.config(bg="white", relief=tk.RIDGE)
            self.starred_tab.config(bg="#c0c0c0", relief=tk.FLAT)
            self.current_view = "all"
        self.load_messages()

    def _filter_starred(self):
        if hasattr(self, "all_tab") and hasattr(self, "starred_tab"):
            self.all_tab.config(bg="#c0c0c0", relief=tk.FLAT)
            self.starred_tab.config(bg="white", relief=tk.RIDGE)
            self.current_view = "starred"
        rows = message_db.get_starred_messages()
        self.load_messages(rows=rows)

    def switch_view(self, view_name):
        """Switch active tab between 'all' and 'starred'"""
        self.current_view = view_name
        if view_name == "all":
            self.all_tab.config(bg="white", relief=tk.RIDGE)
            self.starred_tab.config(bg="#c0c0c0", relief=tk.FLAT)
            self.load_messages()
        elif view_name == "starred":
            self.all_tab.config(bg="#c0c0c0", relief=tk.FLAT)
            self.starred_tab.config(bg="white", relief=tk.RIDGE)
            self._filter_starred()

    def _open_search(self):
        """Simple search dialog."""
        sw = tk.Toplevel(self.win)
        sw.title("Search Messages")
        sw.geometry("340x110")
        sw.resizable(False, False)
        sw.grab_set()

        tk.Label(sw, text="Keyword:", font=("Segoe UI", 9)).pack(
            anchor=tk.W, padx=12, pady=(12, 2))
        entry = ttk.Entry(sw, width=38)
        entry.pack(padx=12)
        entry.focus()

        def do_search():
            kw = entry.get().strip()
            if kw:
                rows = message_db.search_messages(kw)
                self.load_messages(rows=rows)
                self.status_var.set(f"Search: '{kw}'  →  {len(rows)} result(s)")
            sw.destroy()

        entry.bind("<Return>", lambda e: do_search())
        ttk.Button(sw, text="Search", command=do_search).pack(pady=8)

    def _delete_row(self, msg_id):
        if messagebox.askyesno("Delete", "Delete this message from the log?",
                               parent=self.win):
            message_db.delete_message(msg_id)
            self.load_messages()

    def _clear_all(self):
        if messagebox.askyesno("Clear All",
                               "Delete ALL log messages? This cannot be undone.",
                               parent=self.win):
            message_db.delete_all_messages()
            self.load_messages()


class IPMessenger:

    def __init__(self, root):
        self.root = root
        self.root.title("Send Message")
        self.root.geometry("600x500")
        self.root.resizable(True, True)  # Allow resizing and maximizing
        
        # Set window icon
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "messenger.png")
            if os.path.exists(icon_path):
                # Try iconbitmap first (for .ico files)
                try:
                    self.root.iconbitmap(icon_path)
                except:
                    # If iconbitmap fails, try using PhotoImage for PNG
                    try:
                        icon_image = tk.PhotoImage(file=icon_path)
                        self.root.iconphoto(True, icon_image)
                    except:
                        pass
        except Exception:
            pass
        
        # Network settings
        self.server_socket = None
        self.broadcast_socket = None
        self.server_thread = None
        self.broadcast_thread = None
        self.discovery_thread = None
        self.is_server_running = False
        self.port = 5000
        self.broadcast_port = 5001
        self.host = self.get_local_ip()
        self.username = os.getenv('USERNAME', 'Admin')
        self.group = "General"  # Current user's group
        self.hostname = socket.gethostname()
        
        # User discovery
        self.discovered_users = {}  # {ip: {'username': str, 'hostname': str, 'group': str, 'last_seen': datetime}}
        
        # Message sealing (encryption)
        self.seal_enabled = False
        self.attached_files = [] # List of file paths
        self.message_priority = "Normal"
        self.groups = {}  # {group_name: [ip, ...]}
        
        # Display and Sort Settings
        self.show_columns = {
            "Group": tk.BooleanVar(value=True),
            "Host": tk.BooleanVar(value=True),
            "IP": tk.BooleanVar(value=True),
            "Logon": tk.BooleanVar(value=False),
            "DispPriority": tk.BooleanVar(value=False)
        }
        self.show_gridlines = tk.BooleanVar(value=True)
        self.sort_group = tk.BooleanVar(value=True)
        self.sort_group_reverse = tk.BooleanVar(value=False)
        self.sort_secondary = tk.StringVar(value="User") # User, IP, Host
        self.sort_secondary_reverse = tk.BooleanVar(value=False)
        self.sort_ignore_case = tk.BooleanVar(value=True)

        self.seal_var = tk.BooleanVar(value=True)
        self.active_toasts = []
        
        # Store icon image reference to prevent garbage collection
        self.icon_image = None
        self.toast_icon_image = None
        self.toast_icon_small = None
        self.chat_images = [] # Store references to images in chat
        self.receipt_sent_map = {}
        self.active_toasts = []
        self.status_var = tk.StringVar(value="Ready")
        self.user_tree = ttk.Treeview() # Initialize with empty Treeview
        self.member_count_label = tk.Label() # Initialize with empty Label
        self.attachment_path_var = tk.StringVar()
        self.offered_files = {} # {filename: abs_path}
        self.offered_files_lock = threading.Lock()
        
        # Load UI Icons
        self.ui_icons = {}
        self._load_ui_icons()

        # UI Setup
        self.setup_ui()

        # Initialise message database
        message_db.init_db()

        # Start services
        self.start_server()
        self.start_broadcast()
        self.start_discovery()
        
    def _load_ui_icons(self):
        """Load UI specific icons like capture tool"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Restore Main Window Icon
        self.set_window_icon()
        
        # Load Toast Icons
        self._load_toast_icon()
        
        # Load Snipping Tool Icon
        snip_path = os.path.join(base_dir, "capture_icon.png")
        if os.path.exists(snip_path):
            try:
                pil_img = Image.open(snip_path).convert("RGBA")
                self.ui_icons["snip"] = ImageTk.PhotoImage(pil_img.resize((24, 24), Image.Resampling.LANCZOS))
            except: pass

    def _load_toast_icon(self):
        """Load icon images for toast notifications (48x48 body + 16x16 header)."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for name in ("messenger.ico", "messenger_icon.png", "messenger.png"):
            p = os.path.join(base_dir, name)
            if os.path.exists(p):
                try:
                    pil_img = Image.open(p).convert("RGBA")
                    self.toast_icon_image = ImageTk.PhotoImage(
                        pil_img.resize((48, 48), Image.LANCZOS))
                    self.toast_icon_small = ImageTk.PhotoImage(
                        pil_img.resize((16, 16), Image.LANCZOS))
                    return
                except Exception:
                    pass

    def set_window_icon(self):
        """Set title-bar and taskbar icon reliably on Windows"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ico_path = os.path.join(base_dir, "messenger.ico")
        png_path = os.path.join(base_dir, "messenger.png")

        # Always regenerate .ico from .png for best quality & fresh cache
        if os.path.exists(png_path):
            try:
                pil_img = Image.open(png_path).convert("RGBA")
                pil_img.save(
                    ico_path, format="ICO",
                    sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
                )
            except Exception:
                pass

        # Apply icon: iconbitmap positional = applies to THIS window
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)   # sets title-bar icon on root
                # Keep a PIL PhotoImage ref for child dialogs
                if os.path.exists(png_path):
                    self.icon_image = ImageTk.PhotoImage(Image.open(png_path))
                return
            except Exception:
                pass

        # Fallback: iconphoto with PIL
        if os.path.exists(png_path):
            try:
                self.icon_image = ImageTk.PhotoImage(Image.open(png_path))
                self.root.iconphoto(True, self.icon_image)
            except Exception:
                pass
    
    def get_local_ip(self):
        """Get the local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                # Find first non-loopback IP
                hostname = socket.gethostname()
                for ip in socket.gethostbyname_ex(hostname)[2]:
                    if not ip.startswith("127."):
                        return ip
                return "127.0.0.1"
            except Exception:
                return "127.0.0.1"

    def get_all_local_ips(self):
        """Get all active local IPv4 interface addresses"""
        ips = set()
        try:
            hostname = socket.gethostname()
            info = socket.gethostbyname_ex(hostname)
            for ip in info[2]:
                if not ip.startswith("127."):
                    ips.add(ip)
        except Exception:
            pass

        # Socket connect tricks to resolve active routes
        for target in [("8.8.8.8", 80), ("192.168.1.254", 80), ("10.0.0.254", 80)]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.1)
                s.connect(target)
                ip = s.getsockname()[0]
                s.close()
                if not ip.startswith("127."):
                    ips.add(ip)
            except Exception:
                pass

        if not ips:
            primary = self.get_local_ip()
            if primary:
                ips.add(primary)
        return list(ips)
    
    def setup_ui(self):
        """Setup the user interface"""
        # Main container
        main_container = ttk.Frame(self.root, padding="8")
        main_container.pack(fill=tk.BOTH, expand=True)
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(1, weight=1)  # Message display area gets the space
        
        # User list frame - reduced spacing
        user_frame = ttk.LabelFrame(main_container, text="Recipients", padding="5")
        user_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N), pady=(0, 5))
        user_frame.columnconfigure(0, weight=1)
        user_frame.rowconfigure(0, weight=1)
        
        # User list with scrollbar
        list_container = ttk.Frame(user_frame)
        list_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        list_container.columnconfigure(0, weight=1)
        list_container.rowconfigure(0, weight=1)
        
        # Treeview for user list
        columns = ("User", "Group", "Host", "IP")
        self.user_tree = ttk.Treeview(list_container, columns=columns, show="headings", height=6, selectmode="extended")
        self.user_tree.heading("User", text="User")
        self.user_tree.heading("Group", text="Group")
        self.user_tree.heading("Host", text="Host")
        self.user_tree.heading("IP", text="IP Address")
        self.user_tree.column("User", width=150)
        self.user_tree.column("Group", width=100)
        self.user_tree.column("Host", width=180)
        self.user_tree.column("IP", width=130)
        
        # Configure selection colors for consistent blue highlight
        style = ttk.Style()
        style.map("Treeview", 
                  background=[("selected", "#0078d4")],  # Blue selection color
                  foreground=[("selected", "white")])
        
        scrollbar_y = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=self.user_tree.yview)
        self.user_tree.configure(yscrollcommand=scrollbar_y.set)
        
        self.user_tree.grid(row=0, column=0, sticky="wens")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        
        # Member count and refresh panel
        member_panel = ttk.Frame(user_frame)
        member_panel.grid(row=0, column=1, padx=(10, 0), sticky=tk.N)
        
        ttk.Label(member_panel, text="Member", font=("Arial", 9)).pack()
        self.member_count_label = tk.Label(member_panel, text="0", font=("Arial", 10, "bold"))
        self.member_count_label.pack()
        
        refresh_btn = ttk.Button(member_panel, text="⟳", command=self.refresh_user_list, width=3)
        refresh_btn.pack(pady=(10, 0))
        
        # Dropdown arrow button with menu functionality
        dropdown_btn = ttk.Menubutton(member_panel, text="▼", width=3)
        dropdown_btn.pack(pady=(5, 0))
        
        # Create the menu and attach to dropdown button
        menu = tk.Menu(dropdown_btn, tearoff=0)
        dropdown_btn.config(menu=menu)
        
        # User History submenu
        history_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="User History(1)", menu=history_menu)
        history_menu.add_command(label="Recent Users", command=self.show_user_history)
        
        menu.add_command(label="Search User (Ctrl-F)", command=self.search_user)
        menu.add_command(label="Send to Admin", command=self.send_to_admin)
        
        # Group Select submenu
        group_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Group Select", menu=group_menu)
        group_menu.add_command(label="Create Group", command=self.create_group)
        group_menu.add_command(label="Select Group", command=self.select_group)
        
        # Priority Settings submenu
        priority_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Priority Settings", menu=priority_menu)
        priority_menu.add_command(label="High Priority", command=lambda: self.set_priority("High"))
        priority_menu.add_command(label="Normal Priority", command=lambda: self.set_priority("Normal"))
        priority_menu.add_command(label="Low Priority", command=lambda: self.set_priority("Low"))
        
        menu.add_separator()
        
        menu.add_command(label="File/Folder Attach", command=self.attach_file_folder)
        
        # Image & Capture submenu
        image_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Image & Capture", menu=image_menu)
        image_menu.add_command(label="Display Capture (Ctrl-K)", command=self.capture_screen)
        image_menu.add_command(label="Paste image", command=self.paste_image)
        image_menu.add_command(label="Insert Image File...", command=self.attach_image)
        
        menu.add_separator()
        
        # Size/Font/Pos Setting submenu
        size_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Size/Font/Pos Setting", menu=size_menu)
        size_menu.add_command(label="Save size/header as default", command=self.save_size_header_default)
        size_menu.add_command(label="Restore default size (temporary)", command=self.restore_default_size)
        size_menu.add_separator()
        size_menu.add_command(label="List Font...", command=self.list_font_settings)
        size_menu.add_command(label="Edit Font...", command=self.edit_font_settings)
        size_menu.add_command(label="Restore default Font", command=self.restore_default_font)
        size_menu.add_separator()
        size_menu.add_command(label="Fix Position", command=self.fix_position_settings)
        
        menu.add_command(label="Disp Setting...", command=self.display_settings)
        menu.add_command(label="MainSettings...", command=self.main_settings)
        
        menu.add_separator()
        
        menu.add_command(label="Open LogViewer", command=self.open_log_viewer)
        
        # Message section - editable text area where user can type
        msg_display_frame = ttk.LabelFrame(main_container, text="Message", padding="5")
        msg_display_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 5))
        msg_display_frame.columnconfigure(0, weight=1)
        msg_display_frame.rowconfigure(0, weight=1)
        
        # Attachment display area (hidden until needed)
        self.attachment_frame = ttk.Frame(msg_display_frame)
        # Initially hidden - will be shown by update_attachment_display() if files are added
        # self.attachment_frame.pack(fill=tk.X, padx=2, pady=(0, 2))
        
        self.attachment_path_var = tk.StringVar()
        self.attachment_entry = ttk.Entry(self.attachment_frame, textvariable=self.attachment_path_var, state='readonly', cursor="hand2")
        self.attachment_entry.pack(fill=tk.X)
        
        # Bind clicking the attachment entry to open Manager
        self.attachment_entry.bind("<Button-1>", lambda e: self.open_attachment_manager())
        
        # Message text area - editable for typing
        self.message_text = scrolledtext.ScrolledText(
            msg_display_frame,
            wrap=tk.WORD,
            width=70,
            height=20,
            font=("Arial", 10),
            exportselection=False
        )
        self.message_text.pack(fill=tk.BOTH, expand=True)
        self.message_text.focus_set()
        
        # Attach right-click context menu
        self._setup_message_context_menu()
        
        # Store the insertion point for new messages
        self.message_insert_point = "1.0"
        
        # Bottom controls - reduced spacing
        controls_frame = ttk.Frame(main_container)
        controls_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 0))
        controls_frame.columnconfigure(0, weight=1)
        
        # Snipping Tool / Capture Button (Primary left)
        snip_img = self.ui_icons.get("snip")
        if snip_img:
            snip_btn = ttk.Button(controls_frame, image=snip_img, command=self.capture_screen, width=3)
        else:
            snip_btn = ttk.Button(controls_frame, text="📷", command=self.capture_screen, width=3)
        snip_btn.grid(row=0, column=0, padx=(0, 5), sticky=tk.W)
        
        # Document/File icon button (Secondary)
        doc_btn = ttk.Button(controls_frame, text="📄", command=self.open_attachment_manager, width=3)
        doc_btn.grid(row=0, column=1, padx=(0, 5), sticky=tk.W)
        
        # Setup Drag & Drop for main window
        try:
            import windnd
            windnd.hook_dropfiles(self.root, lambda files: self.handle_dropped_files(files))
        except: pass

        # Send button (right side)
        send_btn = ttk.Button(controls_frame, text="Send", command=self.send_message, width=12)
        send_btn.grid(row=0, column=1, padx=(0, 5), sticky=tk.E)
        
        # Seal checkbox (to the right of Send button)
        self.seal_var = tk.BooleanVar(value=True)  # Default checked
        seal_check = ttk.Checkbutton(controls_frame, text="seal", variable=self.seal_var)
        seal_check.grid(row=0, column=2, sticky=tk.E)
        
        # Update user list periodically
        self.update_user_list()
        self.update_member_count()
    
    # ── Message-area right-click context menu ────────────────────────────────
    def _setup_message_context_menu(self):
        """Create the right-click context menu for the message text area."""
        self._msg_ctx_menu = tk.Menu(self.root, tearoff=0)
        self.message_text.bind("<Button-3>", self._show_message_context_menu)

    def _show_message_context_menu(self, event):
        """Show the context menu. Only Undo, Save Selected Image, and
        Edit Selected Image are permanently disabled."""
        menu = self._msg_ctx_menu
        menu.delete(0, tk.END)

        widget = self.message_text

        # Save selection range BEFORE the menu steals focus
        try:
            sel_start = widget.index(tk.SEL_FIRST)
            sel_end = widget.index(tk.SEL_LAST)
        except tk.TclError:
            sel_start = None
            sel_end = None

        # ── Undo: always disabled ────────────────────────────────────────────
        menu.add_command(
            label="Undo",
            state=tk.DISABLED,
            foreground="#888888"
        )

        menu.add_separator()

        # ── Cut ──────────────────────────────────────────────────────────────
        def _do_cut():
            if sel_start and sel_end:
                selected_text = widget.get(sel_start, sel_end)
                self.root.clipboard_clear()
                self.root.clipboard_append(selected_text)
                widget.delete(sel_start, sel_end)
        menu.add_command(label="Cut", command=_do_cut)

        # ── Copy ─────────────────────────────────────────────────────────────
        def _do_copy():
            if sel_start and sel_end:
                selected_text = widget.get(sel_start, sel_end)
                self.root.clipboard_clear()
                self.root.clipboard_append(selected_text)
        menu.add_command(label="Copy", command=_do_copy)

        # ── Paste ────────────────────────────────────────────────────────────
        def _do_paste():
            try:
                clip = self.root.clipboard_get()
            except tk.TclError:
                return
            # If there was a selection, replace it
            if sel_start and sel_end:
                widget.delete(sel_start, sel_end)
                widget.insert(sel_start, clip)
            else:
                widget.insert(tk.INSERT, clip)
        menu.add_command(label="Paste", command=_do_paste)

        # ── Delete ───────────────────────────────────────────────────────────
        def _do_delete():
            if sel_start and sel_end:
                widget.delete(sel_start, sel_end)
            else:
                widget.delete(tk.INSERT)
        menu.add_command(label="Delete", command=_do_delete)

        menu.add_separator()

        # ── Select All ───────────────────────────────────────────────────────
        menu.add_command(
            label="Select All",
            command=lambda: (widget.tag_add(tk.SEL, "1.0", tk.END),
                             widget.mark_set(tk.INSERT, "1.0"))
        )

        menu.add_separator()

        # ── Save Selected Image: always disabled ─────────────────────────────
        menu.add_command(
            label="Save Selected Image...",
            state=tk.DISABLED,
            foreground="#888888"
        )

        # ── Edit Selected Image: always disabled ─────────────────────────────
        menu.add_command(
            label="Edit Selected Image...",
            state=tk.DISABLED,
            foreground="#888888"
        )

        # ── Insert Image File: always enabled ────────────────────────────────
        menu.add_command(
            label="Insert Image File...",
            command=self.attach_image
        )

        # Display the menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def refresh_user_list(self):
        """Refresh the user list"""
        self.update_user_list()
        self.update_member_count()
    
    def is_online(self, ip_or_info):
        """Check if a user is online (within 35s timeout)"""
        if isinstance(ip_or_info, str):
            info = self.discovered_users.get(ip_or_info)
            if ip_or_info == self.host: return True
            if not info: return False
        else:
            info = ip_or_info

        ls = info.get('last_seen')
        if isinstance(ls, str):
            try: ls = datetime.datetime.fromisoformat(ls)
            except: ls = None
        
        if not isinstance(ls, datetime.datetime): return False
        return (datetime.datetime.now() - ls).total_seconds() <= 35

    def update_user_list(self):
        """Update the user list with sorting and visibility settings"""
        # Save current selection before clearing
        selected_items = self.user_tree.selection()
        selected_ips = []
        for item in selected_items:
            tags = self.user_tree.item(item, "tags")
            if tags:
                selected_ips.append(tags[0])
        
        # Clear existing items
        for item in self.user_tree.get_children():
            self.user_tree.delete(item)
        
        # Add local host
        self.discovered_users[self.host] = {
            'username': self.username,
            'hostname': self.hostname,
            'group': '',
            'last_seen': datetime.datetime.now()
        }

        # Handle column visibility using displaycolumns
        cols = ["User"] # User is always shown
        if self.show_columns["Group"].get(): cols.append("Group")
        if self.show_columns["Host"].get():  cols.append("Host")
        if self.show_columns["IP"].get():    cols.append("IP")
        self.user_tree.configure(displaycolumns=cols)
        
        # Update styling for gridlines (if available in theme)
        style = ttk.Style()
        # Note: True gridlines in Treeview depend on the current OS theme 
        # but we ensure the selection blue remains consistent.
        
        # Filter online users
        online_users = []
        for ip, info in self.discovered_users.items():
            if ip == self.host or self.is_online(info):
                online_users.append((ip, info))

        # SORTING LOGIC
        def get_sort_key(item):
            ip, info = item
            keys = []
            
            # 1. Primary Sort: Group
            if self.sort_group.get():
                grp = info.get('group', '').lower() if self.sort_ignore_case.get() else info.get('group', '')
                keys.append(grp if not self.sort_group_reverse.get() else ReverseSort(grp))
            
            # 2. Secondary Sort: User, IP, or Host
            sec_type = self.sort_secondary.get()
            val = ""
            if sec_type == "User": val = info.get('username', '')
            elif sec_type == "IP": val = ip
            elif sec_type == "Host": val = info.get('hostname', '')
            
            if self.sort_ignore_case.get(): val = val.lower()
            keys.append(val if not self.sort_secondary_reverse.get() else ReverseSort(val))
            
            return tuple(keys)

        class ReverseSort:
            def __init__(self, obj): self.obj = obj
            def __lt__(self, other): return self.obj > other.obj

        online_users.sort(key=get_sort_key)

        # Insert items
        inserted_items = {}
        for ip, user_info in online_users:
            username = user_info.get('username', 'Unknown')
            group = user_info.get('group', '')
            hostname = user_info.get('hostname', ip)
            display_host = hostname[:20] + "..." if len(hostname) > 20 else hostname
            
            item = self.user_tree.insert("", tk.END, values=(username, group, display_host, ip), tags=(ip,))
            inserted_items[ip] = item
        
        # Restore selection
        for ip in selected_ips:
            if ip in inserted_items:
                self.user_tree.selection_add(inserted_items[ip])
        
        # Schedule next update (2 seconds)
        if not hasattr(self, '_user_list_timer'):
             self._user_list_timer = None
        
        # Cancel previous timer if any
        if hasattr(self, 'root'):
            self.root.after(2000, self.update_user_list)
    
    def update_member_count(self):
        """Update member count label"""
        count = 0
        for ip, info in self.discovered_users.items():
            if ip == self.host or self.is_online(info):
                count += 1
        
        if hasattr(self, 'member_count_label') and self.member_count_label:
            self.member_count_label.config(text=str(count))
        # Schedule next update
        self.root.after(2000, self.update_member_count)
    
    def attach_image(self):
        """Attach an image file"""
        file_path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp"), ("All files", "*.*")]
        )
        if file_path:
            if file_path not in self.attached_files:
                self.attached_files.append(file_path)
                self.update_attachment_display()
    
    def update_attachment_display(self):
        """Update the text in the attachment entry and show/hide the frame"""
        if not self.attached_files:
            self.attachment_frame.pack_forget()
            self.attachment_path_var.set("")
        else:
            names = [os.path.basename(f) for f in self.attached_files]
            self.attachment_path_var.set(" ".join(names))
            # Ensure it's packed above the text area
            if not self.attachment_frame.winfo_manager():
                self.attachment_frame.pack(fill=tk.X, padx=2, pady=(0, 2), before=self.message_text)
        
    def open_attachment_manager(self):
        """Open the attachment manager dialog"""
        def update_callback(new_list):
            self.attached_files = new_list
            self.update_attachment_display()
            
        AttachmentManager(self.root, self.attached_files, update_callback)
    
    # Menu functions
    def show_user_history(self):
        """Show user history"""
        messagebox.showinfo("User History", "User history feature - Coming soon!")
    
    def search_user(self):
        """Search for a user"""
        search_window = tk.Toplevel(self.root)
        search_window.title("Search User")
        search_window.geometry("300x150")
        
        # Set icon for search window
        if self.icon_image:
            search_window.iconphoto(True, self.icon_image)
        
        ttk.Label(search_window, text="Search:").pack(pady=5)
        search_entry = ttk.Entry(search_window, width=30)
        search_entry.pack(pady=5)
        search_entry.focus()
        search_entry.insert(0, "admin")  # Default to "admin"
        
        def do_search():
            query = search_entry.get().strip().lower()
            if query:
                # Search in user list
                found = False
                for item in self.user_tree.get_children():
                    values = self.user_tree.item(item, "values")
                    username = values[0].lower() if values else ""
                    if query == username or query in str(values).lower():
                        self.user_tree.selection_set(item)
                        self.user_tree.see(item)
                        found = True
                        break
                if not found:
                    messagebox.showwarning("Not Found", f"User '{query}' not found in the list.")
            search_window.destroy()
        
        def send_to_user():
            query = search_entry.get().strip()
            if query:
                # Find user by username and send message
                found_ip = None
                for ip, user_info in self.discovered_users.items():
                    if user_info.get('username', '').lower() == query.lower():
                        found_ip = ip
                        break
                
                if found_ip:
                    # Get message text from message area
                    message = self.message_text.get(self.message_insert_point, tk.END).strip()
                    pass
                    
                    # Send message
                    if self.send_message_to_ip(found_ip, message, self.attached_files):
                        # Clear the sent message text completely
                        self.message_text.delete(self.message_insert_point, tk.END)
                        self.message_insert_point = self.message_text.index(tk.END)
                        self.message_text.mark_set(tk.INSERT, tk.END)
                        self.message_text.focus_set()
                        self.attached_files = []
                        self.update_attachment_display()
                    else:
                        messagebox.showerror("Error", f"Failed to send message to {query}.")
                else:
                    messagebox.showwarning("Not Found", f"User '{query}' not found.")
            search_window.destroy()
        
        search_entry.bind("<Return>", lambda e: do_search())
        button_frame = ttk.Frame(search_window)
        button_frame.pack(pady=5)
        ttk.Button(button_frame, text="Search", command=do_search).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Send to User", command=send_to_user).pack(side=tk.LEFT, padx=5)
        
        # Bind Ctrl-F shortcut
        self.root.bind("<Control-f>", lambda e: self.search_user())
        self.root.bind("<Control-k>", lambda e: self.capture_screen())
    
    def send_to_admin(self):
        """Quick send message to admin"""
        # Find admin user in the treeview and select it
        admin_found = False
        admin_item = None
        
        # First, try to find and select admin in the treeview
        for item in self.user_tree.get_children():
            values = self.user_tree.item(item, "values")
            if values and len(values) > 0:
                username = values[0].lower() if values[0] else ""
                if username == 'admin':
                    # Select admin in the list
                    self.user_tree.selection_set(item)
                    self.user_tree.see(item)
                    admin_found = True
                    admin_item = item
                    break
        
        # Also find admin IP for direct sending
        admin_ip = None
        for ip, user_info in self.discovered_users.items():
            if user_info.get('username', '').lower() == 'admin':
                admin_ip = ip
                break
        
        if not admin_found and not admin_ip:
            messagebox.showwarning("Not Found", "Admin user not found in the list. Make sure admin is online.")
            return
        
        # Get message text from message area
        message = self.message_text.get(self.message_insert_point, tk.END).strip()
        pass
        
        # Send message to admin
        if admin_ip and self.send_message_to_ip(admin_ip, message, self.attached_files):
            # Clear the sent message text completely
            self.message_text.delete(self.message_insert_point, tk.END)
            self.message_insert_point = self.message_text.index(tk.END)
            self.message_text.mark_set(tk.INSERT, tk.END)
            self.message_text.focus_set()
            self.attached_files = []
            self.update_attachment_display()
            # Keep admin selected
            if admin_item:
                self.user_tree.selection_set(admin_item)
        else:
            messagebox.showerror("Error", "Failed to send message to Admin. Check if admin is online and on the same network.")
    
    def create_group(self):
        """Create a new group from currently online users"""
        win = tk.Toplevel(self.root)
        win.title("Create Group")
        win.geometry("380x420")
        win.resizable(False, False)
        win.grab_set()
        if self.icon_image:
            try:
                win.iconphoto(True, self.icon_image)
            except:
                pass

        # Group name
        name_frame = ttk.Frame(win, padding=(10, 10, 10, 5))
        name_frame.pack(fill=tk.X)
        ttk.Label(name_frame, text="Group Name:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        group_name_var = tk.StringVar()
        name_entry = ttk.Entry(name_frame, textvariable=group_name_var, width=35)
        name_entry.pack(fill=tk.X, pady=(4, 0))
        name_entry.focus()

        # User selection list
        list_frame = ttk.LabelFrame(win, text="Select Members", padding=(8, 5))
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        columns = ("User", "Host", "IP")
        member_tree = ttk.Treeview(list_frame, columns=columns, show="headings",
                                   height=10, selectmode="extended")
        member_tree.heading("User", text="User")
        member_tree.heading("Host", text="Host")
        member_tree.heading("IP",   text="IP Address")
        member_tree.column("User", width=100)
        member_tree.column("Host", width=130)
        member_tree.column("IP",   width=110)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=member_tree.yview)
        member_tree.configure(yscrollcommand=sb.set)
        member_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)

        # Populate with online users
        current_time = datetime.datetime.now()
        # Populate with online users
        for ip, info in self.discovered_users.items():
            if ip != self.host and not self.is_online(info):
                continue
            uname = info.get('username', 'Unknown')
            hname = info.get('hostname', ip)
            display_host = hname[:18] + "..." if len(hname) > 18 else hname
            member_tree.insert("", tk.END, values=(uname, display_host, ip), tags=(ip,))

        # Hint label
        ttk.Label(win, text="Hold Ctrl / Shift to select multiple members.",
                  font=("Arial", 8), foreground="gray").pack(padx=10, anchor=tk.W)

        # Buttons
        btn_frame = ttk.Frame(win, padding=(10, 5, 10, 10))
        btn_frame.pack(fill=tk.X)

        def save_group():
            gname = group_name_var.get().strip()
            if not gname:
                messagebox.showwarning("No Name", "Please enter a group name.", parent=win)
                return
            selected = member_tree.selection()
            if not selected:
                messagebox.showwarning("No Members", "Please select at least one member.", parent=win)
                return
            ips = []
            for item in selected:
                tags = member_tree.item(item, "tags")
                if tags:
                    ips.append(tags[0])
            self.groups[gname] = ips
            messagebox.showinfo("Group Created",
                                f"Group '{gname}' created with {len(ips)} member(s).", parent=win)
            win.destroy()

        ttk.Button(btn_frame, text="Save Group", command=save_group).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=win.destroy).pack(side=tk.RIGHT)

    def select_group(self):
        """Select a group and highlight its members in the main user list"""
        if not self.groups:
            messagebox.showinfo("No Groups",
                                "No groups have been created yet.\nUse 'Create Group' first.")
            return

        win = tk.Toplevel(self.root)
        win.title("Select Group")
        win.geometry("340x360")
        win.resizable(False, False)
        win.grab_set()
        if self.icon_image:
            try:
                win.iconphoto(True, self.icon_image)
            except:
                pass

        ttk.Label(win, text="Available Groups:",
                  font=("Arial", 9, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 4))

        # Group list
        list_frame = ttk.Frame(win, padding=(10, 0, 10, 5))
        list_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("Group", "Members")
        group_tree = ttk.Treeview(list_frame, columns=columns, show="headings",
                                  height=10, selectmode="browse")
        group_tree.heading("Group",   text="Group Name")
        group_tree.heading("Members", text="Members")
        group_tree.column("Group",   width=180)
        group_tree.column("Members", width=80, anchor=tk.CENTER)

        sb2 = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=group_tree.yview)
        group_tree.configure(yscrollcommand=sb2.set)
        group_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.pack(side=tk.LEFT, fill=tk.Y)

        for gname, ips in self.groups.items():
            group_tree.insert("", tk.END, values=(gname, len(ips)), tags=(gname,))

        # Member preview
        preview_frame = ttk.LabelFrame(win, text="Members Preview", padding=(8, 4))
        preview_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        preview_label = ttk.Label(preview_frame, text="(select a group above)",
                                  foreground="gray", font=("Arial", 8))
        preview_label.pack(anchor=tk.W)

        def on_group_select(event=None):
            sel = group_tree.selection()
            if not sel:
                return
            tags = group_tree.item(sel[0], "tags")
            if not tags:
                return
            gname = tags[0]
            ips = self.groups.get(gname, [])
            # Build preview text from discovered_users
            names = []
            for ip in ips:
                info = self.discovered_users.get(ip, {})
                names.append(info.get('username', ip))
            preview_label.config(
                text=", ".join(names) if names else "(no online members)",
                foreground="black"
            )

        group_tree.bind("<<TreeviewSelect>>", on_group_select)

        # Buttons
        btn_frame = ttk.Frame(win, padding=(10, 0, 10, 10))
        btn_frame.pack(fill=tk.X)

        def apply_group():
            sel = group_tree.selection()
            if not sel:
                messagebox.showwarning("No Selection", "Please select a group.", parent=win)
                return
            tags = group_tree.item(sel[0], "tags")
            if not tags:
                return
            gname = tags[0]
            ips = self.groups.get(gname, [])

            # Clear current selection and select matching users in main treeview
            self.user_tree.selection_remove(self.user_tree.selection())
            matched = 0
            for item in self.user_tree.get_children():
                item_tags = self.user_tree.item(item, "tags")
                if item_tags and item_tags[0] in ips:
                    self.user_tree.selection_add(item)
                    self.user_tree.see(item)
                    matched += 1

            win.destroy()
            if matched == 0:
                messagebox.showinfo("Group Selected",
                                    f"Group '{gname}' selected, but none of its members are currently online.")
            else:
                messagebox.showinfo("Group Selected",
                                    f"Group '{gname}' selected — {matched} member(s) highlighted.")

        def delete_group():
            sel = group_tree.selection()
            if not sel:
                return
            tags = group_tree.item(sel[0], "tags")
            if not tags:
                return
            gname = tags[0]
            if messagebox.askyesno("Delete Group", f"Delete group '{gname}'?", parent=win):
                del self.groups[gname]
                group_tree.delete(sel[0])
                preview_label.config(text="(select a group above)", foreground="gray")

        ttk.Button(btn_frame, text="Select",       command=apply_group).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Delete Group", command=delete_group).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel",       command=win.destroy).pack(side=tk.RIGHT)
    
    def set_priority(self, priority):
        """Set message priority"""
        self.message_priority = priority
        messagebox.showinfo("Priority Set", f"Message priority set to: {priority}")
    
    def attach_file_folder(self):
        """Attach file or folder"""
        file_path = filedialog.askopenfilename(title="Select File")
        if file_path:
            if file_path not in self.attached_files:
                self.attached_files.append(file_path)
                self.update_attachment_display()
    
    def handle_dropped_files(self, files, target_list=None):
        """Handle files dropped onto the window"""
        t_list = target_list if target_list is not None else self.attached_files
        added = 0
        for f in files:
            path = f.decode('gbk') if isinstance(f, bytes) else f
            if path not in t_list:
                t_list.append(path)
                added += 1
        
        if added > 0:
            if target_list is None: # Only update main display if it's the main window
                self.update_attachment_display()
            self.status_var.set(f"Attached {added} new file(s)")

    def capture_screen(self, target_text=None, target_list=None):
        self.root.iconify()  # Minimize main window
        # Wait a bit for minimize animation
        self.root.after(300, lambda: self.start_snipping(target_text, target_list))

    def start_snipping(self, target_text=None, target_list=None):
        SnippingTool(self.root, lambda img: self.on_capture_complete(img, target_text, target_list))

    def on_capture_complete(self, image, target_text=None, target_list=None):
        self.root.deiconify()  # Restore main window
        if image:
            try:
                # Save to temp file
                temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
                image.save(temp_file)
                
                # Target identification
                txt_widget = target_text if target_text else self.message_text
                
                if target_list is not None:
                    target_list.append(temp_file)
                else:
                    if not hasattr(self, 'inline_images'):
                        self.inline_images = []
                    self.inline_images.append(temp_file)
                
                # Insert directly into message area
                self.insert_image_to_message(temp_file, txt_widget)
            except Exception as e:
                messagebox.showerror("Capture Error", f"Failed to save screenshot: {str(e)}")
    
    def insert_image_to_message(self, image_path, target_text=None):
        """Insert image into message text area"""
        txt = target_text if target_text else self.message_text
        try:
            # Resize for display if too large
            img = Image.open(image_path)
            # Max height 150px
            base_height = 150
            if img.size[1] > base_height:
                h_percent = (base_height / float(img.size[1]))
                w_size = int((float(img.size[0]) * float(h_percent)))
                img = img.resize((w_size, base_height), Image.Resampling.LANCZOS)
            
            photo = ImageTk.PhotoImage(img)
            self.chat_images.append(photo) # Keep reference to prevent GC
            
            txt.insert(tk.INSERT, "\n")
            txt.image_create(tk.INSERT, image=photo, padx=5, pady=5)
            txt.insert(tk.INSERT, "\n")
            txt.see(tk.END)
        except Exception as e:
            print(f"Error displaying image: {e}")
    
    def paste_image(self):
        """Paste image from clipboard"""
        try:
            image = ImageGrab.grabclipboard()
            if isinstance(image, Image.Image):
                # Save to temp file
                temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False).name
                image.save(temp_file)
                
                # Store in inline_images instead of attached_files
                if not hasattr(self, 'inline_images'):
                    self.inline_images = []
                self.inline_images.append(temp_file)
                
                # Insert directly into message area
                self.insert_image_to_message(temp_file)

            elif isinstance(image, list):
                # Handle file copy - treat as inline image if it's an image file
                if len(image) > 0 and os.path.isfile(image[0]):
                    if image[0].lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        # It's an image file, treat as inline
                        file_path = image[0]
                        
                        # Store in inline_images instead of attached_files
                        if not hasattr(self, 'inline_images'):
                            self.inline_images = []
                        self.inline_images.append(file_path)
                        
                        # Insert directly into message area
                        self.insert_image_to_message(file_path)
                    else:
                         messagebox.showwarning("Invalid Format", "The copied file is not a supported image.")
            else:
                 # Try getting text as file path fallback
                 try:
                    clipboard = self.root.clipboard_get()
                    if os.path.exists(clipboard) and clipboard.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                        self.attached_files.append(clipboard)
                        self.update_attachment_display()
                    else:
                        messagebox.showinfo("No Image", "No image found in clipboard.")
                 except:
                    messagebox.showinfo("No Image", "No image found in clipboard.")
        except Exception as e:
             messagebox.showerror("Paste Error", f"Failed to paste image: {str(e)}")
    
    def save_size_header_default(self):
        messagebox.showinfo("Settings", "Current window size saved as default.")

    def restore_default_size(self):
        self.root.state('normal')  # Ensure not maximized
        self.root.geometry("600x500")

    def list_font_settings(self):
        self.open_font_dialog("List Font", self.apply_list_font)

    def edit_font_settings(self):
        self.open_font_dialog("Edit Font", self.apply_edit_font)

    def open_font_dialog(self, title_text, callback):
        """Open font selection dialog"""
        font_window = tk.Toplevel(self.root)
        font_window.title(title_text)
        font_window.geometry("460x570")
        font_window.resizable(False, False)

        # Set icon using iconbitmap (same as main window)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ico_path = os.path.join(base_dir, "messenger.ico")
        if os.path.exists(ico_path):
            try:
                font_window.iconbitmap(ico_path)
            except Exception:
                pass
        elif self.icon_image:
            try:
                font_window.iconphoto(True, self.icon_image)
            except Exception:
                pass

        # Main container padding
        main = ttk.Frame(font_window, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        
        # Top section: 3 lists
        top_frame = ttk.Frame(main)
        top_frame.pack(fill=tk.X, expand=True)
        
        # 1. Font Family
        f_frame = ttk.Frame(top_frame)
        f_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        ttk.Label(f_frame, text="Font:").pack(anchor=tk.W)
        self.font_family_var = tk.StringVar()
        f_entry = ttk.Entry(f_frame, textvariable=self.font_family_var)
        f_entry.pack(fill=tk.X)
        
        f_list_frame = ttk.Frame(f_frame)
        f_list_frame.pack(fill=tk.BOTH, expand=True)
        self.f_list = tk.Listbox(f_list_frame, exportselection=False, width=20, height=10)
        f_scroll = ttk.Scrollbar(f_list_frame, orient=tk.VERTICAL, command=self.f_list.yview)
        self.f_list.config(yscrollcommand=f_scroll.set)
        self.f_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        f_scroll.pack(side=tk.LEFT, fill=tk.Y)
        
        # Populate fonts
        import tkinter.font as tkfont
        fonts = list(sorted(tkfont.families()))
        for f in fonts:
            self.f_list.insert(tk.END, f)
            
        # 2. Font Style
        s_frame = ttk.Frame(top_frame)
        s_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        ttk.Label(s_frame, text="Font style:").pack(anchor=tk.W)
        self.font_style_var = tk.StringVar(value="Regular")
        s_entry = ttk.Entry(s_frame, textvariable=self.font_style_var)
        s_entry.pack(fill=tk.X)
        
        s_list_frame = ttk.Frame(s_frame)
        s_list_frame.pack(fill=tk.BOTH, expand=True)
        self.s_list = tk.Listbox(s_list_frame, exportselection=False, width=15, height=10)
        s_scroll = ttk.Scrollbar(s_list_frame, orient=tk.VERTICAL, command=self.s_list.yview)
        self.s_list.config(yscrollcommand=s_scroll.set)
        self.s_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        s_scroll.pack(side=tk.LEFT, fill=tk.Y)
        
        styles = ["Regular", "Italic", "Bold", "Bold Italic"]
        for s in styles:
            self.s_list.insert(tk.END, s)
            
        # 3. Size
        z_frame = ttk.Frame(top_frame)
        z_frame.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(z_frame, text="Size:").pack(anchor=tk.W)
        self.font_size_var = tk.StringVar(value="10")
        z_entry = ttk.Entry(z_frame, textvariable=self.font_size_var)
        z_entry.pack(fill=tk.X)
        
        z_list_frame = ttk.Frame(z_frame)
        z_list_frame.pack(fill=tk.BOTH, expand=True)
        self.z_list = tk.Listbox(z_list_frame, exportselection=False, width=6, height=10)
        z_scroll = ttk.Scrollbar(z_list_frame, orient=tk.VERTICAL, command=self.z_list.yview)
        self.z_list.config(yscrollcommand=z_scroll.set)
        self.z_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        z_scroll.pack(side=tk.LEFT, fill=tk.Y)
        
        sizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]
        for z in sizes:
            self.z_list.insert(tk.END, str(z))

        # Sample preview area
        sample_frame = ttk.LabelFrame(main, text="Sample", padding=20)
        sample_frame.pack(fill=tk.X, pady=(20, 10))
        
        self.sample_label = tk.Label(sample_frame, text="AaBbYyZz", font=("Arial", 10))
        self.sample_label.pack()
        
        # Script dropdown - full list matching Windows Font dialog
        script_frame = ttk.Frame(main)
        script_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(script_frame, text="Script:").pack(anchor=tk.W)

        all_scripts = [
            "Western", "Greek", "Turkish", "Baltic", "Central European",
            "Cyrillic", "Vietnamese", "Arabic", "Hebrew", "Thai",
            "Japanese", "Korean", "Chinese Simplified", "Chinese Traditional"
        ]
        self.script_var = tk.StringVar(value="Western")
        script_combo = ttk.Combobox(script_frame, textvariable=self.script_var,
                                    values=all_scripts, state="readonly")
        script_combo.pack(fill=tk.X)

        # All available system fonts (kept for filtering)
        import tkinter.font as _tkfont2
        all_fonts_list = list(sorted(_tkfont2.families()))

        def filter_fonts_by_script(event=None):
            """Filter font list based on selected script"""
            script = self.script_var.get()
            script_keywords = {
                "Greek":               ["greek", "symbol", "palatino"],
                "Turkish":             ["arial", "times", "courier", "verdana", "tahoma"],
                "Baltic":              ["arial", "times", "courier", "verdana"],
                "Central European":    ["arial", "times", "courier", "calibri", "cambria"],
                "Cyrillic":            ["arial", "times", "courier", "verdana", "tahoma",
                                        "calibri", "cambria", "cyrillic", "russian"],
                "Vietnamese":          ["arial", "times", "courier", "verdana",
                                        "tahoma", "viet", "unicode"],
                "Arabic":              ["arabic", "tahoma", "traditional arabic",
                                        "simplified arabic", "andalus", "sakkal"],
                "Hebrew":              ["hebrew", "david", "miriam", "rod"],
                "Thai":                ["thai", "angsana", "cordia", "browallia", "leelawadee"],
                "Japanese":            ["gothic", "mincho", "meiryo", "yu gothic",
                                        "hiragino", "osaka", "ms ui"],
                "Korean":              ["batang", "gungsuh", "gulim", "dotum",
                                        "malgun", "nanum"],
                "Chinese Simplified":  ["simhei", "simsun", "nsimsun", "kaiti",
                                        "fangsong", "yahei", "dengxian"],
                "Chinese Traditional": ["mingliu", "pmingliu", "dfkai",
                                        "jhenghei", "biaukai"],
            }
            self.f_list.delete(0, tk.END)
            if script == "Western":
                filtered = all_fonts_list
            else:
                kws = script_keywords.get(script, [])
                filtered = [f for f in all_fonts_list
                            if any(k in f.lower() for k in kws)]
                if not filtered:
                    filtered = all_fonts_list   # fallback: show all
            for f in filtered:
                self.f_list.insert(tk.END, f)
            if self.f_list.size() > 0:
                self.f_list.selection_set(0)
                self.f_list.see(0)
                self.font_family_var.set(self.f_list.get(0))
                update_preview()

        script_combo.bind("<<ComboboxSelected>>", filter_fonts_by_script)

        # Show more fonts link (visual only)
        # using a simple label blue
        link = tk.Label(main, text="Show more fonts", fg="blue", cursor="hand2")
        link.pack(anchor=tk.W, pady=(0, 10))

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(btn_frame, text="Cancel", command=font_window.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="OK", command=lambda: self.apply_font_from_dialog(font_window, callback)).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Help").pack(side=tk.LEFT)

        # Bindings to update preview
        def update_preview(event=None):
            # Update entries based on selection
            if self.f_list.curselection():
                f = self.f_list.get(self.f_list.curselection())
                self.font_family_var.set(f)
            
            if self.s_list.curselection():
                s = self.s_list.get(self.s_list.curselection())
                self.font_style_var.set(s)
                
            if self.z_list.curselection():
                z = self.z_list.get(self.z_list.curselection())
                self.font_size_var.set(z)
            
            # Construct font
            try:
                family = self.font_family_var.get()
                size = int(self.font_size_var.get())
                style_str = self.font_style_var.get().lower()
                weight = "bold" if "bold" in style_str else "normal"
                slant = "italic" if "italic" in style_str else "roman"
                
                self.sample_label.config(font=(family, size, weight, slant))
            except:
                pass

        self.f_list.bind("<<ListboxSelect>>", update_preview)
        self.s_list.bind("<<ListboxSelect>>", update_preview)
        self.z_list.bind("<<ListboxSelect>>", update_preview)
        
        # Set default selections
        try:
            # Try to match current List font (Arial 10 bold (header) is default, let's select Arial 10 Regular)
            def select_item(listbox, item_text):
                try:
                    idx = listbox.get(0, tk.END).index(item_text)
                    listbox.selection_set(idx)
                    listbox.see(idx)
                except:
                    pass
            
            select_item(self.f_list, "Arial")
            select_item(self.s_list, "Regular")
            select_item(self.z_list, "10")
            update_preview()
        except:
            pass

    def apply_font_from_dialog(self, window, callback):
        try:
            family = self.font_family_var.get()
            size = int(self.font_size_var.get())
            style_str = self.font_style_var.get().lower()
            weight = "bold" if "bold" in style_str else "normal"
            slant = "italic" if "italic" in style_str else "roman"
            
            callback(family, size, weight, slant)
            window.destroy()
        except Exception as e:
            messagebox.showerror("Font Error", f"Error applying font:\n{str(e)}")

    def apply_list_font(self, family, size, weight, slant):
        style = ttk.Style()
        style.configure("Treeview", font=(family, size, weight, slant))
        style.configure("Treeview.Heading", font=(family, size, weight, slant))

    def apply_edit_font(self, family, size, weight, slant):
        self.message_text.configure(font=(family, size, weight, slant))
        
    def restore_default_font(self):
        self.apply_list_font("Arial", 9, "normal", "roman")
        self.apply_edit_font("Arial", 10, "normal", "roman")
        messagebox.showinfo("Font", "Restored default font settings.")

    def fix_position_settings(self):
        # Toggle fix position logic here if needed
        messagebox.showinfo("Position", "Window position fixed/unfixed.")
    
    def display_settings(self):
        """Display settings dialog for user list and sorting"""
        win = tk.Toplevel(self.root)
        win.title("SendWindow Sort/Display Settings")
        win.geometry("380x520")
        win.resizable(False, False)
        win.grab_set()
        
        if self.icon_image:
            try:
                win.iconphoto(True, self.icon_image)
            except:
                pass

        # 1. UserList Display option
        disp_frame = ttk.LabelFrame(win, text="UserList Display option", padding=10)
        disp_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Grid for checkboxes
        cb_group = ttk.Checkbutton(disp_frame, text="Group", variable=self.show_columns["Group"])
        cb_group.grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        cb_host = ttk.Checkbutton(disp_frame, text="Host", variable=self.show_columns["Host"])
        cb_host.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        cb_prio = ttk.Checkbutton(disp_frame, text="DispPriority", variable=self.show_columns["DispPriority"])
        cb_prio.grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        
        cb_logon = ttk.Checkbutton(disp_frame, text="Logon", variable=self.show_columns["Logon"])
        cb_logon.grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        cb_ip = ttk.Checkbutton(disp_frame, text="IP addr", variable=self.show_columns["IP"])
        cb_ip.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        cb_grid = ttk.Checkbutton(disp_frame, text="GridLines", variable=self.show_gridlines)
        cb_grid.grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        
        # Info Box
        info_text = "How to change header order :\nHeader Drag&Drop and execute \"save\nlist header\" menu item"
        info_label = tk.Label(disp_frame, text=info_text, justify=tk.LEFT, 
                              relief=tk.SUNKEN, bg="white", font=("Arial", 8), padx=5, pady=5)
        info_label.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))

        # 2. Broadly Sort Settings
        sort_frame = ttk.LabelFrame(win, text="Broadly Sort Settings", padding=10)
        sort_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # First sort key
        key1_frame = ttk.LabelFrame(sort_frame, text="First sort key", padding=5)
        key1_frame.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(key1_frame, text="Group name", variable=self.sort_group).pack(side=tk.LEFT, padx=10)
        ttk.Button(key1_frame, text="reverse", width=8, 
                   command=lambda: self.sort_group_reverse.set(not self.sort_group_reverse.get())).pack(side=tk.RIGHT, padx=5)

        # Second sort key
        key2_frame = ttk.LabelFrame(sort_frame, text="Second sort key", padding=5)
        key2_frame.pack(fill=tk.X, pady=2)
        
        rb_frame = ttk.Frame(key2_frame)
        rb_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        ttk.Radiobutton(rb_frame, text="User name", variable=self.sort_secondary, value="User").grid(row=0, column=0, sticky=tk.W, padx=5)
        ttk.Radiobutton(rb_frame, text="IP address", variable=self.sort_secondary, value="IP").grid(row=0, column=1, sticky=tk.W, padx=5)
        ttk.Radiobutton(rb_frame, text="Machine name", variable=self.sort_secondary, value="Host").grid(row=1, column=0, sticky=tk.W, padx=5)
        
        ttk.Button(key2_frame, text="reverse", width=8,
                   command=lambda: self.sort_secondary_reverse.set(not self.sort_secondary_reverse.get())).pack(side=tk.RIGHT, padx=5)

        # Ignore Case
        ttk.Checkbutton(sort_frame, text="Ignore capital/small letters", variable=self.sort_ignore_case).pack(anchor=tk.W, pady=5)

        # OK Button
        def apply_and_close():
            # Update gridlines style
            style = ttk.Style()
            if self.show_gridlines.get():
                style.configure("Treeview", rowheight=20) # Placeholder for gridline visual or actual setting if available
            
            # Immediately refresh the list with new settings
            self.update_user_list()
            win.destroy()

        ttk.Button(win, text="OK", command=apply_and_close, width=15).pack(pady=10)
    
    def main_settings(self):
        """Open the main settings dialog from the external file"""
        from main_settings import MainSettingsDialog
        # Pass self (the IPMessenger instance) so the dialog can call apply_main_settings
        MainSettingsDialog(self, self.username, self.group, self.icon_image)

    def apply_main_settings(self, new_name, new_group):
        """Apply changes from main settings dialog"""
        if new_name:
            self.username = new_name
        if new_group:
            self.group = new_group
        
        # Title change
        self.root.title(f"IP Messenger - {self.username}")
        
        # Immediate broadcast to announce the new identity
        self.send_immediate_broadcast()
        
        # Refresh local UI if we are in a dialog
        self.update_user_list()
        
        messagebox.showinfo("Settings", "Settings applied successfully.")

    def send_immediate_broadcast(self):
        """Send a single presence broadcast immediately on all interfaces"""
        try:
            self.broadcast_presence()
        except:
            pass
    
    def open_log_viewer(self):
        """Open IPMsg-style Log Viewer backed by SQLite database."""
        LogViewerWindow(self)
    
    def add_message_to_display(self, message, msg_type="received", sender_ip=None, sender_username=None):
        """Add received message to the display area"""
        if msg_type == "received":
            sender = sender_username if sender_username else (sender_ip if sender_ip else "Unknown")
            # Insert at current insertion point (no timestamp)
            self.message_text.insert(self.message_insert_point, f"{sender}: ", "received")
            self.message_text.insert(tk.END, f"{message}\n\n")
            
            # Configure tags
            self.message_text.tag_config("received", foreground="green", font=("Arial", 10, "bold"))
            
            # Update insertion point
            self.message_insert_point = self.message_text.index(tk.END)
            self.message_text.see(tk.END)
    
    def send_message(self):
        """Send message"""
        # Get selected recipients
        selected_items = self.user_tree.selection()
        if not selected_items:
            messagebox.showwarning("No Recipient", "Please select at least one recipient.")
            return
        
        # Get message text from the message text area
        # Get text from current cursor position to end (newly typed text)
        current_pos = self.message_text.index(tk.INSERT)
        end_pos = self.message_text.index(tk.END + "-1c")
        
        # Get the newly typed message (from insertion point to end)
        message = self.message_text.get(self.message_insert_point, tk.END).strip()
        pass
        
        # Get recipient IPs
        recipient_ips = []
        for item in selected_items:
            tags = self.user_tree.item(item, "tags")
            if tags:
                recipient_ips.append(tags[0])
        
        # Gather all files to send (attached files + inline images)
        files_to_send = list(self.attached_files)
        if hasattr(self, 'inline_images'):
            files_to_send.extend(self.inline_images)
        
        # Send to each recipient
        success_count = 0
        for ip in recipient_ips:
            if self.send_message_to_ip(ip, message, files_to_send):
                success_count += 1
                # ── persist sent message ──────────────────────────
                rec_info = self.discovered_users.get(ip, {})
                rec_name = rec_info.get('username', ip)
                now_ts   = datetime.datetime.now().isoformat()
                message_db.save_message(
                    direction  = "sent",
                    sender     = self.username,
                    recipient  = rec_name,
                    message    = message,
                    ip         = ip,
                    has_attach = bool(files_to_send),
                )
                # ── write to ip_messenger.log ────────────────────────
                _write_log(
                    direction  = "sent",
                    sender     = self.username,
                    recipient  = rec_name,
                    message    = message,
                    timestamp  = now_ts,
                    has_attach = bool(files_to_send),
                )
                # ─────────────────────────────────────────────────────

        if success_count > 0:
            # Clear the sent message text completely (from insertion point to end)
            self.message_text.delete(self.message_insert_point, tk.END)
            
            # Update insertion point to end (should be empty now)
            self.message_insert_point = self.message_text.index(tk.END)
            
            # Ensure cursor is at the end and focus is on the text widget
            self.message_text.mark_set(tk.INSERT, tk.END)
            self.message_text.focus_set()
            
            # Clear attached image and inline images
            self.attached_files = []
            if hasattr(self, 'inline_images'):
                self.inline_images = []
            self.update_attachment_display()
            
            # Minimize the window after successful send
            self.root.iconify()
        else:
            messagebox.showerror("Error", "Failed to send message. Check connections.")
    
    def send_message_to_ip(self, target_ip, message, attached_files=[]):
        """Send message to a specific IP"""
        try:
            # Prepare message data
            is_sealed = self.seal_var.get()
            message_to_send = message
            if is_sealed:
                message_to_send = self.seal_message(message)

            # If sending to self, handle differently
            if target_ip in self.get_all_local_ips() or target_ip in ["127.0.0.1", "localhost"]:
                self.handle_self_message(message_to_send, attached_files)
                return True
            
            # Create connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            target_port = self.discovered_users.get(target_ip, {}).get('port', self.port)
            sock.connect((target_ip, target_port))
            
            # Prepare message data for network
            message_data = {
                'message': message_to_send,
                'sender_ip': self.host,
                'sender_username': self.username,
                'sender_hostname': self.hostname,
                'port': self.port,
                'timestamp': datetime.datetime.now().isoformat(),
                'sealed': is_sealed
            }
            
            # Handle image if attached (sending first valid image as preview or base64 if needed)
            if attached_files:
                files_meta = []
                first_image_set = False
                
                for file_path in attached_files:
                    try:
                        file_name = os.path.basename(file_path)
                        file_size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
                        files_meta.append({
                            'name': file_name,
                            'size': file_size,
                            'type': 'dir' if os.path.isdir(file_path) else 'file'
                        })
                        
                        with self.offered_files_lock:
                            self.offered_files[file_name] = file_path

                        if not first_image_set and os.path.isfile(file_path) and file_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                            with open(file_path, 'rb') as f:
                                image_data = base64.b64encode(f.read()).decode('utf-8')
                            message_data['image'] = image_data
                            message_data['image_name'] = file_name
                            first_image_set = True
                    except:
                        pass
                
                message_data['files'] = files_meta
            
            if is_sealed:
                # Already sealed prefix applied above
                pass
            
            # Send message
            data = json.dumps(message_data).encode('utf-8')
            sock.sendall(data)
            sock.close()
            
            return True
        except Exception as e:
            return False
    
    def handle_self_message(self, message, attached_files=[]):
        """Handle message sent to self with attachment support"""
        timestamp = datetime.datetime.now().isoformat()
        is_sealed = message.startswith("[SEALED]")
        
        # Prepare file metadata
        files_meta = []
        for file_path in attached_files:
            try:
                name = os.path.basename(file_path)
                size = os.path.getsize(file_path) if os.path.isfile(file_path) else 0
                files_meta.append({
                    'name': name,
                    'size': size,
                    'type': 'dir' if os.path.isdir(file_path) else 'file'
                })
                # Ensure we can "download" from ourselves
                with self.offered_files_lock:
                    self.offered_files[name] = file_path
            except: pass

        # Unseal message if needed for internal processing
        display_text = message
        if is_sealed:
            # We unseal here so that 'on_click' receives the plain text
            # which is then passed to show_receive_message
            display_text = self.unseal_message(message)

        # toast_msg is what appears in the small popup notification
        toast_msg = "(Sealed Message)" if is_sealed else display_text
        if len(toast_msg) > 60: toast_msg = toast_msg[:57] + "..."

        # Callback for when toast is clicked
        def on_click(m=display_text, fm=files_meta, ts=timestamp):
            # Save to log/db (Clean text only)
            message_db.save_message(
                direction  = "received",
                sender     = self.username,
                recipient  = self.username,
                message    = m,
                ip         = self.host,
                has_attach = bool(fm),
                timestamp  = ts.replace('T', ' ').split('.')[0] # Format for DB
            )
            # Log to file (Clean)
            _write_log("received", self.username, self.username, m, ts, bool(fm))
            
            self.show_receive_message(self.username, self.hostname, self.host, 
                                   m, ts, sealed=is_sealed, files_meta=fm)
            
        self.show_toast_notification(
            self.username, self.hostname, self.host, 
            toast_msg, 
            timestamp,
            callback=on_click
        )
    
    def seal_message(self, message):
        """Seal/encrypt message (simple encoding for demonstration)"""
        # Simple base64 encoding as seal (in production, use proper encryption)
        encoded = base64.b64encode(message.encode('utf-8')).decode('utf-8')
        return f"[SEALED]{encoded}"
    
    def unseal_message(self, sealed_message):
        """Unseal/decrypt message"""
        if not sealed_message.startswith("[SEALED]"):
            return sealed_message
        try:
            # Strip the prefix and decode base64
            encoded_data = sealed_message[len("[SEALED]"):]
            decoded = base64.b64decode(encoded_data).decode('utf-8')
            return decoded
        except Exception:
            # Fallback if unsealing fails
            return sealed_message
    
    def start_server(self):
        """Start the server to listen for incoming connections"""
        if self.is_server_running:
            return
        
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('', self.port))
            self.server_socket.listen(5)
            self.is_server_running = True
            
            self.server_thread = threading.Thread(target=self.server_loop, daemon=True)
            self.server_thread.start()
        except Exception as e:
            messagebox.showerror("Server Error", f"Could not start server:\n{str(e)}")
    
    def server_loop(self):
        """Server loop to accept connections"""
        while self.is_server_running:
            try:
                client_socket, address = self.server_socket.accept()
                
                # Handle client in a separate thread
                client_thread = threading.Thread(
                    target=self.handle_client, 
                    args=(client_socket, address),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if self.is_server_running:
                    pass  # Socket closed
    
    def handle_client(self, client_socket, address):
        """Handle messages from a connected client - reads full data"""
        try:
            data_chunks = []
            while True:
                chunk = client_socket.recv(65536)
                if not chunk:
                    break
                data_chunks.append(chunk)
            
            if not data_chunks:
                return
                
            full_data = b''.join(data_chunks)
            try:
                data = full_data.decode('utf-8')
            except UnicodeDecodeError:
                # Fallback if binary data got in somehow, though we expect JSON
                return
            
            try:
                message_data = json.loads(data)
                sender_ip = address[0]
                sender_username = message_data.get('sender_username', None)
                
                if message_data.get('type') == 'read_receipt':
                    receiver_name = message_data.get('sender_username', sender_ip)
                    self.root.after(50, lambda: self.show_opened_toast_notification(receiver_name))
                    return

                if message_data.get('type') == 'file_request':
                    file_name = message_data.get('file_name')
                    with self.offered_files_lock:
                        path = self.offered_files.get(file_name)
                    
                    if path and os.path.exists(path):
                        try:
                            with open(path, 'rb') as f:
                                file_content = base64.b64encode(f.read()).decode('utf-8')
                            response = {
                                'type': 'file_response',
                                'file_name': file_name,
                                'data': file_content
                            }
                            client_socket.sendall(json.dumps(response).encode('utf-8'))
                        except:
                            pass
                    return

                # Update discovered users
                if sender_ip not in self.get_all_local_ips() and sender_ip not in ["127.0.0.1", "localhost"]:
                    self.discovered_users[sender_ip] = {
                        'username': sender_username or 'Unknown',
                        'hostname': message_data.get('sender_hostname', sender_ip),
                        'group': '',
                        'port': message_data.get('port', self.port),
                        'last_seen': datetime.datetime.now()
                    }
                
                # Show received message notification
                message = message_data.get('message', '')
                is_sealed = message_data.get('sealed', False)
                if message.startswith("[SEALED]"):
                    message = self.unseal_message(message)
                    is_sealed = True

                # ── Prepare content for display vs logging ──────────────────────────
                # User specifically requested NO attachment info text in the message
                display_message = message  
                log_message = message      
                
                files_meta = message_data.get('files', [])
                # We won't append [Attachments:] to log_message as per user request

                if message_data.get('image'):
                    if log_message: log_message += "\n"
                    log_message += f"\n[Attached Image: {message_data.get('image_name', 'image.png')}]"

                sender_hostname = message_data.get('sender_hostname', sender_ip)
                timestamp = message_data.get('timestamp', datetime.datetime.now().isoformat())

                # ── persist received message ──────────────────────────
                _has_attach = bool(
                    message_data.get('files') or message_data.get('image')
                )
                _now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                message_db.save_message(
                    direction  = "received",
                    sender     = sender_username or 'Unknown',
                    recipient  = self.username,
                    message    = log_message,
                    ip         = sender_ip,
                    has_attach = _has_attach,
                    timestamp  = _now_str,
                )
                # ── write to ip_messenger.log ────────────────────────
                _write_log(
                    direction  = "received",
                    sender     = sender_username or 'Unknown',
                    recipient  = self.username,
                    message    = log_message,
                    timestamp  = timestamp,
                    has_attach = _has_attach,
                )
                # ─────────────────────────────────────────────────────

                # Show toast notification - capture variables properly
                _msg    = display_message               # clean text for window
                _sealed = is_sealed
                _s_user = sender_username or 'Unknown'
                _s_host = sender_hostname
                _s_ip   = sender_ip
                _ts     = timestamp

                def show_toast(su=_s_user, sh=_s_host, si=_s_ip,
                               m=_msg, t=_ts, sl=_sealed, fm=message_data.get('files', [])):
                    # For sealed messages show "(Sealed Message)" in the toast body
                    # so the content is NOT revealed in the notification popup
                    display_msg = "(Sealed Message)" if sl else m

                    # Callback: clicking the toast opens the receive window with
                    # the actual decoded message and the correct sealed flag
                    def on_click(su=su, sh=sh, si=si, m=m, t=t, sl=sl, fm=fm):
                        self.show_receive_message(su, sh, si, m, t, sealed=sl, files_meta=fm)

                    self.show_toast_notification(su, sh, si, display_msg, t,
                                                 callback=on_click)
                self.root.after(50, show_toast)
            except json.JSONDecodeError:
                pass
        except Exception as e:
            pass
        finally:
            try:
                client_socket.close()
            except:
                pass
    
    def show_toast_notification(self, sender_username, sender_hostname, sender_ip, message, timestamp, callback=None):
        """Show a dark Windows 10/11-style toast notification (matches IPMSG screenshot)."""
        # ── colours ──────────────────────────────────────────────────
        BG      = "#1f1f1f"
        FG      = "#ffffff"
        FG_DIM  = "#aaaaaa"
        BTN_BG  = "#2d2d2d"

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.attributes("-alpha", 0.97)
        toast.configure(bg=BG)
        toast.resizable(False, False)

        # ── dimensions & position (bottom-right) ─────────────────────
        toast_w = 420
        toast_h = 120
        sw = toast.winfo_screenwidth()
        sh = toast.winfo_screenheight()
        x = sw - toast_w - 16
        y = sh - toast_h - 52 - (len(self.active_toasts) * (toast_h + 8))
        toast.geometry(f"{toast_w}x{toast_h}+{x}+{y}")

        # ── parse timestamp ──────────────────────────────────────────
        try:
            dt = datetime.datetime.fromisoformat(timestamp)
        except Exception:
            dt = datetime.datetime.now()
        time_str = dt.strftime("at %a %b %d %H:%M:%S %Y")

        # ══ layout ═══════════════════════════════════════════════════
        # Top header row:  "  IPMSG for Win              ⋯   ✕  "
        hdr = tk.Frame(toast, bg=BG)
        hdr.pack(fill=tk.X, padx=10, pady=(6, 0))

        # Small icon + app name in header
        if hasattr(self, 'toast_icon_small') and self.toast_icon_small:
            tk.Label(hdr, image=self.toast_icon_small,
                     bg=BG).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(hdr, text="IPMSG for Win", font=("Segoe UI", 8),
                 fg=FG_DIM, bg=BG).pack(side=tk.LEFT)

        # Close (✕) button
        close_btn = tk.Label(hdr, text="✕", font=("Segoe UI", 10),
                             fg=FG_DIM, bg=BG, cursor="hand2", padx=4)
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Button-1>", lambda e: self.close_toast(toast))
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=FG))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=FG_DIM))

        # More (⋯) button
        more_btn = tk.Label(hdr, text="⋯", font=("Segoe UI", 10),
                            fg=FG_DIM, bg=BG, cursor="hand2", padx=4)
        more_btn.pack(side=tk.RIGHT)
        more_btn.bind("<Enter>", lambda e: more_btn.config(fg=FG))
        more_btn.bind("<Leave>", lambda e: more_btn.config(fg=FG_DIM))

        # Body row:  [icon]  [text block]
        body = tk.Frame(toast, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 10))

        # Icon on the left
        icon_frame = tk.Frame(body, bg=BG, width=52, height=52)
        icon_frame.pack(side=tk.LEFT, padx=(0, 12))
        icon_frame.pack_propagate(False)

        toast_icon = self.toast_icon_image or self.icon_image
        if toast_icon:
            tk.Label(icon_frame, image=toast_icon,
                     bg=BG).pack(expand=True)
        else:
            cv = tk.Canvas(icon_frame, width=48, height=48,
                           bg=BG, highlightthickness=0)
            cv.pack(expand=True)
            cv.create_rectangle(4, 4, 24, 24, fill="#FFD700",
                                outline="#FF0000", width=2)
            cv.create_rectangle(24, 24, 44, 44, fill="#0078D4",
                                outline="#FF0000", width=2)
            cv.create_line(8, 8, 40, 40, fill="#FF0000", width=3)
            cv.create_line(40, 8, 8, 40, fill="#FF0000", width=3)

        # Text block on the right
        txt = tk.Frame(body, bg=BG)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(txt, text="Message Received",
                 font=("Segoe UI Semibold", 12), fg=FG, bg=BG,
                 anchor="w").pack(fill=tk.X)

        info_line = f"{sender_username} ({sender_hostname}/{sender_ip})"
        tk.Label(txt, text=info_line,
                 font=("Segoe UI", 9), fg=FG_DIM, bg=BG,
                 anchor="w").pack(fill=tk.X, pady=(2, 0))

        tk.Label(txt, text=time_str,
                 font=("Segoe UI", 9), fg=FG_DIM, bg=BG,
                 anchor="w").pack(fill=tk.X)

        # ── store data for click handler ─────────────────────────────
        toast.sender_username = sender_username
        toast.sender_hostname = sender_hostname
        toast.sender_ip   = sender_ip
        toast.message      = message
        toast.timestamp    = timestamp

        def on_toast_click(event):
            self.close_toast(toast)
            if callback:
                callback()
            else:
                # Default behavior: show receive window
                is_sealed = False
                if message == "(Sealed Message)" or getattr(toast, "_is_sealed", False):
                    is_sealed = True
                self.show_receive_message(
                    sender_username, sender_hostname,
                    sender_ip, message, timestamp,
                    sealed=is_sealed)

        # Bind click to everything
        for w in (toast, hdr, body, icon_frame, txt):
            w.bind("<Button-1>", on_toast_click)
        for child in txt.winfo_children():
            child.bind("<Button-1>", on_toast_click)

        # Hand cursor on hover
        for w in (toast, body, icon_frame, txt):
            w.config(cursor="hand2")
        for child in txt.winfo_children():
            child.config(cursor="hand2")

        # Track & animate
        self.active_toasts.append(toast)
        toast.update_idletasks()

        # Auto-dismiss after 8 seconds
        toast.after(8000, lambda: self.close_toast(toast))

        # Slide-in animation
        self.animate_toast_in(toast, x, y)
    
    def animate_toast_in(self, toast, target_x, target_y):
        """Animate toast sliding in from right"""
        start_x = toast.winfo_screenwidth()
        steps = 20
        delay = 10
        
        def animate(step):
            if not toast.winfo_exists(): return
            if step <= steps:
                current_x = start_x - (start_x - target_x) * (step / steps)
                toast.geometry(f"+{int(current_x)}+{target_y}")
                toast.after(delay, lambda: animate(step + 1))
            else:
                toast.geometry(f"+{target_x}+{target_y}")
        
        animate(0)
    
    def close_toast(self, toast):
        """Close toast notification"""
        if toast in self.active_toasts:
            self.active_toasts.remove(toast)
        toast.destroy()
        # Reposition remaining toasts
        self.reposition_toasts()
    
    def reposition_toasts(self):
        """Reposition remaining toasts"""
        screen_height = self.root.winfo_screenheight()
        toast_h = 120
        
        for i, toast in enumerate(self.active_toasts):
            try:
                x = toast.winfo_x()
                y = screen_height - toast_h - 52 - (i * (toast_h + 8))
                toast.geometry(f"{toast.winfo_width()}x{toast.winfo_height()}+{x}+{y}")
            except:
                pass
    
    def show_opened_toast_notification(self, receiver_name):
        """Show a 'Message was Opened' toast notification (matches user screenshot)."""
        print(f"[DEBUG] Showing 'Opened' toast for: {receiver_name}")
        BG      = "#1f1f1f"
        FG      = "#ffffff"
        FG_DIM  = "#aaaaaa"

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.attributes("-alpha", 0.97)
        toast.configure(bg=BG)
        toast.resizable(False, False)

        toast_w = 420
        toast_h = 100
        sw = toast.winfo_screenwidth()
        sh = toast.winfo_screenheight()
        x = sw - toast_w - 16
        # Account for multiple toasts stacked
        y = sh - toast_h - 52 - (len(self.active_toasts) * (toast_h + 8))
        toast.geometry(f"{toast_w}x{toast_h}+{x}+{y}")

        # Top header
        hdr = tk.Frame(toast, bg=BG)
        hdr.pack(fill=tk.X, padx=10, pady=(6, 0))
        if hasattr(self, 'toast_icon_small') and self.toast_icon_small:
            tk.Label(hdr, image=self.toast_icon_small, bg=BG).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(hdr, text="IPMSG for Win", font=("Segoe UI", 8), fg=FG_DIM, bg=BG).pack(side=tk.LEFT)
        
        close_btn = tk.Label(hdr, text="✕", font=("Segoe UI", 10), fg=FG_DIM, bg=BG, cursor="hand2", padx=4)
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Button-1>", lambda e: self.close_toast(toast))

        # Body row
        body = tk.Frame(toast, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 10))

        # Blue info icon on the left
        icon_frame = tk.Frame(body, bg=BG, width=52, height=52)
        icon_frame.pack(side=tk.LEFT, padx=(0, 12))
        icon_frame.pack_propagate(False)
        
        cv = tk.Canvas(icon_frame, width=48, height=48, bg=BG, highlightthickness=0)
        cv.pack(expand=True)
        cv.create_oval(4, 4, 44, 44, fill="#0078D4", outline="#0078D4")
        cv.create_text(24, 24, text="i", fill="white", font=("Times New Roman", 24, "bold"))

        # Text block
        txt = tk.Frame(body, bg=BG)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(txt, text="Message was Opened", font=("Segoe UI Semibold", 12), fg=FG, bg=BG, anchor="w").pack(fill=tk.X)
        tk.Label(txt, text=receiver_name, font=("Segoe UI", 11), fg=FG_DIM, bg=BG, anchor="w").pack(fill=tk.X)

        self.active_toasts.append(toast)
        toast.deiconify()
        toast.lift()
        toast.after(6000, lambda: self.close_toast(toast))
        self.animate_toast_in(toast, x, y)

    def send_read_receipt(self, target_ip):
        """Send a notification to the sender that the message was opened"""
        if not target_ip: return
        target_ip = target_ip.strip()
        print(f"[DEBUG] Receipt Target: {target_ip}")
        
        # Comprehensive self-check for local testing
        local_ips = set(self.get_all_local_ips()) | {"127.0.0.1", "localhost", self.host}
        if any(ip in target_ip for ip in local_ips) or any(target_ip in ip for ip in local_ips):
            print("[DEBUG] Self-Receipt Triggered")
            self.root.after(100, lambda: self.show_opened_toast_notification(self.username))
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            target_port = self.discovered_users.get(target_ip, {}).get('port', self.port)
            sock.connect((target_ip, target_port))
            
            data = json.dumps({
                'type': 'read_receipt',
                'sender_username': self.username,
                'sender_ip': self.host,
                'port': self.port
            }).encode('utf-8')
            
            sock.sendall(data)
            sock.close()
        except:
            pass

    def show_receive_message(self, sender_username, sender_hostname, sender_ip, message, timestamp, sealed=False, files_meta=[]):
        """Show receive message window"""
        receive_window = tk.Toplevel(self.root)
        receive_window.title("Receive Message ++++")
        receive_window.resizable(True, True)      # allow resize AND minimize
        # No transient → window gets its own taskbar entry and can be minimized
        
        # Icon
        if self.icon_image:
            receive_window.iconphoto(True, self.icon_image)
        
        # Parse timestamp
        try:
            dt = datetime.datetime.fromisoformat(timestamp)
            time_str = dt.strftime("at %a %b %d %H:%M:%S %Y")
        except:
            time_str = f"at {datetime.datetime.now().strftime('%a %b %d %H:%M:%S %Y')}"
        
        # ── Main container (pack only) ───────────────────────────────
        main_frame = tk.Frame(receive_window, bg="#f0f0f0")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # ── Header (with 1px border to match screenshot) ──────────────
        header_frame = tk.Frame(main_frame, bg="#f0f0f0", 
                                highlightbackground="#cccccc", highlightthickness=1)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Inner header padding
        header_inner = tk.Frame(header_frame, bg="#f0f0f0")
        header_inner.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(header_inner, text="Message from...",
                  font=("Segoe UI", 9)).pack(anchor=tk.W)
        ttk.Label(header_inner,
                  text=f"  {sender_username} ({sender_hostname}/{sender_ip})",
                  font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(2, 0))
        ttk.Label(header_inner, text=f"    {time_str}",
                  font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(2, 0))
        
        # ── Bottom button bar (packed BEFORE msg_frame so it stays fixed) ──
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(0, 0))
        
        # 📄 file icon (left)
        def view_received_attachments():
            self.show_attachments_dialog(sender_ip, files_meta)
            
        ttk.Button(button_frame, text="📄", command=view_received_attachments, width=3).pack(side=tk.LEFT)
        
        # Reply button
        def reply_message():
            receive_window.destroy()
            self.open_send_dialog_for_reply(sender_ip, sender_username, message)
        
        ttk.Button(button_frame, text="Reply",
                   command=reply_message,
                   width=10).pack(side=tk.RIGHT, padx=(4, 0))
        
        # Close button
        ttk.Button(button_frame, text="Close",
                   command=receive_window.destroy,
                   width=10).pack(side=tk.RIGHT, padx=(4, 4))
        
        # ── Attachment section (Hidden if sealed until opened) ──────────────
        attach_section = None
        if files_meta:
            attach_section = tk.Frame(main_frame, bg="#f0f0f0")
            if not sealed:
                attach_section.pack(fill=tk.X, pady=(0, 10))
            
            for f in files_meta:
                fn = f.get('name', 'Unknown')
                fs = f.get('size', 0)
                
                # Attachment UI box with blue border
                item_frame = tk.Frame(attach_section, bg="#f0f0f0",
                                     highlightbackground="#3498db", highlightthickness=1)
                item_frame.pack(fill=tk.X, pady=1)
                
                # Filename label with light blue background
                f_lbl = tk.Label(item_frame, text=fn, font=("Segoe UI", 10),
                                bg="#eef6ff", fg="#000000", anchor=tk.W, 
                                padx=8, pady=3, cursor="hand2")
                f_lbl.pack(fill=tk.X, padx=1, pady=1)
                
                # Visual hover effect
                f_lbl.bind("<Enter>", lambda e, l=f_lbl: l.config(bg="#d9eaff"))
                f_lbl.bind("<Leave>", lambda e, l=f_lbl: l.config(bg="#eef6ff"))

                def start_dl(event, name=fn):
                    # Guess the file type based on extension
                    ext = os.path.splitext(name)[1].lower()
                    ftypes = [("All Files", "*.*")]
                    if ext == ".png": ftypes.insert(0, ("PNG Image", "*.png"))
                    elif ext in [".jpg", ".jpeg"]: ftypes.insert(0, ("JPEG Image", "*.jpg;*.jpeg"))
                    elif ext == ".pdf": ftypes.insert(0, ("PDF Document", "*.pdf"))
                    elif ext == ".txt": ftypes.insert(0, ("Text File", "*.txt"))
                    elif ext == ".ipynb": ftypes.insert(0, ("Jupyter Notebook", "*.ipynb"))
                    
                    dst = filedialog.asksaveasfilename(
                        initialfile=name, 
                        title=f"Save {name}",
                        defaultextension=ext if ext else "",
                        filetypes=ftypes,
                        parent=self.root
                    )
                    if dst:
                        self.status_var.set(f"Downloading {name}...")
                        threading.Thread(target=self.perform_download, 
                                         args=(sender_ip, name, dst), daemon=True).start()
                
                f_lbl.bind("<Button-1>", start_dl)
        
        # ── Message content area (fills remaining space) ─────────────
        msg_frame = tk.Frame(main_frame, bg="white", bd=0)
        msg_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        
        # Trigger receipt if it contains attachments (standard message)
        if not sealed and files_meta:
            print("[DEBUG] Non-sealed with attachments, sending receipt")
            threading.Thread(target=self.send_read_receipt,
                             args=(sender_ip,), daemon=True).start()

        if sealed:
            # ── SEALED: EXACT MATCH FOR SCREENSHOT "Open" BOX ────────
            receive_window.geometry("380x280")
            receive_window.minsize(360, 240)
            
            # Make the msg_frame blend with the window background
            msg_frame.config(bg="#f0f0f0")
            
            seal_box = tk.Label(
                msg_frame, bg="#eef7ff",
                highlightbackground="#3498db", highlightthickness=1,
                text="Open", font=("Segoe UI", 11),
                fg="#000000", cursor="hand2",
                bd=0
            )
            seal_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

            def reveal_message(event=None):
                # Show attachment section if it exists
                if attach_section:
                    attach_section.pack(fill=tk.X, pady=(0, 10), before=msg_frame)

                # Send read receipt on opening (every time for this instance)
                print("[DEBUG] Sealed message opened, sending receipt")
                threading.Thread(target=self.send_read_receipt,
                                 args=(sender_ip,), daemon=True).start()
                
                # Clear sealed placeholder widgets
                for w in msg_frame.winfo_children():
                    w.destroy()
                
                # Turn msg_frame into normal white message box
                msg_frame.config(
                    bg="white", bd=0,
                    highlightbackground="#cccccc", highlightthickness=1
                )
                receive_window.geometry("520x420")
                
                txt = scrolledtext.ScrolledText(
                    msg_frame, wrap=tk.WORD, font=("Arial", 11),
                    state=tk.DISABLED, bd=0, highlightthickness=0
                )
                txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                txt.config(state=tk.NORMAL)
                txt.delete("1.0", tk.END)
                txt.insert("1.0", message)
                txt.config(state=tk.DISABLED)

            seal_box.bind("<Button-1>", reveal_message)
            # Exact hover colors for premium feel
            seal_box.bind("<Enter>", lambda e: seal_box.config(bg="#d9eaff"))
            seal_box.bind("<Leave>", lambda e: seal_box.config(bg="#eef7ff"))

        else:
            # ── NOT SEALED: show message immediately ──────────────────
            receive_window.geometry("520x420")
            receive_window.minsize(380, 300)
            txt = scrolledtext.ScrolledText(
                msg_frame, wrap=tk.WORD, font=("Arial", 11),
                state=tk.DISABLED, bd=0, highlightthickness=0
            )
            txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            txt.config(state=tk.NORMAL)
            txt.delete("1.0", tk.END)
            txt.insert("1.0", message)
            txt.config(state=tk.DISABLED)
            self.receipt_sent_map[sender_ip] = True

        
    
    def open_send_dialog_for_reply(self, reply_ip, reply_username, quoted_message=None):
        """Open send dialog for replying to a message"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Send Message (for Reply)")
        dialog.geometry("600x500")
        dialog.resizable(True, True)  # allow resize, minimize, and maximize
        # No transient or grab_set -> allows independent window behavior like minimizing to taskbar
        
        # Icon is inherited from root window, but set explicitly if available
        if self.icon_image:
            dialog.iconphoto(True, self.icon_image)
        
        # Main container - reduced padding
        main_container = ttk.Frame(dialog, padding="8")
        main_container.pack(fill=tk.BOTH, expand=True)
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(1, weight=1)
        
        # User list frame - reduced padding and spacing
        user_frame = ttk.LabelFrame(main_container, text="Recipients", padding="5")
        user_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N), pady=(0, 5))
        user_frame.columnconfigure(0, weight=1)
        user_frame.rowconfigure(0, weight=1)
        
        # User list with scrollbar
        list_container = ttk.Frame(user_frame)
        list_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        list_container.columnconfigure(0, weight=1)
        list_container.rowconfigure(0, weight=1)
        
        # Treeview for user list
        columns = ("User", "Group", "Host", "IP")
        user_tree = ttk.Treeview(list_container, columns=columns, show="headings", height=6, selectmode="extended")
        user_tree.heading("User", text="User")
        user_tree.heading("Group", text="Group")
        user_tree.heading("Host", text="Host")
        user_tree.heading("IP", text="IP")
        user_tree.column("User", width=150)
        user_tree.column("Group", width=100)
        user_tree.column("Host", width=180)
        user_tree.column("IP", width=130)
        
        scrollbar_y = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=user_tree.yview)
        user_tree.configure(yscrollcommand=scrollbar_y.set)
        
        user_tree.grid(row=0, column=0, sticky="wens")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        
        # Populate user list and select reply recipient
        reply_item = None
        for ip, user_info in self.discovered_users.items():
            if ip != self.host and not self.is_online(user_info):
                continue
            
            username = user_info.get('username', 'Unknown')
            group = user_info.get('group', '')
            hostname = user_info.get('hostname', ip)
            display_host = hostname[:20] + "..." if len(hostname) > 20 else hostname
            
            item = user_tree.insert("", tk.END, values=(username, group, display_host, ip), tags=(ip,))
            if ip == reply_ip:
                reply_item = item
        
        # Select reply recipient
        if reply_item:
            user_tree.selection_set(reply_item)
            user_tree.see(reply_item)
        
        # Member count and refresh panel
        member_panel = ttk.Frame(user_frame)
        member_panel.grid(row=0, column=1, padx=(10, 0), sticky=tk.N)
        
        ttk.Label(member_panel, text="Member", font=("Arial", 9)).pack()
        member_count = 0
        for ip, info in self.discovered_users.items():
            if ip == self.host or self.is_online(info):
                member_count += 1
        ttk.Label(member_panel, text=str(member_count), font=("Arial", 10, "bold")).pack()
        
        refresh_btn = ttk.Button(member_panel, text="⟳", command=lambda: self.refresh_user_list_dialog(user_tree, member_panel), width=3)
        refresh_btn.pack(pady=(10, 0))
        
        # Message input area - reduced padding
        msg_input_frame = ttk.LabelFrame(main_container, text="Message", padding="5")
        msg_input_frame.grid(row=1, column=0, columnspan=2, sticky="wens", pady=(0, 5))
        msg_input_frame.columnconfigure(0, weight=1)
        msg_input_frame.rowconfigure(0, weight=1)
        
        message_text = scrolledtext.ScrolledText(
            msg_input_frame,
            wrap=tk.WORD,
            width=60,
            height=12,
            font=("Arial", 10)
        )
        message_text.pack(fill=tk.BOTH, expand=True)
        
        # Handle quoted message if provided
        message_text.delete("1.0", tk.END)
        if quoted_message:
            last_msg_lines = [line for line in quoted_message.split("\n") if not line.startswith(">")]
            while last_msg_lines and not last_msg_lines[0].strip():
                last_msg_lines.pop(0)
            quoted_lines = [">" + line for line in last_msg_lines]
            message_text.insert("1.0", "\n".join(quoted_lines) + "\n\n")
        
        # Ensure scrollbar is visible
        message_text.update()
        message_text.focus_set()
        
        # Bottom controls - reduced spacing
        controls_frame = ttk.Frame(main_container)
        controls_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 0))
        controls_frame.columnconfigure(1, weight=1)
        
        # Document/File icon button
        attached_files = []  # Use list to allow modification
        def open_attachments():
            def cb(new_list):
                attached_files.clear()
                attached_files.extend(new_list)
            
            AttachmentManager(dialog, attached_files, cb)
        
        # Snipping Tool / Capture (for prompt reply)
        snip_img = self.ui_icons.get("snip")
        snip_cmd = lambda: self.capture_screen(target_text=message_text, target_list=attached_files)
        if snip_img:
            snip_btn = ttk.Button(controls_frame, image=snip_img, command=snip_cmd)
        else:
            snip_btn = ttk.Button(controls_frame, text="捕", command=snip_cmd, width=3)
        snip_btn.grid(row=0, column=0, padx=(0, 5), sticky=tk.W)
        
        # Document/File icon button (moved)
        doc_btn = ttk.Button(controls_frame, text="📄", command=open_attachments, width=3)
        doc_btn.grid(row=0, column=1, padx=(0, 5), sticky=tk.W)
        
        # Setup Drag & Drop for reply dialog
        try:
            import windnd
            windnd.hook_dropfiles(dialog, lambda files: self.handle_dropped_files(files, target_list=attached_files))
        except: pass
        
        # Send button
        def send_reply():
            selected_items = user_tree.selection()
            if not selected_items:
                messagebox.showwarning("No Recipient", "Please select at least one recipient.")
                return
            
            message = message_text.get("1.0", tk.END).strip()
            pass
            
            recipient_ips = []
            for item in selected_items:
                tags = user_tree.item(item, "tags")
                if tags:
                    recipient_ips.append(tags[0])
            
            success_count = 0
            # Temporarily set seal_var for sending
            old_seal = self.seal_var.get()
            self.seal_var.set(seal_var.get())
            for ip in recipient_ips:
                if self.send_message_to_ip(ip, message, attached_files):
                    success_count += 1
                    
                    # ── persist sent message ──────────────────────────
                    rec_info = self.discovered_users.get(ip, {})
                    rec_name = rec_info.get('username', ip)
                    now_ts   = datetime.datetime.now().isoformat()
                    message_db.save_message(
                        direction  = "sent",
                        sender     = self.username,
                        recipient  = rec_name,
                        message    = message,
                        ip         = ip,
                        has_attach = bool(attached_files),
                    )
                    # ── write to ip_messenger.log ────────────────────────
                    _write_log(
                        direction  = "sent",
                        sender     = self.username,
                        recipient  = rec_name,
                        message    = message,
                        timestamp  = now_ts,
                        has_attach = bool(attached_files),
                    )
            self.seal_var.set(old_seal)
            
            if success_count > 0:
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Failed to send message. Check connections.")
        
        send_btn = ttk.Button(controls_frame, text="Send", command=send_reply, width=12)
        send_btn.grid(row=0, column=1, padx=(0, 5), sticky=tk.E)
        
        # Seal checkbox (checked by default) - to the right of Send button
        seal_var = tk.BooleanVar(value=True)
        seal_check = ttk.Checkbutton(controls_frame, text="seal", variable=seal_var)
        seal_check.grid(row=0, column=2, sticky=tk.E)
        
        # Store seal_var for use in send_reply
        dialog.seal_var = seal_var

    def show_attachments_dialog(self, sender_ip, files_meta):
        """Show dialog to view and download received attachments"""
        if not files_meta:
            messagebox.showinfo("Attachments", "No attachments in this message.")
            return

        window = tk.Toplevel(self.root)
        window.title("Received Attachments")
        window.geometry("500x350")
        window.transient(self.root)
        
        if self.icon_image:
            window.iconphoto(True, self.icon_image)
            
        main_frame = ttk.Frame(window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text=f"Attachments from {sender_ip}", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 10))

        columns = ("name", "size", "type")
        tree = ttk.Treeview(main_frame, columns=columns, show="headings", height=8)
        tree.heading("name", text="File Name")
        tree.heading("size", text="Size")
        tree.heading("type", text="Type")
        
        tree.column("name", width=220)
        tree.column("size", width=100)
        tree.column("type", width=80)
        
        for f in files_meta:
            sz = f.get('size', 0)
            size_str = f"{sz} B"
            if sz > 1024*1024: size_str = f"{sz//(1024*1024)} MB"
            elif sz > 1024: size_str = f"{sz//1024} KB"
            
            tree.insert("", tk.END, values=(f.get('name'), size_str, f.get('type', 'file')))
            
        tree.pack(fill=tk.BOTH, expand=True)
        
        def download_selected():
            selection = tree.selection()
            if not selection:
                messagebox.showwarning("Selection", "Please select a file to download.")
                return
            item = tree.item(selection[0])
            file_name = item['values'][0]
            
            save_path = filedialog.asksaveasfilename(initialfile=file_name, title="Save Attachment")
            if save_path:
                self.status_var.set(f"Downloading {file_name}...")
                threading.Thread(target=self.perform_download, args=(sender_ip, file_name, save_path), daemon=True).start()

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        
        ttk.Button(btn_frame, text="Download Selected", command=download_selected, width=20).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Close", command=window.destroy).pack(side=tk.RIGHT, padx=10)

    def perform_download(self, sender_ip, file_name, save_path):
        """Actually download the file content (via direct copy for self, or socket for others)"""
        try:
            # ── Special Case: Self Transfer (Reliability) ───────────────────────
            # Normalize IPs for comparison
            is_self = (sender_ip in self.get_all_local_ips() or 
                       sender_ip in ["127.0.0.1", "localhost", "0.0.0.0"])
            
            if is_self:
                with self.offered_files_lock:
                    local_src = self.offered_files.get(file_name)
                
                if local_src and os.path.exists(local_src):
                    try:
                        import shutil
                        shutil.copy2(local_src, save_path)
                        
                        # Verify the copy worked
                        if os.path.exists(save_path):
                            self.root.after(0, lambda n=file_name: [
                                self.status_var.set("Ready"),
                                messagebox.showinfo("Success", f"Successfully saved (Self Transfer):\n{n}", parent=self.root)
                            ])
                            return
                    except Exception as copy_err:
                        print(f"Self-copy failed: {copy_err}, trying network fallback...")
                # If local_src not found, fall through to network attempt just in case

            # ── Network Transfer ───────────────────────────────────────────────
            # Connect to sender
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(15)
            
            # If the provided IP is our own, try localhost first to avoid firewall issues
            connect_ip = sender_ip
            if connect_ip == self.host: connect_ip = "127.0.0.1"
            
            target_port = self.discovered_users.get(sender_ip, {}).get('port', self.port)
            sock.connect((connect_ip, target_port))
            
            request = {
                'type': 'file_request',
                'file_name': file_name,
                'sender_ip': self.host,
                'sender_username': self.username,
                'port': self.port
            }
            sock.sendall(json.dumps(request).encode('utf-8'))
            sock.shutdown(socket.SHUT_WR) # Signal end of request to server
            
            # Receive response chunks until closed by server
            data_chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data_chunks.append(chunk)
            
            sock.close()
            
            if not data_chunks:
                raise Exception("No data received from sender.")
                
            full_data = b''.join(data_chunks)
            response = json.loads(full_data.decode('utf-8'))
            
            if response.get('type') == 'file_response' and 'data' in response:
                file_content = base64.b64decode(response['data'])
                with open(save_path, 'wb') as f:
                    f.write(file_content)
                    f.flush()
                    os.fsync(f.fileno())
                
                # Verify file was written
                if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                    self.root.after(0, lambda n=file_name: [
                        self.status_var.set("Ready"),
                        messagebox.showinfo("Success", f"Successfully saved:\n{n}", parent=self.root)
                    ])
                else:
                    raise Exception("File was created but is empty or missing.")
            else:
                raise Exception("Invalid response type from sender.")
                
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Download Error", f"Failed to download {file_name}:\n{str(e)}"))
        finally:
            self.root.after(0, lambda: self.status_var.set("Ready"))

    def refresh_user_list_dialog(self, user_tree, member_panel):
        """Refresh user list in dialog"""
        for item in user_tree.get_children():
            user_tree.delete(item)
        
        current_time = datetime.datetime.now()
        for ip, user_info in self.discovered_users.items():
            if ip != self.host and not self.is_online(user_info):
                continue
            
            username = user_info.get('username', 'Unknown')
            group = user_info.get('group', '')
            hostname = user_info.get('hostname', ip)
            display_host = hostname[:20] + "..." if len(hostname) > 20 else hostname
            
            user_tree.insert("", tk.END, values=(username, group, display_host, ip), tags=(ip,))
        
        count = 0
        for ip, info in self.discovered_users.items():
            if ip == self.host or self.is_online(info):
                count += 1
        for widget in member_panel.winfo_children():
            if isinstance(widget, ttk.Label) and widget.cget("text").isdigit():
                widget.config(text=str(count))
    
    def unseal_message(self, message):
        """Unseal/decrypt message"""
        if message.startswith("[SEALED]"):
            try:
                encoded = message[8:]  # Remove [SEALED] prefix
                decoded = base64.b64decode(encoded).decode('utf-8')
                return decoded
            except:
                return message
        return message
    
    def broadcast_presence(self):
        """Broadcast presence on all active local interfaces"""
        local_ips = self.get_all_local_ips()
        for ip in local_ips:
            broadcast_data = json.dumps({
                'type': 'presence',
                'username': self.username,
                'group': self.group,
                'hostname': self.hostname,
                'ip': ip,
                'port': self.port
            })
            
            host_parts = ip.split('.')
            if len(host_parts) == 4:
                if ip.startswith("169.254"):
                    network = "169.254.255.255"
                else:
                    network = '.'.join(host_parts[:-1]) + '.255'
            else:
                network = '255.255.255.255'
                
            try:
                # Bind temporary UDP socket to specific interface IP to force routing
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((ip, 0))
                
                # Send to calculated subnet broadcast
                sock.sendto(broadcast_data.encode('utf-8'), (network, self.broadcast_port))
                
                # Also send to global broadcast address as fallback
                sock.sendto(broadcast_data.encode('utf-8'), ('255.255.255.255', self.broadcast_port))
                sock.close()
            except Exception:
                pass

    def start_broadcast(self):
        """Start broadcasting presence on the network"""
        try:
            self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            self.broadcast_thread = threading.Thread(target=self.broadcast_loop, daemon=True)
            self.broadcast_thread.start()
        except Exception as e:
            pass
    
    def broadcast_loop(self):
        """Broadcast presence periodically on all interfaces and detect local IP changes"""
        while self.is_server_running:
            try:
                self.host = self.get_local_ip()
                self.broadcast_presence()
                threading.Event().wait(5)  # Broadcast every 5 seconds
            except Exception as e:
                threading.Event().wait(5)
    
    def start_discovery(self):
        """Start listening for presence broadcasts"""
        try:
            discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            discovery_socket.bind(('', self.broadcast_port))
            
            self.discovery_thread = threading.Thread(
                target=self.discovery_loop,
                args=(discovery_socket,),
                daemon=True
            )
            self.discovery_thread.start()
        except Exception as e:
            pass
    
    def discovery_loop(self, discovery_socket):
        """Listen for presence broadcasts"""
        while self.is_server_running:
            try:
                data, addr = discovery_socket.recvfrom(1024)
                try:
                    presence_data = json.loads(data.decode('utf-8'))
                    if presence_data.get('type') == 'presence':
                        ip = addr[0]
                        # Don't add ourselves
                        if ip not in self.get_all_local_ips() and ip not in ["127.0.0.1", "localhost"]:
                            self.discovered_users[ip] = {
                                'username': presence_data.get('username', 'Unknown'),
                                'hostname': presence_data.get('hostname', ip),
                                'group': presence_data.get('group', ''),
                                'port': presence_data.get('port', self.port),
                                'last_seen': datetime.datetime.now()
                            }
                except json.JSONDecodeError:
                    pass
            except Exception as e:
                if self.is_server_running:
                    pass
    
    def on_closing(self):
        """Handle window closing"""
        self.is_server_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        if self.broadcast_socket:
            try:
                self.broadcast_socket.close()
            except:
                pass
        self.root.destroy()

def main():
    # ── Windows taskbar icon fix ──────────────────────────────────────────────
    # Setting a unique AppUserModelID BEFORE Tk() is created tells Windows to
    # treat this as its own application, so the taskbar shows our .ico instead
    # of the generic Python interpreter icon.
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "IPMessenger.App.1.0"
            )
        except Exception:
            pass

    root = tk.Tk()

    # Apply .ico to title bar + taskbar (iconbitmap is the most reliable on Win32)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(base_dir, "messenger.ico")
    png_path = os.path.join(base_dir, "messenger.png")

    # Auto-generate .ico if missing
    if not os.path.exists(ico_path) and os.path.exists(png_path):
        try:
            Image.open(png_path).save(
                ico_path, format="ICO",
                sizes=[(16, 16), (32, 32), (48, 48), (64, 64)]
            )
        except Exception:
            pass

    if os.path.exists(ico_path):
        try:
            root.iconbitmap(default=ico_path)
        except Exception:
            pass

    app = IPMessenger(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
