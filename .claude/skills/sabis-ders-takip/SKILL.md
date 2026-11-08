---
name: sabis-ders-takip
description: Sakarya Üniversitesi SABİS/OBS ders takibi. SABİS duyurularını ve ödevlerini scraper ile lectures/*.md dosyalarına çeker, ders notlarını bu dosyalarda tutar, yaklaşan ödev/sunum/sınav özeti çıkarır ve duyuruda olmayan eksik bilgileri kullanıcıya sorar. Kullanıcı "derslerim ne durumda", "hangi ödev yakın", "özet ver", "SABİS'i güncelle", "duyuruları çek", "X dersi için not al", "sunum ne zamandı", "bekleyen bilgiler" gibi bir şey dediğinde veya /sabis-ders-takip yazdığında kullan.
---

# SABİS ders takibi

Amaç: çalışan bir öğrencinin ödev, sunum, sınav ve ders notlarını tek yerde tutmak. Böylece dönem ortasında "neyi kaçırdım" yığılması olmaz.
Her ders için tek kaynak `lectures/<KOD>-<ders-adi>.md` dosyasıdır.

## Dosya düzeni

```
.env                      # SABIS_KULLANICI / SABIS_SIFRE. ASLA okuma, yazdırma, içeriğini gösterme.
scraper/sabis_scraper.py  # SABİS'ten çeker, lectures/ altını günceller
lectures/
  _son_calisma.md         # son çalışmanın özeti: yeni duyurular, SABİS ödev teslimleri, sınav takvimi
  <KOD>-<ad>.md           # ders başına not dosyası
  .data/<KOD>.json        # duyuru arşivi (hoca silse bile saklanır) + ham veri
```

Her ders dosyasında iki bölüm vardır:

- `<!-- NOTLAR:BASLA -->` … `<!-- NOTLAR:BITIR -->`: kullanıcının ve Claude'un bölümü. Scraper buraya **asla** dokunmaz. Notları yalnızca buraya yaz.
- `<!-- OTO:BASLA … -->` … `<!-- OTO:BITIR -->`: scraper'ın bölümü. Her çalışmada yeniden yazılır. **Elle düzenleme**, yazdığın her şey silinir.

NOTLAR bölümünün alt başlıkları:

1. `### 📌 Yaklaşan işler`: tablo `| İş | Tür | Son tarih | Durum | Kaynak |`
   - **Tür:** Ödev · Sunum · Sınav · Proje · Görev · Devam · Diğer
   - **Son tarih:** `YYYY-MM-DD HH:MM` (saat bilinmiyorsa `YYYY-MM-DD`, tarih bilinmiyorsa `❓`)
   - **Durum:** ⏳ Bekliyor · 🔄 Devam ediyor · ✅ Bitti · ❌ Kaçtı
   - **Kaynak:** `SABİS duyuru 2026-10-27`, `SABİS ödev`, `Derste söylendi`, `WhatsApp grubu`, `Kullanıcı` …
   - Tablo, ileride takvim ve hatırlatıcı entegrasyonunun da tek kaynağıdır. Tarihleri her zaman bu biçimde tut.
2. `### ❓ Bekleyen bilgiler (sorulacak)`: `- [ ]` maddeleri. Kullanıcıdan cevap bekleyen sorular.
3. `### 📝 Ders notları`: `- YYYY-MM-DD: not` biçiminde, en yenisi en üstte.

## İş akışları

### 1. Güncelleme ("SABİS'i güncelle", "duyuruları çek")

1. `lectures/_son_calisma.md` dosyasının başlığındaki tarihe bak. Bugün zaten çalıştıysa tekrar çalıştırma (ban riski, günde en fazla 1 kez), mevcut veriyle devam et. Kullanıcı yine de isterse çalıştır.
2. Proje kökünde çalıştır: `python scraper/sabis_scraper.py`. Yaklaşık 1-2 dakika sürer, istekler arasında 2-3 saniye bekler.
   - `.env` yoksa kullanıcıdan `.env.example` dosyasını `.env` olarak kopyalayıp doldurmasını iste. Şifreyi sohbete yazmasını isteme.
   - "Giriş başarısız" hatası alırsan kullanıcı adı ve şifreyi kontrol etmesini söyle. Başka bir hata alırsan çıktıyı göster. SABİS'in HTML yapısı değişmiş olabilir; `scraper/sabis_scraper.py` içindeki `parse_*` fonksiyonlarını güncellemek gerekebilir.
3. `_son_calisma.md` dosyasını oku. Yeni duyuruların her biri için ilgili ders dosyasının OTO bölümünü oku ve **NOTLAR'a yansıt**:
   - Tarih, ödev, sunum, sınav, ders iptali veya derslik değişikliği varsa `Yaklaşan işler` tablosuna ekle ya da güncelle.
   - Duyuru bir şeyi belirsiz bırakıyorsa `Bekleyen bilgiler` altına soru ekle. Örnekler: "sunum tarihleri ekte" denip ek okunamıyorsa, ödev konusu yazılmamışsa, teslim formatı belli değilse, "WhatsApp grubundan görev" deniyorsa.
   - SABİS Ödevler tablosunda "⚠️ yüklenmedi" olan ve süresi dolmamış ödevleri mutlaka `Yaklaşan işler`e ekle.
4. Ardından 2. akıştaki özeti ver ve 3. akıştaki soruları sor.

### 2. Özet ("ne durumdayım", "hangi ödev yakın", "özet ver")

Tüm `lectures/*.md` dosyalarını oku (NOTLAR + OTO) ve **bugünün tarihine göre** şu sırayla, kısa bir özet ver:

1. 🔴 **Süresi geçmiş, bitmemiş:** Durumu ✅ olmayan ve tarihi geçmiş işler. Kaçtı mı, hâlâ teslim edilebilir mi diye sor.
2. 🟠 **Bu hafta (≤7 gün):** Tarih, ders, iş ve kalan gün. SABİS yükleme durumu 0/x ise belirt.
3. 🟡 **Önümüzdeki 2-4 hafta.**
4. 🎤 **Sunumlar** ve 📝 **Sınavlar** ayrı başlıkta. Tarihi `❓` olanları da listele.
5. 🗓️ **Ders düzeni değişiklikleri:** İptal, online ders, derslik değişikliği ve devam zorunluluğu (yakın tarihli olanlar).
6. ❓ **Bekleyen bilgi sayısı.** Ardından 3. akışa geç.

Biçim: tablo veya kısa madde listesi kullan, her satırda ders kodunu yaz. Uzun duyuru metinlerini tekrar etme, sadece eyleme dönük bilgiyi ver.
Tarih hesabını dikkatli yap: duyurularda yıl yazmaz. Scraper yılı tahmin eder, metindeki tarihler ("17 Kasım 2026 Salı") her zaman önceliklidir.

### 3. Eksik bilgileri sorma

SABİS'te olmayan ama hocanın derste veya WhatsApp'ta söylemiş olabileceği bilgileri kullanıcıya sor:

- Tüm dosyalardaki işaretlenmemiş `- [ ]` maddelerini topla ve tarih yakınlığına göre sırala.
- Bir seferde **en fazla 4 soru** sor. AskUserQuestion aracı varsa onu kullan, her soruya "Bilmiyorum / sonra sor" seçeneği ekle. Yoksa numaralı liste halinde sor.
- Cevap gelince ilgili dosyada `- [ ]` yerine `- [x] … → cevap (YYYY-MM-DD)` yaz. Bilgiyi `Yaklaşan işler` tablosuna veya `Ders notları`na da işle, Kaynak: `Kullanıcı (derste söylendi)`.
- "Bilmiyorum" cevabında maddeyi açık bırak, sonuna `(sorulma: YYYY-MM-DD)` ekle. Aynı gün tekrar sorma.

### 4. Not alma ("X dersi için not: …", "BSM515'te hoca şunu dedi …")

1. Dersi bul: kod (BSM515), ders adının bir parçası ("nesneye", "bulanık") veya hoca adı. Belirsizse sor.
2. Notu `### 📝 Ders notları` başına `- YYYY-MM-DD: …` biçiminde ekle (bugünün tarihi).
3. Notta tarih, teslim, sunum, sınav veya konu bilgisi varsa `Yaklaşan işler` tablosunu da güncelle. Bir bekleyen soruyu cevaplıyorsa onu `[x]` yap.
4. "Ödevi bitirdim", "sunumu yaptım" gibi durum bildirimlerinde tablodaki Durum'u güncelle.
5. Kullanıcıya ne değiştirdiğini tek satırla söyle.

## Takip dışı dersler

Kullanıcı bir ders için "bu ders yok", "boş", "etkisi yok" derse:

1. O dosyada `<!-- NOTLAR:BASLA -->` satırının hemen altına `<!-- TAKIP:YOK -->` ekle.
2. Altına `> 🚫 **Takip dışı:** …` notunu yaz ve bekleyen soruları kapat.

Bu derslerin işleri özetlere girmez, onlar hakkında soru sorulmaz. Scraper `_son_calisma.md` dosyasında bu dersleri ayrı listeler. Takip dışı bir derste yeni duyuru veya ödev çıkarsa ⚠️ ile uyarır, bu uyarıyı kullanıcıya ilet.

## Kurallar

- `.env` dosyasını asla okuma, gösterme veya commit etme. Şifreyi asla sohbette isteme.
- OTO bölümünü asla elle düzenleme. NOTLAR işaretlerini (`<!-- NOTLAR:BASLA -->`, `<!-- NOTLAR:BITIR -->`) silme.
- Scraper'ı günde en fazla 1 kez çalıştır.
- Ek dosyalar (`dl.sabis.sakarya.edu.tr/u/...` linkleri) oturum gerektirebilir, içeriklerini okuyamayabilirsin. "Ekte" denen tarih veya konu bilgisini kullanıcıya sor.
- Yeni bir ders dosyası scraper tarafından oluşturulduğunda NOTLAR şablonu boş gelir. İlk fırsatta o dersin duyurularından `Yaklaşan işler` ve `Bekleyen bilgiler` bölümlerini doldur.
