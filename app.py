"""Marmara deprem kaynak atama karar destek arayüzü.

Supabase kimlik bilgisi varsa o istemci kullanılır. Anahtar yokken bellek içi
deneme yalnızca DEPREM_DEMO=1 ile açılır. Admin ADMIN_PASSWORD ister; ekip
kendi erişim koduyla girer.
"""

import copy
import hashlib
import html
import hmac
import math
import os
import random
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from supabase import create_client

from model.legacy_assignment import solve_team_to_site
from model.planning_inputs import build_live_instance, plan_view
from model.problem import solve_first_stage
from model.routing import CHAIN_CAPTION, chain_rows, solve_team_chains

READ_CACHE_TTL_SECONDS = 20
TALEP_UST_SINIR = 1_000_000
KAPASITE_UST_SINIR = 100_000
KOD_UST_SINIR = 80
DEMO_ADMIN_PAROLA = "demo"
GIRIS_GECIKME_SANIYE = 0.25
GIRIS_GECIKME_TAVAN = 1.5
ADMIN_PAROLA_YOK = (
    "Yönetici girişi kapalı: ADMIN_PASSWORD tanımlı değil. "
    ".streamlit/secrets.toml dosyasına ADMIN_PASSWORD = \"...\" yazın "
    "veya ortam değişkeni ADMIN_PASSWORD ayarlayın. Örnek: secrets.toml.example. "
    "Parola tanımlanmadan Admin paneli açılmaz."
)
EKIP_GIRIS_MESAJ = {
    "tanimli_degil": (
        "Bu ekip için erişim kodu tanımlı değil. Yönetici ekip eklerken kod yazmalıdır."
    ),
    "bos": "Erişim kodu zorunludur.",
    "hatali": "Erişim kodu hatalı.",
    "yok": "Ekip kaydı bulunamadı.",
}
AVCILAR_MAHALLELER = [
    "Cihangir",
    "Yeşilkent",
    "Üniversite",
    "Tahtakale",
    "Gümüşpala",
    "Firuzköy",
    "Denizköşkler",
    "Merkez",
    "Ambarlı",
    "Mustafa Kemal",
]
AVCILAR_BILGI = (
    "Kaynak ve normalizasyon. Orijinal veri (İBB-KRDAE 2020): "
    "nüfus ~448.000, bina 26.762, orta ve üzeri hasar ~7.039 bina (%27), "
    "geçici barınma 34.941 hane (~105.000 kişi). "
    "Küçük ölçekli model için bu toplam 10 mahalle noktasına bölünür. "
    "Koordinatlar Avcılar merkezi (40,98° K, 28,72° D) çevresinde ±0,05° üretilir. "
    "Nokta talebi yaklaşık 600–1400 kişidir. "
    "«Avcılar Temizle ve Üret» ismi Avcılar- ile başlayan kayıtları siler ve yeniden üretir; "
    "silme için ayrıca onay istenir."
)
DURUM_ETIKET = {
    "aktif": "Aktif",
    "tamam": "Tamam",
    "musait": "Müsait",
    "meşgul": "Meşgul",
    "devam": "Devam ediyor",
    "bitti": "Bitti",
}
ATAMA_SELECT = "*, ekipler(isim), enkazlar(isim)"
GOREV_SELECT = (
    "id, ekip_id, enkaz_id, baslangic, durum, "
    "enkazlar(isim, talep, enlem, boylam, makine_gerekli)"
)
EKIP_GOREV_YOK = "Henüz görev yok, müsaitsiniz"
EKIP_BAGLANTI = "Bağlantı kurulamadı. Görev bilgisi alınamadı."
EKIP_TELEFON_CSS = """
<style>
/* Streamlit düğmesi ~38px. Eldiven için en az 44px; burada 48px.
   Yalnızca ekip akışı. Kenar çubuğu kullanılmaz.
   Varsayılan birincil kırmızı, beyaz yazı açık havada zayıf: zemin #111.
   stMain: section.main bu sürümde yok. */
[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stExpandSidebarButton"],
[data-testid="stHeader"],
[data-testid="stHeaderActionElements"] {
  display: none !important;
}
[data-testid="stMain"] [data-testid="stBaseButton-primary"],
[data-testid="stMain"] [data-testid="stBaseButton-secondary"],
[data-testid="stMain"] [data-testid="stBaseLinkButton-secondary"],
[data-testid="stMain"] [data-testid="stFormSubmitButton"] button,
[data-testid="stMain"] button[aria-label^="Help for"] {
  min-height: 48px !important;
  min-width: 48px !important;
  font-size: 1.0625rem;
}
[data-testid="stMain"] [data-testid="stBaseButton-primary"] {
  background-color: #111111 !important;
  color: #ffffff !important;
  border: 2px solid #111111 !important;
}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"],
[data-testid="stMain"] [data-testid="stBaseLinkButton-secondary"] {
  background-color: #ffffff !important;
  color: #111111 !important;
  border: 2px solid #111111 !important;
}
[data-testid="stMain"] input[role="combobox"],
[data-testid="stMain"] [data-testid="stTextInput"] input,
[data-testid="stMain"] button[aria-label="Open"],
[data-testid="stMain"] button[aria-label="Show password"],
[data-testid="stMain"] button[aria-label="Hide password"] {
  min-height: 48px !important;
  min-width: 48px !important;
  font-size: 1.0625rem;
}
[data-testid="stMain"] [data-testid="stAlert"] {
  font-size: 1.125rem;
  overflow-wrap: anywhere;
}
.ekip-gorev {
  font-size: 1.25rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.ekip-gorev p {
  margin: 0 0 0.65rem 0;
}
.ekip-kimlik {
  font-size: 1rem;
  line-height: 1.3;
  margin: 0 0 0.15rem 0;
}
/* Streamlit sütunu dar ekranda min-width:%100 ile alta kayıyor.
   Çıkış ve Rol aynı satırda kalsın. */
[data-testid="stMain"] [data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap !important;
}
[data-testid="stMain"] [data-testid="stColumn"] {
  min-width: 0 !important;
}
/* İki harita bağlantısı aynı kural: yükseklik ve kalınlık eşit, 390px'te yan yana. */
.ekip-harita {
  display: flex;
  gap: 0.5rem;
  margin: 0.25rem 0 0.75rem 0;
}
.ekip-harita a {
  flex: 1 1 0;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  min-height: 48px;
  min-width: 0;
  padding: 0.45rem 0.4rem;
  border: 2px solid #111111;
  background: #ffffff;
  color: #111111;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.2;
  text-align: center;
  text-decoration: none;
}
</style>
"""
_DBS = {}
_CONFIRM_AVCILAR = "confirm_avcilar_sil"


