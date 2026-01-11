import streamlit as st
import anthropic
import json
import time
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="NCAA Coach Finder", page_icon="🏆", layout="wide")

SPORTS = [
    "Men's Soccer", "Women's Soccer",
    "Men's Basketball", "Women's Basketball",
    "Men's Track & Field", "Women's Track & Field",
    "Men's Cross Country", "Women's Cross Country",
    "Men's Rowing", "Women's Rowing",
    "Men's Lacrosse", "Women's Lacrosse",
    "Men's Swimming & Diving", "Women's Swimming & Diving",
    "Men's Tennis", "Women's Tennis",
    "Men's Golf", "Women's Golf",
    "Women's Volleyball", "Women's Field Hockey", 
    "Football", "Baseball", "Softball"
]

# --- LOAD CONFERENCE MAP FROM GOOGLE SHEETS ---
@st.cache_data(ttl=600)
def load_conference_map():
    """Load Config_Map from Google Sheets."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(
            creds_dict, 
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(st.secrets["SHEET_URL"])
        worksheet = sh.worksheet("Config_Map")
        df = pd.DataFrame(worksheet.get_all_records())
        return df
    except Exception as e:
        st.error(f"Error loading Config_Map: {e}")
        return pd.DataFrame()


# --- CORE SEARCH FUNCTION ---
def find_coaches(school: str, sport: str, division: str, conference: str) -> dict:
    """Use Claude with web search to find coaching staff contacts."""
    
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    
    prompt = f"""Find the {sport} coaching staff contacts for {school}.

Search query to use: {school} {sport} coaches staff directory contacts email

Find ALL coaches/staff for {sport} at {school}. For each person, get:
- Full name
- Title (Head Coach, Assistant Coach, Director of Operations, etc.)
- Email address  
- Phone number (if listed)

Return ONLY this JSON format:
{{
    "school": "{school}",
    "sport": "{sport}",
    "division": "{division}",
    "conference": "{conference}",
    "source_url": "URL where you found this info",
    "coaches": [
        {{"name": "John Smith", "title": "Head Coach", "email": "jsmith@school.edu", "phone": "555-123-4567"}},
        {{"name": "Jane Doe", "title": "Assistant Coach", "email": "jdoe@school.edu", "phone": null}}
    ]
}}

Important:
- Use null for missing email/phone (not "None" or "N/A")  
- Only include real coaches from official athletics pages
- Include head coach, all assistants, volunteer coaches, directors of operations
- Most .edu athletics sites list emails on staff pages"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Extract JSON from response
        for block in response.content:
            if hasattr(block, 'text'):
                text = block.text
                start = text.find('{')
                end = text.rfind('}') + 1
                if start != -1 and end > start:
                    data = json.loads(text[start:end])
                    data['tokens'] = response.usage.input_tokens + response.usage.output_tokens
                    data['status'] = 'success'
                    return data
        
        return {"status": "error", "error": "Could not parse response", "school": school, "sport": sport}
        
    except Exception as e:
        return {"status": "error", "error": str(e), "school": school, "sport": sport}


