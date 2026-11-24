import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest

import app

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")


def alerts(at):
    return [el.value for el in (*at.success, *at.warning, *at.error, *at.info)]


def assert_clean(testcase, at):
    if at.exception:
        lines = []
        for exc in at.exception:
            lines.extend(getattr(exc, "stack_trace", []) or [])
            lines.append(str(getattr(exc, "value", exc)))
        testcase.fail("\n".join(lines))


def frame_with(at, column):
    for item in at.dataframe:
        if column in item.value.columns:
            return item.value
    raise AssertionError(f"{column} sütunu yok")


def admin_giris(at, parola="demo"):
    at.text_input(key="admin_parola").set_value(parola)
    return at.button(key="admin_giris").click().run()


def ekip_giris(at, ekip_id, kod):
    at = at.selectbox(key="rol").set_value("Ekip").run()
    at.selectbox(key="ekip_giris_sec").set_value(ekip_id)
    at.text_input(key="ekip_giris_kod").set_value(kod)
    return at.button(key="ekip_giris").click().run()


class ParolaTests(unittest.TestCase):
    def test_parola_yoksa_admin_kapali_denemede_demo(self):
        self.assertEqual(app.yonetici_parolasi(None, None, False), (None, False))
        self.assertEqual(app.yonetici_parolasi("  ", "", False), (None, False))
        self.assertEqual(app.yonetici_parolasi(None, None, True), (app.DEMO_ADMIN_PAROLA, True))
        self.assertEqual(app.yonetici_parolasi(None, "ortam", True), ("ortam", False))
        self.assertEqual(app.yonetici_parolasi("dosya", "ortam", False), ("dosya", False))

    def test_karsilastirma(self):
        self.assertTrue(app.parola_eslesir(" demo ", "demo"))
        self.assertTrue(app.parola_eslesir("şifre", "şifre"))
        self.assertFalse(app.parola_eslesir("demo", "Demo"))
        self.assertFalse(app.parola_eslesir("sifre", "şifre"))
        self.assertFalse(app.parola_eslesir("", "demo"))
        self.assertFalse(app.parola_eslesir("demo", None))
        self.assertFalse(app.parola_eslesir("yanlis", "demo"))

    def test_ekip_kodu_sonucu(self):
        self.assertEqual(app.ekip_kodu_sonucu(None, "a"), "yok")
        self.assertEqual(app.ekip_kodu_sonucu({"erisim_kodu": None}, "a"), "tanimli_degil")
        self.assertEqual(app.ekip_kodu_sonucu({"erisim_kodu": "  "}, "a"), "tanimli_degil")
        self.assertEqual(app.ekip_kodu_sonucu({"erisim_kodu": "ekip-1"}, "  "), "bos")
        self.assertEqual(app.ekip_kodu_sonucu({"erisim_kodu": "ekip-1"}, "ekip-2"), "hatali")
        self.assertEqual(app.ekip_kodu_sonucu({"erisim_kodu": "ekip-1"}, "ekip-1"), "tamam")

    def test_kod_uzunlugu(self):
        self.assertEqual(app.ekip_hatalari("AK", 10, "kisa"), [])
        self.assertIn(
            "Erişim kodu en fazla 80 karakter olabilir.",
            app.ekip_hatalari("AK", 10, "a" * 81),
        )

    def test_kod_modele_girmez(self):
        rows = app.modelsiz_ekip([{"id": 1, "kapasite": 3, "erisim_kodu": "gizli"}])
        self.assertEqual(rows, [{"id": 1, "kapasite": 3}])
        self.assertEqual(app.modelsiz_ekip([{"id": 2}])[0], {"id": 2})

    def test_baska_ekip_gorevi_kapanmaz(self):
        from demo_client import MemorySupabase

        db = MemorySupabase()
        self.assertEqual(
            {int(row["id"]): row["erisim_kodu"] for row in db.table("ekipler").select("*").execute().data},
            {1: "ekip-1", 2: "ekip-2", 3: "ekip-3"},
        )
        self.assertIsNone(app.gorevi_bitir(db, 2, 1))
        self.assertIsNone(app.gorevi_bitir(db, 3, 1))
        self.assertEqual(db.table("atamalar").select("*").eq("id", 1).execute().data[0]["durum"], "devam")
        self.assertEqual(db.table("ekipler").select("*").eq("id", 1).execute().data[0]["durum"], "meşgul")
        bit = app.gorevi_bitir(db, 1, 1, simdi="2026-11-23T12:00:00")
        self.assertEqual(bit, "2026-11-23T12:00:00")
        kapali = db.table("atamalar").select("*").eq("id", 1).execute().data[0]
        self.assertEqual(kapali["durum"], "bitti")
        self.assertEqual(kapali["bitis"], bit)
        self.assertEqual(db.table("ekipler").select("*").eq("id", 1).execute().data[0]["durum"], "musait")
        self.assertIsNone(app.gorevi_bitir(db, 1, 1))


