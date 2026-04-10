"""
ExM Review Paper Manager v2
===========================
Usage:  streamlit run paper_manager.py
"""

import streamlit as st
import pandas as pd
import json
import urllib.request
import urllib.parse
import io
from pathlib import Path
from datetime import datetime

# --- Config ---
APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "_data_2026-04-10"
REFINED_JSON = DATA_DIR / "exm_refined.json"
DECISIONS_JSON = APP_DIR / "paper_decisions.json"
CUSTOM_PAPERS_JSON = APP_DIR / "paper_custom_additions.json"
S2_API_KEY = "peed9692To8iAr6sYYdBnapbP87v59jkXLH0PFWc"

SECTIONS = [
    "S2: Chemistry", "S3.1: Pre-expansion protein", "S3.2: Post-expansion protein",
    "S3.3: High expansion", "S4: RNA", "S5: Cell Biology", "S5: Neurobiology",
    "S5: Microbiology", "S5: Virology", "S5: Plant Biology (NEW)",
    "S6: Next Gen", "Review/Protocol",
]

PRIORITY_LABELS = {"method": "Method", "application": "Application", "review": "Review"}


# JCR Quartile lookup (based on JCR 2023/2024, best quartile across categories)
_JCR = {
    # Q1
    "nature": "Q1", "science": "Q1", "cell": "Q1",
    "nature methods": "Q1", "nature biotechnology": "Q1", "nature biomedical engineering": "Q1",
    "nature medicine": "Q1", "nature materials": "Q1", "nature nanotechnology": "Q1",
    "nature communications": "Q1",
    "journal of the american chemical society": "Q1", "acs nano": "Q1", "acs central science": "Q1",
    "chemical reviews": "Q1", "science advances": "Q1", "science translational medicine": "Q1",
    "cell reports methods": "Q1", "elife": "Q2",
    "proceedings of the national academy of sciences of the united states of america": "Q1",
    "embo journal": "Q1", "the embo journal": "Q1",
    "current biology": "Q1", "plos biology": "Q1", "nucleic acids research": "Q1",
    "angewandte chemie": "Q1", "jama neurology": "Q1", "analytical chemistry": "Q1",
    "nano letters (print)": "Q1", "nano letters": "Q1", "applied physics reviews": "Q1",
    "innovation (cambridge (mass.))": "Q1", "the plant cell": "Q1",
    "journal of cell biology": "Q1", "molecular systems biology": "Q1",
    "journal of experimental botany": "Q1", "mbio": "Q1", "bmc biology": "Q1",
    "npj biofilms and microbiomes": "Q1", "cellular and molecular life sciences": "Q1",
    "advances in materials": "Q1", "small methods": "Q1",
    "current opinion in cell biology": "Q1",
    "current opinion in neurobiology": "Q1", "current opinion in structural biology": "Q1",
    "current opinion in plant biology": "Q1", "acs chemical biology": "Q1",
    "environmental science and technology": "Q1",
    "environmental science &amp; technology letters": "Q1", "advancement of science": "Q1",
    "plant physiology": "Q1",
    # Moved to Q2 (IF dropped or uncertain)
    "molecular microbiology": "Q2", "journal of neuroimmunology": "Q2",
    "aggregate": "Q2", "photoacoustics": "Q2",
    "chemical & biomedical imaging": "Q2",  # new journal, no official JCR yet
    # Q2
    "journal of cell science": "Q2", "communications biology": "Q2", "scientific reports": "Q2",
    "biophysical journal": "Q2", "plos pathogens": "Q2", "plos genetics": "Q2", "plos one": "Q2",
    "life science alliance": "Q2", "journal of microscopy": "Q2",
    "frontiers in synaptic neuroscience": "Q2", "frontiers in cell and developmental biology": "Q2",
    "frontiers in cellular neuroscience": "Q2", "cell and tissue research": "Q2",
    "journal of medical virology": "Q2",
    "investigative ophthalmology and visual science": "Q2",
    "american journal of physiology - cell physiology": "Q2", "gene therapy": "Q2",
    "msphere": "Q2", "open biology": "Q2", "nano convergence": "Q2", "chembiochem": "Q2",
    "cytoskeleton": "Q2", "small structures": "Q2", "analytica chimica acta": "Q2",
    "talanta: the international journal of pure and applied analytical chemistry": "Q2",
    "analyst": "Q2", "brain research": "Q2", "neurophotonics": "Q2", "the faseb journal": "Q2",
    "microbial cell": "Q2", "optics letters": "Q2", "ieee transactions on image processing": "Q2",
    "biochimica et biophysica acta - bioenergetics": "Q2",
    "acta biochimica et biophysica sinica": "Q2", "journal of materials chemistry. b": "Q2",
    "journal of photochemistry and photobiology. b: biology": "Q2",
    "platelets": "Q2", "parasitology research": "Q2", "experimental parasitology": "Q2",
    "viruses": "Q2", "pathogens": "Q2", "nanomaterials": "Q2",
}


