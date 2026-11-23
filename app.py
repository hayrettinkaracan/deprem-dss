"""Marmara deprem kaynak atama karar destek arayüzü.

Supabase kimlik bilgisi varsa o istemci kullanılır. Yoksa oturumluk bellek
içi istemci devreye girer; üretim bağlantısı bu yüzden değişmez.
"""

import copy
import fnmatch
import math
import os
import random
import re
from datetime import datetime
from uuid import uuid4

import pandas as pd
import pulp
import streamlit as st
from supabase import create_client

READ_CACHE_TTL_SECONDS = 20
TALEP_UST_SINIR = 1_000_000
KAPASITE_UST_SINIR = 100_000
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
GOREV_SELECT = "*, enkazlar(isim, talep)"
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


def ekip_hatalari(isim, kapasite):
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
    return hatalar


def kayit_etiketi(row):
    durum = etiket_durum(row.get("durum"))
    ek = f" · {durum}" if durum else ""
    return f"{row.get('isim', '—')} (#{int(row['id'])}){ek}"


def _eq(left, right):
    if left == right:
        return True
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def _like(value, pattern):
    translated = []
    for ch in str(pattern):
        if ch == "%":
            translated.append("*")
        elif ch == "_":
            translated.append("?")
        elif ch in "*?[]":
            translated.append(f"[{ch}]")
        else:
            translated.append(ch)
    return fnmatch.fnmatchcase("" if value is None else str(value), "".join(translated))


def _split_select(spec):
    parts = []
    buf = []
    depth = 0
    for ch in spec:
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.op = "select"
        self.payload = None
        self.columns = "*"
        self.filters = []

    def select(self, columns="*"):
        self.op = "select"
        self.columns = columns
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def upsert(self, payload):
        # Şemada enkaz_id üzerinde çakışma anahtarı yok; upsert yeni satır ekler.
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def like(self, column, pattern):
        self.filters.append(("like", column, pattern))
        return self

    def execute(self):
        return self.db.execute(self)