class GirisTests(unittest.TestCase):
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

    def test_giris_formu_etiketli(self):
        at = self.app()
        assert_clean(self, at)
        for widget in (*at.text_input, *at.selectbox, *at.button):
            self.assertTrue(str(widget.label).strip())
        self.assertEqual(at.text_input(key="admin_parola").label, "Yönetici parolası")
        self.assertTrue(at.button(key="admin_giris").form_id)
        self.assertTrue(any("Yönetici parolası: demo" in m for m in alerts(at)))
        at = at.selectbox(key="rol").set_value("Ekip").run()
        assert_clean(self, at)
        self.assertEqual(at.text_input(key="ekip_giris_kod").label, "Erişim kodu")
        self.assertEqual(at.selectbox(key="ekip_giris_sec").label, "Ekip")
        self.assertTrue(at.button(key="ekip_giris").form_id)
        self.assertTrue(any("ekip-1" in m and "ekip-2" in m for m in alerts(at)))

    def test_admin_parola_yoksa_panel_kapali(self):
        os.environ.pop("DEPREM_DEMO", None)
        os.environ.pop("ADMIN_PASSWORD", None)
        at = AppTest.from_file(APP, default_timeout=30)
        at.secrets["SUPABASE_URL"] = "https://example.supabase.co"
        at.secrets["SUPABASE_KEY"] = "test-key"
        at = at.run()
        assert_clean(self, at)
        self.assertTrue(any("ADMIN_PASSWORD" in m and "tanımlı değil" in m for m in alerts(at)))
        self.assertIn("secrets.toml", "\n".join(alerts(at)))
        self.assertFalse(any(el.value == "Admin Paneli" for el in at.header))
        self.assertFalse(any(w.key == "admin_parola" for w in at.text_input))
        self.assertFalse(any(el.value == "Enkaz Ekle" for el in at.subheader))

    def test_yanlis_parola_reddedilir(self):
        at = self.app()
        self.assertFalse(any(el.value == "Admin Paneli" for el in at.header))
        at.text_input(key="admin_parola").set_value("yanlis")
        at = at.button(key="admin_giris").click().run()
        assert_clean(self, at)
        self.assertTrue(any(m == "Parola hatalı." for m in alerts(at)))
        self.assertFalse(any(el.value == "Admin Paneli" for el in at.header))
        self.assertNotIn("auth", at.session_state)
        self.assertGreaterEqual(at.session_state["giris_hata"], 1)

    def test_bos_parola(self):
        at = self.app()
        at.text_input(key="admin_parola").set_value("   ")
        at = at.button(key="admin_giris").click().run()
        assert_clean(self, at)
        self.assertTrue(any(m == "Parola zorunludur." for m in alerts(at)))
        self.assertNotIn("auth", at.session_state)
        self.assertNotIn("giris_hata", at.session_state)

    def test_dogru_parola_ve_cikis(self):
        at = admin_giris(self.app())
        assert_clean(self, at)
        self.assertTrue(any(el.value == "Admin Paneli" for el in at.header))
        self.assertEqual(dict(at.session_state["auth"]), {"rol": "Admin"})
        at = at.button(key="cikis").click().run()
        assert_clean(self, at)
        self.assertNotIn("auth", at.session_state)
        self.assertFalse(any(el.value == "Admin Paneli" for el in at.header))
        self.assertTrue(any(w.key == "admin_parola" for w in at.text_input))
        self.assertFalse(any(w.key == "cikis" for w in at.button))

    def test_ortam_parolasi_deneme_parolasini_gecersiz_kilar(self):
        os.environ["ADMIN_PASSWORD"] = "gizli-sifre"
        at = self.app()
        assert_clean(self, at)
        metin = "\n".join(alerts(at))
        self.assertNotIn("gizli-sifre", metin)
        self.assertNotIn("Yönetici parolası: demo", metin)
        at.text_input(key="admin_parola").set_value("demo")
        at = at.button(key="admin_giris").click().run()
        self.assertTrue(any(m == "Parola hatalı." for m in alerts(at)))
        at.text_input(key="admin_parola").set_value("gizli-sifre")
        at = at.button(key="admin_giris").click().run()
        assert_clean(self, at)
        self.assertEqual(at.session_state["auth"]["rol"], "Admin")

    def test_secrets_parolasi(self):
        at = AppTest.from_file(APP, default_timeout=30)
        at.secrets["ADMIN_PASSWORD"] = "dosya-sifre"
        at = at.run()
        assert_clean(self, at)
        self.assertFalse(any("dosya-sifre" in m for m in alerts(at)))
        at.text_input(key="admin_parola").set_value("demo")
        at = at.button(key="admin_giris").click().run()
        self.assertTrue(any(m == "Parola hatalı." for m in alerts(at)))
        at.text_input(key="admin_parola").set_value("dosya-sifre")
        at = at.button(key="admin_giris").click().run()
        assert_clean(self, at)
        self.assertTrue(any(el.value == "Admin Paneli" for el in at.header))

    def test_baska_ekibin_gorevi_gorunmez(self):
        at = ekip_giris(self.app(), 2, "ekip-1")
        assert_clean(self, at)
        self.assertTrue(any(m == "Erişim kodu hatalı." for m in alerts(at)))
        self.assertNotIn("auth", at.session_state)
        at = ekip_giris(self.app(), 2, "ekip-2")
        assert_clean(self, at)
        metin = "\n".join([*alerts(at), *(el.value for el in at.caption)])
        self.assertIn("aktif görevin yok", metin)
        self.assertNotIn("Aktif görev", metin)
        self.assertNotIn("Avcılar-Merkez", metin)
        self.assertFalse(any(w.key == "gorev_bitti" for w in at.button))
        db = at.session_state["memory_db"]
        self.assertIsNone(app.gorevi_bitir(db, at.session_state["auth"]["ekip_id"], 1))
        self.assertEqual(db.table("atamalar").select("*").eq("id", 1).execute().data[0]["durum"], "devam")
        self.assertEqual(db.table("ekipler").select("*").eq("id", 1).execute().data[0]["durum"], "meşgul")

    def test_yonetici_kod_verir_ekip_girer(self):
        at = admin_giris(self.app())
        at.text_input(key="ekip_isim").set_value("AK-Yeni")
        at.text_input(key="ekip_kod").set_value("yeni-kod")
        at = at.button(key="ekip_ekle").click().run()
        assert_clean(self, at)
        self.assertIn("yeni-kod", set(frame_with(at, "Erişim kodu")["Erişim kodu"]))
        db = at.session_state["memory_db"]
        yeni_id = int(db.table("ekipler").select("*").eq("isim", "AK-Yeni").execute().data[0]["id"])
        at = at.button(key="cikis").click().run()
        at = ekip_giris(at, yeni_id, "yeni-kod")
        assert_clean(self, at)
        self.assertEqual(int(at.session_state["auth"]["ekip_id"]), yeni_id)
        self.assertTrue(any("aktif görevin yok" in m for m in alerts(at)))
        self.assertFalse(any("Aktif görev" in m for m in alerts(at)))


if __name__ == "__main__":
    unittest.main()
