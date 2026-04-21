import tkinter as tk
from tkinter import ttk, messagebox
import os

class MainSettingsDialog:
    def __init__(self, parent, current_username, current_group, icon_image=None):
        self.parent = parent
        # Parent is the IPMessenger instance, its root is the Tk window
        self.window = tk.Toplevel(parent.root)
        self.window.title("IP Messenger Settings")
        self.window.geometry("640x540")
        self.window.resizable(False, False)
        self.window.grab_set()
        
        # Set icon
        if icon_image:
            try:
                self.window.iconphoto(True, icon_image)
            except:
                pass
        else:
            # Try to load icon if not provided
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                ico_path = os.path.join(base_dir, "messenger.ico")
                if os.path.exists(ico_path):
                    self.window.iconbitmap(ico_path)
            except:
                pass

        # Use a PanedWindow or just frames for the side-by-side layout
        main_paned = ttk.Frame(self.window)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left Column: Category List and Sidebar Buttons
        left_col = ttk.Frame(main_paned)
        left_col.place(x=0, y=0, width=280, height=520)

        self.setup_sidebar(left_col)
        self.setup_sidebar_buttons(left_col)

        # Right Column: Content Frame
        self.right_col = ttk.Frame(main_paned)
        self.right_col.place(x=300, y=0, width=320, height=520)
        
        # We will focus on "Basic/LAN Settings" as per the screenshot
        self.show_basic_settings(current_username, current_group)

    def setup_sidebar(self, parent):
        categories = [
            "Basic/LAN Settings", "Master Settings", "Detail Settings",
            "Send Window", "Recv Window", "TaskTray", "Image/Capture",
            "URL/File Link", "Log Settings", "Auto FileDownload",
            "Remote Command", "Recv Trans (Slack/etc)", "Auto Update",
            "Settings/Experiment"
        ]
        
        list_frame = ttk.Frame(parent)
        list_frame.place(x=0, y=0, width=280, height=350)
        
        self.category_list = tk.Listbox(list_frame, font=("Segoe UI", 10), bd=1, relief=tk.SOLID)
        for cat in categories:
            self.category_list.insert(tk.END, cat)
        
        self.category_list.pack(fill=tk.BOTH, expand=True)
        self.category_list.select_set(0) # Default selection

    def setup_sidebar_buttons(self, parent):
        btn_frame = ttk.Frame(parent)
        btn_frame.place(x=40, y=365, width=200, height=150)
        
        # Buttons precisely matching the spacing/style
        ttk.Button(btn_frame, text="OK", width=22, command=self.on_ok).pack(pady=3)
        ttk.Button(btn_frame, text="Apply", width=22, command=self.on_apply).pack(pady=3)
        ttk.Button(btn_frame, text="Cancel", width=22, command=self.window.destroy).pack(pady=3)
        ttk.Button(btn_frame, text="Help", width=22).pack(pady=12)

    def show_basic_settings(self, current_username, current_group):
        # User name (Entry)
        u_frame = ttk.LabelFrame(self.right_col, text="User name")
        u_frame.place(x=0, y=0, width=190, height=65)
        self.user_var = tk.StringVar(value=current_username)
        u_entry = ttk.Entry(u_frame, textvariable=self.user_var)
        u_entry.pack(padx=10, pady=8, fill=tk.X)

        # Group name (Combobox)
        g_frame = ttk.LabelFrame(self.right_col, text="Group name")
        g_frame.place(x=205, y=0, width=115, height=65)
        self.group_var = tk.StringVar(value=current_group)
        self.group_combo = ttk.Combobox(g_frame, textvariable=self.group_var, values=[current_group])
        self.group_combo.pack(padx=10, pady=8, fill=tk.X)

        # Broadcast Setup frame
        bc_frame = ttk.LabelFrame(self.right_col, text="Broadcast Setup for different segments", padding=5)
        bc_frame.place(x=0, y=75, width=320, height=210)

        # Input box for BC addressing
        self.bc_input = ttk.Entry(bc_frame)
        self.bc_input.place(x=5, y=10, width=200)

        # Listbox for addresses
        self.bc_list = tk.Listbox(bc_frame, height=5, font=("Arial", 9), bd=1, relief=tk.SOLID)
        self.bc_list.place(x=215, y=10, width=90, height=120)
        
        # Label help
        ttk.Label(bc_frame, text="Ex) 192.168.0.255\n      (or FQDN)", font=("Arial", 9)).place(x=10, y=45)

        # Buttons >> and <<
        ttk.Button(bc_frame, text=">>", width=4).place(x=175, y=55)
        ttk.Button(bc_frame, text="<<", width=4).place(x=175, y=90)

        # Unicast required
        self.unicast_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bc_frame, text="Unicast required", variable=self.unicast_var).place(x=10, y=140)

        # Info line
        info_l = tk.Label(bc_frame, text="If Master Mode is setted, this setting is...", 
                         relief=tk.SUNKEN, bg="white", anchor=tk.W, padx=10, font=("Arial", 8))
        info_l.place(x=5, y=170, width=300, height=25)

        # Bottom row components
        # Local segment broadcast
        ttk.Label(self.right_col, text="Local segment\nbroadcast", font=("Arial", 9)).place(x=0, y=300)
        self.loc_bc_combo = ttk.Combobox(self.right_col, values=["Directed broadcast"])
        self.loc_bc_combo.set("Directed broadcast")
        self.loc_bc_combo.place(x=130, y=305, width=190)

        # IPv4/IPv6 Mode
        ttk.Label(self.right_col, text="IPv4/IPv6 Mode", font=("Arial", 9)).place(x=0, y=350)
        self.ip_mode_combo = ttk.Combobox(self.right_col, values=["IPv4 mode", "IPv6 mode", "Dual stack"])
        self.ip_mode_combo.set("IPv4 mode")
        self.ip_mode_combo.place(x=130, y=350, width=110)
        ttk.Label(self.right_col, text="(need restart)", font=("Arial", 8), foreground="gray").place(x=245, y=352)

        # Language section
        lang_frame = ttk.LabelFrame(self.right_col, text="Language")
        lang_frame.place(x=5, y=410, width=310, height=80)
        
        self.lang_combo = ttk.Combobox(lang_frame, values=["System/Auto", "English", "Japanese"])
        self.lang_combo.set("System/Auto")
        self.lang_combo.place(x=10, y=15, width=160)
        ttk.Label(lang_frame, text="(need restart)", font=("Arial", 8), foreground="gray").place(x=180, y=18)

    def on_apply(self):
        new_name = self.user_var.get().strip()
        new_group = self.group_var.get().strip()
        if hasattr(self.parent, 'apply_main_settings'):
            self.parent.apply_main_settings(new_name, new_group)

    def on_ok(self):
        self.on_apply()
        self.window.destroy()
