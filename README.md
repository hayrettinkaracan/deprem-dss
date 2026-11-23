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

## Model

Paket `model/` Streamlit ve Supabase import etmez.

- 1/11: birinci aşama (4.4)–(4.10), `solve_first_stage`.
- 2/11: bireysel ekip zinciri (4.18)–(4.23), `solve_team_chains`. Ziyaret düğümleri `(i, t)` ve `(j, t, ℓ)`. Çözülen ufuk yer tutucusu 1 periyottur.

"Atama Çalıştır" her iki sonucu da gösterir. Supabase'e yazılan operasyonel atama seçilen tek senaryo için eskisi gibi kalır.

```bash
python -m pytest -q
```