def etiket_durum(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return DURUM_ETIKET.get(str(value), str(value))


def evet_hayir(value):
    try:
        return "Evet" if int(value) == 1 else "Hayır"
    except (TypeError, ValueError):
        return "Hayır"


def format_dt(value):
    if value is None or value == "":
        return "—"
    text = str(value).strip()
    if not text or text.lower() == "none":
        return "—"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.strftime("%d.%m.%Y %H:%M")


def enkaz_hatalari(isim, enlem, boylam, talep):
    hatalar = []
    temiz = "" if isim is None else str(isim).strip()
    if not temiz:
        hatalar.append("Enkaz ismi zorunludur.")
    elif len(temiz) > 120:
        hatalar.append("Enkaz ismi en fazla 120 karakter olabilir.")
    try:
        enlem_f = float(enlem)
        boylam_f = float(boylam)
        talep_f = float(talep)
    except (TypeError, ValueError):
        hatalar.append("Enlem, boylam ve talep sayı olmalıdır.")
        return hatalar
    if not -90 <= enlem_f <= 90:
        hatalar.append("Enlem -90 ile 90 arasında olmalıdır.")
    if not -180 <= boylam_f <= 180:
        hatalar.append("Boylam -180 ile 180 arasında olmalıdır.")
    if talep_f <= 0:
        hatalar.append("Talep 0'dan büyük olmalıdır.")
    elif talep_f > TALEP_UST_SINIR:
        hatalar.append("Talep 1.000.000 kişiyi aşamaz.")
    return hatalar


def ekip_hatalari(isim, kapasite, erisim_kodu=""):
    hatalar = []
    temiz = "" if isim is None else str(isim).strip()
    if not temiz:
        hatalar.append("Ekip ismi zorunludur.")
    elif len(temiz) > 120:
        hatalar.append("Ekip ismi en fazla 120 karakter olabilir.")
    try:
        kapasite_f = float(kapasite)
    except (TypeError, ValueError):
        hatalar.append("Kapasite sayı olmalıdır.")
        return hatalar
    if kapasite_f <= 0:
        hatalar.append("Kapasite 0'dan büyük olmalıdır.")
    elif kapasite_f > KAPASITE_UST_SINIR:
        hatalar.append("Kapasite 100.000 kişiyi aşamaz.")
    kod = "" if erisim_kodu is None else str(erisim_kodu).strip()
    if len(kod) > KOD_UST_SINIR:
        hatalar.append("Erişim kodu en fazla 80 karakter olabilir.")
    return hatalar


def yonetici_parolasi(secret, env, demo):
    """(parola, deneme_varsayilani).

    secret, sonra ortam. İkisi de boşsa ve demo değilse parola yoktur;
    Admin paneli açılmaz. İkisi de boşsa ve demo ise belgelenmiş deneme parolası geçerlidir.
    """
    for raw in (secret, env):
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text, False
    if demo:
        return DEMO_ADMIN_PAROLA, True
    return None, False


def parola_eslesir(girilen, beklenen):
    """Sabit süreli karşılaştırma. Boş değer eşleşmez."""
    if girilen is None or beklenen is None:
        return False
    girilen_s = str(girilen).strip()
    beklenen_s = str(beklenen).strip()
    if not girilen_s or not beklenen_s:
        return False
    return hmac.compare_digest(
        hashlib.sha256(girilen_s.encode("utf-8")).digest(),
        hashlib.sha256(beklenen_s.encode("utf-8")).digest(),
    )


def ekip_kodu_sonucu(ekip, girilen):
    """'tamam', 'bos', 'hatali', 'tanimli_degil' veya 'yok'."""
    if not ekip:
        return "yok"
    kayitli = ekip.get("erisim_kodu")
    if kayitli is None or str(kayitli).strip() == "":
        return "tanimli_degil"
    if girilen is None or str(girilen).strip() == "":
        return "bos"
    if parola_eslesir(girilen, kayitli):
        return "tamam"
    return "hatali"


def atama_ekibe_ait(atama, ekip_id):
    try:
        return int(atama.get("ekip_id")) == int(ekip_id)
    except (AttributeError, TypeError, ValueError):
        return False


def gorevi_bitir(db, oturum_ekip_id, atama_id, simdi=None):
    """Yalnızca oturumdaki ekibin devam eden görevini kapatır. Değilse None."""
    try:
        oturum_id = int(oturum_ekip_id)
        atama_int = int(atama_id)
    except (TypeError, ValueError):
        return None
    rows = run_select(
        db,
        "atamalar",
        "*",
        (("eq", "id", atama_int), ("eq", "durum", "devam")),
    )
    if len(rows) != 1 or not atama_ekibe_ait(rows[0], oturum_id):
        return None
    bit = simdi or datetime.now().isoformat()
    db.table("atamalar").update({"durum": "bitti", "bitis": bit}).eq("id", atama_int).eq(
        "ekip_id", oturum_id
    ).execute()
    db.table("ekipler").update({"durum": "musait"}).eq("id", oturum_id).execute()
    return bit


def talep_metni(value):
    if value is None or value == "":
        return "—"
    try:
        sayi = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(sayi):
        return "—"
    return f"{sayi:.1f} kişi"


def gecen_sure(baslangic, simdi=None):
    """Başlangıçtan beri geçen süre. Okunamıyorsa veya gelecekteyse —."""
    if baslangic is None:
        return "—"
    text = str(baslangic).strip()
    if not text or text.lower() == "none":
        return "—"
    try:
        start = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    now = simdi or datetime.now(start.tzinfo)
    if start.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=start.tzinfo)
    elif start.tzinfo is None and now.tzinfo is not None:
        start = start.replace(tzinfo=now.tzinfo)
    saniye = (now - start).total_seconds()
    if saniye < 0:
        return "—"
    dakika = int(saniye // 60)
    gun, dakika = divmod(dakika, 24 * 60)
    saat, dakika = divmod(dakika, 60)
    parcalar = []
    if gun:
        parcalar.append(f"{gun} gün")
    if saat:
        parcalar.append(f"{saat} saat")
    if dakika or not parcalar:
        parcalar.append(f"{dakika} dakika")
    return " ".join(parcalar)


def harita_baglari(enlem, boylam):
    """(Google Maps https, geo URI). Koordinat yoksa (None, None)."""
    try:
        lat = float(enlem)
        lon = float(boylam)
    except (TypeError, ValueError):
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return (
        f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}",
        f"geo:{lat:.6f},{lon:.6f}",
    )


def konum_metni(enlem, boylam):
    google, _geo = harita_baglari(enlem, boylam)
    if google is None:
        return "Konum yok"
    lat = float(enlem)
    lon = float(boylam)
    ns = "K" if lat >= 0 else "G"
    ew = "D" if lon >= 0 else "B"
    return f"{abs(lat):.5f}° {ns}, {abs(lon):.5f}° {ew}"


