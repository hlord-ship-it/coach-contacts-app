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

# --- 2. AI AGENT (Gemini 2.0 Fix) ---
def run_agent(sport, conference):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        
        # WE ARE USING GEMINI 2.0
        # This is the only model your account seems to have access to (based on previous errors).
        model_name = "gemini-2.0-flash-exp"
        
        # --- THE FIX ---
        # Instead of using 'genai.protos' (which crashed), we use a raw dictionary.
        # We use the key 'google_search' which Gemini 2.0 specifically requested.
        tools = [
            {'google_search': {}} 
        ]
        
        model = genai.GenerativeModel(model_name, tools=tools)
        
    except Exception as e:
        st.error(f"Configuration Error: {e}")
        return []

    st.info(f"🤖 Agent (using {model_name}) is searching Google for {conference} {sport}...")
    
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
        st.caption("If this fails, your API key might not have 'Vertex AI' enabled properly.")
        return []

# --- 3. APP INTERFACE ---

with st.sidebar:
    st.header("🎛️ Settings")
    st.info("Using Model: gemini-2.0-flash-exp")
    
    st.divider()
    
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
        with st.spinner("Connecting..."):
            new_data = run_agent(target_sport, target_conf)
            
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
