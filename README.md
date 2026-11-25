# Deprem Kaynak Atama DSS

Streamlit tabanlı karar destek sistemi prototipi. Arayüz Türkçedir.

## Çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

`.streamlit/secrets.toml` içinde `SUPABASE_URL` ve `SUPABASE_KEY` gerekir. Anahtar yoksa uygulama durur ve eksik anahtarı bildirir.

Kayıtların kaydedilmediği yerel deneme:

```bash
DEPREM_DEMO=1 streamlit run app.py
```

Bu mod `demo_client.py` içindeki bellek istemcisini kullanır. Sayfanın üstünde verilerin kaydedilmediği uyarısı durur. Anahtar tanımlıysa `DEPREM_DEMO` yok sayılır ve Supabase kullanılır.

## Roller

Rol seçimi tek başına yetki vermez. Rol ve Çıkış ana alandadır. Ekip akışı kenar çubuğuna bağlı değildir; ekip ekranı `layout="wide"` kullanmaz.

Admin parolası `ADMIN_PASSWORD` değeridir. Önce `.streamlit/secrets.toml` (Streamlit Cloud'da Secrets), yoksa ortam değişkeni okunur. Karşılaştırma `hmac.compare_digest` ile yapılır. Oturum bellekte tutulur; Çıkış oturumu siler.

Parola tanımlı değilse ve uygulama deneme modunda değilse Admin paneli açılmaz. Ekranda dosyaya veya ortam değişkenine nasıl yazılacağı gösterilir. Deneme modunda parola tanımlı değilse yönetici parolası `demo` olur ve giriş formunda yazılır. `ADMIN_PASSWORD` tanımlıysa deneme modunda da o parola geçerlidir.

Ekip, kaydını ve erişim kodunu girerek oturum açar. Kod `ekipler.erisim_kodu` sütunundadır. Yönetici ekip oluştururken kodu yazar ve tabloda görür. Kod boşsa o ekip giriş yapamaz. Girişten sonra tek ekran vardır: enkaz adı, talep (kişi), iş makinesi gerekli mi, atanmış UMKE ve iş makinesi, başlangıç (`gg.aa.yyyy ss:dd`) ve geçen süre, harita bağlantısı. «Görevim Bitti» önce onay ister. Görev yoksa «Henüz görev yok, müsaitsiniz» yazılır. Bağlantı hatasında yığın izi yerine «Yeniden dene» gösterilir.

Eski Supabase projesine sütun eklemek için `supabase_schema.sql` içindeki şu satır yeterlidir:

```sql
alter table ekipler add column if not exists erisim_kodu text;
```

Kod boş bırakılan ekip kaydı, sütun henüz yokken de yazılır. Bu kontrol arayüzdedir; anon anahtarla tabloya doğrudan erişim ayrıca kısıtlanmaz.

Deneme ekipleri: AK-1 (#1) `ekip-1`, AK-1 (#2) `ekip-2`, AK-3 (#3) `ekip-3`. Kodlar deneme giriş formunda da listelenir.

## Model (1/11)
## Model

Paket `model/` Streamlit ve Supabase import etmez.

- 1/11: birinci aşama (4.4)–(4.10), `solve_first_stage`.
- 2/11: bireysel ekip zinciri (4.18)–(4.23), `solve_team_chains`.
- 3/11: \(T=\{1..36\}\), \(L=2\), \(H=72\). Periyot aşan yol (4.1), (4.24)–(4.33), (4.36)–(4.39). İş hâlâ giriş başına \(L\) saattir.

"Atama Çalıştır" her iki sonucu da gösterir. Supabase'e yazılan operasyonel atama seçilen tek senaryo için eskisi gibi kalır.

PuLP 2.9 kullanılır. PuLP 3+ `PULP_CBC_CMD` ve `LpVariable.dicts` adlarını kaldırdı.

## Kontroller

```bash
pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 -m pytest -q
```

PuLP **2.9.0** sabittir (`requirements.txt`). CBC, PuLP 2.9 paketinin içinden gelir. PuLP 3 bu çözücü adını kaldırdığı için kurulmaz.

## 5.3 sayısal koşu

Uzun CBC koşusu depoya gömülü değildir. Çizelge 5.1 planı yerelde üretilir ve `docs/sonuclar_5_3.md` dosyasının üzerine yazılır.

```bash
pip install -r requirements.txt
python -m scripts.run_5_3 --mode z1 --time-limit 900 --threads 4 --out docs/sonuclar_5_3.md
python -m scripts.run_5_3 --mode pareto --time-limit 120 --threads 4 --points 5 --out docs/sonuclar_5_3.md
```

`--threads 0` bütün çekirdekleri kullanır. `--mode z1` yalnız (4.2). `--mode pareto` Z1’den sonra Z̄_2 ve Z_2 uçlarını, ardından beş ε noktasında Z1 + δ Z2 amaçlı (4.4) taramasını çalıştırır. Süre sınırında kalan noktanın durumu ve aralığı dosyada olduğu gibi durur.

## Özellikler

- Admin: parola sonrası enkaz ve ekip girişi, Avcılar örnek verisi, operasyonel atama, birinci aşama planı, durum
- Ekip: kendi koduyla giriş, telefonda tek ekranda kendi görevini görme ve onaydan sonra bitirme
- Tamamlanan atamalar yeniden planlamada silinmez
