"""Canlı kayıtları planlama ve operasyonel çözüme bağlar.

Denklemler ``solve_planning``, ``solve_operational`` ve ``dispatch_target``
içindedir. Bu modül girdi hazırlar, sonucu tabloya çevirir ve atamayı yazar.
Devam eden bir atamayı kapatmaz; görevi olmayan ekibe hedef ekler.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from model.dispatch import dispatch_target
from model.instance import Instance
from model.operational import OperationalState, TeamState, solve_operational
from model.planning import PlanningSolution, solve_planning
from model.planning_inputs import (
    LIVE_CENTERS,
    LIVE_U_TOP,
    LIVE_W_TOP,
    build_planning_instance,
    ekip_tipi,
)
from model.staff import GROUP_A, GROUPS, Resource, group_load, planning_staff

COZUM_YOK = (
    "Süre sınırı içinde uygun tam sayı çözüm bulunamadı. "
    "Periyot sayısını azaltın veya süre sınırını artırın."
)
GIRDI_YOK = "Aktif enkaz veya müsait Arama-Kurtarma ekibi yok"
ACIK_MERKEZ_YOK = "Açık merkez yok. Önce planı çalıştırın."
PLAN_YOK = "Kayıtlı plan yok. Önce atamayı çalıştırın."
PLAN_CAPTION = (
    "Z1 beklenen karşılanmayan iştir. Alt sınır çözücünün en iyi alt sınırıdır. "
    "MIP aralığı (üst − alt) / alt değeridir. Aralık 0 değilse sonuç kanıtlanmış optimal değildir. "
    "Program, olasılığı en yüksek senaryodadır. "
    "Devam eden atama kapanmaz. Yeni hedef, görevi olmayan ekibe yazılır."
)

_CENTER = re.compile(r"^\((.+),(\d+),(\d+)\)$")
_DEBRIS = re.compile(r"^\((.+),(\d+)\)$")
_GRUP_AD = {"A": "Arama-kurtarma", "U": "UMKE", "W": "İş makinesi"}


class PlanGirdiHatasi(ValueError):
    """Eksik canlı kayıt. Çözücü çağrılmaz."""


def cozum_var(solution: PlanningSolution) -> bool:
    return solution.objective is not None


def guvenli_hata(exc: BaseException) -> str:
    satir = str(exc).splitlines()[0].strip() if str(exc).strip() else ""
    if not satir or "Traceback" in satir or "traceback" in satir.lower():
        return "Plan çözülemedi. Süre sınırını veya periyot sayısını değiştirip yeniden deneyin."
    return "Plan çözülemedi: " + satir[:180]


def aktif_enkaz(rows: list[dict]) -> list[dict]:
    bulunan = []
    for row in rows:
        if str(row.get("durum") or "") != "aktif":
            continue
        try:
            talep = float(row.get("talep"))
        except (TypeError, ValueError):
            continue
        if talep <= 0:
            continue
        bulunan.append(row)
    return bulunan


def arama_ekipleri(rows: list[dict], yalniz_musait: bool = False) -> list[dict]:
    bulunan = []
    for row in rows:
        if str(row.get("tip") or "Arama-Kurtarma") != "Arama-Kurtarma":
            continue
        if row.get("kapasite") is None:
            continue
        if yalniz_musait and str(row.get("durum") or "") != "musait":
            continue
        temiz = dict(row)
        temiz.pop("erisim_kodu", None)
        bulunan.append(temiz)
    return bulunan


def referans_senaryo(instance: Instance):
    return max(instance.scenarios, key=lambda scenario: scenario.P)


def kaynak_etiketi(group: str, resource_id: str) -> str:
    """UMKE 1, İş makinesi 1. Arama-kurtarma adı ekip kaydından gelir."""

    sira = resource_id.rsplit("-", 1)[-1]
    if group == "U":
        return f"UMKE {sira}"
    if group == "W":
        return f"İş makinesi {sira}"
    return resource_id


def _kisa_merkez(ad: str) -> str:
    """Ziyaret hücresi dar ekranda da okunsun. Tam ad yerleştirme tablosunda durur."""

    return {
        "Avcılar Belediye Koordinasyon": "Belediye",
        "Ambarlı Lojistik": "Ambarlı",
    }.get(ad, ad)


def merkez_adi(anahtar: str) -> str:
    for key, name, _lat, _lon in LIVE_CENTERS:
        if key == anahtar:
            return name
    return anahtar


def calistir_plan(
    db,
    enkaz_rows: list[dict],
    ekip_rows: list[dict],
    periods: int,
    time_limit: int,
    threads: int = 1,
    u_top: int | None = None,
    w_top: int | None = None,
    simdi: str | None = None,
) -> dict:
    """İlk plan. Müsait arama-kurtarma ekipleri girer. Mevcut devam satırı kapanmaz."""

    enkaz = aktif_enkaz(enkaz_rows)
    ekipler = arama_ekipleri(ekip_rows, yalniz_musait=True)
    if not enkaz or not ekipler:
        raise PlanGirdiHatasi(GIRDI_YOK)
    periods = max(1, int(periods))
    time_limit = max(1, int(time_limit))
    instance, roster = build_planning_instance(enkaz, ekipler, u_top=u_top, w_top=w_top)
    solution = solve_planning(instance, periods=periods, time_limit=time_limit, threads=threads)
    ozet = gorunum(instance, solution, roster, periyot=periods, sure=time_limit)
    if cozum_var(solution):
        hedefler = _hedefler(instance, solution, roster, _devam_haritasi(_atamalari(db)))
        yazilan = atama_yaz(db, hedefler, simdi=simdi)
        ozet["yazilan"] = yazilan
        if yazilan:
            ozet["mesaj"] = f"{ozet['mesaj']} {yazilan} ekibe hedef yazıldı."
    plan_kaydet(db, ozet)
    return ozet


def olay_guncelle(
    db,
    yedek: dict | None = None,
    periods: int | None = None,
    time_limit: int | None = None,
    threads: int = 1,
    simdi: str | None = None,
) -> dict | None:
    """Yeni enkaz veya biten görev sonrası operasyonel çözüm. Plan yoksa None."""

    kayit = plan_oku(db) or yedek
    if not kayit:
        return None
    acik = set(kayit.get("acik") or [])
    if not acik:
        return _uyari(kayit, ACIK_MERKEZ_YOK)
    enkaz_rows, ekip_rows, atama_rows = _tablolar(db)
    enkaz = aktif_enkaz(enkaz_rows)
    ekipler = arama_ekipleri(ekip_rows, yalniz_musait=False)
    if not enkaz or not ekipler:
        return _uyari(kayit, GIRDI_YOK)
    periyot = max(1, int(periods or kayit.get("periyot") or 1))
    sure = max(1, int(time_limit or kayit.get("sure") or 15))
    instance, roster = build_planning_instance(
        enkaz,
        ekipler,
        u_top=kayit.get("u_top", LIVE_U_TOP),
        w_top=kayit.get("w_top", LIVE_W_TOP),
    )
    try:
        state = operasyon_durumu(instance, kayit, roster, atama_rows)
    except ValueError as exc:
        return _uyari(kayit, guvenli_hata(exc))
    solution = solve_operational(
        instance,
        periyot,
        state,
        time_limit=sure,
        threads=threads,
    )
    if not cozum_var(solution):
        eski = dict(kayit)
        eski["durum"] = _durum_adi(solution.status, False)
        eski["durum_kodu"] = solution.status
        eski["alt_sinir"] = solution.lower_bound
        eski["aralik"] = solution.gap
        eski["saniye"] = solution.seconds
        eski["level"] = "warning"
        eski["uyari"] = COZUM_YOK
        eski["mesaj"] = COZUM_YOK
        return eski
    ozet = gorunum(
        instance,
        solution,
        roster,
        periyot=periyot,
        sure=sure,
        u_top=instance.U_top,
        w_top=instance.W_top,
        baslik="Operasyonel yeniden çözüm",
        onceki_merkez={int(item["ekip_id"]): item.get("merkez") for item in kayit.get("ekipler") or []},
    )
    ozet["acik"] = sorted(acik)
    ozet["acik_adlar"] = [merkez_adi(key) for key in ozet["acik"]]
    devam = _devam_haritasi(atama_rows)
    hedefler = _hedefler(instance, solution, roster, devam, yalniz_bos=True)
    yazilan = atama_yaz(db, hedefler, simdi=simdi)
    ozet["yazilan"] = yazilan
    if yazilan:
        ozet["mesaj"] = f"{ozet['mesaj']} {yazilan} ekibe yeni hedef yazıldı."
    else:
        ozet["mesaj"] = f"{ozet['mesaj']} Devam eden atamalar aynı kaldı."
    plan_kaydet(db, ozet)
    return ozet


def gorunum(
    instance: Instance,
    solution: PlanningSolution,
    roster: list[tuple[dict, str]],
    periyot: int,
    sure: int,
    u_top: int | None = None,
    w_top: int | None = None,
    baslik: str = "Plan",
    onceki_merkez: dict[int, str] | None = None,
) -> dict:
    senaryo = referans_senaryo(instance)
    var = cozum_var(solution)
    z1 = None
    if var:
        z1 = solution.z1 if solution.z1 is not None else solution.objective
    acik = [center.j for center in instance.centers if solution.G.get(center.j) == 1] if var else []
    yerlesim = _yerlesim(instance, solution, roster, senaryo.s, onceki_merkez) if var else []
    merkez_satirlari = _merkez_satirlari(instance, solution, yerlesim) if var else []
    program, sutunlar = _program(instance, solution, roster, senaryo.s) if var else ([], [])
    mesaj = (
        f"{baslik} hazır. Çözücü durumu: {_durum_adi(solution.status, var)}. Z1 = {_sayi(z1)}."
        if var
        else COZUM_YOK
    )
    return {
        "baslik": baslik,
        "level": "success" if var else "warning",
        "mesaj": mesaj,
        "uyari": None if var else COZUM_YOK,
        "durum": _durum_adi(solution.status, var),
        "durum_kodu": solution.status,
        "z1": z1,
        "alt_sinir": solution.lower_bound,
        "aralik": solution.gap,
        "saniye": solution.seconds,
        "periyot": periyot,
        "sure": sure,
        "u_top": instance.U_top if u_top is None else u_top,
        "w_top": instance.W_top if w_top is None else w_top,
        "referans": senaryo.s,
        "referans_adi": senaryo.name,
        "acik": acik,
        "acik_adlar": [merkez_adi(key) for key in acik],
        "merkez_satirlari": merkez_satirlari,
        "yerlesim": yerlesim,
        "program": program,
        "periyot_sutunlari": sutunlar,
        "ekipler": [
            {
                "ekip_id": int(row["id"]),
                "isim": str(row.get("isim") or ""),
                "kaynak": kaynak,
                "merkez": _yer_merkezi(yerlesim, int(row["id"])),
                "grup": "Arama-kurtarma",
            }
            for row, kaynak in roster
        ],
        "caption": PLAN_CAPTION + f" Senaryo: {senaryo.name}. Çözücü süresi: {_sayi(solution.seconds)} s.",
    }


def atama_yaz(db, hedefler: list[dict], simdi: str | None = None) -> int:
    """Görevi olmayan ekibe devam satırı ekler. Var olan devam satırını kapatmaz."""

    bas = simdi or datetime.now().isoformat(timespec="seconds")
    yazilan = 0
    for hedef in hedefler:
        ekip_id = int(hedef["ekip_id"])
        enkaz_id = hedef.get("enkaz_id")
        if enkaz_id is None:
            continue
        var = (
            db.table("atamalar")
            .select("id, enkaz_id, durum")
            .eq("ekip_id", ekip_id)
            .eq("durum", "devam")
            .execute()
            .data
        )
        if var:
            continue
        db.table("atamalar").insert(
            {
                "ekip_id": ekip_id,
                "enkaz_id": int(enkaz_id),
                "baslangic": bas,
                "durum": "devam",
            }
        ).execute()
        db.table("ekipler").update({"durum": "meşgul"}).eq("id", ekip_id).execute()
        yazilan += 1
    return yazilan


def plan_kaydet(db, ozet: dict) -> None:
    try:
        mevcut = db.table("planlar").select("id").execute().data
        for row in mevcut:
            db.table("planlar").delete().eq("id", row["id"]).execute()
        db.table("planlar").insert(
            {
                "olusturma": datetime.now().isoformat(timespec="seconds"),
                "durum": ozet.get("durum_kodu") or ozet.get("durum"),
                "periyot_sayisi": ozet.get("periyot"),
                "sure_sinir": ozet.get("sure"),
                "z1": ozet.get("z1"),
                "alt_sinir": ozet.get("alt_sinir"),
                "aralik": ozet.get("aralik"),
                "acik_merkezler": ", ".join(ozet.get("acik_adlar") or []),
                "ozet": json.dumps(ozet, ensure_ascii=False),
            }
        ).execute()
    except Exception as exc:
        if "planlar" in str(exc).lower() or "schema" in str(exc).lower():
            ozet["kayit_uyari"] = (
                "Plan hesaplandı fakat planlar tablosuna yazılamadı. "
                "supabase_schema.sql içindeki planlar tablosunu ekleyin."
            )
            return
        raise


def plan_oku(db) -> dict | None:
    try:
        rows = db.table("planlar").select("*").execute().data
    except Exception:
        return None
    if not rows:
        return None
    son = max(rows, key=lambda row: int(row.get("id") or 0))
    ham = son.get("ozet")
    if not ham:
        return None
    if isinstance(ham, dict):
        return ham
    try:
        return json.loads(ham)
    except (TypeError, ValueError):
        return None


def operasyon_durumu(instance, kayit: dict, roster, atama_rows: list[dict]) -> OperationalState:
    acik = frozenset(kayit.get("acik") or [])
    if not acik:
        raise ValueError(ACIK_MERKEZ_YOK)
    ilk = sorted(acik)[0]
    ev = {int(item["ekip_id"]): item.get("merkez") for item in kayit.get("ekipler") or []}
    devam: dict[int, str] = {}
    bitti: dict[int, set[str]] = {}
    for row in atama_rows:
        try:
            ekip_id = int(row["ekip_id"])
        except (TypeError, ValueError, KeyError):
            continue
        site = "" if row.get("enkaz_id") is None else str(row.get("enkaz_id"))
        if str(row.get("durum") or "") == "devam" and site:
            devam[ekip_id] = site
        elif str(row.get("durum") or "") == "bitti" and site:
            bitti.setdefault(ekip_id, set()).add(site)
    siteler = {site.i for site in instance.sites}
    teams: list[TeamState] = []
    kaynaklar = set()
    for row, kaynak in roster:
        ekip_id = int(row["id"])
        resource = Resource(kaynak, GROUP_A, 1.0, k=ekip_tipi(ekip_id))
        ayrilan = {site for site in bitti.get(ekip_id, set()) if site in siteler}
        current = devam.get(ekip_id)
        if current in siteler:
            teams.append(TeamState(resource, f"d_{current}_t1", 0.0, False, ayrilan - {current}))
        else:
            home = ev.get(ekip_id) or ilk
            if home not in acik:
                home = ilk
            teams.append(TeamState(resource, f"c_{home}_t1_l1", 0.0, True, ayrilan))
        kaynaklar.add(kaynak)
    for resource in planning_staff(instance).resources:
        if resource.group == GROUP_A or resource.r in kaynaklar:
            continue
        teams.append(TeamState(resource, f"c_{ilk}_t1_l1", 0.0, True))
    remaining = {
        (group, site.i, scenario.s): group_load(site, group)
        for scenario in instance.scenarios
        for site in instance.sites
        for group in GROUPS
    }
    return OperationalState(1, 0.0, acik, teams, remaining)


def _hedefler(instance, solution, roster, devam: dict[int, str], yalniz_bos: bool = True) -> list[dict]:
    if not cozum_var(solution):
        return []
    senaryo = referans_senaryo(instance)
    acik = {center.j for center in instance.centers if solution.G.get(center.j) == 1}
    if not acik:
        return []
    kalan = {(group, site.i): group_load(site, group) for site in instance.sites for group in GROUPS}
    siteler = {site.i for site in instance.sites}
    bulunan = []
    for row, kaynak in roster:
        ekip_id = int(row["id"])
        if yalniz_bos and ekip_id in devam:
            continue
        resource = next((item for item in solution.teams if item.r == kaynak), None)
        if resource is None:
            resource = Resource(kaynak, GROUP_A, 1.0, k=ekip_tipi(ekip_id))
        chain = solution.chains.get((kaynak, senaryo.s), [])
        origin = _merkez_from_chain(chain) or next(iter(sorted(acik)))
        if origin not in {center.j for center in instance.centers}:
            origin = next(iter(sorted(acik)))
        target = dispatch_target(
            instance,
            resource,
            senaryo,
            1,
            origin,
            acik,
            kalan,
            set(),
        )
        enkaz_id = int(target) if target in siteler else None
        bulunan.append({"ekip_id": ekip_id, "enkaz_id": enkaz_id, "merkez": origin})
    return bulunan


def _merkez_satirlari(instance: Instance, solution: PlanningSolution, yerlesim: list[dict]) -> list[dict]:
    if solution.V or solution.VU or solution.VW:
        satirlar = []
        for center in instance.centers:
            arama = 0
            for team in instance.team_types:
                arama += int(solution.V.get((center.j, team.k), 0))
            satirlar.append(
                {
                    "Merkez": center.name,
                    "Açık": "Evet" if solution.G.get(center.j) == 1 else "Hayır",
                    "Arama-kurtarma": arama,
                    "UMKE": int(solution.VU.get(center.j, 0)),
                    "İş makinesi": int(solution.VW.get(center.j, 0)),
                }
            )
        return satirlar
    sayac = {
        center.j: {"Arama-kurtarma": 0, "UMKE": 0, "İş makinesi": 0} for center in instance.centers
    }
    ad = {center.name: center.j for center in instance.centers}
    for row in yerlesim:
        key = ad.get(row.get("Merkez"))
        grup = row.get("Grup")
        if key and grup in sayac[key]:
            sayac[key][grup] += 1
    return [
        {
            "Merkez": center.name,
            "Açık": "Evet" if solution.G.get(center.j) == 1 else "Hayır",
            "Arama-kurtarma": sayac[center.j]["Arama-kurtarma"],
            "UMKE": sayac[center.j]["UMKE"],
            "İş makinesi": sayac[center.j]["İş makinesi"],
        }
        for center in instance.centers
    ]


def _yerlesim(instance, solution, roster, scenario_s: str, onceki: dict[int, str] | None) -> list[dict]:
    ad = {center.j: center.name for center in instance.centers}
    satirlar = []
    kullanilan = set()
    for row, kaynak in roster:
        chain = solution.chains.get((kaynak, scenario_s), [])
        merkez = _merkez_from_chain(chain)
        if merkez is None and onceki:
            merkez = onceki.get(int(row["id"]))
        satirlar.append(
            {
                "Ekip": f"{row.get('isim') or 'Ekip'} (#{int(row['id'])})",
                "Grup": "Arama-kurtarma",
                "Merkez": ad.get(merkez, merkez or "—"),
            }
        )
        kullanilan.add(kaynak)
    for resource in solution.teams:
        if resource.r in kullanilan or resource.group == GROUP_A:
            continue
        chain = solution.chains.get((resource.r, scenario_s), [])
        merkez = _merkez_from_chain(chain)
        satirlar.append(
            {
                "Ekip": kaynak_etiketi(resource.group, resource.r),
                "Grup": _GRUP_AD.get(resource.group, resource.group),
                "Merkez": ad.get(merkez, merkez or "—"),
            }
        )
    return satirlar


def _program(instance, solution, roster, scenario_s: str) -> tuple[list[dict], list[str]]:
    site_ad = {site.i: site.name for site in instance.sites}
    merkez_ad = {center.j: center.name for center in instance.centers}
    sutunlar = ["Ekip", "Periyot", "Yer"]
    satirlar = []
    kaynaklar = [(kaynak, f"{row.get('isim') or 'Ekip'} (#{int(row['id'])})") for row, kaynak in roster]
    ekstra = {
        resource.r
        for resource in solution.teams
        if resource.group != GROUP_A and resource.r not in {item[0] for item in kaynaklar}
    }
    for resource in solution.teams:
        if resource.r in ekstra:
            kaynaklar.append((resource.r, kaynak_etiketi(resource.group, resource.r)))
    for kaynak, etiket in kaynaklar:
        chain = solution.chains.get((kaynak, scenario_s), [])
        hucre = {t: [] for t in range(1, solution.periods + 1)}
        for node in chain:
            if node in {"σ", "ω"} or node.startswith("o_") or node.startswith("ω"):
                continue
            center = _CENTER.match(node)
            if center:
                period = int(center.group(2))
                if period in hucre:
                    hucre[period].append(merkez_ad.get(center.group(1), center.group(1)))
                continue
            debris = _DEBRIS.match(node)
            if debris:
                period = int(debris.group(2))
                if period in hucre:
                    hucre[period].append(site_ad.get(debris.group(1), debris.group(1)))
        yazildi = False
        merkez_adlari = set(merkez_ad.values())
        for period in range(1, solution.periods + 1):
            adlar = []
            for ad in hucre[period]:
                if not adlar or adlar[-1] != ad:
                    adlar.append(ad)
            if not adlar:
                continue
            siteler = [ad for ad in adlar if ad not in merkez_adlari]
            goster = siteler or [_kisa_merkez(ad) for ad in adlar]
            satirlar.append({"Ekip": etiket, "Periyot": str(period), "Yer": ", ".join(goster)})
            yazildi = True
        if not yazildi:
            satirlar.append({"Ekip": etiket, "Periyot": "—", "Yer": "—"})
    return satirlar, sutunlar


def _merkez_from_chain(chain: list[str]) -> str | None:
    for node in chain:
        if node.startswith("o_") and len(node) > 2:
            return node[2:]
        center = _CENTER.match(node)
        if center:
            return center.group(1)
    return None


def _yer_merkezi(yerlesim: list[dict], ekip_id: int) -> str | None:
    etiket = f"(#{ekip_id})"
    for row in yerlesim:
        if str(row.get("Ekip") or "").endswith(etiket):
            ad = row.get("Merkez")
            for key, name, _lat, _lon in LIVE_CENTERS:
                if name == ad:
                    return key
            if ad in {key for key, _name, _lat, _lon in LIVE_CENTERS}:
                return ad
    return None


def _durum_adi(status: str, cozum: bool = False) -> str:
    if status == "Time limit":
        return "Süre doldu, çözüm bulundu" if cozum else "Süre doldu, çözüm yok"
    return {
        "Optimal": "Optimal",
        "Infeasible": "Uygun çözüm yok",
        "Not Solved": "Çözülmedi",
        "Undefined": "Tanımsız",
    }.get(status, status or "—")


def _sayi(value) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.4g}"


def _tablolar(db):
    enkaz = db.table("enkazlar").select("*").execute().data
    ekipler = db.table("ekipler").select("*").execute().data
    atamalar = db.table("atamalar").select("*").execute().data
    return enkaz, ekipler, atamalar


def _atamalari(db) -> list[dict]:
    return db.table("atamalar").select("*").execute().data


def _devam_haritasi(rows: list[dict]) -> dict[int, str]:
    bulunan = {}
    for row in rows:
        if str(row.get("durum") or "") != "devam":
            continue
        try:
            bulunan[int(row["ekip_id"])] = str(row.get("enkaz_id"))
        except (TypeError, ValueError, KeyError):
            continue
    return bulunan


def _uyari(kayit: dict, mesaj: str) -> dict:
    eski = dict(kayit)
    eski["level"] = "warning"
    eski["uyari"] = mesaj
    eski["mesaj"] = mesaj
    return eski
