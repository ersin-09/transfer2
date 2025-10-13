# PR'yi Yeniden Oluşturma Rehberi

Bu depo üzerinde daha önce hazırlanan değişiklikleri GitHub'da yeniden bir pull request (PR) olarak
paylaşmakta zorlanıyorsan aşağıdaki adımları izleyebilirsin. Komutlar varsayılan olarak
`work` adlı yerel dal üzerinde çalışıldığını kabul eder.

## 1. Çalışma alanını temizle

```bash
git status
```

Çıktıda "working tree clean" görmelisin. Eğer takip edilmeyen dosyalar veya değişiklikler varsa
yedek aldıktan sonra aşağıdaki komutla onları sıfırlayabilirsin:

```bash
git reset --hard
```

## 2. Doğru dalda olduğundan emin ol

```bash
git checkout work
```

## 3. Uzak depodan son durumu al

```bash
git fetch origin
```

Bu adım, GitHub'daki `work` dalında senin yerelinde bulunmayan commit'ler varsa onları indirir.

## 4. Gerekirse commit'i tekrar uygula

Eğer "Share discovery data between tabs" başlıklı commit'i yeniden uygulaman gerekiyorsa
öncelikle hash değerini bul:

```bash
git log --oneline --grep "Share discovery data between tabs"
```

Komut çıktı olarak örneğin `abc1234 Share discovery data between tabs` benzeri bir satır verir.
Bu hash değerini kullanarak commit'i mevcut dala tekrar ekleyebilirsin:

```bash
git cherry-pick abc1234
```

Birden fazla commit gerekiyorsa her biri için `cherry-pick` çalıştırabilirsin.

## 5. Değişiklikleri doğrula

Kodun derlenip derlenmediğini kontrol etmek için daha önce kullanılan derleme komutlarını tekrar
çalıştır:

```bash
python -m compileall client_gui_v6.py receiver_finder.py
```

## 6. Değişiklikleri GitHub'a gönder

Commit'lerin hazır olduğunda bunları uzak depoya aktarmak için:

```bash
git push origin work
```

Eğer GitHub'daki dal senin yerel commit'lerinden geri kalmışsa ve push reddedilirse mevcut durumu
zorla güncellemek için (diğer ekip arkadaşlarının bu dal üzerinde çalışmadığından emin ol):

```bash
git push --force-with-lease origin work
```

## 7. Pull request'i yeniden aç

GitHub'da depo sayfasına gidip `Compare & pull request` düğmesini kullanarak yeni bir PR
oluşturabilirsin. Daha önce kapattığın PR'ın referansını açıklama kısmına eklemek, yapılan
çalışmayı takip etmeyi kolaylaştırır.

Bu adımlar sırasında hata alırsan komutların tam çıktısını not ederek tekrar denemeden önce
soruna uygun çözümü arayabilir veya burada paylaşabilirsin.