def jcr_rank(venue: str) -> str:
    """Get JCR quartile for a journal. Returns Q1/Q2/Preprint/Protocol/Other."""
    v = (venue or "").lower().strip()
    # Direct match
    if v in _JCR:
        return _JCR[v]
    # Partial match
    for key, val in _JCR.items():
        if key in v or v in key:
            return val
    # Preprints
    if "biorxiv" in v or "arxiv" in v or "research square" in v or "preprint" in v:
        return "Preprint"
    # Protocol/methods books
    if any(k in v for k in ["methods in molecular", "bio-protocol", "journal of visualized",
                             "star protocols", "current protocols", "methodsx",
                             "micropublication", "methods in microscopy"]):
        return "Protocol"
    # Conference proceedings
    if any(k in v for k in ["congress", "conference", "proceedings", "workshop"]):
        return "Conf"
    return "Other"


def make_cite_paren(first_author: str, year: int) -> str:
    last = first_author.strip().split()[-1] if first_author and first_author != "N/A" else "Unknown"
    return f"({last} et al., {year})"


def make_cite_key(first_author: str, year: int) -> str:
    last = first_author.strip().split()[-1] if first_author and first_author != "N/A" else "Unknown"
    return f"{last} et al., {year}"


def parse_paper_row(p: dict) -> dict:
    authors = p.get("authors", [])
    if authors and isinstance(authors[0], str):
        first_author = authors[0].split(",")[0]
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."
    else:
        first_author = str(authors[0]) if authors else "N/A"
        author_str = first_author

    # Boyden Lab = Ed Boyden is last (corresponding) author
    is_boyden = False
    if authors:
        last_author = authors[-1] if isinstance(authors[-1], str) else str(authors[-1])
        is_boyden = "boyden" in last_author.lower()

    cats = [c for c in p.get("categories", []) if c != "Uncategorized"]
    venue = p.get("venue", "") or ""

    return {
        "doi": p.get("doi", ""),
        "title": p.get("title", ""),
        "first_author": first_author,
        "authors": author_str,
        "authors_all": ", ".join(a if isinstance(a, str) else str(a) for a in authors).lower(),
        "year": p.get("year", 0),
        "venue": venue,
        "jcr": jcr_rank(venue),
        "citations": p.get("citations", 0),
        "type": PRIORITY_LABELS.get(p.get("relevance", ""), p.get("type", "Unknown")),
        "is_boyden": is_boyden,
        "source": p.get("source", ""),
        "auto_sections": cats,
        "primary_section": cats[0] if cats else "Uncategorized",
        "abstract": (p.get("abstract", "") or "")[:800],
        "pub_date": p.get("pub_date", ""),
        "cite_key": make_cite_key(first_author, p.get("year", 0)),
        "cite_paren": make_cite_paren(first_author, p.get("year", 0)),
    }


# --- Persistence ---

def load_papers() -> pd.DataFrame:
    with open(REFINED_JSON) as f:
        rows = [parse_paper_row(p) for p in json.load(f)]
    if CUSTOM_PAPERS_JSON.exists():
        with open(CUSTOM_PAPERS_JSON) as f:
            for p in json.load(f):
                rows.append(parse_paper_row(p))
    return pd.DataFrame(rows)


def load_decisions() -> dict:
    if DECISIONS_JSON.exists():
        with open(DECISIONS_JSON) as f:
            raw = json.load(f)
        out = {}
        for doi, val in raw.items():
            out[doi] = val if isinstance(val, dict) else {"decision": val, "sections": [], "notes": ""}
        return out
    return {}


