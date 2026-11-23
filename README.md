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

Kenar çubuğundaki rol seçimi tek başına yetki vermez.

Admin parolası `ADMIN_PASSWORD` değeridir. Önce `.streamlit/secrets.toml` (Streamlit Cloud'da Secrets), yoksa ortam değişkeni okunur. Karşılaştırma `hmac.compare_digest` ile yapılır. Oturum bellekte tutulur; kenar çubuğundaki Çıkış oturumu siler.

Parola tanımlı değilse ve uygulama deneme modunda değilse Admin paneli açılmaz. Ekranda dosyaya veya ortam değişkenine nasıl yazılacağı gösterilir. Deneme modunda parola tanımlı değilse yönetici parolası `demo` olur ve giriş formunda yazılır. `ADMIN_PASSWORD` tanımlıysa deneme modunda da o parola geçerlidir.

Ekip, kaydını ve erişim kodunu girerek oturum açar. Kod `ekipler.erisim_kodu` sütunundadır. Yönetici ekip oluştururken kodu yazar ve tabloda görür. Kod boşsa o ekip giriş yapamaz. Girişten sonra ekip yalnızca kendi devam eden görevini görür ve yalnızca onu kapatabilir.

Eski Supabase projesine sütun eklemek için `supabase_schema.sql` içindeki şu satır yeterlidir:

```sql
alter table ekipler add column if not exists erisim_kodu text;
```

Kod boş bırakılan ekip kaydı, sütun henüz yokken de yazılır. Bu kontrol arayüzdedir; anon anahtarla tabloya doğrudan erişim ayrıca kısıtlanmaz.

Deneme ekipleri: AK-1 (#1) `ekip-1`, AK-1 (#2) `ekip-2`, AK-3 (#3) `ekip-3`. Kodlar deneme giriş formunda da listelenir.

## Model (1/11)

Birinci aşama kararları `model/` paketindedir ve rapor (4.4)–(4.10) ile Çizelge 5.1'e göredir: `G_j`, `V_{j,k}`, `V^U_j`, `V^W_j`. Paket Streamlit ve Supabase import etmez. "Atama Çalıştır" sekmesi bu planı gösterir; Supabase'e yazılan operasyonel atama seçilen tek senaryo için eskisi gibi kalır.

PuLP 2.9 kullanılır. PuLP 3+ `PULP_CBC_CMD` ve `LpVariable.dicts` adlarını kaldırdı.

## Kontroller

```bash
python3 -m unittest discover -s tests -v
python3 -m pytest -q
```

## Özellikler

- Admin: parola sonrası enkaz ve ekip girişi, Avcılar örnek verisi, operasyonel atama, birinci aşama planı, durum
- Ekip: kendi koduyla giriş, kendi görevini görme ve bitirme
- Tamamlanan atamalar yeniden planlamada silinmez
