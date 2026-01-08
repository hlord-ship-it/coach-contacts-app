import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import json
import time

# --- 1. SETUP & AUTHENTICATION ---
try:
    # This looks for the hidden "Secrets" menu we are about to set up
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    
    # Setup Gemini AI
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    SHEET_URL = st.secrets["SHEET_URL"]
    
except Exception as e:
    st.error(f"Waiting for Secrets setup... (Error: {e})")
    st.stop()

# Configure the AI Model
model = genai.GenerativeModel('gemini-1.5-pro', 
    tools=[{"google_search_retrieval": {"dynamic_retrieval_config": {"mode": "dynamic", "dynamic_threshold": 0.3}}}])

# --- 2. FUNCTIONS ---
def get_data():
    try:
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.get_worksheet(0)
        return worksheet, pd.DataFrame(worksheet.get_all_records())
    except Exception as e:
        st.error(f"Connect Error: {e}")
        return None, pd.DataFrame()

def search_conference(conference_name):
    prompt = f"Find 2025-2026 Men's Track staff for {conference_name}. Return JSON list: [{{'school': '...', 'conference': '{conference_name}', 'coach_name': '...', 'title': '...', 'email': '...'}}]"
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"Gemini Error: {e}")
        return []

# --- 3. INTERFACE ---
st.set_page_config(page_title="Coach Finder DB", layout="wide")
st.title("🏃‍♂️ D3 Coach Database Manager")

with st.sidebar:
    target_conf = st.selectbox("Select Conference:", ["NESCAC", "UAA", "SCIAC", "Liberty League", "WIAC", "Centennial", "MIAC"])
    if st.button("Refresh"): st.rerun()

worksheet, df = get_data()
st.subheader(f"Database View: {target_conf}")

if not df.empty:
    subset = df[df["conference"] == target_conf] if "conference" in df.columns else df
    st.dataframe(subset, use_container_width=True)
else:
    st.info("Database is empty or secrets not set.")

if st.button(f"🚀 Find {target_conf} Coaches", type="primary"):
    with st.spinner("Searching..."):
        new_data = search_conference(target_conf)
        if new_data:
            rows = [[d.get("school"), d.get("conference"), d.get("coach_name"), d.get("title"), d.get("email")] for d in new_data]
            worksheet.append_rows(rows)
            st.success("Success!")
            time.sleep(1); st.rerun()---