def save_decisions(d: dict):
    with open(DECISIONS_JSON, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def get_dec(d, doi): return (d.get(doi) or {}).get("decision", "Pending") if isinstance(d.get(doi), dict) else (d.get(doi, "Pending") if isinstance(d.get(doi), str) else "Pending")
def get_secs(d, doi, auto): e = d.get(doi); return e.get("sections") or auto if isinstance(e, dict) else auto
def get_notes(d, doi): e = d.get(doi); return e.get("notes", "") if isinstance(e, dict) else ""

def set_field(d, doi, **kw):
    if doi not in d or isinstance(d[doi], str):
        old = d.get(doi, "Pending")
        d[doi] = {"decision": old if isinstance(old, str) else "Pending", "sections": [], "notes": ""}
    d[doi].update(kw)


def load_custom(): return json.load(open(CUSTOM_PAPERS_JSON)) if CUSTOM_PAPERS_JSON.exists() else []
def save_custom(p): json.dump(p, open(CUSTOM_PAPERS_JSON, "w"), indent=2, ensure_ascii=False)


def fetch_doi(doi):
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi, safe='')}?fields=title,authors,year,venue,externalIds,citationCount,abstract,publicationDate"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"x-api-key": S2_API_KEY}), timeout=15) as r:
            d = json.loads(r.read().decode())
        return {"doi": doi, "title": d.get("title",""), "authors": [a.get("name","") for a in (d.get("authors") or [])],
                "year": d.get("year",0), "venue": d.get("venue",""), "citations": d.get("citationCount",0) or 0,
                "abstract": d.get("abstract",""), "pub_date": d.get("publicationDate",""),
                "relevance": "method", "is_boyden": False, "categories": [], "source": "Manual addition"}
    except:
        return None


def export_bibtex(df_sel):
    entries, seen = [], set()
    for _, r in df_sel.iterrows():
        last = r["first_author"].split()[-1] if r["first_author"] != "N/A" else "unknown"
        key = f"{last}{r['year']}"
        while key in seen: key += "b"
        seen.add(key)
        entries.append(f"@article{{{key},\n  title={{{r['title']}}},\n  author={{{r['authors']}}},\n  journal={{{r['venue']}}},\n  year={{{r['year']}}},\n  doi={{{r['doi']}}}\n}}")
    return "\n\n".join(entries)


def export_excel(df_all, decisions):
    rows = []
    for _, r in df_all.iterrows():
        rows.append({"Decision": get_dec(decisions, r["doi"]), "Citation": r["cite_paren"],
            "Year": r["year"], "Title": r["title"], "First Author": r["first_author"],
            "Journal": r["venue"], "JCR": r["jcr"], "Citations": r["citations"],
            "Type": r["type"], "Boyden Lab": "Yes" if r["is_boyden"] else "",
            "Sections": "; ".join(get_secs(decisions, r["doi"], r["auto_sections"])),
            "DOI": r["doi"], "Abstract": r["abstract"], "Notes": get_notes(decisions, r["doi"])})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, index=False, sheet_name="Papers")
        ws = w.sheets["Papers"]
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col)+2, 60)
    return buf.getvalue()


# ============================================================
# APP
# ============================================================

