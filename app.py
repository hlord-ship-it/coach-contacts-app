import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from duckduckgo_search import DDGS
import json
import time

# --- 1. SETUP & AUTHENTICATION ---
try:
    # Google Sheets Auth
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    # Gemini Auth
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    SHEET_URL = st.secrets["SHEET_URL"]
    
except Exception as e:
    st.error(f"⚠️ Secrets Error: {e}")
    st.stop()

# Use the 'Flash' model - it's faster and more stable for this
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. FUNCTIONS ---
def get_data():
    """Fetch current data from Google Sheet"""
    try:
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(0)
        # Check if sheet is empty
        if not worksheet.get_all_values():
            return worksheet, pd.DataFrame()
        return worksheet, pd.DataFrame(worksheet.get_all_records())
    except Exception as e:
        return None, pd.DataFrame()

def search_web(query):
    """Uses DuckDuckGo to find live info (bypasses Google Permission errors)"""
    try:
        results = DDGS().text(query, max_results=5)
        return str(results)
    except Exception as e:
        return ""

def search_conference(conference_name):
    """The Agent Workflow"""
    
    # 1. Search Phase
    status_text = st.empty()
    status_text.info(f"🔍 Searching web for {conference_name} rosters...")
    
    search_query = f"{conference_name} men's track and field coaching staff directory 2025"
    search_results = search_web(search_query)
    
    # 2. Extract Phase
    status_text.info("🧠 AI is analyzing the search results...")
    
    prompt = f"""
    I have performed a search for the {conference_name} Men's Track Coaching Staff.
    Here are the raw search results:
    {search_results}
    
    Based ONLY on these results:
    1. Identify the schools and their coaches.
    2. Return a JSON list.
    
    JSON SCHEMA:
    [
        {{"school": "School Name", "conference": "{conference_name}", "coach_name": "Name", "title": "Title", "email": "Email (or 'Not Listed')"}}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        status_text.empty() # Clear status
        return data
    except Exception as e:
        st.error(f"AI Processing Error: {e}")
        return []

# --- 3. THE APP INTERFACE ---
st.set_page_config(page_title="Coach DB", layout="wide", page_icon="🏃‍♂️")

st.title("🏃‍♂️ D3 Coach Database Manager")
st.markdown("Use this tool to find coach emails by conference and save them to your master database.")

# Sidebar
with st.sidebar:
    st.header("Settings")
    target_conf = st.selectbox("Select Conference:", 
        ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "MIAC"])
    
    if st.button("🔄 Refresh Table"):
        st.rerun()

# Main Display
worksheet, df = get_data()

st.subheader(f"📍 Database View: {target_conf}")

if worksheet is not None and not df.empty and "conference" in df.columns:
    subset = df[df["conference"] == target_conf]
    if not subset.empty:
        st.dataframe(subset, use_container_width=True)
        st.success(f"Found {len(subset)} records.")
    else:
        st.info(f"No coaches found for {target_conf} yet.")
else:
    st.info("Database is currently empty. Run a search below to fill it!")

st.divider()

# Action Button
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown(f"**Want to find coaches for {target_conf}?**")
    st.caption("This will browse the web, find the 2025 rosters, and add them to the sheet.")
with col2:
    if st.button(f"🚀 Find {target_conf} Coaches", type="primary"):
        new_data = search_conference(target_conf)
        
        if new_data:
            rows_to_add = [[d.get("school"), d.get("conference"), d.get("coach_name"), d.get("title"), d.get("email")] for d in new_data]
            worksheet.append_rows(rows_to_add)
            st.balloons()
            st.success(f"Added {len(new_data)} coaches!")
            time.sleep(2)
            st.rerun()
        else:
            st.warning("No data found. Try again or check the conference name.")
