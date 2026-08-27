import os
import re
import urllib.parse
from datetime import datetime
import duckdb
import pandas as pd
import pdfplumber
import requests
import streamlit as st

# =====================================================================
# 1. CONFIGURACIÓN VISUAL Y ETAPAS
# =====================================================================
st.set_page_config(
    page_title="ATS Recruiter Pro ($0)",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    div[data-testid="stExpander"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        margin-bottom: 8px;
    }
    .stButton>button { border-radius: 6px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

STAGES = [
    "Sin gestionar",
    "Convocados",
    "Entrevista grupal",
    "Prueba en VP",
    "Entrevista individual",
    "Contratados"
]

STAGE_COLORS = {
    "Sin gestionar": "#64748b",
    "Convocados": "#2563eb",
    "Entrevista grupal": "#7c3aed",
    "Prueba en VP": "#ea580c",
    "Entrevista individual": "#0891b2",
    "Contratados": "#16a34a"
}

# =====================================================================
# 2. CONEXIÓN CON GOOGLE SHEETS
# =====================================================================
API_URL = st.secrets.get("SHEETS_API_URL", os.getenv("SHEETS_API_URL", ""))

def load_data() -> pd.DataFrame:
    if not API_URL:
        return pd.DataFrame(columns=[
            "id", "nombre", "email", "telefono", "ciudad", 
            "etapa", "tags", "notas", "cv_texto", "fecha_creacion"
        ])
    try:
        resp = requests.get(API_URL, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            df = pd.DataFrame(data)
            if df.empty:
                df = pd.DataFrame(columns=[
                    "id", "nombre", "email", "telefono", "ciudad", 
                    "etapa", "tags", "notas", "cv_texto", "fecha_creacion"
                ])
            else:
                df["id"] = pd.to_numeric(df["id"], errors="coerce").fillna(0).astype(int)
                for col in ["nombre", "email", "telefono", "ciudad", "etapa", "tags", "notas", "cv_texto", "fecha_creacion"]:
                    if col not in df.columns:
                        df[col] = ""
                    else:
                        df[col] = df[col].fillna("").astype(str)
            return df
        else:
            st.error(f"Error al conectar con Google Sheets (HTTP {resp.status_code})")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"Error al cargar datos: {e}")
        return pd.DataFrame()

def sync_data_to_sheet(df: pd.DataFrame):
    if not API_URL:
        st.error("No se ha configurado la URL de Google Sheets en Secrets.")
        return
    try:
        payload = {
            "action": "sync_all",
            "data": df.to_dict(orient="records")
        }
        resp = requests.post(API_URL, json=payload, timeout=25)
        if resp.status_code == 200:
            st.toast("✅ Base de datos actualizada en Google Sheets.")
        else:
            st.error(f"Error al guardar: {resp.text}")
    except Exception as e:
        st.error(f"Error de sincronización: {e}")

# Cargar datos al iniciar
df_all = load_data()

def get_next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    valid_ids = pd.to_numeric(df["id"], errors="coerce").dropna()
    return int(valid_ids.max() + 1) if not valid_ids.empty else 1

def update_candidate_stage(cand_id: int, new_stage: str):
    global df_all
    idx = df_all.index[df_all["id"] == cand_id]
    if len(idx) > 0:
        df_all.loc[idx[0], "etapa"] = new_stage
        sync_data_to_sheet(df_all)

def update_candidate_details(cand_id: int, tags: str, notas: str):
    global df_all
    idx = df_all.index[df_all["id"] == cand_id]
    if len(idx) > 0:
        df_all.loc[idx[0], "tags"] = tags
        df_all.loc[idx[0], "notas"] = notas
        sync_data_to_sheet(df_all)

def insert_single(nombre, email, telefono, ciudad, etapa, tags, notas):
    global df_all
    next_id = get_next_id(df_all)
    new_row = {
        "id": next_id,
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
        "ciudad": ciudad,
        "etapa": etapa,
        "tags": tags,
        "notas": notas,
        "cv_texto": "",
        "fecha_creacion": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    df_all = pd.concat([df_all, pd.DataFrame([new_row])], ignore_index=True)
    sync_data_to_sheet(df_all)

def insert_batch(new_records_df: pd.DataFrame):
    global df_all
    current_id = get_next_id(df_all)
    new_records_df["id"] = range(current_id, current_id + len(new_records_df))
    new_records_df["fecha_creacion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df_all = pd.concat([df_all, new_records_df], ignore_index=True)
    sync_data_to_sheet(df_all)

# =====================================================================
# 3. BARRA LATERAL (FILTROS)
# =====================================================================
with st.sidebar:
    st.title("💼 ATS Cloud")
    st.caption("Base de datos sincronizada con Google Sheets.")
    
    if not API_URL:
        st.warning("⚠️ Pega la URL de tu Apps Script:")
        temp_url = st.text_input("URL (.exec)")
        if temp_url:
            API_URL = temp_url
            st.rerun()
            
    if st.button("🔄 Recargar datos desde Drive"):
        st.rerun()
        
    st.divider()
    cities = ["Todas"] + sorted(list(df_all["ciudad"].replace("", "No especificada").unique())) if not df_all.empty else ["Todas"]
    selected_city = st.selectbox("Filtrar por Ciudad", cities)
    search_term = st.text_input("Buscar (Nombre / Email / Tag)", "")

# =====================================================================
# 4. FILTRADO CON DUCKDB
# =====================================================================
if not df_all.empty:
    con = duckdb.connect(database=':memory:')
    con.register('candidates', df_all)
    query = "SELECT * FROM candidates WHERE 1=1"
    if selected_city != "Todas":
        query += f" AND ciudad = '{selected_city}'"
    if search_term:
        term = f"%{search_term.lower()}%"
        query += f" AND (LOWER(nombre) LIKE '{term}' OR LOWER(email) LIKE '{term}' OR LOWER(tags) LIKE '{term}')"
    filtered_df = con.execute(query).df()
    con.close()
else:
    filtered_df = pd.DataFrame()

# =====================================================================
# 5. PESTAÑAS PRINCIPALES
# =====================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Tablero Kanban", 
    "📥 Ingesta Multicanal", 
    "💬 Mensajes & Contacto", 
    "📊 Analítica"
])

# --- TAB 1: KANBAN ---
with tab1:
    cols = st.columns(6)
    for i, stage in enumerate(STAGES):
        with cols[i]:
            stage_cands = filtered_df[filtered_df['etapa'] == stage] if not filtered_df.empty else pd.DataFrame()
            count = len(stage_cands)
            color = STAGE_COLORS[stage]
            st.markdown(
                f"<div style='background-color:{color};color:white;padding:8px;border-radius:6px;text-align:center;font-weight:600;margin-bottom:10px;'>{stage} ({count})</div>",
                unsafe_allow_html=True
            )
            
            for _, cand in stage_cands.iterrows():
                with st.expander(f"👤 {cand['nombre']}"):
                    st.write(f"📍 **Ciudad:** {cand['ciudad']}")
                    st.write(f"✉️ **Email:** {cand['email'] or 'Sin email'}")
                    st.write(f"📞 **Tel:** {cand['telefono'] or 'Sin tel'}")
                    if cand['tags']:
                        st.caption(f"🏷️ `{cand['tags']}`")
                    
                    new_st = st.selectbox(
                        "Mover a:", 
                        STAGES, 
                        index=STAGES.index(cand['etapa']) if cand['etapa'] in STAGES else 0,
                        key=f"stage_sel_{cand['id']}"
                    )
                    if new_st != cand['etapa']:
                        update_candidate_stage(cand['id'], new_st)
                        st.rerun()
                        
                    with st.form(key=f"form_note_{cand['id']}"):
                        t = st.text_input("Tags", value=cand['tags'] or "")
                        n = st.text_area("Notas", value=cand['notas'] or "")
                        if st.form_submit_button("Guardar"):
                            update_candidate_details(cand['id'], t, n)
                            st.rerun()
                            
                    if cand['cv_texto']:
                        with st.popover("📄 Ver extracto CV"):
                            st.text_area("Texto extraído", value=cand['cv_texto'], height=180, disabled=True)

# --- TAB 2: INGESTA MULTICANAL ---
with tab2:
    st.subheader("📥 Cargar Candidatos")
    mode = st.radio("Método", ["Individual Manual", "Planilla Excel / CSV (Masivo)", "Lote de CVs (PDF)"], horizontal=True)
    
    if mode == "Individual Manual":
        with st.form("manual_add_form"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Nombre y Apellido *")
                email = st.text_input("Correo")
                phone = st.text_input("Teléfono")
            with c2:
                city = st.text_input("Ciudad", value="Buenos Aires")
                stage = st.selectbox("Etapa Inicial", STAGES)
                tags = st.text_input("Etiquetas", value="General")
            notes = st.text_area("Notas iniciales")
            if st.form_submit_button("Guardar"):
                if name:
                    insert_single(name, email, phone, city, stage, tags, notes)
                    st.success(f"Candidato {name} guardado en Google Sheets.")
                    st.rerun()
                else:
                    st.error("El nombre es obligatorio.")

    elif mode == "Planilla Excel / CSV (Masivo)":
        file = st.file_uploader("Sube tu archivo Excel o CSV", type=["xlsx", "xls", "csv"])
        if file:
            df_in = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
            st.write(f"Filas encontradas: **{len(df_in)}**")
            st.dataframe(df_in.head(5))
            if st.button("Confirmar e Importar"):
                with st.spinner("Procesando con DuckDB..."):
                    cols_map = {str(c).lower().strip(): c for c in df_in.columns}
                    name_c = next((cols_map[c] for c in cols_map if 'nom' in c or 'name' in c), None)
                    email_c = next((cols_map[c] for c in cols_map if 'mail' in c), None)
                    phone_c = next((cols_map[c] for c in cols_map if 'tel' in c or 'cel' in c or 'phone' in c), None)
                    city_c = next((cols_map[c] for c in cols_map if 'ciu' in c or 'city' in c), None)
                    
                    clean = pd.DataFrame()
                    clean['nombre'] = df_in[name_c].fillna("Sin Nombre") if name_c else "Sin Nombre"
                    clean['email'] = df_in[email_c].fillna("") if email_c else ""
                    clean['telefono'] = df_in[phone_c].fillna("") if phone_c else ""
                    clean['ciudad'] = df_in[city_c].fillna("No especificada") if city_c else "No especificada"
                    clean['etapa'] = "Sin gestionar"
                    clean['tags'] = "Carga Masiva"
                    clean['notas'] = ""
                    clean['cv_texto'] = ""
                    
                    insert_batch(clean)
                    st.success("¡Importación masiva completada!")
                    st.rerun()

    elif mode == "Lote de CVs (PDF)":
        pdfs = st.file_uploader("Selecciona los archivos PDF", type=["pdf"], accept_multiple_files=True)
        if pdfs and st.button(f"Procesar y guardar {len(pdfs)} CVs"):
            parsed = []
            progress = st.progress(0)
            for i, p in enumerate(pdfs):
                txt = ""
                with pdfplumber.open(p) as pdf:
                    for page in pdf.pages:
                        extracted = page.extract_text()
                        if extracted: txt += extracted + "\n"
                
                email_m = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', txt)
                phone_m = re.search(r'(\+?\d{1,3}[\s-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}', txt)
                
                parsed.append({
                    "nombre": p.name.replace(".pdf", "").replace("_", " ").title(),
                    "email": email_m.group(0) if email_m else "",
                    "telefono": phone_m.group(0) if phone_m else "",
                    "ciudad": "No especificada",
                    "etapa": "Sin gestionar",
                    "tags": "PDF CV",
                    "notas": "",
                    "cv_texto": txt[:2500]
                })
                progress.progress((i + 1) / len(pdfs))
            insert_batch(pd.DataFrame(parsed))
            st.success("¡CVs procesados y guardados en Google Sheets!")
            st.rerun()

# --- TAB 3: COMUNICACIONES ---
with tab3:
    st.subheader("💬 Contactar Candidatos")
    target_stage = st.selectbox("Seleccionar etapa:", STAGES)
    msg_template = st.text_area(
        "Plantilla del mensaje:",
        "¡Hola {nombre}! Te contactamos respecto a tu postulación en {ciudad} para avanzar a la etapa de '{etapa}'."
    )
    
    target_cands = filtered_df[filtered_df['etapa'] == target_stage] if not filtered_df.empty else pd.DataFrame()
    st.write(f"Candidatos en esta etapa: **{len(target_cands)}**")
    
    if not target_cands.empty:
        for _, c in target_cands.iterrows():
            c1, c2, c3 = st.columns([2, 1, 1])
            msg = msg_template.format(nombre=c['nombre'], ciudad=c['ciudad'], etapa=c['etapa'])
            with c1:
                st.markdown(f"**{c['nombre']}** ({c['ciudad']})")
            with c2:
                if c['telefono']:
                    clean_phone = re.sub(r'[^0-9]', '', str(c['telefono']))
                    wa_url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(msg)}"
                    st.link_button("📱 WhatsApp", wa_url)
                else:
                    st.caption("Sin teléfono")
            with c3:
                if c['email']:
                    mail_url = f"mailto:{c['email']}?subject=Proceso de Selección&body={urllib.parse.quote(msg)}"
                    st.link_button("✉️ Correo", mail_url)
                else:
                    st.caption("Sin email")

# --- TAB 4: ANALÍTICA ---
with tab4:
    if not df_all.empty:
        con = duckdb.connect(database=':memory:')
        con.register('df', df_all)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Distribución por Etapa")
            m_stage = con.execute("SELECT etapa, COUNT(*) as total FROM df GROUP BY etapa").df()
            st.bar_chart(m_stage.set_index("etapa"))
        with c2:
            st.markdown("##### Distribución por Ciudad")
            m_city = con.execute("SELECT ciudad, COUNT(*) as total FROM df GROUP BY ciudad LIMIT 8").df()
            st.bar_chart(m_city.set_index("ciudad"))
        con.close()
    else:
        st.info("Sin datos cargados.")