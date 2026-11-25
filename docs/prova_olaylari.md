# Saat 1, 3, 5, 7, 9, 11 prova kayıtları

**HYK onayıyla üretilmiş hipotetik veri.** Rapor saatleri verir, kayıt içeriğini vermez. Tohum `20261125`. Aynı tohum `data/rehearsal.py` içinde aynı tabloyu üretir.

Her saatte bir yeni enkaz ve bir gönüllü vardır. Adet raporda yoktur. Hasar sınıfı üç sınıf üzerinde düzgün çekilir; sınıf seçilince γ ve yetkinlik 4.2 / 5.3 hiyerarşisidir. Ağır enkazda E = 1. m^A, 5.3 ölçeğidir (Ağır 4, Orta 2,5, Hafif 1,5). m^U = 0,3 m^A. m^W = 0,5 m^A yalnız E = 1 ise. Gönüllü üretkenliği Üçgen(1; 1,5; 3)/5. Merkez süreleri üçgen aralığını bozmaz; enkaz–enkaz süre, merkez sürelerinin orta noktasıdır. Gönüllü, J1 ve J2 açık kabul edilerek bu ikisinden birinde bir sonraki periyodun başında belirir. β, 5.3 kalıbıdır.

Saat periyodun içindedir. Kayıt bir sonraki periyodun başına girer: saat 1 → periyot 2 (θ = 2), saat 11 → periyot 7 (θ = 12).

| Saat | Giriş | θ | Enkaz | κ | γ | m^A | m^U | m^W | E | τ J1 | τ J2 | Gönüllü p | Merkez |
|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 2 | 2 | I6 | Hafif | 1 | 1.5 | 0.45 | 0 | 0 | 0.8 | 1.0 | 0.3437 | J1 |
| 3 | 3 | 4 | I7 | Hafif | 1 | 1.5 | 0.45 | 0 | 0 | 1.2 | 1.1 | 0.3309 | J2 |
| 5 | 4 | 6 | I8 | Hafif | 1 | 1.5 | 0.45 | 0 | 0 | 0.8 | 0.8 | 0.5165 | J2 |
| 7 | 5 | 8 | I9 | Hafif | 1 | 1.5 | 0.45 | 0 | 0 | 0.9 | 0.9 | 0.4721 | J1 |
| 9 | 6 | 10 | I10 | Hafif | 1 | 1.5 | 0.45 | 0 | 0 | 0.9 | 0.9 | 0.4990 | J1 |
| 11 | 7 | 12 | I11 | Ağır | 3 | 4.0 | 1.2 | 2.0 | 1 | 0.6 | 0.6 | 0.2983 | J2 |

Yerel koşu, olay başına bir operasyonel çözümdür. Tam ufuk için olay başı 60 saniye kabaca 6 dakika tutar. Kısa kontrol bir olay ve yalnız giriş periyodudur (`--periods 2 --max-events 1 --time-limit 15`).
