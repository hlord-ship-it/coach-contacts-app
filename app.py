import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import requests
import time
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ----------------------------
# 1) CORE CONFIGURATION
# ----------------------------
st.set_page_config(page_title="NCAA Coach Harvester v3", layout="wide")

SERPER_ENDPOINT = "https://google.serper.dev/search"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Tweakable knobs
SERPER_NUM_RESULTS = 8
SERPER_MAX_QUERIES = 4
SCRAPE_TIMEOUT_S = 20
GEMINI_TIMEOUT_S = 60
MAX_CONTENT_CHARS_FOR_GEMINI = 12000  # keep payload smaller + more relevant

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)

SPORT_SEARCH_PATTERNS = {
    "Men's Soccer": ["men's soccer", "msoc", "soccer"],
    "Women's Soccer": ["women's soccer", "wsoc", "soccer"],
    "Men's Basketball": ["men's basketball", "mbb", "basketball"],
    "Women's Basketball": ["women's basketball", "wbb", "basketball"],
    "Football": ["football"],
    "Men's Track & Field": ["men's track", "track and field", "cross country", "mtrack", "mxctf"],
    "Women's Track & Field": ["women's track", "track and field", "cross country", "wtrack", "wxctf"],
    "Rowing": ["rowing", "crew"],
    "Men's Lacrosse": ["men's lacrosse", "mlax", "lacrosse"],
    "Women's Lacrosse": ["women's lacrosse", "wlax", "lacrosse"],
    "Volleyball": ["volleyball"],
    "Swimming": ["swimming", "diving", "swimming and diving"],
    "Tennis": ["tennis"],
    "Golf": ["golf"],
    "Field Hockey": ["field hockey"],
}

# Optional: known domains (great when accurate)
KNOWN_ATHLETICS_DOMAINS = {
    "Harvard": "gocrimson.com",
    "Yale": "yalebulldogs.com",
    "Princeton": "goprincetontigers.com",
    "Brown": "brownbears.com",
    "Dartmouth": "dartmouthsports.com",
    # ... keep your full mapping if you want ...
}

NEGATIVE_URL_TERMS = [
    "roster", "schedule", "recap", "news", "article", "tickets", "stats", "boxscore", "preview",
    "camps", "clinic", "recreation", "intramural", "club", "pdf"
]

STAFF_URL_HINTS = ["staff", "coaches", "coach", "directory", "staff-directory", "coaching-staff", "staffdir"]


def robust_json_extract(text: str):
    """Extract JSON from potentially messy LLM output."""
    if not text:
        return None
    t = text.strip().replace("", "").replace("```", "").strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    # array
    try:
        match = re.search(r"\[[\s\S]*\]", t)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    # object -> array
    try:
        match = re.search(r"\{[\s\S]*\}", t)
        if match:
            return [json.loads(match.group(0))]
    except Exception:
        pass
    return None


def normalize_school_key(school: str) -> str:
    return re.sub(r"\s+", " ", (school or "")).strip().lower()


def domain_for_school(school: str) -> str | None:
    s = normalize_school_key(school)
    for k, d in KNOWN_ATHLETICS_DOMAINS.items():
        if normalize_school_key(k) in s:
            return d
    return None


def build_serper_queries(school: str, sport: str) -> list[str]:
    """
    Key improvement: build *high-intent* queries that target staff/coaches pages and
    exclude obvious noise (rosters/news/schedules).
    """
    aliases = SPORT_SEARCH_PATTERNS.get(sport, [sport])
    sport_or = " OR ".join([f"\"{a}\"" for a in aliases[:3]])

    negatives = " ".join([f"-{t}" for t in ["roster", "schedule", "recap", "news", "tickets", "stats", "pdf"]])
    intent = "(staff OR coaches OR \"coaching staff\" OR directory)"
    email_hint = "(email OR \"@\")"

    dom = domain_for_school(school)
    qs = []

    if dom:
        # Most reliable: official athletics site
        qs.append(
            f"site:{dom} {intent} {sport_or} {email_hint} {negatives}"
        )

    # .edu (works for schools without strong athletics domain mapping)
    qs.append(
        f"site:.edu \"{school}\" {intent} {sport_or} {email_hint} {negatives}"
    )

    # General athletics site query (catches .com athletics sites too)
    qs.append(
        f"\"{school}\" athletics {intent} {sport_or} {email_hint} {negatives}"
    )

    # URL-focused query
    qs.append(
        f"\"{school}\" {sport_or} (inurl:staff OR inurl:coaches OR inurl:directory) {negatives}"
    )

    return qs


