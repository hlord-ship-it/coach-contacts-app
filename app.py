import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
import re

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Athletic Strategy DB", layout="wide", page_icon="🏅")

def clean_and_parse_json(text):
    """
    The most robust way to get JSON out of an LLM response.
    Handles markdown fences, leading/trailing text, and encoding issues.
    """
    try:
        # 1. Strip whitespace
        text = text.strip()
        
        # 2. Remove Markdown code blocks if present
        # This regex removes ```json ... ``` or just ``` ... ```
        text = re.sub(r'^```(?:json)?\s+', '', text)
        text = re.sub(r'\s+```$', '', text)
        
        # 3. Find the actual JSON array [ ... ]
        # This ignores any "Sure, here is your list" filler text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            json_str = match.group(0)
            return json.loads(json_str)
        
        # 4. Fallback: try raw parse
        return json.loads(text)
    except Exception as e:
        st.error(f"Extraction Failed. AI output started with: {text[:50]}...")
        raise ValueError(f"JSON Parse Error: {e}")

# --- 2. GOOGLE SHEETS AUTH ---
@st.cache_resource
def get_gsheet():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        scopes = ['[https://www.googleapis.com/auth/spreadsheets](https://www.googleapis.com/auth/spreadsheets)', '[https://www.googleapis.com/auth/drive](https://www.googleapis.com/auth/drive)']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_url(st.secrets["SHEET_URL"]).get_worksheet(0)
    except Exception as e:
        st.sidebar.error(f"Sheet Error: {e}")
        return None

# --- 3. THE RESEARCH ENGINE ---
def run_research_agent(sport, conference):
    api_key = st.secrets["GEMINI_API_KEY"]
    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=){api_key}"
    
    # Force the model to be a data-miner
    prompt = (
        f"Act as a professional athletic directory researcher. "
        f"Find the 2025 coaching staff for {sport} in the {conference} conference. "
        "Visit every member school's athletic website. "
        "Return a JSON list of objects with keys: school, coach_name, title, email. "
        "Output ONLY the JSON array. NO markdown, NO backticks, NO text before or after."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "response_mime_type": "application/json", # This is the magic setting
            "temperature": 0.0,
            "max_output_tokens": 8192
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
        res_data = response.json()
        
        # Debugging: See what the AI actually said in the sidebar
        with st.sidebar.expander("AI Raw Response"):
            st.write(res_data)

        if 'candidates' in res_data:
            raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
            return clean_and_parse_json(raw_text)
        else:
            st.error("Model refused to answer or found no data.")
            return None
    except Exception as e:
        st.error(f"API Request Failed: {e}")
        return None

# --- 4. STREAMLIT UI ---
st.title("🏆 Athletic Strategy Research Agent")

col1, col2 = st.columns(2)
with col1: sport = st.selectbox("Sport", ["Men's Soccer", "Women's Soccer", "Football", "Basketball", "Track & Field"])
with col2: conf = st.selectbox("Conference", ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial"])

if st.button("🚀 Run Search Agent"):
    with st.spinner(f"Agent is searching web for {conf} staff..."):
        data = run_research_agent(sport, conf)
        
        if data:
            st.success(f"Extracted {len(data)} staff members!")
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
            
            # Save to Sheet
            ws = get_gsheet()
            if ws:
                rows = [[sport, conf, r.get('school'), r.get('coach_name'), r.get('title'), r.get('email')] for r in data]
                ws.append_rows(rows)
                st.toast("✅ Google Sheet Updated!")

# --- 5. HISTORY ---
if st.checkbox("Show Database History"):
    ws = get_gsheet()
    if ws:
        st.dataframe(pd.DataFrame(ws.get_all_records()))
