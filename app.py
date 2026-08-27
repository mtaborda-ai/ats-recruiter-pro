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
# 1. CONFIGURACIÓN Y ESTILOS
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
    .tag-badge {
        background-color: #e0f2fe;
        color: #0369a1;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        margin-right: 4px;
        margin-bottom: 4px;
        display: inline-block;
        border: 1px solid #bae6fd;
    }
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
try:
    API_URL = st.secrets["SHEETS_API_URL"]
except Exception:
    API_URL = os.getenv("SHEETS_API_URL", "")

def load_data() -> pd.DataFrame:
    if not API_URL:
        return pd.DataFrame(columns=[
            "id", "nombre", "email", "telefono", "ciudad", 
            "etapa", "tags", "notas", "cv_texto", "fecha_creacion"
        ])
    try:
        resp = requests.get(API_URL, timeout=60)
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
    except requests.exceptions.Timeout:
        st.warning("⚠️ Google Sheets tardó en responder. Haz clic en 'Recargar datos'.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error al cargar datos: {e}")
        return pd.DataFrame()

def sync_data_to_sheet(df: pd.DataFrame):
    if not API_URL:
        st.error("Falta configurar la variable SHEETS_API_URL en Settings ➔ Secrets.")
        return
    try:
        payload = {
            "action": "sync_all",
            "data": df.to_dict(orient="records")
        }
        resp = requests.post(API_URL, json=payload, timeout=60)
        if resp.status_code == 200:
            st.toast("✅ Google Sheets actualizado con éxito.")
        else:
            st.error(f"Error al guardar: {resp.text}")
    except requests.exceptions.Timeout:
        st.warning("⚠️ La sincronización se está completando en segundo plano en Google Drive.")
    except Exception as e:
        st.error(f"Error de sincronización: {e}")

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

