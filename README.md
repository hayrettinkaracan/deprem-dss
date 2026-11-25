# Deprem Kaynak Atama DSS

END4902 bitirme çalışması için yazılmış Türkçe bir karar destek prototipi. PuLP 2.9 / CBC ile merkez açma, kaynak yerleştirme ve ekip rotalarını çözen bir model (`model/`) ve Streamlit arayüzü (`app.py`) içerir. 5.3 doğrulama koşuları `scripts/run_5_3.py` ile üretilir. Arayüzün güncel modele bağlanması sonraki adımdır.

Yayındaki sürüm: https://deprem-dss.streamlit.app/

## Gereksinimler ve kurulum

Depoda `pyproject.toml` veya `uv.lock` yoktur. Bağımlılıklar `requirements.txt` içindedir. PuLP 2.9.0 olarak kilitlidir; PuLP 3, `PULP_CBC_CMD` ve `LpVariable.dicts` adlarını kaldırdığı için kurulmamalıdır. CBC, PuLP 2.9 paketinin içinden gelir. Geliştirme kabı (`.devcontainer`) Python 3.11 imajını kullanır.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`uv` ile: `uv venv && uv pip install -r requirements.txt`. Sonrasında aynı `python -m ...` komutları geçerlidir (`uv run python -m ...` de olur).

## Arayüzü çalıştırma

```bash
streamlit run app.py
```

Kalıcı kurulumda `.streamlit/secrets.toml` içinde `SUPABASE_URL` ve `SUPABASE_KEY` gerekir (örnek: `secrets.toml.example`). Anahtar yoksa uygulama durur ve eksik anahtarı bildirir. Şema `supabase_schema.sql` içindedir. Eski bir Supabase projesine erişim kodu sütunu eklemek için:

```sql
alter table ekipler add column if not exists erisim_kodu text;
```

Kayıtların kaydedilmediği yerel deneme:

```bash
DEPREM_DEMO=1 streamlit run app.py
```

Bu mod `demo_client.py` içindeki bellek istemcisini kullanır. Sayfanın üstünde verilerin kaydedilmediği uyarısı durur. Anahtar tanımlıysa `DEPREM_DEMO` yok sayılır ve Supabase kullanılır.

