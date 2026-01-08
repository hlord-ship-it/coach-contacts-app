import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from duckduckgo_search import DDGS
import json
import time

# --- PAGE CONFIG ---
st.set_page_config(page_title="Athletic Strategy DB", layout="wide", page_icon="🏅")

# --- 1. SETUP & AUTHENTICATION ---
# We wrap this in a function to prevent constant reloading
@st.cache_resource
def connect_services():
    try:
        # Google Sheets Auth
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Connect to Sheet
        sheet_url = st.secrets["SHEET_URL"]
        return client.open_by_url(sheet_url).sheet1
        
    except Exception as e:
        st.error(f"⚠️ Connection Error: {e}")
        return None

# --- 2. SEARCH LOGIC ---
def search_web(query):
    """Bypasses Google Search API permission issues by using DuckDuckGo"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6))
        return str(results)
    except Exception as e:
        st.error(f"Search Engine Error: {e}")
        return ""

def run_agent(sport, conference, model_name):
    """The AI Worker"""
    
    # 1. Setup Gemini with user-selected model
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel(model_name)
    except Exception as e:
        st.error(f"Error configuring AI Model '{model_name}': {e}")
        return []

    # 2. Search Phase
    st.info(f"🔍 Searching the web for {conference} {sport} coaches...")
    search_query = f"{conference} {sport} coaching staff directory 2025"
    raw_results = search_web(search_query)
    
    if not raw_results:
        st.error("Could not find search results. Try again.")
        return []

    # 3. Analysis Phase
    st.info("🧠 Analyzing rosters and extracting emails...")
    
    prompt = f"""
    I have searched for the '{sport}' coaching staff for the '{conference}' conference.
    Here are the raw search snippets:
    {raw_results}
    
    TASK:
    1. Identify the universities in this conference mentioned in the results.
    2. Extract the Coach Name, Title (Head/Assistant), and Email if visible.
    3. If Email is not found, put "Not Listed".
    
    OUTPUT FORMAT:
    Return ONLY a pure JSON list. Do not write markdown.
    [
        {{"sport": "{sport}", "conference": "{conference}", "school": "University Name", "coach_name": "Name", "title": "Title", "email": "Email"}}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        # Clean text to ensure valid JSON
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"AI Processing Error (Model: {model_name}): {e}")
        return []

# --- 3. THE APP INTERFACE ---

# Sidebar: Controls & History
with st.sidebar:
    st.title("🎛️ Controls")
    
    # Model Selector (Fixes the 404 Error by letting you choose)
    model_name = st.text_input("AI Model Name", value="gemini-1.5-flash", help="If you get a 404 error, try: gemini-1.5-pro, gemini-2.0-flash-exp")
    
    st.divider()
    
    st.subheader("📚 Saved Reports")
    # Load data to show history
    worksheet = connect_services()
    if worksheet:
        all_data = worksheet.get_all_records()
        df = pd.DataFrame(all_data)
        
        # Show existing Sport/Conference combos
        if not df.empty and "conference" in df.columns and "sport" in df.columns:
            # Create unique list of existing reports
            existing_reports = df[["sport", "conference"]].drop_duplicates()
            
            # Create clickable filters
            selected_report = st.radio(
                "View Database:",
                options=["Show All"] + [f"{r.conference} - {r.sport}" for i, r in existing_reports.iterrows()],
                index=0
            )
        else:
            selected_report = "Show All"
            st.caption("No reports saved yet.")

# Main Page
st.title("🏆 Athletic Strategy Database")

tab1, tab2 = st.tabs(["🔍 Find New Coaches", "📂 View Database"])

# TAB 1: SEARCH TOOL
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        target_sport = st.selectbox("Select Sport", ["Men's Track & Field", "Women's Track & Field", "Men's Soccer", "Women's Soccer", "Football", "Men's Basketball"])
    with col2:
        # Common D3 conferences, editable
        target_conf = st.selectbox("Select Conference", ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "MIAC", "ODAC", "Empire 8"], index=0)

    if st.button(f"🚀 Find {target_conf} - {target_sport} Coaches", type="primary"):
        with st.spinner("Agent is working..."):
            new_data = run_agent(target_sport, target_conf, model_name)
            
            if new_data:
                st.success(f"Found {len(new_data)} coaches!")
                
                # Show preview
                st.dataframe(new_data)
                
                # Save to Sheet
                if worksheet:
                    rows_to_add = [[d["sport"], d["conference"], d["school"], d["coach_name"], d["title"], d["email"]] for d in new_data]
                    worksheet.append_rows(rows_to_add)
                    st.toast("✅ Saved to Database!")
                    time.sleep(1)
                    st.rerun()

# TAB 2: DATABASE VIEW
with tab2:
    if worksheet and not df.empty:
        # Filter Logic
        display_df = df.copy()
        
        if selected_report != "Show All":
            # Parse the string "NESCAC - Men's Track" back to filters
            f_conf, f_sport = selected_report.split(" - ", 1)
            display_df = display_df[
                (display_df["conference"] == f_conf) & 
                (display_df["sport"] == f_sport)
            ]
            st.info(f"Showing filter: {selected_report}")
        
        st.dataframe(display_df, use_container_width=True)
        st.caption(f"Total Records: {len(display_df)}")
    else:
        st.info("Database is empty. Go to the 'Find New Coaches' tab to start building.")
