import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
import time
import re

# --- 1. CORE CONFIGURATION ---
st.set_page_config(page_title="NCAA Coach Harvester v2", layout="wide")

# Sport-specific search patterns for better URL targeting
SPORT_SEARCH_PATTERNS = {
    "Men's Soccer": ["men's soccer staff", "men's soccer coaches", "msoc staff"],
    "Women's Soccer": ["women's soccer staff", "women's soccer coaches", "wsoc staff"],
    "Men's Basketball": ["men's basketball staff", "men's basketball coaches"],
    "Women's Basketball": ["women's basketball staff", "women's basketball coaches"],
    "Football": ["football staff", "football coaches"],
    "Men's Track & Field": ["track and field staff", "cross country staff", "track coaches"],
    "Women's Track & Field": ["track and field staff", "cross country staff", "track coaches"],
    "Rowing": ["rowing staff", "rowing coaches", "crew coaches"],
    "Men's Lacrosse": ["men's lacrosse staff", "men's lacrosse coaches"],
    "Women's Lacrosse": ["women's lacrosse staff", "women's lacrosse coaches"],
    "Volleyball": ["volleyball staff", "volleyball coaches"],
    "Swimming": ["swimming staff", "swimming and diving coaches"],
    "Tennis": ["tennis staff", "tennis coaches"],
    "Golf": ["golf staff", "golf coaches"],
    "Field Hockey": ["field hockey staff", "field hockey coaches"],
}

# Known athletics URL patterns by school (fallback database)
KNOWN_ATHLETICS_DOMAINS = {
    "Brown": "brownbears.com",
    "Columbia": "gocolumbialions.com", 
    "Cornell": "cornellbigred.com",
    "Dartmouth": "dartmouthsports.com",
    "Harvard": "gocrimson.com",
    "Penn": "pennathletics.com",
    "Princeton": "goprincetontigers.com",
    "Yale": "yalebulldogs.com",
}

def robust_json_extract(text):
    """Extract JSON from potentially messy LLM output."""
    try:
        # Try direct parse first
        return json.loads(text)
    except:
        pass
    try:
        # Find JSON array pattern
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except:
        pass
    try:
        # Find JSON object pattern and wrap in array
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return [json.loads(match.group(0))]
    except:
        pass
    return None

# --- 2. DYNAMIC MAP LOADING ---
@st.cache_data(ttl=600)
def load_config_from_sheets():
    """Reads the 'Config_Map' tab to build the UI menus."""
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

# --- 3. IMPROVED PIPELINE COMPONENTS ---

def search_for_staff_page(school, sport, status_container=None):
    """
    Multi-strategy search for the correct staff directory URL.
    Returns tuple: (url, confidence_score)
    """
    url = "https://google.serper.dev/search"
    headers = {
        'X-API-KEY': st.secrets["SERPER_API_KEY"], 
        'Content-Type': 'application/json'
    }
    
    # Get sport-specific search terms
    sport_terms = SPORT_SEARCH_PATTERNS.get(sport, [sport.lower() + " staff"])
    
    # Strategy 1: Direct staff page search
    queries = [
        f'site:.edu "{school}" {sport_terms[0]}',  # Most specific
        f'{school} athletics {sport_terms[0]} site:.edu',
        f'{school} {sport} coaching staff',
    ]
    
    # Check if we have a known domain
    for key, domain in KNOWN_ATHLETICS_DOMAINS.items():
        if key.lower() in school.lower():
            queries.insert(0, f'site:{domain} {sport_terms[0]}')
            break
    
    best_url = None
    best_score = 0
    
    for query in queries[:3]:  # Limit to 3 searches to save API calls
        try:
            payload = json.dumps({"q": query, "num": 5})
            res = requests.post(url, headers=headers, data=payload)
            results = res.json().get('organic', [])
            
            for result in results:
                link = result.get('link', '')
                title = result.get('title', '').lower()
                snippet = result.get('snippet', '').lower()
                
                # Score the result
                score = 0
                
                # Must be .edu or known athletics domain
                if '.edu' in link or any(d in link for d in KNOWN_ATHLETICS_DOMAINS.values()):
                    score += 10
                else:
                    continue
                
                # Bonus for staff/coaches in URL
                if 'staff' in link.lower() or 'coaches' in link.lower():
                    score += 20
                
                # Bonus for sport name in URL
                sport_lower = sport.lower().replace("'s", "").replace(" ", "-")
                if sport_lower in link.lower() or sport_lower.replace("-", "") in link.lower():
                    score += 15
                
                # Bonus for "staff" or "coaches" in title
                if 'staff' in title or 'coaches' in title:
                    score += 10
                
                # Penalty for news/recap pages
                if any(x in link.lower() for x in ['news', 'recap', 'schedule', 'roster', 'stats']):
                    score -= 15
                
                # Bonus if email visible in snippet
                if '@' in snippet:
                    score += 25
                
                if score > best_score:
                    best_score = score
                    best_url = link
                    
            if best_score >= 40:  # Good enough, stop searching
                break
                
        except Exception as e:
            if status_container:
                status_container.write(f"⚠️ Search error: {e}")
            continue
    
    return best_url, best_score