Yönetici paneli `ADMIN_PASSWORD` ister. Değer önce `.streamlit/secrets.toml` (Streamlit Cloud'da Secrets), yoksa ortam değişkeninden okunur; karşılaştırma `hmac.compare_digest` ile yapılır. Parola yoksa ve deneme modu açık değilse Admin paneli açılmaz. Deneme modunda parola tanımlı değilse yönetici parolası `demo` olur; `ADMIN_PASSWORD` tanımlıysa deneme modunda da o parola geçerlidir.

Ekip, kaydını ve `ekipler.erisim_kodu` değerini girerek oturum açar. Kod boşsa o ekip giriş yapamaz. Girişten sonra tek ekran vardır: enkaz adı, talep (kişi), iş makinesi gerekli mi, atanmış UMKE ve iş makinesi, başlangıç (`gg.aa.yyyy ss:dd`) ve geçen süre, harita bağlantısı. «Görevim Bitti» önce onay ister. Görev yoksa «Henüz görev yok, müsaitsiniz» yazılır. Deneme ekipleri: AK-1 (#1) `ekip-1`, AK-1 (#2) `ekip-2`, AK-3 (#3) `ekip-3`. Kodlar deneme giriş formunda da listelenir. Tamamlanan atamalar yeniden planlamada silinmez.

«Atamayı Çalıştır» seçilen senaryoyu kayda yazar; yanındaki plan / zincir önizlemesi canlı kaydı değiştirmez. Arayüzün güncel modele bağlanması sonraki adımdır.

## 5.3 sayısal koşular

Uzun CBC işi yerelde çalışır. `--time-limit` her CBC çağrısı içindir. `--threads 0` bütün çekirdekleri kullanır. `--periods` son periyottur (varsayılan 36).

```bash
python -m scripts.run_5_3 --mode z1 --time-limit 900 --threads 4 --periods 36 --out docs/sonuclar_5_3.md
python -m scripts.run_5_3 --mode pareto --time-limit 120 --threads 4 --points 5 --out docs/sonuclar_5_3_pareto.md
python -m scripts.run_5_3 --mode rehearsal --time-limit 60 --threads 4 --periods 36 --out docs/prova_5_3.md
python -m scripts.run_5_3 --mode rehearsal --time-limit 120 --threads 0 --periods 12 --out docs/prova_5_3_24saat.md
```

36 periyotluk planlama modeli (Z1) kurulduğunda 110.661 değişken (92.399 ikili) ve 228.656 kısıt içerir; kurulum birkaç saniyedir.

- `z1`: tek çağrı. 36 periyot, 4 çekirdekte çoğunlukla birkaç dakika ile 15 dakika. 900 s yerel bütçedir. Çıktı, süre sınırı altında bulunan en iyi çözümdür.
- `pareto`: Z1, iki Z2 ucu ve beş ε noktası, toplam 7 çağrı. 120 s ile üst sınır kabaca 15 dakikadır. Çıktıyı `docs/sonuclar_5_3.md` üzerine yazmamak için ayrı `--out` yolu verin.
- `rehearsal`: saat 1, 3, 5, 7, 9, 11 için varsayımsal olay. Altı olay, olay başı bir çağrı. Tam ufukta olay başı 60 s ile çözücü süresi kabaca 6 dakikadır; model kurulumu yüzünden duvar saati daha uzun olabilir. 24 saatlik ufukta (`--periods 12`) olay başı 120 s ile toplam kabaca 15 dakikadır.

Kısa kontrol (bir iki dakikada biter; uzun prova dosyasının üzerine yazmaz):

```bash
python -m scripts.run_5_3 --mode rehearsal --max-events 1 --periods 2 --time-limit 15 --out docs/prova_test.md
```

Süre sınırında kalan noktanın durumu ve aralığı dosyada durur.

## Testler

```bash
python -m pytest -q
python -m unittest discover -s tests -v
```

## Klasör yapısı

```
app.py                 Streamlit arayüzü
demo_client.py         Deneme (bellek) veri istemcisi
data/                  5.3 örneği ve prova olay üreticisi
docs/                  Koşu çıktıları ve girdi notları
model/                 MILP modelleri (Streamlit / Supabase import etmez)
scripts/               5.3 koşu betiği (run_5_3.py)
tests/                 Birim testleri
requirements.txt       Bağımlılıklar (PuLP 2.9.0 kilitli)
secrets.toml.example   SUPABASE_URL, SUPABASE_KEY, ADMIN_PASSWORD örneği
supabase_schema.sql    Tablo şeması
```

## Çıktı dosyaları

- `docs/sonuclar_5_3.md`: Z1 sonucu (durum, Z1, alt sınır, aralık, senaryo amaçları, yerleştirme, zincirler). Depoda durur.
- `docs/sonuclar_5_3_pareto.md`: ε taraması (ön sonuç). Depoda durur.
- `docs/prova_5_3.md`: 36 periyotluk prova koşusunun çıktısı (olay başı 60 s).
- `docs/prova_5_3_24saat.md`: 24 saatlik (12 periyot) prova koşusunun çıktısı (olay başı 120 s).
- `docs/hipotetik_tau.md`, `docs/prova_olaylari.md`: girdi notları (koşu çıktısı değil).

## Notlar

- Arayüzün güncel modele bağlanması sonraki adımdır.
- `z1` çıktısı süre sınırı altında elde edilen en iyi çözümdür; durum ve aralık dosyada durur.
- Pareto taraması ön sonuçtur; daha uzun süreyle genişletilebilir.
- 5.3 örneği doğrulama amaçlıdır. Nihai uygulama gerçekçi Avcılar verisiyle yapılacaktır.
