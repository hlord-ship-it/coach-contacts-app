import streamlit as st
import anthropic
import json
import time
import pandas as pd
from datetime import datetime

# --- CONFIG ---
st.set_page_config(page_title="Coach Finder", page_icon="🏆", layout="wide")

# Sports list
SPORTS = [
    "Men's Soccer", "Women's Soccer",
    "Men's Basketball", "Women's Basketball",
    "Men's Track & Field", "Women's Track & Field",
    "Men's Rowing", "Women's Rowing",
    "Men's Lacrosse", "Women's Lacrosse",
    "Men's Swimming", "Women's Swimming",
    "Men's Tennis", "Women's Tennis",
    "Men's Golf", "Women's Golf",
    "Volleyball", "Field Hockey", "Football"
]

# --- CORE FUNCTION ---
def find_coaches(school: str, sport: str) -> dict:
    """
    Use Claude with web search to find coaching staff.
    """
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    
    prompt = f"""Find the {sport} coaching staff contacts for {school}.

Search for: {school} {sport} coaches staff directory contacts

I need for each coach:
- Full name
- Title (Head Coach, Assistant Coach, etc.)
- Email address
- Phone number (if available)

Return ONLY valid JSON:
{{
    "school": "{school}",
    "sport": "{sport}",
    "source_url": "URL where you found this",
    "coaches": [
        {{"name": "Full Name", "title": "Head Coach", "email": "email@school.edu", "phone": "555-123-4567"}}
    ]
}}

Use null for missing email/phone. Only include real coaches you found."""

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
                    return data
        
        return {"error": "Could not parse response"}
        
    except Exception as e:
        return {"error": str(e)}


# --- UI ---
st.title("🏆 Coach Finder")
st.caption("Find coaching staff contacts instantly using AI web search")

# Check API key
if "ANTHROPIC_API_KEY" not in st.secrets:
    st.error("⚠️ ANTHROPIC_API_KEY not found in secrets!")
    st.stop()

# Tabs for different modes
tab1, tab2 = st.tabs(["🔍 Quick Search", "📋 Batch Search"])

# --- TAB 1: QUICK SEARCH ---
with tab1:
    col1, col2 = st.columns(2)
    
    with col1:
        school = st.text_input("School Name", placeholder="e.g., Harvard, Stanford, Ohio State")
    
    with col2:
        sport = st.selectbox("Sport", SPORTS)
    
    if st.button("🔍 Find Coaches", type="primary", disabled=not school):
        with st.spinner(f"Searching for {school} {sport} coaches..."):
            result = find_coaches(school, sport)
        
        if "error" in result:
            st.error(f"Error: {result['error']}")
        else:
            st.success(f"Found {len(result.get('coaches', []))} coaches!")
            
            # Show source
            if result.get('source_url'):
                st.caption(f"Source: {result['source_url']}")
            
            # Display coaches
            coaches = result.get('coaches', [])
            if coaches:
                df = pd.DataFrame(coaches)
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                # Download button
                csv = df.to_csv(index=False)
                st.download_button(
                    "📥 Download CSV",
                    csv,
                    f"{school.replace(' ', '_')}_{sport.replace(' ', '_')}_coaches.csv",
                    "text/csv"
                )
            
            # Show cost
            tokens = result.get('tokens', 0)
            cost = (tokens * 0.8 / 1_000_000 * 3) + (tokens * 0.2 / 1_000_000 * 15)
            st.caption(f"Tokens used: {tokens:,} (~${cost:.4f})")


# --- TAB 2: BATCH SEARCH ---
with tab2:
    st.subheader("Search Multiple Schools")
    
    # Input methods
    input_method = st.radio("Input method:", ["Enter schools", "Paste list"], horizontal=True)
    
    if input_method == "Enter schools":
        schools_input = st.text_area(
            "Schools (one per line)", 
            placeholder="Harvard\nYale\nPrinceton\nColumbia",
            height=150
        )
        schools = [s.strip() for s in schools_input.split('\n') if s.strip()]
    else:
        schools_input = st.text_input(
            "Paste comma-separated list",
            placeholder="Harvard, Yale, Princeton, Columbia"
        )
        schools = [s.strip() for s in schools_input.split(',') if s.strip()]
    
    batch_sport = st.selectbox("Sport", SPORTS, key="batch_sport")
    
    if schools:
        st.info(f"Will search {len(schools)} schools. Estimated cost: ~${len(schools) * 0.01:.2f}")
    
    if st.button("🚀 Search All", type="primary", disabled=not schools):
        
        all_coaches = []
        progress = st.progress(0)
        status = st.empty()
        results_area = st.empty()
        
        for i, school in enumerate(schools):
            status.text(f"Searching {school}... ({i+1}/{len(schools)})")
            
            result = find_coaches(school, batch_sport)
            
            if "error" not in result:
                for coach in result.get('coaches', []):
                    coach['school'] = school
                    coach['source_url'] = result.get('source_url')
                    all_coaches.append(coach)
            
            # Update display
            if all_coaches:
                df = pd.DataFrame(all_coaches)
                results_area.dataframe(df, use_container_width=True, hide_index=True)
            
            progress.progress((i + 1) / len(schools))
            time.sleep(0.5)  # Rate limiting
        
        status.text("")
        st.success(f"✅ Complete! Found {len(all_coaches)} total coaches.")
        
        # Download all
        if all_coaches:
            df = pd.DataFrame(all_coaches)
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download All Results",
                csv,
                f"coaches_{batch_sport.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv"
            )


# --- SIDEBAR ---
with st.sidebar:
    st.header("ℹ️ About")
    st.markdown("""
    This tool uses Claude AI with web search to find 
    coaching staff contact information.
    
    **Cost:** ~$0.01 per school searched
    
    **Tips:**
    - Use official school names
    - Results include emails when publicly listed
    - Download CSV to save results
    """)
    
    st.divider()
    
    st.header("📊 Usage")
    if "search_count" not in st.session_state:
        st.session_state.search_count = 0
    st.metric("Searches this session", st.session_state.search_count)