class MemorySupabase:
    """Supabase sorgularının oturumluk karşılığı. Üretim istemcisi değildir."""

    is_memory = True

    def __init__(self):
        self.scope_id = uuid4().hex
        self.tables = {
            "enkazlar": [],
            "ekipler": [],
            "atamalar": [],
            "yardimci_kaynaklar": [],
        }
        self._seq = {name: 1 for name in self.tables}
        self.select_count = 0
        self.fetch_requests = 0
        self.insert_calls = 0
        self._seed()

    def table(self, name):
        if name not in self.tables:
            self.tables[name] = []
            self._seq[name] = 1
        return _Query(self, name)

    def _seed(self):
        seed = {
            "enkazlar": [
                {
                    "id": 1,
                    "isim": "Avcılar-Merkez",
                    "enlem": 40.9792,
                    "boylam": 28.7214,
                    "talep": 820.4,
                    "makine_gerekli": 1,
                    "durum": "aktif",
                },
                {
                    "id": 2,
                    "isim": "Avcılar-Ambarlı",
                    "enlem": 40.9681,
                    "boylam": 28.7035,
                    "talep": 640,
                    "makine_gerekli": 0,
                    "durum": "aktif",
                },
                {
                    "id": 3,
                    "isim": "Kadıköy-Moda",
                    "enlem": 40.9830,
                    "boylam": 29.0252,
                    "talep": 0,
                    "makine_gerekli": 0,
                    "durum": "tamam",
                },
                {
                    "id": 4,
                    "isim": "Avcılar-Merkez",
                    "enlem": 40.9855,
                    "boylam": 28.7350,
                    "talep": 510.2,
                    "makine_gerekli": 1,
                    "durum": "aktif",
                },
            ],
            "ekipler": [
                {
                    "id": 1,
                    "isim": "AK-1",
                    "tip": "Arama-Kurtarma",
                    "kapasite": 120,
                    "durum": "meşgul",
                },
                {
                    "id": 2,
                    "isim": "AK-1",
                    "tip": "Arama-Kurtarma",
                    "kapasite": 80,
                    "durum": "musait",
                },
                {
                    "id": 3,
                    "isim": "AK-3",
                    "tip": "Arama-Kurtarma",
                    "kapasite": 100,
                    "durum": "musait",
                },
            ],
            "atamalar": [
                {
                    "id": 1,
                    "ekip_id": 1,
                    "enkaz_id": 1,
                    "baslangic": "2026-11-23T06:30:00",
                    "bitis": None,
                    "durum": "devam",
                },
                {
                    "id": 2,
                    "ekip_id": 3,
                    "enkaz_id": 3,
                    "baslangic": "2026-11-22T18:00:00",
                    "bitis": "2026-11-22T22:15:00",
                    "durum": "bitti",
                },
            ],
            "yardimci_kaynaklar": [
                {"id": 1, "enkaz_id": 2, "umke_sayisi": 4, "makine_sayisi": 1},
            ],
        }
        for name, rows in seed.items():
            self.tables[name] = [dict(row) for row in rows]
            self._seq[name] = max(int(row["id"]) for row in rows) + 1

    def _match(self, row, filters):
        for op, column, expected in filters:
            if op == "eq" and not _eq(row.get(column), expected):
                return False
            if op == "like" and not _like(row.get(column), expected):
                return False
        return True

    def _embed(self, row, relation, columns):
        foreign = {"ekipler": "ekip_id", "enkazlar": "enkaz_id"}.get(relation)
        if foreign is None or relation not in self.tables:
            return None
        match = next(
            (item for item in self.tables[relation] if _eq(item.get("id"), row.get(foreign))),
            None,
        )
        if match is None:
            return None
        return {column: match.get(column) for column in columns}

    def _project(self, row, spec):
        if spec.strip() == "*":
            return dict(row)
        include_all = False
        projected = {}
        for part in _split_select(spec):
            if part == "*":
                include_all = True
                continue
            match = re.fullmatch(r"(\w+)\(([^)]*)\)", part)
            if match:
                relation = match.group(1)
                columns = [item.strip() for item in match.group(2).split(",") if item.strip()]
                projected[relation] = self._embed(row, relation, columns)
            else:
                projected[part] = row.get(part)
        if include_all:
            merged = dict(row)
            merged.update(projected)
            return merged
        return projected

    def execute(self, query):
        table = self.tables[query.table]
        if query.op == "select":
            rows = [self._project(row, query.columns) for row in table if self._match(row, query.filters)]
            return _Result(copy.deepcopy(rows))
        if query.op == "insert":
            self.insert_calls += 1
            payloads = query.payload if isinstance(query.payload, list) else [query.payload]
            inserted = []
            for item in payloads:
                row = dict(item)
                if row.get("id") is None:
                    row["id"] = self._seq[query.table]
                    self._seq[query.table] += 1
                else:
                    self._seq[query.table] = max(self._seq[query.table], int(row["id"]) + 1)
                table.append(row)
                inserted.append(dict(row))
            return _Result(inserted)
        if query.op == "update":
            updated = []
            for row in table:
                if self._match(row, query.filters):
                    row.update(query.payload)
                    updated.append(dict(row))
            return _Result(updated)
        if query.op == "delete":
            kept = []
            deleted = []
            for row in table:
                if self._match(row, query.filters):
                    deleted.append(dict(row))
                else:
                    kept.append(row)
            self.tables[query.table] = kept
            return _Result(deleted)
        raise ValueError(query.op)


class SupabaseHandle:
    is_memory = False
    scope_id = "prod"

    def __init__(self, client):
        self._client = client

    def table(self, name):
        return self._client.table(name)


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


