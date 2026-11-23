import streamlit as st
import pandas as pd
import random
from datetime import datetime
import pulp
from supabase import create_client, Client

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
        
        if st.button("Avcılar Gerçek Verisinden Ölçekli Enkaz Üret"):
            st.info("""
            **Orijinal Veri (İBB-KRDAE 2020):**
            - Nüfus: ~448.000
            - Bina: 26.762
            - Orta+ hasar: ~7.039 bina (%27)
            - Geçici barınma: 34.941 hane (~105.000 kişi)
            
            **Normalizasyon:** Küçük ölçekli model için 10 enkaz noktasına bölündü.
            Toplam talep ≈ 10.500 kişi (orijinalin ~1/10’u).
            """)
            # Eski Avcılar kayıtlarını sil
            supabase.table("enkazlar").delete().like("isim", "Avcılar-%").execute()
            supabase.table("enkazlar").delete().like("isim", "Enkaz-%").execute()
            
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
            st.success("Avcılar ölçekli 10 enkaz noktası eklendi")
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
        
        if st.button("Atamayı Çalıştır (PuLP ile)"):
            enkaz_resp = supabase.table("enkazlar").select("*").eq("durum", "aktif").execute()
            ekip_resp = supabase.table("ekipler").select("*").eq("durum", "musait").eq("tip", "Arama-Kurtarma").execute()
            
            enkazlar = pd.DataFrame(enkaz_resp.data)
            ekipler = pd.DataFrame(ekip_resp.data)
            
            if len(enkazlar) == 0 or len(ekipler) == 0:
                st.warning("Aktif enkaz veya müsait Arama-Kurtarma ekibi yok")
            else:
                enkazlar['h'] = [1 if random.random() < h_orani else 0 for _ in range(len(enkazlar))]
                acik_enkazlar = enkazlar[enkazlar['h'] == 1]
                
                if len(acik_enkazlar) == 0:
                    st.warning("Bu senaryoda tüm yollar kapalı (h=0)")
                else:
                    etkin_carpan = 1.0 / (1.0 + beta)
                    
                    prob = pulp.LpProblem("Ekip_Atama", pulp.LpMinimize)
                    x = pulp.LpVariable.dicts("atama", 
                                              ((e['id'], z['id']) for _, e in ekipler.iterrows() for _, z in acik_enkazlar.iterrows()),
                                              cat='Binary')
                    unmet = pulp.LpVariable.dicts("unmet", acik_enkazlar['id'].tolist(), lowBound=0)
                    prob += pulp.lpSum(unmet[z['id']] for _, z in acik_enkazlar.iterrows())
                    
                    for _, z in acik_enkazlar.iterrows():
                        assigned_cap = pulp.lpSum(x[e['id'], z['id']] * e['kapasite'] * etkin_carpan
                                                  for _, e in ekipler.iterrows())
                        prob += unmet[z['id']] >= z['talep'] - assigned_cap
                    
                    for _, e in ekipler.iterrows():
                        prob += pulp.lpSum(x[e['id'], z['id']] for _, z in acik_enkazlar.iterrows()) <= 1
                    
                    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
                    
                    if pulp.LpStatus[status] == 'Optimal':
                        atanan = 0
                        for _, e in ekipler.iterrows():
                            for _, z in acik_enkazlar.iterrows():
                                if pulp.value(x[e['id'], z['id']]) > 0.5:
                                    bas = datetime.now().isoformat()
                                    supabase.table("atamalar").insert({
                                        "ekip_id": int(e['id']),
                                        "enkaz_id": int(z['id']),
                                        "baslangic": bas,
                                        "durum": "devam"
                                    }).execute()
                                    supabase.table("ekipler").update({"durum": "meşgul"}).eq("id", int(e['id'])).execute()
                                    etkin_kap = e['kapasite'] * etkin_carpan
                                    yeni_talep = max(0, z['talep'] - etkin_kap)
                                    supabase.table("enkazlar").update({
                                        "talep": yeni_talep,
                                        "durum": "tamam" if yeni_talep <= 0 else "aktif"
                                    }).eq("id", int(z['id'])).execute()
                                    atanan += 1
                        kapali = len(enkazlar) - len(acik_enkazlar)
                        st.success(f"{atanan} ekip atandı | β={beta} | Kapalı yol: {kapali} enkaz")
                    else:
                        st.error("Model çözülemedi")
            st.rerun()
        
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
