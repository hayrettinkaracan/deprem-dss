# Deprem Kaynak Atama DSS

Streamlit tabanlı karar destek sistemi prototipi. Arayüz Türkçedir.

## Çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

`SUPABASE_URL` ve `SUPABASE_KEY` tanımlıysa (`.streamlit/secrets.toml`) uygulama Supabase kullanır. Anahtar yoksa bellek içi örnek veriyle açılır; bu yol üretimdeki istemciyi değiştirmez.

PuLP 3 ve sonrası bu projedeki model çağrılarıyla uyumlu değildir. `requirements.txt` bu yüzden 2.x sürümünü ister.

## Kontroller

```bash
python3 -m unittest discover -s tests -v
```

## Özellikler

- Admin: enkaz ve ekip girişi, Avcılar örnek verisi, PuLP ataması, durum
- Ekip: kendi görevini görme ve bitirme
- Tamamlanan atamalar yeniden planlamada silinmez
