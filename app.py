import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
import time

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Athletic Strategy DB", layout="wide", page_icon="🏅")

# --- 2. GOOGLE SHEETS AUTHENTICATION ---
@st.cache_resource
def get_google_sheet():
    """Authenticates and returns the first worksheet of the specified Google Sheet."""
    try:
        # Load credentials from Streamlit Secrets
        creds_info = dict(st.secrets["gcp_service_account"])
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Open by URL from secrets
        sheet = client.open_by_url(st.secrets["SHEET_URL"])
        return sheet.get_worksheet(0) # Returns the first tab
    except Exception as e:
        st.sidebar.error(f"Google Sheets Connection Error: {e}")
        return None

# --- 3. THE AI RESEARCH AGENT (DIRECT REST) ---
def run_research_agent(sport, conference):
    api_key = st.secrets["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{"parts": [{"text": f"Research the 2025 coaching staff for {sport} in the {conference} conference. Return a JSON list: school, coach_name, title, email."}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=90)
        res_data = response.json()
        
        # --- DEBUG WINDOW ---
        with st.expander("🛠️ Debug: Raw AI Response"):
            st.write(res_data)
        
        # 1. Check if the response actually has content
        if 'candidates' not in res_data or not res_data['candidates'][0]['content'].get('parts'):
            st.error("The AI returned an empty response. This often means 'Google Search' is disabled for your API key or billing is required.")
            return None

        raw_output = res_data['candidates'][0]['content']['parts'][0]['text']
        
        # 2. Clean the output (strip markdown if the model ignored our request)
        clean_output = raw_output.strip()
        if clean_output.startswith("```"):
            clean_output = clean_output.split("json")[-1].split("```")[0].strip()
        
        if not clean_output:
            st.warning("The AI found no data for this conference.")
            return []

        return json.loads(clean_output)
        
    except json.JSONDecodeError as e:
        st.error(f"JSON Error: The model gave us text that wasn't a list. Raw text: {raw_output[:100]}...")
        return None
    except Exception as e:
        st.error(f"Research Agent failed: {e}")
        return None
        
# --- 4. STREAMLIT UI ---
st.title("🏆 Athletic Strategy Database")
st.markdown("Automated coaching staff discovery via Gemini 2.0 Search Grounding.")

tab1, tab2 = st.tabs(["🔍 Find New Staff", "📂 Database History"])

with tab1:
    # User Inputs
    col1, col2 = st.columns(2)
    with col1:
        target_sport = st.selectbox("Select Sport", 
            ["Men's Soccer", "Women's Soccer", "Football", "Men's Basketball", "Women's Basketball", "Track & Field"])
    with col2:
        target_conf = st.selectbox("Select Conference", 
            ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "Ivy League"])

    if st.button("🚀 Run Research Agent"):
        if not st.secrets.get("GEMINI_API_KEY"):
            st.error("Missing Gemini API Key in secrets!")
        else:
            with st.spinner(f"Agent is browsing the web for {target_conf} {target_sport} staff..."):
                results = run_research_agent(target_sport, target_conf)
                
                if results:
                    st.success(f"Found {len(results)} staff members!")
                    df = pd.DataFrame(results)
                    st.dataframe(df, use_container_width=True)
                    
                    # Sync to Google Sheets
                    worksheet = get_google_sheet()
                    if worksheet:
                        # Prepare rows for append (Sport, Conference, School, Name, Title, Email)
                        rows_to_add = [
                            [target_sport, target_conf, r.get('school'), r.get('coach_name'), r.get('title'), r.get('email')] 
                            for r in results
                        ]
                        try:
                            worksheet.append_rows(rows_to_add)
                            st.toast("✅ Database synced to Google Sheets!")
                        except Exception as e:
                            st.error(f"Failed to write to Sheet: {e}")
                else:
                    st.warning("No data was returned. The agent may have encountered a search restriction.")

with tab2:
    st.subheader("Current Database Records")
    worksheet = get_google_sheet()
    if worksheet:
        try:
            # Pull existing data
            data = worksheet.get_all_records()
            if data:
                history_df = pd.DataFrame(data)
                st.dataframe(history_df, use_container_width=True)
                
                # Simple CSV Download
                csv = history_df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Database as CSV", data=csv, file_name="athletic_db_export.csv", mime="text/csv")
            else:
                st.info("The database is currently empty.")
        except Exception as e:
            st.error(f"Could not load history: {e}")
    else:
        st.warning("Google Sheets connection is not configured.")

# --- 5. SIDEBAR DIAGNOSTICS ---
with st.sidebar:
    st.header("⚙️ System Status")
    if st.secrets.get("GEMINI_API_KEY"):
        st.write("✅ Gemini API: Connected")
    else:
        st.write("❌ Gemini API: Missing")
        
    if get_google_sheet():
        st.write("✅ Google Sheets: Connected")
    else:
        st.write("❌ Google Sheets: Missing")
    
    st.divider()
    st.caption("v1.2.0 | Gemini 2.0 Flash | Grounding Enabled")