def serper_search(query: str) -> list[dict]:
    headers = {
        "X-API-KEY": st.secrets["SERPER_API_KEY"],
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": SERPER_NUM_RESULTS}
    r = requests.post(SERPER_ENDPOINT, headers=headers, json=payload, timeout=20)
    r.raise_for_status()
    return r.json().get("organic", []) or []


def score_search_result(link: str, title: str, snippet: str, school: str, sport: str) -> int:
    """
    Key improvement: scoring favors staff/coaches/directory pages and penalizes noise.
    """
    link_l = (link or "").lower()
    title_l = (title or "").lower()
    snippet_l = (snippet or "").lower()

    score = 0

    # domain quality
    dom = domain_for_school(school)
    if dom and dom in link_l:
        score += 35
    elif ".edu" in link_l:
        score += 20
    elif any(d in link_l for d in KNOWN_ATHLETICS_DOMAINS.values()):
        score += 25
    else:
        # still allow (some schools host athletics on .com), but lower confidence
        score += 5

    # staff/coaches hints
    if any(h in link_l for h in STAFF_URL_HINTS):
        score += 30
    if "staff" in title_l or "coaches" in title_l or "directory" in title_l:
        score += 15

    # sport relevance
    for a in SPORT_SEARCH_PATTERNS.get(sport, [sport]):
        a_l = a.lower()
        if a_l in title_l:
            score += 8
        if a_l in snippet_l:
            score += 6
        if a_l.replace(" ", "-") in link_l:
            score += 6

    # email hint in snippet is gold
    if "@" in snippet_l:
        score += 25

    # penalties
    if any(bad in link_l for bad in NEGATIVE_URL_TERMS):
        score -= 35
    if any(bad in title_l for bad in ["recap", "preview", "game", "result"]):
        score -= 20

    return score


def search_for_staff_page(school: str, sport: str, status=None) -> tuple[str | None, int]:
    best_url, best_score = None, -10
    queries = build_serper_queries(school, sport)

    for qi, q in enumerate(queries[:SERPER_MAX_QUERIES]):
        if status:
            status.write(f"🔎 Query {qi+1}/{min(len(queries), SERPER_MAX_QUERIES)}: `{q}`")

        try:
            results = serper_search(q)
        except Exception as e:
            if status:
                status.write(f"⚠️ Serper error: {e}")
            continue

        for r in results:
            link = r.get("link", "") or ""
            title = r.get("title", "") or ""
            snippet = r.get("snippet", "") or ""
            s = score_search_result(link, title, snippet, school, sport)
            if s > best_score:
                best_score, best_url = s, link

        # early stop if clearly good
        if best_score >= 70:
            break

    return best_url, best_score


def compact_relevant_text(raw_text: str, sport: str) -> str:
    """
    Key improvement: reduce content to the most relevant lines so Gemini sees *staff table*
    not campus navigation/legal text.
    """
    if not raw_text:
        return ""

    sport_terms = [t.lower() for t in SPORT_SEARCH_PATTERNS.get(sport, [sport])]
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

    # keep lines containing sport terms, coaches/staff terms, or emails
    keep = []
    for ln in lines:
        lnl = ln.lower()
        if EMAIL_RE.search(ln):
            keep.append(ln)
            continue
        if any(t in lnl for t in sport_terms):
            keep.append(ln)
            continue
        if any(k in lnl for k in ["coach", "coaches", "staff", "director", "coordinator", "assistant", "head coach"]):
            keep.append(ln)
            continue

    # fallback: if filtering too aggressive, keep the first chunk
    if len("\n".join(keep)) < 800:
        return "\n".join(lines[:200])[:MAX_CONTENT_CHARS_FOR_GEMINI]

    return "\n".join(keep)[:MAX_CONTENT_CHARS_FOR_GEMINI]


def scrape_page_content(url: str, status=None) -> str | None:
    """
    Scrape page content.
    Priority: 1) Jina Reader  2) Direct requests -> BeautifulSoup -> text
    """
    if not url:
        return None

    # Method 1: Jina Reader
    try:
        if status:
            status.write("📄 Scrape: trying Jina Reader…")
        jina_url = f"https://r.jina.ai/{url}"
        r = requests.get(jina_url, timeout=SCRAPE_TIMEOUT_S, headers={"Accept": "text/plain"})
        if r.status_code == 200 and len(r.text) > 500:
            if status:
                status.write(f"✅ Jina ok ({len(r.text):,} chars)")
            return r.text
    except Exception as e:
        if status:
            status.write(f"⚠️ Jina failed: {str(e)[:120]}")

    # Method 2: Direct
    try:
        if status:
            status.write("📄 Scrape: trying direct request…")
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = requests.get(url, headers=headers, timeout=SCRAPE_TIMEOUT_S, allow_redirects=True)
        if r.status_code != 200:
            if status:
                status.write(f"⚠️ Direct request HTTP {r.status_code}")
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        if len(text) > 500:
            if status:
                status.write(f"✅ Direct ok ({len(text):,} chars)")
            return text
    except Exception as e:
        if status:
            status.write(f"⚠️ Direct request failed: {str(e)[:120]}")

    return None


def extract_emails_locally(text: str) -> list[str]:
    return sorted(set(m.group(0) for m in EMAIL_RE.finditer(text or "")))[:50]


def extract_coaches_with_gemini(content: str, school: str, sport: str, status=None) -> list[dict]:
    """
    Key improvement: prompt is stricter and includes a validation checklist,
    plus we pre-filter content so Gemini sees the staff section.
    """
    if not content:
        return []

    api_key = str(st.secrets["GEMINI_API_KEY"]).strip()

    # IMPORTANT: use params to avoid URL parsing issues from whitespace/newlines
    params = {"key": api_key}

    relevant = compact_relevant_text(content, sport)
    visible_emails = extract_emails_locally(relevant)

    prompt = f"""
You are extracting athletics coaching staff for a database.

School: {school}
Sport: {sport}

Return ONLY a strict JSON array (no markdown, no comments).
Each item MUST have exactly these keys:
- coach_name (string)
- title (string)
- email (string or null)

Rules:
- Include head coach + all assistants/volunteers/coordinators/staff listed for this sport.
- If email is not present, set email to null.
- Do NOT invent emails.
- Do NOT include athletic department staff unrelated to this sport unless clearly part of this sport’s staff.

If emails are present in the text, prefer them. Here is a list of emails seen in the page text:
{visible_emails}

PAGE TEXT (filtered to relevant lines):
{relevant}

JSON:
"""

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            # Correct v1beta field name:
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }

    try:
        r = requests.post(GEMINI_ENDPOINT, params=params, json=payload, timeout=GEMINI_TIMEOUT_S)
        if r.status_code != 200:
            if status:
                status.write(f"❌ Gemini HTTP {r.status_code}: {r.text[:300]}")
            return []

        data = r.json()
        parts = (data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}]))
        text = parts[0].get("text", "") if parts else ""

        coaches = robust_json_extract(text)
        if not coaches:
            return []

        cleaned = []
        for c in coaches:
            if not isinstance(c, dict):
                continue
            name = str(c.get("coach_name", "")).strip()
            title = str(c.get("title", "")).strip()
            email = c.get("email", None)

            if not name or len(name) < 3 or name.lower() in {"none", "null", "n/a"}:
                continue

            if email is not None:
                email_s = str(email).strip()
                if not email_s or email_s.lower() in {"none", "null", "n/a"} or "@" not in email_s:
                    email = None
                else:
                    email = email_s

            cleaned.append({
                "school": school,
                "coach_name": name,
                "title": title if title and title.lower() not in {"none", "null"} else "Staff",
                "email": email,
            })

        # de-dupe by (name,title)
        seen = set()
        out = []
        for c in cleaned:
            key = (c["coach_name"].lower(), c["title"].lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(c)

        return out

    except Exception as e:
        if status:
            status.write(f"⚠️ Extraction error: {e}")
        return []


# ----------------------------
# 2) GOOGLE SHEETS + CONFIG
# ----------------------------
@st.cache_data(ttl=600)
def load_config_from_sheets():
    """Reads the 'Config_Map' tab to build the UI menus."""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(st.secrets["SHEET_URL"])
        worksheet = sh.worksheet("Config_Map")
        return pd.DataFrame(worksheet.get_all_records())
    except Exception as e:
        st.error(f"Error loading Config_Map: {e}")
        return pd.DataFrame()


def append_results_to_sheet(rows: list[dict], tab_name: str):
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_url(st.secrets["SHEET_URL"])

    try:
        ws = sh.worksheet(tab_name)
    except Exception:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=12)

    df = pd.DataFrame(rows)
    # Ensure consistent columns
    cols = ["timestamp", "Division", "Conference", "school", "coach_name", "title", "email", "source_url"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols]

    # header if empty
    if not ws.row_values(1):
        ws.append_row(cols)

    ws.append_rows(df.values.tolist())


