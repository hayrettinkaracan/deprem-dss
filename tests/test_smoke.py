import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from streamlit.testing.v1 import AppTest

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


class SmokeTests(unittest.TestCase):
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

    def test_anahtar_yoksa_uygulama_durur(self):
        os.environ.pop("DEPREM_DEMO", None)
        at = AppTest.from_file(APP, default_timeout=30).run()
        assert_clean(self, at)
        metin = "\n".join(alerts(at))
        self.assertIn("Supabase anahtarları bulunamadı", metin)
        self.assertIn("DEPREM_DEMO=1", metin)
        self.assertFalse(any(el.value == "Admin Paneli" for el in at.header))

    def test_admin_sayfalari(self):
        at = admin_giris(self.app())
        assert_clean(self, at)
        self.assertTrue(any("kaydedilmez" in m for m in alerts(at)))
        self.assertTrue(any(el.value == "Admin Paneli" for el in at.header))
        self.assertTrue(any("İBB-KRDAE" in el.value for el in at.info))
        enkaz = frame_with(at, "Talep (kişi)")
        self.assertNotIn("id", enkaz.columns)
        self.assertNotIn("makine_gerekli", enkaz.columns)
        self.assertIn("Evet", set(enkaz["İş makinesi"]))
        self.assertIn("Hayır", set(enkaz["İş makinesi"]))
        self.assertIn("Aktif", set(enkaz["Durum"]))
        self.assertIn("Tamam", set(enkaz["Durum"]))
        atama = frame_with(at, "Başlangıç")
        self.assertNotIn("id", atama.columns)
        self.assertIn("23.11.2026 06:30", set(atama["Başlangıç"]))
        self.assertNotIn("2026-11-23T06:30:00", set(atama["Başlangıç"]))
        self.assertIn("Devam ediyor", set(atama["Durum"]))
        for item in at.dataframe:
            self.assertNotIn("id", item.value.columns)
            self.assertNotIn("makine_gerekli", item.value.columns)
        self.assertTrue(any("Harita:" in el.value and "büyük nokta" in el.value for el in at.caption))
        haritalar = list(at.get("deck_gl_json_chart"))
        self.assertGreaterEqual(len(haritalar), 1)
        self.assertIn("aktif", haritalar[0].proto.alt)
        for widget in (*at.text_input, *at.number_input, *at.selectbox, *at.checkbox):
            self.assertTrue(str(widget.label).strip())
        periyot = at.number_input(key="plan_periyot")
        sure = at.number_input(key="plan_sure")
        self.assertIn("periyot", periyot.help.lower())
        self.assertIn("saniye", sure.help.lower())
        self.assertEqual(periyot.value, 10)
        self.assertEqual(sure.value, 120)
        self.assertIn("-90", at.number_input(key="enkaz_enlem").help)
        self.assertIn("kişi", at.number_input(key="enkaz_talep").help.lower())

    def test_onbellek_ikinci_okumayi_atlar(self):
        at = admin_giris(self.app())
        assert_clean(self, at)
        ilk = at.session_state["memory_db"].select_count
        self.assertGreater(ilk, 0)
        at.number_input(key="plan_periyot").set_value(8).run()
        assert_clean(self, at)
        self.assertEqual(at.session_state["memory_db"].select_count, ilk)

    def test_bos_isim_ve_talep_hata_mesaji(self):
        at = admin_giris(self.app())
        once = len(frame_with(at, "Talep (kişi)"))
        at.button(key="enkaz_ekle").click().run()
        assert_clean(self, at)
        self.assertTrue(any("Enkaz ismi zorunludur." in m for m in alerts(at)))
        self.assertEqual(len(frame_with(at, "Talep (kişi)")), once)
        at.text_input(key="enkaz_isim").set_value("   ")
        at.button(key="enkaz_ekle").click().run()
        self.assertTrue(any("Enkaz ismi zorunludur." in m for m in alerts(at)))
        at.text_input(key="enkaz_isim").set_value("Testköy")
        at.number_input(key="enkaz_talep").set_value(0.0)
        at.button(key="enkaz_ekle").click().run()
        assert_clean(self, at)
        self.assertTrue(any("Talep 0'dan büyük olmalıdır." in m for m in alerts(at)))
        self.assertEqual(len(frame_with(at, "Talep (kişi)")), once)

    def test_enkaz_eklenince_mesaj_kalir(self):
        at = admin_giris(self.app())
        at.text_input(key="enkaz_isim").set_value("Testköy")
        at.button(key="enkaz_ekle").click().run()
        assert_clean(self, at)
        self.assertTrue(any(m == "Enkaz eklendi" for m in alerts(at)))
        self.assertIn("Testköy", set(frame_with(at, "Talep (kişi)")["İsim"]))

    def test_silme_onay_istemeden_silmez(self):
        at = admin_giris(self.app())
        at.button(key="avcilar_sil_iste").click().run()
        assert_clean(self, at)
        self.assertTrue(any("geri alınamaz" in m for m in alerts(at)))
        self.assertTrue(any("İBB-KRDAE" in m for m in alerts(at)))
        isimler = set(frame_with(at, "Talep (kişi)")["İsim"])
        self.assertIn("Kadıköy-Moda", isimler)
        self.assertNotIn("Avcılar-Cihangir", isimler)
        at.button(key="avcilar_sil_vazgec").click().run()
        assert_clean(self, at)
        self.assertFalse(any("geri alınamaz" in m for m in alerts(at)))
        self.assertNotIn("Avcılar-Cihangir", set(frame_with(at, "Talep (kişi)")["İsim"]))
        at.button(key="avcilar_sil_iste").click().run()
        at.button(key="avcilar_sil_onay").click().run()
        assert_clean(self, at)
        self.assertTrue(any("silindi" in m for m in alerts(at)))
        isimler = set(frame_with(at, "Talep (kişi)")["İsim"])
        self.assertIn("Avcılar-Cihangir", isimler)
        self.assertIn("Kadıköy-Moda", isimler)

    def test_ekip_id_ile_secilir_ve_mesaj_kalir(self):
        at = self.app()
        at = at.selectbox(key="rol").set_value("Ekip").run()
        assert_clean(self, at)
        self.assertTrue(any(el.value == "Ekip Paneli" for el in at.header))
        self.assertFalse(any("Devam ediyor" in el.value for el in at.html))
        kutu = at.selectbox(key="ekip_giris_sec")
        self.assertIsInstance(kutu.value, int)
        ak1 = [etiket for etiket in kutu.options if etiket.startswith("AK-1")]
        self.assertGreaterEqual(len(ak1), 2)
        self.assertEqual(len(ak1), len(set(ak1)))
        self.assertTrue(all("#" in etiket for etiket in ak1))
        at.text_input(key="ekip_giris_kod").set_value("ekip-1")
        at = at.button(key="ekip_giris").click().run()
        assert_clean(self, at)
        govde = "\n".join(el.value for el in at.html)
        self.assertTrue(any(el.value == "Görev: Avcılar-Merkez (#1)" for el in at.subheader))
        self.assertIn("(#1)", govde)
        self.assertIn("23.11.2026 06:30", govde)
        self.assertIn("Meşgul", govde)
        self.assertFalse(any(w.key == "ekip_giris_sec" for w in at.selectbox))
        at = at.button(key="cikis").click().run()
        at.selectbox(key="ekip_giris_sec").set_value(2)
        at.text_input(key="ekip_giris_kod").set_value("ekip-2")
        at = at.button(key="ekip_giris").click().run()
        assert_clean(self, at)
        self.assertTrue(any("Henüz görev yok, müsaitsiniz" in m for m in alerts(at)))
        self.assertFalse(any("Devam ediyor" in el.value for el in at.html))
        at = at.button(key="cikis").click().run()
        at.selectbox(key="ekip_giris_sec").set_value(1)
        at.text_input(key="ekip_giris_kod").set_value("ekip-1")
        at = at.button(key="ekip_giris").click().run()
        at.button(key="gorev_bitti").click().run()
        assert_clean(self, at)
        self.assertTrue(any("görevi biter" in m and "çalışmaya devam eder" in m for m in alerts(at)))
        self.assertFalse(any("Görev tamamlandı" in m for m in alerts(at)))
        at.button(key="gorev_bitti_onay").click().run()
        assert_clean(self, at)
        self.assertTrue(any("Görev tamamlandı" in m and "(#1)" in m for m in alerts(at)))
        self.assertTrue(any("Diğer ekipler aynı enkazda devam edebilir." in m for m in alerts(at)))
        self.assertTrue(any("Görev bitti" in m for m in alerts(at)))

    def test_ayni_isimli_enkaza_yardimci_kaynak(self):
        at = admin_giris(self.app())
        kutu = at.selectbox(key="yardimci_enkaz")
        self.assertIsInstance(kutu.value, int)
        etiketler = [etiket for etiket in kutu.options if "Avcılar-Merkez" in etiket]
        self.assertGreaterEqual(len(etiketler), 2)
        self.assertEqual(len(etiketler), len(set(etiketler)))
        kutu.set_value(4)
        at.number_input(key="yardimci_umke").set_value(9)
        at.button(key="yardimci_kaydet").click().run()
        assert_clean(self, at)
        self.assertTrue(any("Yardımcı kaynak atandı" in m and "(#4)" in m for m in alerts(at)))
        yardim = frame_with(at, "UMKE")
        self.assertTrue(any("(#4)" in isim for isim in yardim["Enkaz"]))
        self.assertIn(9, set(yardim["UMKE"]))

    def test_atama_ozeti_rerun_sonrasi_durur(self):
        at = admin_giris(self.app())
        at.number_input(key="plan_periyot").set_value(2)
        at.number_input(key="plan_sure").set_value(12)
        at.button(key="atama_calistir").click().run(timeout=40)
        assert_clean(self, at)

        def sonuc_metinleri(agac):
            return "\n".join(alerts(agac))

        parcalar = (
            "Plan hazır",
            "Süre sınırı içinde uygun",
            "Plan çözülemedi",
            "müsait Arama-Kurtarma",
        )
        metin = sonuc_metinleri(at)
        self.assertTrue(any(parca in metin for parca in parcalar))
        at.run()
        assert_clean(self, at)
        metin_sonra = sonuc_metinleri(at)
        self.assertTrue(any(parca in metin_sonra for parca in parcalar))
        if "Plan hazır" in metin_sonra:
            ozet = frame_with(at, "Ekip")
            self.assertIn("Merkez", ozet.columns)
            self.assertGreater(len(ozet), 0)
            self.assertTrue(ozet["Ekip"].str.contains("#").any() or ozet["Ekip"].str.contains("UMKE").any())
        basliklar = [el.value for el in at.subheader]
        self.assertTrue(
            any(baslik == "Plan sonucu" for baslik in basliklar)
            or any("Plan çözülemedi" in m or "müsait Arama-Kurtarma" in m for m in alerts(at))
        )


if __name__ == "__main__":
    unittest.main()