def _adet(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def son_yardimci(rows):
    """Aynı enkaz için birden fazla satır varsa en son id."""
    if not rows:
        return None

    def _sira(row):
        try:
            return int(row.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    return max(rows, key=_sira)


def yardimci_metni(rows):
    yardim = son_yardimci(rows)
    if yardim is None:
        return "Atanmadı"
    return f"UMKE {_adet(yardim.get('umke_sayisi'))}, iş makinesi {_adet(yardim.get('makine_sayisi'))}"


def gorev_basligi(atama):
    """Enkaz adı başlıktır. Kayıt numarası aynı isimli sahaları ayırır."""
    enkaz = atama.get("enkazlar") if isinstance(atama.get("enkazlar"), dict) else {}
    ad = enkaz.get("isim") or "—"
    try:
        return f"Görev: {ad} (#{int(atama.get('enkaz_id'))})"
    except (TypeError, ValueError):
        return f"Görev: {ad}"


def gorev_satirlari(_ekip, atama, yardimci_rows, simdi=None):
    """Görev kartının ayrıntı satırları ve harita adresleri. Ekip kimliği ayrı satırdadır."""
    enkaz = atama.get("enkazlar") if isinstance(atama.get("enkazlar"), dict) else {}
    google, geo = harita_baglari(enkaz.get("enlem"), enkaz.get("boylam"))
    satirlar = [
        ("Talep", talep_metni(enkaz.get("talep"))),
        ("İş makinesi gerekli", evet_hayir(enkaz.get("makine_gerekli"))),
        ("Yardımcı kaynak", yardimci_metni(yardimci_rows)),
        ("Başlangıç", format_dt(atama.get("baslangic"))),
        ("Geçen süre", gecen_sure(atama.get("baslangic"), simdi)),
        ("Konum", konum_metni(enkaz.get("enlem"), enkaz.get("boylam"))),
    ]
    return satirlar, google, geo


def gorev_html(satirlar):
    parcalar = [
        '<div class="ekip-gorev" role="status" '
        'style="font-size:1.25rem;line-height:1.45;overflow-wrap:anywhere">'
    ]
    for etiket, deger in satirlar:
        parcalar.append(
            '<p style="margin:0 0 0.65rem 0"><strong>'
            + html.escape(str(etiket))
            + ":</strong> "
            + html.escape(str(deger))
            + "</p>"
        )
    parcalar.append("</div>")
    return "".join(parcalar)


def ekip_onay_metni(enkaz_adi):
    """Yalnızca bu ekibin ataması kapanır. Enkaz ve diğer ekipler durmaz."""
    ad = enkaz_adi or "—"
    return (
        f"Bu ekibin {ad} görevi biter ve ekip müsait olur. "
        "Aynı enkazdaki diğer ekipler çalışmaya devam eder."
    )


def ekip_bitti_metni(ekip_adi, ekip_id, enkaz_adi, bas_txt, bit_txt):
    return (
        f"Görev bitti. Görev tamamlandı: {ekip_adi} (#{ekip_id}) → {enkaz_adi}. "
        f"Başlangıç {bas_txt}, bitiş {bit_txt}. "
        "Diğer ekipler aynı enkazda devam edebilir."
    )


def ekip_gorev_kaydi(fetch, ekip_id):
    """Ekip satırı, devam eden görev, varsa o enkazın yardımcı kaynağı.

    Görev yoksa yardımcı kaynak okunmaz.
    """
    ekip_no = int(ekip_id)
    bulunan = fetch("ekipler", "id, isim, durum", (("eq", "id", ekip_no),))
    atamalar = [
        row
        for row in fetch(
            "atamalar",
            GOREV_SELECT,
            (("eq", "ekip_id", ekip_no), ("eq", "durum", "devam")),
        )
        if atama_ekibe_ait(row, ekip_no)
    ]
    gorev = atamalar[0] if atamalar else None
    yardimci = []
    if gorev is not None:
        try:
            enkaz_no = int(gorev.get("enkaz_id"))
        except (TypeError, ValueError):
            enkaz_no = None
        if enkaz_no is not None:
            yardimci = fetch(
                "yardimci_kaynaklar",
                "id, umke_sayisi, makine_sayisi",
                (("eq", "enkaz_id", enkaz_no),),
            )
    return bulunan, gorev, yardimci


def modelsiz_ekip(rows):
    """Erişim kodunu optimizasyon girdisine koyma."""
    temiz = []
    for row in rows:
        item = dict(row)
        item.pop("erisim_kodu", None)
        temiz.append(item)
    return temiz


def demo_ekip_kod_notu(ekipler):
    satirlar = []
    for row in ekipler:
        kod = "" if row.get("erisim_kodu") is None else str(row.get("erisim_kodu")).strip()
        if not kod:
            continue
        satirlar.append(f"{row.get('isim', '—')} (#{int(row['id'])}): {kod}")
    if not satirlar:
        return None
    return "Deneme ekip kodları: " + ", ".join(satirlar) + "."


def secret_degeri(name):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return None


def kayit_basarisiz_giris():
    adet = int(st.session_state.get("giris_hata", 0)) + 1
    st.session_state["giris_hata"] = adet
    time.sleep(min(GIRIS_GECIKME_SANIYE * adet, GIRIS_GECIKME_TAVAN))


def _admin_giris(parola, deneme_varsayilani):
    st.subheader("Yönetici girişi")
    if parola is None:
        st.error(ADMIN_PAROLA_YOK)
        return
    if deneme_varsayilani:
        st.info(
            f"Deneme modu. Yönetici parolası: {DEMO_ADMIN_PAROLA}. "
            "Kalıcı kurulumda bu parola geçersizdir; .streamlit/secrets.toml dosyasına "
            "ADMIN_PASSWORD yazın veya aynı adlı ortam değişkenini ayarlayın."
        )
    with st.form("admin_giris_form"):
        girilen = st.text_input(
            "Yönetici parolası",
            key="admin_parola",
            type="password",
            autocomplete="current-password",
            help="ADMIN_PASSWORD değeri. Deneme modunda parola tanımlı değilse formun üstünde yazılır.",
        )
        if st.form_submit_button("Giriş", key="admin_giris"):
            if girilen is None or not str(girilen).strip():
                st.error("Parola zorunludur.")
            elif parola_eslesir(girilen, parola):
                st.session_state["auth"] = {"rol": "Admin"}
                st.session_state["giris_hata"] = 0
                st.rerun()
            else:
                kayit_basarisiz_giris()
                st.error("Parola hatalı.")


def _ekip_giris(ekipler, demo):
    st.header("Ekip Paneli")
    st.subheader("Ekip girişi")
    if not ekipler:
        st.warning("Henüz ekip yok.")
        return
    if demo:
        notu = demo_ekip_kod_notu(ekipler)
        if notu:
            st.info(notu)
    with st.form("ekip_giris_form"):
        ekip_id, by_id = select_kayit(
            "Ekip",
            ekipler,
            key="ekip_giris_sec",
            help_text="Kayıt numarası (#) kimliktir. Aynı isimli ekiplerden kodu girilen kayıt açılır.",
        )
        kod = st.text_input(
            "Erişim kodu",
            key="ekip_giris_kod",
            type="password",
            autocomplete="off",
            help="Yöneticinin bu ekibe verdiği kod. Başka ekibin kodu bu kaydı açmaz.",
        )
        if st.form_submit_button(
            "Giriş",
            key="ekip_giris",
            type="primary",
            width="stretch",
        ):
            sonuc = ekip_kodu_sonucu(by_id.get(int(ekip_id)), kod)
            if sonuc == "tamam":
                st.session_state["auth"] = {"rol": "Ekip", "ekip_id": int(ekip_id)}
                st.session_state["giris_hata"] = 0
                st.rerun()
            if sonuc == "hatali":
                kayit_basarisiz_giris()
            st.error(EKIP_GIRIS_MESAJ[sonuc])


def kayit_etiketi(row):
    durum = etiket_durum(row.get("durum"))
    ek = f" · {durum}" if durum else ""
    return f"{row.get('isim', '—')} (#{int(row['id'])}){ek}"


class SupabaseHandle:
    is_memory = False
    scope_id = "prod"

    def __init__(self, client):
        self._client = client

    def table(self, name):
        return self._client.table(name)


def demo_isteniyor():
    return os.environ.get("DEPREM_DEMO", "").strip() == "1"


def read_credentials():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except (KeyError, FileNotFoundError):
        return None
    url = "" if url is None else str(url).strip()
    key = "" if key is None else str(key).strip()
    if not url or not key:
        return None
    return url, key


def run_select(db, table, columns, filters):
    query = db.table(table).select(columns)
    for op, column, value in filters:
        if op == "eq":
            query = query.eq(column, value)
        elif op == "like":
            query = query.like(column, value)
        else:
            raise ValueError(f"Bilinmeyen filtre: {op}")
    result = query.execute()
    return copy.deepcopy(result.data or [])


def flash(level, message):
    flashes = list(st.session_state.get("flashes", []))
    flashes.append((level, message))
    st.session_state["flashes"] = flashes


def render_flashes():
    for level, message in st.session_state.pop("flashes", []):
        {"success": st.success, "warning": st.warning, "error": st.error, "info": st.info}[level](message)


def _hatalari_goster(hatalar):
    for mesaj in hatalar:
        st.error(mesaj)


def _avcilar_satirlari(ustune):
    rows = []
    for mahalle in AVCILAR_MAHALLELER:
        if ustune:
            isim = f"Avcılar-{mahalle}-{random.randint(10, 99)}"
        else:
            isim = f"Avcılar-{mahalle}"
        rows.append(
            {
                "isim": isim,
                "enlem": 40.98 + random.uniform(-0.05, 0.05),
                "boylam": 28.72 + random.uniform(-0.05, 0.05),
                "talep": random.uniform(600, 1400),
                "makine_gerekli": 1 if random.random() < 0.35 else 0,
                "durum": "aktif",
            }
        )
    return rows


def show_enkaz_tablosu(rows):
    if not rows:
        st.info("Kayıtlı enkaz yok.")
        return
    frame = pd.DataFrame(rows)
    view = pd.DataFrame(
        {
            "İsim": frame["isim"],
            "Enlem": pd.to_numeric(frame["enlem"], errors="coerce"),
            "Boylam": pd.to_numeric(frame["boylam"], errors="coerce"),
            "Talep (kişi)": pd.to_numeric(frame["talep"], errors="coerce"),
            "İş makinesi": frame["makine_gerekli"].map(evet_hayir),
            "Durum": frame["durum"].map(etiket_durum),
        }
    )
    st.dataframe(
        view,
        hide_index=True,
        column_config={
            "İsim": st.column_config.TextColumn("İsim"),
            "Enlem": st.column_config.NumberColumn("Enlem", format="%.5f"),
            "Boylam": st.column_config.NumberColumn("Boylam", format="%.5f"),
            "Talep (kişi)": st.column_config.NumberColumn("Talep (kişi)", format="%.1f"),
            "İş makinesi": st.column_config.TextColumn("İş makinesi"),
            "Durum": st.column_config.TextColumn("Durum"),
        },
    )


def show_enkaz_haritasi(rows):
    noktalar = []
    for row in rows:
        try:
            lat = float(row["enlem"])
            lon = float(row["boylam"])
        except (TypeError, ValueError, KeyError):
            continue
        if math.isfinite(lat) and math.isfinite(lon):
            noktalar.append((row, lat, lon))
    if not noktalar:
        st.caption("Koordinatı olan enkaz yok.")
        return
    durumlar = [str(row.get("durum")) for row, _, _ in noktalar]
    aktif = sum(durum == "aktif" for durum in durumlar)
    tamam = sum(durum == "tamam" for durum in durumlar)
    diger = len(durumlar) - aktif - tamam
    parcalar = [f"{aktif} aktif (büyük nokta)", f"{tamam} tamam (küçük nokta)"]
    if diger:
        parcalar.append(f"{diger} diğer (küçük nokta)")
    st.caption("Harita: " + ", ".join(parcalar) + ". Durum tabloda da yazılır; renk tek başına kullanılmaz.")
    plot = pd.DataFrame(
        {
            "lat": [lat for _, lat, _ in noktalar],
            "lon": [lon for _, _, lon in noktalar],
            "boyut": [2000 if durum == "aktif" else 450 for durum in durumlar],
            "renk": ["#1d4e89" if durum == "aktif" else "#6b7280" for durum in durumlar],
        }
    )
    st.map(
        plot,
        latitude="lat",
        longitude="lon",
        color="renk",
        size="boyut",
        height=420,
        alt=(
            f"Enkaz haritası. {aktif} aktif site büyük nokta, "
            f"{tamam} tamamlanmış site küçük nokta. İsim ve durum tabloda yazılıdır."
        ),
    )


def kod_metni(value):
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or "—"


def show_ekip_tablosu(rows):
    if not rows:
        st.info("Kayıtlı ekip yok.")
        return
    frame = pd.DataFrame(rows)
    if "erisim_kodu" in frame.columns:
        kodlar = frame["erisim_kodu"].map(kod_metni)
    else:
        kodlar = ["—"] * len(frame)
    view = pd.DataFrame(
        {
            "İsim": frame["isim"],
            "Tip": frame["tip"],
            "Kapasite (kişi)": pd.to_numeric(frame["kapasite"], errors="coerce"),
            "Durum": frame["durum"].map(etiket_durum),
            "Erişim kodu": kodlar,
        }
    )
    st.dataframe(
        view,
        hide_index=True,
        column_config={
            "İsim": st.column_config.TextColumn("İsim"),
            "Tip": st.column_config.TextColumn("Tip"),
            "Kapasite (kişi)": st.column_config.NumberColumn("Kapasite (kişi)", format="%.1f"),
            "Durum": st.column_config.TextColumn("Durum"),
            "Erişim kodu": st.column_config.TextColumn(
                "Erişim kodu",
                help="Ekip bu kodla panele girer. Yalnızca yönetici oturumunda görünür.",
            ),
        },
    )


def show_atama_tablosu(rows, bos_mesaj):
    if not rows:
        st.info(bos_mesaj)
        return
    view = pd.DataFrame(
        [
            {
                "Ekip": (row.get("ekipler") or {}).get("isim") or "—",
                "Enkaz": (row.get("enkazlar") or {}).get("isim") or "—",
                "Başlangıç": format_dt(row.get("baslangic")),
                "Bitiş": format_dt(row.get("bitis")),
                "Durum": etiket_durum(row.get("durum")),
            }
            for row in rows
        ]
    )
    st.dataframe(
        view,
        hide_index=True,
        column_config={
            "Ekip": st.column_config.TextColumn("Ekip"),
            "Enkaz": st.column_config.TextColumn("Enkaz"),
            "Başlangıç": st.column_config.TextColumn("Başlangıç"),
            "Bitiş": st.column_config.TextColumn("Bitiş"),
            "Durum": st.column_config.TextColumn("Durum"),
        },
    )


def show_yardimci_tablosu(rows, enkaz_rows):
    if not rows:
        st.caption("Henüz yardımcı kaynak kaydı yok.")
        return
    isimler = {int(row["id"]): row.get("isim") or "—" for row in enkaz_rows}
    view = pd.DataFrame(
        [
            {
                "Enkaz": f"{isimler.get(int(row['enkaz_id']), '—')} (#{int(row['enkaz_id'])})",
                "UMKE": int(row.get("umke_sayisi") or 0),
                "İş makinesi": int(row.get("makine_sayisi") or 0),
            }
            for row in rows
        ]
    )
    st.dataframe(
        view,
        hide_index=True,
        column_config={
            "Enkaz": st.column_config.TextColumn("Enkaz"),
            "UMKE": st.column_config.NumberColumn("UMKE", format="%d"),
            "İş makinesi": st.column_config.NumberColumn("İş makinesi", format="%d"),
        },
    )


def select_kayit(label, rows, key, help_text):
    by_id = {}
    ids = []
    for row in rows:
        kayit_id = int(row["id"])
        ids.append(kayit_id)
        by_id[kayit_id] = row

    def _fmt(kayit_id, by_id=by_id):
        return kayit_etiketi(by_id[int(kayit_id)])

    return st.selectbox(label, options=ids, format_func=_fmt, key=key, help=help_text), by_id


def render_son_atama():
    son = st.session_state.get("son_atama")
    if not son:
        return
    {"success": st.success, "warning": st.warning, "error": st.error, "info": st.info}[son["level"]](son["mesaj"])
    if son.get("satirlar"):
        st.dataframe(
            pd.DataFrame(son["satirlar"]),
            hide_index=True,
            column_config={
                "Ekip": st.column_config.TextColumn("Ekip"),
                "Enkaz": st.column_config.TextColumn("Enkaz"),
                "Etkin kapasite (kişi)": st.column_config.NumberColumn(
                    "Etkin kapasite (kişi)",
                    format="%.1f",
                    help="Kapasite / (1+β)",
                ),
            },
        )
    if son.get("kapali"):
        st.caption("Kapalı yol nedeniyle atama yapılmayan enkazlar: " + ", ".join(son["kapali"]))


def _zinciri_kaydet(plan_instance):
    try:
        chain_solution = solve_team_chains(plan_instance, time_limit=20)
    except Exception as exc:
        st.session_state["chain_error"] = str(exc)
        st.session_state.pop("chain_view", None)
        return
    if chain_solution.status != "Optimal":
        st.session_state["chain_error"] = f"Zincir çözümü {chain_solution.status}"
        st.session_state.pop("chain_view", None)
        return
    st.session_state["chain_view"] = {
        "objective": chain_solution.objective,
        "caption": CHAIN_CAPTION,
        "rows": chain_rows(plan_instance, chain_solution),
    }
    st.session_state.pop("chain_error", None)


def render_birinci_asama():
    if st.session_state.get("plan_error"):
        st.warning(f"Birinci aşama planı kurulamadı: {st.session_state['plan_error']}")
    view = st.session_state.get("plan_view")
    if not view:
        return
    st.subheader("Birinci aşama planı (G, V, V^U, V^W)")
    st.caption(view["caption"])
    col_obj, col_open, col_teams = st.columns(3)
    col_obj.metric("Beklenen karşılanmayan talep", f"{view['objective']:.1f}")
    col_open.metric("Açık merkez", view["open_count"])
    col_teams.metric("Ön konumlanan ekip", view["team_count"])
    frame = pd.DataFrame(view["rows"])
    if "Açık" in frame.columns:
        frame["Açık"] = frame["Açık"].map(
            lambda value: {"evet": "Evet", "hayır": "Hayır"}.get(str(value).lower(), value)
        )
    config = {
        "Merkez": st.column_config.TextColumn("Merkez"),
        "Açık": st.column_config.TextColumn("Açık"),
        "UMKE": st.column_config.NumberColumn("UMKE", format="%d"),
        "İş makinesi": st.column_config.NumberColumn("İş makinesi", format="%d"),
    }
    for column in frame.columns:
        if column not in config and pd.api.types.is_numeric_dtype(frame[column]):
            config[column] = st.column_config.NumberColumn(column, format="%d")
    st.dataframe(frame, hide_index=True, column_config=config)
    if view["opened_names"]:
        st.success("Açılan merkezler: " + ", ".join(view["opened_names"]))
    else:
        st.info("Plan hiçbir merkezi açmadı.")
    if st.session_state.get("chain_error"):
        st.warning(f"Ekip zinciri kurulamadı: {st.session_state['chain_error']}")
    chain_view = st.session_state.get("chain_view")
    if chain_view:
        st.subheader("Ekip zincirleri (Y)")
        st.caption(chain_view["caption"])
        st.metric("Zincir modeli amaç", f"{chain_view['objective']:.1f}")
        st.dataframe(pd.DataFrame(chain_view["rows"]), hide_index=True)


def _rol_secimi():
    return st.selectbox(
        "Rol",
        ["Admin", "Ekip"],
        key="rol",
        help="Admin parola ister. Ekip, kendi kaydını ve erişim kodunu girer; yalnızca kendi görevini görür.",
    )


def _cikis_dugmesi(genis=False):
    auth = st.session_state.get("auth")
    if isinstance(auth, dict) and st.button(
        "Çıkış",
        key="cikis",
        width="stretch" if genis else "content",
        help="Oturumu kapatır. Panele dönmek için parola veya ekip kodu gerekir.",
    ):
        st.session_state.pop("auth", None)
        st.session_state.pop("ekip_onay_id", None)
        st.session_state.pop("gorev_sonuc", None)
        st.rerun()


def _ekip_ust_satir():
    """Rol ve çıkış üstte. Asıl eylem ekranın sonunda kalır."""
    if isinstance(st.session_state.get("auth"), dict):
        sol, sag = st.columns([1, 2], vertical_alignment="bottom")
        with sol:
            _cikis_dugmesi(genis=True)
        with sag:
            _rol_secimi()
    else:
        _rol_secimi()


def _ekip_telefon_css():
    st.html(EKIP_TELEFON_CSS)


def _ekip_baglanti_goster(refresh):
    st.error(EKIP_BAGLANTI)
    if st.button("Yeniden dene", key="ekip_yeniden", width="stretch", wrap=True):
        refresh()
        st.rerun()


def _ekip_harita(google, geo):
    if not google:
        return
    # İkisi de düz bağlantı ve aynı sınıf. https yeni sekmede açılır;
    # geo: harita uygulamasına gider, target kullanmaz.
    st.html(
        '<div class="ekip-harita">'
        '<a href="'
        + html.escape(google, quote=True)
        + '" target="_blank" rel="noopener noreferrer">Google Haritalar</a>'
        '<a href="'
        + html.escape(geo, quote=True)
        + '">Harita uygulaması</a>'
        "</div>"
    )


def _kimlik_satiri(ekip):
    st.html('<p class="ekip-kimlik">' + html.escape(kayit_etiketi(ekip)) + "</p>")


def _ekip_aktif(db, refresh, ekip_id, secilen, gorev, yardimci):
    satirlar, google, geo = gorev_satirlari(secilen, gorev, yardimci)
    st.subheader(gorev_basligi(gorev))
    st.html(gorev_html(satirlar))
    _ekip_harita(google, geo)
    onay = st.session_state.get("ekip_onay_id")
    try:
        onayda = int(onay) == int(gorev["id"])
    except (TypeError, ValueError):
        onayda = False
    if onay is not None and not onayda:
        st.session_state.pop("ekip_onay_id", None)
    if not onayda and st.button("Yenile", key="ekip_yenile", width="stretch", wrap=True):
        refresh()
        st.rerun()
    if not onayda:
        if st.button(
            "Görevim Bitti",
            key="gorev_bitti",
            type="primary",
            width="stretch",
            wrap=True,
        ):
            st.session_state["ekip_onay_id"] = int(gorev["id"])
            st.rerun()
        return
    enkaz = gorev.get("enkazlar") if isinstance(gorev.get("enkazlar"), dict) else {}
    enkaz_adi = enkaz.get("isim") or "—"
    st.warning(ekip_onay_metni(enkaz_adi))
    if st.button("Vazgeç", key="gorev_bitti_vazgec", width="stretch", wrap=True):
        st.session_state.pop("ekip_onay_id", None)
        st.rerun()
    if st.button(
        "Evet, görevi bitir",
        key="gorev_bitti_onay",
        type="primary",
        width="stretch",
        wrap=True,
    ):
        try:
            bit = gorevi_bitir(db, ekip_id, gorev["id"])
        except Exception:
            _ekip_baglanti_goster(refresh)
            return
        if bit is None:
            st.session_state.pop("ekip_onay_id", None)
            st.error("Bu görev size ait değil veya zaten kapanmış.")
            return
        refresh()
        st.session_state.pop("ekip_onay_id", None)
        st.session_state["gorev_sonuc"] = {
            "ekip_id": ekip_id,
            "metin": ekip_bitti_metni(
                secilen.get("isim") or "—",
                ekip_id,
                enkaz_adi,
                format_dt(gorev.get("baslangic")),
                format_dt(bit),
            ),
        }
        st.rerun()


def _ekip_paneli(db, fetch, refresh, auth):
    try:
        ekip_id = int(auth["ekip_id"])
    except (KeyError, TypeError, ValueError):
        st.error("Oturum geçersiz. Çıkış yapıp yeniden girin.")
        return
    try:
        bulunan, gorev, yardimci = ekip_gorev_kaydi(fetch, ekip_id)
    except Exception:
        _ekip_baglanti_goster(refresh)
        return
    if not bulunan:
        st.warning("Ekip kaydı bulunamadı. Çıkış yapıp yeniden girin.")
        return
    secilen = bulunan[0]
    _kimlik_satiri(secilen)
    if gorev is not None:
        eski = st.session_state.get("gorev_sonuc")
        if isinstance(eski, dict) and eski.get("ekip_id") == ekip_id:
            st.session_state.pop("gorev_sonuc", None)
        _ekip_aktif(db, refresh, ekip_id, secilen, gorev, yardimci)
        return
    sonuc = st.session_state.get("gorev_sonuc")
    if isinstance(sonuc, dict) and sonuc.get("ekip_id") == ekip_id and sonuc.get("metin"):
        st.success(sonuc["metin"])
    else:
        st.info(EKIP_GOREV_YOK)
    if st.button("Yenile", key="ekip_yenile", width="stretch", wrap=True):
        refresh()
        st.rerun()


def main():
    # Rol yerleşimden önce okunur: ekip ekranı centered, yönetim wide kalır.
    rol = st.session_state.get("rol", "Admin")
    if rol == "Ekip":
        st.set_page_config(
            page_title="Deprem Kaynak Atama DSS",
            layout="centered",
            initial_sidebar_state="collapsed",
        )
    else:
        st.set_page_config(
            page_title="Deprem Kaynak Atama DSS",
            layout="wide",
            initial_sidebar_state="auto",
        )

    @st.cache_resource
    def connect_supabase(url, key):
        return create_client(url, key)

    @st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
    def load_rows(scope, table, columns, filters):
        return run_select(_DBS[scope], table, columns, filters)

    def refresh():
        load_rows.clear()

    creds = read_credentials()
    if creds is None and not demo_isteniyor():
        st.title("Marmara Depremi Kaynak Atama Karar Destek Sistemi")
        st.error(
            "Supabase anahtarları bulunamadı. .streamlit/secrets.toml dosyasına "
            "SUPABASE_URL ve SUPABASE_KEY yazın. Kayıtların kaydedilmediği yerel deneme "
            "için uygulamayı DEPREM_DEMO=1 ile başlatın."
        )
        st.stop()

    if creds is None:
        from demo_client import MemorySupabase

        db = st.session_state.get("memory_db")
        if db is None:
            db = MemorySupabase()
            st.session_state["memory_db"] = db
        _DBS[db.scope_id] = db
    else:
        db = SupabaseHandle(connect_supabase(creds[0], creds[1]))
        _DBS[db.scope_id] = db

    def fetch(table, columns="*", filters=()):
        return load_rows(db.scope_id, table, columns, tuple(filters))

    def fetch_now(table, columns="*", filters=()):
        return run_select(db, table, columns, tuple(filters))

    if rol != "Ekip":
        st.title("Marmara Depremi Kaynak Atama Karar Destek Sistemi")
    if getattr(db, "is_memory", False):
        if rol == "Ekip":
            st.warning("Deneme modu. Kayıtlar kaydedilmez.")
        else:
            st.warning(
                "Deneme modu. Veriler kaydedilmez; kayıtlar yalnızca bu oturumda bellekte tutulur."
            )
    render_flashes()
    if rol == "Admin" and not getattr(db, "is_memory", False):
        st.sidebar.info("Veriler Supabase'te kalır. Tamamlanan atamalar yeniden planlamada silinmez.")
    auth = st.session_state.get("auth")
    if auth is not None and not isinstance(auth, dict):
        st.session_state.pop("auth", None)
        auth = None
    giris_tamam = isinstance(auth, dict) and auth.get("rol") == rol
    if rol != "Ekip":
        _rol_secimi()
        _cikis_dugmesi()
    parola, deneme_varsayilani = yonetici_parolasi(
        secret_degeri("ADMIN_PASSWORD"),
        os.environ.get("ADMIN_PASSWORD"),
        getattr(db, "is_memory", False),
    )

    if rol == "Admin" and not giris_tamam:
        _admin_giris(parola, deneme_varsayilani)
    elif rol == "Ekip" and not giris_tamam:
        _ekip_telefon_css()
        _ekip_ust_satir()
        try:
            ekipler = fetch("ekipler", "*")
        except Exception:
            _ekip_baglanti_goster(refresh)
        else:
            _ekip_giris(ekipler, getattr(db, "is_memory", False))
    elif rol == "Admin":
        st.header("Admin Paneli")
        render_son_atama()
        render_birinci_asama()
        tab_enkaz, tab_ekip, tab_atama, tab_durum = st.tabs(
            ["Enkazlar", "Ekipler", "Atama Çalıştır", "Durum"]
        )

        with tab_enkaz:
            st.subheader("Enkaz Ekle")
            with st.form("enkaz_form"):
                isim = st.text_input(
                    "Enkaz ismi",
                    key="enkaz_isim",
                    max_chars=120,
                    placeholder="Örn. Avcılar-Merkez",
                )
                enlem = st.number_input(
                    "Enlem",
                    key="enkaz_enlem",
                    value=41.0,
                    min_value=-90.0,
                    max_value=90.0,
                    step=0.01,
                    format="%.5f",
                    help="Derece. Geçerli aralık -90 ile 90. Varsayılan, İstanbul için yaklaşık bir değerdir (41,0).",
                )
                boylam = st.number_input(
                    "Boylam",
                    key="enkaz_boylam",
                    value=28.9,
                    min_value=-180.0,
                    max_value=180.0,
                    step=0.01,
                    format="%.5f",
                    help="Derece. Geçerli aralık -180 ile 180. Varsayılan, İstanbul için yaklaşık bir değerdir (28,9).",
                )
                talep = st.number_input(
                    "Talep (kişi)",
                    key="enkaz_talep",
                    value=100.0,
                    min_value=0.0,
                    step=1.0,
                    format="%.1f",
                    help="Enkazda karşılanması beklenen kişi sayısı. 0'dan büyük, en fazla 1.000.000.",
                )
                makine = st.checkbox(
                    "İş makinesi gerekli",
                    key="enkaz_makine",
                    help="Enkaz iş makinesi istiyorsa işaretleyin. Makine ekip olarak atanmaz; Durum sekmesinde havuza yazılır.",
                )
                if st.form_submit_button("Enkaz ekle", key="enkaz_ekle"):
                    hatalar = enkaz_hatalari(isim, enlem, boylam, talep)
                    if hatalar:
                        _hatalari_goster(hatalar)
                    else:
                        db.table("enkazlar").insert(
                            {
                                "isim": isim.strip(),
                                "enlem": float(enlem),
                                "boylam": float(boylam),
                                "talep": float(talep),
                                "makine_gerekli": 1 if makine else 0,
                                "durum": "aktif",
                            }
                        ).execute()
                        refresh()
                        flash("success", "Enkaz eklendi")
                        st.rerun()

            st.subheader("Avcılar örnek verisi")
            st.info(AVCILAR_BILGI)
            col_sil, col_ekle = st.columns(2)
            with col_sil:
                if st.button(
                    "Avcılar Temizle ve Üret",
                    key="avcilar_sil_iste",
                    help="İsmi Avcılar- ile başlayan enkazları silip 10 mahalle noktası yazar. Önce onay ister.",
                ):
                    st.session_state[_CONFIRM_AVCILAR] = True
            with col_ekle:
                if st.button(
                    "Avcılar Üzerine Ekle",
                    key="avcilar_ekle",
                    help="Mevcut kayıtları silmeden 10 yeni Avcılar noktası ekler.",
                ):
                    db.table("enkazlar").insert(_avcilar_satirlari(ustune=True)).execute()
                    refresh()
                    flash("success", "Yeni Avcılar enkazları eklendi (eskiler duruyor)")
                    st.rerun()
            if st.session_state.get(_CONFIRM_AVCILAR):
                st.warning(
                    "İsmi «Avcılar-» ile başlayan tüm enkaz kayıtları silinecek ve 10 yeni nokta yazılacak. "
                    "Bu işlem geri alınamaz."
                )
                onay_col, vazgec_col = st.columns(2)
                with onay_col:
                    if st.button("Sil ve üret", key="avcilar_sil_onay"):
                        db.table("enkazlar").delete().like("isim", "Avcılar-%").execute()
                        db.table("enkazlar").insert(_avcilar_satirlari(ustune=False)).execute()
                        st.session_state[_CONFIRM_AVCILAR] = False
                        refresh()
                        flash("success", "Eski Avcılar kayıtları silindi, yenileri eklendi")
                        st.rerun()
                with vazgec_col:
                    if st.button("Vazgeç", key="avcilar_sil_vazgec"):
                        st.session_state[_CONFIRM_AVCILAR] = False
                        st.rerun()

            st.subheader("Mevcut Enkazlar")
            enkaz_rows = fetch("enkazlar", "*")
            show_enkaz_tablosu(enkaz_rows)
            show_enkaz_haritasi(enkaz_rows)

        with tab_ekip:
            st.subheader("Ekip Ekle")
            with st.form("ekip_form"):
                ekip_isim = st.text_input(
                    "Ekip ismi",
                    key="ekip_isim",
                    max_chars=120,
                    placeholder="Örn. AK-1",
                )
                st.selectbox(
                    "Tip",
                    ["Arama-Kurtarma"],
                    key="ekip_tip",
                    help="Yalnızca arama-kurtarma ekipleri modele girer. UMKE ve iş makinesi enkaz havuzunda tutulur.",
                )
                kapasite = st.number_input(
                    "Kapasite (kişi)",
                    key="ekip_kapasite",
                    value=10.0,
                    min_value=0.0,
                    step=1.0,
                    format="%.1f",
                    help="Ekibin karşılayabileceği kişi sayısı. 0'dan büyük, en fazla 100.000. β etkin kapasiteyi kapasite / (1+β) olacak şekilde düşürür.",
                )
                erisim_kodu = st.text_input(
                    "Erişim kodu",
                    key="ekip_kod",
                    max_chars=KOD_UST_SINIR,
                    autocomplete="off",
                    help="Ekibin panele girerken yazacağı kod. Boş bırakılırsa bu ekip giriş yapamaz. Kod aşağıdaki tabloda görünür.",
                )
                if st.form_submit_button("Ekip ekle", key="ekip_ekle"):
                    hatalar = ekip_hatalari(ekip_isim, kapasite, erisim_kodu)
                    if hatalar:
                        _hatalari_goster(hatalar)
                    else:
                        payload = {
                            "isim": ekip_isim.strip(),
                            "tip": "Arama-Kurtarma",
                            "kapasite": float(kapasite),
                            "durum": "musait",
                        }
                        kod = "" if erisim_kodu is None else str(erisim_kodu).strip()
                        # Sütun eski şemada yokken kod boşsa kayıt eskisi gibi yazılır.
                        if kod:
                            payload["erisim_kodu"] = kod
                        try:
                            db.table("ekipler").insert(payload).execute()
                        except Exception as exc:
                            if "erisim_kodu" in str(exc).lower():
                                st.error(
                                    "Erişim kodu kaydedilemedi. supabase_schema.sql içindeki "
                                    "ekipler.erisim_kodu sütununu ekleyin."
                                )
                            else:
                                raise
                        else:
                            refresh()
                            flash("success", "Arama-Kurtarma ekibi eklendi")
                            st.rerun()
            st.info(
                "UMKE ve iş makinesi bireysel ekip olarak atanmaz. Enkaz bazlı yardımcı kaynak havuzu olarak yönetilir."
            )
            show_ekip_tablosu(fetch("ekipler", "*"))

        with tab_atama:
            st.subheader("Atama Optimizasyonu")
            senaryo = st.selectbox(
                "Senaryo",
                ["İyimser", "Baz", "Kötümser"],
                key="senaryo",
                help=(
                    "Operasyonel atamada β etkin kapasiteyi düşürür: kapasite / (1+β). "
                    "h, yolun açık olma olasılığıdır; çekilişte h=0 çıkan enkaza atama yapılmaz. "
                    "Birinci aşama planı üç rapor senaryosunu birlikte çözer; orada β yol gecikmesidir. "
                    "İyimser β=0,2 ve h≈0,9. Baz β=0,5 ve h≈0,7. Kötümser β=1,0 ve h≈0,4."
                ),
            )
            beta = {"İyimser": 0.2, "Baz": 0.5, "Kötümser": 1.0}[senaryo]
            h_orani = {"İyimser": 0.9, "Baz": 0.7, "Kötümser": 0.4}[senaryo]
            st.caption(f"β = {beta} | Açık yol oranı h ≈ {h_orani}")
            st.caption(
                "Operasyonel atama seçilen senaryoyu eski kapasite çarpanıyla Supabase'e yazar. "
                "Birinci aşama planı rapor senaryolarını birlikte çözer; β orada yol gecikmesidir."
            )
            if st.button(
                "Atamayı Çalıştır (PuLP ile)",
                key="atama_calistir",
                help="Müsait arama-kurtarma ekiplerini, yolu açık görünen aktif enkazlara atar ve birinci aşama planını çözer.",
            ):
                enkazlar = pd.DataFrame(
                    fetch_now("enkazlar", "*", (("eq", "durum", "aktif"),))
                )
                ekipler = pd.DataFrame(
                    fetch_now(
                        "ekipler",
                        "*",
                        (("eq", "durum", "musait"), ("eq", "tip", "Arama-Kurtarma")),
                    )
                )
                if len(enkazlar) == 0 or len(ekipler) == 0:
                    st.session_state["son_atama"] = {
                        "level": "warning",
                        "mesaj": "Aktif enkaz veya müsait Arama-Kurtarma ekibi yok",
                        "satirlar": [],
                        "kapali": [],
                    }
                    st.session_state.pop("plan_view", None)
                    st.session_state.pop("plan_error", None)
                    st.session_state.pop("chain_view", None)
                    st.session_state.pop("chain_error", None)
                else:
                    enkazlar["h"] = [1 if random.random() < h_orani else 0 for _ in range(len(enkazlar))]
                    acik_enkazlar = enkazlar[enkazlar["h"] == 1]
                    kapali_isimler = [str(isim) for isim in enkazlar.loc[enkazlar["h"] == 0, "isim"].tolist()]
                    if len(acik_enkazlar) == 0:
                        st.session_state["son_atama"] = {
                            "level": "warning",
                            "mesaj": "Bu senaryoda tüm yollar kapalı (h=0)",
                            "satirlar": [],
                            "kapali": kapali_isimler,
                        }
                    else:
                        team_rows = modelsiz_ekip(ekipler.to_dict("records"))
                        site_rows = acik_enkazlar.to_dict("records")
                        result = solve_team_to_site(team_rows, site_rows, beta)
                        if result.status == "Optimal":
                            atanan = 0
                            satirlar = []
                            team_by_id = {team["id"]: team for team in team_rows}
                            site_by_id = {site["id"]: site for site in site_rows}
                            for assignment in result.assignments:
                                team = team_by_id[assignment.ekip_id]
                                site = site_by_id[assignment.enkaz_id]
                                bas = datetime.now().isoformat()
                                db.table("atamalar").insert({
                                    "ekip_id": int(team["id"]),
                                    "enkaz_id": int(site["id"]),
                                    "baslangic": bas,
                                    "durum": "devam",
                                }).execute()
                                db.table("ekipler").update({"durum": "meşgul"}).eq("id", int(team["id"])).execute()
                                yeni_talep = max(0, site["talep"] - assignment.etkin_kapasite)
                                db.table("enkazlar").update({
                                    "talep": yeni_talep,
                                    "durum": "tamam" if yeni_talep <= 0 else "aktif",
                                }).eq("id", int(site["id"])).execute()
                                atanan += 1
                                satirlar.append(
                                    {
                                        "Ekip": f"{team['isim']} (#{int(team['id'])})",
                                        "Enkaz": f"{site['isim']} (#{int(site['id'])})",
                                        "Etkin kapasite (kişi)": round(float(assignment.etkin_kapasite), 1),
                                    }
                                )
                            st.session_state["son_atama"] = {
                                "level": "success",
                                "mesaj": (
                                    f"{atanan} ekip atandı | β={beta} | "
                                    f"Kapalı yol: {len(enkazlar) - len(acik_enkazlar)} enkaz"
                                ),
                                "satirlar": satirlar,
                                "kapali": kapali_isimler,
                            }
                        else:
                            st.session_state["son_atama"] = {
                                "level": "error",
                                "mesaj": "Model çözülemedi",
                                "satirlar": [],
                                "kapali": [],
                            }
                    try:
                        plan_instance = build_live_instance(
                            enkazlar.to_dict("records"),
                            modelsiz_ekip(ekipler.to_dict("records")),
                        )
                        plan_solution = solve_first_stage(plan_instance)
                        if plan_solution.status != "Optimal":
                            st.session_state["plan_error"] = f"Plan çözümü {plan_solution.status}"
                            st.session_state.pop("plan_view", None)
                            st.session_state.pop("chain_view", None)
                            st.session_state.pop("chain_error", None)
                        else:
                            st.session_state["plan_view"] = plan_view(plan_instance, plan_solution)
                            st.session_state.pop("plan_error", None)
                            _zinciri_kaydet(plan_instance)
                    except Exception as exc:
                        st.session_state["plan_error"] = str(exc)
                        st.session_state.pop("plan_view", None)
                        st.session_state.pop("chain_view", None)
                        st.session_state.pop("chain_error", None)
                refresh()
                st.rerun()
            st.info("Not: h=0 olan enkazlara atama yapılmaz. β etkin kapasiteyi düşürür. Tamamlanmış atamalar korunur.")

        with tab_durum:
            st.subheader("Aktif Atamalar (Devam Eden)")
            show_atama_tablosu(
                fetch("atamalar", ATAMA_SELECT, (("eq", "durum", "devam"),)),
                "Aktif atama yok",
            )
            st.subheader("Tamamlanmış Atamalar (Korunan)")
            show_atama_tablosu(
                fetch("atamalar", ATAMA_SELECT, (("eq", "durum", "bitti"),)),
                "Tamamlanmış atama yok",
            )
            st.subheader("Yardımcı Kaynaklar (UMKE / İş Makinesi)")
            st.caption("Bireysel atanmaz, enkaz bazlı havuz.")
            aktif_enkaz = fetch("enkazlar", "id, isim, durum", (("eq", "durum", "aktif"),))
            yardimci_rows = fetch("yardimci_kaynaklar", "*")
            tum_enkaz = fetch("enkazlar", "id, isim")
            show_yardimci_tablosu(yardimci_rows, tum_enkaz)
            if aktif_enkaz:
                with st.form("yardimci_form"):
                    secilen_id, _ = select_kayit(
                        "Enkaz",
                        aktif_enkaz,
                        key="yardimci_enkaz",
                        help_text="Kayıt numarası (#) kimliktir. Aynı isimli enkazlarda doğru kaydı seçin.",
                    )
                    umke = st.number_input(
                        "UMKE sayısı",
                        key="yardimci_umke",
                        min_value=0,
                        value=2,
                        step=1,
                        help="Bu enkaza ayrılan UMKE sayısı. Kişi bazında ekip olarak atanmaz.",
                    )
                    makine_sayisi = st.number_input(
                        "İş makinesi sayısı",
                        key="yardimci_makine",
                        min_value=0,
                        value=1,
                        step=1,
                        help="Bu enkaza ayrılan iş makinesi sayısı.",
                    )
                    if st.form_submit_button("Yardımcı kaynak ata", key="yardimci_kaydet"):
                        db.table("yardimci_kaynaklar").upsert(
                            {
                                "enkaz_id": int(secilen_id),
                                "umke_sayisi": int(umke),
                                "makine_sayisi": int(makine_sayisi),
                            }
                        ).execute()
                        refresh()
                        hedef = next(row for row in aktif_enkaz if int(row["id"]) == int(secilen_id))
                        flash("success", f"Yardımcı kaynak atandı: {kayit_etiketi(hedef)}")
                        st.rerun()
            else:
                st.info("Aktif enkaz yok.")
    else:
        _ekip_telefon_css()
        _ekip_ust_satir()
        _ekip_paneli(db, fetch, refresh, auth)


if __name__ == "__main__":
    main()