def show_ekip_tablosu(rows):
    if not rows:
        st.info("Kayıtlı ekip yok.")
        return
    frame = pd.DataFrame(rows)
    view = pd.DataFrame(
        {
            "İsim": frame["isim"],
            "Tip": frame["tip"],
            "Kapasite (kişi)": pd.to_numeric(frame["kapasite"], errors="coerce"),
            "Durum": frame["durum"].map(etiket_durum),
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


def main():
    # İlk Streamlit çağrısı bu olmalı.
    st.set_page_config(page_title="Deprem Kaynak Atama DSS", layout="wide")

    @st.cache_resource
    def connect_supabase(url, key):
        return create_client(url, key)

    @st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
    def load_rows(scope, table, columns, filters):
        db = _DBS[scope]
        if getattr(db, "is_memory", False):
            db.select_count += 1
        return run_select(db, table, columns, filters)

    def refresh():
        load_rows.clear()

    creds = read_credentials()
    if creds is None:
        db = st.session_state.get("memory_db")
        if db is None:
            db = MemorySupabase()
            st.session_state["memory_db"] = db
        _DBS[db.scope_id] = db
    else:
        db = SupabaseHandle(connect_supabase(creds[0], creds[1]))
        _DBS[db.scope_id] = db

    def fetch(table, columns="*", filters=()):
        if getattr(db, "is_memory", False):
            db.fetch_requests += 1
        return load_rows(db.scope_id, table, columns, tuple(filters))

    def fetch_now(table, columns="*", filters=()):
        return run_select(db, table, columns, tuple(filters))

    st.title("Marmara Depremi Kaynak Atama Karar Destek Sistemi")
    render_flashes()
    if getattr(db, "is_memory", False):
        st.sidebar.info("Supabase anahtarı yok. Kayıtlar bu oturumda bellekte tutulur.")
    else:
        st.sidebar.info("Veriler Supabase'te kalır. Tamamlanan atamalar yeniden planlamada silinmez.")
    rol = st.sidebar.selectbox(
        "Rol",
        ["Admin", "Ekip"],
        key="rol",
        help="Admin enkaz, ekip ve atamayı yönetir. Ekip yalnızca seçtiği görevi görür ve bitirir.",
    )

    if rol == "Admin":
        st.header("Admin Paneli")
        render_son_atama()
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
                if st.form_submit_button("Ekip ekle", key="ekip_ekle"):
                    hatalar = ekip_hatalari(ekip_isim, kapasite)
                    if hatalar:
                        _hatalari_goster(hatalar)
                    else:
                        db.table("ekipler").insert(
                            {
                                "isim": ekip_isim.strip(),
                                "tip": "Arama-Kurtarma",
                                "kapasite": float(kapasite),
                                "durum": "musait",
                            }
                        ).execute()
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
                    "β etkin kapasiteyi düşürür: kapasite / (1+β). "
                    "h, yolun açık olma olasılığıdır; çekilişte h=0 çıkan enkaza atama yapılmaz. "
                    "İyimser β=0,2 ve h≈0,9. Baz β=0,5 ve h≈0,7. Kötümser β=1,0 ve h≈0,4."
                ),
            )
            beta = {"İyimser": 0.2, "Baz": 0.5, "Kötümser": 1.0}[senaryo]
            h_orani = {"İyimser": 0.9, "Baz": 0.7, "Kötümser": 0.4}[senaryo]
            st.caption(f"β = {beta} | Açık yol oranı h ≈ {h_orani}")
            if st.button(
                "Atamayı Çalıştır (PuLP ile)",
                key="atama_calistir",
                help="Müsait arama-kurtarma ekiplerini, yolu açık görünen aktif enkazlara atar.",
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
                    sonuc = {
                        "level": "warning",
                        "mesaj": "Aktif enkaz veya müsait Arama-Kurtarma ekibi yok",
                        "satirlar": [],
                        "kapali": [],
                    }
                else:
                    # Çözücü ve kısıtlar bilinçli olarak aynı bırakıldı.
                    enkazlar["h"] = [1 if random.random() < h_orani else 0 for _ in range(len(enkazlar))]
                    acik_enkazlar = enkazlar[enkazlar["h"] == 1]
                    if len(acik_enkazlar) == 0:
                        sonuc = {
                            "level": "warning",
                            "mesaj": "Bu senaryoda tüm yollar kapalı (h=0)",
                            "satirlar": [],
                            "kapali": [str(isim) for isim in enkazlar["isim"].tolist()],
                        }
                    else:
                        etkin_carpan = 1.0 / (1.0 + beta)
                        prob = pulp.LpProblem("Ekip_Atama", pulp.LpMinimize)
                        x = pulp.LpVariable.dicts(
                            "atama",
                            (
                                (e["id"], z["id"])
                                for _, e in ekipler.iterrows()
                                for _, z in acik_enkazlar.iterrows()
                            ),
                            cat="Binary",
                        )
                        unmet = pulp.LpVariable.dicts("unmet", acik_enkazlar["id"].tolist(), lowBound=0)
                        prob += pulp.lpSum(unmet[z["id"]] for _, z in acik_enkazlar.iterrows())
                        for _, z in acik_enkazlar.iterrows():
                            assigned_cap = pulp.lpSum(
                                x[e["id"], z["id"]] * e["kapasite"] * etkin_carpan
                                for _, e in ekipler.iterrows()
                            )
                            prob += unmet[z["id"]] >= z["talep"] - assigned_cap
                        for _, e in ekipler.iterrows():
                            prob += pulp.lpSum(x[e["id"], z["id"]] for _, z in acik_enkazlar.iterrows()) <= 1
                        status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
                        if pulp.LpStatus[status] == "Optimal":
                            pending = []
                            for _, e in ekipler.iterrows():
                                for _, z in acik_enkazlar.iterrows():
                                    if pulp.value(x[e["id"], z["id"]]) > 0.5:
                                        etkin_kap = e["kapasite"] * etkin_carpan
                                        # Talep düşümü satırın orijinal talebinden hesaplanır.
                                        yeni_talep = max(0, z["talep"] - etkin_kap)
                                        pending.append(
                                            {
                                                "ekip_id": int(e["id"]),
                                                "enkaz_id": int(z["id"]),
                                                "baslangic": datetime.now().isoformat(),
                                                "durum": "devam",
                                                "ekip_isim": e["isim"],
                                                "enkaz_isim": z["isim"],
                                                "etkin_kap": float(etkin_kap),
                                                "yeni_talep": float(yeni_talep),
                                            }
                                        )
                            if pending:
                                db.table("atamalar").insert(
                                    [
                                        {
                                            "ekip_id": item["ekip_id"],
                                            "enkaz_id": item["enkaz_id"],
                                            "baslangic": item["baslangic"],
                                            "durum": "devam",
                                        }
                                        for item in pending
                                    ]
                                ).execute()
                            for item in pending:
                                db.table("ekipler").update({"durum": "meşgul"}).eq("id", item["ekip_id"]).execute()
                                db.table("enkazlar").update(
                                    {
                                        "talep": item["yeni_talep"],
                                        "durum": "tamam" if item["yeni_talep"] <= 0 else "aktif",
                                    }
                                ).eq("id", item["enkaz_id"]).execute()
                            kapali_isimler = [
                                str(isim) for isim in enkazlar.loc[enkazlar["h"] == 0, "isim"].tolist()
                            ]
                            sonuc = {
                                "level": "success",
                                "mesaj": (
                                    f"{len(pending)} ekip atandı | β={beta} | "
                                    f"Kapalı yol: {len(enkazlar) - len(acik_enkazlar)} enkaz"
                                ),
                                "satirlar": [
                                    {
                                        "Ekip": f"{item['ekip_isim']} (#{item['ekip_id']})",
                                        "Enkaz": f"{item['enkaz_isim']} (#{item['enkaz_id']})",
                                        "Etkin kapasite (kişi)": round(item["etkin_kap"], 1),
                                    }
                                    for item in pending
                                ],
                                "kapali": kapali_isimler,
                            }
                        else:
                            sonuc = {
                                "level": "error",
                                "mesaj": "Model çözülemedi",
                                "satirlar": [],
                                "kapali": [],
                            }
                st.session_state["son_atama"] = sonuc
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
        st.header("Ekip Paneli")
        ekipler = fetch("ekipler", "*")
        if ekipler:
            ekip_id, by_id = select_kayit(
                "Ekibini seç",
                ekipler,
                key="ekip_sec",
                help_text="Kayıt numarası (#) kimliktir. Aynı isimli ekiplerden yalnızca seçilen kapanır.",
            )
            atama = fetch(
                "atamalar",
                GOREV_SELECT,
                (("eq", "ekip_id", int(ekip_id)), ("eq", "durum", "devam")),
            )
            if atama:
                gorev = atama[0]
                enkaz = gorev.get("enkazlar") or {}
                talep = enkaz.get("talep")
                talep_txt = "—" if talep is None else f"{float(talep):.1f}"
                enkaz_adi = enkaz.get("isim") or "—"
                bas_txt = format_dt(gorev.get("baslangic"))
                st.success(
                    f"Aktif görev: {enkaz_adi} (#{gorev.get('enkaz_id')}). "
                    f"Kalan talep {talep_txt} kişi. Başlangıç {bas_txt}."
                )
                if st.button(
                    "Görevim Bitti",
                    key="gorev_bitti",
                    help="Seçili ekibin devam eden görevini bitirir ve ekibi müsait yapar. Aynı enkazdaki diğer ekipler durur.",
                ):
                    bit = datetime.now().isoformat()
                    db.table("atamalar").update({"durum": "bitti", "bitis": bit}).eq("id", gorev["id"]).execute()
                    db.table("ekipler").update({"durum": "musait"}).eq("id", int(ekip_id)).execute()
                    refresh()
                    secilen = by_id[int(ekip_id)]
                    flash(
                        "success",
                        (
                            f"Görev tamamlandı: {secilen['isim']} (#{int(ekip_id)}) → {enkaz_adi}. "
                            f"Başlangıç {bas_txt}, bitiş {format_dt(bit)}."
                        ),
                    )
                    flash("info", "Diğer ekipler aynı enkazda devam edebilir.")
                    st.rerun()
            else:
                st.info("Şu an aktif görevin yok. Müsait durumdasın.")
        else:
            st.warning("Henüz ekip yok.")

    if os.environ.get("DEPREM_CACHE_PROBE") == "1" and getattr(db, "is_memory", False):
        once_istek = db.fetch_requests
        once_sorgu = db.select_count
        fetch("ekipler", "*")
        fetch("ekipler", "*")
        st.session_state["onbellek_kanit"] = (
            db.fetch_requests - once_istek,
            db.select_count - once_sorgu,
        )


if __name__ == "__main__":
    main()
