import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class ValidationTests(unittest.TestCase):
    def test_enkaz_isim_zorunlu(self):
        self.assertIn("Enkaz ismi zorunludur.", app.enkaz_hatalari("  ", 41, 28.9, 10))

    def test_enkaz_koordinat_ve_talep(self):
        self.assertTrue(any("Enlem" in h for h in app.enkaz_hatalari("A", 95, 28.9, 10)))
        self.assertTrue(any("Boylam" in h for h in app.enkaz_hatalari("A", 41, 200, 10)))
        self.assertIn("Talep 0'dan büyük olmalıdır.", app.enkaz_hatalari("A", 41, 28.9, 0))
        self.assertIn("Talep 1.000.000 kişiyi aşamaz.", app.enkaz_hatalari("A", 41, 28.9, 2_000_000))
        self.assertEqual(app.enkaz_hatalari("  Avcılar  ", 41, 28.9, 10), [])

    def test_ekip_kapasite(self):
        self.assertIn("Ekip ismi zorunludur.", app.ekip_hatalari("", 10))
        self.assertIn("Kapasite 0'dan büyük olmalıdır.", app.ekip_hatalari("AK", 0))
        self.assertIn("Kapasite 100.000 kişiyi aşamaz.", app.ekip_hatalari("AK", 100_001))
        self.assertEqual(app.ekip_hatalari("AK", 12), [])


class MemoryClientTests(unittest.TestCase):
    def test_batch_insert_tek_cagri(self):
        db = app.MemorySupabase()
        before = db.insert_calls
        rows = [
            {
                "isim": f"Test-{i}",
                "enlem": 41,
                "boylam": 29,
                "talep": 10,
                "makine_gerekli": 0,
                "durum": "aktif",
            }
            for i in range(10)
        ]
        result = db.table("enkazlar").insert(rows).execute()
        self.assertEqual(len(result.data), 10)
        self.assertEqual(db.insert_calls, before + 1)
        self.assertEqual(result.data[0]["id"] + 9, result.data[-1]["id"])

    def test_like_silme_digerlerini_birakir(self):
        db = app.MemorySupabase()
        db.table("enkazlar").insert(
            {
                "isim": "Kadıköy-Ek",
                "enlem": 40.9,
                "boylam": 29.0,
                "talep": 5,
                "makine_gerekli": 0,
                "durum": "aktif",
            }
        ).execute()
        db.table("enkazlar").delete().like("isim", "Avcılar-%").execute()
        isimler = [row["isim"] for row in db.table("enkazlar").select("isim").execute().data]
        self.assertFalse(any(isim.startswith("Avcılar-") for isim in isimler))
        self.assertIn("Kadıköy-Moda", isimler)
        self.assertIn("Kadıköy-Ek", isimler)

    def test_join_ve_id_filtresi(self):
        db = app.MemorySupabase()
        devam = (
            db.table("atamalar")
            .select("*, ekipler(isim), enkazlar(isim, talep)")
            .eq("durum", "devam")
            .execute()
            .data
        )
        self.assertEqual(len(devam), 1)
        self.assertEqual(devam[0]["ekipler"]["isim"], "AK-1")
        self.assertEqual(devam[0]["ekip_id"], 1)
        self.assertEqual(devam[0]["enkazlar"]["isim"], "Avcılar-Merkez")
        self.assertAlmostEqual(devam[0]["enkazlar"]["talep"], 820.4)
        yalniz = db.table("ekipler").select("id, isim").eq("id", 2).execute().data
        self.assertEqual(yalniz, [{"id": 2, "isim": "AK-1"}])

    def test_select_kopyadir(self):
        db = app.MemorySupabase()
        ilk = db.table("ekipler").select("*").execute().data
        ilk[0]["isim"] = "degisti"
        tekrar = db.table("ekipler").select("*").execute().data
        self.assertEqual(tekrar[0]["isim"], "AK-1")

    def test_upsert_yeni_satir(self):
        db = app.MemorySupabase()
        before = len(db.table("yardimci_kaynaklar").select("*").execute().data)
        db.table("yardimci_kaynaklar").upsert(
            {"enkaz_id": 4, "umke_sayisi": 9, "makine_sayisi": 0}
        ).execute()
        after = db.table("yardimci_kaynaklar").select("*").eq("enkaz_id", 4).execute().data
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["umke_sayisi"], 9)
        self.assertEqual(
            len(db.table("yardimci_kaynaklar").select("*").execute().data),
            before + 1,
        )


if __name__ == "__main__":
    unittest.main()
