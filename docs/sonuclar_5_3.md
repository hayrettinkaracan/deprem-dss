# 5.3 planlama sonucu (Z1)

Bu dosya `python -m scripts.run_5_3 --mode z1` ile üretildi.
Amaç yalnız (4.2). (4.28), Z2 ve ε yok.

- Durum: Time limit
- Süre sınırı: 900 s, çekirdek: tümü
- Çözücü duvar saati: 920.32
- Z1: 113.74
- Alt sınır: 39.909
- CBC aralığı (Z1 − alt sınır) / alt sınır: 1.85

Aralık 0 değilse sonuç kanıtlanmış optimal değildir.

## Senaryo

| Senaryo | Z1_s |
|---|---:|
| s1 | 108.67 |
| s2 | 113.58 |
| s3 | 120.11 |

## Açık merkezler ve yerleştirme

G = `{'J1': 1, 'J2': 1}`
V = `{('J1', 'hafif'): 0, ('J1', 'orta'): 1, ('J1', 'agir'): 1, ('J2', 'hafif'): 1, ('J2', 'orta'): 1, ('J2', 'agir'): 0}`
V^U = `{'J1': 1, 'J2': 2}`
V^W = `{'J1': 1, 'J2': 1}`

## Zincirler

- hafif-1 s1: σ → o_J2 → (I4,1) → (I4,2) → (J2,2,1) → ω
- orta-1 s1: σ → o_J1 → (I2,1) → (I2,2) → (J1,3,1) → ω
- orta-2 s1: σ → o_J2 → (I3,1) → (I3,2) → (J2,2,1) → ω
- agir-1 s1: σ → o_J1 → (I1,1) → (I1,2) → (I1,3) → (I5,4) → (I5,5) → (I5,6) → (J2,7,1) → ω
- umke-1 s1: σ → o_J1 → (I1,2) → (I1,3) → (J1,3,1) → (I2,4) → (J1,4,1) → ω
- umke-2 s1: σ → o_J2 → (I3,2) → (J2,3,1) → (I4,3) → (J2,4,1) → ω
- umke-3 s1: σ → o_J2 → (J2,1,1) → (J2,2,1) → (J2,3,1) → (J2,4,1) → (I5,5) → (I5,6) → (J2,7,1) → ω
- makine-1 s1: σ → o_J1 → (I1,1) → (I1,2) → (J1,3,1) → (I2,3) → (I2,4) → (J1,4,1) → ω
- makine-2 s1: σ → o_J2 → (I5,1) → (I5,2) → (J2,3,1) → ω
- hafif-1 s2: σ → o_J2 → (I4,1) → (I4,2) → (J2,2,1) → ω
- orta-1 s2: σ → o_J1 → (I2,1) → (I2,2) → (J1,3,1) → ω
- orta-2 s2: σ → o_J2 → (I3,1) → (I3,2) → (J2,2,1) → ω
- agir-1 s2: σ → o_J1 → (I1,1) → (I1,2) → (I1,3) → (I5,4) → (I5,5) → (I5,6) → (J2,7,1) → ω
- umke-1 s2: σ → o_J1 → (I1,2) → (I1,3) → (J1,3,1) → (I2,4) → (J1,4,1) → ω
- umke-2 s2: σ → o_J2 → (I3,2) → (J2,3,1) → (I4,3) → (J2,4,1) → ω
- umke-3 s2: σ → o_J2 → (J2,1,1) → (J2,2,1) → (J2,3,1) → (J2,4,1) → (I5,5) → (I5,6) → (J2,7,1) → ω
- makine-1 s2: σ → o_J1 → (I1,1) → (I1,2) → (J1,3,1) → (I2,3) → (I2,4) → (J1,4,1) → ω
- makine-2 s2: σ → o_J2 → (I5,1) → (I5,2) → (J2,3,1) → ω
- hafif-1 s3: σ → o_J2 → (I4,1) → (I4,2) → (J2,2,1) → ω
- orta-1 s3: σ → o_J1 → (I2,1) → (I2,2) → (J1,3,1) → ω
- orta-2 s3: σ → o_J2 → (I3,1) → (I3,2) → (J2,2,1) → ω
- agir-1 s3: σ → o_J1 → (I1,1) → (I1,2) → (I1,3) → (I5,4) → (I5,5) → (I5,6) → (J2,7,1) → ω
- umke-1 s3: σ → o_J1 → (I1,2) → (I1,3) → (J1,3,1) → (I2,4) → (J1,4,1) → ω
- umke-2 s3: σ → o_J2 → (I3,2) → (J2,3,1) → (I4,3) → (J2,4,1) → ω
- umke-3 s3: σ → o_J2 → (J2,1,1) → (J2,2,1) → (J2,3,1) → (J2,4,1) → (I5,5) → (I5,6) → (J2,7,1) → ω
- makine-1 s3: σ → o_J1 → (I1,1) → (I1,2) → (J1,3,1) → (I2,3) → (I2,4) → (J1,4,1) → ω
- makine-2 s3: σ → o_J2 → (I5,1) → (I5,2) → (J2,3,1) → ω

