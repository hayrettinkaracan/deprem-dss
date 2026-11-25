# 5.3 planlama sonucu (Z1)

Aşağıdaki sayılar, merkez kopyaları henüz |I|+1 iken tek iş parçacığı ve 40 saniye sınırla alınmış bir ara koşudur. Güncel model, zaman penceresine sığmayan ℓ kopyalarını atar, aynı tür ekiplerin başlangıcını sıralar ve bütün çekirdekleri kullanır. Yeni sayı için:

```bash
python -m scripts.run_5_3 --mode z1 --time-limit 900 --threads 4 --out docs/sonuclar_5_3.md
```

Kaynak: END4902_20261125, Çizelge 5.1 ve (4.2), (4.7)–(4.27), (4.30)–(4.32), (4.34). (4.28), Z2 ve ε bu ara koşuda yok. Amaç yalnız beklenen ağırlıklı kümülatif kalan iştir.

Çözücü: PuLP 2.9.0, CBC 2.10.3, tek iş parçacığı, `gapRel = 0`, süre sınırı 40 saniye. Model 36 periyot, 3 senaryo, 9 ekiptir (yaklaşık 262 bin sütun). CBC kök aramasını bu sürede kapatamadı.

**Durum: süre sınırı. Kanıtlanmış optimal değildir.**

| | |
|---|---|
| Z1 (beklenen) | 113.7395 |
| Alt sınır | 39.902 |
| CBC aralığı (Z1 − alt sınır) / alt sınır | 1.85 |
| CBC duvar saati | 56 s |

CBC aralığı 1,85, çözümün alt sınıra yüzde 1,85 yakın olduğu anlamına gelmez. Optimal değer [39.902, 113.740] aralığındadır. Daha iyi bir tamsayı çözüm süre içinde bulunamadı; uydurma bir optimal değer yazılmadı.

## Senaryo amaçları

Aynı yerleşim üç senaryoda ortaktır (4.25). β seyahati uzattığı için periyotlara sığan iş senaryoya göre değişir.

| Senaryo | P | Z1_s |
|---|---:|---:|
| s1 iyimser | 0.30 | 108.67 |
| s2 beklenen | 0.45 | 113.58 |
| s3 kötümser | 0.25 | 120.11 |

0.30×108.67 + 0.45×113.58 + 0.25×120.11 = 113.7395.

## Açılan merkezler ve yerleştirme

İki merkez de açık: G_J1 = 1, G_J2 = 1.

| | J1 | J2 |
|---|---:|---:|
| Hafif | 0 | 1 |
| Orta | 1 | 1 |
| Ağır | 1 | 0 |
| UMKE | 1 | 2 |
| Makine | 1 | 1 |

## Ziyaret sırası (s1)

Saatler Bas–Bit çözümün içindedir; sıra şöyledir.

| Ekip | Zincir |
|---|---|
| hafif-1 | σ → o_J2 → I4 → J2 → ω |
| orta-1 | σ → o_J1 → I2 → J1 → ω |
| orta-2 | σ → o_J2 → I3 → J2 → ω |
| agir-1 | σ → o_J1 → I1 → I5 → J1 → ω |
| umke-1 | σ → o_J1 → I1 → J1 → I2 → J1 → ω |
| umke-2 | σ → o_J2 → I3 → J2 → I4 → J2 → ω |
| umke-3 | σ → o_J2 → J2'de bekler → I5 → J2 → ω |
| makine-1 | σ → o_J1 → I1 → J1 → I2 → J1 → ω |
| makine-2 | σ → o_J2 → I5 → J2 → ω |

Bu çözüm 5.3.2'nin bu dilimdeki denetimlerini sağlar: çalışma ile yol çakışmaz, hafif ekip yalnız I4'tedir, makine I3 ve I4'e girmez, ikinci fiziksel giriş yoktur, devam ikinci giriş sayılmaz, q sürelerin toplamıdır, UMKE 0,2 AFAD-saat birikmeden girmez, grup işi bitmeden ayrılış yoktur. ϑ = 0,01, η = 0,2.

## Hipotetik enkaz–enkaz süreleri

**HYK onayıyla üretilmiş hipotetik veri.** Çizelge 5.1'de yoktur. Orta nokta, 0,1 saate, tam yarıda yukarı. Ayrıntı: `docs/hipotetik_tau.md`.

|  | I1 | I2 | I3 | I4 | I5 |
|---|---:|---:|---:|---:|---:|
| I1 | — | 0.8 | 1.2 | 1.3 | 1.3 |
| I2 | 0.8 | — | 1.1 | 1.3 | 1.3 |
| I3 | 1.2 | 1.1 | — | 0.8 | 1.0 |
| I4 | 1.3 | 1.3 | 0.8 | — | 1.0 |
| I5 | 1.3 | 1.3 | 1.0 | 1.0 | — |

β, varış enkazının senaryo gecikmesidir. Merkeze dönüşte güzergâh çıkılan enkazındır. Bu tablodaki bütün çiftlerde, en kötü β = 0,50 ile bile τ(1+β) ≤ 1,95 ≤ 2 olduğundan h = 1'dir.
