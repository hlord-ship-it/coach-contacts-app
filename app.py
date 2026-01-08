import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
import time
import re

# --- 1. CORE CONFIGURATION ---
st.set_page_config(page_title="Global Athletic Harvester", layout="wide")

def robust_json_extract(text):
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match: return json.loads(match.group(0))
        return json.loads(text)
    except: return None

# --- 2. DYNAMIC MAP LOADING ---
@st.cache_data(ttl=600) # Refreshes every 10 minutes
def load_config_from_sheets():
    """Reads the 'Config_Map' tab to build the UI menus."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        gc = gspread.authorize(creds)
        
        # Access the 'Config_Map' tab
        sh = gc.open_by_url(st.secrets["SHEET_URL"])
        worksheet = sh.worksheet("Config_Map")
        df = pd.DataFrame(worksheet.get_all_records())
        return df
    except Exception as e:
        st.error(f"Error loading Config_Map: {e}")
        return pd.DataFrame()

# --- 3. PIPELINE COMPONENTS ---
def get_school_directory_url(school, sport):
    """Search for the specific directory URL."""
    url = "https://google.serper.dev/search"
    query = f"{school} {sport} coaching staff directory .edu"
    headers = {'X-API-KEY': st.secrets["SERPER_API_KEY"], 'Content-Type': 'application/json'}
    payload = json.dumps({"q": query, "num": 3})
    
    res = requests.post(url, headers=headers, data=payload)
    results = res.json().get('organic', [])
    return results[0].get('link') if results else None

def scrape_and_extract(url, school, sport):
    """Scrapes via Jina and extracts via Gemini."""
    # Scrape
    jina_text = requests.get(f"https://r.jina.ai/{url}").text
    
    # Extract
    api_key = st.secrets["GEMINI_API_KEY"]
    gem_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    prompt = (
        f"Extract a JSON list of {sport} coaches for {school} from this text. "
        "Keys: school, coach_name, title, email. \n\n"
        f"TEXT:\n{jina_text[:12000]}"
    )
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0}
    }
    
    res = requests.post(gem_url, json=payload)
    try:
        return robust_json_extract(res.json()['candidates'][0]['content']['parts'][0]['text'])
    except: return []

# --- 4. UI LOGIC ---
st.title("🏆 NCAA Master Harvester")

config_df = load_config_from_sheets()

if not config_df.empty:
    # 1. Select Division
    divisions = sorted(config_df['Division'].unique())
    selected_div = st.selectbox("Select Division", divisions)
    
    # 2. Select Conference (Filtered by Division)
    conferences = sorted(config_df[config_df['Division'] == selected_div]['Conference'].unique())
    selected_conf = st.selectbox("Select Conference", conferences)
    
    # 3. Select Sport
    selected_sport = st.selectbox("Select Sport", ["Men's Soccer", "Women's Soccer", "Football", "Basketball", "Lacrosse"])

    if st.button(f"🚀 Harvest {selected_conf} Data"):
        # Get list of schools for this selection
        target_schools = config_df[
            (config_df['Division'] == selected_div) & 
            (config_df['Conference'] == selected_conf)
        ]['School'].tolist()
        
        st.write(f"Starting harvest for **{len(target_schools)} schools**...")
        
        results_area = st.empty()
        all_data = []
        
        progress = st.progress(0)
        for i, school in enumerate(target_schools):
            with st.status(f"Processing {school}...", expanded=False):
                dir_url = get_school_directory_url(school, selected_sport)
                if dir_url:
                    data = scrape_and_extract(dir_url, school, selected_sport)
                    if data:
                        for entry in data: 
                            entry['Division'] = selected_div
                            entry['Conference'] = selected_conf
                        all_data.extend(data)
                        results_area.dataframe(pd.DataFrame(all_data), use_container_width=True)
            
            progress.progress((i + 1) / len(target_schools))
            time.sleep(1) # Safety delay
            
        st.success("Harvesting Complete!")
