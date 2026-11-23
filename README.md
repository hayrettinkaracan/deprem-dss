# Deprem Kaynak Atama DSS

Streamlit tabanlı karar destek sistemi prototipi.

## Çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Özellikler (MVP)

- Admin: Enkaz/ekip ekleme, rastgele veri, basit atama
- Ekip: Görev görme, "Görevim Bitti" ile serbest kalma
- Çoklu ekip, bağımsız bitiş, yeniden atama hazır

## Model (1/11)

Birinci aşama kararları `model/` paketindedir: merkez açma `G_j`, ekip ön konumlandırma `V_{j,k}`, UMKE `V^U_j`, iş makinesi `V^W_j`. Paket Streamlit ve Supabase import etmez. "Atama Çalıştır" sekmesi bu planı gösterir; Supabase'e yazılan operasyonel atama seçilen tek senaryo için eskisi gibi kalır.

```bash
python -m pytest -q
```