# ----------------------------
# 3) HARVEST PIPELINE
# ----------------------------
def harvest_single_school(school: str, sport: str, division: str, conference: str, status=None) -> list[dict]:
    if status:
        status.write("🔍 Finding staff directory…")

    staff_url, confidence = search_for_staff_page(school, sport, status)
    if not staff_url:
        return [{
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "Division": division,
            "Conference": conference,
            "school": school,
            "coach_name": None,
            "title": "NOT FOUND - No staff page",
            "email": None,
            "source_url": None,
        }]

    if status:
        status.write(f"✅ Staff page: {staff_url} (confidence {confidence})")
        status.write("📄 Scraping…")

    content = scrape_page_content(staff_url, status)
    if not content:
        return [{
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "Division": division,
            "Conference": conference,
            "school": school,
            "coach_name": None,
            "title": "NOT FOUND - Scrape failed",
            "email": None,
            "source_url": staff_url,
        }]

    if status:
        status.write("🤖 Extracting coaches…")

    coaches = extract_coaches_with_gemini(content, school, sport, status)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    if coaches:
        for c in coaches:
            c["timestamp"] = ts
            c["Division"] = division
            c["Conference"] = conference
            c["source_url"] = staff_url
        return coaches

    return [{
        "timestamp": ts,
        "Division": division,
        "Conference": conference,
        "school": school,
        "coach_name": None,
        "title": "NOT FOUND - Extraction failed",
        "email": None,
        "source_url": staff_url,
    }]