st.set_page_config(page_title="ExM Paper Manager", page_icon="🔬", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""<style>
    .paper-title a { text-decoration: none; color: #1a1a1a; font-weight: 600; font-size: 1.02em; }
    .paper-title a:hover { color: #1a73e8; text-decoration: underline; }
    .paper-meta { color: #666; font-size: 0.82em; margin: 2px 0 4px 0; line-height: 1.4; }
    .paper-abstract { color: #555; font-size: 0.82em; margin: 2px 0; line-height: 1.4; }
    .badge { padding: 1px 6px; border-radius: 3px; font-size: 0.75em; margin-left: 6px; }
    .badge-boyden { background: #c6efce; color: #006100; }
    .badge-ed { background: #dae8fc; color: #1a5276; }
    div[data-testid="stVerticalBlock"] > div { padding-top: 0; }
    .stMultiSelect { margin-bottom: 0 !important; }
    .stMultiSelect [data-baseweb="tag"] { background-color: #e8eef4 !important; color: #2c3e50 !important; }
    .stMultiSelect [data-baseweb="tag"] span[aria-label] { color: #7f8c8d !important; }
</style>""", unsafe_allow_html=True)

st.title("ExM Review Paper Manager")
st.caption("Citations from Semantic Scholar (retrieved 2026-04-10)")

df = load_papers()
decisions = load_decisions()
df["decision"] = df["doi"].map(lambda d: get_dec(decisions, d))

# --- Sidebar ---
with st.sidebar:
    st.header("Filters")
    decision_filter = st.multiselect("Decision", ["Pending", "Include", "Exclude"], default=["Pending", "Include"])
    yr_min, yr_max = int(df["year"].min()), int(df["year"].max())
    year_range = st.slider("Year", yr_min, yr_max, (yr_min, yr_max))
    rank_filter = st.multiselect("JCR Quartile", ["Q1", "Q2", "Preprint", "Protocol", "Conf", "Other"],
                                  default=["Q1", "Q2", "Preprint"])
    type_filter = st.multiselect("Paper Type", ["Method", "Application", "Review", "Unknown"],
                                  default=["Method", "Application"])
    section_filter = st.multiselect("Section (auto-tagged)", SECTIONS + ["Uncategorized"])
    st.divider()
    boyden_only = st.checkbox("Boyden Lab only (Ed = corresponding author)", False)
    cite_min = st.number_input("Min citations", 0, 500, 0)
    notes_search = st.text_input("Filter by notes", placeholder="e.g. important, revisit...")

    mask = (df["decision"].isin(decision_filter) & df["year"].between(*year_range)
            & df["jcr"].isin(rank_filter) & df["type"].isin(type_filter) & (df["citations"] >= cite_min))
    if section_filter:
        mask &= df["auto_sections"].apply(lambda c: any(s in c for s in section_filter))
    if boyden_only:
        mask &= df["is_boyden"]
    if notes_search:
        nq = notes_search.lower()
        mask &= df["doi"].apply(lambda d: nq in get_notes(decisions, d).lower())
    df_filtered = df[mask].copy()

    st.divider()
    st.header("Stats")
    total = len(df)
    included = len(df[df["decision"] == "Include"])
    excluded = len(df[df["decision"] == "Exclude"])
    pending = len(df[df["decision"] == "Pending"])
    st.metric("Showing", f"{len(df_filtered)}/{total}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Include", included); c2.metric("Exclude", excluded); c3.metric("Pending", pending)

# --- Sort + Search ---
col_sort, col_search = st.columns([1, 2])
with col_sort:
    sort_col = st.selectbox("Sort by", ["citations", "year", "jcr"], index=0)
with col_search:
    search_q = st.text_input("Search title or author", placeholder="e.g. magnify, boyden, centriole...")

sort_asc = (sort_col not in ("citations", "year"))  # citations and year default descending
df_filtered = df_filtered.sort_values(sort_col, ascending=sort_asc)

if search_q:
    q = search_q.lower()
    df_filtered = df_filtered[df_filtered["title"].str.lower().str.contains(q, na=False)
                              | df_filtered["authors_all"].str.contains(q, na=False)]

# --- Tabs ---
tab_cards, tab_table, tab_add, tab_share, tab_export = st.tabs([
    "Card View", "Table View", "Add Paper", "Share with Ed", "Export & Citations"
])

# ============================================================
# Card View
# ============================================================
with tab_cards:
    for idx, row in df_filtered.iterrows():
        doi = row["doi"]
        doi_url = f"https://doi.org/{doi}" if doi else ""
        boyden_b = '<span class="badge badge-boyden">Boyden Lab</span>' if row["is_boyden"] else ""

        with st.container(border=True):
            # Line 1: Title + Decision buttons (SAME ROW)
            col_title, col_btn = st.columns([4, 2])
            with col_title:
                title_html = f'<a href="{doi_url}" target="_blank">{row["title"]}</a>' if doi_url else row["title"]
                st.markdown(f'<div class="paper-title">{title_html}{boyden_b}</div>', unsafe_allow_html=True)
            with col_btn:
                cur_dec = get_dec(decisions, doi)
                bc = st.columns(3)
                for i, label in enumerate(["Include", "Exclude", "Pending"]):
                    is_active = (cur_dec == label)
                    if bc[i].button(label, key=f"d_{idx}_{label}",
                                    type="primary" if is_active else "secondary",
                                    use_container_width=True):
                        if not is_active and doi:
                            set_field(decisions, doi, decision=label)
                            save_decisions(decisions)
                            st.rerun()

            # Line 2: Citation + meta
            rank_colors = {"Q1": "#c62828", "Q2": "#e65100", "Preprint": "#1565c0",
                           "Protocol": "#757575", "Conf": "#757575", "Other": "#757575"}
            rc = rank_colors.get(row["jcr"], "#757575")
            st.markdown(
                f'<div class="paper-meta">'
                f'<code>{row["cite_paren"]}</code> &middot; {row["authors"]} &middot; '
                f'<em>{row["venue"]}</em> '
                f'<span style="color:{rc};font-weight:600;">({row["jcr"]})</span> &middot; '
                f'Cit: {row["citations"]} &middot; {row["type"]}'
                f'</div>', unsafe_allow_html=True)

            # Line 3-4: Left = Abstract + Sections, Right = Notes (tall, fills space)
            col_left, col_right = st.columns([3, 2])
            with col_left:
                abs_text = row["abstract"]
                if abs_text:
                    st.markdown(f'<div class="paper-abstract">{abs_text}</div>',
                                unsafe_allow_html=True)
                # Sections at bottom of left column
                cur_secs = get_secs(decisions, doi, row["auto_sections"])
                new_secs = st.multiselect("Sections", SECTIONS, default=cur_secs,
                                           key=f"s_{idx}", label_visibility="collapsed")
                if set(new_secs) != set(cur_secs):
                    set_field(decisions, doi, sections=new_secs); save_decisions(decisions)

            with col_right:
                cur_notes = get_notes(decisions, doi)
                new_notes = st.text_area("Notes", value=cur_notes, key=f"n_{idx}",
                                          placeholder="Notes...", label_visibility="collapsed",
                                          height=200)
                if new_notes != cur_notes and doi:
                    set_field(decisions, doi, notes=new_notes); save_decisions(decisions)

# ============================================================
# Table View
# ============================================================
with tab_table:
    st.subheader(f"Papers ({len(df_filtered)})")
    display_df = df_filtered[["decision", "cite_paren", "year", "title", "first_author", "venue",
                               "jcr", "citations", "type", "is_boyden", "primary_section", "doi"]].copy()
    edited = st.data_editor(display_df, column_config={
        "decision": st.column_config.SelectboxColumn("Decision", options=["Pending","Include","Exclude"], width="small"),
        "cite_paren": st.column_config.TextColumn("Citation", width="medium"),
        "year": st.column_config.NumberColumn("Year", format="%d", width="small"),
        "title": st.column_config.TextColumn("Title", width="large"),
        "first_author": st.column_config.TextColumn("1st Author", width="medium"),
        "venue": st.column_config.TextColumn("Journal", width="medium"),
        "jcr": st.column_config.TextColumn("JCR", width="small"),
        "citations": st.column_config.NumberColumn("Cit.", width="small"),
        "type": st.column_config.TextColumn("Type", width="small"),
        "is_boyden": st.column_config.CheckboxColumn("Boyden", width="small"),
        "primary_section": st.column_config.TextColumn("Section", width="medium"),
        "doi": st.column_config.TextColumn("DOI", width="medium"),
    }, use_container_width=True, hide_index=True, num_rows="fixed", key="tbl")

    if st.button("Save Decisions", type="primary", key="save_tbl"):
        for i in range(len(edited)):
            ri = df_filtered.index[i]
            d = df.loc[ri, "doi"]
            if d: set_field(decisions, d, decision=edited.iloc[i]["decision"])
        save_decisions(decisions); st.success("Saved!"); st.rerun()

# ============================================================
# Add Paper
# ============================================================
with tab_add:
    st.subheader("Add a Paper by DOI")
    doi_input = st.text_input("DOI", placeholder="e.g. 10.1038/s41592-024-02454-9")
    col_f, col_m = st.columns(2)
    with col_f:
        if st.button("Fetch from Semantic Scholar", disabled=not doi_input):
            if doi_input in df["doi"].values:
                st.warning("Already in the list.")
            else:
                with st.spinner("Fetching..."): paper = fetch_doi(doi_input)
                if paper:
                    st.success(f"**{paper['title']}**")
                    st.write(f"{', '.join(paper['authors'][:5])} | {paper['year']} | {paper['venue']} | Cit: {paper['citations']}")
                    a_sec = st.multiselect("Sections", SECTIONS, key="a_sec")
                    a_type = st.selectbox("Type", ["Method","Application","Review"], key="a_type")
                    a_boy = st.checkbox("Boyden Lab (Ed = corresponding)", key="a_boy")
                    if st.button("Add", type="primary", key="a_confirm"):
                        paper.update(categories=a_sec, type=a_type, is_boyden=a_boy)
                        c = load_custom(); c.append(paper); save_custom(c)
                        set_field(decisions, doi_input, decision="Include", sections=a_sec, notes="")
                        save_decisions(decisions); st.success("Added!"); st.rerun()
                else: st.error("Not found. Try manual entry.")
    with col_m:
        with st.expander("Manual entry"):
            mt = st.text_input("Title", key="mt"); ma = st.text_input("Authors", key="ma")
            my = st.number_input("Year", 2020, 2030, 2025, key="my"); mv = st.text_input("Journal", key="mv")
            md = st.text_input("DOI", value=doi_input, key="md")
            ms = st.multiselect("Sections", SECTIONS, key="ms")
            mp = st.selectbox("Type", ["Method","Application","Review"], key="mp")
            mb = st.checkbox("Boyden Lab", key="mb")
            if st.button("Add manually", key="m_add") and mt:
                p = {"doi":md, "title":mt, "authors":[a.strip() for a in ma.split(",")], "year":my,
                     "venue":mv, "citations":0, "abstract":"", "pub_date":"", "relevance":mp.lower(),
                     "type":mp, "is_boyden":mb, "categories":ms, "source":"Manual"}
                c = load_custom(); c.append(p); save_custom(c)
                if md: set_field(decisions, md, decision="Include", sections=ms, notes=""); save_decisions(decisions)
                st.success(f"Added: {mt}"); st.rerun()

# ============================================================
# Share with Ed
# ============================================================
with tab_share:
    st.subheader("Share with Ed")
    st.markdown("1. **Download Excel** → send to Ed\n2. Ed fills **Decision** + **Notes** + corrects **Sections**\n3. Upload Ed's file → **Merge**")
    st.divider()
    try:
        st.download_button("Download Excel for Ed", export_excel(df, decisions), type="primary",
            file_name=f"ExM_papers_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except ImportError: st.error("pip install openpyxl")
    st.divider()
    uploaded = st.file_uploader("Upload Ed's reviewed Excel", type=["xlsx"])
    if uploaded:
        df_ed = pd.read_excel(uploaded, sheet_name="Papers")
        ed_dec = {}
        for _, r in df_ed.iterrows():
            d = str(r.get("DOI","")).strip(); dec = str(r.get("Decision","")).strip()
            notes = str(r.get("Notes","")).strip(); ss = str(r.get("Sections","")).strip()
            secs = [s.strip() for s in ss.split(";") if s.strip()] if ss else []
            if d and dec in ("Include","Exclude","Pending"):
                ed_dec[d] = {"decision":dec, "sections":secs, "notes":notes if notes!="nan" else ""}
        st.write(f"{len(ed_dec)} entries found")
        if st.button("Merge", type="primary"):
            m = 0
            for d, e in ed_dec.items():
                if e != decisions.get(d, {}): decisions[d] = e; m += 1
            save_decisions(decisions); st.success(f"Merged {m} updates."); st.rerun()

# ============================================================
# Export & Citations
# ============================================================
with tab_export:
    st.subheader("Export & Citations")
    inc_df = df[df["doi"].map(lambda d: get_dec(decisions, d) == "Include")]
    if len(inc_df) > 0:
        st.success(f"{len(inc_df)} papers marked as Include")
        st.subheader("Citations by section")
        for sec in SECTIONS:
            sp = inc_df[inc_df["doi"].apply(lambda d: sec in get_secs(decisions, d,
                df.loc[df["doi"]==d, "auto_sections"].iloc[0] if len(df[df["doi"]==d])>0 else []))]
            if len(sp) > 0:
                with st.expander(f"**{sec}** ({len(sp)})", expanded=False):
                    for _, r in sp.iterrows():
                        st.markdown(f"**{r['cite_key']}** — {r['title'][:80]}... *{r['venue']}*")
                    st.code("(" + "; ".join(sp["cite_key"].tolist()) + ")", language=None)
        st.divider()
        st.subheader("All citations")
        st.text_area("Parenthetical", "(" + "; ".join(inc_df["cite_key"].tolist()) + ")", height=80)
        st.divider()
        st.subheader("Reference list")
        for _, r in inc_df.sort_values(["first_author","year"]).iterrows():
            st.caption(f"{r['authors']}, {r['year']}. {r['title']}. *{r['venue']}*. https://doi.org/{r['doi']}")
        st.divider()
        c1, c2 = st.columns(2)
        c1.download_button("BibTeX", export_bibtex(inc_df), file_name=f"exm_{datetime.now().strftime('%Y%m%d')}.bib", mime="text/plain")
        c2.download_button("JSON", inc_df[["doi","title","authors","year","venue","citations","cite_paren","abstract"]].to_json(orient="records",indent=2),
            file_name=f"exm_{datetime.now().strftime('%Y%m%d')}.json", mime="application/json")
    else:
        st.info("No papers marked as 'Include' yet.")
    st.divider()
    st.bar_chart(pd.DataFrame({"Decision":["Include","Exclude","Pending"],"Count":[included,excluded,pending]}), x="Decision", y="Count")
