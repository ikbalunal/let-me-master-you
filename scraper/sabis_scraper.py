"""
SABİS (Sakarya Üniversitesi OBS) ders duyurusu / ödev scraper'ı.

Ne yapar?
  1. .env dosyasından SABIS_KULLANICI ve SABIS_SIFRE okur, SABİS'e giriş yapar.
  2. "Seçilen Dersler" (/Ders) sayfasındaki tüm dersleri bulur.
  3. Her ders için: ders bilgileri, Duyurular, Ödevler (+ ödev detayı) ve Sınavlar sekmelerini çeker.
  4. lectures/<KOD>-<ders-adi>.md dosyalarını oluşturur / günceller.
     - Dosyadaki "NOTLAR" bölümüne (senin ve Claude'un notları) ASLA dokunmaz.
     - Sadece "OTO" (otomatik) bölümünü yeniden yazar.
  5. Daha önce görülen duyuruları lectures/.data/ altında saklar; hoca silse bile kaybolmaz.
  6. lectures/_son_calisma.md dosyasına bu çalışmadaki yenilikleri ve yaklaşan SABİS teslimlerini yazar.

İstekler arasında 2-3 saniye rastgele bekler. Günde 1 kez çalıştırmak yeterlidir.

Kullanım:
    python scraper/sabis_scraper.py
    python scraper/sabis_scraper.py --yil 2026 --donem 1     # belirli dönem (1=Güz, 2=Bahar, 3=Yaz)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from markdownify import markdownify as html_to_md

OBS = "https://obs.sabis.sakarya.edu.tr"
ROOT = Path(__file__).resolve().parent.parent
LECTURES = ROOT / "lectures"
DATA_DIR = LECTURES / ".data"

NOT_BASLA = "<!-- NOTLAR:BASLA -->"
NOT_BITIR = "<!-- NOTLAR:BITIR -->"
OTO_BASLA = "<!-- OTO:BASLA — Bu bölüm scraper tarafından her çalışmada yeniden yazılır, elle düzenleme. -->"
OTO_BITIR = "<!-- OTO:BITIR -->"
TAKIP_YOK = "<!-- TAKIP:YOK -->"
OTO_BASLA_RE = re.compile(r"<!-- OTO:BASLA.*?-->")

AYLAR = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

NOW = datetime.now()

# Windows konsolu (cp1252/cp857) Türkçe karakter ve emojide çökmesin
for _akim in (sys.stdout, sys.stderr):
    try:
        _akim.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# --------------------------------------------------------------------------- yardımcılar

def bekle() -> None:
    time.sleep(random.uniform(2.0, 3.0))


def temiz(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def slugify(text: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    text = text.translate(tr)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:60].rstrip("-")


def duyuru_tarihi(label: str) -> str:
    """'27 Ekim, 15:23' -> '2026-10-27 15:23'. SABİS yıl vermediği için yıl tahmin edilir:
    bugünden ileri bir tarih çıkarsa bir önceki yıl kabul edilir."""
    m = re.match(r"(\d{1,2})\s+(\S+?),?\s+(\d{1,2}):(\d{2})", temiz(label))
    if not m:
        return temiz(label)
    gun, ay_adi, sa, dk = m.groups()
    ay = AYLAR.get(ay_adi.lower().replace("i̇", "i"))
    if not ay:
        return temiz(label)
    yil_m = re.search(r"\b(20\d{2})\b", label)
    yil = int(yil_m.group(1)) if yil_m else NOW.year
    dt = datetime(yil, ay, int(gun), int(sa), int(dk))
    if not yil_m and dt > NOW + timedelta(days=1):
        dt = dt.replace(year=yil - 1)
    return dt.strftime("%Y-%m-%d %H:%M")


def sabis_tarih(text: str) -> str:
    """'15.11.2026 23:59:00' -> '2026-11-15 23:59'"""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})", text or "")
    if not m:
        return temiz(text)
    g, a, y, s, d = map(int, m.groups())
    return f"{y:04d}-{a:02d}-{g:02d} {s:02d}:{d:02d}"


def md_govde(html: str) -> str:
    """Duyuru HTML gövdesini okunur Markdown'a çevirir (linkler korunur)."""
    md = html_to_md(html or "", heading_style="ATX", bullets="-", escape_underscores=False,
                    escape_asterisks=False, strip=["table", "tbody", "thead", "tr", "td", "th"])
    md = md.replace("\xa0", " ")
    md = "\n".join(line.strip() for line in md.splitlines())
    md = re.sub(r"\n{3,}", "\n\n", md)
    # çıplak URL'leri tıklanabilir yap (zaten <...> veya (...) içinde olanlara dokunma)
    md = re.sub(r"(?<![(<\[])\b(https?://[^\s)>\]]+)", r"<\1>", md)
    return md.strip()


