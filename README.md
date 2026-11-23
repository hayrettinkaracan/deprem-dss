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

## Model

Paket `model/` Streamlit ve Supabase import etmez.

- 1/11: birinci aşama (4.4)–(4.10), `solve_first_stage`.
- 2/11: bireysel ekip zinciri (4.18)–(4.23), `solve_team_chains`.
- 3/11: \(T=\{1..36\}\), \(L=2\), \(H=72\). Periyot aşan yol (4.1), (4.24)–(4.33), (4.36)–(4.39). İş hâlâ giriş başına \(L\) saattir.

"Atama Çalıştır" her iki sonucu da gösterir. Supabase'e yazılan operasyonel atama seçilen tek senaryo için eskisi gibi kalır.

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
