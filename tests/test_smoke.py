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


class SmokeTests(unittest.TestCase):
    def app(self):
        return AppTest.from_file(APP, default_timeout=30).run()

    def test_admin_sayfalari(self):
        at = self.app()
        assert_clean(self, at)
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
        senaryo = at.selectbox(key="senaryo")
        self.assertIn("β", senaryo.help)
        self.assertIn("h", senaryo.help)
        self.assertIn("-90", at.number_input(key="enkaz_enlem").help)
        self.assertIn("kişi", at.number_input(key="enkaz_talep").help.lower())

    def test_onbellek_ikinci_okumayi_atlar(self):
        os.environ["DEPREM_CACHE_PROBE"] = "1"
        try:
            at = self.app()
        finally:
            os.environ.pop("DEPREM_CACHE_PROBE", None)
        assert_clean(self, at)
        self.assertEqual(at.session_state["onbellek_kanit"], (2, 0))

    def test_bos_isim_ve_talep_hata_mesaji(self):
        at = self.app()
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
        at = self.app()
        at.text_input(key="enkaz_isim").set_value("Testköy")
        at.button(key="enkaz_ekle").click().run()
        assert_clean(self, at)
        self.assertTrue(any(m == "Enkaz eklendi" for m in alerts(at)))
        self.assertIn("Testköy", set(frame_with(at, "Talep (kişi)")["İsim"]))

    def test_silme_onay_istemeden_silmez(self):
        at = self.app()
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
        at.selectbox(key="rol").set_value("Ekip").run()
        assert_clean(self, at)
        self.assertTrue(any(el.value == "Ekip Paneli" for el in at.header))
        kutu = at.selectbox(key="ekip_sec")
        self.assertIsInstance(kutu.value, int)
        ak1 = [etiket for etiket in kutu.options if etiket.startswith("AK-1")]
        self.assertGreaterEqual(len(ak1), 2)
        self.assertEqual(len(ak1), len(set(ak1)))
        self.assertTrue(all("#" in etiket for etiket in ak1))
        self.assertTrue(any("Aktif görev" in m and "(#1)" in m for m in alerts(at)))
        kutu.set_value(2).run()
        assert_clean(self, at)
        self.assertTrue(any("aktif görevin yok" in m for m in alerts(at)))
        self.assertFalse(any("Aktif görev" in m for m in alerts(at)))
        at.selectbox(key="ekip_sec").set_value(1).run()
        at.button(key="gorev_bitti").click().run()
        assert_clean(self, at)
        self.assertTrue(any("Görev tamamlandı" in m and "(#1)" in m for m in alerts(at)))
        self.assertTrue(any("Diğer ekipler aynı enkazda devam edebilir." in m for m in alerts(at)))
        self.assertTrue(any("aktif görevin yok" in m for m in alerts(at)))

    def test_ayni_isimli_enkaza_yardimci_kaynak(self):
        at = self.app()
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
        at = self.app()
        at.button(key="atama_calistir").click().run(timeout=60)
        assert_clean(self, at)
        def sonuc_metinleri(agac):
            metin = "\n".join(alerts(agac))
            return metin

        metin = sonuc_metinleri(at)
        self.assertTrue(
            any(parca in metin for parca in ("ekip atandı", "yollar kapalı", "Model çözülemedi", "müsait Arama-Kurtarma"))
        )
        at.run()
        assert_clean(self, at)
        metin_sonra = sonuc_metinleri(at)
        self.assertTrue(
            any(
                parca in metin_sonra
                for parca in ("ekip atandı", "yollar kapalı", "Model çözülemedi", "müsait Arama-Kurtarma")
            )
        )
        if "ekip atandı" in metin_sonra and not metin_sonra.strip().startswith("0 ekip"):
            ozet = frame_with(at, "Etkin kapasite (kişi)")
            self.assertIn("Ekip", ozet.columns)
            self.assertIn("Enkaz", ozet.columns)
            self.assertGreater(len(ozet), 0)
            self.assertTrue(ozet["Ekip"].str.contains("#").all())
            self.assertTrue(ozet["Enkaz"].str.contains("#").all())


if __name__ == "__main__":
    unittest.main()
