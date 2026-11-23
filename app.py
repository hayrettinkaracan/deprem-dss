import streamlit as st
import pandas as pd
import random
from datetime import datetime
from supabase import create_client, Client

from model.legacy_assignment import solve_team_to_site
from model.planning_inputs import build_live_instance, plan_view
from model.problem import solve_first_stage
from model.routing import CHAIN_CAPTION, chain_rows, solve_team_chains

# Supabase bağlantısı (secrets.toml veya env'den)
@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = get_supabase()

st.set_page_config(page_title="Deprem Kaynak Atama DSS", layout="wide")
st.title("Marmara Depremi Kaynak Atama Karar Destek Sistemi")

# Rol seçimi
rol = st.sidebar.selectbox("Rol Seç", ["Admin", "Ekip"])

if rol == "Admin":
    st.header("Admin Paneli")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Enkazlar", "Ekipler", "Atama Çalıştır", "Durum"])
    
    with tab1:
        st.subheader("Enkaz Ekle")
        with st.form("enkaz_form"):
            isim = st.text_input("Enkaz İsmi")
            enlem = st.number_input("Enlem", value=41.0)
            boylam = st.number_input("Boylam", value=28.9)
            talep = st.number_input("Talep (kişi)", value=100.0)
            makine_gerekli = st.checkbox("İş Makinesi Gerekli")
            if st.form_submit_button("Ekle"):
                supabase.table("enkazlar").insert({
                    "isim": isim,
                    "enlem": enlem,
                    "boylam": boylam,
                    "talep": talep,
                    "makine_gerekli": 1 if makine_gerekli else 0,
                    "durum": "aktif"
                }).execute()
                st.success("Enkaz eklendi")
                st.rerun()
        
        st.subheader("Mevcut Enkazlar")
        response = supabase.table("enkazlar").select("*").execute()
        df = pd.DataFrame(response.data)
        st.dataframe(df)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Avcılar Temizle ve Üret"):
                st.info("""
                **Orijinal Veri (İBB-KRDAE 2020):**
                - Nüfus: ~448.000
                - Bina: 26.762
                - Orta+ hasar: ~7.039 bina (%27)
                - Geçici barınma: 34.941 hane (~105.000 kişi)
                
                **Normalizasyon:** Küçük ölçekli model için 10 enkaz noktasına bölündü.
                """)
                supabase.table("enkazlar").delete().like("isim", "Avcılar-%").execute()
                mahalleler = ["Cihangir", "Yeşilkent", "Üniversite", "Tahtakale", "Gümüşpala", 
                              "Firuzköy", "Denizköşkler", "Merkez", "Ambarlı", "Mustafa Kemal"]
                for mah in mahalleler:
                    talep = random.uniform(600, 1400)
                    makine = 1 if random.random() < 0.35 else 0
                    supabase.table("enkazlar").insert({
                        "isim": f"Avcılar-{mah}",
                        "enlem": 40.98 + random.uniform(-0.05, 0.05),
                        "boylam": 28.72 + random.uniform(-0.05, 0.05),
                        "talep": talep,
                        "makine_gerekli": makine,
                        "durum": "aktif"
                    }).execute()
                st.success("Eski Avcılar kayıtları silindi, yenileri eklendi")
                st.rerun()
        
        with col2:
            if st.button("Avcılar Üzerine Ekle"):
                mahalleler = ["Cihangir", "Yeşilkent", "Üniversite", "Tahtakale", "Gümüşpala", 
                              "Firuzköy", "Denizköşkler", "Merkez", "Ambarlı", "Mustafa Kemal"]
                for mah in mahalleler:
                    talep = random.uniform(600, 1400)
                    makine = 1 if random.random() < 0.35 else 0
                    supabase.table("enkazlar").insert({
                        "isim": f"Avcılar-{mah}-{random.randint(10,99)}",
                        "enlem": 40.98 + random.uniform(-0.05, 0.05),
                        "boylam": 28.72 + random.uniform(-0.05, 0.05),
                        "talep": talep,
                        "makine_gerekli": makine,
                        "durum": "aktif"
                    }).execute()
                st.success("Yeni Avcılar enkazları eklendi (eskiler duruyor)")
                st.rerun()
    
    with tab2:
        st.subheader("Ekip Ekle")
        with st.form("ekip_form"):
            isim = st.text_input("Ekip İsmi")
            tip = st.selectbox("Tip", ["Arama-Kurtarma"])
            kapasite = st.number_input("Kapasite", value=10.0)
            if st.form_submit_button("Ekle"):
                supabase.table("ekipler").insert({
                    "isim": isim,
                    "tip": tip,
                    "kapasite": kapasite,
                    "durum": "musait"
                }).execute()
                st.success("Arama-Kurtarma ekibi eklendi")
                st.rerun()
        
        st.info("Not: UMKE ve İş Makinesi bireysel ekip olarak atanmaz. Enkaz bazlı yardımcı kaynak havuzu olarak yönetilir.")
        
        response = supabase.table("ekipler").select("*").execute()
        df = pd.DataFrame(response.data)
        st.dataframe(df)
    
    with tab3:
        st.subheader("Atama Optimizasyonu")
        
        senaryo = st.selectbox("Senaryo", ["İyimser", "Baz", "Kötümser"])
        beta = {"İyimser": 0.2, "Baz": 0.5, "Kötümser": 1.0}[senaryo]
        h_orani = {"İyimser": 0.9, "Baz": 0.7, "Kötümser": 0.4}[senaryo]
        st.caption(f"β = {beta} | Açık yol oranı h ≈ {h_orani}")
        st.caption(
            "Operasyonel atama seçilen senaryoyu eski kapasite çarpanıyla Supabase'e yazar. "
            "Birinci aşama planı rapor senaryolarını birlikte çözer; β orada yol gecikmesidir."
        )

        if st.button("Atamayı Çalıştır (PuLP ile)"):
            enkaz_resp = supabase.table("enkazlar").select("*").eq("durum", "aktif").execute()
            ekip_resp = supabase.table("ekipler").select("*").eq("durum", "musait").eq("tip", "Arama-Kurtarma").execute()

            enkazlar = pd.DataFrame(enkaz_resp.data)
            ekipler = pd.DataFrame(ekip_resp.data)

            if len(enkazlar) == 0 or len(ekipler) == 0:
                st.session_state["ops_notice"] = (
                    "warning",
                    "Aktif enkaz veya müsait Arama-Kurtarma ekibi yok",
                )
                st.session_state.pop("plan_view", None)
                st.session_state.pop("plan_error", None)
                st.session_state.pop("chain_view", None)
                st.session_state.pop("chain_error", None)
            else:
                enkazlar["h"] = [1 if random.random() < h_orani else 0 for _ in range(len(enkazlar))]
                acik_enkazlar = enkazlar[enkazlar["h"] == 1]

                if len(acik_enkazlar) == 0:
                    st.session_state["ops_notice"] = (
                        "warning",
                        "Bu senaryoda tüm yollar kapalı (h=0)",
                    )
                else:
                    team_rows = ekipler.to_dict("records")
                    site_rows = acik_enkazlar.to_dict("records")
                    result = solve_team_to_site(team_rows, site_rows, beta)

                    if result.status == "Optimal":
                        atanan = 0
                        team_by_id = {team["id"]: team for team in team_rows}
                        site_by_id = {site["id"]: site for site in site_rows}
                        for assignment in result.assignments:
                            team = team_by_id[assignment.ekip_id]
                            site = site_by_id[assignment.enkaz_id]
                            bas = datetime.now().isoformat()
                            supabase.table("atamalar").insert({
                                "ekip_id": int(team["id"]),
                                "enkaz_id": int(site["id"]),
                                "baslangic": bas,
                                "durum": "devam",
                            }).execute()
                            supabase.table("ekipler").update({"durum": "meşgul"}).eq("id", int(team["id"])).execute()
                            yeni_talep = max(0, site["talep"] - assignment.etkin_kapasite)
                            supabase.table("enkazlar").update({
                                "talep": yeni_talep,
                                "durum": "tamam" if yeni_talep <= 0 else "aktif",
                            }).eq("id", int(site["id"])).execute()
                            atanan += 1
                        kapali = len(enkazlar) - len(acik_enkazlar)
                        st.session_state["ops_notice"] = (
                            "success",
                            f"{atanan} ekip atandı | β={beta} | Kapalı yol: {kapali} enkaz",
                        )
                    else:
                        st.session_state["ops_notice"] = ("error", "Model çözülemedi")

                try:
                    plan_instance = build_live_instance(
                        enkazlar.to_dict("records"),
                        ekipler.to_dict("records"),
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
                        try:
                            chain_solution = solve_team_chains(plan_instance, time_limit=20)
                        except Exception as exc:
                            st.session_state["chain_error"] = str(exc)
                            st.session_state.pop("chain_view", None)
                        else:
                            if chain_solution.status == "Optimal":
                                st.session_state["chain_view"] = {
                                    "objective": chain_solution.objective,
                                    "caption": CHAIN_CAPTION,
                                    "rows": chain_rows(plan_instance, chain_solution),
                                }
                                st.session_state.pop("chain_error", None)
                            else:
                                st.session_state["chain_error"] = (
                                    f"Zincir çözümü {chain_solution.status}"
                                )
                                st.session_state.pop("chain_view", None)
                except Exception as exc:
                    st.session_state["plan_error"] = str(exc)
                    st.session_state.pop("plan_view", None)
                    st.session_state.pop("chain_view", None)
                    st.session_state.pop("chain_error", None)
            st.rerun()

        notice = st.session_state.get("ops_notice")
        if notice:
            level, text = notice
            getattr(st, level)(text)

        if st.session_state.get("plan_error"):
            st.warning(f"Birinci aşama planı kurulamadı: {st.session_state['plan_error']}")
        view = st.session_state.get("plan_view")
        if view:
            st.subheader("Birinci aşama planı (G, V, V^U, V^W)")
            st.caption(view["caption"])
            col_obj, col_open, col_teams = st.columns(3)
            col_obj.metric("Beklenen karşılanmayan talep", f"{view['objective']:.1f}")
            col_open.metric("Açık merkez", view["open_count"])
            col_teams.metric("Ön konumlanan ekip", view["team_count"])
            st.dataframe(pd.DataFrame(view["rows"]))
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
            st.dataframe(pd.DataFrame(chain_view["rows"]))

        st.info("Not: h=0 olan enkazlara atama yapılmaz. β etkin kapasiteyi düşürür. Tamamlanmış atamalar korunur.")
    
    with tab4:
        st.subheader("Aktif Atamalar (Devam Eden)")
        aktif = supabase.table("atamalar").select("*, ekipler(isim), enkazlar(isim)").eq("durum", "devam").execute()
        if aktif.data:
            df_aktif = pd.DataFrame([{
                "id": a["id"],
                "ekip": a["ekipler"]["isim"] if a.get("ekipler") else "",
                "enkaz": a["enkazlar"]["isim"] if a.get("enkazlar") else "",
                "Bas": a["baslangic"],
                "Bit": a.get("bitis"),
                "durum": a["durum"]
            } for a in aktif.data])
            st.dataframe(df_aktif)
        else:
            st.info("Aktif atama yok")
        
        st.subheader("Tamamlanmış Atamalar (Korunan)")
        bitti = supabase.table("atamalar").select("*, ekipler(isim), enkazlar(isim)").eq("durum", "bitti").execute()
        if bitti.data:
            df_bitti = pd.DataFrame([{
                "id": a["id"],
                "ekip": a["ekipler"]["isim"] if a.get("ekipler") else "",
                "enkaz": a["enkazlar"]["isim"] if a.get("enkazlar") else "",
                "Bas": a["baslangic"],
                "Bit": a.get("bitis")
            } for a in bitti.data])
            st.dataframe(df_bitti)
        
        st.subheader("Yardımcı Kaynaklar (UMKE / İş Makinesi)")
        st.caption("Rapora uygun: bireysel atanmaz, enkaz bazlı havuz.")
        enkaz_aktif = supabase.table("enkazlar").select("id, isim").eq("durum", "aktif").execute()
        if enkaz_aktif.data:
            secilen = st.selectbox("Enkaz seç", [e["isim"] for e in enkaz_aktif.data])
            enkaz_id = next(e["id"] for e in enkaz_aktif.data if e["isim"] == secilen)
            umke = st.number_input("UMKE sayısı", min_value=0, value=2)
            makine = st.number_input("İş Makinesi sayısı", min_value=0, value=1)
            if st.button("Yardımcı Kaynak Ata"):
                supabase.table("yardimci_kaynaklar").upsert({
                    "enkaz_id": enkaz_id,
                    "umke_sayisi": umke,
                    "makine_sayisi": makine
                }).execute()
                st.success("Yardımcı kaynak atandı")

else:  # Ekip
    st.header("Ekip Paneli")
    ekipler = supabase.table("ekipler").select("*").execute()
    if ekipler.data:
        ekip_sec = st.selectbox("Ekibini Seç", [e["isim"] for e in ekipler.data])
        ekip_id = next(e["id"] for e in ekipler.data if e["isim"] == ekip_sec)
        
        atama = supabase.table("atamalar").select("*, enkazlar(isim, talep)").eq("ekip_id", ekip_id).eq("durum", "devam").execute()
        
        if atama.data:
            a = atama.data[0]
            st.success(f"Görevin: {a['enkazlar']['isim']} (Talep: {a['enkazlar']['talep']})")
            st.caption(f"Bas zamanı: {a['baslangic']}")
            
            if st.button("Görevim Bitti", key=f"bitir_{ekip_id}"):
                bit = datetime.now().isoformat()
                supabase.table("atamalar").update({
                    "durum": "bitti",
                    "bitis": bit
                }).eq("id", a["id"]).execute()
                supabase.table("ekipler").update({"durum": "musait"}).eq("id", ekip_id).execute()
                st.success(f"Görev tamamlandı! Bas: {a['baslangic']} → Bit: {bit}")
                st.info("Diğer ekipler aynı enkazda devam edebilir.")
                st.rerun()
        else:
            st.info("Şu an aktif görevin yok. Müsait durumdasın.")
    else:
        st.warning("Henüz ekip yok.")

st.sidebar.info("Supabase sürümü: Kalıcı veri, senaryo + h/β, Bas/Bit, yeniden planlama koruması.")