## Çözücü çıktısı

```
Cbc0010I After 100 nodes, 43 on tree, 113.7395 best solution, best possible 39.908503 (150.93 seconds)
Cbc0010I After 200 nodes, 73 on tree, 113.7395 best solution, best possible 39.908503 (342.71 seconds)
Cbc0010I After 300 nodes, 97 on tree, 113.7395 best solution, best possible 39.908503 (588.25 seconds)
Cbc0010I After 400 nodes, 124 on tree, 113.7395 best solution, best possible 39.908503 (859.91 seconds)
Cbc0030I Thread 0 used 53 times,  waiting to start 1.3306084,  252 locks, 0.048688173 locked, 8.0108643e-05 waiting for locks
Cbc0030I Thread 1 used 54 times,  waiting to start 8.5442376,  263 locks, 0.058717012 locked, 6.7472458e-05 waiting for locks
Cbc0030I Thread 2 used 69 times,  waiting to start 25.862386,  331 locks, 0.064759731 locked, 0.00011610985 waiting for locks
Cbc0030I Thread 3 used 27 times,  waiting to start 17.876069,  130 locks, 0.033046961 locked, 3.7431717e-05 waiting for locks
Cbc0030I Thread 4 used 34 times,  waiting to start 18.002504,  167 locks, 0.034399748 locked, 4.8398972e-05 waiting for locks
Cbc0030I Thread 5 used 45 times,  waiting to start 26.558329,  219 locks, 0.043025017 locked, 7.3194504e-05 waiting for locks
Cbc0030I Thread 6 used 32 times,  waiting to start 23.37712,  154 locks, 0.031981945 locked, 4.2915344e-05 waiting for locks
Cbc0030I Thread 7 used 34 times,  waiting to start 31.684464,  164 locks, 0.036005259 locked, 4.529953e-05 waiting for locks
Cbc0030I Thread 8 used 44 times,  waiting to start 20.663253,  215 locks, 0.044070244 locked, 6.7472458e-05 waiting for locks
Cbc0030I Thread 9 used 38 times,  waiting to start 37.283394,  183 locks, 0.038748503 locked, 6.0558319e-05 waiting for locks
Cbc0030I Main thread 888.03789 waiting for threads,  867 locks, 0.00086593628 locked, 0.00024080276 waiting for locks
Cbc0020I Exiting on maximum time
Cbc0005I Partial search - best objective 113.7395 (best possible 39.908503), took 4790320 iterations and 421 nodes (919.21 seconds)
Cbc0032I Strong branching done 7598 times (517021 iterations), fathomed 18 nodes and fixed 358 variables
Cbc0035I Maximum depth 24, 15975 variables fixed on reduced cost
Cuts at root node changed objective from 39.9048 to 39.9048
Result - Stopped on time limit
Objective value:                113.73950000
Lower bound:                    39.909
Gap:                            1.85
Enumerated nodes:               421
Total iterations:               4790320
Time (CPU seconds):             8073.28
Time (Wallclock seconds):       919.83
Option for printingOptions changed from normal to all
Total time (CPU seconds):       8073.71   (Wallclock seconds):       920.32
```