# --- SAVE TO GOOGLE SHEETS ---
def save_to_sheets(results_df: pd.DataFrame, sport: str, conference: str):
    """Append results to the main sheet (Sheet1)."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(
            creds_dict, 
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(st.secrets["SHEET_URL"])
        
        # Use Sheet1 as the main output
        worksheet = sh.worksheet("Sheet1")
        
        # Format data for Sheet1 columns: timestamp, sport, conference, school, coach_name, title, email
        rows_to_add = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for _, row in results_df.iterrows():
            rows_to_add.append([
                timestamp,
                sport,
                conference,
                row.get('school', ''),
                row.get('name', ''),
                row.get('title', ''),
                row.get('email', '')
            ])
        
        if rows_to_add:
            worksheet.append_rows(rows_to_add)
        
        return True, len(rows_to_add)
        
    except Exception as e:
        return False, str(e)


# --- UI ---
st.title("🏆 NCAA Coach Finder")
st.caption("Find coaching staff contacts by conference • Powered by Claude AI web search")

# Check secrets
missing_secrets = []
if "ANTHROPIC_API_KEY" not in st.secrets:
    missing_secrets.append("ANTHROPIC_API_KEY")
if "gcp_service_account" not in st.secrets:
    missing_secrets.append("gcp_service_account")
if "SHEET_URL" not in st.secrets:
    missing_secrets.append("SHEET_URL")

if missing_secrets:
    st.error(f"⚠️ Missing secrets: {', '.join(missing_secrets)}")
    with st.expander("How to configure secrets"):
        st.code('''
# In Streamlit Cloud → Settings → Secrets, add:

ANTHROPIC_API_KEY = "sk-ant-api03-xxxxx"
SHEET_URL = "https://docs.google.com/spreadsheets/d/xxxxx"

[gcp_service_account]
type = "service_account"
project_id = "your-project"
private_key_id = "xxxxx"
private_key = "-----BEGIN PRIVATE KEY-----\\nxxxxx\\n-----END PRIVATE KEY-----\\n"
client_email = "xxxxx@xxxxx.iam.gserviceaccount.com"
client_id = "xxxxx"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
        ''', language="toml")
    st.stop()

# Load conference data
config_df = load_conference_map()

if config_df.empty:
    st.error("❌ Could not load Config_Map from Google Sheets")
    st.stop()

st.success(f"✅ Loaded {len(config_df)} schools across {config_df['Conference'].nunique()} conferences")

# --- SELECTION UI ---
st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    divisions = sorted(config_df['Division'].unique())
    selected_div = st.selectbox("1️⃣ Select Division", divisions)

with col2:
    conferences = sorted(config_df[config_df['Division'] == selected_div]['Conference'].unique())
    selected_conf = st.selectbox("2️⃣ Select Conference", conferences)

with col3:
    selected_sport = st.selectbox("3️⃣ Select Sport", SPORTS)

# Get schools for this conference
schools = sorted(config_df[
    (config_df['Division'] == selected_div) & 
    (config_df['Conference'] == selected_conf)
]['School'].tolist())

# Preview schools
with st.expander(f"📋 Schools in {selected_conf} ({len(schools)})", expanded=False):
    cols = st.columns(3)
    for i, school in enumerate(schools):
        cols[i % 3].write(f"• {school}")

# Cost estimate
cost_per_school = 0.01
estimated_cost = len(schools) * cost_per_school

st.info(f"🎯 **{len(schools)} schools** in {selected_conf} • Estimated cost: **${estimated_cost:.2f}**")

# --- ACTION BUTTONS ---
st.divider()

col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 1])

with col_btn1:
    harvest_all = st.button(
        f"🚀 Harvest All {len(schools)} Schools",
        type="primary",
        use_container_width=True
    )

with col_btn2:
    test_school = st.selectbox("Test single:", [""] + schools, label_visibility="collapsed")

with col_btn3:
    test_single = st.button("🧪 Test One", use_container_width=True, disabled=not test_school)

# --- HARVEST EXECUTION ---
if harvest_all or test_single:
    
    schools_to_search = schools if harvest_all else [test_school]
    
    st.divider()
    st.subheader(f"🔍 Finding {selected_sport} Coaches in {selected_conf}")
    
    # Results storage
    all_coaches = []
    errors = []
    total_tokens = 0
    
    # Progress tracking
    progress_bar = st.progress(0)
    status_text = st.empty()
    results_table = st.empty()
    
    for i, school in enumerate(schools_to_search):
        status_text.markdown(f"**Searching:** {school} ({i+1}/{len(schools_to_search)})")
        
        # Call Claude
        result = find_coaches(school, selected_sport, selected_div, selected_conf)
        
        if result.get('status') == 'success':
            coaches = result.get('coaches', [])
            total_tokens += result.get('tokens', 0)
            
            for coach in coaches:
                coach['school'] = school
                coach['division'] = selected_div
                coach['conference'] = selected_conf
                coach['source_url'] = result.get('source_url', '')
                all_coaches.append(coach)
            
            status_text.markdown(f"✅ **{school}**: Found {len(coaches)} coaches")
        else:
            errors.append({"school": school, "error": result.get('error', 'Unknown error')})
            status_text.markdown(f"❌ **{school}**: {result.get('error', 'Error')[:50]}")
        
        # Update results table
        if all_coaches:
            df_display = pd.DataFrame(all_coaches)[['school', 'name', 'title', 'email']]
            results_table.dataframe(df_display, use_container_width=True, hide_index=True)
        
        # Update progress
        progress_bar.progress((i + 1) / len(schools_to_search))
        
        # Rate limiting
        if i < len(schools_to_search) - 1:
            time.sleep(0.5)
    
    # --- RESULTS SUMMARY ---
    st.divider()
    
    # Calculate cost
    estimated_actual_cost = (total_tokens * 0.8 / 1_000_000 * 3) + (total_tokens * 0.2 / 1_000_000 * 15)
    
    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
    col_stat1.metric("Schools Searched", len(schools_to_search))
    col_stat2.metric("Coaches Found", len(all_coaches))
    col_stat3.metric("Tokens Used", f"{total_tokens:,}")
    col_stat4.metric("Cost", f"${estimated_actual_cost:.4f}")
    
    if errors:
        with st.expander(f"⚠️ {len(errors)} Errors", expanded=False):
            for err in errors:
                st.write(f"• **{err['school']}**: {err['error']}")
    
    # --- EXPORT OPTIONS ---
    if all_coaches:
        st.divider()
        st.subheader("📤 Export Results")
        
        results_df = pd.DataFrame(all_coaches)
        
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            # Download CSV
            csv = results_df.to_csv(index=False)
            filename = f"{selected_conf}_{selected_sport.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv"
            st.download_button(
                "📥 Download CSV",
                csv,
                filename,
                "text/csv",
                use_container_width=True
            )
        
        with col_exp2:
            # Save to Google Sheets
            if st.button("📊 Save to Google Sheet", use_container_width=True):
                success, result = save_to_sheets(results_df, selected_sport, selected_conf)
                if success:
                    st.success(f"✅ Saved {result} rows to Sheet1!")
                else:
                    st.error(f"❌ Error: {result}")

# --- SIDEBAR ---
with st.sidebar:
    st.header("ℹ️ How It Works")
    st.markdown("""
    1. Select Division → Conference → Sport
    2. Click "Harvest" to search all schools
    3. Claude AI searches the web for each school
    4. Results auto-save to Google Sheets
    
    **Cost:** ~$0.01 per school
    """)
    
    st.divider()
    
    st.header("📊 Quick Stats")
    st.metric("Total Schools", len(config_df))
    st.metric("D1 Schools", len(config_df[config_df['Division'] == 'D1']))
    st.metric("D2 Schools", len(config_df[config_df['Division'] == 'D2']))
    st.metric("D3 Schools", len(config_df[config_df['Division'] == 'D3']))
    
    st.divider()
    
    st.caption("Built for Crimson Athletics 🏆")
