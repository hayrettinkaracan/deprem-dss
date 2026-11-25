"""Yeni modelin arayüz bağlantısı. Küçük örnek, kısa süre sınırı, bellek istemcisi."""

from __future__ import annotations

from model.live_plan import (
    COZUM_YOK,
    PlanGirdiHatasi,
    atama_yaz,
    calistir_plan,
    gorunum,
    guvenli_hata,
    olay_guncelle,
)
from model.planning import PlanningSolution
from model.planning_inputs import build_planning_instance, ekip_tipi

from demo_client import MemorySupabase

import app


def _db():
    db = MemorySupabase()
    db.tables["enkazlar"] = [
        {
            "id": 1,
            "isim": "Kuzey",
            "enlem": 40.984,
            "boylam": 28.727,
            "talep": 2,
            "makine_gerekli": 0,
            "durum": "aktif",
        },
        {
            "id": 2,
            "isim": "Güney",
            "enlem": 40.970,
            "boylam": 28.700,
            "talep": 2,
            "makine_gerekli": 0,
            "durum": "aktif",
        },
    ]
    db.tables["ekipler"] = [
        {
            "id": 1,
            "isim": "AK-1",
            "tip": "Arama-Kurtarma",
            "kapasite": 1,
            "durum": "musait",
            "erisim_kodu": "gizli-1",
        },
        {
            "id": 2,
            "isim": "AK-2",
            "tip": "Arama-Kurtarma",
            "kapasite": 1,
            "durum": "musait",
            "erisim_kodu": "gizli-2",
        },
    ]
    db.tables["atamalar"] = []
    db._seq["enkazlar"] = 3
    db._seq["ekipler"] = 3
    db._seq["atamalar"] = 1
    return db


def _enkaz_ekip(db):
    return db.tables["enkazlar"], db.tables["ekipler"]


def test_kaynak_kimligi_ekip_numarasina_baglidir():
    enkaz = _db().tables["enkazlar"]
    birinci = {"id": 7, "isim": "Yedi", "tip": "Arama-Kurtarma", "kapasite": 1}
    ikinci = {"id": 9, "isim": "Dokuz", "tip": "Arama-Kurtarma", "kapasite": 1}
    araya = {"id": 8, "isim": "Sekiz", "tip": "Arama-Kurtarma", "kapasite": 1}
    _ilk, roster = build_planning_instance(enkaz, [ikinci, birinci])
    assert ekip_tipi(7) == "e7"
    assert {int(row["id"]): kaynak for row, kaynak in roster} == {7: "e7-1", 9: "e9-1"}
    _genis, genis = build_planning_instance(enkaz, [araya, birinci, ikinci])
    assert {int(row["id"]): kaynak for row, kaynak in genis}[7] == "e7-1"


def test_cozum_yoksa_turkce_uyari_ve_alt_sinir():
    db = _db()
    enkaz, ekipler = _enkaz_ekip(db)
    instance, roster = build_planning_instance(enkaz, ekipler, u_top=0, w_top=0)
    bos = PlanningSolution(
        status="Time limit",
        objective=None,
        z1_by_scenario={},
        gap=None,
        lower_bound=1.5,
        seconds=8,
        G={},
        V={},
        VU={},
        VW={},
        periods=2,
        horizon=4,
        teams=[],
        log_excerpt="no feasible solution found",
    )
    ozet = gorunum(instance, bos, roster, periyot=2, sure=8)
    assert ozet["level"] == "warning"
    assert ozet["uyari"] == COZUM_YOK
    assert "tam sayı" in ozet["mesaj"]
    assert "Traceback" not in ozet["mesaj"]
    assert ozet["alt_sinir"] == 1.5
    assert ozet["durum"] == "Süre sınırı"
    assert "Traceback" not in guvenli_hata(RuntimeError("Traceback (most recent call last):\nboom"))


