import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest

import app
from demo_client import MemorySupabase

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")


def alerts(at):
    return [el.value for el in (*at.success, *at.warning, *at.error, *at.info)]


def html_metin(at):
    return "\n".join(el.value for el in at.html)


def assert_clean(testcase, at):
    if at.exception:
        lines = []
        for exc in at.exception:
            lines.extend(getattr(exc, "stack_trace", []) or [])
            lines.append(str(getattr(exc, "value", exc)))
        testcase.fail("\n".join(lines))


def ekip_giris(at, ekip_id, kod):
    at = at.selectbox(key="rol").set_value("Ekip").run()
    at.selectbox(key="ekip_giris_sec").set_value(ekip_id)
    at.text_input(key="ekip_giris_kod").set_value(kod)
    return at.button(key="ekip_giris").click().run()


class _KopukSupabase(MemorySupabase):
    def execute(self, query):
        if query.op == "select":
            raise ConnectionError("supabase timeout\nTraceback (most recent call last): boom")
        return super().execute(query)


class GorevMetinTests(unittest.TestCase):
    def test_sure_ve_talep(self):
        bas = "2026-11-23T06:30:00"
        self.assertEqual(app.gecen_sure(bas, datetime(2026, 11, 23, 8, 0, 0)), "1 saat 30 dakika")
        self.assertEqual(app.gecen_sure(bas, datetime(2026, 11, 24, 6, 30, 0)), "1 gün")
        self.assertEqual(app.gecen_sure(bas, datetime(2026, 11, 24, 8, 35, 0)), "1 gün 2 saat 5 dakika")
        self.assertEqual(app.gecen_sure(bas, datetime(2026, 11, 23, 6, 30, 30)), "0 dakika")
        self.assertEqual(app.gecen_sure("2026-11-23T08:00:00", datetime(2026, 11, 23, 6, 30)), "—")
        self.assertEqual(app.gecen_sure(None, datetime(2026, 11, 23, 6, 30)), "—")
        self.assertEqual(app.gecen_sure("yok", datetime(2026, 11, 23, 6, 30)), "—")
        self.assertEqual(app.talep_metni(820.4), "820 kişi")
        self.assertEqual(app.talep_metni(None), "—")
        self.assertEqual(app.talep_metni("yok"), "—")

    def test_harita_ve_yardimci(self):
        google, geo = app.harita_baglari(40.9792, 28.7214)
        self.assertEqual(
            google,
            "https://www.google.com/maps/search/?api=1&query=40.979200,28.721400",
        )
        self.assertEqual(geo, "geo:40.979200,28.721400")
        self.assertEqual(app.harita_baglari(None, 1), (None, None))
        self.assertEqual(app.harita_baglari(91, 0), (None, None))
        self.assertEqual(app.konum_metni(40.9792, 28.7214), "40.97920° K, 28.72140° D")
        self.assertEqual(app.konum_metni(-33.8, -70.6), "33.80000° G, 70.60000° B")
        self.assertEqual(app.konum_metni("x", 1), "Konum yok")
        self.assertEqual(app.yardimci_metni([]), "Atanmadı")
        self.assertEqual(
            app.yardimci_metni(
                [
                    {"id": 1, "umke_sayisi": 2, "makine_sayisi": 1},
                    {"id": 5, "umke_sayisi": 9, "makine_sayisi": 3},
                ]
            ),
            "UMKE 9, iş makinesi 3",
        )

    def test_gorev_satirlari_kacis_ve_css(self):
        atama = {
            "id": 1,
            "ekip_id": 1,
            "enkaz_id": 1,
            "baslangic": "2026-11-23T06:30:00",
            "durum": "devam",
            "enkazlar": {
                "isim": "Avcılar-Merkez",
                "talep": 820.4,
                "enlem": 40.9792,
                "boylam": 28.7214,
                "makine_gerekli": 1,
            },
        }
        ekip = {"id": 1, "isim": "AK-1", "durum": "meşgul"}
        simdi = datetime(2026, 11, 23, 8, 0, 0)
        satirlar, google, _geo = app.gorev_satirlari(
            ekip,
            atama,
            [{"id": 2, "umke_sayisi": 2, "makine_sayisi": 1}],
            simdi=simdi,
        )
        sozluk = dict(satirlar)
        self.assertEqual(app.gorev_basligi(atama), "Görev: Avcılar-Merkez (#1)")
        self.assertNotIn("Enkaz", sozluk)
        self.assertNotIn("Durum", sozluk)
        self.assertEqual(sozluk["Talep"], "820 kişi")
        self.assertEqual(sozluk["İş makinesi gerekli"], "Evet")
        self.assertEqual(sozluk["Yardımcı kaynak"], "UMKE 2, iş makinesi 1")
        self.assertEqual(sozluk["Başlangıç"], "23.11.2026 06:30")
        self.assertEqual(sozluk["Geçen süre"], "1 saat 30 dakika")
        self.assertIn("40.979200,28.721400", google)
        makinesiz = dict(atama)
        makinesiz["enkazlar"] = dict(atama["enkazlar"], makine_gerekli=0)
        self.assertEqual(
            dict(app.gorev_satirlari(ekip, makinesiz, [], simdi=simdi)[0])["İş makinesi gerekli"],
            "Hayır",
        )
        self.assertEqual(
            dict(app.gorev_satirlari(ekip, atama, [], simdi=simdi)[0])["Yardımcı kaynak"],
            "Atanmadı",
        )
        kacis = app.gorev_html([("Enkaz", "<b>")])
        self.assertIn("&lt;b&gt;", kacis)
        self.assertNotIn("<b>", kacis)
        self.assertIn("48px", app.EKIP_TELEFON_CSS)
        self.assertIn("44px", app.EKIP_TELEFON_CSS)
        onay = app.ekip_onay_metni("Avcılar-Merkez")
        self.assertEqual(
            onay,
            "Bu ekibin Avcılar-Merkez görevi biter ve ekip müsait olur. "
            "Aynı enkazdaki diğer ekipler çalışmaya devam eder.",
        )
        self.assertNotIn("kapanır", onay)
        self.assertNotIn("durur", onay)
        bitti = app.ekip_bitti_metni(
            "AK-1", 1, "Avcılar-Merkez", "23.11.2026 06:30", "24.11.2026 12:00"
        )
        self.assertTrue(bitti.startswith("Görev bitti."))
        self.assertIn("Görev tamamlandı: AK-1 (#1)", bitti)
        self.assertIn("23.11.2026 06:30", bitti)
        self.assertIn("Diğer ekipler aynı enkazda devam edebilir.", bitti)


