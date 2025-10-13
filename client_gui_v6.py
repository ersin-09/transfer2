import os, json, threading, time, socket, struct, urllib.request, urllib.parse, subprocess, tempfile, datetime, tkinter as tk
import http.client
from tkinter import ttk, messagebox
from tkinter.ttk import Progressbar
import concurrent.futures
import zipfile, shutil
import urllib.error
import math
import queue
import hashlib
import sys

from tkinter import font as tkfont

APP_TITLE = "Dosya Transferi v6 – Tam (Kısayol + Hızlı Tarama)"
DEFAULT_KEY = "1234"


class Tooltip:
    def __init__(self, widget, text, delay=500):
        self.widget, self.text, self.delay = widget, text, delay
        self._id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._unschedule)
        widget.bind("<ButtonPress>", self._unschedule)

    def _schedule(self, _):
        self._id = self.widget.after(self.delay, self._show)

    def _unschedule(self, _=None):
        if self._id:
            self.widget.after_cancel(self._id)
            self._id = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, bg="#ffffe0", relief="solid",
                 borderwidth=1, padx=6, pady=2).pack()
        self._tip = tw


class AppTab(tk.Frame):
    def __init__(self, master, shared):
        super().__init__(master)
        self.shared = shared if isinstance(shared, dict) else {}
        self._shared_lock = threading.Lock()
        # shared["key"], ["http_port"], ["tcp_port"], ["subnets"]
        host = self.winfo_toplevel()
        if isinstance(host, (tk.Tk, tk.Toplevel)):
            host.title(APP_TITLE)
            host.geometry("1220x740")
            host.minsize(980, 620)
        self.configure(bg="#f4f4f4")
        self._make_style()

        # ---- client_config.json ----
        self.ccfg = self._load_client_config()
        self.http_port = self.ccfg.get("preferred_http_port", 8088)
        self.tcp_port = self.ccfg.get("preferred_tcp_port", 5050)
        self.mcast_group = self.ccfg.get("listen_mcast_group", "239.0.0.250")
        self.mcast_port = self.ccfg.get("listen_mcast_port", 9999)
        self.progress_port = int(self.ccfg.get("progress_port", 6060))  # INT tut
        self.subnets = self.ccfg.get("subnets", ["192.168.1"])

        # Üst çubuk
        top = tk.Frame(self, bg="#f4f4f4")
        top.pack(fill="x", padx=12, pady=(10, 5))

        tk.Label(top, text="Alıcılar:", bg="#f4f4f4").pack(side="left")
        self.discovery_combo = ttk.Combobox(top, width=36, state="readonly")
        self.discovery_combo.pack(side="left", padx=(5, 12))
        self.discovery_combo.bind("<<ComboboxSelected>>", lambda e: self._pick_discovered())

        tk.Label(top, text="Sunucu IP:", bg="#f4f4f4").pack(side="left")
        self.ip_var = tk.StringVar(value="127.0.0.1")
        ttk.Entry(top, width=16, textvariable=self.ip_var).pack(side="left", padx=(5, 10))

        tk.Label(top, text="Anahtar:", bg="#f4f4f4").pack(side="left")
        self.key_var = tk.StringVar(value=DEFAULT_KEY)
        ttk.Entry(top, width=12, textvariable=self.key_var).pack(side="left", padx=(5, 12))

        self._make_auto_width_button(top, "Yenile", self.refresh_remote).pack(side="left", padx=(0, 6))
        self._make_auto_width_button(top, "TARA", self.discover_by_scan).pack(side="left", padx=(0, 6))

        btn_frame = tk.Frame(top, bg="#f4f4f4")
        btn_frame.pack(side="right", padx=(0, 5))
        self._make_auto_width_button(btn_frame, "Upload", self.do_upload).pack(side="left", padx=4)
        self._make_auto_width_button(btn_frame, "Download", self.do_download).pack(side="left", padx=4)
        self._make_auto_width_button(btn_frame, "Güncelle", self.update_server).pack(side="left", padx=4)

        # Yerel kısayollar (panelden ÖNCE hazırlanmalı)
        self.local_shortcuts_map = {}
        self._init_local_shortcuts()


        # Paneller
        mid = ttk.PanedWindow(self, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=12, pady=6)

        # Yerel panel
        self.local_cwd = os.path.expanduser("~\\Desktop")
        self.left = self._build_local_panel(mid)
        mid.add(self.left, weight=1)

        # Uzak panel
        self.remote_path = tk.StringVar()
        self.right = self._build_remote_panel(mid)
        mid.add(self.right, weight=1)
        self._remote_clipboard = None         # {"op": "copy"|"move", "paths": [abs1, abs2, ...]}
        self._remote_clipboard_src_dir = None # panonun alındığı klasör (bilgi amaçlı)


        # Durum çubuğu
        bottom = tk.Frame(self, bg="#f4f4f4")
        bottom.pack(fill="x", padx=12, pady=(6, 10))
        self.status = tk.StringVar(value="Hazır. Henüz sunucuya bağlanılmadı.")
        ttk.Label(bottom, textvariable=self.status).pack(side="left")
        self.pb = Progressbar(bottom, length=300, mode="determinate")
        self.pb.pack(side="right", padx=10)

        # --- 1.1 EKLENECEK YER: ProgressBar'dan HEMEN SONRA ---
        ctrl = tk.Frame(bottom, bg="#f4f4f4")
        ctrl.pack(side="right", padx=(0, 8))

        self.queue_info = tk.StringVar(value="Kuyruk: 0 iş")
        ttk.Label(ctrl, textvariable=self.queue_info).pack(side="right", padx=(10,0))

        self.btn_cancel = ttk.Button(ctrl, text="■", width=3, command=self._queue_cancel_current)
        self.btn_cancel.pack(side="right", padx=(6,0))

        self._paused = False
        self.btn_pause = ttk.Button(ctrl, text="⏸", width=3, command=self._queue_toggle_pause)
        self.btn_pause.pack(side="right", padx=(6,0))

        # Kuyruk veri yapıları
        self._job_queue = queue.Queue()
        self._queue_thread = threading.Thread(target=self._queue_loop, daemon=True)
        self._queue_thread.start()

        # Mevcut iş için kontrol bayrakları ve meta
        self._current_job_cancel = threading.Event()
        self._progress_meta = {"files_total": 0, "files_done": 0, "name": "", "last_sent": 0, "last_t": 0.0}
        # --- 1.1 BİTİŞ ---

        # State
        self.remote_abs = "C:\\"
        self.discovered = {}           # key "ip:tcp" -> {"ip":..., "tcpPort":..., "name":..., "last_seen":...}
        self.discovery_index = {}      # display -> {"ip":..., "tcpPort":...}
        self._shortcuts_loaded = False
        self.shortcuts_map = {}        # "Masaüstü" -> "C:\\Users\\...\\Desktop"
        self._remote_identity = None  # (ip, http_port, key) takibi
        self._remote_clipboard = None  # {"mode":"copy"|"cut", "items":[absolute paths]}


        # Yerel kısayollar
        self.local_shortcuts_map = {}
        self._init_local_shortcuts()

        self.refresh_local()
        # self.refresh_remote()  # açılışta otomatik bağlanma yok

        # Multicast dinleyici
        threading.Thread(target=self._mcast_listener_loop, daemon=True).start()

        # Diğer sekmelerle (Finder) otomatik keşif sonuçlarını paylaş
        self._publish_shared_discovery(initial=True)


    def _current_remote_identity(self):
        return (self.ip_var.get().strip(), self.http_port, self.key_var.get().strip())

        # ===== Kuyruk kontrol =====
    def _queue_toggle_pause(self):
        self._paused = not self._paused
        self.btn_pause.config(text=("▶" if self._paused else "⏸"))
        self.status.set("DURAKLATILDI" if self._paused else "Devam ediyor...")

    def _queue_cancel_current(self):
        self._current_job_cancel.set()
        self.status.set("İptal istendi...")

    def _enqueue_upload(self, items):
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("Uyarı", "Sunucu IP boş!")
            return
        job = {
            "type": "upload",
            "ip": ip,
            "remote_abs": self.remote_abs,
            "items": items,
        }
        self._job_queue.put(job)
        self._update_queue_info()

  
    def _queue_loop(self):
        while True:
            job = self._job_queue.get()
            self._current_job_cancel.clear()
            try:
                # Eski biçimle (("upload", items)) geldiyse dict'e dönüştür
                if isinstance(job, tuple):
                    kind, items = job
                    if kind == "upload":
                        job = {
                            "type": "upload",
                            "ip": self.ip_var.get().strip(),
                            "remote_abs": self.remote_abs,
                            "items": items,
                        }

                if job.get("type") == "upload":
                    self._run_upload_job(job)
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Yükleme", err))
            finally:
                self._update_queue_info()
                self._job_queue.task_done()



    # ---------- Tema ----------
    def _make_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", rowheight=22)
        s.configure("TFrame", background="#f4f4f4")
        # Yazı boyutunu değiştirmeden dar buton stili
        s.configure("AutoWidth.TButton", padding=(2, 0), borderwidth=1)

    # --- Buton genişliği: metin kadar ---
    def _make_auto_width_button(self, parent, text, command, style="AutoWidth.TButton"):
        """
        Yazı tipini değiştirmeden, butonun metin kadar geniş olmasını sağlar.
        ttk.Button üzerinde -font yok; fontu style'dan okuruz.
        """
        btn = ttk.Button(parent, text=text, command=command, style=style)

        # Stil üzerinden fontu bul (yoksa TButton, yoksa TkDefaultFont)
        s = ttk.Style(self)
        font_name = s.lookup(style, "font") or s.lookup("TButton", "font") or "TkDefaultFont"
        try:
            fnt = tkfont.nametofont(font_name)
        except Exception:
            fnt = tkfont.nametofont("TkDefaultFont")

        # Metni piksel olarak ölç, karakter birimine çevirip width belirle
        char_px = max(1, fnt.measure("0"))
        text_px = fnt.measure(text)
        width_chars = max(1, math.ceil(text_px / char_px))
        btn.configure(width=width_chars)

        return btn


    # ---------- Config ----------
    def _app_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def _load_client_config(self):
        try:
            here = self._app_dir()
            with open(os.path.join(here, "client_config.json"), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_client_config(self):
        try:
            here = self._app_dir()
            path = os.path.join(here, "client_config.json")
            temp = os.path.join(here, "client_config.tmp.json")
            data = dict(self.ccfg)  # shallow copy
            # favoriler kalıcı kalsın
            favs = []
            for label, p in self.local_shortcuts_map.items():
                if label.startswith("⭐ "):  # sadece kullanıcı eklediklerini yaz
                    if os.path.isdir(p):
                        favs.append(p)
            data["local_favorites"] = favs
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp, path)
        except Exception as e:
            print("client_config yazma hatası:", e)

    # ---------- Yerel panel ----------
    def _build_local_panel(self, parent):
        frm = tk.Frame(parent, bg="#ffffff", bd=1, relief="solid")

        # Başlık
        head = tk.Frame(frm, bg="#ffffff")
        head.pack(fill="x", padx=8, pady=6)
        tk.Label(head, text="Yerel (Bu Bilgisayar)", bg="#ffffff",
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        # Yol çubuğu
        pathbar = tk.Frame(frm, bg="#f4f4f4")
        pathbar.pack(fill="x", padx=8, pady=(0, 6))

        tk.Label(pathbar, text="Yol:", bg="#f4f4f4").pack(side="left")
        self.local_path = tk.StringVar(value=self.local_cwd)
        ttk.Entry(pathbar, textvariable=self.local_path).pack(side="left", fill="x", expand=True, padx=5)

        # DAR – metin kadar geniş butonlar
        btn_go = self._make_auto_width_button(pathbar, "Git", self.local_go)
        btn_up = self._make_auto_width_button(pathbar, "↑", self.local_up)
        btn_mk = self._make_auto_width_button(pathbar, "+", self.local_mkdir)
        btn_del = self._make_auto_width_button(pathbar, "X", self.local_delete)
        for b in (btn_go, btn_up, btn_mk, btn_del):
            b.pack(side="left", padx=(6, 0))

        # Yerel kısayol combobox + favori ekle (⭐)
        tk.Label(pathbar, text="Kısayol:", bg="#f4f4f4").pack(side="left", padx=(10, 0))
        self.local_shortcut_var = tk.StringVar()
        self.local_shortcut_combo = ttk.Combobox(pathbar, width=28, state="readonly",
                                                 textvariable=self.local_shortcut_var)
        self.local_shortcut_combo.pack(side="left", padx=(4, 0))
        self.local_shortcut_combo.bind("<<ComboboxSelected>>", lambda e: self._local_use_shortcut())

        btn_star = self._make_auto_width_button(pathbar, "⭐", self._add_local_favorite)
        btn_star.pack(side="left", padx=(6, 0))

        # İlk yüklemede kısayolları doldur
        self._populate_local_shortcuts()

        # Liste
        cols = ("name", "size", "mtime")
        self.local_tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="extended")
        for c, t, w, a in zip(cols, ["Ad", "Boyut", "Tarih"], [320, 90, 150], ["w", "e", "center"]):
            self.local_tv.heading(c, text=t)
            self.local_tv.column(c, width=w, anchor=a)
        self.local_tv.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.local_tv.bind("<Double-1>", self.local_open)
        self.local_tv.bind("<Button-3>", self._local_context_menu)   # sağ tık


                # Dahili sürükle-bırak (local -> remote)
        self.local_tv.bind("<ButtonPress-1>", self._dnd_start_local)
        self.local_tv.bind("<B1-Motion>", self._dnd_motion_local)
        self.local_tv.bind("<ButtonRelease-1>", self._dnd_drop_local)
        self._dnd_dragging = False
        self._dnd_label = None
        self._dnd_origin_xy = (0, 0)


        frm.pack(fill="both", expand=True)
        return frm


    def _dnd_start_local(self, e):
        self._dnd_origin_xy = (e.x_root, e.y_root)
        self._dnd_dragging = False

    def _dnd_motion_local(self, e):
        dx = abs(e.x_root - self._dnd_origin_xy[0])
        dy = abs(e.y_root - self._dnd_origin_xy[1])
        if not self._dnd_dragging and (dx > 6 or dy > 6):
            self._dnd_dragging = True
            # küçük sürükleme etiketi
            self._dnd_label = tk.Toplevel(self)
            self._dnd_label.wm_overrideredirect(True)
            tk.Label(self._dnd_label, text="Yüklemek için bırak", bg="#333", fg="#fff", padx=6, pady=3).pack()
        if self._dnd_dragging and self._dnd_label:
            self._dnd_label.geometry(f"+{e.x_root+10}+{e.y_root+10}")

    def _dnd_drop_local(self, e):
        if self._dnd_label:
            try: self._dnd_label.destroy()
            except Exception: pass
            self._dnd_label = None

        if not self._dnd_dragging:
            return

        # Bırakma hedefi remote_tv mi?
        rx, ry = self.remote_tv.winfo_rootx(), self.remote_tv.winfo_rooty()
        rw, rh = self.remote_tv.winfo_width(), self.remote_tv.winfo_height()
        inside = (rx <= e.x_root <= rx+rw) and (ry <= e.y_root <= ry+rh)
        if not inside:
            return

        # Seçili yerel öğelerin tam yollarını topla ve do_upload(paths=...) ile kuyruğa ekle
        sels = self.local_tv.selection()
        if not sels:
            return
        abs_paths = []
        for s in sels:
            name = self.local_tv.item(s, "values")[0]
            abs_paths.append(os.path.join(self.local_cwd, name))

        self.do_upload(paths=abs_paths)
        self.status.set(f"Kuyruğa eklendi: {len(abs_paths)} öğe")


    def _refresh_local_shortcuts_values(self):
        order = list(self.local_shortcuts_map.keys())
        self.local_shortcut_combo["values"] = order

    def _init_local_shortcuts(self):
        """Yerel (Bu Bilgisayar) için kısayolları doldurur."""
        m = {}

        def add(label, path):
            if path and os.path.isdir(path):
                m[label] = path

        home = os.path.expanduser("~")
        add("Masaüstü", os.path.join(home, "Desktop"))
        add("Belgeler", os.path.join(home, "Documents"))
        add("İndirilenler", os.path.join(home, "Downloads"))
        add("Resimler", os.path.join(home, "Pictures"))
        add("Müzik", os.path.join(home, "Music"))
        add("Videolar", os.path.join(home, "Videos"))

        # Sürücüler (C:\, D:\, ...)
        for ch in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{ch}:\\"
            if os.path.isdir(root):
                add(root, root)

        # Kullanıcı favorileri (client_config.json → local_favorites)
        favs = self.ccfg.get("local_favorites", [])
        for p in favs:
            if os.path.isdir(p):
                label = "⭐ " + os.path.basename(os.path.normpath(p))
                if label in m:
                    label = f"⭐ {os.path.basename(os.path.dirname(p))}\\{os.path.basename(p)}"
                m[label] = p

        self.local_shortcuts_map = m
        if hasattr(self, "local_shortcut_combo"):
            self._refresh_local_shortcuts_values()

    def _populate_local_shortcuts(self):
        """Combobox değerlerini doldur (başlangıç ve favori ekleme sonrası)."""
        self._refresh_local_shortcuts_values()

    def _add_local_favorite(self):
        """Mevcut local_cwd'yi favorilere ekler ve kalıcı kaydeder."""
        p = self.local_cwd
        if not os.path.isdir(p):
            messagebox.showwarning("Favori", "Geçerli bir klasör yok.")
            return
        label = "⭐ " + os.path.basename(os.path.normpath(p))
        if label in self.local_shortcuts_map and self.local_shortcuts_map[label] == p:
            messagebox.showinfo("Favori", "Bu klasör zaten favorilerde.")
            return
        base_label = label
        i = 2
        while label in self.local_shortcuts_map and self.local_shortcuts_map[label] != p:
            label = f"{base_label} ({i})"
            i += 1
        self.local_shortcuts_map[label] = p
        self._refresh_local_shortcuts_values()
        self._save_client_config()
        messagebox.showinfo("Favori", f"Eklendi: {label}")

    def refresh_local(self):
        self.local_path.set(self.local_cwd)
        tv = self.local_tv
        for i in tv.get_children():
            tv.delete(i)
        try:
            with os.scandir(self.local_cwd) as it:
                # Klasörler üstte, alfabetik
                entries = sorted(it, key=lambda e: (e.is_file(), e.name.lower()))
                for e in entries:
                    try:
                        st = e.stat(follow_symlinks=False)
                        # KB olarak boyut (klasör için boş)
                        size = "" if e.is_dir() else f"{st.st_size // 1024} KB"
                        # Son değişiklik zamanı
                        mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        size = "" if e.is_dir() else "?"
                        mtime = ""
                    tv.insert(
                        "",
                        "end",
                        values=(e.name, size, mtime),
                        tags=("dir",) if e.is_dir() else ()
                    )
        except Exception as ex:
            messagebox.showerror("Yerel listeleme", str(ex))


    def local_open(self, _):
        sel = self.local_tv.focus()
        if not sel:
            return
        name = self.local_tv.item(sel, "values")[0]
        newp = os.path.join(self.local_cwd, name)
        if os.path.isdir(newp):
            self.local_cwd = newp
            self.refresh_local()

    def local_up(self):
        up = os.path.dirname(self.local_cwd)
        if up and os.path.isdir(up):
            self.local_cwd = up
            self.refresh_local()

    def local_go(self):
        """Yol girişindeki klasöre git."""
        p = (self.local_path.get() or "").strip()
        if not p:
            return
        if os.path.isdir(p):
            self.local_cwd = p
            self.refresh_local()
        else:
            messagebox.showerror("Yerel Gezinme", f"Geçersiz klasör:\n{p}")

    def local_mkdir(self):
        """Geçerli yerel klasörde yeni klasör oluştur."""
        import tkinter.simpledialog as sd
        name = sd.askstring("Yeni klasör", "Klasör adı:")
        if not name:
            return
        target = os.path.join(self.local_cwd, name)
        try:
            os.makedirs(target, exist_ok=True)
            self.refresh_local()
        except Exception as e:
            messagebox.showerror("Klasör oluşturma (yerel)", str(e))

    def local_delete(self):
        """Seçili yerel dosya/klasörü sil."""
        sel = self.local_tv.focus()
        if not sel:
            messagebox.showwarning("Uyarı", "Soldan silmek için bir öğe seçin.")
            return
        name = self.local_tv.item(sel, "values")[0]
        target = os.path.join(self.local_cwd, name)
        if not messagebox.askyesno("Sil", f"Silinsin mi?\n{target}"):
            return
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
            self.refresh_local()
        except Exception as e:
            messagebox.showerror("Silme (yerel)", str(e))

    def _local_use_shortcut(self):
        """Kısayol seçildiğinde yerel paneli o konuma götürür."""
        label = getattr(self, "local_shortcut_var", tk.StringVar()).get()
        p = getattr(self, "local_shortcuts_map", {}).get(label)
        if p and os.path.isdir(p):
            self.local_cwd = p
            self.refresh_local()

    def _remote_selected_abs_paths(self):
        paths = []
        for iid in self.remote_tv.selection():
            name = self.remote_tv.item(iid, "values")[0]
            paths.append(os.path.join(self.remote_abs, name))
        return paths

    def _remote_base(self):
        return f"http://{self.ip_var.get().strip()}:{self.http_port}"

    def _http_open(self, url, timeout=5):
        return urllib.request.urlopen(url, timeout=timeout)

    def _show_http_error(self, title, err: Exception):
        if isinstance(err, urllib.error.HTTPError):
            try:
                body = err.read().decode("utf-8", errors="ignore")
            except Exception:
                body = str(err)
            messagebox.showerror(title, f"{err}\n\n{body}")
        else:
            messagebox.showerror(title, str(err))


    # ---------- Uzak panel ----------
    def _build_remote_panel(self, parent):
        frm = tk.Frame(parent, bg="#ffffff", bd=1, relief="solid")
        head = tk.Frame(frm, bg="#ffffff")
        head.pack(fill="x", padx=8, pady=6)
        tk.Label(head, text="Uzak (Sunucu)", bg="#ffffff", font=("Segoe UI", 10, "bold")).pack(side="left")

        pathbar = tk.Frame(frm, bg="#f4f4f4")
        pathbar.pack(fill="x", padx=8, pady=(0, 6))
        tk.Label(pathbar, text="Yol:", bg="#f4f4f4").pack(side="left")
        ttk.Entry(pathbar, textvariable=self.remote_path).pack(side="left", fill="x", expand=True, padx=5)

        btn_go = self._make_auto_width_button(pathbar, "Git", self.remote_go)
        btn_up = self._make_auto_width_button(pathbar, "↑", self.remote_up)
        btn_mk = self._make_auto_width_button(pathbar, "+", self.remote_mkdir)
        btn_del = self._make_auto_width_button(pathbar, "X", self.remote_delete)
        for b in (btn_go, btn_up, btn_mk, btn_del):
            b.pack(side="left", padx=(10, 0))

        # Kısayol combobox
        tk.Label(pathbar, text="Kısayol:", bg="#f4f4f4").pack(side="left", padx=(10, 0))
        self.shortcut_var = tk.StringVar()
        self.shortcut_combo = ttk.Combobox(pathbar, width=28, state="readonly", textvariable=self.shortcut_var)
        self.shortcut_combo.pack(side="left", padx=(4, 0))
        self.shortcut_combo.bind("<<ComboboxSelected>>", lambda e: self._use_shortcut())
        # _build_remote_panel içinde, combobox'tan hemen sonra
        btn_sc = ttk.Button(pathbar, text="↻", command=self._force_reload_shortcuts)
        btn_sc.pack(side="left", padx=(4,0))


        cols = ("name", "size", "mtime", "type")
        self.remote_tv = ttk.Treeview(frm, columns=cols, show="headings", selectmode="extended")
        for c, t, w, a in zip(cols, ["Ad", "Boyut", "Tarih", "Tür"], [320, 90, 150, 60], ["w", "e", "center", "center"]):
            self.remote_tv.heading(c, text=t)
            self.remote_tv.column(c, width=w, anchor=a)
        self.remote_tv.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.remote_tv.bind("<Double-1>", self.remote_open)
        self.remote_tv.bind("<Button-3>", self._remote_context_menu) # sağ tık

        frm.pack(fill="both", expand=True)
        return frm


        # ---------- Local context menu ----------
    def _local_context_menu(self, e):
        iid = self.local_tv.identify_row(e.y)
        if iid:
            self.local_tv.selection_set(iid)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Yeniden Adlandır", command=self._local_rename)
        menu.add_separator()
        menu.add_command(label="Kes", command=lambda: self._local_clip("cut"))
        menu.add_command(label="Kopyala", command=lambda: self._local_clip("copy"))
        menu.add_command(label="Yapıştır", command=self._local_paste)
        menu.add_separator()
        menu.add_command(label="Özellikler", command=self._local_props)
        menu.tk_popup(e.x_root, e.y_root)

    def _local_rename(self):
        sel = self.local_tv.focus()
        if not sel: return
        old = self.local_tv.item(sel, "values")[0]
        oldp = os.path.join(self.local_cwd, old)
        import tkinter.simpledialog as sd
        new = sd.askstring("Yeniden Adlandır", "Yeni ad:", initialvalue=old)
        if not new or new == old: return
        newp = os.path.join(self.local_cwd, new)
        try:
            os.rename(oldp, newp)
            self.refresh_local()
        except Exception as ex:
            messagebox.showerror("Yeniden Adlandır", str(ex))

    def _local_clip(self, kind):
        sels = self.local_tv.selection()
        if not sels:
            return
        paths = []
        for s in sels:
            name = self.local_tv.item(s, "values")[0]
            paths.append(os.path.join(self.local_cwd, name))
        self._local_clipboard = {"action": kind, "paths": paths}
        self.status.set(f"{kind.upper()} – {len(paths)} öğe")

    def _local_paste(self):
        clip = getattr(self, "_local_clipboard", None)
        if not clip: return
        action = clip["action"]
        paths  = clip["paths"]
        for p in paths:
            base = os.path.basename(p.rstrip("\\/"))
            dst  = os.path.join(self.local_cwd, base)
            try:
                if action == "copy":
                    if os.path.isdir(p):
                        shutil.copytree(p, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(p, dst)
                else:  # cut
                    shutil.move(p, dst)
            except Exception as ex:
                messagebox.showerror("Yapıştır", f"{base}\n{ex}")
                break
        self.refresh_local()

    def _local_props(self):
        sel = self.local_tv.focus()
        if not sel: return
        name = self.local_tv.item(sel, "values")[0]
        p = os.path.join(self.local_cwd, name)

        top = tk.Toplevel(self)
        top.title("Özellikler – " + name)
        top.resizable(False, False)
        tk.Label(top, text=p, wraplength=480, justify="left").pack(anchor="w", padx=12, pady=(10,6))

        info = []
        try:
            st = os.stat(p, follow_symlinks=False)
            info.append(("Boyut", (f"{st.st_size/1024/1024:.2f} MB" if os.path.isfile(p) else "—")))
            info.append(("Değiştirme", datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")))
        except Exception:
            pass

        rows = tk.Frame(top); rows.pack(fill="x", padx=12, pady=6)
        for k,v in info:
            r = tk.Frame(rows); r.pack(fill="x")
            tk.Label(r, text=k+":", width=12, anchor="w").pack(side="left")
            tk.Label(r, text=v, anchor="w").pack(side="left")

        # Klasörse toplam boyutu arka planda hesapla
        if os.path.isdir(p):
            sz_var = tk.StringVar(value="Hesaplanıyor...")
            r = tk.Frame(rows); r.pack(fill="x")
            tk.Label(r, text="Toplam:", width=12, anchor="w").pack(side="left")
            tk.Label(r, textvariable=sz_var, anchor="w").pack(side="left")
            def calc():
                total = 0
                for root,_,files in os.walk(p):
                    for fn in files:
                        try: total += os.path.getsize(os.path.join(root, fn))
                        except Exception: pass
                self.after(0, lambda: sz_var.set(f"{total/1024/1024:.2f} MB"))
            threading.Thread(target=calc, daemon=True).start()

        ttk.Button(top, text="Kapat", command=top.destroy).pack(pady=(6,10))

    def _ui_error(self, title: str, exc: Exception):
        msg = str(exc)
        self.after(0, lambda t=title, m=msg: messagebox.showerror(t, m))

    def _ui_info(self, title: str, text: str):
        self.after(0, lambda t=title, s=text: messagebox.showinfo(t, s))

    def _ui_status(self, text: str):
        self.after(0, lambda s=text: self.status.set(s))

    def _ui_progress(self, value: float):
        self.after(0, lambda v=value: self.pb.configure(value=v))


    # ---------- Remote context menu ----------
    def _remote_context_menu(self, event):
        try:
            iid = self.remote_tv.identify_row(event.y)
            if iid:
                # tıklanan satırı seçime dahil et
                if iid not in self.remote_tv.selection():
                    self.remote_tv.selection_set(iid)
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label="Kopyala", command=self._remote_copy)
            menu.add_command(label="Kes", command=self._remote_cut)
            menu.add_command(label="Yapıştır", command=self._remote_paste)
            menu.add_separator()
            menu.add_command(label="Yeniden Adlandır", command=self._remote_rename)
            menu.add_separator()
            menu.add_command(label="Özellikler", command=self._remote_props)
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            except: pass

    def _remote_rename_stub(self):
        """Seçili uzak öğeyi sunucuda yeniden adlandırır (/api/rename)."""
        rfile = self.get_remote_file()
        if not rfile:
            messagebox.showwarning("Yeniden Adlandır", "Sağdan bir dosya/klasör seçin.")
            return

        if not self._server_supports("rename"):
            messagebox.showinfo("Yeniden Adlandır", "Sunucu 'rename' özelliğini bildirmiyor.")
            return

        import tkinter.simpledialog as sd
        curr_name = os.path.basename(rfile)
        newname = sd.askstring("Yeniden Adlandır", "Yeni ad:", initialvalue=curr_name)
        if not newname or newname == curr_name:
            return

        base = self._base_url()
        q = urllib.parse.urlencode({"abs": rfile, "newname": newname, "key": self.key_var.get()})
        try:
            urllib.request.urlopen(f"{base}/api/rename?{q}", timeout=20).read()
            self.status.set(f"Yeniden adlandırıldı: {curr_name} → {newname}")
            self.refresh_remote()
        except urllib.error.HTTPError as e:
            try: body = e.read().decode("utf-8", errors="ignore")
            except Exception: body = str(e)
            messagebox.showerror("Yeniden Adlandır", f"{e}\n\n{body}")
        except Exception as e:
            messagebox.showerror("Yeniden Adlandır", str(e))


    def _remote_copy_move_stub(self):
        """Uzak panodaki öğeleri mevcut uzak dizine kopyala/taşı (/api/copy|/api/move)."""
        clip = getattr(self, "_remote_clip", None)
        if not clip or not clip.get("items"):
            messagebox.showinfo("Uzak Kes/Kopyala/Yapıştır", "Panoda öğe yok.")
            return

        mode = clip.get("mode", "copy")
        if mode == "copy" and not self._server_supports("copy"):
            messagebox.showinfo("Uzak Yapıştır", "Sunucu 'copy' özelliğini bildirmiyor.")
            return
        if mode == "cut" and not self._server_supports("move"):
            messagebox.showinfo("Uzak Yapıştır", "Sunucu 'move' özelliğini bildirmiyor.")
            return

        base = self._base_url()
        key = self.key_var.get()
        dst_dir = self.remote_abs

        ok_all = True
        for src in clip["items"]:
            params = {
                "src": src,
                "dst": dst_dir,   # klasör ise içine kopyalar/taşır
                "ensure": "1",    # gerekiyorsa ara klasörleri oluştur
                "overwrite": "0", # var ise hata ver
                "key": key,
            }
            url = f"{base}/api/{'copy' if mode=='copy' else 'move'}?{urllib.parse.urlencode(params)}"
            try:
                urllib.request.urlopen(url, timeout=60).read()
            except urllib.error.HTTPError as e:
                try: body = e.read().decode("utf-8", errors="ignore")
                except Exception: body = str(e)
                messagebox.showerror("Uzak Yapıştır", f"{e}\n\n{body}")
                ok_all = False
                break
            except Exception as e:
                messagebox.showerror("Uzak Yapıştır", str(e))
                ok_all = False
                break

        if ok_all:
            if mode == "cut":
                # taşıma tamamlandıysa pano temizlenir
                self._remote_clip = None
            self.status.set("Uzak yapıştır tamamlandı.")
            self.refresh_remote()

    def remote_copy_selected(self):
        sels = self.remote_tv.selection()
        if not sels:
            messagebox.showinfo("Kopyala", "Sağdan en az bir öğe seçin.")
            return
        items = []
        for s in sels:
            name = self.remote_tv.item(s, "values")[0]
            items.append(os.path.join(self.remote_abs, name))
        self._remote_clip = {"mode": "copy", "items": items}
        self.status.set(f"Panoya kopyalandı: {len(items)} öğe")

    def remote_cut_selected(self):
        sels = self.remote_tv.selection()
        if not sels:
            messagebox.showinfo("Kes", "Sağdan en az bir öğe seçin.")
            return
        items = []
        for s in sels:
            name = self.remote_tv.item(s, "values")[0]
            items.append(os.path.join(self.remote_abs, name))
        self._remote_clip = {"mode": "cut", "items": items}
        self.status.set(f"Panoya kesildi: {len(items)} öğe")

    def _remote_copy(self):
        paths = self._remote_selected_abs_paths()
        if not paths:
            messagebox.showinfo("Kopyala", "Sağdan bir veya daha çok öğe seç.")
            return
        self._remote_clipboard = {"op": "copy", "paths": paths}
        self._remote_clipboard_src_dir = self.remote_abs
        self.status.set(f"Panoya kopyalandı: {len(paths)} öğe")

    def _remote_cut(self):
        paths = self._remote_selected_abs_paths()
        if not paths:
            messagebox.showinfo("Kes", "Sağdan bir veya daha çok öğe seç.")
            return
        self._remote_clipboard = {"op": "move", "paths": paths}
        self._remote_clipboard_src_dir = self.remote_abs
        self.status.set(f"Panoya kes: {len(paths)} öğe")

    def _remote_paste(self):
        clip = self._remote_clipboard
        if not clip or not clip.get("paths"):
            messagebox.showinfo("Yapıştır", "Panoda öğe yok.")
            return
        op = clip.get("op")
        srcs = clip.get("paths")
        dst_dir = self.remote_abs   # şu an açık olan klasör
        base = self._remote_base()
        key = self.key_var.get().strip()

        ok_all = True
        for src in srcs:
            try:
                q = urllib.parse.urlencode({
                    "key": key,
                    "src": src,
                    "dst": dst_dir,
                    "ensure": "1",      # yoksa oluştur
                    # "overwrite": "0", # istersen ekleyebilirsin
                })
                if op == "copy":
                    url = f"{base}/api/copy?{q}"
                else:
                    url = f"{base}/api/move?{q}"
                with self._http_open(url, timeout=15) as r:
                    _ = r.read()
            except Exception as e:
                ok_all = False
                self._show_http_error("Yapıştır", e)
                break

        self.refresh_remote()
        if ok_all and op == "move":
            # taşımada pano temizlenir (Windows davranışı gibi)
            self._remote_clipboard = None
        if ok_all:
            self.status.set("Yapıştırma tamamlandı")

    def _remote_rename(self):
        sels = self.remote_tv.selection()
        if len(sels) != 1:
            messagebox.showinfo("Yeniden Adlandır", "Tek bir öğe seç.")
            return
        old_name = self.remote_tv.item(sels[0], "values")[0]
        old_abs = os.path.join(self.remote_abs, old_name)

        import tkinter.simpledialog as sd
        new_name = sd.askstring("Yeniden Adlandır", "Yeni ad:", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return

        base = self._remote_base()
        key = self.key_var.get().strip()
        try:
            q = urllib.parse.urlencode({"key": key, "abs": old_abs, "newname": new_name})
            with self._http_open(f"{base}/api/rename?{q}", timeout=15) as r:
                _ = r.read()
            self.refresh_remote()
            self.status.set("Yeniden adlandırıldı")
        except Exception as e:
            self._show_http_error("Yeniden Adlandır", e)

    def _remote_props(self):
        sels = self.remote_tv.selection()
        if not sels:
            return
        lines = []
        for iid in sels:
            vals = self.remote_tv.item(iid, "values")
            name, size, mtime, typ = vals
            lines.append(f"{name}\n  Tür: {typ}\n  Boyut: {size}\n  Tarih: {mtime}")
        messagebox.showinfo("Özellikler", "\n\n".join(lines))



    def _remote_props(self):
        items = self._remote_selected_items() if hasattr(self, "_remote_selected_items") else []
        if not items:
            messagebox.showwarning("Özellikler", "Sağdan bir öğe seç.")
            return
        it = items[0]
        name = it["name"]
        typ  = it["type"]
        # mtime/size zaten listede gösteriliyor; burada basit bir pencere açalım
        top = tk.Toplevel(self)
        top.title("Özellikler – " + name)
        top.resizable(False, False)
        tk.Label(top, text=os.path.join(self.remote_abs, name), wraplength=480, justify="left").pack(anchor="w", padx=12, pady=(10,6))
        rows = tk.Frame(top); rows.pack(fill="x", padx=12, pady=6)
        tk.Label(rows, text="Tür:", width=12, anchor="w").pack(side="left")
        tk.Label(rows, text=("Klasör" if typ=="dir" else "Dosya"), anchor="w").pack(side="left")
        ttk.Button(top, text="Kapat", command=top.destroy).pack(pady=(6,10))



    def _remote_selected_items(self):
        """Uzak panelde seçilen öğeleri listeler."""
        items = []
        for iid in self.remote_tv.selection():
            vals = self.remote_tv.item(iid, "values")
            if not vals:
                continue
            name = vals[0]
            typ  = vals[3] if len(vals) >= 4 else ""
            items.append({
                "name": name,
                "type": typ,
                "abs": os.path.join(self.remote_abs, name),
            })
        return items
    
    def _server_supports(self, feature: str) -> bool:
        if not hasattr(self, "_server_features"):
            self._server_features = None
        if self._server_features is None:
            try:
                base = self._base_url()
                k = urllib.parse.urlencode({"key": self.key_var.get()})
                with urllib.request.urlopen(f"{base}/api/features?{k}", timeout=2) as r:
                    self._server_features = json.loads(r.read().decode())
            except Exception:
                self._server_features = {}
        return bool(self._server_features.get(feature))

    


    # ---------- Hızlı subnet tarama ----------
    def discover_by_scan(self):
        self.status.set("Subnetler hızlı taranıyor...")
        found = []
        key = self.key_var.get()

        def check_ip(ip):
            url = f"http://{ip}:{self.http_port}/api/roots?key={key}"
            try:
                with urllib.request.urlopen(url, timeout=0.35) as r:
                    if r.status == 200:
                        return ip
            except:
                return None

        def scan_worker():
            with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
                futures = []
                for base in self.subnets:
                    # "192.168.1" ya da "192.168.1.10-50" formatı
                    if "-" in base:
                        prefix, rng = base.rsplit(".", 1)
                        start, end = rng.split("-")
                        start, end = int(start), int(end)
                        for last in range(start, end + 1):
                            ip = f"{prefix}.{last}"
                            futures.append(ex.submit(check_ip, ip))
                    else:
                        for last in range(1, 255):
                            ip = f"{base}.{last}"
                            futures.append(ex.submit(check_ip, ip))
                for f in concurrent.futures.as_completed(futures):
                    ip = f.result()
                    if ip:
                        found.append(ip)
                        # keşfi kalıcı listeye ekle (isim yoksa ip kullan)
                        # discover_by_scan -> scan_worker içinde, found eklerken:
                        k = f"{ip}:{self.tcp_port}"
                        self.discovered[k] = {
                            "ip": ip,
                            "tcpPort": self.tcp_port,
                            "httpPort": self.http_port,   # eldeki port (announce gelince doğruya güncellenecek)
                            "name": ip,
                            "last_seen": time.time()
                        }
                        self.after(0, self._update_discovery_combo)

            msg = f"Taramada {len(found)} sunucu bulundu."
            self.status.set(msg)

            # Bulunan her alıcıya kendi IP'mizi gönder ve kaydettir
            try:
                for _ip in list(found):
                    _ = self._send_my_ip_to(_ip)
                self.status.set(msg + " | IP gönderildi.")
            except Exception:
                pass

            if found:
                messagebox.showinfo("Tarama tamamlandı", msg + "\n" + "\n".join(found))
            else:
                messagebox.showinfo("Tarama tamamlandı", msg)

        threading.Thread(target=scan_worker, daemon=True).start()

    # ---------- Yardımcılar: Kendi IP ve gönderim ----------
    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
            finally:
                s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"

    def _send_my_ip_to(self, target_ip: str) -> bool:
        """
        transfer_client_v6.exe ile sunucunun ÇALIŞMA DİZİNİNE sender_<ip>.txt yükler.
        """
        try:
            my_ip = self._get_local_ip()
            content = f"{my_ip} | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            tmpdir = tempfile.gettempdir()
            fname = f"sender_{my_ip.replace(':','-')}.txt"
            fpath = os.path.join(tmpdir, fname)

            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)

            exe = "transfer_client_v6.exe"
            remote_dir = "."  # Sunucunun çalışma dizini

            try:
                done_evt = threading.Event()
                threading.Thread(
                    target=self._listen_progress,
                    args=(self.progress_port, done_evt),
                    daemon=True
                ).start()

                p = subprocess.Popen([
                    exe,
                    target_ip,
                    str(self.tcp_port),
                    fpath,
                    str(self.progress_port),
                    remote_dir
                ])
                rc = p.wait()
                # kısa bir süre progress'in kapanmasını bekle
                done_evt.wait(timeout=1.5)
                return rc == 0
            except Exception:
                return False
        except Exception:
            return False

    # ---------- Uzak gezinme yardımcıları ----------
    def get_remote_file(self):
        sel = self.remote_tv.focus()
        if not sel:
            return None
        vals = self.remote_tv.item(sel, "values")
        return os.path.join(self.remote_abs, vals[0])

    def remote_open(self, _):
        sel = self.remote_tv.focus()
        if not sel:
            return
        vals = self.remote_tv.item(sel, "values")
        if len(vals) >= 4 and vals[3] == "dir":
            self.remote_abs = os.path.join(self.remote_abs, vals[0])
            self.refresh_remote()

    def remote_up(self):
        up = os.path.dirname(self.remote_abs)
        if up:
            self.remote_abs = up
            self.refresh_remote()

    def remote_go(self):
        p = self.remote_path.get().strip()
        if not p:
            return
        self.remote_abs = p
        self.refresh_remote()

    def _use_shortcut(self):
        label = self.shortcut_var.get()
        p = self.shortcuts_map.get(label)
        if p:
            self.remote_abs = p
            self.refresh_remote()

    def remote_paste(self):
        clip = getattr(self, "_remote_clip", None)  # {"mode": "copy"|"cut", "items": [abs1, abs2,...]}
        if not clip or not clip.get("items"):
            messagebox.showinfo("Uzak Kes/Kopyala/Yapıştır", "Panoda öğe yok.")
            return

        base = self._base_url()
        ipkey = urllib.parse.urlencode({"key": self.key_var.get()})
        dst_dir = self.remote_abs
        mode = clip.get("mode", "copy")

        if mode == "copy" and not self._server_supports("copy"):
            messagebox.showinfo("Uzak Kes/Kopyala/Yapıştır", "Sunucu copy desteklemiyor.")
            return
        if mode == "cut" and not self._server_supports("move"):
            messagebox.showinfo("Uzak Kes/Kopyala/Yapıştır", "Sunucu move desteklemiyor.")
            return

        ok_all = True
        for src in clip["items"]:
            q = {
                "src": src,
                "dst": dst_dir,
                "ensure": "1",
                "overwrite": "0",
                "key": self.key_var.get(),
            }
            try:
                if mode == "copy":
                    urllib.request.urlopen(f"{base}/api/copy?{urllib.parse.urlencode(q)}", timeout=30)
                else:
                    urllib.request.urlopen(f"{base}/api/move?{urllib.parse.urlencode(q)}", timeout=30)
            except Exception as e:
                ok_all = False
                messagebox.showerror("Uzak Yapıştır", str(e))
                break

        if ok_all:
            if mode == "cut":
                self._remote_clip = None
            self.refresh_remote()


    # ---------- Uzak sunucu işlemleri ----------
    def _base_url(self):
        return f"http://{self.ip_var.get().strip()}:{self.http_port}"

    def _ensure_shortcuts_loaded(self):
        if self._shortcuts_loaded:
            return
        try:
            base = self._base_url()
            k = urllib.parse.urlencode({"key": self.key_var.get()})
            with urllib.request.urlopen(f"{base}/api/shortcuts?{k}", timeout=2.0) as r:
                shorts = json.loads(r.read().decode())
            with urllib.request.urlopen(f"{base}/api/roots?{k}", timeout=2.0) as r:
                roots = json.loads(r.read().decode())

            # Map ve combobox doldur
            self.shortcuts_map = {}
            order = []
            for lbl, path in (shorts or {}).items():
                self.shortcuts_map[lbl] = path
                order.append(lbl)
            for root in (roots or []):
                self.shortcuts_map[root] = root
                order.append(root)
            self.shortcut_combo["values"] = order

            # Uzak başlangıç yolu geçerli değilse ilk köke dön
            if roots:
                try:
                    cur = getattr(self, "remote_abs", "")
                    # basit doğrulama: "X:\" ile başlıyor mu, ve roots içinde var mı
                    if not cur or not any(str(cur).upper().startswith(str(r).upper()) for r in roots):
                        self.remote_abs = roots[0]
                except Exception:
                    self.remote_abs = roots[0]

            self._shortcuts_loaded = True

        except Exception as e:
            # hata olursa yeniden denemeye izin veriyoruz
            self._shortcuts_loaded = False
            self.status.set(f"Kısayol/Root alınamadı: {e}")


    

    def refresh_remote(self):
        # 1) Sunucu kimliği değişti mi? (ip, http_port, key)
        ident = self._current_remote_identity()
        if ident != getattr(self, "_remote_identity", None):
            self._remote_identity = ident
            # Kısayol/roots önbelleğini sıfırla
            self._shortcuts_loaded = False
            self.shortcuts_map = {}
            try:
                self.shortcut_combo["values"] = ()
            except Exception:
                pass

        # 2) Gerekirse kısayolları HEMEN yükle
        self._ensure_shortcuts_loaded()

        # 3) Listeyi doldur
        for i in self.remote_tv.get_children():
            self.remote_tv.delete(i)
        abs_path = getattr(self, "remote_abs", "C:\\")
        self.remote_path.set(abs_path)
        base = self._base_url()
        try:
            q = urllib.parse.urlencode({"abs": abs_path, "key": self.key_var.get()})
            with urllib.request.urlopen(f"{base}/api/list?{q}") as r:
                data = json.loads(r.read().decode())
            for item in sorted(data, key=lambda x: (x["type"] != "dir", x["name"].lower())):
                size = "" if item["type"] == "dir" else f"{item.get('size', 0) // 1024} KB"
                self.remote_tv.insert("", "end",
                                    values=(item["name"], size, item.get("mtime", ""), item["type"]))
            self.status.set(f"Uzak: {abs_path}")
        except Exception as e:
            self.status.set("Bağlantı hatası")
            messagebox.showerror("Uzak listeleme", str(e))


    def remote_rename(self):
        rfile = self.get_remote_file()
        if not rfile:
            messagebox.showwarning("Yeniden Adlandır", "Sağdan öğe seç.")
            return
        if not self._server_supports("rename"):
            messagebox.showinfo("Yeniden Adlandır", "Sunucu rename desteklemiyor.")
            return
        import tkinter.simpledialog as sd
        newname = sd.askstring("Yeniden Adlandır", "Yeni ad:")
        if not newname: return
        base = self._base_url()
        q = urllib.parse.urlencode({"abs": rfile, "newname": newname, "key": self.key_var.get()})
        try:
            urllib.request.urlopen(f"{base}/api/rename?{q}", timeout=15)
            self.refresh_remote()
        except Exception as e:
            messagebox.showerror("Yeniden Adlandır", str(e))


    def remote_mkdir(self):
        import tkinter.simpledialog as sd
        name = sd.askstring("Yeni klasör", "Klasör adı:")
        if not name:
            return
        base = self._base_url()
        q = urllib.parse.urlencode({"abs": self.remote_abs, "name": name, "key": self.key_var.get()})
        try:
            urllib.request.urlopen(f"{base}/api/mkdir?{q}")
            self.refresh_remote()
        except Exception as e:
            messagebox.showerror("Klasör oluşturma", str(e))

    def remote_delete(self):
        items = self._remote_selected_items()
        if not items:
            messagebox.showwarning("Uyarı", "Sağdan dosya/klasör seç.")
            return

        if len(items) == 1:
            ask = f"Seçili öğe silinsin mi?\n{items[0]['abs']}"
        else:
            ask = f"Seçili {len(items)} öğe silinsin mi?"
        if not messagebox.askyesno("Sil", ask):
            return

        base = self._base_url()
        key  = self.key_var.get()
        ok_all = True
        for it in items:
            q = urllib.parse.urlencode({"abs": it["abs"], "key": key})
            try:
                urllib.request.urlopen(f"{base}/api/delete?{q}")
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode("utf-8", errors="ignore")
                except Exception:
                    body = str(e)
                messagebox.showerror("Silme", f"{it['name']}\n\n{e}\n\n{body}")
                ok_all = False
                break
            except Exception as e:
                messagebox.showerror("Silme", f"{it['name']}\n\n{e}")
                ok_all = False
                break

        self.refresh_remote()
        if ok_all:
            self.status.set("Silme tamamlandı.")


    # --- ZIPDIR doğrudan TCP ile gönderim ---
    def _send_zipdir_direct(self, ip: str, tcp_port: int, local_dir: str, remote_base_dir: str) -> bool:
        """
        Klasörü geçici .zip'e alır, TCP ile 'zipdir' header + ZIP akışı gönderir.
        Sunucudan 'OK\\n' ACK bekler (sunucu tarafında destek varsa).
        """
        try:
            # 1) Geçici ZIP oluştur
            zpath = os.path.join(
                tempfile.gettempdir(),
                f"up_{os.path.basename(local_dir)}_{int(time.time()*1000)}.zip"
            )
            with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                base = local_dir
                for root, _, files in os.walk(base):
                    rel_root = os.path.relpath(root, base)
                    for fn in files:
                        lp = os.path.join(root, fn)
                        arc = os.path.join(rel_root, fn) if rel_root != "." else fn
                        zf.write(lp, arcname=arc.replace("\\", "/"))

            total = os.path.getsize(zpath)

            # 2) TCP: header + zip akışı
            hdr = {"type": "zipdir", "dest": remote_base_dir, "name": os.path.basename(local_dir)}
            line = (json.dumps(hdr) + "\n").encode("utf-8")

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                try:
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass
                s.connect((ip, int(tcp_port)))
                s.sendall(line)

                sent = 0
                last_ui = 0.0
                with open(zpath, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 256)  # 256 KB
                        if not chunk:
                            break
                        s.sendall(chunk)
                        sent += len(chunk)
                        if total > 0:
                            now = time.time()
                            if (now - last_ui) >= 0.05:
                                pct = min(100.0, (sent / total) * 100.0)
                                self.after(0, lambda v=pct: self.pb.configure(value=v))
                                txt = f"Gönderiliyor... %{pct:.0f}"
                                self.after(0, lambda t=txt: self.status.set(t))
                                # veya:
                                self._ui_progress(pct)
                                self._ui_status(f"Gönderiliyor... %{pct:.0f}")

                                last_ui = now

                # 3) Yazmayı kapat ve ACK bekle
                try:
                    s.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

                # 'OK\\n' gelmesini bekle (maks 120 sn)
                s.settimeout(120.0)
                buff = b""
                while True:
                    chunk = s.recv(1024)
                    if not chunk:
                        break
                    buff += chunk
                    if b"\n" in buff:
                        break
                ack = buff.decode(errors="ignore").strip()
                if ack != "OK":
                    # ACK gelmediyse, yine de HTTP ile doğrulayacağız.
                    pass

            finally:
                try:
                    s.close()
                except Exception:
                    pass

            # 4) Geçici ZIP'i sil
            try:
                os.remove(zpath)
            except Exception:
                pass

            return True

        except OSError as e:
            # Sunucu hemen kapatırsa 10053/10054 olabilir → HTTP doğrulamasıyla karar vereceğiz.
            win = getattr(e, "winerror", None)
            if win in (10053, 10054):
                self.after(0, lambda: self.status.set("Gönderim tamamlandı (uzak uç kapattı)"))
                return True
            err_msg = f"Hata: {e}"
            self.after(0, lambda msg=err_msg: messagebox.showerror("Klasör Yükleme", msg))
            return False
        except Exception as e:
            err_msg = f"Hata: {e}"
            self.after(0, lambda msg=err_msg: messagebox.showerror("Klasör Yükleme", msg))
            return False

    # ---------- Upload / Download ----------
    def do_upload(self, paths=None):
        """Butonla: soldaki seçimleri yükler. Sürükle-bırak: paths listesi gelir."""
        items = []

        if paths:  # sürükle-bırak
            for ap in paths:
                ap = ap.strip()
                if not ap:
                    continue
                name = os.path.basename(ap.rstrip("\\/"))
                typ  = "dir" if os.path.isdir(ap) else "file"
                items.append((name, ap, typ))
        else:      # butondan çağrı: soldaki seçimler
            sels = self.local_tv.selection()
            if not sels:
                messagebox.showwarning("Uyarı", "Soldan dosya/klasör seç.")
                return
            for iid in sels:
                name = self.local_tv.item(iid, "values")[0]
                ap   = os.path.join(self.local_cwd, name)
                typ  = "dir" if os.path.isdir(ap) else "file"
                items.append((name, ap, typ))

        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("Uyarı", "Sunucu IP boş!")
            return

        job = {
            "type": "upload",
            "ip": ip,
            "remote_abs": self.remote_abs,
            "items": items,
        }
        self._job_queue.put(job)
        self._update_queue_info()
        self.status.set(f"Kuyruğa eklendi: {len(items)} öğe")


    def _update_queue_info(self):
        try:
            pending = self._job_queue.qsize()
        except Exception:
            pending = 0
        self.queue_info.set(f"Kuyruk: {pending} iş")

    def _queue_toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.status.set("DURAKLATILDI")
            try: self.btn_pause.configure(text="▶")
            except Exception: pass
        else:
            self.status.set("Devam ediyor…")
            try: self.btn_pause.configure(text="⏸")
            except Exception: pass

    def _queue_cancel_current(self):
        self._current_job_cancel.set()
        self.status.set("İptal isteniyor…")

    def _wait_if_paused(self):
        while self._paused and not self._current_job_cancel.is_set():
            time.sleep(0.1)
            self.update_idletasks()

    def _queue_loop(self):
        while True:
            job = self._job_queue.get()
            self._current_job_cancel.clear()
            try:
                if job.get("type") == "upload":
                    self._run_upload_job(job)
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Yükleme", str(err)))
            finally:
                self._update_queue_info()
                self._job_queue.task_done()

    def _ensure_remote_dir(self, rel_dir: str, base_http: str, key: str) -> bool:
        if not rel_dir or rel_dir == ".":
            return True
        try:
            q = urllib.parse.urlencode({"abs": self.remote_abs, "name": rel_dir, "key": key})
            urllib.request.urlopen(f"{base_http}/api/mkdir?{q}", timeout=5)
            return True
        except Exception:
            return False

    def _verify_remote_folder(self, folder_abs: str, base_http: str, key: str, timeout_s: int = 30) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline and not self._current_job_cancel.is_set():
            try:
                q = urllib.parse.urlencode({"abs": folder_abs, "key": key})
                with urllib.request.urlopen(f"{base_http}/api/list?{q}", timeout=5) as r:
                    _ = json.loads(r.read().decode())
                return True
            except Exception:
                time.sleep(0.25)
        return False

    def _send_one_file(self, ip: str, tcp_port: int, local_path: str, dest_dir: str, files_done: int, files_total: int) -> bool:
        exe = "transfer_client_v6.exe"
        try:
            done_evt = threading.Event()
            # meta’yı progress dinleyiciye geçir
            meta = {"files_done": files_done, "files_total": files_total, "name": os.path.basename(local_path)}
            threading.Thread(target=self._listen_progress, args=(self.progress_port, done_evt, meta), daemon=True).start()
            p = subprocess.Popen([exe, ip, str(tcp_port), local_path, str(self.progress_port), dest_dir])
            rc = p.wait()
            done_evt.wait(timeout=2)
            return rc == 0
        except Exception:
            return False

    def _run_upload_job(self, job: dict):
        """
        YÜKLEME İŞİ (kuyruk tarafından çağrılır).
        - Dizinde önce ZIP→AÇ (zipdir) dener, 30 sn doğrular.
        - Olmazsa tek tek dosyaya düşer (önce klasörleri oluşturur).
        - self._paused ve self._current_job_cancel destekli.
        """
        ip = job["ip"]
        remote_abs = job["remote_abs"]
        items = job["items"]

        base_http = f"http://{ip}:{self.http_port}"
        key = self.key_var.get().strip()

        # Toplam iş (dosya/adım) sayısını hesaplamak için kaba bir yaklaşım:
        files_total = 0
        for _, ap, typ in items:
            if typ == "file":
                files_total += 1
            else:
                for _, _, files in os.walk(ap):
                    files_total += len(files)
        if files_total == 0:
            files_total = len(items)  # sadece klasör iskeleti bile olsa

        files_done = 0
        self._progress_meta.update({"files_total": files_total, "files_done": 0})

        for name, ap, typ in items:
            if self._current_job_cancel.is_set():
                self.status.set("İptal edildi.")
                break

            # Pause desteği
            self._wait_if_paused()
            if self._current_job_cancel.is_set():
                break

            if typ == "dir":
                base_name = os.path.basename(ap)
                self.status.set(f"Klasör gönderiliyor (ZIP→Aç): {base_name}")
                self.pb["value"] = 0
                self.update_idletasks()

                # 1) ZIP→TCP (zipdir) dene
                ok_zip = self._send_zipdir_direct(ip, self.tcp_port, ap, remote_abs)

                # 2) Doğrula (30 sn)
                target_abs = os.path.join(remote_abs, base_name)
                ok_ver = ok_zip and self._verify_remote_folder(target_abs, base_http, key, timeout_s=30)

                if not ok_ver:
                    # 3) FALLBACK: tek tek dosya
                    self.status.set(f"Zipdir doğrulanamadı, tek tek gönderiliyor: {base_name}")
                    # Üst klasör kabını oluştur
                    if not self._ensure_remote_dir(base_name, base_http, key):
                        messagebox.showerror("Yükleme", f"Klasör oluşturulamadı: {base_name}")
                        break
                    dest_root = os.path.join(remote_abs, base_name)

                    # Dosya işleri
                    file_jobs = []
                    for root, _, files in os.walk(ap):
                        rel_dir = os.path.relpath(root, ap)  # "." veya alt
                        for fn in files:
                            lp = os.path.join(root, fn)
                            file_jobs.append((rel_dir if rel_dir != "." else "", lp))

                    total_in_dir = len(file_jobs)
                    for i, (rel_dir, lp) in enumerate(file_jobs, 1):
                        if self._current_job_cancel.is_set():
                            break
                        self._wait_if_paused()
                        if self._current_job_cancel.is_set():
                            break

                        rel_path = os.path.join(base_name, rel_dir) if rel_dir else base_name
                        if not self._ensure_remote_dir(rel_path, base_http, key):
                            messagebox.showerror("Yükleme", f"Klasör oluşturulamadı: {rel_path}")
                            break

                        dest_dir = os.path.join(remote_abs, rel_path)
                        # files_done sayacı (global)
                        files_done += 1
                        self._progress_meta.update({"files_done": files_done, "name": os.path.basename(lp)})
                        ok = self._send_one_file(ip, self.tcp_port, lp, dest_dir, files_done, files_total)
                        if not ok:
                            messagebox.showerror("Yükleme", f"Gönderilemedi: {os.path.basename(lp)}")
                            break

                        self.status.set(f"{files_done}/{files_total} gönderildi: {os.path.basename(lp)}")
                        self.update_idletasks()

                else:
                    # zipdir başarılı; dizindeki dosyaları “gönderildi” say
                    cnt = 0
                    for _, _, files in os.walk(ap):
                        cnt += len(files)
                    files_done += cnt
                    self._progress_meta.update({"files_done": files_done})
                    self.status.set(f"Klasör tamamlandı: {base_name}")

            else:
                # TEK DOSYA
                files_done += 1
                self._progress_meta.update({"files_done": files_done, "name": name})
                self.status.set(f"Dosya gönderiliyor: {name}")
                ok = self._send_one_file(ip, self.tcp_port, ap, remote_abs, files_done, files_total)
                if not ok:
                    messagebox.showerror("Yükleme", f"Gönderilemedi: {name}")
                    break

            # Döngü sonunda UI tazele
            self.pb["value"] = min(100, int(files_done * 100 / max(1, files_total)))
            self.update_idletasks()

        self.refresh_remote()
        if not self._current_job_cancel.is_set():
            self.status.set("Yükleme bitti.")
            self.pb["value"] = 100


    def _listen_progress(self, port, done_evt, meta=None):
        """
        transfer_client_v6.exe'den gelen UDP progress'i dinler.
        JSON: {"sent": int, "total": int}  (+ opsiyonel meta alanları)
        Hız (MB/sn) ve ETA'yı yerelde hesaplarız.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("", int(port)))
            sock.settimeout(15.0)

            # Başlat
            self._progress_meta["last_sent"] = 0
            self._progress_meta["last_t"] = time.time()
            self._progress_meta["speed"] = 0.0
            files_done = (meta or {}).get("files_done", 0)
            files_total = (meta or {}).get("files_total", 0)
            name = (meta or {}).get("name", "")

            while True:
                data, _ = sock.recvfrom(4096)
                try:
                    j = json.loads(data.decode())
                except Exception:
                    continue

                sent = int(j.get("sent", 0))
                total = max(1, int(j.get("total", 1)))

                now = time.time()
                dt = max(1e-3, now - self._progress_meta["last_t"])
                ds = max(0, sent - self._progress_meta["last_sent"])
                inst_speed = ds / dt  # B/s
                # basit EMA
                sp = 0.7 * inst_speed + 0.3 * self._progress_meta["speed"]
                self._progress_meta["speed"] = sp
                self._progress_meta["last_t"] = now
                self._progress_meta["last_sent"] = sent

                # ETA
                eta_s = None
                if sp > 0 and total >= sent:
                    eta_s = int((total - sent) / sp)

                # UI
                pct = min(100.0, (sent / total) * 100.0)
                self.pb["value"] = pct

                # Hız MB/sn
                mbps = sp / (1024 * 1024)
                # dosya sayacı metası varsa göster
                if files_total > 0:
                    head = f"[{files_done}/{files_total}] "
                else:
                    head = ""

                if eta_s is None:
                    eta_text = ""
                else:
                    m, s = divmod(eta_s, 60)
                    h, m = divmod(m, 60)
                    eta_text = f" | ETA {h:02d}:{m:02d}:{s:02d}"

                short_name = name if name else j.get("name", "")
                if short_name and len(short_name) > 40:
                    short_name = "…" + short_name[-37:]

                self.status.set(f"{head}{short_name} %{pct:.0f} | {mbps:.2f} MB/sn{eta_text}")
                self.update_idletasks()

                if sent >= total and total > 0:
                    break
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self.pb["value"] = 100
            self.update_idletasks()
            if done_evt:
                done_evt.set()


    def do_download(self):
        items = self._remote_selected_items()
        if not items:
            messagebox.showwarning("Uyarı", "Sağdan dosya/klasör seç.")
            return

        base = self._base_url()
        key  = self.key_var.get()

        def report_hook(blocks, block_size, total_size):
            if total_size > 0:
                pct = min(100, (blocks * block_size * 100) / total_size)
                self.pb["value"] = pct
                self.update_idletasks()

        def download_one_file(it):
            target = os.path.join(self.local_cwd, it["name"])
            self.status.set(f"İndiriliyor: {it['name']}")
            self.pb["value"] = 0
            q = urllib.parse.urlencode({"abs": it["abs"], "key": key})
            urllib.request.urlretrieve(f"{base}/api/download?{q}", target, reporthook=report_hook)
            self.status.set(f"İndirildi: {target}")

        def unique_dir(base_path: str) -> str:
            if not os.path.exists(base_path):
                return base_path
            i = 2
            while True:
                cand = f"{base_path} ({i})"
                if not os.path.exists(cand):
                    return cand
                i += 1

        def download_one_folder(it):
            name = it["name"]
            rfile = it["abs"]
            zip_name = name + ".zip"
            zip_path = os.path.join(self.local_cwd, zip_name)

            # 1) ZIP indir
            self.status.set(f"Klasör ZIP olarak indiriliyor: {name}")
            self.pb["value"] = 0
            q = urllib.parse.urlencode({"abs": rfile, "key": key})
            urllib.request.urlretrieve(f"{base}/api/download?{q}", zip_path, reporthook=report_hook)

            # 2) İçeriği analiz/çıkar
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    members = [m for m in zf.infolist() if m.filename and not m.filename.startswith("__MACOSX/")]
                    # Tek kök klasör var mı?
                    roots = set()
                    for m in members:
                        fn = m.filename.replace("\\", "/")
                        if fn.endswith("/"):
                            fn = fn[:-1]
                        if not fn:
                            continue
                        roots.add(fn.split("/")[0])
                    single_root = (len(roots) == 1)
                    root_name = next(iter(roots)) if single_root else None

                    final_dir = unique_dir(os.path.join(self.local_cwd, name))
                    extract_parent = self.local_cwd if single_root else final_dir
                    if not single_root:
                        os.makedirs(final_dir, exist_ok=True)

                    files_only = [m for m in members if not m.is_dir()]
                    total_files = max(1, len(files_only))
                    done = 0
                    self.status.set("ZIP çıkartılıyor...")
                    self.pb["value"] = 0
                    for m in members:
                        zf.extract(m, extract_parent)
                        if not m.is_dir():
                            done += 1
                            pct = int(done * 100 / total_files)
                            self.pb["value"] = pct
                            self.update_idletasks()
            finally:
                try:
                    os.remove(zip_path)
                except Exception:
                    pass

            # 3) Tek kök varsa klasörü doğru isme taşı
            if single_root:
                extracted_root = os.path.join(self.local_cwd, root_name)
                if os.path.abspath(extracted_root) != os.path.abspath(final_dir):
                    try:
                        os.replace(extracted_root, final_dir)
                    except Exception:
                        shutil.copytree(extracted_root, final_dir, dirs_exist_ok=True)
                        shutil.rmtree(extracted_root, ignore_errors=True)

            self.status.set(f"İndirildi ve klasöre çıkartıldı: {final_dir}")

        def worker():
            total = len(items)
            for idx, it in enumerate(items, 1):
                try:
                    if it["type"] == "dir":
                        download_one_folder(it)
                    else:
                        download_one_file(it)
                    self.status.set(f"{idx}/{total} tamamlandı: {it['name']}")
                except Exception as e:
                    messagebox.showerror("İndirme", f"{it['name']}\n\n{e}")
                    break

            self.pb["value"] = 100
            self.refresh_local()

        threading.Thread(target=worker, daemon=True).start()

    def update_server(self):
        import tkinter.filedialog as fd
        fpath = fd.askopenfilename(title="Yeni Sunucu EXE Seç", filetypes=[("EXE Dosyası", "*.exe"), ("Tüm Dosyalar", "*.*")])
        if not fpath:
            return
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("Uyarı", "Sunucu IP boş!")
            return
        key = self.key_var.get().strip()
        if not key:
            messagebox.showwarning("Uyarı", "Sunucu anahtarı boş olamaz!")
            return
        self.status.set("Sunucu dosyası gönderiliyor...")
        self.pb["value"] = 0

        def run_update():
            conn = None
            try:
                total = os.path.getsize(fpath)
                conn = http.client.HTTPConnection(ip, int(self.http_port), timeout=90)
                query = urllib.parse.urlencode({"key": key})
                conn.putrequest("POST", f"/api/update?{query}")
                conn.putheader("Content-Type", "application/octet-stream")
                conn.putheader("Content-Length", str(total))
                conn.endheaders()

                sent = 0
                chunk_size = 256 * 1024

                with open(fpath, "rb") as src:
                    while True:
                        chunk = src.read(chunk_size)
                        if not chunk:
                            break
                        conn.send(chunk)
                        sent += len(chunk)
                        pct = 100 if total <= 0 else min(100, int(sent * 100 / total))
                        self.after(0, lambda v=pct: self.pb.configure(value=v))

                resp = conn.getresponse()
                body = resp.read().decode("utf-8", "ignore").strip()
                if resp.status != 200 or body.upper() != "OK":
                    raise RuntimeError(f"Sunucu güncelleme hatası: {resp.status} {resp.reason}\n{body}")

                def on_success():
                    self.pb.configure(value=100)
                    self.status.set("Sunucu güncellemesi başlatıldı. Sunucu kısa süreliğine yeniden başlayabilir.")

                self.after(0, on_success)
            except Exception as e:
                def on_error(msg=str(e)):
                    messagebox.showerror("Sunucu Güncelleme", msg)
                    self.status.set("Güncelleme hatası!")
                    self.pb.configure(value=0)

                self.after(0, on_error)
            finally:
                if conn is not None:
                    conn.close()

        threading.Thread(target=run_update, daemon=True).start()

    # ---------- Multicast keşif ----------
    def _mcast_listener_loop(self):
        group, port = self.mcast_group, int(self.mcast_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('', port))
        except Exception as e:
            print("Multicast bind hatası:", e)
            self._publish_shared_discovery()
            return

        # Windows'ta IP_ADD_MEMBERSHIP için 4s + u_long (INADDR_ANY) paketi
        try:
            mreq = struct.pack("4sl", socket.inet_aton(group), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception as e:
            print("Multicast üyelik hatası:", e)
            self._publish_shared_discovery()
            return

        sock.settimeout(3.0)

        STALE = 60.0  # 60 sn görülmeyenleri düşür
        # UI güncellemesini sıkıştırmak için basit throttle
        last_ui = 0.0
        UI_MIN_INTERVAL = 0.2  # sn

        while True:
            try:
                data, _ = sock.recvfrom(4096)
                try:
                    j = json.loads(data.decode("utf-8", errors="ignore"))
                except Exception:
                    continue  # bozuk paket

                ip = j.get('ip')
                if not ip:
                    continue  # IP yoksa geç

                tcp = j.get('tcpPort', self.tcp_port)
                http = j.get('httpPort', getattr(self, "http_port", 8088))
                name = j.get('name', ip) or ip

                key = f"{ip}:{tcp}"
                now = time.time()
                entry = {
                    "ip": ip,
                    "tcpPort": tcp,
                    "httpPort": http,
                    "name": name,
                    "last_seen": now,
                }
                self.discovered[key] = entry

                # UI’yi çok sık çağırmamak için throttle
                if now - last_ui >= UI_MIN_INTERVAL:
                    self.after(0, self._update_discovery_combo)
                    last_ui = now

                self._publish_shared_discovery()

            except socket.timeout:
                now = time.time()
                changed = False
                for k, v in list(self.discovered.items()):
                    if now - v.get('last_seen', 0) > STALE:
                        del self.discovered[k]
                        changed = True
                if changed:
                    self.after(0, self._update_discovery_combo)
                    self._publish_shared_discovery()

            except Exception as e:
                print("Mcast recv hata:", e)
                break

        self._publish_shared_discovery()

    def _publish_shared_discovery(self, initial=False):
        if not isinstance(self.shared, dict):
            return
        snapshot = {}
        for key, meta in (self.discovered or {}).items():
            if not isinstance(meta, dict):
                continue
            last_seen = meta.get("last_seen")
            if isinstance(last_seen, (int, float)):
                last_seen_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_seen))
            else:
                last_seen_str = last_seen or ""
            snapshot[key] = {
                "ip": meta.get("ip"),
                "tcpPort": meta.get("tcpPort"),
                "httpPort": meta.get("httpPort"),
                "name": meta.get("name"),
                "last_seen": last_seen_str,
            }
        payload = {
            "source": "transfer",
            "timestamp": time.time(),
            "entries": snapshot,
            "initial": bool(initial),
        }
        with self._shared_lock:
            self.shared["discovery_payload"] = payload

    def _update_discovery_combo(self):
        """Keşfedilen sunucuları combobox'a doldurur (ip,tcp,http saklar)."""
        try:
            vals = []
            index = []

            # Güvenli int dönüştürücü
            def _to_int(v, default):
                try:
                    return int(v)
                except Exception:
                    return default

            # self.discovered: {key -> meta(dict)} beklenir
            for _, meta in (self.discovered or {}).items():
                if not isinstance(meta, dict):
                    continue
                ip   = (meta.get("ip") or "").strip()
                if not ip:
                    continue
                name = (meta.get("name") or "").strip()
                tcp  = _to_int(meta.get("tcpPort", self.tcp_port), self.tcp_port)
                http = _to_int(meta.get("httpPort", getattr(self, "http_port", 8088)), getattr(self, "http_port", 8088))

                label = name if name else ip
                disp  = f"{label} ({ip}:{tcp})" if label else f"{ip}:{tcp}"

                # Toplama listeleri
                index.append((name or ip, ip, tcp, http, disp))

            # Sırala: ada göre, yoksa IP'ye göre
            index.sort(key=lambda t: (t[0].lower(), t[1]))

            # values ve discovery_index’i üret
            self.discovery_index = {}
            for _, ip, tcp, http, disp in index:
                vals.append(disp)
                self.discovery_index[disp] = {
                    "ip": ip,
                    "tcpPort": int(tcp),
                    "httpPort": int(http),
                }

            # Combobox’a bas
            current = self.discovery_combo.get()
            self.discovery_combo["values"] = vals

            # (Opsiyonel) Mevcut seçim listede yoksa temizle
            if current and current not in self.discovery_index:
                # self.discovery_combo.set("")  # istersen aç
                pass

        except tk.TclError:
            # Uygulama kapanırken veya widget yokken çağrılmış olabilir—sessiz geç
            return
        except Exception as e:
            print("update_discovery_combo hatası:", e)


    def _force_reload_shortcuts(self):
        self._shortcuts_loaded = False
        self.shortcuts_map = {}
        try:
            self.shortcut_combo.set("")
        except Exception:
            pass
        # Hemen çek
        self._ensure_shortcuts_loaded()

    def _pick_discovered(self):
        sel = self.discovery_combo.get()
        try:
            meta = self.discovery_index.get(sel)
            if meta:
                # IP, TCP, HTTP’yi RAM’e al
                self.ip_var.set(meta["ip"])
                self.tcp_port = int(meta.get("tcpPort", self.tcp_port))
                self.http_port = int(meta.get("httpPort", self.http_port))   # << ÖNEMLİ

            else:
                # Plain text fallback ("Isim (ip:tcp)" / "ip:tcp" / sadece "ip")
                if "(" in sel and ")" in sel:
                    ip_port = sel[sel.rfind("(")+1:sel.rfind(")")]
                else:
                    ip_port = sel
                if ":" in ip_port:
                    ip, tcp = ip_port.split(":")
                    self.ip_var.set(ip)
                    self.tcp_port = int(tcp)
                else:
                    self.ip_var.set(ip_port)

            # Kısayolları mutlaka yeniden çek
            self._force_reload_shortcuts()

            # Artık uzak paneli yenile (kısayollar hazır)
            self.refresh_remote()

            self.status.set(f"🔗 {sel} seçildi (TCP {self.tcp_port}, HTTP {self.http_port})")
        except Exception as e:
            self.status.set(f"Alıcı seçimi hatası: {e}")



