import json
import time

import gspread
import pandas as pd
import requests
import streamlit as st
from google.oauth2.service_account import Credentials

# --- PAGE CONFIG ---
st.set_page_config(page_title="Athletic Strategy DB", layout="wide", page_icon="🏅")

# #region agent log
def _log(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    """Write NDJSON logs locally for debug mode. Never log secrets."""
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(
            "/Users/carolyn/Desktop/Crimson Coach Project/.cursor/debug.log", "a"
        ) as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass


_log("A", "app.py:29", "App loaded")
# #endregion

# --- 1. SHEETS AUTH ---
@st.cache_resource
def get_worksheet():
    _log("B", "app.py:36", "Connecting to Google Sheets (no secrets logged)")
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_url(st.secrets["SHEET_URL"])
    ws = sh.sheet1
    _log("B", "app.py:51", "Connected to Google Sheet")
    return ws


def ensure_headers(ws) -> None:
    expected = ["timestamp", "sport", "conference", "school", "coach_name", "title", "email"]
    try:
        current = ws.row_values(1)
        if not current:
            ws.append_row(expected)
            _log("C", "app.py:61", "Headers created", {"cols": len(expected)})
    except Exception as e:
        _log("C", "app.py:64", "Header check failed", {"error": str(e)})


# --- 2. GEMINI VIA RAW HTTP (v1beta) ---
def _extract_json_list(text: str) -> list[dict]:
    """Parse a JSON list from model output; falls back to bracket extraction."""
    if not text:
        return []
    s = text.strip()
    # If the model wraps in code fences, strip them
    s = s.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(s)
        return data if isinstance(data, list) else []
    except Exception:
        start = s.find("[")
        end = s.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(s[start : end + 1])
                return data if isinstance(data, list) else []
            except Exception:
                return []
        return []


def run_agent(sport: str, conference: str) -> list[dict]:
    """Calls Gemini 2.0 Flash with Google Search grounding via raw HTTP."""
    api_key = st.secrets["GEMINI_API_KEY"]

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/gemini-2.0-flash:generateContent?key={api_key}"
    )

    prompt = f"""
You are a research agent. Use live web search.

Task:
- Find the 2025-2026 {sport} coaching staff for every school in the {conference} conference.
- Include Head Coach and Assistants where available.

Return ONLY a strict JSON array (no markdown) where each item is:
{{"school": "...", "coach_name": "...", "title": "...", "email": "Email or Not Listed"}}
"""

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    _log("D", "app.py:132", "Gemini request starting", {"sport": sport, "conference": conference})
    try:
        resp = requests.post(url, json=payload, timeout=90)
        _log("D", "app.py:135", "Gemini response received", {"status": resp.status_code})
    except Exception as e:
        _log("D", "app.py:137", "Gemini request failed", {"error": str(e)})
        raise RuntimeError("API Request Failed (network/request error).") from e

    if resp.status_code != 200:
        # Do NOT leak api_key; show only server message.
        try:
            err = resp.json()
        except Exception:
            err = {"text": resp.text[:500]}
        _log("D", "app.py:146", "Gemini non-200", {"status": resp.status_code, "err": str(err)[:500]})
        raise RuntimeError(f"API Request Failed (HTTP {resp.status_code}). Check Streamlit logs.")

    data = resp.json()
    # Typical response shape: candidates[0].content.parts[0].text
    parts = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])
    )
    text = parts[0].get("text", "") if parts else ""

    results = _extract_json_list(text)
    _log("E", "app.py:163", "Parsed model output", {"items": len(results)})

    # Normalize + validate minimal shape
    cleaned: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        cleaned.append(
            {
                "school": str(r.get("school", "")).strip(),
                "coach_name": str(r.get("coach_name", "")).strip(),
                "title": str(r.get("title", "")).strip(),
                "email": str(r.get("email", "")).strip() or "Not Listed",
            }
        )
    return [c for c in cleaned if c["school"] and c["coach_name"]]


# --- 3. UI ---
st.title("🏆 Athletic Strategy Database Agent")

ws = None
df_history = pd.DataFrame()
try:
    ws = get_worksheet()
    ensure_headers(ws)
    df_history = pd.DataFrame(ws.get_all_records())
except Exception as e:
    _log("B", "app.py:196", "Sheets init failed", {"error": str(e)})
    st.warning("Google Sheet connection failed. Double-check Streamlit Secrets and Sheet sharing.")

tab1, tab2 = st.tabs(["🔍 Research", "📂 History"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        sport = st.selectbox(
            "Sport",
            ["Men's Soccer", "Women's Soccer", "Men's Track & Field", "Women's Track & Field", "Football", "Men's Basketball"],
        )
    with col2:
        conference = st.selectbox("Conference", ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "MIAC"])

    if st.button("🚀 Run Search Agent", type="primary"):
        with st.spinner("Searching Google..."):
            try:
                rows = run_agent(sport, conference)
            except Exception as e:
                st.error(str(e))
                rows = []

        if rows:
            st.success(f"Found {len(rows)} coaches.")
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

            if ws is not None:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                append_rows = [
                    [ts, sport, conference, r["school"], r["coach_name"], r["title"], r["email"]]
                    for r in rows
                ]
                try:
                    ws.append_rows(append_rows)
                    _log("F", "app.py:236", "Appended rows to sheet", {"rows": len(append_rows)})
                    st.toast("✅ Saved to Google Sheet")
                    st.rerun()
                except Exception as e:
                    _log("F", "app.py:241", "Append failed", {"error": str(e)})
                    st.error(f"Error saving to sheet: {e}")
        else:
            st.info("No results returned. Try again or choose a different conference/sport.")

with tab2:
    if df_history.empty:
        st.info("No history yet (or sheet connection failed).")
    else:
        st.dataframe(df_history, use_container_width=True)
