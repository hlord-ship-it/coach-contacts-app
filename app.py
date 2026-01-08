import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
import re
import time

# --- 1. CONFIGURATION & UI SETUP ---
st.set_page_config(page_title="Athletic Strategy DB", layout="wide", page_icon="🏅")

def robust_json_extract(text):
    """Surgically extracts JSON arrays from AI responses, handling markdown or filler text."""
    try:
        # Use regex to find the first '[' and last ']'
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except Exception as e:
        # Fallback: if it's a single object, try finding '{...}'
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return [json.loads(match.group(0))]
        raise ValueError(f"Could not parse JSON from: {text[:100]}...")

# --- 2. GOOGLE SHEETS INTEGRATION ---
@st.cache_resource
def get_worksheet():
    """Connects to Google Sheets using Streamlit Secrets."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_url(st.secrets["SHEET_URL"])
        return sheet.get_worksheet(0)
    except Exception as e:
        st.sidebar.error(f"Sheet Connection Failed: {e}")
        return None

# --- 3. THE RESEARCH ENGINE (GEMINI 2.0 FLASH) ---
def run_research_agent(sport, conference):
    """Calls Gemini 2.0 via REST with Google Search Grounding enabled."""
    api_key = st.secrets["GEMINI_API_KEY"]
    
    # 2.0 Flash is the standard for fast search grounding in 2026
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{
                "text": (
                    f"Find the 2025 coaching staff for {sport} in the {conference} conference. "
                    "Search for every school in the conference. Extract the school name, "
                    "coach name, title (Head or Assistant), and email. "
                    "Return ONLY a valid JSON list of objects."
                )
            }]
        }],
        "tools": [{"google_search": {}}], # Required field for 2.0 Grounding
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "max_output_tokens": 8192
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
        res_json = response.json()
        
        # Check for candidates (Standard Google API structure)
        if 'candidates' in res_json and res_json['candidates'][0]['content'].get('parts'):
            raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
            return robust_json_extract(raw_text)
        else:
            st.error(f"API Error: {res_json}")
            return None
    except Exception as e:
        st.error(f"Agent Request Failed: {e}")
        return None

# --- 4. MAIN APPLICATION UI ---
st.title("🏆 Athletic Strategy Research Agent")
st.markdown("Automated 2025 Staff Discovery Powered by Gemini 2.0 Search Grounding")

tab1, tab2 = st.tabs(["🔍 Search & Extract", "📂 Database View"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        sport = st.selectbox("Sport", ["Men's Soccer", "Women's Soccer", "Football", "Basketball", "Track & Field"])
    with col2:
        conf = st.selectbox("Conference", ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "Ivy League"])

    if st.button("🚀 Execute Research"):
        with st.spinner(f"Agent is searching {conf} directories..."):
            data = run_research_agent(sport, conf)
            
            if data:
                st.success(f"Successfully extracted {len(data)} records!")
                df = pd.DataFrame(data)
                st.dataframe(df, use_container_width=True)
                
                # Automatically Save to Google Sheets
                ws = get_worksheet()
                if ws:
                    rows = [[sport, conf, r.get('school'), r.get('coach_name'), r.get('title'), r.get('email')] for r in data]
                    ws.append_rows(rows)
                    st.toast("✅ Google Sheet Updated!")
            else:
                st.warning("No data returned. Verify your API key has Grounding enabled.")

with tab2:
    ws = get_worksheet()
    if ws:
        records = ws.get_all_records()
        if records:
            st.dataframe(pd.DataFrame(records), use_container_width=True)
        else:
            st.info("The database is currently empty.")

# --- 5. SIDEBAR DIAGNOSTICS ---
with st.sidebar:
    st.header("⚙️ System Status")
    st.write("Model: `Gemini 2.0 Flash`")
    st.write("Tool: `Google Search`")
    if st.secrets.get("GEMINI_API_KEY"): st.write("✅ API Key: Loaded")
    if get_worksheet(): st.write("✅ Google Sheets: Connected")