def apply_bulk_tags(candidate_ids: list, new_tags_str: str, mode: str = "append"):
    """Aplica etiquetas masivamente a una lista de IDs de candidatos."""
    global df_all
    new_tags_list = [t.strip() for t in new_tags_str.split(",") if t.strip()]
    if not new_tags_list:
        return
        
    for cid in candidate_ids:
        idx = df_all.index[df_all["id"] == cid]
        if len(idx) > 0:
            current_tags = [t.strip() for t in str(df_all.loc[idx[0], "tags"]).split(",") if t.strip()]
            if mode == "append":
                # Une y elimina duplicados manteniendo el orden
                combined = list(dict.fromkeys(current_tags + new_tags_list))
                df_all.loc[idx[0], "tags"] = ", ".join(combined)
            else: # overwrite
                df_all.loc[idx[0], "tags"] = ", ".join(new_tags_list)
                
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
# 3. PARSER DE EXCEL / CSV (COMPUTRABAJO & GENERAL)
# =====================================================================
def parse_computrabajo_or_generic_file(file, custom_bulk_tags="") -> pd.DataFrame:
    file.seek(0)
    if file.name.endswith('.csv'):
        df_preview = pd.read_csv(file, nrows=5)
    else:
        df_preview = pd.read_excel(file, nrows=5)
        
    cols_0 = [str(c).lower().strip() for c in df_preview.columns]
    has_name_0 = any('nom' in c or 'name' in c for c in cols_0)
    has_email_0 = any('mail' in c or 'correo' in c for c in cols_0)
    
    file.seek(0)
    if not (has_name_0 and has_email_0):
        if file.name.endswith('.csv'):
            df_raw = pd.read_csv(file, header=1)
        else:
            df_raw = pd.read_excel(file, header=1)
    else:
        if file.name.endswith('.csv'):
            df_raw = pd.read_csv(file)
        else:
            df_raw = pd.read_excel(file)
            
    cols_map = {str(c).lower().strip(): c for c in df_raw.columns}
    
    name_c = next((cols_map[c] for c in cols_map if c == 'nombre' or 'primer nombre' in c), None)
    surname_c = next((cols_map[c] for c in cols_map if 'apellido' in c), None)
    email_c = next((cols_map[c] for c in cols_map if 'mail' in c or 'correo' in c), None)
    phone_c = next((cols_map[c] for c in cols_map if 'tel' in c or 'cel' in c or 'phone' in c or 'whatsapp' in c), None)
    city_c = next((cols_map[c] for c in cols_map if 'direcc' in c or 'ciu' in c or 'localidad' in c or 'city' in c), None)
    
    title_c = next((cols_map[c] for c in cols_map if 'título del cv' in c or 'titulo del cv' in c or 'puesto' in c), None)
    exp_c = next((cols_map[c] for c in cols_map if 'experiencia profesional' in c or 'experiencia' in c), None)
    desc_c = next((cols_map[c] for c in cols_map if 'descripción profesional' in c or 'descripcion' in c or 'perfil' in c), None)
    study_c = next((cols_map[c] for c in cols_map if 'estudios' in c or 'titulación' in c or 'titulacion' in c), None)
    questions_c = next((cols_map[c] for c in cols_map if 'preguntas' in c), None)
    age_c = next((cols_map[c] for c in cols_map if 'edad' in c), None)
    
    clean = pd.DataFrame()
    
    if name_c and surname_c:
        clean['nombre'] = (df_raw[name_c].fillna('').astype(str).str.strip() + " " + df_raw[surname_c].fillna('').astype(str).str.strip()).str.strip()
    elif name_c:
        clean['nombre'] = df_raw[name_c].fillna('Sin Nombre').astype(str).str.strip()
    else:
        clean['nombre'] = "Sin Nombre"
        
    clean['email'] = df_raw[email_c].fillna('').astype(str).str.strip() if email_c else ""
    clean['telefono'] = df_raw[phone_c].fillna('').astype(str).str.strip() if phone_c else ""
    clean['ciudad'] = df_raw[city_c].fillna('No especificada').astype(str).str.strip() if city_c else "No especificada"
    clean['etapa'] = "Sin gestionar"
    
    # Preparar tags personalizados iniciales
    extra_tags = [t.strip() for t in custom_bulk_tags.split(",") if t.strip()]
    
    tags_list = []
    for _, row in df_raw.iterrows():
        t_items = list(extra_tags)
        if title_c and str(row.get(title_c, '')).strip() not in ['', 'nan', 'No especificado']:
            t_items.append(str(row[title_c]).strip())
        if age_c and str(row.get(age_c, '')).strip() not in ['', 'nan', '0']:
            t_items.append(f"{row[age_c]} años")
        tags_list.append(", ".join(t_items) if t_items else "CompuTrabajo")
    clean['tags'] = tags_list
    clean['notas'] = ""
    
    cv_texts = []
    for _, row in df_raw.iterrows():
        parts = []
        if title_c and str(row.get(title_c, '')).strip() not in ['', 'nan', 'No especificado']:
            parts.append(f"📌 TÍTULO CV: {row[title_c]}")
        if age_c and str(row.get(age_c, '')).strip() not in ['', 'nan']:
            parts.append(f"👤 EDAD: {row[age_c]}")
        if study_c and str(row.get(study_c, '')).strip() not in ['', 'nan']:
            parts.append(f"🎓 ESTUDIOS: {row[study_c]}")
        if desc_c and str(row.get(desc_c, '')).strip() not in ['', 'nan', 'No especificado']:
            parts.append(f"\n📝 DESCRIPCIÓN:\n{row[desc_c]}")
        if exp_c and str(row.get(exp_c, '')).strip() not in ['', 'nan', 'No especificado']:
            parts.append(f"\n💼 EXPERIENCIA LABORAL:\n{row[exp_c]}")
        if questions_c and str(row.get(questions_c, '')).strip() not in ['', 'nan', 'No especificado']:
            preguntas_fmt = str(row[questions_c]).replace('/', '\n• ')
            parts.append(f"\n❓ PREGUNTAS DE FILTRADO:\n• {preguntas_fmt}")
            
        cv_texts.append("\n".join(parts))
    clean['cv_texto'] = cv_texts
    
    return clean

# =====================================================================
# 4. EXTRACCIÓN DE TODAS LAS ETIQUETAS ÚNICAS
# =====================================================================
all_unique_tags = set()
if not df_all.empty and "tags" in df_all.columns:
    for raw_tag in df_all["tags"].dropna():
        for t in str(raw_tag).split(","):
            clean_t = t.strip()
            if clean_t and clean_t.lower() not in ["none", "nan", ""]:
                all_unique_tags.add(clean_t)
sorted_tags = sorted(list(all_unique_tags))

# =====================================================================
# 5. BARRA LATERAL (FILTROS MULTI-ETIQUETA)
# =====================================================================
with st.sidebar:
    st.title("💼 ATS Cloud")
    st.caption("Filtros y Sincronización en Tiempo Real.")
    
    if st.button("🔄 Recargar datos"):
        st.rerun()
        
    st.divider()
    st.subheader("🔍 Filtros de Búsqueda")
    
    cities = ["Todas"] + sorted(list(df_all["ciudad"].replace("", "No especificada").unique())) if not df_all.empty else ["Todas"]
    selected_city = st.selectbox("Filtrar por Ubicación / Barrio", cities)
    
    # Filtro multi-etiqueta
    selected_tags = st.multiselect("🏷️ Filtrar por Etiquetas (ej: Caba, 27/08)", options=sorted_tags)
    
    tag_logic = "AND"
    if len(selected_tags) > 1:
        tag_logic = st.radio("Coincidencia de etiquetas:", ["Contiene TODAS (AND)", "Contiene ALGUNA (OR)"], horizontal=True)
    
    search_term = st.text_input("Buscar texto libre", "")