# ----------------------------
# 4) UI
# ----------------------------
st.title("🏆 NCAA Coach Harvester v3")
st.caption("More specific Serper searches + sport-focused extraction")

config_df = load_config_from_sheets()

if config_df.empty:
    st.error("Could not load Config_Map. Check your Google Sheet + Secrets.")
    st.stop()

col1, col2, col3 = st.columns(3)

with col1:
    divisions = sorted(config_df["Division"].dropna().unique())
    selected_div = st.selectbox("Select Division", divisions)

with col2:
    confs = sorted(config_df[config_df["Division"] == selected_div]["Conference"].dropna().unique())
    selected_conf = st.selectbox("Select Conference", confs)

with col3:
    sports = list(SPORT_SEARCH_PATTERNS.keys())
    selected_sport = st.selectbox("Select Sport", sports)

target_schools = config_df[
    (config_df["Division"] == selected_div) &
    (config_df["Conference"] == selected_conf)
]["School"].dropna().tolist()

with st.expander(f"📋 Schools to harvest ({len(target_schools)})"):
    st.write(", ".join(target_schools))

col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    harvest_all = st.button(f"🚀 Harvest All {len(target_schools)} Schools", type="primary")
with col_btn2:
    test_school = st.selectbox("Or test single school:", [""] + target_schools)
    harvest_single = st.button("🧪 Test Single School")

if harvest_all or (harvest_single and test_school):
    schools_to_process = target_schools if harvest_all else [test_school]
    st.divider()
    st.subheader(f"Harvesting {selected_sport} from {selected_conf}")

    results_placeholder = st.empty()
    all_results: list[dict] = []
    progress = st.progress(0.0)

    for i, school in enumerate(schools_to_process):
        with st.status(f"Processing {school}…", expanded=True) as status:
            rows = harvest_single_school(school, selected_sport, selected_div, selected_conf, status)
            all_results.extend(rows)

        df = pd.DataFrame(all_results)
        show_cols = ["school", "coach_name", "title", "email", "source_url"]
        show_cols = [c for c in show_cols if c in df.columns]
        results_placeholder.dataframe(df[show_cols], width="stretch", hide_index=True)

        progress.progress((i + 1) / len(schools_to_process))
        time.sleep(0.25)  # basic rate-limit

    found = sum(1 for r in all_results if r.get("coach_name"))
    st.success(f"✅ Done. Found {found} coaches across {len(schools_to_process)} schools.")

    st.divider()
    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        csv = pd.DataFrame(all_results).to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            csv,
            f"{selected_conf}_{selected_sport.replace(' ', '_')}_coaches.csv",
            "text/csv",
        )

    with col_exp2:
        if st.button("📤 Save to Google Sheet"):
            tab = f"{selected_sport.replace(' ', '_')}_Coaches"
            append_results_to_sheet(all_results, tab)
            st.success(f"✅ Saved to '{tab}' tab!")### Key changes (and why they make search/extraction “specific enough”)

- **More targeted Serper queries**: Builds high-intent queries with `(staff OR coaches OR "coaching staff" OR directory)` plus **email hints** and **negative terms** (roster/news/schedule/etc.). This reduces “random athletics pages” and increases staff-directory hits.
- **Result scoring improved**: Strong bonuses for **official athletics domains**, staff-like URL patterns (`/staff`, `/coaches`, `/directory`), and email presence; heavy penalties for rosters/news/recaps/intramurals. This picks the *right page* more often.
- **Content is filtered before Gemini**: Instead of dumping 15k chars of noisy HTML text, `compact_relevant_text()` keeps only lines mentioning **sport terms**, **coach/staff keywords**, or **emails**. Gemini sees the staff table content rather than headers/menus/legal.
- **Gemini REST payload fixed for v1beta**: Uses `generationConfig.responseMimeType` (correct casing) and uses `params={"key": ...}` instead of embedding the key in the URL (avoids malformed URL issues).
- **Cleaner output guarantees**: Forces strict JSON array shape and cleans/dedupes results before saving.

If you want, paste your current `requirements.txt` and I’ll tell you exactly what to add/remove (you’ll need at least `beautifulsoup4` for this version).