# --------------------------------------------------------------------------- veri modelleri

@dataclass
class Duyuru:
    tarih: str
    baslik: str
    govde_md: str
    ekler: list[dict] = field(default_factory=list)
    ilk_gorulme: str = ""

    @property
    def anahtar(self) -> str:
        return f"{self.tarih}|{self.baslik}"


@dataclass
class Odev:
    ad: str
    baslangic: str
    bitis: str
    erisim: str
    detay_url: str = ""
    aciklama: str = ""
    yukleme: str = ""
    dosya_var: bool = False


@dataclass
class Ders:
    grup_id: int
    kod: str
    ad: str
    grup: str
    degerlendirme: list[tuple[str, str]] = field(default_factory=list)
    hocalar: str = ""
    ders_tipi: str = ""
    akts: str = ""
    saat: str = ""
    devam: str = ""
    duyurular: list[Duyuru] = field(default_factory=list)
    odevler: list[Odev] = field(default_factory=list)
    sinavlar: list[list[str]] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"{OBS}/Ders/Grup/{self.grup_id}#Duyuru"

    @property
    def dosya(self) -> Path:
        return LECTURES / f"{self.kod}-{slugify(self.ad)}.md"


# --------------------------------------------------------------------------- oturum / giriş

class Sabis:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        })

    @staticmethod
    def _form_verisi(form) -> dict:
        data = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            if inp.get("type") == "checkbox":
                continue
            data.setdefault(name, inp.get("value", ""))
        return data

    def giris(self, kullanici: str, sifre: str) -> None:
        print("→ SABİS giriş sayfası açılıyor...")
        r = self.s.get(OBS + "/", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("input", attrs={"name": "Username"})
        form = form.find_parent("form") if form else None
        if form is None:
            if "dersDetay" in r.text or "Seçilen Dersler" in r.text:
                print("  (zaten giriş yapılmış)")
                return
            raise RuntimeError("Giriş formu bulunamadı; SABİS sayfa yapısı değişmiş olabilir.")

        data = self._form_verisi(form)
        data.update({"Username": kullanici, "Password": sifre, "button": "login", "RememberLogin": "false"})
        action = urljoin(r.url, form.get("action") or r.url)

        bekle()
        print("→ Kimlik bilgileri gönderiliyor...")
        r = self.s.post(action, data=data, timeout=30)
        r.raise_for_status()

        # IdentityServer, response_mode=form_post ile otomatik gönderilen bir form döndürür.
        for _ in range(3):
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.find("input", attrs={"name": "Password"}):
                hata = temiz(soup.select_one(".validation-summary-errors, .alert-danger, .text-danger").get_text()
                             if soup.select_one(".validation-summary-errors, .alert-danger, .text-danger") else "")
                raise RuntimeError(f"Giriş başarısız. Kullanıcı adı/şifre kontrol et. {hata}")
            auto = soup.find("form")
            if auto and auto.find("input", attrs={"name": "id_token"}) or (
                    auto and "signin-oidc" in (auto.get("action") or "")):
                bekle()
                r = self.s.post(urljoin(r.url, auto["action"]), data=self._form_verisi(auto), timeout=30)
                r.raise_for_status()
                continue
            break

        bekle()
        test = self.s.get(OBS + "/Ders", timeout=30)
        if "dersDetay(" not in test.text and "Seçilen Dersler" not in test.text:
            raise RuntimeError("Giriş tamamlanamadı (OBS'ye yönlendirilemedi).")
        self._ders_html = test.text
        print("✓ Giriş başarılı.")

    def get(self, path: str) -> str:
        bekle()
        r = self.s.get(urljoin(OBS, path), timeout=30)
        r.raise_for_status()
        return r.text

    def sekme(self, target: str, grup_id: int) -> str:
        """Ders sayfasındaki sekmeler jQuery .load ile POST {dersGrupId} gönderir."""
        bekle()
        r = self.s.post(
            urljoin(OBS, target),
            data={"dersGrupId": grup_id},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{OBS}/Ders/Grup/{grup_id}"},
            timeout=30,
        )
        if r.status_code == 404:
            return ""
        r.raise_for_status()
        return r.text


# --------------------------------------------------------------------------- ayrıştırıcılar

def parse_ders_listesi(html: str) -> list[Ders]:
    soup = BeautifulSoup(html, "html.parser")
    dersler = []
    for kart in soup.select("[onclick^='dersDetay']"):
        m = re.search(r"dersDetay\((\d+),\s*(\d+)\)", kart["onclick"])
        if not m:
            continue
        gid, kok = int(m.group(1)), int(m.group(2))
        kod = temiz(kart.select_one(".symbol-label").get_text()) if kart.select_one(".symbol-label") else "?"
        ad_el = kart.select_one("a")
        ad = temiz(ad_el.get_text()) if ad_el else kod
        grup_el = kart.select_one(".text-muted")
        grup = temiz(grup_el.get_text()) if grup_el else ""
        if gid == 0:
            print(f"  ! {kod} {ad}: grup id yok (Kök ders, id={kok}), atlanıyor.")
            continue
        card = kart.find_parent(class_="card-body") or kart.parent
        degerlendirme = []
        for tr in card.select("table tbody tr"):
            tds = [temiz(td.get_text()) for td in tr.find_all("td")]
            if len(tds) >= 2:
                degerlendirme.append((tds[0], tds[1]))
        dersler.append(Ders(grup_id=gid, kod=kod, ad=ad, grup=grup, degerlendirme=degerlendirme))
    return dersler


def parse_ders_bilgi(html: str, ders: Ders) -> None:
    soup = BeautifulSoup(html, "html.parser")
    blok = soup.select_one(".py-9")
    if not blok:
        return
    satirlar = [temiz(d.get_text(" ")) for d in blok.find_all("div", recursive=False)]
    for i, s in enumerate(satirlar):
        if s.startswith("Ders Tipi:"):
            ders.ders_tipi = s.split(":", 1)[1].strip()
        elif s.startswith("AKTS:"):
            ders.akts = s.split(":", 1)[1].strip()
        elif s.startswith("Saat/Uygulama:"):
            ders.saat = s.split(":", 1)[1].strip()
        elif s.startswith("Dersi Verenler:"):
            ders.hocalar = ", ".join(x for x in satirlar[i + 1:] if x)
        elif "Devam" in s and ":" not in s:
            ders.devam = s


def parse_duyurular(html: str) -> list[Duyuru]:
    soup = BeautifulSoup(html, "html.parser")
    sonuc = []
    for item in soup.select(".timeline-item"):
        label = item.select_one(".timeline-label")
        baslik = item.select_one(".timeline-content .h2")
        govde = item.select_one(".timeline-content .text-dark")
        ekler = []
        govde_html = ""
        if govde:
            # "Eklenmiş dosya:" kısmını ayır
            ham = govde.decode_contents()
            parca = re.split(r"(?:<br\s*/?>\s*)*Eklenmiş dosya:\s*<br\s*/?>", ham, maxsplit=1)
            govde_html = parca[0]
            if len(parca) > 1:
                for a in BeautifulSoup(parca[1], "html.parser").find_all("a"):
                    ekler.append({"ad": temiz(a.get_text()), "url": a.get("href", "")})
        sonuc.append(Duyuru(
            tarih=duyuru_tarihi(label.get_text() if label else ""),
            baslik=temiz(baslik.get_text()) if baslik else "(başlıksız)",
            govde_md=md_govde(govde_html),
            ekler=ekler,
        ))
    return sonuc


def parse_odevler(html: str) -> list[Odev]:
    soup = BeautifulSoup(html, "html.parser")
    odevler = []
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        detay = tr.find("a", href=re.compile(r"/Odev/Detay/"))
        odevler.append(Odev(
            ad=temiz(tds[0].get_text()),
            baslangic=sabis_tarih(tds[1].get_text()),
            bitis=sabis_tarih(tds[2].get_text()),
            erisim=sabis_tarih(tds[3].get_text()) if len(tds) > 3 else "",
            detay_url=urljoin(OBS, detay["href"]) if detay else "",
        ))
    return odevler


def parse_odev_detay(html: str, odev: Odev) -> None:
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select(".form-group.row"):
        lab = row.find("label")
        if not lab:
            continue
        ad = temiz(lab.get_text())
        deger = row.find("div")
        metin = temiz(deger.get_text(" ")) if deger else ""
        if ad.startswith("Açıklama"):
            odev.aciklama = metin
        elif ad.startswith("Yükleme Sayısı"):
            odev.yukleme = (re.search(r"\d+\s*/\s*\d+", metin) or [metin])[0]
        elif ad.startswith("Ödev Dosyası"):
            odev.dosya_var = True  # imzalı S3 linki kısa ömürlü; md'ye link yazmıyoruz


def parse_tablo(html: str) -> list[list[str]]:
    """Sınavlar gibi yapısı bilinmeyen sekmeler için genel tablo okuyucu. İlk satır başlık."""
    soup = BeautifulSoup(html, "html.parser")
    tablo = soup.find("table")
    if not tablo:
        return []
    satirlar = []
    for tr in tablo.find_all("tr"):
        hucreler = [temiz(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
        hucreler = [h for h in hucreler if h not in ("Detay", "Sorun Bildir")]
        if any(hucreler):
            satirlar.append(hucreler)
    return satirlar


# --------------------------------------------------------------------------- arşiv (görülen duyurular)

def arsivle(ders: Ders) -> list[Duyuru]:
    """Yeni çekilen duyuruları arşivle birleştirir, bu çalışmada ilk kez görülenleri döndürür."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    yol = DATA_DIR / f"{ders.kod}.json"
    eski: dict[str, dict] = {}
    if yol.exists():
        try:
            eski = {d["tarih"] + "|" + d["baslik"]: d for d in json.loads(yol.read_text("utf-8")).get("duyurular", [])}
        except Exception:
            eski = {}
    yeniler = []
    birlesik: dict[str, Duyuru] = {}
    for k, d in eski.items():
        birlesik[k] = Duyuru(**d)
    for d in ders.duyurular:
        if d.anahtar in birlesik:
            d.ilk_gorulme = birlesik[d.anahtar].ilk_gorulme
        else:
            d.ilk_gorulme = NOW.strftime("%Y-%m-%d %H:%M")
            yeniler.append(d)
        birlesik[d.anahtar] = d
    ders.duyurular = sorted(birlesik.values(), key=lambda d: d.tarih, reverse=True)
    kayit = asdict(ders)
    kayit["guncelleme"] = NOW.strftime("%Y-%m-%d %H:%M")
    kayit["url"] = ders.url
    yol.write_text(json.dumps(kayit, ensure_ascii=False, indent=2), "utf-8")
    return yeniler if eski else []  # ilk çalışmada her şeyi "yeni" diye işaretleme


# --------------------------------------------------------------------------- markdown üretimi

def notlar_sablonu(ders: Ders) -> str:
    return f"""{NOT_BASLA}
## 🗒️ Notlarım ve takip
_Bu bölümü sen ve Claude düzenler. Scraper buraya dokunmaz._

### 📌 Yaklaşan işler
| İş | Tür | Son tarih | Durum | Kaynak |
|---|---|---|---|---|

### ❓ Bekleyen bilgiler (sorulacak)
- [ ]

### 📝 Ders notları
-

{NOT_BITIR}"""


def oto_blogu(ders: Ders) -> str:
    satir = [OTO_BASLA, "## 📥 SABİS verisi (otomatik)", f"_Son çekim: {NOW:%Y-%m-%d %H:%M}_", ""]

    satir.append("### Ödevler (SABİS Ödevler sekmesi)")
    if ders.odevler:
        satir += ["| Ödev | Açıklama | Başlangıç | **Bitiş** | Yükleme | Detay |", "|---|---|---|---|---|---|"]
        for o in ders.odevler:
            durum = o.yukleme or "?"
            if o.yukleme.startswith("0") and o.bitis > NOW.strftime("%Y-%m-%d %H:%M"):
                durum += " ⚠️ yüklenmedi"
            satir.append(f"| {o.ad} | {o.aciklama or '-'} | {o.baslangic} | **{o.bitis}** | {durum} | "
                         f"[aç]({o.detay_url}) |")
    else:
        satir.append("_SABİS'te bu derse ait ödev yok._")
    satir.append("")

    satir.append("### Sınavlar (SABİS Sınavlar sekmesi)")
    if len(ders.sinavlar) > 1:
        bas, *govde = ders.sinavlar
        satir += ["| " + " | ".join(bas) + " |", "|" + "---|" * len(bas)]
        satir += ["| " + " | ".join(r) + " |" for r in govde]
    else:
        satir.append("_SABİS'te bu derse ait sınav kaydı yok._")
    satir.append("")

    satir.append(f"### Duyurular ({len(ders.duyurular)})")
    if not ders.duyurular:
        satir.append("_Henüz duyuru yok._")
    for d in ders.duyurular:
        satir += ["", f"#### {d.tarih} — {d.baslik}"]
        if d.govde_md:
            satir += ["", d.govde_md]
        if d.ekler:
            satir += ["", "**Ekler:** " + ", ".join(f"[{e['ad']}]({e['url']})" for e in d.ekler)]
    satir += ["", OTO_BITIR]
    return "\n".join(satir)


def baslik_blogu(ders: Ders) -> str:
    deg = ", ".join(f"%{o} {t}" for o, t in ders.degerlendirme) or "SABİS'te tanımlı değil"
    bilgi = [f"# {ders.kod} — {ders.ad}", "",
             f"> **Grup:** {ders.grup} · **Hoca:** {ders.hocalar or '?'} · **AKTS:** {ders.akts or '?'} · "
             f"**Tip:** {ders.ders_tipi or '?'} · **Saat:** {ders.saat or '?'}",
             f"> **Değerlendirme:** {deg}"]
    if ders.devam:
        bilgi.append(f"> **Devam:** {ders.devam}")
    bilgi.append(f"> **SABİS:** <{ders.url}>")
    return "\n".join(bilgi)


def md_yaz(ders: Ders) -> None:
    LECTURES.mkdir(parents=True, exist_ok=True)
    yol = ders.dosya
    # Aynı ders için farklı isimli eski dosya varsa onu kullan (ders adı değişirse notlar kaybolmasın)
    eslesen = sorted(LECTURES.glob(f"{ders.kod}-*.md"))
    if not yol.exists() and eslesen:
        yol = eslesen[0]

    oto = oto_blogu(ders)
    if yol.exists():
        mevcut = yol.read_text("utf-8")
        bas = OTO_BASLA_RE.search(mevcut)
        son = mevcut.find(OTO_BITIR)
        if bas and son != -1:
            yeni = mevcut[:bas.start()] + oto + mevcut[son + len(OTO_BITIR):]
        else:
            yeni = mevcut.rstrip() + "\n\n" + oto + "\n"
        # başlık bloğunu (ilk boş satıra kadar olan > satırları) güncelle
        if yeni.startswith("# "):
            ilk_not = yeni.find(NOT_BASLA)
            if ilk_not != -1:
                yeni = baslik_blogu(ders) + "\n\n" + yeni[ilk_not:]
    else:
        yeni = baslik_blogu(ders) + "\n\n" + notlar_sablonu(ders) + "\n\n" + oto + "\n"
    yol.write_text(yeni, "utf-8")


def takip_disi(ders: Ders) -> bool:
    """NOTLAR bölümünde <!-- TAKIP:YOK --> işareti olan dersler özetlerde ayrı gösterilir."""
    eslesen = sorted(LECTURES.glob(f"{ders.kod}-*.md"))
    return bool(eslesen) and TAKIP_YOK in eslesen[0].read_text("utf-8")


def ozet_yaz(dersler: list[Ders], yeniler: dict[str, list[Duyuru]], sinav_takvimi: str) -> Path:
    simdi = NOW.strftime("%Y-%m-%d %H:%M")
    disarida = [d for d in dersler if takip_disi(d)]
    # Takip dışı bir derste SABİS'e bir şey düşerse gözden kaçmasın
    uyari = [d for d in disarida if yeniler.get(d.kod) or d.odevler]
    dersler = [d for d in dersler if d not in disarida]
    s = [f"# SABİS son çalışma — {simdi}", "",
         "_Bu dosya her çalışmada yeniden yazılır. Claude, özet çıkarırken buradan başlar._", ""]

    s.append("## 🆕 Bu çalışmada gelen yeni duyurular")
    hic = True
    for d in dersler:
        for y in yeniler.get(d.kod, []):
            hic = False
            s.append(f"- **{d.kod}** · {y.tarih} — {y.baslik} → [{d.dosya.name}]({d.dosya.name})")
    if hic:
        s.append("- Yeni duyuru yok (ya da ilk çalışma).")
    for d in uyari:
        s.append(f"- ⚠️ **{d.kod}** takip dışı ama SABİS'te yeni duyuru/ödev var → [{d.dosya.name}]({d.dosya.name})")
    s.append("")

    s.append("## ⏰ SABİS'teki ödev teslimleri")
    odevler = sorted(((o, d) for d in dersler for o in d.odevler), key=lambda x: x[0].bitis)
    if odevler:
        s += ["| Bitiş | Ders | Ödev | Açıklama | Yükleme |", "|---|---|---|---|---|"]
        for o, d in odevler:
            gecti = " (süresi geçti)" if o.bitis < simdi else ""
            s.append(f"| **{o.bitis}**{gecti} | {d.kod} {d.ad} | {o.ad} | {o.aciklama or '-'} | {o.yukleme or '?'} |")
    else:
        s.append("- SABİS'te ödev yok.")
    s.append("")

    s.append("## 📝 Sınav takvimi (SABİS)")
    s.append(sinav_takvimi or "- Sınav bilgisi bulunamadı.")
    s.append("")

    s.append("## 📚 Dersler")
    for d in dersler:
        s.append(f"- [{d.kod} — {d.ad}]({d.dosya.name}) · {len(d.duyurular)} duyuru · {len(d.odevler)} ödev")
    for d in disarida:
        s.append(f"- 🚫 ~~{d.kod} — {d.ad}~~ (takip dışı)")
    yol = LECTURES / "_son_calisma.md"
    yol.write_text("\n".join(s) + "\n", "utf-8")
    return yol


# --------------------------------------------------------------------------- ana akış

def main() -> int:
    ap = argparse.ArgumentParser(description="SABİS duyuru/ödev scraper")
    ap.add_argument("--yil", type=int, help="Akademik yıl (ör. 2026). Boşsa SABİS'in varsayılan dönemi.")
    ap.add_argument("--donem", type=int, help="1=Güz, 2=Bahar, 3=Yaz")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    kullanici = os.getenv("SABIS_KULLANICI", "").strip()
    sifre = os.getenv("SABIS_SIFRE", "")
    if not kullanici or not sifre:
        print("HATA: .env dosyasında SABIS_KULLANICI ve SABIS_SIFRE tanımlı olmalı (.env.example'a bak).")
        return 1

    sabis = Sabis()
    sabis.giris(kullanici, sifre)

    if args.yil and args.donem:
        ders_html = sabis.get(f"/Ders/{args.yil}/{args.donem}")
    else:
        ders_html = sabis._ders_html
    dersler = parse_ders_listesi(ders_html)
    print(f"✓ {len(dersler)} ders bulundu.")

    yeniler: dict[str, list[Duyuru]] = {}
    for d in dersler:
        print(f"→ {d.kod} {d.ad}")
        parse_ders_bilgi(sabis.get(f"/Ders/Grup/{d.grup_id}"), d)
        d.duyurular = parse_duyurular(sabis.sekme("/Grup/Duyurular", d.grup_id))
        d.odevler = parse_odevler(sabis.sekme("/Odev/Grup", d.grup_id))
        for o in d.odevler:
            if o.detay_url:
                try:
                    parse_odev_detay(sabis.get(o.detay_url), o)
                except requests.HTTPError as e:
                    print(f"  ! ödev detayı alınamadı: {e}")
        d.sinavlar = parse_tablo(sabis.sekme("/Sinav/Grup", d.grup_id))
        yeniler[d.kod] = arsivle(d)
        md_yaz(d)
        print(f"  {len(d.duyurular)} duyuru, {len(d.odevler)} ödev"
              + (f", {len(yeniler[d.kod])} YENİ duyuru" if yeniler[d.kod] else ""))

    takvim = ""
    try:
        t = BeautifulSoup(sabis.get("/Sinav/Takvim"), "html.parser")
        tablo = parse_tablo(str(t))
        if len(tablo) > 1:
            bas, *govde = tablo
            takvim = "\n".join(["| " + " | ".join(bas) + " |", "|" + "---|" * len(bas)]
                               + ["| " + " | ".join(r) + " |" for r in govde])
    except requests.HTTPError:
        pass

    yol = ozet_yaz(dersler, yeniler, takvim)
    print(f"\n✓ Bitti. Özet: {yol.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"HATA: {e}")
        sys.exit(2)
