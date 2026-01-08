import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
import re

# --- 1. SETUP & UI ---
st.set_page_config(page_title="Athletic Strategy DB", layout="wide", page_icon="🏅")

def robust_json_extract(text):
    """Ensures we get a clean JSON list even if the AI adds text or markdown."""
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(text)
    except:
        return None

# --- 2. THE EYES: SERPER.DEV SEARCH ---
def get_serper_data(sport, conference):
    """Fetches the top Google results for the specific coaching staff."""
    url = "https://google.serper.dev/search"
    # We target the 'Staff Directory' specifically to get the best snippets
    query = f"2025 {sport} coaching staff directory {conference} conference .edu"
    
    payload = json.dumps({"q": query, "num": 10})
    headers = {
        'X-API-KEY': st.secrets["SERPER_API_KEY"],
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=15)
        response.raise_for_status()
        return response.json().get('organic', [])
    except Exception as e:
        st.error(f"Search failed: {e}")
        return []

# --- 3. THE BRAIN: GEMINI EXTRACTION ---
def extract_coaches(search_hits, sport, conference):
    """Feeds search snippets to Gemini to structure into JSON."""
    api_key = st.secrets["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    # Format the search results into a context block
    context = ""
    for i, hit in enumerate(search_hits):
        context += f"SOURCE {i+1}: {hit.get('link')}\nTITLE: {hit.get('title')}\nSNIPPET: {hit.get('snippet')}\n\n"

    prompt = (
        f"You are a sports data analyst. Based on the search results below, find the 2025 coaching staff "
        f"for {sport} in the {conference}. \n\n"
        "Instructions:\n"
        "1. Identify the School, Coach Name, Title, and Email from the snippets.\n"
        "2. If an email is not in the snippet, check the URL—if it's a staff directory, list the email as 'Visit Source'.\n"
        "3. Return ONLY a JSON list of objects.\n\n"
        f"SEARCH RESULTS:\n{context}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.0}
    }

    try:
        response = requests.post(url, json=payload, timeout=60)
        res_data = response.json()
        raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
        return robust_json_extract(raw_text)
    except Exception as e:
        st.error(f"Extraction failed: {e}")
        return None

# --- 4. GOOGLE SHEETS SYNC ---
def sync_to_sheets(data, sport, conference):
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
        ws = gspread.authorize(creds).open_by_url(st.secrets["SHEET_URL"]).get_worksheet(0)
        
        rows = [[sport, conference, r.get('school'), r.get('coach_name'), r.get('title'), r.get('email')] for r in data]
        ws.append_rows(rows)
        return True
    except Exception as e:
        st.sidebar.error(f"Sheets Sync Error: {e}")
        return False

# --- 5. APP INTERFACE ---
st.title("🏆 Athletic Strategy DB (Serper Mode)")

col1, col2 = st.columns(2)
with col1: sport_input = st.selectbox("Sport", ["Men's Soccer", "Women's Soccer", "Football", "Basketball"])
with col2: conf_input = st.selectbox("Conference", ["NESCAC", "UAA", "SCIAC", "Liberty League", "Ivy League"])

if st.button("🚀 Run Data Pipeline"):
    with st.status("Gathering Intelligence...", expanded=True) as status:
        # Step 1: Deterministic Search
        st.write("🔍 Querying Google via Serper.dev...")
        hits = get_serper_data(sport_input, conf_input)
        
        if not hits:
            status.update(label="Search Failed", state="error")
            st.stop()
            
        # Step 2: Intelligent Extraction
        st.write(f"🧠 Analyzing {len(hits)} sources with Gemini 2.0...")
        extracted_data = extract_coaches(hits, sport_input, conf_input)
        
        if extracted_data:
            st.write(f"✅ Extracted {len(extracted_data)} records.")
            st.dataframe(pd.DataFrame(extracted_data), use_container_width=True)
            
            # Step 3: Database Sync
            st.write("📝 Syncing to Google Sheets...")
            if sync_to_sheets(extracted_data, sport_input, conf_input):
                status.update(label="Pipeline Complete!", state="complete")
                st.toast("Database updated!")
        else:
            status.update(label="Extraction Failed", state="error")