def test_var_olan_atama_kapanmaz_yeni_ekibe_yazilir():
    db = _db()
    db.tables["atamalar"] = [
        {"id": 1, "ekip_id": 1, "enkaz_id": 1, "baslangic": "2026-11-23T06:30:00", "bitis": None, "durum": "devam"}
    ]
    db._seq["atamalar"] = 2
    yazilan = atama_yaz(
        db,
        [{"ekip_id": 1, "enkaz_id": 2}, {"ekip_id": 2, "enkaz_id": 2}],
        simdi="2026-11-25T10:00:00",
    )
    assert yazilan == 1
    eski = db.table("atamalar").select("*").eq("id", 1).execute().data[0]
    assert eski["durum"] == "devam"
    assert int(eski["enkaz_id"]) == 1
    yeni = db.table("atamalar").select("*").eq("ekip_id", 2).eq("durum", "devam").execute().data
    assert len(yeni) == 1
    assert int(yeni[0]["enkaz_id"]) == 2
    assert db.table("ekipler").select("*").eq("id", 2).execute().data[0]["durum"] == "meşgul"


def test_kucuk_plan_hedef_yazar_ve_operasyon_digere_dokunmaz():
    db = _db()
    enkaz, ekipler = _enkaz_ekip(db)
    ozet = calistir_plan(
        db,
        enkaz,
        ekipler,
        periods=2,
        time_limit=8,
        threads=1,
        u_top=0,
        w_top=0,
        simdi="2026-11-25T10:00:00",
    )
    assert ozet["level"] == "success"
    assert ozet["z1"] is not None
    assert ozet["durum"]
    assert "alt_sinir" in ozet
    assert "aralik" in ozet
    assert ozet["acik"]
    assert ozet["yerlesim"]
    assert ozet["program"]
    hucreler = " ".join(
        str(deger) for satir in ozet["program"] for deger in satir.values()
    )
    assert "Kuzey" in hucreler or "Güney" in hucreler
    assert "gizli" not in str(ozet)
    devam = db.table("atamalar").select("*").eq("durum", "devam").execute().data
    assert devam
    kayitli = db.table("planlar").select("*").execute().data
    assert len(kayitli) == 1
    assert kayitli[0]["ozet"]

    birinci = next(row for row in devam if int(row["ekip_id"]) == 1)
    ikinci = next((row for row in devam if int(row["ekip_id"]) == 2), None)
    bit = app.gorevi_bitir(db, 1, birinci["id"], simdi="2026-11-25T12:00:00")
    assert bit == "2026-11-25T12:00:00"
    assert db.table("atamalar").select("*").eq("id", birinci["id"]).execute().data[0]["durum"] == "bitti"
    if ikinci is not None:
        assert db.table("atamalar").select("*").eq("id", ikinci["id"]).execute().data[0]["durum"] == "devam"

    db.tables["enkazlar"].append(
        {
            "id": 3,
            "isim": "Doğu",
            "enlem": 40.990,
            "boylam": 28.740,
            "talep": 2,
            "makine_gerekli": 1,
            "durum": "aktif",
        }
    )
    db._seq["enkazlar"] = 4
    guncel = olay_guncelle(db, periods=2, time_limit=8, threads=1, simdi="2026-11-25T12:05:00")
    assert guncel is not None
    assert guncel["level"] == "success"
    assert db.table("atamalar").select("*").eq("id", birinci["id"]).execute().data[0]["durum"] == "bitti"
    if ikinci is not None:
        duran = db.table("atamalar").select("*").eq("id", ikinci["id"]).execute().data[0]
        assert duran["durum"] == "devam"
        assert int(duran["enkaz_id"]) == int(ikinci["enkaz_id"])
    yeni_metin = " ".join(str(deger) for satir in guncel["program"] for deger in satir.values())
    assert "Doğu" in yeni_metin or guncel["acik"]
    assert olay_guncelle(MemorySupabase()) is None


def test_girdi_yoksa_cozucu_calismaz():
    db = _db()
    try:
        calistir_plan(db, [], db.tables["ekipler"], periods=1, time_limit=1, threads=1, u_top=0, w_top=0)
    except PlanGirdiHatasi as exc:
        assert "müsait Arama-Kurtarma" in str(exc)
    else:
        raise AssertionError("girdi hatası beklenirdi")
