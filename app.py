import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import json
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Athletic Strategy DB", layout="wide", page_icon="🏅")

# --- 1. SETUP & AUTHENTICATION ---
@st.cache_resource
def connect_services():
    try:
        if "gcp_service_account" not in st.secrets:
            return None
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet_url = st.secrets["SHEET_URL"]
        return client.open_by_url(sheet_url).sheet1
    except Exception as e:
        return None

# --- 2. DYNAMIC MODEL LOADER ---
# This function asks Google what models are ACTUALLY available to you
def get_available_models():
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        models = []
        for m in genai.list_models():
            # Filter for models that generate text
            if 'generateContent' in m.supported_generation_methods:
                # specific clean up to remove "models/" prefix
                name = m.name.replace("models/", "")
                models.append(name)
        return sorted(models)
    except Exception as e:
        st.error(f"API Key Error: {e}")
        return ["gemini-1.5-flash"] # Fallback

# --- 3. AI AGENT ---
def run_agent(sport, conference, selected_model_name):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        
        # We use the standard 1.5 tool definition
        # This is safe for 'gemini-1.5-flash' and 'gemini-1.5-pro'
        tools = [
            {"google_search_retrieval": {
                "dynamic_retrieval_config": {
                    "mode": "dynamic",
                    "dynamic_threshold": 0.7,
                }
            }}
        ]
        
        # Use the user-selected model from the sidebar
        model = genai.GenerativeModel(selected_model_name, tools=tools)
        
    except Exception as e:
        st.error(f"Configuration Error: {e}")
        return []

    st.info(f"🤖 Agent (using {selected_model_name}) is searching Google for {conference} {sport}...")
    
    prompt = f"""
    Find the 2025 coaching staff directory for {sport} in the {conference} conference.
    For every university in the conference, list the Head Coach and Assistant Coaches.
    
    Return the data as a JSON list. 
    Format: [{{"school": "University Name", "coach_name": "Name", "title": "Head/Assistant", "email": "Email or 'Not Listed'"}}]
    """
    
    try:
        response = model.generate_content(prompt)
        
        st.info("🔄 Parsing results...")
        
        raw_text = response.text
        clean_text = raw_text.replace("```json", "").replace("```", "").strip()
        
        start = clean_text.find("[")
        end = clean_text.rfind("]") + 1
        if start != -1 and end != -1:
            clean_text = clean_text[start:end]
            
        return json.loads(clean_text)
    
    except Exception as e:
        st.error(f"Execution Error: {e}")
        st.caption("Try selecting a different model in the sidebar.")
        return []

# --- 4. APP INTERFACE ---

with st.sidebar:
    st.header("🎛️ Settings")
    
    # LOAD MODELS DYNAMICALLY
    available_models = get_available_models()
    
    # Try to default to 'gemini-1.5-flash' if it exists in the list
    default_index = 0
    if "gemini-1.5-flash" in available_models:
        default_index = available_models.index("gemini-1.5-flash")
        
    model_choice = st.selectbox("Select AI Model", available_models, index=default_index)
    st.caption(f"Connected: {len(available_models)} models found.")

    st.divider()
    
    # HISTORY LOADER
    worksheet = connect_services()
    df_history = pd.DataFrame()
    if worksheet:
        try:
            data = worksheet.get_all_records()
            df_history = pd.DataFrame(data)
        except: pass

    selected_filter = "Show All"
    if not df_history.empty and "conference" in df_history.columns:
        pairs = df_history[["conference", "sport"]].drop_duplicates()
        options = ["Show All"] + [f"{r.conference} - {r.sport}" for i, r in pairs.iterrows()]
        selected_filter = st.radio("Load Database:", options)

st.title("🏆 Athletic Strategy Database")

tab1, tab2 = st.tabs(["🔍 Find New Coaches", "📂 View Database"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        target_sport = st.selectbox("Sport", ["Men's Track & Field", "Women's Track & Field", "Men's Soccer", "Women's Soccer", "Football", "Men's Basketball"])
    with col2:
        target_conf = st.selectbox("Conference", ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial"])

    if st.button(f"🚀 Find {target_conf} Coaches"):
        if not model_choice:
            st.error("No model selected.")
        else:
            with st.spinner(f"Connecting to {model_choice}..."):
                new_data = run_agent(target_sport, target_conf, model_choice)
                
                if new_data:
                    st.success(f"Found {len(new_data)} coaches!")
                    st.dataframe(new_data)
                    
                    if worksheet:
                        rows = [[target_sport, target_conf, d.get("school"), d.get("coach_name"), d.get("title"), d.get("email")] for d in new_data]
                        try:
                            worksheet.append_rows(rows)
                            st.toast("✅ Saved!")
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Save Error: {e}")
                else:
                    st.warning("No data found.")

with tab2:
    if df_history.empty:
        st.info("Database is empty.")
    else:
        display_df = df_history.copy()
        if selected_filter != "Show All":
            f_conf, f_sport = selected_filter.split(" - ", 1)
            display_df = display_df[
                (display_df["conference"] == f_conf) & 
                (display_df["sport"] == f_sport)
            ]
        st.dataframe(display_df, use_container_width=True)