### Step 2: Launch the App on Streamlit
1.  Go to [share.streamlit.io](https://share.streamlit.io/).
2.  Click **"Continue with GitHub"** and log in with your work account.
3.  Click **"Create app"** (the blue button in the top right).
4.  Select your repository (`hlord-ship-it/coach-contacts-app`), set the branch to `main`, and the file path to `app.py`.
5.  **Before you click Deploy**, look for the **"Advanced settings"** link at the bottom.

---

### Step 3: The Secrets Menu
1.  When you click **Advanced settings**, a text box called **"Secrets"** will appear.
2.  **Copy and paste everything below** into that box:

GEMINI_API_KEY = "AIzaSyBNA7b7G8Km2Tb8eyXw95Q6n7SwIjDtr4k"
SHEET_URL = "https://docs.google.com/spreadsheets/d/11OTvUva_7ghPOioXUvaxjwYOHPpV-jjc4Ow6gLPsYPA/edit"

[gcp_service_account]
type = "service_account"
project_id = "coach-finder-app-483715"
private_key_id = "c033b2533d01888379a236d31d0a72eaf3e990db"
private_key = "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDDOFOFaVX+ztl9\nH965KOUrdtppvQxwnSU7A6Hnz+XG023Gwa1ayg5WETl146Wt4Nm2ykCJGtEmHWaa\naE32aRxvMleq8fADMyp1mu3/6vKhQOQNUB/EZU3UPG++cHQOE6xbypCDaTsEprot\nQ2eEUOykjn4GhdqhVHhEkObif2P9vV/zjd5YTdaQhmE+QYROqM/ciJ2aIbB0YwE2\nbXyeUTgsrPvc6CFLyes3/1TIZNbK4e6q+jIdJFJjhZSl4VffYgscoNrLsShLA54G\npFvQ30BanJeGr77ay4TinDjxUgd592O6bj+srvgDcZRykKqpK+YXZJwFO3pHLyr3\nQF/lRuVxAgMBAAECggEACfNain/SgtDvVAnmU+DKQZtmyaH5utm/tpDaVVMK/sXz\nIADqQajv7yIkoCYw4TqHTmJjxLlJtNwlyTQM2UUFToOt5Ug8uCUJAoKZpARJRr/k\nf+s4G04gl/NWrMnVmIwXKnyaPiCEghmvfrQjWCK51S9wLAvxl2yTTsdmBWCB68J/\nA8+A5Y6zVkW43bRgw7ikIHw+uGd3ytcSevpj5a+Rq0NC+pokDAeVJvB6FH08Syru\nt73LiVN8XcPPaah9OwgqyyzayLS6qTapDxbmATcXiuPyQgHrghhtMWYrOqEGm9Zw\nd45KrkCCKdXG89kxp+j8RPYfhNc7gIGMKAm3jboogwKBgQDvmGs5YSYVL5PpkNwa\np5FlyoyPeU5bfOHHzjwLoZyzp6CJ58a5QOgSBre2bhSLPlYcznSfHenGB9GMbm3m\nKXRokw5mz2ax5KKHwULIvGzG6t0vpNjzY5FHq69p7peayenffdUmYP6TvNtJ85Fa\nSh3uZb/y1+EQKcuIBh/2H9+3lwKBgQDQlhrPzMTAMWP0I3jrMmvqk+3wRHJL8EXs\nHdQb9FrAJ6K1VJIMfRjby+GnZfnxn/6DX6TIIl0/0ZfRFHl39G6gGN5dB1NJJrWE\npRoRDzqCyZClnYsdxVLkwKYt8FrD/Fbo5cAgV76dMHt8JWZF5xI+0MPt9cX77vHI\nS4cPHausNwKBgAxeKtLIcAXR8emxn5sEoV3GyeCyG1hfpuwAelsDWapwcboMq9Zu\nQkyD6kHRht/1NM7B3YVFLwcY6jk8jhG+fBLV3H10IVH3gmhNkpv4FglioE5QTR6r\nOhmgBCsMtOi5mYf+39zeTuXjbtJvb0Zg4xCmUfVALY7/CVGZN1cmKA87AoGAB9uv\n1OZM/0SdFGSFuK6knCjIjQW3HJ9HsxaImCkDhju4CIbQHcJUvmsW7DyORwkVCJQA\n3D1XMAFQa+MOlHNT+5oUPoL5I0dfDUk/Cyd8t9KqLWMbC5sUfWO4nwBwGvQVvh5x\nt4Y2uytJa6rpCHclG9K3nu5kcBJXb4lQ5EPk5M8CgYBPFWx6GRdHxxSb2PaWmpzd\n23LLC6lfed37kqIwaf6vK8EOOnu7oCclQgoEugM0cgADfO6qODnDADEZzkkApYhM\nDjD+xe8p4LJu8mo73XsF/3mU85AfxuKGej58Meduhhcrmnue9VuL+l5WL8P8cVhV\npN1OfoctZMP1nLFgoqelgQ==\n-----END PRIVATE KEY-----\n"
client_email = "data-bot@coach-finder-app-483715.iam.gserviceaccount.com"
client_id = "116014310838930128813"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/data-bot%40coach-finder-app-483715.iam.gserviceaccount.com"3.  Click **Save**.
4.  Now click **Deploy!**

Streamlit will now install the software, connect to your Google Sheet using those "Secrets," and give you a live URL you can send to your colleagues. No more security warnings
