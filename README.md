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

PuLP 3 ve sonrası bu projedeki model çağrılarıyla uyumlu değildir. `requirements.txt` bu yüzden 2.x sürümünü ister.

## Kontroller

```bash
python3 -m unittest discover -s tests -v
```

## Özellikler

- Admin: enkaz ve ekip girişi, Avcılar örnek verisi, PuLP ataması, durum
- Ekip: kendi görevini görme ve bitirme
- Tamamlanan atamalar yeniden planlamada silinmez
