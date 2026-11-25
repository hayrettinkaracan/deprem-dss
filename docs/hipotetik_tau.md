# Enkaz–enkaz süreleri

Bu tablo **HYK onayıyla üretilmiş hipotetik veri**dir. END4902_20261125 Çizelge 5.1 yalnız merkez–enkaz sürelerini verir. Saat 1, 3, 5, 7, 9 ve 11 kayıtlarının içeriği de raporda yoktur; üretilmez.

## Yöntem

Her enkaz çifti `(i, i')` için, verilen merkez sürelerinden üçgen aralığı kurulur:

- alt sınır = max_j |τ_{i,j} − τ_{i',j}|
- üst sınır = min_j (τ_{i,j} + τ_{i',j})

Süre, aralığın orta noktasıdır ve 0,1 saate yuvarlanır. Tam yarıda yukarı yuvarlanır (1,25 → 1,3). Yuvarlama aralığın dışına düşerse, aralıkta kalan en yakın 0,1 saat alınır. τ_{i',i} = τ_{i,i'}.

Bu kural `data/section_5_3.py` içindeki `hypothetical_site_tau` ile aynıdır. 5.3'te yuvarlama aralığın içinde kalır.

## β ve h

β güzergâhın enkazına aittir (5.3: "I1 ve I5 güzergâhları"). Varış bir enkazsa o enkazın senaryo β'si kullanılır; iki enkaz arasındaki gecikme gidilen işin yoluna yazılır. Varış merkezse güzergâh çıkılan enkazındır. β periyot boyunca sabittir. h = 1 ancak τ(1+β) ≤ 2 (4.29). Yay yalnız h = 1 ise kurulur.

## Tablo (saat)

|  | I1 | I2 | I3 | I4 | I5 |
|---|---:|---:|---:|---:|---:|
| I1 | — | 0,8 | 1,2 | 1,3 | 1,3 |
| I2 | 0,8 | — | 1,1 | 1,3 | 1,3 |
| I3 | 1,2 | 1,1 | — | 0,8 | 1,0 |
| I4 | 1,3 | 1,3 | 0,8 | — | 1,0 |
| I5 | 1,3 | 1,3 | 1,0 | 1,0 | — |
