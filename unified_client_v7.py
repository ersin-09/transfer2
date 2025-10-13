# unified_client_v7.py
import tkinter as tk
from tkinter import ttk

# modülleri import et
import client_gui_v6 as cg   # içinde AppTab olacak
import receiver_finder as rf # içinde FinderTab olacak

def main():
    root = tk.Tk()
    root.title("Dosya Transferi + Alıcı Bulucu (Birleşik)")
    root.geometry("1280x800")

    # Ortak ayarlar (iki yönlü paylaşılacak sözlük)
    shared = {
        "key": "1234",
        "http_port": 8088,
        "tcp_port": 5050,
        "subnets": ["192.168.1"],  # list de olabilir, Finder tarafı virgülle gösterir
    }

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)

    # --- Bulucu sekmesi ve bağlı paneller ---
    frame_finder = ttk.Frame(nb)
    frame_finder.pack(fill="both", expand=True)
    finder_tab = rf.FinderTab(frame_finder, shared, notebook=nb)
    finder_tab.pack(fill="both", expand=True)
    nb.add(frame_finder, text="📡 Alıcı Bulucu")

    # --- Transfer sekmesi ---
    frame_transfer = ttk.Frame(nb)
    frame_transfer.pack(fill="both", expand=True)
    transfer_tab = cg.AppTab(frame_transfer, shared)
    transfer_tab.pack(fill="both", expand=True)
    nb.add(frame_transfer, text="💻 Dosya Transferi")

    # Basit senkronizasyon örneği:
    # Finder tabındaki Key/Port/Subnets değişince shared güncellenirse,
    # transfer_tab bunları shared'den kullanır; istersen event/callback ile UI'yı da güncellersiniz.

    root.mainloop()

if __name__ == "__main__":
    main()
