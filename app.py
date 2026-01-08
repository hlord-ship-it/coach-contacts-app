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
@st.cache_resource
def connect_services():
    try:
        # Load Google Credentials from Secrets
        if "gcp_service_account" not in st.secrets:
            st.error("⚠️ Missing 'gcp_service_account' in Secrets.")
            return None
            
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

# --- 2. SEARCH LOGIC (DuckDuckGo) ---
def search_web(query):
    """Uses DuckDuckGo to find coaching directories."""
    try:
        with DDGS() as ddgs:
            # We fetch 6 results to give the AI enough info
            results = list(ddgs.text(query, max_results=6))
        return str(results)
    except Exception as e:
        st.error(f"Search Engine Error: {e}")
        return ""

# --- 3. AI AGENT ---
def run_agent(sport, conference, model_name):
    """Searches and extracts coach data using the selected AI model."""
    
    # 1. Setup Gemini
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel(model_name)
    except Exception as e:
        st.error(f"Error configuring AI: {e}")
        return []

    # 2. Search Phase
    st.info(f"🔍 Searching: {conference} {sport} staff directory...")
    search_query = f"{conference} {sport} coaching staff directory 2025"
    raw_results = search_web(search_query)
    
    if not raw_results:
        st.warning("No search results found. The internet might be blocking scraping for this query.")
        return []

    # 3. Extraction Phase
    st.info(f"🧠 Analyzing results with {model_name}...")
    
    prompt = f"""
    I have searched for the '{sport}' coaching staff for the '{conference}' conference.
    Here are the raw search snippets:
    {raw_results}
    
    TASK:
    1. Identify the universities in this conference from the snippets.
    2. Extract: School, Coach Name, Title (Head/Assistant), Email.
    3. If Email is not found, write "Not Listed".
    
    OUTPUT:
    Return ONLY a valid JSON list. No markdown formatting.
    [
        {{"sport": "{sport}", "conference": "{conference}", "school": "University Name", "coach_name": "Name", "title": "Title", "email": "Email"}}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        # Clean the response to ensure it is pure JSON
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    
    except Exception as e:
        # Specific error handling for the 404 Model issue
        err_msg = str(e)
        if "404" in err_msg:
            st.error(f"❌ Model Error: The model '{model_name}' was not found. Your API key might not have access to it yet.")
            st.warning("👉 Try switching to 'gemini-2.0-flash-exp' or 'gemini-1.5-pro' in the Sidebar.")
        else:
            st.error(f"AI Processing Error: {e}")
        return []

# --- 4. APP INTERFACE ---

# Sidebar: Controls & Database
with st.sidebar:
    st.header("🎛️ Settings")
    
    # MODEL SELECTOR - Updated for Gemini 3
    model_options = [
        "gemini-3-pro-preview", 
        "gemini-3-flash-preview", 
        "gemini-2.0-flash-exp", 
        "gemini-1.5-pro",
        "gemini-1.5-flash"
    ]
    model_name = st.selectbox("Select AI Model", model_options, index=0)
    
    st.divider()
    
    st.subheader("📚 Saved Reports")
    worksheet = connect_services()
    
    # Load existing data for the "Database" view
    df_history = pd.DataFrame()
    if worksheet:
        try:
            data = worksheet.get_all_records()
            df_history = pd.DataFrame(data)
        except:
            pass # Handle empty sheet gracefully

    # Database Filter Buttons
    selected_filter = "Show All"
    if not df_history.empty and "conference" in df_history.columns:
        # Create unique pairs of Conference-Sport
        pairs = df_history[["conference", "sport"]].drop_duplicates()
        
        # Add a radio button for each saved report
        options = ["Show All"] + [f"{r.conference} - {r.sport}" for i, r in pairs.iterrows()]
        selected_filter = st.radio("Load Database:", options)

# Main Page Layout
st.title("🏆 Athletic Strategy Database")
st.markdown("Use the **Search** tab to find new coaches. Use the **Database** tab to view saved history.")

tab1, tab2 = st.tabs(["🔍 Find New Coaches", "📂 View Database"])

# --- TAB 1: SEARCH ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        target_sport = st.selectbox("Sport", ["Men's Track & Field", "Women's Track & Field", "Men's Soccer", "Women's Soccer", "Football", "Men's Basketball"])
    with col2:
        target_conf = st.selectbox("Conference", ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "Empire 8", "ODAC"])

    if st.button(f"🚀 Find {target_conf} Coaches"):
        new_data = run_agent(target_sport, target_conf, model_name)
        
        if new_data:
            st.success(f"Found {len(new_data)} coaches!")
            st.dataframe(new_data)
            
            # Save to Sheet
            if worksheet:
                # Prepare rows (ensure order matches columns)
                rows = [[d.get("sport"), d.get("conference"), d.get("school"), d.get("coach_name"), d.get("title"), d.get("email")] for d in new_data]
                worksheet.append_rows(rows)
                st.toast("Saved to Database!")
                time.sleep(2)
                st.rerun() # Refresh to show in sidebar

# --- TAB 2: DATABASE ---
with tab2:
    if df_history.empty:
        st.info("Database is empty. Go to 'Find New Coaches' to start.")
    else:
        # Filter Logic
        display_df = df_history.copy()
        if selected_filter != "Show All":
            # Extract filters from the string "Conference - Sport"
            f_conf, f_sport = selected_filter.split(" - ", 1)
            display_df = display_df[
                (display_df["conference"] == f_conf) & 
                (display_df["sport"] == f_sport)
            ]
            st.info(f"Showing saved data for: {selected_filter}")
        
        st.dataframe(display_df, use_container_width=True)