# =====================================================================
# 6. MOTOR DE FILTRADO CON DUCKDB
# =====================================================================
if not df_all.empty:
    con = duckdb.connect(database=':memory:')
    con.register('candidates', df_all)
    query = "SELECT * FROM candidates WHERE 1=1"
    
    if selected_city != "Todas":
        query += f" AND ciudad = '{selected_city}'"
        
    if selected_tags:
        if "TODAS" in tag_logic or tag_logic == "AND":
            for t in selected_tags:
                query += f" AND LOWER(tags) LIKE '%{t.lower()}%'"
        else: # OR
            tag_conditions = " OR ".join([f"LOWER(tags) LIKE '%{t.lower()}%'" for t in selected_tags])
            query += f" AND ({tag_conditions})"
        
    if search_term:
        term = f"%{search_term.lower()}%"
        query += f""" AND (
            LOWER(nombre) LIKE '{term}' OR 
            LOWER(email) LIKE '{term}' OR 
            LOWER(tags) LIKE '{term}' OR 
            LOWER(cv_texto) LIKE '{term}' OR
            LOWER(notas) LIKE '{term}'
        )"""
        
    filtered_df = con.execute(query).df()
    con.close()
else:
    filtered_df = pd.DataFrame()

# =====================================================================
# 7. PESTAÑAS PRINCIPALES
# =====================================================================
tab1, tab_bulk, tab2, tab3, tab4 = st.tabs([
    "📋 Tablero Kanban",
    "🏷️ Etiquetado Masivo",
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
                    st.write(f"📍 **Ubicación:** {cand['ciudad']}")
                    st.write(f"✉️ **Email:** {cand['email'] or 'Sin email'}")
                    st.write(f"📞 **Tel:** {cand['telefono'] or 'Sin tel'}")
                    
                    if cand['tags']:
                        badges_html = "".join([f"<span class='tag-badge'>🏷️ {t.strip()}</span>" for t in str(cand['tags']).split(',') if t.strip()])
                        st.markdown(badges_html, unsafe_allow_html=True)
                    
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
                        t = st.text_input("Etiquetas (separadas por coma)", value=cand['tags'] or "", help="Ej: Caba, 27/08, Equipo Alfa")
                        n = st.text_area("Notas del Reclutador", value=cand['notas'] or "")
                        if st.form_submit_button("Guardar"):
                            update_candidate_details(cand['id'], t, n)
                            st.rerun()
                            
                    if cand['cv_texto']:
                        with st.popover("📄 Ver Experiencia y Perfil"):
                            st.text_area("Detalle de Experiencia CompuTrabajo", value=cand['cv_texto'], height=300, disabled=True)

# --- TAB 2: ETIQUETADO MASIVO ---
with tab_bulk:
    st.subheader("🏷️ Asignación Masiva de Etiquetas")
    st.caption("Aplica una o múltiples etiquetas a grupos enteros de candidatos a la vez.")
    
    col_b1, col_b2 = st.columns(2)
    
    with col_b1:
        st.markdown("##### 1. Definir Etiquetas a Asignar")
        bulk_tags_input = st.text_input(
            "Etiquetas a aplicar (separadas por coma):",
            placeholder="Ej: Caba, 27/08, Equipo Alfa, Convocatoria Mañana"
        )
        tag_mode = st.radio("Modo de asignación:", ["Añadir a las etiquetas existentes", "Reemplazar etiquetas existentes"], horizontal=True)
        
    with col_b2:
        st.markdown("##### 2. Seleccionar Destinatarios")
        target_selection = st.radio(
            "Aplicar a:",
            ["A los candidatos que coinciden con los filtros actuales", "A todos los candidatos de una etapa específica"]
        )
        
        if target_selection == "A todos los candidatos de una etapa específica":
            target_stage_bulk = st.selectbox("Selecciona la etapa:", STAGES, key="bulk_stage_target")
            target_ids = df_all[df_all['etapa'] == target_stage_bulk]['id'].tolist() if not df_all.empty else []
        else:
            target_ids = filtered_df['id'].tolist() if not filtered_df.empty else []
            
        st.write(f"👥 Candidatos seleccionados para etiquetar: **{len(target_ids)}**")
        
    if st.button(f"🚀 Aplicar Etiquetas a los {len(target_ids)} Candidatos"):
        if not bulk_tags_input.strip():
            st.error("Ingresa al menos una etiqueta.")
        elif not target_ids:
            st.warning("No hay candidatos seleccionados.")
        else:
            with st.spinner("Actualizando etiquetas en Google Sheets..."):
                apply_bulk_tags(target_ids, bulk_tags_input, mode="append" if "Añadir" in tag_mode else "overwrite")
                st.success(f"¡Se asignaron las etiquetas '{bulk_tags_input}' a {len(target_ids)} candidatos!")
                st.rerun()

# --- TAB 3: INGESTA MULTICANAL ---
with tab2:
    st.subheader("📥 Cargar Candidatos")
    mode = st.radio("Método", ["Planilla CompuTrabajo / Excel / CSV (Masivo)", "Individual Manual", "Lote de CVs (PDF)"], horizontal=True)
    
    if mode == "Planilla CompuTrabajo / Excel / CSV (Masivo)":
        st.info("💡 Puedes ingresar etiquetas masivas que se aplicarán automáticamente a todos los candidatos de la planilla (ej: Caba, 27/08).")
        
        bulk_upload_tags = st.text_input("Etiquetas adicionales para esta planilla (opcional):", placeholder="Ej: Caba, 27/08, Promotores")
            
        file = st.file_uploader("Sube tu archivo Excel (.xlsx) o CSV de CompuTrabajo", type=["xlsx", "xls", "csv"])
        if file:
            with st.spinner("Leyendo y procesando experiencias laborales..."):
                clean_df = parse_computrabajo_or_generic_file(file, custom_bulk_tags=bulk_upload_tags)
                st.write(f"📊 Candidatos detectados: **{len(clean_df)}**")
                st.dataframe(clean_df[["nombre", "ciudad", "telefono", "tags", "email"]].head(10), use_container_width=True)
                
                if st.button(f"Confirmar e Importar {len(clean_df)} Candidatos a Google Sheets"):
                    with st.spinner("Guardando en Google Sheets..."):
                        insert_batch(clean_df)
                        st.success("¡Importación masiva completada con éxito!")
                        st.rerun()

    elif mode == "Individual Manual":
        with st.form("manual_add_form"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Nombre y Apellido *")
                email = st.text_input("Correo")
                phone = st.text_input("Teléfono")
            with c2:
                city = st.text_input("Ciudad / Localidad", value="Buenos Aires")
                stage = st.selectbox("Etapa Inicial", STAGES)
                tags = st.text_input("Etiquetas (separadas por coma)", value="Caba, 27/08", help="Ej: Caba, 27/08, Turno Mañana")
            notes = st.text_area("Notas iniciales")
            if st.form_submit_button("Guardar Candidato"):
                if name:
                    insert_single(name, email, phone, city, stage, tags, notes)
                    st.success(f"Candidato {name} agregado a Google Sheets.")
                    st.rerun()
                else:
                    st.error("El nombre es obligatorio.")

    elif mode == "Lote de CVs (PDF)":
        pdf_tags = st.text_input("Etiquetas para este lote de PDFs:", value="CV PDF, Caba, 27/08")
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
                    "tags": pdf_tags,
                    "notas": "",
                    "cv_texto": txt[:3000]
                })
                progress.progress((i + 1) / len(pdfs))
            insert_batch(pd.DataFrame(parsed))
            st.success("¡CVs procesados y guardados en Google Sheets!")
            st.rerun()

# --- TAB 4: COMUNICACIONES ---
with tab3:
    st.subheader("💬 Contactar Candidatos")
    target_stage = st.selectbox("Seleccionar etapa:", STAGES)
    msg_template = st.text_area(
        "Plantilla del mensaje:",
        "¡Hola {nombre}! Te contactamos respecto a tu postulación en {ciudad} para coordinar el paso a la etapa de '{etapa}'."
    )
    
    target_cands = filtered_df[filtered_df['etapa'] == target_stage] if not filtered_df.empty else pd.DataFrame()
    st.write(f"Candidatos en esta etapa (filtrados): **{len(target_cands)}**")
    
    if not target_cands.empty:
        for _, c in target_cands.iterrows():
            c1, c2, c3 = st.columns()
            msg = msg_template.format(nombre=c['nombre'], ciudad=c['ciudad'], etapa=c['etapa'])
            with c1:
                st.markdown(f"**{c['nombre']}** ({c['ciudad']})")
                if c['tags']:
                    badges_html = "".join([f"<span class='tag-badge'>🏷️ {t.strip()}</span>" for t in str(c['tags']).split(',') if t.strip()])
                    st.markdown(badges_html, unsafe_allow_html=True)
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

# --- TAB 5: ANALÍTICA ---
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
            st.markdown("##### Distribución por Ubicación / Barrio")
            m_city = con.execute("SELECT ciudad, COUNT(*) as total FROM df GROUP BY ciudad LIMIT 8").df()
            st.bar_chart(m_city.set_index("ciudad"))
        con.close()
    else:
        st.info("Sin datos cargados.")
