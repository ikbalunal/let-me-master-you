# Let Me Master You

**[English](#english) · [Türkçe](#türkçe)**

---

## English

Never lose track of homework, presentations and exams again.

The scraper collects your course announcements and assignments into one Markdown file per course. A [Claude Code](https://claude.com/claude-code) skill then reads those files to:

- tell you what is due soon,
- ask you about things your instructor only said in class,
- keep your course notes.

> ⚠️ The scraper is written **only for SABİS / OBS, Sakarya University's student information system** (`obs.sabis.sakarya.edu.tr`). It is an unofficial tool and will not work with other universities without changes.

### Setup

```bash
git clone https://github.com/ikbalunal/let-me-master-you.git
cd let-me-master-you
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your SABİS e-mail and password. `.env` is git-ignored, so never share it.

### Usage

```bash
python scraper/sabis_scraper.py
```

This creates `lectures/<CODE>-<course>.md` for each course, plus `lectures/_son_calisma.md` (what's new and upcoming deadlines). Run it **at most once a day**. It waits 2–3 seconds between requests.

Then open the folder in Claude Code and just ask:

- "update SABİS"
- "what's due this week?"
- "note for BSM515: presentation must be 10 min"

Each course file has two parts:

- **NOTLAR** (notes): yours. The scraper never touches it.
- **OTO** (auto): rewritten on every run.

---

## Türkçe

Ödev, sunum ve sınav tarihlerini bir daha kaçırma.

Scraper ders duyurularını ve ödevlerini her ders için bir Markdown dosyasında toplar. Ardından bir [Claude Code](https://claude.com/claude-code) skill'i bu dosyaları okuyarak:

- yaklaşan işleri söyler,
- hocanın sadece derste söylediği bilgileri sana sorar,
- ders notlarını tutar.

> ⚠️ Scraper **yalnızca Sakarya Üniversitesi'nin öğrenci bilgi sistemi SABİS / OBS** (`obs.sabis.sakarya.edu.tr`) için yazılmıştır. Resmi bir araç değildir. Başka üniversitelerde değişiklik yapmadan çalışmaz.

### Kurulum

```bash
git clone https://github.com/ikbalunal/let-me-master-you.git
cd let-me-master-you
pip install -r requirements.txt
```

`.env.example` dosyasını `.env` adıyla kopyala, SABİS mailini ve şifreni yaz. `.env` git'e gönderilmez, kimseyle paylaşma.

### Kullanım

```bash
python scraper/sabis_scraper.py
```

Her ders için `lectures/<KOD>-<ders>.md` dosyası oluşur. Ayrıca `lectures/_son_calisma.md` dosyasında yenilikler ve yaklaşan teslimler yer alır. **Günde en fazla 1 kez** çalıştır. İstekler arasında 2-3 saniye bekler.

Sonra klasörü Claude Code ile aç ve yazman yeterli:

- "SABİS'i güncelle"
- "bu hafta ne var?"
- "BSM515 notu: sunum 10 dk olacak"

Her ders dosyasında iki bölüm var:

- **NOTLAR**: senin. Scraper dokunmaz.
- **OTO**: her çalışmada yenilenir.

---

```
scraper/sabis_scraper.py           # SABİS scraper
.claude/skills/sabis-ders-takip/   # Claude Code skill
lectures/                          # your notes (git-ignored) / notların (git'e gitmez)
```