class EkipEkranTests(unittest.TestCase):
    def setUp(self):
        self._eski_parola = os.environ.pop("ADMIN_PASSWORD", None)
        os.environ["DEPREM_DEMO"] = "1"

    def tearDown(self):
        os.environ.pop("DEPREM_DEMO", None)
        if self._eski_parola is None:
            os.environ.pop("ADMIN_PASSWORD", None)
        else:
            os.environ["ADMIN_PASSWORD"] = self._eski_parola

    def app(self):
        return AppTest.from_file(APP, default_timeout=30).run()

    def test_gorev_yok(self):
        at = ekip_giris(self.app(), 2, "ekip-2")
        assert_clean(self, at)
        self.assertTrue(any(m == app.EKIP_GOREV_YOK for m in alerts(at)))
        self.assertFalse(any(w.key == "gorev_bitti" for w in at.button))
        self.assertFalse(any(w.key == "harita_google" for w in at.link_button))
        self.assertNotIn("geo:", html_metin(at))
        self.assertEqual(len(at.dataframe), 0)
        self.assertEqual(len(at.tabs), 0)
        self.assertIn("AK-1 (#2)", html_metin(at))
        self.assertIn("Müsait", html_metin(at))
        self.assertTrue(any(w.key == "cikis" for w in at.button))
        self.assertTrue(any(w.key == "rol" for w in at.selectbox))
        self.assertFalse(any(w.key == "senaryo" for w in at.selectbox))

    def test_aktif_gorev_harita_ve_onay(self):
        at = ekip_giris(self.app(), 1, "ekip-1")
        assert_clean(self, at)
        govde = html_metin(at)
        self.assertTrue(any(el.value == "Görev: Avcılar-Merkez (#1)" for el in at.subheader))
        self.assertIn("AK-1 (#1)", govde)
        self.assertIn("Meşgul", govde)
        self.assertIn("820 kişi", govde)
        self.assertIn("İş makinesi gerekli", govde)
        self.assertIn("Evet", govde)
        self.assertIn("UMKE 2, iş makinesi 1", govde)
        self.assertIn("23.11.2026 06:30", govde)
        self.assertIn("Geçen süre", govde)
        self.assertNotIn("Geçen süre:</strong> —", govde)
        self.assertIn("40.97920° K, 28.72140° D", govde)
        self.assertIn("Google Haritalar", govde)
        self.assertIn("Harita uygulaması", govde)
        self.assertIn(
            'href="https://www.google.com/maps/search/?api=1&amp;query=40.979200,28.721400"',
            govde,
        )
        self.assertIn('href="geo:40.979200,28.721400"', govde)
        self.assertEqual(len(at.link_button), 0)
        self.assertEqual(len(at.dataframe), 0)
        self.assertEqual(len(at.tabs), 0)
        self.assertIn("48px", govde)
        db = at.session_state["memory_db"]
        at.button(key="gorev_bitti").click().run()
        assert_clean(self, at)
        self.assertEqual(db.table("atamalar").select("*").eq("id", 1).execute().data[0]["durum"], "devam")
        self.assertTrue(any("görevi biter" in m and "Avcılar-Merkez" in m for m in alerts(at)))
        self.assertTrue(any("çalışmaya devam eder" in m for m in alerts(at)))
        self.assertFalse(any("kapanır" in m or "durur" in m for m in alerts(at)))
        self.assertTrue(any(w.key == "gorev_bitti_vazgec" for w in at.button))
        self.assertTrue(any(w.key == "gorev_bitti_onay" for w in at.button))
        self.assertFalse(any(w.key == "gorev_bitti" for w in at.button))
        self.assertFalse(any("Görev tamamlandı" in m for m in alerts(at)))
        at.button(key="gorev_bitti_vazgec").click().run()
        assert_clean(self, at)
        self.assertEqual(db.table("atamalar").select("*").eq("id", 1).execute().data[0]["durum"], "devam")
        self.assertTrue(any(w.key == "gorev_bitti" for w in at.button))
        self.assertFalse(any("görevi biter" in m for m in alerts(at)))
        at.button(key="gorev_bitti").click().run()
        at.button(key="gorev_bitti_onay").click().run()
        assert_clean(self, at)
        kapali = db.table("atamalar").select("*").eq("id", 1).execute().data[0]
        self.assertEqual(kapali["durum"], "bitti")
        self.assertIsNotNone(kapali["bitis"])
        self.assertEqual(db.table("ekipler").select("*").eq("id", 1).execute().data[0]["durum"], "musait")
        metin = "\n".join(alerts(at))
        self.assertIn("Görev bitti.", metin)
        self.assertIn("Görev tamamlandı: AK-1 (#1) → Avcılar-Merkez.", metin)
        self.assertIn("23.11.2026 06:30", metin)
        self.assertIn("Diğer ekipler aynı enkazda devam edebilir.", metin)
        self.assertNotIn(app.EKIP_GOREV_YOK, metin)
        at.run()
        assert_clean(self, at)
        self.assertTrue(any(m.startswith("Görev bitti.") for m in alerts(at)))
        self.assertFalse(any(w.key == "gorev_bitti" for w in at.button))

    def test_ekip_ekrani_az_sorgu(self):
        at = self.app()
        at = at.selectbox(key="rol").set_value("Ekip").run()
        taban = at.session_state["memory_db"].select_count
        self.assertGreater(taban, 0)
        at.selectbox(key="ekip_giris_sec").set_value(2)
        at.text_input(key="ekip_giris_kod").set_value("ekip-2")
        at = at.button(key="ekip_giris").click().run()
        assert_clean(self, at)
        self.assertEqual(at.session_state["memory_db"].select_count, taban + 2)
        at.run()
        self.assertEqual(at.session_state["memory_db"].select_count, taban + 2)
        at = at.button(key="cikis").click().run()
        at.selectbox(key="ekip_giris_sec").set_value(1)
        at.text_input(key="ekip_giris_kod").set_value("ekip-1")
        once = at.session_state["memory_db"].select_count
        at = at.button(key="ekip_giris").click().run()
        assert_clean(self, at)
        self.assertEqual(at.session_state["memory_db"].select_count, once + 3)
        at.run()
        self.assertEqual(at.session_state["memory_db"].select_count, once + 3)

    def test_baglanti_hatasi_yeniden_dene(self):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["memory_db"] = _KopukSupabase()
        at.session_state["rol"] = "Ekip"
        at.session_state["auth"] = {"rol": "Ekip", "ekip_id": 1}
        at = at.run()
        assert_clean(self, at)
        metin = "\n".join([*alerts(at), html_metin(at)])
        self.assertIn(app.EKIP_BAGLANTI, metin)
        self.assertNotIn("Traceback", metin)
        self.assertNotIn("supabase timeout", metin)
        self.assertTrue(any(w.key == "ekip_yeniden" for w in at.button))
        self.assertFalse(any(w.key == "gorev_bitti" for w in at.button))
        self.assertEqual(len(at.dataframe), 0)
        at.session_state["memory_db"] = MemorySupabase()
        at.button(key="ekip_yeniden").click().run()
        assert_clean(self, at)
        self.assertTrue(any(el.value == "Görev: Avcılar-Merkez (#1)" for el in at.subheader))
        self.assertIn("820 kişi", html_metin(at))
        self.assertFalse(any(m == app.EKIP_BAGLANTI for m in alerts(at)))
        self.assertFalse(any(w.key == "ekip_yeniden" for w in at.button))


if __name__ == "__main__":
    unittest.main()