def scrape_page_content(url, status_container=None):
    """
    Scrape page content using Jina Reader with retry logic.
    """
    if not url:
        return None
        
    try:
        # Jina Reader API
        jina_url = f"https://r.jina.ai/{url}"
        headers = {
            "Accept": "text/plain",
            "X-Return-Format": "text"
        }
        
        response = requests.get(jina_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            content = response.text
            
            # Check if we got meaningful content
            if len(content) < 500:
                if status_container:
                    status_container.write(f"⚠️ Page content too short ({len(content)} chars)")
                return None
                
            return content
        else:
            if status_container:
                status_container.write(f"⚠️ Jina returned status {response.status_code}")
            return None
            
    except Exception as e:
        if status_container:
            status_container.write(f"⚠️ Scrape error: {e}")
        return None

def extract_coaches_with_gemini(content, school, sport, status_container=None):
    """
    Use Gemini to extract structured coach data from page content.
    Improved prompt with examples and validation.
    """
    if not content:
        return []
    
    api_key = st.secrets["GEMINI_API_KEY"]
    gem_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    # Improved extraction prompt with examples
    prompt = f"""Extract ALL {sport} coaching staff from this {school} athletics page.

INSTRUCTIONS:
1. Find every person listed as a coach, director, or staff member for {sport}
2. Extract their full name, exact title, and email if visible
3. Email format is usually firstname_lastname@school.edu or similar
4. If email is not visible, set email to null (not "None" string)
5. Include head coach, assistant coaches, volunteer coaches, directors

OUTPUT FORMAT - Return ONLY a JSON array:
[
  {{"coach_name": "John Smith", "title": "Head Coach", "email": "jsmith@school.edu"}},
  {{"coach_name": "Jane Doe", "title": "Assistant Coach", "email": null}}
]

PAGE CONTENT:
{content[:15000]}

JSON OUTPUT:"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.1
        }
    }
    
    try:
        response = requests.post(gem_url, json=payload, timeout=60)
        response_data = response.json()
        
        if 'candidates' in response_data:
            text = response_data['candidates'][0]['content']['parts'][0]['text']
            coaches = robust_json_extract(text)
            
            if coaches:
                # Validate and clean the data
                cleaned = []
                for coach in coaches:
                    if isinstance(coach, dict):
                        name = coach.get('coach_name', '').strip()
                        title = coach.get('title', '').strip()
                        email = coach.get('email')
                        
                        # Skip if no name or obviously bad data
                        if not name or name.lower() in ['none', 'null', 'n/a', '']:
                            continue
                        if len(name) < 3:
                            continue
                            
                        # Clean email
                        if email and (email.lower() in ['none', 'null', 'n/a', ''] or '@' not in str(email)):
                            email = None
                            
                        cleaned.append({
                            'school': school,
                            'coach_name': name,
                            'title': title if title and title.lower() not in ['none', 'null'] else 'Staff',
                            'email': email
                        })
                
                return cleaned
                
        return []
        
    except Exception as e:
        if status_container:
            status_container.write(f"⚠️ Extraction error: {e}")
        return []

def harvest_single_school(school, sport, division, conference, status_container=None):
    """
    Complete harvest pipeline for a single school.
    Returns list of coach dictionaries.
    """
    results = []
    
    # Step 1: Find the staff page
    if status_container:
        status_container.write("🔍 Searching for staff directory...")
    
    url, confidence = search_for_staff_page(school, sport, status_container)
    
    if not url:
        if status_container:
            status_container.write("❌ No staff page found")
        return [{
            'school': school,
            'coach_name': None,
            'title': 'NOT FOUND - No staff page',
            'email': None,
            'source_url': None,
            'Division': division,
            'Conference': conference
        }]
    
    if status_container:
        status_container.write(f"✅ Found: {url[:60]}... (confidence: {confidence})")
    
    # Step 2: Scrape the page
    if status_container:
        status_container.write("📄 Scraping page content...")
    
    content = scrape_page_content(url, status_container)
    
    if not content:
        if status_container:
            status_container.write("❌ Could not scrape page")
        return [{
            'school': school,
            'coach_name': None,
            'title': 'NOT FOUND - Scrape failed',
            'email': None,
            'source_url': url,
            'Division': division,
            'Conference': conference
        }]
    
    if status_container:
        status_container.write(f"✅ Got {len(content):,} chars of content")
    
    # Step 3: Extract coach data
    if status_container:
        status_container.write("🤖 Extracting coach data...")
    
    coaches = extract_coaches_with_gemini(content, school, sport, status_container)
    
    if coaches:
        for coach in coaches:
            coach['source_url'] = url
            coach['Division'] = division
            coach['Conference'] = conference
        
        if status_container:
            status_container.write(f"✅ Found {len(coaches)} coaches!")
        return coaches
    else:
        if status_container:
            status_container.write("⚠️ No coaches extracted")
        return [{
            'school': school,
            'coach_name': None,
            'title': 'NOT FOUND - Extraction failed',
            'email': None,
            'source_url': url,
            'Division': division,
            'Conference': conference
        }]

# --- 4. UI LOGIC ---
st.title("🏆 NCAA Coach Harvester v2")
st.caption("Improved search, scraping, and extraction pipeline")

config_df = load_config_from_sheets()

if not config_df.empty:
    col1, col2, col3 = st.columns(3)
    
    with col1:
        divisions = sorted(config_df['Division'].unique())
        selected_div = st.selectbox("Select Division", divisions)
    
    with col2:
        conferences = sorted(config_df[config_df['Division'] == selected_div]['Conference'].unique())
        selected_conf = st.selectbox("Select Conference", conferences)
    
    with col3:
        sports = list(SPORT_SEARCH_PATTERNS.keys())
        selected_sport = st.selectbox("Select Sport", sports)
    
    # Show schools that will be harvested
    target_schools = config_df[
        (config_df['Division'] == selected_div) & 
        (config_df['Conference'] == selected_conf)
    ]['School'].tolist()
    
    with st.expander(f"📋 Schools to harvest ({len(target_schools)})"):
        st.write(", ".join(target_schools))

    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        harvest_all = st.button(f"🚀 Harvest All {len(target_schools)} Schools", type="primary")
    
    with col_btn2:
        # Option to test single school
        test_school = st.selectbox("Or test single school:", [""] + target_schools)
        harvest_single = st.button("🧪 Test Single School")

    # Results container
    if harvest_all or (harvest_single and test_school):
        
        schools_to_process = target_schools if harvest_all else [test_school]
        
        st.divider()
        st.subheader(f"Harvesting {selected_sport} coaches from {selected_conf}")
        
        results_placeholder = st.empty()
        all_results = []
        
        progress = st.progress(0)
        
        for i, school in enumerate(schools_to_process):
            with st.status(f"Processing {school}...", expanded=True) as status:
                coaches = harvest_single_school(
                    school, 
                    selected_sport, 
                    selected_div, 
                    selected_conf,
                    status
                )
                all_results.extend(coaches)
                
                # Update results display
                df = pd.DataFrame(all_results)
                results_placeholder.dataframe(
                    df[['school', 'coach_name', 'title', 'email']], 
                    use_container_width=True,
                    hide_index=True
                )
            
            progress.progress((i + 1) / len(schools_to_process))
            time.sleep(0.5)  # Rate limiting
        
        st.success(f"✅ Harvesting complete! Found {len([r for r in all_results if r.get('coach_name')])} coaches from {len(schools_to_process)} schools.")
        
        # Export options
        st.divider()
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            csv = pd.DataFrame(all_results).to_csv(index=False)
            st.download_button(
                "📥 Download CSV",
                csv,
                f"{selected_conf}_{selected_sport.replace(' ', '_')}_coaches.csv",
                "text/csv"
            )
        
        with col_exp2:
            if st.button("📤 Save to Google Sheet"):
                try:
                    creds_dict = dict(st.secrets["gcp_service_account"])
                    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
                    creds = Credentials.from_service_account_info(
                        creds_dict, 
                        scopes=['https://www.googleapis.com/auth/spreadsheets']
                    )
                    gc = gspread.authorize(creds)
                    sh = gc.open_by_url(st.secrets["SHEET_URL"])
                    
                    # Create or get the output worksheet
                    ws_name = f"{selected_sport.replace(' ', '_')}_Coaches"
                    try:
                        worksheet = sh.worksheet(ws_name)
                    except:
                        worksheet = sh.add_worksheet(title=ws_name, rows=1000, cols=10)
                    
                    # Append data
                    df = pd.DataFrame(all_results)
                    worksheet.append_rows(df.values.tolist())
                    st.success(f"✅ Saved to '{ws_name}' tab!")
                    
                except Exception as e:
                    st.error(f"Error saving: {e}")

else:
    st.error("Could not load Config_Map. Please check your Google Sheets connection.")
    st.info("Make sure you have a 'Config_Map' tab with columns: Division, Conference, School")
