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

## Model (1/11)

Birinci aşama kararları `model/` paketindedir ve rapor (4.4)–(4.10) ile Çizelge 5.1'e göredir: `G_j`, `V_{j,k}`, `V^U_j`, `V^W_j`. Paket Streamlit ve Supabase import etmez. "Atama Çalıştır" sekmesi bu planı gösterir; Supabase'e yazılan operasyonel atama seçilen tek senaryo için eskisi gibi kalır.

PuLP 2.9 kullanılır. PuLP 3+ `PULP_CBC_CMD` ve `LpVariable.dicts` adlarını kaldırdı.

## Kontroller

```bash
python3 -m unittest discover -s tests -v
python3 -m pytest -q
```

## Özellikler

- Admin: enkaz ve ekip girişi, Avcılar örnek verisi, operasyonel atama, birinci aşama planı, durum
- Ekip: kendi görevini görme ve bitirme
- Tamamlanan atamalar yeniden planlamada silinmez
