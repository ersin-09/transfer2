# receiver_finder.py — Açık Cihazlar + TXT + stabil seçim (tam, düzeltildi)
# Gereken: Pillow (duvar için) → pip install pillow

import json, os, time, socket, struct, threading, concurrent.futures, errno, subprocess, sys
import urllib.request, urllib.parse, urllib.error
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except Exception:
    PIL_OK = False

APP_TITLE = "Alıcı Bulucu (Multicast + Hızlı Tarama + Ad Değiştir + TXT + Açık Cihazlar)"

DEFAULT_CLIENT_CFG = {
    "preferred_http_port": 8088,
    "preferred_tcp_port": 5050,
    "listen_mcast_group": "239.0.0.250",
    "listen_mcast_port": 9999,
    "subnets": ["192.168.1", "10.0.0"],
    "key": "1234",
    "tightvnc_viewer_path": r"C:\\Program Files\\TightVNC\\tvnviewer.exe",
    "tightvnc_password": "",
    "tightvnc_port": 5900,
}

CLIENT_CFG_NAME = "client_config.json"


class FinderTab(tk.Frame):
    def __init__(self, master, shared, notebook=None):
        super().__init__(master)
        self.shared = shared if isinstance(shared, dict) else {}
        self._external_notebook = notebook

        # Bu sınıf hem tek başına bir pencere olarak hem de sekme olarak
        # kullanılabildiği için pencere başlığını/ölçülerini doğrudan
        # üst düzeyde ayarlamak gerekiyor. Frame üzerinde title/geometry
        # olmadığı için toplevel'i hedefliyoruz.
        toplevel = self.winfo_toplevel()
        try:
            toplevel.title(APP_TITLE)
            toplevel.geometry("1000x640")
            toplevel.minsize(920, 560)
        except Exception:
            pass

        self.ccfg = self._load_cfg()

        # RAM
        self.discovered = {}  # key: "ip:tcp" -> meta
        self._listening = False
        self._rf_scheduled = False
        self._shared_stamp = None
        self._shared_notice = False
        self._known_dirty = False
        self._last_known_save = 0.0

        # Duvar sekmesi/penceresi
        self.wall = None
        self._wall_container = None

        # UI
        self._make_ui()
        self._load_known_to_table()
        self.after(600, self._poll_shared_discovery)

    # ---------- paths ----------
    def _here(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def _cfg_path(self):
        return os.path.join(self._here(), CLIENT_CFG_NAME)

    def _txt_path(self):
        return os.path.join(self._here(), "alicilar.txt")

    def _find_notebook(self):
        widget = self
        while widget is not None:
            master = getattr(widget, "master", None)
            if master is None:
                return None
            if isinstance(master, ttk.Notebook):
                return master
            widget = master
        return None

    # ---------- config ----------
    def _load_cfg(self):
        path = self._cfg_path()
        if not os.path.exists(path):
            return dict(DEFAULT_CLIENT_CFG)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        out = dict(DEFAULT_CLIENT_CFG)
        out.update({k: v for k, v in data.items() if v is not None})
        return out

    def _save_cfg(self):
        self._sync_cfg_from_inputs()
        self._update_known_receivers_cache()
        self._write_cfg_to_disk(silent=False)

    def _write_cfg_to_disk(self, silent=False):
        try:
            path = self._cfg_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.ccfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            self._last_known_save = time.monotonic()
            self._known_dirty = False
            if not silent:
                self.status.set(f"Kaydedildi: {path}")
        except Exception as e:
            self._known_dirty = True
            self.status.set(f"client_config yazma hatası: {e}")

    def _sync_cfg_from_inputs(self):
        def _as_int(value, fallback):
            try:
                return int(value)
            except Exception:
                return fallback

        self.ccfg["key"] = self.key_var.get().strip() or DEFAULT_CLIENT_CFG["key"]
        self.ccfg["preferred_http_port"] = _as_int(self.http_var.get(), DEFAULT_CLIENT_CFG["preferred_http_port"])
        self.ccfg["preferred_tcp_port"] = _as_int(self.tcp_var.get(), DEFAULT_CLIENT_CFG["preferred_tcp_port"])
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        self.ccfg["subnets"] = subnets or list(DEFAULT_CLIENT_CFG["subnets"])
        self.ccfg["tightvnc_viewer_path"] = (self.vnc_path_var.get() or "").strip()
        self.ccfg["tightvnc_password"] = self.vnc_pass_var.get() or ""
        self.ccfg["tightvnc_port"] = _as_int(self.vnc_port_var.get(), DEFAULT_CLIENT_CFG["tightvnc_port"])

    def _sync_cfg_from_inputs(self):
        def _as_int(value, fallback):
            try:
                return int(value)
            except Exception:
                return fallback

        self.ccfg["key"] = self.key_var.get().strip() or DEFAULT_CLIENT_CFG["key"]
        self.ccfg["preferred_http_port"] = _as_int(self.http_var.get(), DEFAULT_CLIENT_CFG["preferred_http_port"])
        self.ccfg["preferred_tcp_port"] = _as_int(self.tcp_var.get(), DEFAULT_CLIENT_CFG["preferred_tcp_port"])
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        self.ccfg["subnets"] = subnets or list(DEFAULT_CLIENT_CFG["subnets"])
        self.ccfg["tightvnc_viewer_path"] = (self.vnc_path_var.get() or "").strip()
        self.ccfg["tightvnc_password"] = self.vnc_pass_var.get() or ""
        self.ccfg["tightvnc_port"] = _as_int(self.vnc_port_var.get(), DEFAULT_CLIENT_CFG["tightvnc_port"])

    def _sync_cfg_from_inputs(self):
        def _as_int(value, fallback):
            try:
                return int(value)
            except Exception:
                return fallback

        self.ccfg["key"] = self.key_var.get().strip() or DEFAULT_CLIENT_CFG["key"]
        self.ccfg["preferred_http_port"] = _as_int(self.http_var.get(), DEFAULT_CLIENT_CFG["preferred_http_port"])
        self.ccfg["preferred_tcp_port"] = _as_int(self.tcp_var.get(), DEFAULT_CLIENT_CFG["preferred_tcp_port"])
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        self.ccfg["subnets"] = subnets or list(DEFAULT_CLIENT_CFG["subnets"])
        self.ccfg["tightvnc_viewer_path"] = (self.vnc_path_var.get() or "").strip()
        self.ccfg["tightvnc_password"] = self.vnc_pass_var.get() or ""
        self.ccfg["tightvnc_port"] = _as_int(self.vnc_port_var.get(), DEFAULT_CLIENT_CFG["tightvnc_port"])

    def _sync_cfg_from_inputs(self):
        def _as_int(value, fallback):
            try:
                return int(value)
            except Exception:
                return fallback

        self.ccfg["key"] = self.key_var.get().strip() or DEFAULT_CLIENT_CFG["key"]
        self.ccfg["preferred_http_port"] = _as_int(self.http_var.get(), DEFAULT_CLIENT_CFG["preferred_http_port"])
        self.ccfg["preferred_tcp_port"] = _as_int(self.tcp_var.get(), DEFAULT_CLIENT_CFG["preferred_tcp_port"])
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        self.ccfg["subnets"] = subnets or list(DEFAULT_CLIENT_CFG["subnets"])
        self.ccfg["tightvnc_viewer_path"] = (self.vnc_path_var.get() or "").strip()
        self.ccfg["tightvnc_password"] = self.vnc_pass_var.get() or ""
        self.ccfg["tightvnc_port"] = _as_int(self.vnc_port_var.get(), DEFAULT_CLIENT_CFG["tightvnc_port"])

    def _sync_cfg_from_inputs(self):
        def _as_int(value, fallback):
            try:
                return int(value)
            except Exception:
                return fallback

        self.ccfg["key"] = self.key_var.get().strip() or DEFAULT_CLIENT_CFG["key"]
        self.ccfg["preferred_http_port"] = _as_int(self.http_var.get(), DEFAULT_CLIENT_CFG["preferred_http_port"])
        self.ccfg["preferred_tcp_port"] = _as_int(self.tcp_var.get(), DEFAULT_CLIENT_CFG["preferred_tcp_port"])
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        self.ccfg["subnets"] = subnets or list(DEFAULT_CLIENT_CFG["subnets"])
        self.ccfg["tightvnc_viewer_path"] = (self.vnc_path_var.get() or "").strip()
        self.ccfg["tightvnc_password"] = self.vnc_pass_var.get() or ""
        self.ccfg["tightvnc_port"] = _as_int(self.vnc_port_var.get(), DEFAULT_CLIENT_CFG["tightvnc_port"])

    def _sync_cfg_from_inputs(self):
        def _as_int(value, fallback):
            try:
                return int(value)
            except Exception:
                return fallback

        self.ccfg["key"] = self.key_var.get().strip() or DEFAULT_CLIENT_CFG["key"]
        self.ccfg["preferred_http_port"] = _as_int(self.http_var.get(), DEFAULT_CLIENT_CFG["preferred_http_port"])
        self.ccfg["preferred_tcp_port"] = _as_int(self.tcp_var.get(), DEFAULT_CLIENT_CFG["preferred_tcp_port"])
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        self.ccfg["subnets"] = subnets or list(DEFAULT_CLIENT_CFG["subnets"])
        self.ccfg["tightvnc_viewer_path"] = (self.vnc_path_var.get() or "").strip()
        self.ccfg["tightvnc_password"] = self.vnc_pass_var.get() or ""
        self.ccfg["tightvnc_port"] = _as_int(self.vnc_port_var.get(), DEFAULT_CLIENT_CFG["tightvnc_port"])

    def _sync_cfg_from_inputs(self):
        def _as_int(value, fallback):
            try:
                return int(value)
            except Exception:
                return fallback

        self.ccfg["key"] = self.key_var.get().strip() or DEFAULT_CLIENT_CFG["key"]
        self.ccfg["preferred_http_port"] = _as_int(self.http_var.get(), DEFAULT_CLIENT_CFG["preferred_http_port"])
        self.ccfg["preferred_tcp_port"] = _as_int(self.tcp_var.get(), DEFAULT_CLIENT_CFG["preferred_tcp_port"])
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        self.ccfg["subnets"] = subnets or list(DEFAULT_CLIENT_CFG["subnets"])
        self.ccfg["tightvnc_viewer_path"] = (self.vnc_path_var.get() or "").strip()
        self.ccfg["tightvnc_password"] = self.vnc_pass_var.get() or ""
        self.ccfg["tightvnc_port"] = _as_int(self.vnc_port_var.get(), DEFAULT_CLIENT_CFG["tightvnc_port"])

    # ---------- TXT ----------
    def _write_receivers_txt(self):
        try:
            lines = []
            seen = set()
            for k, m in sorted(self.discovered.items(), key=lambda kv: (kv[1].get("name") or "", kv[1].get("ip") or "")):
                ip = m.get("ip", "")
                name = (m.get("name") or "").strip()
                tcp = str(m.get("tcpPort", ""))
                http = str(m.get("httpPort", ""))
                sig = (ip, tcp)
                if sig in seen:
                    continue
                seen.add(sig)
                lines.append(f"{ip}\t{name}\t{tcp}\t{http}")
            path = self._txt_path()
            tmp = path + ".tmp"
            new_content = "\n".join(lines) + "\n"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    current_content = f.read()
                if current_content == new_content:
                    return
            except FileNotFoundError:
                current_content = None
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_content)
            os.replace(tmp, path)
            self.status.set(f"Alıcı listesi yazıldı: {path}")
        except Exception as e:
            self.status.set(f"alicilar.txt yazma hatası: {e}")
            return

        if self._update_known_receivers_cache():
            self._maybe_autosave_known(force=True, silent=True)

    def _build_known_receivers(self):
        entries = []
        seen = set()
        for _, meta in sorted(self.discovered.items(), key=lambda kv: (kv[1].get("name") or "", kv[1].get("ip") or "")):
            ip = meta.get("ip")
            if not ip:
                continue
            try:
                tcp = int(meta.get("tcpPort") or self.tcp_var.get())
            except Exception:
                tcp = int(self.tcp_var.get())
            try:
                http = int(meta.get("httpPort") or self.http_var.get())
            except Exception:
                http = int(self.http_var.get())
            sig = (ip, tcp)
            if sig in seen:
                continue
            seen.add(sig)
            entries.append({
                "ip": ip,
                "name": (meta.get("name") or ip).strip() or ip,
                "tcpPort": tcp,
                "httpPort": http,
                "last_seen": meta.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        return entries

    def _update_known_receivers_cache(self):
        entries = self._build_known_receivers()
        current = self.ccfg.get("known_receivers") or []
        if self._known_lists_equal(entries, current):
            return False
        self.ccfg["known_receivers"] = entries
        self._known_dirty = True
        return True

    def _known_lists_equal(self, new_entries, old_entries):
        if len(new_entries) != len(old_entries):
            return False

        def _normalize(entry):
            return {
                "ip": entry.get("ip"),
                "name": entry.get("name"),
                "tcpPort": int(entry.get("tcpPort") or 0),
                "httpPort": int(entry.get("httpPort") or 0),
            }

        for new, old in zip(new_entries, old_entries):
            if _normalize(new) != _normalize(old):
                return False

            new_seen = new.get("last_seen")
            old_seen = old.get("last_seen")
            if new_seen == old_seen:
                continue
            try:
                new_ts = time.strptime(new_seen, "%Y-%m-%d %H:%M:%S") if new_seen else None
                old_ts = time.strptime(old_seen, "%Y-%m-%d %H:%M:%S") if old_seen else None
            except Exception:
                return False
            if not new_ts or not old_ts:
                return False
            delta = abs(time.mktime(new_ts) - time.mktime(old_ts))
            if delta >= 60:
                return False
        return True

    def _maybe_autosave_known(self, force=False, silent=True):
        if not force and not self._known_dirty:
            return
        now = time.monotonic()
        if force or (now - self._last_known_save) >= 5.0:
            self._write_cfg_to_disk(silent=silent)

    # ---------- UI ----------
    def _make_ui(self):
        list_tab = None

        # Finder sekmesi doğrudan Notebook içinde kullanılıyorsa aynı sekme üzerinde çizim yap
        if self._external_notebook is not None:
            self._tab_notebook = None
            list_tab = self
            top_tab = getattr(self, "master", None) or self
        else:
            self._tab_notebook = ttk.Notebook(self)
            self._tab_notebook.pack(fill="both", expand=True)

            list_tab = ttk.Frame(self._tab_notebook)
            self._tab_notebook.add(list_tab, text="📋 Bulunanlar")
            top_tab = list_tab

        # Bu çerçeveyi, Notebook seçimleri için saklıyoruz
        self._top_tab_frame = top_tab

        top = tk.Frame(list_tab)
        top.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(top, text="Key:").grid(row=0, column=0, sticky="e")
        self.key_var = tk.StringVar(value=self.ccfg.get("key", "1234"))
        ttk.Entry(top, textvariable=self.key_var, width=10).grid(row=0, column=1, padx=(4, 14))

        tk.Label(top, text="HTTP:").grid(row=0, column=2, sticky="e")
        self.http_var = tk.IntVar(value=int(self.ccfg.get("preferred_http_port", 8088)))
        ttk.Entry(top, textvariable=self.http_var, width=6).grid(row=0, column=3, padx=(4, 14))

        tk.Label(top, text="TCP:").grid(row=0, column=4, sticky="e")
        self.tcp_var = tk.IntVar(value=int(self.ccfg.get("preferred_tcp_port", 5050)))
        ttk.Entry(top, textvariable=self.tcp_var, width=6).grid(row=0, column=5, padx=(4, 14))

        tk.Label(top, text="Subnets (virgülle):").grid(row=0, column=6, sticky="e")
        self.subnets_var = tk.StringVar(value=",".join(self.ccfg.get("subnets", [])))
        ttk.Entry(top, textvariable=self.subnets_var, width=28).grid(row=0, column=7, padx=(4, 0))

        vnc_frame = tk.Frame(list_tab)
        vnc_frame.pack(fill="x", padx=10, pady=(0, 6))
        vnc_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(vnc_frame, text="TightVNC Viewer Yolu:").grid(row=0, column=0, sticky="e")
        self.vnc_path_var = tk.StringVar(value=self.ccfg.get("tightvnc_viewer_path", DEFAULT_CLIENT_CFG["tightvnc_viewer_path"]))
        ttk.Entry(vnc_frame, textvariable=self.vnc_path_var).grid(row=0, column=1, sticky="we", padx=(4, 12))

        ttk.Label(vnc_frame, text="Şifre:").grid(row=1, column=0, sticky="e")
        self.vnc_pass_var = tk.StringVar(value=self.ccfg.get("tightvnc_password", ""))
        ttk.Entry(vnc_frame, textvariable=self.vnc_pass_var, show="*").grid(row=1, column=1, sticky="we", padx=(4, 12))

        ttk.Label(vnc_frame, text="Port:").grid(row=1, column=2, sticky="e")
        self.vnc_port_var = tk.IntVar(value=int(self.ccfg.get("tightvnc_port", 5900)))
        ttk.Entry(vnc_frame, textvariable=self.vnc_port_var, width=6).grid(row=1, column=3, padx=(4, 0))

        btns = tk.Frame(list_tab)
        btns.pack(fill="x", padx=10, pady=(0, 8))

        self.btn_listen = ttk.Button(btns, text="🟢 Otomatik Bul (Multicast) Başlat", command=self.toggle_listen)
        self.btn_listen.pack(side="left")

        ttk.Button(btns, text="⚡ Hızlı Tara", command=self.fast_scan).pack(side="left", padx=8)
        ttk.Button(btns, text="📝 Seçilene Ad Ver", command=self.rename_selected_any).pack(side="left", padx=(8, 0))

        self.save_known_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(btns, text="Bulunanları alicilar.txt dosyasına yaz", variable=self.save_known_var)\
            .pack(side="left", padx=(12, 0))

        ttk.Button(btns, text="🗒️ Alıcıları TXT'ye Yaz", command=self._write_receivers_txt)\
            .pack(side="left", padx=(8, 0))

        ttk.Button(btns, text="🔌 Açık Cihazlar Sekmesi", command=self.open_wall)\
            .pack(side="left", padx=(12, 0))

        ttk.Button(btns, text="➕ Manuel Ekle", command=self.add_manual_receiver)\
            .pack(side="left", padx=(12, 0))
        ttk.Button(btns, text="➖ Seçileni Sil", command=self.remove_selected)\
            .pack(side="left", padx=(8, 0))

        ttk.Button(btns, text="💾 client_config.json Kaydet", command=self._save_cfg).pack(side="right")

        self.send_unicast_on_scan = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            btns,
            text="Hızlı taramada IP’mi karşıya bildir (unicast)",
            variable=self.send_unicast_on_scan
        ).pack(side="left", padx=(12, 0))

        body = ttk.Panedwindow(list_tab, orient="vertical")
        body.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        table_frame = ttk.Frame(body)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)
        body.add(table_frame, weight=3)

        cols = ("name", "ip", "tcp", "http", "last_seen")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical")
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal")
        self.tv = ttk.Treeview(
            table_frame,
            columns=cols,
            show="headings",
            selectmode="extended",
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )
        yscroll.config(command=self.tv.yview)
        xscroll.config(command=self.tv.xview)
        self.tv.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        for c, t in zip(cols, ("Ad", "IP", "TCP", "HTTP", "Son Görülme")):
            self.tv.heading(c, text=t)
        self.tv.column("name", width=280, anchor="w")
        self.tv.column("ip", width=160, anchor="center")
        self.tv.column("tcp", width=70, anchor="center")
        self.tv.column("http", width=70, anchor="center")
        self.tv.column("last_seen", width=160, anchor="center")

        # Duvarı Bulunanlar sekmesinde, tablo ile paylaşılan bir alt panelde göster
        self._wall_holder = ttk.Frame(body)
        body.add(self._wall_holder, weight=2)
        self._wall_container = self._wall_holder
        if PIL_OK:
            self._ensure_wall_panel()
        else:
            self.wall = None
            warn = ttk.Frame(self._wall_container)
            warn.pack(fill="both", expand=True, padx=20, pady=20)
            ttk.Label(warn, text="Açık Cihazlar için Pillow (PIL) gerekli:\npip install pillow", justify="center").pack(expand=True)

        self.status = tk.StringVar(value="Hazır.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=10, pady=(0, 10))

        self.key_var.trace_add("write", self._on_key_changed)

    def _on_key_changed(self, *_):
        wall = self._ensure_wall_panel()
        if wall and wall.winfo_exists():
            wall.key = self.key_var.get().strip()

    def _ensure_wall_panel(self):
        if not PIL_OK:
            return None
        container = getattr(self, "_wall_container", None)
        if container is None or not container.winfo_exists():
            return None
        if self.wall and self.wall.winfo_exists():
            return self.wall
        for child in list(container.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        panel = WallPanel(container, finder=self, key=self.key_var.get().strip(), on_close=None, close_label=None)
        panel.pack(fill="both", expand=True)
        self.wall = panel
        return panel

    # ---------- known listesi (opsiyonel görüntü) ----------
    def _load_known_to_table(self):
        for m in self.ccfg.get("known_receivers", []):
            ip = m.get("ip")
            if not ip:
                continue
            name = m.get("name") or ip
            tcp = int(m.get("tcpPort", self.tcp_var.get()))
            http = int(m.get("httpPort", self.http_var.get()))
            k = f"{ip}:{tcp}"
            self.discovered[k] = {
                "name": name,
                "ip": ip,
                "tcpPort": tcp,
                "httpPort": http,
                "last_seen": m.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        self._refresh_table()

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- paylaşılmış keşif verisi ----------
    def _poll_shared_discovery(self):
        try:
            payload = self.shared.get("discovery_payload") if isinstance(self.shared, dict) else None
        except Exception:
            payload = None

        if isinstance(payload, dict):
            stamp = payload.get("timestamp")
            if stamp and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                entries = payload.get("entries") or {}
                source = payload.get("source") or "shared"
                if self._apply_shared_entries(entries, source):
                    if self.save_known_var.get():
                        self._write_receivers_txt()
                    if not self._shared_notice and source == "transfer":
                        self.status.set("Dosya Transferi sekmesinden gelen otomatik bulma sonuçları gösteriliyor.")
                        self._shared_notice = True

        # periyodik tekrar
        if self.winfo_exists():
            self.after(1000, self._poll_shared_discovery)

    def _apply_shared_entries(self, entries, source_tag):
        if not isinstance(entries, dict):
            return False
        changed = False
        seen = set()
        tag = f"shared:{source_tag}" if source_tag else "shared"
        for key, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            clone = dict(meta)
            clone.setdefault("name", clone.get("ip", ""))
            clone["tcpPort"] = int(clone.get("tcpPort") or self.tcp_var.get())
            clone["httpPort"] = int(clone.get("httpPort") or self.http_var.get())
            clone["last_seen"] = clone.get("last_seen") or time.strftime("%Y-%m-%d %H:%M:%S")
            clone["_source"] = tag
            seen.add(key)
            if self.discovered.get(key) != clone:
                self.discovered[key] = clone
                changed = True

        for key in list(self.discovered.keys()):
            meta = self.discovered.get(key)
            if isinstance(meta, dict) and meta.get("_source") == tag and key not in seen:
                del self.discovered[key]
                changed = True

        if changed:
            self.safe_refresh(delay_ms=80)
        return changed

    def _handle_listen_start_error(self, context, err):
        self._listening = False
        try:
            if self.btn_listen.winfo_exists():
                self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
        except Exception:
            pass

        msg = f"{context}: {err}"
        if isinstance(err, OSError):
            addr_in_use = (err.errno == errno.EADDRINUSE) or (getattr(err, "winerror", None) == 10048)
            if addr_in_use:
                if isinstance(self.shared, dict) and self.shared.get("discovery_payload"):
                    msg = ("Multicast portu kullanımda (muhtemelen Dosya Transferi sekmesi dinliyor). "
                           "O sekmeden paylaşılan liste kullanılacak.")
                else:
                    msg = "Multicast portu başka bir uygulama tarafından kullanılıyor."
        self.status.set(msg)

    # ---------- helpers ----------
    def _local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"

    def _call_update_unicast(self, ip, http_port, key):
        myip = self._local_ip()
        url = f"http://{ip}:{http_port}/api/update_config?" + urllib.parse.urlencode({"key": key, "add_unicast": myip})
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                _ = r.read()
            self.status.set(f"{ip} için TargetUnicast → {myip}")
            return True
        except Exception as e:
            self.status.set(f"update_config hatası/ulaşılamadı: {e}")
            return False

    def _call_update_name(self, ip, http_port, key, newname):
        if not newname or not newname.strip():
            return False, "Geçersiz ad"
        url = f"http://{ip}:{http_port}/api/update_config?" + urllib.parse.urlencode({"key": key, "name": newname.strip()})
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                _ = r.read()
            return True, "OK"
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", "ignore")
            except Exception:
                body = str(e)
            return False, f"HTTP {e.code}: {body}"
        except Exception as e:
            return False, str(e)

    # ---------- multicast ----------
    def toggle_listen(self):
        if self._listening:
            self._listening = False
            self.btn_listen.config(text="🟢 Otomatik Bul (Multicast) Başlat")
            self.status.set("Dinleme durduruldu.")
            return
        self._listening = True
        self.btn_listen.config(text="⏸ Durdur")
        self.status.set("Dinleniyor… (multicast)")
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        group = self.ccfg.get("listen_mcast_group", "239.0.0.250")
        port = int(self.ccfg.get("listen_mcast_port", 9999))
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", port))
        except OSError as e:
            self.after(0, lambda err=e: self._handle_listen_start_error("Multicast bind hatası", err))
            return

        mreq = struct.pack("4sl", socket.inet_aton(group), socket.INADDR_ANY)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError as e:
            self.after(0, lambda err=e: self._handle_listen_start_error("Multicast üyelik hatası", err))
            return

        sock.settimeout(2.0)

        while self._listening:
            try:
                # buffer'ı büyüttük
                data, _ = sock.recvfrom(65535)
                try:
                    j = json.loads(data.decode("utf-8", "ignore"))
                except Exception:
                    # Bazı sunucular birden çok JSON'u \n ile yolluyorsa:
                    parts = [p for p in data.decode("utf-8", "ignore").splitlines() if p.strip()]
                    ok = False
                    for p in parts:
                        try:
                            j = json.loads(p)
                            ok = True
                            break
                        except Exception:
                            continue
                    if not ok:
                        continue  # anlaşılmayan paket

                ip = j.get("ip")
                if not ip:
                    continue
                name = j.get("name") or ip
                tcp = int(j.get("tcpPort", self.tcp_var.get()))
                http = int(j.get("httpPort", self.http_var.get()))
                k = f"{ip}:{tcp}"

                meta = self.discovered.get(k, {})
                meta.update({
                    "name": name,
                    "ip": ip,
                    "tcpPort": tcp,
                    "httpPort": http,
                    "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                self.discovered[k] = meta

                # DİKKAT: Otomatik bulmada artık unicast GÖNDERMİYORUZ.
                # (İstek üzerine kaldırıldı.)

                self.safe_refresh()

            except socket.timeout:
                pass
            except Exception as e:
                self.after(0, lambda: self.status.set(f"Multicast hata: {e}"))

        try:
            sock.close()
        except Exception:
            pass

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

        if self._listening:
            # beklenmedik çıkışlarda düğmeyi sıfırla
            self.after(0, lambda: self._handle_listen_start_error("Multicast dinleme sonlandı", RuntimeError("Dinleme döngüsü sona erdi")))

    # ---------- hızlı tarama ----------
    def fast_scan(self):
        subnets = [s.strip() for s in self.subnets_var.get().split(",") if s.strip()]
        http_port = int(self.http_var.get())
        key = self.key_var.get().strip()
        self.status.set("Hızlı tarama başladı…")
        threading.Thread(target=self._scan_worker, args=(subnets, http_port, key), daemon=True).start()

    def _scan_worker(self, subnets, http_port, key):
        def check_ip(ip):
            try:
                url = f"http://{ip}:{http_port}/api/roots?" + urllib.parse.urlencode({"key": key})
                with urllib.request.urlopen(url, timeout=0.35) as r:
                    if r.status == 200:
                        return ip
            except Exception:
                return None

        found = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            fut = []
            for base in subnets:
                if "-" in base:
                    prefix, rng = base.rsplit(".", 1)
                    s, e = rng.split("-")
                    s = int(s); e = int(e)
                    for last in range(s, e + 1):
                        fut.append(ex.submit(check_ip, f"{prefix}.{last}"))
                elif base.count(".") == 2:
                    for last in range(1, 255):
                        fut.append(ex.submit(check_ip, f"{base}.{last}"))
                else:
                    fut.append(ex.submit(check_ip, base))

            for f in concurrent.futures.as_completed(fut):
                ip = f.result()
                if not ip:
                    continue
                k = f"{ip}:{int(self.tcp_var.get())}"
                self.discovered[k] = {
                    "name": ip,
                    "ip": ip,
                    "tcpPort": int(self.tcp_var.get()),
                    "httpPort": int(http_port),
                    "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                if getattr(self, "send_unicast_on_scan", None) and self.send_unicast_on_scan.get():
                    self._call_update_unicast(ip, http_port, key)
                self.safe_refresh()
                found.append(ip)

        if self.save_known_var.get():
            self._write_receivers_txt()
        self.after(0, lambda: self.status.set(f"Hızlı tarama bitti. Bulunan: {len(found)}"))

    # ---------- tablo yenileme ----------
    def _refresh_table(self):
        # TV mevcut değilse ya da yok olduysa (gizlenmiş/oluşturulmamış), sessizce çık
        tv = getattr(self, "tv", None)
        try:
            if tv is None or not tv.winfo_exists():
                return
        except Exception:
            return

        selected = set(tv.selection())
        y0, _ = tv.yview()
        existing = set(tv.get_children())
        keep = set()

        for k, m in sorted(self.discovered.items(), key=lambda kv: kv[1].get("name") or ""):
            vals = (m.get("name", ""), m.get("ip", ""), m.get("tcpPort", ""), m.get("httpPort", ""), m.get("last_seen", ""))
            if tv.exists(k):
                tv.item(k, values=vals)
            else:
                tv.insert("", "end", iid=k, values=vals)
            keep.add(k)

        for iid in (existing - keep):
            tv.delete(iid)

        still = [iid for iid in selected if tv.exists(iid)]
        if still:
            tv.selection_set(still)
        tv.yview_moveto(y0)

        if self.wall and self.wall.winfo_exists():
            self.wall.refresh_hosts(self.discovered)

        self._update_known_receivers_cache()
        self._maybe_autosave_known(silent=True)

    def safe_refresh(self, delay_ms=120):
        if self._rf_scheduled:
            return
        self._rf_scheduled = True

        def _do():
            try:
                self._refresh_table()
            finally:
                self._rf_scheduled = False

        self.after(delay_ms, _do)

    # ---------- UI actions ----------
    def rename_selected_any(self):
        """Seçim tabloya değil de Bulunanlar duvarında yapıldığında da yeniden adlandır."""
        # Önce tablo seçim var mı bak
        tv = getattr(self, "tv", None)
        tv_sel = []
        try:
            if tv is not None and tv.winfo_exists():
                tv_sel = list(tv.selection())
        except Exception:
            tv_sel = []
        if tv_sel:
            return self.rename_selected()

        # Duvardan seçimleri al
        wall_sel = []
        try:
            if self.wall and self.wall.winfo_exists():
                wall_sel = list(self.wall.get_selection_keys())
        except Exception:
            wall_sel = []

        if not wall_sel:
            messagebox.showinfo("Bilgi", "Lütfen en az bir sunucu seçin.")
            return

        for host_key in wall_sel:
            meta = self.discovered.get(host_key, {})
            ip = meta.get("ip")
            tcp = meta.get("tcpPort")
            http = meta.get("httpPort")
            name = meta.get("name") or ip or ""
            if not ip and isinstance(host_key, str) and ":" in host_key:
                ip = host_key.split(":", 1)[0]
            if tcp in (None, "") and isinstance(host_key, str) and ":" in host_key:
                try:
                    tcp = int(host_key.split(":", 1)[1])
                except Exception:
                    tcp = None
            if http in (None, ""):
                try:
                    http = int(self.http_var.get())
                except Exception:
                    http = 8088

            if not ip:
                continue
            newname = simpledialog.askstring("Ad Değiştir", f"{ip} için yeni ad:", initialvalue=name or "")
            if newname is None:
                continue
            ok, msg = self._call_update_name(ip, int(http), self.key_var.get().strip(), newname)
            if ok:
                try:
                    tcp_val = int(tcp) if tcp not in (None, "") else int(self.tcp_var.get())
                except Exception:
                    tcp_val = int(self.tcp_var.get())
                key = f"{ip}:{tcp_val}"
                if key in self.discovered:
                    self.discovered[key]["name"] = newname.strip()
                    self.discovered[key]["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._refresh_table()
                self.status.set(f"{ip} adı → {newname}")
                if self.save_known_var.get():
                    self._write_receivers_txt()
            else:
                messagebox.showerror("Hata", f"{ip}: {msg}")
    def rename_selected(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Bilgi", "Lütfen tabloda en az bir sunucu seçin.")
            return
        for iid in sel:
            vals = self.tv.item(iid, "values")
            if not vals or len(vals) < 4:
                continue
            cur_name, ip, tcp_str, http_str = vals[0], vals[1], vals[2], vals[3]
            try:
                http_port = int(http_str)
            except Exception:
                http_port = int(self.http_var.get())

            newname = simpledialog.askstring("Ad Değiştir", f"{ip} için yeni ad:", initialvalue=cur_name or "")
            if newname is None:
                continue

            ok, msg = self._call_update_name(ip, http_port, self.key_var.get().strip(), newname)
            if ok:
                key = f"{ip}:{int(tcp_str) if tcp_str else int(self.tcp_var.get())}"
                if key in self.discovered:
                    self.discovered[key]["name"] = newname.strip()
                    self.discovered[key]["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._refresh_table()
                self.status.set(f"{ip} adı → {newname}")
                if self.save_known_var.get():
                    self._write_receivers_txt()
            else:
                messagebox.showerror("Hata", f"{ip}: {msg}")

    def add_manual_receiver(self):
        default_tcp = int(self.tcp_var.get())
        default_http = int(self.http_var.get())

        ip = simpledialog.askstring("Manuel Alıcı Ekle", "IP adresi:")
        if not ip:
            return
        ip = ip.strip()
        if not ip:
            return

        name = simpledialog.askstring("Manuel Alıcı Ekle", "Ad (opsiyonel):", initialvalue=ip) or ""
        tcp_str = simpledialog.askstring("Manuel Alıcı Ekle", "TCP portu:", initialvalue=str(default_tcp))
        http_str = simpledialog.askstring("Manuel Alıcı Ekle", "HTTP portu:", initialvalue=str(default_http))

        try:
            tcp = int(tcp_str) if tcp_str else default_tcp
        except Exception:
            messagebox.showerror("Hata", "TCP portu sayısal olmalıdır.")
            return

        try:
            http = int(http_str) if http_str else default_http
        except Exception:
            messagebox.showerror("Hata", "HTTP portu sayısal olmalıdır.")
            return

        key = f"{ip}:{tcp}"
        self.discovered[key] = {
            "name": name.strip() or ip,
            "ip": ip,
            "tcpPort": tcp,
            "httpPort": http,
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._refresh_table()

        if self.save_known_var.get():
            self._write_receivers_txt()

        self.status.set(f"Manuel alıcı eklendi: {ip}")

    def remove_selected(self):
        sel = list(self.tv.selection())
        if (not sel) and self.wall and self.wall.winfo_exists():
            try:
                sel = list(self.wall.get_selection_keys())
            except Exception:
                sel = []
        if not sel:
            messagebox.showinfo("Bilgi", "Silmek için lütfen tabloda en az bir satır seçin.")
            return

        removed = 0
        for iid in sel:
            if iid in self.discovered:
                del self.discovered[iid]
                removed += 1

        if not removed:
            return

        self._refresh_table()

        if self.save_known_var.get():
            self._write_receivers_txt()

        self.status.set(f"{removed} kayıt silindi.")

    # ---------- Açık Cihazlar ----------
    def open_wall(self):
        if not PIL_OK:
            messagebox.showwarning("Pillow gerekli", "Açık Cihazlar sekmesi için Pillow (PIL) gerekli:\n\npip install pillow")
            return

        panel = self._ensure_wall_panel()
        if not panel or not panel.winfo_exists():
            self.status.set("Açık Cihazlar paneli başlatılamadı.")
            return

        notebook = self._external_notebook or getattr(self, "_tab_notebook", None)
        # Artık duvar, Bulunanlar sekmesinin içinde. Notebook varsa o sekmeyi seçelim.
        if notebook:
            tab = getattr(self, "_top_tab_frame", None)
            if tab is not None:
                try:
                    notebook.select(tab)
                    notebook.update_idletasks()
                except Exception:
                    pass


class WallPanel(tk.Frame):
    """Küçük anlık görüntüler duvarı.
       - Her host için ~4 sn yenileme
       - İstekler kademeli
       - 260px genişlik, JPEG kalite 45 (sunucuda /api/shot ile)
    """
    THUMB_W = 260
    REFRESH_MS = 4000
    STAGGER_MS = 250

    def __init__(self, master, finder: "FinderTab", key: str, on_close=None, close_label="Kapat"):
        super().__init__(master)
        self._finder = finder
        self._on_close = on_close
        self._close_label = close_label
        self.key = key
        self.items = {}   # hostKey -> dict(frame, img_label, name_lbl, ip, http, photo)
        self.selected = set()

        # kaydırılabilir alan
        outer = tk.Frame(self)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_host = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.grid_host, anchor="nw")
        self.grid_host.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # Boş alana tıklanınca seçimleri temizle (sadece duvar alanında)
        try:
            self.canvas.bind("<Button-1>", self._on_wall_background_click, add="+")
            self.grid_host.bind("<Button-1>", self._on_wall_background_click, add="+")
        except Exception:
            pass

        # üst bar
        top = tk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Kalite (q):").pack(side="left", padx=(8, 2))
        self.q_var = tk.IntVar(value=45)
        ttk.Entry(top, textvariable=self.q_var, width=4).pack(side="left")
        ttk.Label(top, text="Genişlik (w):").pack(side="left", padx=(8, 2))
        self.w_var = tk.IntVar(value=self.THUMB_W)
        ttk.Entry(top, textvariable=self.w_var, width=5).pack(side="left")
        ttk.Button(top, text="Yenile", command=self.full_refresh).pack(side="left", padx=8)
        if callable(self._on_close):
            ttk.Button(top, text=self._close_label, command=self._on_close).pack(side="right", padx=(0, 8))

        self.column_count = 5
        self.after(200, self._auto_resize_columns)

        # ilk doldurma
        self.refresh_hosts(finder.discovered)

        self.bind("<Destroy>", self._notify_destroy, add="+")

    def _notify_destroy(self, event):
        if event.widget is self and getattr(self._finder, "wall", None) is self:
            self._finder.wall = None

    def _auto_resize_columns(self):
        w = self.winfo_width()
        per = self.THUMB_W + 28
        cols = max(3, min(8, w // per))
        if cols != self.column_count:
            self.column_count = cols
            self._regrid()
        self.after(800, self._auto_resize_columns)

    def refresh_hosts(self, discovered: dict):
        keys = sorted(discovered.keys(), key=lambda k: (discovered[k].get("name") or "", discovered[k].get("ip") or ""))
        existing = set(self.items.keys())
        keep = set()

        for k in keys:
            m = discovered[k]
            ip = m.get("ip")
            http = int(m.get("httpPort", 8088))
            name = m.get("name") or ip
            vnc_port = self._resolve_vnc_port(m)
            if k not in self.items:
                fr = tk.Frame(self.grid_host, bd=1, relief="solid")
                nm = tk.Label(fr, text=name, anchor="w")
                nm.pack(fill="x")
                img = tk.Label(fr, text="(yükleniyor)" if PIL_OK else "Pillow gerekli")
                img.pack()
                ipport = tk.Label(fr, text=f"{ip}:{http}", fg="#666")
                ipport.pack()
                self.items[k] = {
                    "frame": fr,
                    "name_lbl": nm,
                    "img_label": img,
                    "ip": ip,
                    "http": http,
                    "photo": None,
                    "vnc_port": vnc_port,
                    "ipport_lbl": ipport,
                    "selected": False,
                }
                for widget in (fr, nm, img, ipport):
                    self._bind_wall_item(widget, k)
                self._apply_item_selected_state(k)
            else:
                self.items[k]["name_lbl"].config(text=name)
                self.items[k]["ip"] = ip
                self.items[k]["http"] = http
                self.items[k]["vnc_port"] = vnc_port
                self._apply_item_selected_state(k)
            keep.add(k)

        for k in list(existing - keep):
            self.items[k]["frame"].destroy()
            del self.items[k]
            self.selected.discard(k)

        self._regrid()

        if PIL_OK:
            delay = 0
            for k in keys:
                self.after(delay, lambda kk=k: self._schedule_fetch(kk))
                delay += self.STAGGER_MS

    def _regrid(self):
        for i, (k, item) in enumerate(self.items.items()):
            r = i // self.column_count
            c = i % self.column_count
            item["frame"].grid(row=r, column=c, padx=6, pady=6, sticky="nsew")

    def _bind_wall_item(self, widget, hostKey):
        if widget is None:
            return
        try:
            widget.configure(cursor="hand2")
        except Exception:
            pass
        widget.bind("<Double-Button-1>", lambda e, hk=hostKey: self._handle_double_click(hk), add="+")
        widget.bind("<Button-1>", lambda e, hk=hostKey: self._toggle_select(hk), add="+")

    def _on_wall_background_click(self, event):
        """Duvar içinde, herhangi bir öğe üzerinde olmayan tıklamada seçimleri temizle."""
        try:
            target = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            target = None

        # Hedef bir öğe veya onun alt bileşeni ise, temizleme yapma
        if target is not None:
            if self._is_widget_of_any_item(target):
                return

        # Aksi halde (boş alan), seçimi temizle
        self.clear_selection()

    def _is_widget_of_any_item(self, widget):
        """Widget, herhangi bir öğe frame'inin altında mı?"""
        try:
            frames = [d.get("frame") for d in self.items.values()]
        except Exception:
            frames = []
        w = widget
        limit = 0
        while w is not None and limit < 64:
            if w in frames:
                return True
            # grid_host'a kadar geldiysek ve eşleşme yoksa, öğe değildir
            if w is self.grid_host:
                return False
            try:
                w = w.master
            except Exception:
                break
            limit += 1
        return False

    def _apply_item_selected_state(self, hostKey):
        item = self.items.get(hostKey)
        if not item:
            return
        sel = hostKey in self.selected
        bg = "#cde8ff" if sel else None
        try:
            item["frame"].configure(bg=bg)
        except Exception:
            pass
        for lbl_key in ("name_lbl", "img_label", "ipport_lbl"):
            w = item.get(lbl_key)
            if w is not None:
                try:
                    w.configure(bg=bg)
                except Exception:
                    pass

    def _toggle_select(self, hostKey):
        if hostKey in self.selected:
            self.selected.remove(hostKey)
        else:
            self.selected.add(hostKey)
        self._apply_item_selected_state(hostKey)

    def clear_selection(self):
        for k in list(self.selected):
            self._apply_item_selected_state(k)
        self.selected.clear()

    def get_selection_keys(self):
        return list(self.selected)

    def _resolve_vnc_port(self, meta):
        if meta:
            candidate = meta.get("vncPort") if isinstance(meta, dict) else None
            if candidate is None and isinstance(meta, dict):
                candidate = meta.get("tightvnc_port")
            if candidate not in (None, ""):
                try:
                    return int(candidate)
                except Exception:
                    pass
        finder = self._finder
        if hasattr(finder, "vnc_port_var"):
            try:
                return int(finder.vnc_port_var.get())
            except Exception:
                pass
        try:
            return int(finder.ccfg.get("tightvnc_port", 5900))
        except Exception:
            return 5900

    def _handle_double_click(self, hostKey):
        item = self.items.get(hostKey)
        if not item:
            return
        ip = item.get("ip")
        if not ip:
            messagebox.showerror("TightVNC", "Seçilen host için IP bilgisi bulunamadı.")
            return
        if not sys.platform.startswith("win"):
            messagebox.showinfo("TightVNC", "TightVNC ile doğrudan bağlanma yalnızca Windows üzerinde desteklenir.")
            return

        finder = self._finder
        viewer_path = ""
        if hasattr(finder, "vnc_path_var"):
            try:
                viewer_path = finder.vnc_path_var.get().strip()
            except Exception:
                viewer_path = ""
        if not viewer_path:
            viewer_path = (finder.ccfg.get("tightvnc_viewer_path") or "").strip()
        if not viewer_path:
            messagebox.showerror("TightVNC", "Lütfen client_config ayarlarında TightVNC Viewer yolunu tanımlayın.")
            return

        if os.path.isdir(viewer_path):
            viewer_path = os.path.join(viewer_path, "tvnviewer.exe")

        if not os.path.exists(viewer_path):
            messagebox.showerror("TightVNC", f"TightVNC Viewer bulunamadı:\n{viewer_path}")
            return

        password = ""
        if hasattr(finder, "vnc_pass_var"):
            try:
                password = finder.vnc_pass_var.get()
            except Exception:
                password = ""
        if not password:
            password = finder.ccfg.get("tightvnc_password", "")
        if not password:
            messagebox.showwarning("TightVNC", "client_config.json içinde TightVNC şifresi tanımlı değil.")
            return

        port = item.get("vnc_port")
        if port in (None, ""):
            port = self._resolve_vnc_port(None)
        try:
            port = int(port)
        except Exception:
            port = 5900

        target = f"{ip}::{port}"
        args = [viewer_path, target, f"-password={password}"]
        try:
            subprocess.Popen(args)
            if hasattr(finder, "status"):
                finder.status.set(f"TightVNC açılıyor: {target}")
        except FileNotFoundError:
            messagebox.showerror("TightVNC", f"TightVNC Viewer çalıştırılamadı, dosya bulunamadı:\n{viewer_path}")
        except Exception as e:
            messagebox.showerror("TightVNC", f"TightVNC Viewer başlatılamadı:\n{e}")

    def _schedule_fetch(self, hostKey):
        if hostKey not in self.items:
            return
        t = threading.Thread(target=self._fetch_once, args=(hostKey,), daemon=True)
        t.start()

    def _fetch_once(self, hostKey):
        if hostKey not in self.items:
            return
        it = self.items[hostKey]
        ip, http = it["ip"], it["http"]
        w = max(120, min(1280, int(self.w_var.get() or self.THUMB_W)))
        q = max(1, min(95, int(self.q_var.get() or 45)))
        url = f"http://{ip}:{http}/api/shot?" + urllib.parse.urlencode({"w": w, "q": q, "key": self.key})
        try:
            req = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
            with urllib.request.urlopen(req, timeout=1.8) as r:
                data = r.read()
            self.after(0, lambda: self._apply_image(hostKey, data))
        except Exception:
            self.after(0, lambda: it["img_label"].config(text="(erişilemedi)"))
        finally:
            self.after(self.REFRESH_MS, lambda: self._schedule_fetch(hostKey))

    def _apply_image(self, hostKey, raw):
        if hostKey not in self.items:
            return
        it = self.items[hostKey]
        try:
            from io import BytesIO
            img = Image.open(BytesIO(raw))
            photo = ImageTk.PhotoImage(img)
            it["photo"] = photo
            it["img_label"].config(image=photo, text="")
        except Exception:
            it["img_label"].config(text="(görüntü hatası)")

    def full_refresh(self):
        for k in list(self.items.keys()):
            self._schedule_fetch(k)


# --------------------------------------------------
if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("1000x640")
    root.minsize(920, 560)

    finder = FinderTab(root, shared={})
    finder.pack(fill="both", expand=True)

    root.mainloop()
