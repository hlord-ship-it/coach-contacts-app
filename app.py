import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import json
import time

# --- 1. SETUP & AUTHENTICATION ---
try:
    # This looks for the hidden "Secrets" menu in Streamlit Cloud
    creds_dict = dict(st.secrets["gcp_service_account"])
    # Ensure the private key handles newlines correctly
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    # Setup Gemini AI
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    SHEET_URL = st.secrets["SHEET_URL"]
    
except Exception as e:
    st.error(f"⚠️ Setup Required: Please ensure your 'Secrets' are configured in the Streamlit Cloud dashboard. (Error: {e})")
    st.stop()

# Configure the AI Model with Search
model = genai.GenerativeModel('gemini-1.5-pro', 
    tools=[{"google_search_retrieval": {"dynamic_retrieval_config": {"mode": "dynamic", "dynamic_threshold": 0.3}}}])

# --- 2. FUNCTIONS ---
def get_data():
    """Fetch current data from Google Sheet"""
    try:
        sh = client.open_by_url(SHEET_URL)
        # Assuming data is in the first tab
        worksheet = sh.get_worksheet(0)
        return worksheet, pd.DataFrame(worksheet.get_all_records())
    except Exception as e:
        st.error(f"Could not connect to Google Sheet: {e}")
        return None, pd.DataFrame()

def search_conference(conference_name):
    """The Agentic Workflow"""
    prompt = f"""
    Find the 2025-2026 Men's Track & Field Coaching Staff for all schools in the {conference_name} conference.
    
    1. First, search for the list of member schools in this conference.
    2. Then, for EACH school, find the Head Coach and Assistant Coaches.
    3. Return the data as a pure JSON list of objects.
    
    JSON FORMAT:
    [
        {{"school": "School Name", "conference": "{conference_name}", "coach_name": "Name", "title": "Title", "email": "Email or 'Not Listed'"}}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        # Clean up JSON (remove markdown backticks if present)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"Gemini Error: {e}")
        return []

# --- 3. THE APP INTERFACE ---
st.set_page_config(page_title="Coach Finder DB", layout="wide")
st.title("🏃‍♂️ D3 Coach Database Manager")

# Sidebar for controls
with st.sidebar:
    st.header("Controls")
    target_conf = st.selectbox("Select Conference:", 
        ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "MIAC"])
    
    if st.button("Refresh Database"):
        st.rerun()

# Main Area
worksheet, df = get_data()

st.subheader(f"Database View: {target_conf}")

if worksheet is not None and not df.empty:
    # Filter view by selected conference
    if "conference" in df.columns:
        subset = df[df["conference"] == target_conf]
        st.dataframe(subset, use_container_width=True)
        st.caption(f"Showing {len(subset)} coaches for {target_conf}")
    else:
        st.dataframe(df)
else:
    st.info("Database is empty or could not load. Try clicking 'Find Coaches' below to start.")

st.divider()

# The "Action" Section
col1, col2 = st.columns([2, 1])

with col1:
    st.write(f"**Missing data for {target_conf}?**")
    st.write("Click the button to have the AI search Google, verify rosters, and update the sheet automatically.")

with col2:
    if st.button(f"🚀 Find {target_conf} Coaches", type="primary"):
        with st.spinner("Agent is working... (Browsing websites, verifying emails)"):
            new_data = search_conference(target_conf)
            
            if new_data:
                # Prepare rows for Google Sheets (values only)
                rows_to_add = [[d.get("school"), d.get("conference"), d.get("coach_name"), d.get("title"), d.get("email")] for d in new_data]
                
                # Append to Sheet
                worksheet.append_rows(rows_to_add)
                st.success(f"Success! Added {len(new_data)} coaches.")
                time.sleep(2)
                st.rerun()
            else:
                st.error("No data found or AI timed out. Try again.")
