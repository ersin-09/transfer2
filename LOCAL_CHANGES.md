# Local Depo Güncellemeleri

Bu çalışma alanında aşağıdaki düzenlemeler uygulanmış durumdadır:

- `receiver_finder.py` içinde "Canlı Duvar" artık aynı Tk penceresinde ayrı bir sekme olarak
  açılabiliyor; sekme kapatıldığında `FinderTab` referansları temizleniyor ve tekrar açılabiliyor.
- Canlı Duvar küçük resimlerine çift tıklandığında Windows üzerinde TightVNC Viewer otomatik
  olarak açılıp seçilen makineye bağlanıyor; yol, port ve şifre `client_config.json` üzerinden
  yönetilebiliyor (varsayılan yol `C:\Program Files\TightVNC\tvnviewer.exe`, klasör seçilirse
  dosya adı otomatik eklenir).
- Finder sekmesi artık otomatik keşif sonuçlarını Dosya Transferi sekmesiyle paylaşıyor; böylece
  aynı anda çalışan iki sekmede multicast portu çakışsa bile transfer sekmesinin yakaladığı
  alıcı listesi Finder tablosuna düşüyor.
- `client_gui_v6.py` dosyasında Transfer sekmesi keşif sonuçlarını ortak `shared` sözlüğüne
  aktarıyor.
- Finder ve Transfer sekmeleri üst düzey Tk penceresi üzerinde başlık/boyut ayarlayarak sekme
  veya bağımsız kullanımda tutarlı davranıyor.
- Standart başlatıcı, Tk kök penceresi oluşturup `FinderTab` bileşenini yerleştiriyor.
- Dosya Transferi sekmesindeki "Sunucu Güncelle" işlemi artık yeni EXE'yi doğrudan sunucunun
  `/api/update` uç noktasına HTTP üzerinden gönderip ilerlemeyi gösteriyor; işlem bittiğinde
  sunucu Windows'ta ek yetki gerektirmeden kendi kendini kapatıp yeni dosyayı yerine taşıyarak
  yeniden başlatıyor.
- Transfer sekmesinin üst çubuğundaki Yenile/TARA/Upload/Download/Güncelle butonları otomatik
  genişlikli stile alındı; böylece düğmeler gereksiz yatay alan kaplamadan daha kompakt
  görünüyor.

Bu değişiklikler yerel Git deposunda commitlenmiş hâlde bulunuyor. GitHub deposunda görünmeleri
için aşağıdaki adımları izleyebilirsin:

1. Gerekirse ek düzenlemelerini yap ve `git status` ile kontrol et.
2. `git push origin work` komutunu çalıştırarak `work` dalındaki commit'i GitHub'a gönder.
3. GitHub'da bu commit'i içeren bir pull request açarak ana dala dahil edebilirsin.

> **İpucu:** Daha önce açtığın PR'ı yeniden oluşturman gerekiyorsa ayrıntılı yönergeler için
> `PR_RECREATE_GUIDE.md` dosyasına göz atabilirsin.

> Not: Bu ortamda benim yaptığım commitler otomatik olarak uzaktaki depoya gönderilmez; `git push`
işlemini senin çalıştırman gerekir.
