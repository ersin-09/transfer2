
# Dosya Transferi v6 – Otomatik IP Ayarlama (Sunucu Kendini Günceller)

- **İstemci (GUI)**: Hızlı Tarama sonrası her bulunan alıcıya `sender_<IP>.txt` gönderir. Hedef klasör: sunucunun **çalışma dizini** ('.').
- **Sunucu**: `sender_*.txt` dosyası geldiği anda veya çalışma dizininde belirdiği an
  `server_config.json` dosyasındaki `announce.target_unicast` alanını **yalnızca bu IP** olacak şekilde değiştirir ve hemen bellek içinde uygular.
- Eski IP'ler silinir, sadece en son gelen IP kalır.

Değiştirilen dosyalar:
- `client_gui_v6.py` (uzaktan dizin '.' yapıldı ve tarama sonrası IP gönderimi garantilendi)
- `transfer_server_v6.go` (sender dosyası algılama, config güncelleme, arka plan watcher)

Her şey hazırdır; diğer dosyalar değişmemiştir.
