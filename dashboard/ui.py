"""
dashboard/ui.py  (Fatema - Member 2)  -  shared look for every dashboard page.

One place for the colours, fonts and HTML building blocks, so all four pages
(and the PowerPoint) look like one product: a light, airy "daytime sky" theme with
the README banner's colours (navy, sky blue, teal and the gold sun).
The base theme lives in .streamlit/config.toml; this module adds the extras
that config.toml cannot do (hero banner, KPI cards, section headers ...).

How to use it on any page (Member 3 / Eman: copy these lines):

    import streamlit as st
    import ui

    st.set_page_config(page_title="Passenger feedback", page_icon="💬", layout="wide")
    ui.apply_theme()                                   # once, right after set_page_config
    ui.hero("Passenger feedback", "Reviews and photo likes from MongoDB Atlas.",
            eyebrow="Page 3 · MongoDB", chips=["MongoDB Atlas", "passenger_feedback"])
    ui.kpi_row([ui.Kpi("Reviews", "1,204", "in passenger_feedback", "💬"),
                ui.Kpi("Avg rating", "4.3", "out of 5", "⭐", accent="teal")])
    ui.section("Latest reviews", "Newest first", icon="📝")
    with ui.card_container("reviews"):                  # white card around a chart or table
        st.dataframe(df)
    ui.footer()

Chart colours: use ui.CARRIER_COLORS (mainline = gold, regional = teal) so every
page colours the two airlines the same way. They passed the colour-blind and
contrast checks on white.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from urllib.parse import quote

import streamlit as st

# ------------------------------------------------------------------------------------------
# Design tokens (light theme)
# ------------------------------------------------------------------------------------------
PAGE = "#F6F8FC"       # page background
CARD = "#FFFFFF"       # cards and chart backgrounds
LINE = "#E3E9F2"       # borders
NAVY = "#0B1F3A"       # main text (15.5:1 on the page)
MUTED = "#55657C"      # secondary text (5.6:1)
BLUE = "#1F5FAF"       # links, tabs, focus (theme primary colour)
GOLD = "#F2B544"       # accent: Sync now button, highlights (the banner's sun)
TEXT = NAVY            # text inside charts

# Chart series colours - validated together on white
# (lightness band, chroma, colour-blind separation, 3:1 contrast all pass).
MAINLINE = "#C2841A"   # mainline carrier (DM) - gold
REGIONAL = "#0F86A0"   # regional partner (PX) - teal
CARRIER_COLORS = {"Mainline carrier": MAINLINE, "Regional partner": REGIONAL}
CARRIER_CODE_COLORS = {"DM": MAINLINE, "PX": REGIONAL}
BEFORE = "#94A3B8"     # "before" state in before/after charts (deliberately muted grey)
AFTER = MAINLINE       # "after" state

# Status colours are reserved for meaning (never used for a chart series): text, tint, icon
STATUS = {
    "good": ("#1E7F4A", "#E7F6EE", "✅"),
    "warn": ("#9A5B00", "#FFF4DE", "⚠️"),
    "bad": ("#B3261E", "#FDECEA", "⛔"),
    "info": ("#0B6E85", "#E3F5F9", "ℹ️"),
    "neutral": ("#55657C", "#EEF2F7", "•"),
}


@dataclass
class Kpi:
    """One KPI card: label, big value, small note underneath, optional emoji icon."""
    label: str
    value: str
    note: str = ""
    icon: str = ""
    unit: str = ""
    accent: str = "gold"   # gold | teal


# Decorative flight path drawn in the hero (an SVG used as a CSS background,
# so it works on every Streamlit version and never shifts the page layout).
_ROUTE_SVG = """<svg xmlns='http://www.w3.org/2000/svg' width='560' height='240' viewBox='0 0 560 240'>
<style>
.r{fill:none;stroke:#FFFFFF;stroke-opacity:.85;stroke-width:2.2;stroke-linecap:round;stroke-dasharray:2 11;animation:f 1.8s linear infinite}
.p{transform-origin:center;transform-box:fill-box;animation:p 2.6s ease-out infinite}
@keyframes f{to{stroke-dashoffset:-26}}
@keyframes p{from{transform:scale(.6);opacity:.9}to{transform:scale(2.8);opacity:0}}
@media (prefers-reduced-motion:reduce){.r,.p{animation:none}}
</style>
<path class='r' d='M130 196 C 230 60, 400 26, 520 120'/>
<circle cx='130' cy='196' r='6' fill='#F2B544'/><circle class='p' cx='130' cy='196' r='6' fill='#F2B544'/>
<circle cx='520' cy='120' r='6' fill='#FFFFFF'/><circle class='p' cx='520' cy='120' r='6' fill='#FFFFFF'/>
<g transform='translate(340 42) rotate(12)'><path d='M0 6 L22 0 L26 2 L10 9 L14 18 L10 19 L3 11 L-4 13 L-6 11 Z' fill='#FFFFFF'/></g>
</svg>"""
_ROUTE_URI = "data:image/svg+xml;charset=utf-8," + quote(" ".join(_ROUTE_SVG.split()))

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');
:root {{
  --ui-page:{PAGE}; --ui-card:{CARD}; --ui-line:{LINE}; --ui-navy:{NAVY}; --ui-muted:{MUTED};
  --ui-blue:{BLUE}; --ui-gold:{GOLD}; --ui-gold-deep:{MAINLINE}; --ui-teal:{REGIONAL};
  --ui-radius:18px;
  --ui-shadow:0 1px 2px rgba(16,40,80,.06), 0 14px 34px -18px rgba(16,40,80,.28);
  --ui-shadow-hover:0 2px 4px rgba(16,40,80,.08), 0 22px 44px -18px rgba(16,40,80,.36);
  --ui-head:'Plus Jakarta Sans','Segoe UI',system-ui,-apple-system,sans-serif;
}}
/* page canvas: soft sky-blue and warm sun glow at the top, like a bright morning */
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(1000px 460px at 92% -10%, rgba(242,181,68,.18), transparent 62%),
    radial-gradient(900px 480px at -8% -6%, rgba(63,169,218,.16), transparent 60%),
    var(--ui-page);
}}
[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3 {{ font-family: var(--ui-head) !important; letter-spacing: -.01em; color: var(--ui-navy); }}
/* primary buttons: golden, with navy text and a soft glow */
[data-testid="stBaseButton-primary"], [data-testid="baseButton-primary"] {{
  color: var(--ui-navy) !important; font-weight: 700 !important; border: 0 !important;
  background: linear-gradient(180deg, #FFD27A 0%, #F2B544 55%, #E9A12C 100%) !important;
  box-shadow: 0 10px 24px -10px rgba(233,161,44,.85), inset 0 1px 0 rgba(255,255,255,.6);
  transition: transform .15s ease, box-shadow .15s ease;
}}
[data-testid="stBaseButton-primary"] p, [data-testid="baseButton-primary"] p {{ color: var(--ui-navy) !important; font-weight: 700 !important; }}
[data-testid="stBaseButton-primary"]:hover, [data-testid="baseButton-primary"]:hover {{
  transform: translateY(-1px); box-shadow: 0 14px 28px -10px rgba(233,161,44,.95), inset 0 1px 0 rgba(255,255,255,.6); }}
/* sidebar: white to pale sky */
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, #FFFFFF 0%, #EEF4FB 100%); border-right: 1px solid var(--ui-line); }}
/* white cards: bordered containers, expanders, tables */
[data-testid="stVerticalBlockBorderWrapper"] {{ background: var(--ui-card); border-radius: var(--ui-radius) !important;
  border-color: var(--ui-line) !important; box-shadow: var(--ui-shadow); }}
[data-testid="stExpander"] details {{ background: var(--ui-card); border-radius: 14px; border-color: var(--ui-line); box-shadow: var(--ui-shadow); }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}
[data-testid="stTabs"] [role="tab"] p {{ font-family: var(--ui-head); font-weight: 600; }}

@keyframes ui-rise {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}

/* ---------- every page, no code changes needed ---------- */
/* st.metric -> white KPI cards */
[data-testid="stMetric"] {{ position: relative; overflow: hidden; background: var(--ui-card); border: 1px solid var(--ui-line);
  border-radius: 16px; padding: 14px 16px 12px; box-shadow: var(--ui-shadow); animation: ui-rise .5s ease-out both; }}
[data-testid="stMetric"]::before {{ content: ""; position: absolute; left: 0; top: 0; height: 4px; width: 100%;
  background: linear-gradient(90deg, #F2B544, #FFD98A 45%, #7FD3EA); }}
[data-testid="stMetricLabel"] p {{ font: 700 11.5px/1.25 var(--ui-head) !important; letter-spacing: .08em; text-transform: uppercase;
  color: var(--ui-muted) !important; }}
[data-testid="stMetricValue"] {{ font-family: var(--ui-head) !important; font-weight: 800 !important; color: var(--ui-navy);
  font-size: clamp(1.6rem, 1.1vw + 1.1rem, 2.1rem) !important; }}
/* forms -> white cards */
[data-testid="stForm"] {{ background: var(--ui-card); border: 1px solid var(--ui-line) !important; border-radius: 18px !important;
  box-shadow: var(--ui-shadow); padding: 18px 20px 20px !important; }}
/* secondary buttons -> soft white pills with a gold hover */
[data-testid="stBaseButton-secondary"] {{ background: #FFFFFF; border: 1px solid var(--ui-line) !important; border-radius: 12px !important;
  box-shadow: 0 1px 2px rgba(16,40,80,.06); transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease; }}
[data-testid="stBaseButton-secondary"]:hover {{ border-color: #F2B544 !important; color: var(--ui-navy) !important;
  transform: translateY(-1px); box-shadow: 0 10px 20px -12px rgba(16,40,80,.4); }}
/* horizontal radios -> pills */
[data-testid="stRadio"] [role="radiogroup"] {{ gap: 8px; flex-wrap: wrap; }}
[data-testid="stRadio"] [role="radiogroup"] > label {{ background: #FFFFFF; border: 1px solid var(--ui-line); border-radius: 999px;
  padding: 6px 14px 6px 10px; margin: 0; box-shadow: 0 1px 2px rgba(16,40,80,.06); transition: border-color .15s ease, background .15s ease; }}
[data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) {{ border-color: var(--ui-blue); background: #EAF1FB; }}
/* sidebar navigation */
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] {{ border-radius: 10px; }}
[data-testid="stSidebarNav"] a[aria-current="page"], [data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: linear-gradient(90deg, rgba(242,181,68,.24), rgba(242,181,68,.05)) !important; box-shadow: inset 3px 0 0 #F2B544; }}
[data-testid="stNavSectionHeader"] {{ font-family: var(--ui-head); font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
/* st.page_link -> blue pill */
[data-testid="stPageLink"] a {{ display: inline-flex; border: 1px solid #CFE0F5; background: #F2F7FD; border-radius: 999px; padding: 4px 12px;
  transition: background .15s ease, transform .15s ease; }}
[data-testid="stPageLink"] a:hover {{ background: #E3EEFB; transform: translateX(2px); }}
/* white cards made with ui.card_container() */
[class*="st-key-uicard_"] {{ background: var(--ui-card); border: 1px solid var(--ui-line); border-radius: var(--ui-radius);
  box-shadow: var(--ui-shadow); padding: 16px 18px; animation: ui-rise .55s ease-out both; }}

/* ---------- home page pieces ---------- */
.ui-page__top {{ display: flex; align-items: center; justify-content: space-between; }}
.ui-page__icon {{ width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; font-size: 22px;
  background: linear-gradient(135deg, #FFF1CF, #DDF2FB); border: 1px solid var(--ui-line); }}
.ui-page__num {{ font: 800 30px/1 var(--ui-head); color: #DCE4EF; }}
.ui-page__title {{ font: 800 18px/1.25 var(--ui-head); color: var(--ui-navy); margin-top: 12px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.ui-page__text {{ font-size: 13.5px; color: var(--ui-muted); line-height: 1.5; margin-top: 5px; height: 81px; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; }}
.ui-tags {{ display: flex; flex-wrap: wrap; align-content: flex-start; gap: 6px; margin: 10px 0 4px; }}
.ui-page .ui-tags {{ height: 50px; overflow: hidden; }}
.ui-soon {{ display: inline-flex; align-items: center; gap: 6px; font-size: 14px; white-space: nowrap; color: #8391A7; border: 1px dashed #CFD8E5;
  border-radius: 999px; padding: 6px 12px; }}
.ui-tag {{ font-size: 11.5px; font-weight: 700; padding: 4px 9px; border-radius: 999px; color: #1F4E8C; background: #EAF1FB; }}
.ui-tag--gold {{ color: #6B4A00; background: #FCEBC0; }}
.ui-flows {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }}
.ui-flowcard {{ display: flex; gap: 12px; padding: 14px 15px; border-radius: 16px; background: var(--ui-card); border: 1px solid var(--ui-line);
  box-shadow: var(--ui-shadow); animation: ui-rise .55s ease-out both; }}
.ui-flowcard__num {{ flex: none; width: 34px; height: 34px; border-radius: 11px; display: grid; place-items: center;
  font: 800 15px/1 var(--ui-head); color: #FFFFFF; background: linear-gradient(135deg, #1F6FC4, #3FA9DA); }}
.ui-flowcard__route {{ font: 800 14px/1.3 var(--ui-head); color: var(--ui-navy); }}
.ui-flowcard__text {{ font-size: 12.5px; color: var(--ui-muted); margin-top: 3px; line-height: 1.45; }}
.ui-team {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
.ui-member {{ display: flex; gap: 13px; align-items: flex-start; padding: 15px 16px; border-radius: 16px; background: var(--ui-card);
  border: 1px solid var(--ui-line); box-shadow: var(--ui-shadow); }}
.ui-member__avatar {{ flex: none; width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center;
  font: 800 17px/1 var(--ui-head); color: var(--ui-navy); background: linear-gradient(135deg, #FFD98A, #F2B544); }}
.ui-member__name {{ font: 800 15px/1.3 var(--ui-head); color: var(--ui-navy); }}
.ui-member__role {{ font-size: 12.5px; color: var(--ui-muted); margin-top: 2px; line-height: 1.45; }}
.ui-side {{ margin-top: 8px; padding: 12px 13px; border-radius: 14px; background: #FFFFFF; border: 1px solid var(--ui-line); font-size: 12.5px; color: var(--ui-muted); }}
.ui-side__title {{ font: 800 11px/1 var(--ui-head); letter-spacing: .12em; text-transform: uppercase; color: var(--ui-navy); margin-bottom: 8px; }}
.ui-side__row {{ display: flex; align-items: center; gap: 8px; margin: 5px 0; }}
.ui-dot {{ width: 8px; height: 8px; border-radius: 50%; flex: none; box-shadow: 0 0 0 3px rgba(0,0,0,.04); }}

/* ---------- hero: bright daytime sky ---------- */
.ui-hero {{
  position: relative; overflow: hidden; isolation: isolate;
  border-radius: 26px; padding: 30px 34px 28px; margin: 4px 0 20px;
  background: linear-gradient(118deg, #0F4C9C 0%, #1F6FC4 42%, #3FA9DA 78%, #7FD3EA 100%);
  box-shadow: 0 30px 60px -30px rgba(15,76,156,.55), inset 0 1px 0 rgba(255,255,255,.25);
  animation: ui-rise .6s ease-out both;
}}
.ui-hero::before {{
  content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(300px 220px at 88% 12%, rgba(255,214,120,.85), rgba(255,214,120,.25) 45%, transparent 72%),
    url("{_ROUTE_URI}") no-repeat right -10px top 0 / 470px 200px;
}}
.ui-hero::after {{   /* two soft clouds drifting slowly */
  content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(closest-side, rgba(255,255,255,.55), transparent) 0 0 / 260px 70px no-repeat,
    radial-gradient(closest-side, rgba(255,255,255,.40), transparent) 0 0 / 200px 54px no-repeat;
  background-position: 70% 88%, 92% 62%;
  animation: ui-clouds 22s ease-in-out infinite alternate;
}}
@keyframes ui-clouds {{ to {{ background-position: 62% 88%, 98% 60%; }} }}
.ui-hero__eyebrow {{
  display: inline-flex; align-items: center; gap: 8px;
  font: 700 11.5px/1 var(--ui-head); letter-spacing: .14em; text-transform: uppercase;
  color: #FFFFFF; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.35);
  padding: 7px 12px; border-radius: 999px; backdrop-filter: blur(6px);
}}
.ui-hero__title {{ font: 800 clamp(30px, 4.2vw, 46px)/1.06 var(--ui-head); letter-spacing: -.02em;
  margin: 14px 0 8px; color: #FFFFFF; text-shadow: 0 2px 18px rgba(8,40,90,.25); }}
.ui-hero__subtitle {{ max-width: 600px; color: #F1F7FF; font-size: 15.5px; line-height: 1.55; }}
.ui-chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
.ui-chip {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 700;
  color: #FFFFFF; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.35);
  padding: 6px 11px; border-radius: 999px; backdrop-filter: blur(6px); }}
.ui-chip--gold {{ color: var(--ui-navy); background: var(--ui-gold); border-color: transparent;
  box-shadow: 0 6px 16px -8px rgba(233,161,44,.9); }}
@media (max-width: 900px) {{
  .ui-hero {{ padding: 22px 20px 20px; }}
  .ui-hero::before {{ background: radial-gradient(220px 170px at 92% 6%, rgba(255,214,120,.8), transparent 72%); }}
}}

/* ---------- KPI cards ---------- */
.ui-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin: 0 0 18px; }}
.ui-kpi {{ position: relative; overflow: hidden; padding: 16px 18px 15px; border-radius: var(--ui-radius);
  background: var(--ui-card); border: 1px solid var(--ui-line); box-shadow: var(--ui-shadow);
  transition: transform .18s ease, box-shadow .18s ease; animation: ui-rise .55s ease-out both; }}
.ui-kpi:nth-child(2) {{ animation-delay: .05s; }} .ui-kpi:nth-child(3) {{ animation-delay: .10s; }}
.ui-kpi:nth-child(4) {{ animation-delay: .15s; }} .ui-kpi:nth-child(5) {{ animation-delay: .20s; }}
.ui-kpi::before {{ content: ""; position: absolute; left: 0; top: 0; height: 4px; width: 100%;
  background: linear-gradient(90deg, #F2B544, #FFD98A); }}
.ui-kpi--teal::before {{ background: linear-gradient(90deg, #0F86A0, #7FD3EA); }}
.ui-kpi:hover {{ transform: translateY(-3px); box-shadow: var(--ui-shadow-hover); }}
.ui-kpi__label {{ display: flex; align-items: center; gap: 10px; font: 700 11.5px/1.25 var(--ui-head);
  letter-spacing: .08em; text-transform: uppercase; color: var(--ui-muted); }}
.ui-kpi__icon {{ flex: none; width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center;
  font-size: 16px; background: linear-gradient(135deg, #FFF4D9, #FFE3A6); }}
.ui-kpi--teal .ui-kpi__icon {{ background: linear-gradient(135deg, #E0F5FA, #BDE8F2); }}
.ui-kpi__value {{ font: 800 clamp(23px, 1.2vw + 16px, 30px)/1.1 var(--ui-head); color: var(--ui-navy);
  margin-top: 12px; font-variant-numeric: tabular-nums; }}
.ui-kpi__unit {{ font-size: 14px; font-weight: 700; color: var(--ui-muted); margin-left: 5px; }}
.ui-kpi__note {{ font-size: 12.5px; color: var(--ui-muted); margin-top: 4px; line-height: 1.35; }}

/* ---------- before / after tiles ---------- */
.ui-compare {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 6px 0 14px; }}
.ui-compare__tile {{ padding: 14px 16px; border-radius: 16px; background: var(--ui-card); border: 1px solid var(--ui-line);
  box-shadow: var(--ui-shadow); animation: ui-rise .5s ease-out both; }}
.ui-compare__tile--changed {{ border-color: #F2B544; background: linear-gradient(180deg, #FFF9EA 0%, #FFFFFF 70%);
  box-shadow: 0 0 0 3px rgba(242,181,68,.18), var(--ui-shadow); }}
.ui-compare__label {{ font: 700 11.5px/1.2 var(--ui-head); letter-spacing: .08em; text-transform: uppercase; color: var(--ui-muted); }}
.ui-compare__values {{ display: flex; align-items: baseline; gap: 8px; margin-top: 8px; font-variant-numeric: tabular-nums; }}
.ui-compare__before {{ font: 700 18px/1 var(--ui-head); color: #8391A7; }}
.ui-compare__arrow {{ color: var(--ui-gold-deep); font-weight: 800; }}
.ui-compare__after {{ font: 800 27px/1 var(--ui-head); color: var(--ui-navy); }}
.ui-delta {{ display: inline-block; margin-top: 9px; font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 999px;
  color: var(--ui-muted); background: #EEF2F7; }}
.ui-delta--changed {{ color: var(--ui-navy); background: var(--ui-gold); }}

/* ---------- section headers ---------- */
.ui-section {{ display: flex; align-items: center; gap: 13px; margin: 28px 0 12px; }}
.ui-section__icon {{ flex: none; width: 40px; height: 40px; border-radius: 13px; display: grid; place-items: center; font-size: 19px;
  background: linear-gradient(135deg, #FFF1CF 0%, #DDF2FB 100%); border: 1px solid var(--ui-line); box-shadow: var(--ui-shadow); }}
.ui-section__title {{ font: 800 21px/1.2 var(--ui-head); color: var(--ui-navy); letter-spacing: -.01em; }}
.ui-section__caption {{ font-size: 13.5px; color: var(--ui-muted); margin-top: 3px; line-height: 1.45; }}

/* ---------- pipeline strip ---------- */
.ui-flow {{ display: flex; flex-wrap: wrap; align-items: stretch; gap: 10px; margin: 2px 0 8px; }}
.ui-flow__step {{ flex: 1 1 150px; min-width: 150px; padding: 14px 15px; border-radius: 16px;
  background: var(--ui-card); border: 1px solid var(--ui-line); box-shadow: var(--ui-shadow);
  transition: transform .18s ease; animation: ui-rise .55s ease-out both; }}
.ui-flow__step:hover {{ transform: translateY(-2px); }}
.ui-flow__tag {{ display: inline-block; font: 800 10.5px/1 var(--ui-head); letter-spacing: .12em; text-transform: uppercase;
  padding: 5px 8px; border-radius: 7px; color: #0B4F60; background: #D7F1F8; }}
.ui-flow__tag--bronze {{ color: #6B3A12; background: #F6D5B8; }}
.ui-flow__tag--silver {{ color: #334155; background: #E2E8F0; }}
.ui-flow__tag--gold {{ color: #6B4A00; background: #FCE3A0; }}
.ui-flow__name {{ font: 800 16px/1.25 var(--ui-head); color: var(--ui-navy); margin-top: 9px; }}
.ui-flow__meta {{ font-size: 12.5px; color: var(--ui-muted); margin-top: 3px; line-height: 1.4; }}
.ui-flow__arrow {{ flex: 0 0 26px; align-self: center; height: 2px; position: relative;
  background: repeating-linear-gradient(90deg, #E9A12C 0 6px, transparent 6px 11px);
  background-size: 22px 2px; animation: ui-flow 1.2s linear infinite; }}
.ui-flow__arrow::after {{ content: ""; position: absolute; right: -2px; top: -4px; border: 5px solid transparent;
  border-left-color: #E9A12C; border-right: 0; }}
@keyframes ui-flow {{ to {{ background-position: 22px 0; }} }}
@media (max-width: 760px) {{ .ui-flow__arrow {{ display: none; }} }}

/* ---------- small pieces ---------- */
.ui-badge {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 700;
  padding: 4px 10px; border-radius: 999px; margin: 2px 4px 2px 0; }}
.ui-note {{ font-size: 13.5px; color: var(--ui-muted); line-height: 1.55; }}
.ui-card {{ padding: 16px 18px; border-radius: var(--ui-radius); background: var(--ui-card); border: 1px solid var(--ui-line);
  box-shadow: var(--ui-shadow); }}
.ui-card__title {{ font: 800 15px/1.3 var(--ui-head); color: var(--ui-navy); margin-bottom: 9px; }}
.ui-kv {{ display: grid; grid-template-columns: auto 1fr; gap: 7px 14px; font-size: 13.5px; margin: 0; }}
.ui-kv dt {{ color: var(--ui-muted); }}
.ui-kv dd {{ margin: 0; color: var(--ui-navy); font-weight: 600; }}
.ui-footer {{ margin: 34px 0 6px; padding-top: 14px; border-top: 1px solid var(--ui-line); font-size: 12.5px;
  color: var(--ui-muted); display: flex; flex-wrap: wrap; gap: 6px 18px; justify-content: space-between; }}
@media (prefers-reduced-motion: reduce) {{
  .ui-hero, .ui-hero::after, .ui-kpi, .ui-compare__tile, .ui-flow__step, .ui-flow__arrow {{ animation: none; }}
  .ui-kpi, .ui-flow__step {{ transition: none; }}
}}
</style>
"""


def _e(text) -> str:
    """Escape text for HTML (also stops Streamlit reading $...$ as LaTeX)."""
    return html.escape(str(text), quote=True).replace("$", "&#36;")


def _html(markup: str) -> None:
    # One line, no indentation: Markdown would turn indented lines into code blocks.
    st.markdown(markup, unsafe_allow_html=True)


def apply_theme() -> None:
    """Inject the shared CSS. Call once per page, right after st.set_page_config()."""
    st.markdown(_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str = "", eyebrow: str = "", chips: list[str] | None = None,
         gold_chip: str | None = None) -> None:
    """Big sky-gradient banner at the top of a page."""
    chip_html = ""
    if gold_chip:
        chip_html += f'<span class="ui-chip ui-chip--gold">{_e(gold_chip)}</span>'
    chip_html += "".join(f'<span class="ui-chip">{_e(c)}</span>' for c in (chips or []))
    _html(
        '<div class="ui-hero">'
        + (f'<div class="ui-hero__eyebrow">✈︎ {_e(eyebrow)}</div>' if eyebrow else "")
        + f'<div class="ui-hero__title" role="heading" aria-level="1">{_e(title)}</div>'
        + (f'<div class="ui-hero__subtitle">{_e(subtitle)}</div>' if subtitle else "")
        + (f'<div class="ui-chips">{chip_html}</div>' if chip_html else "")
        + "</div>"
    )


def kpi_row(kpis: list[Kpi]) -> None:
    """A responsive row of KPI cards (wraps on small screens)."""
    cards = []
    for k in kpis:
        icon = f'<span class="ui-kpi__icon">{_e(k.icon)}</span>' if k.icon else ""
        unit = f'<span class="ui-kpi__unit">{_e(k.unit)}</span>' if k.unit else ""
        note = f'<div class="ui-kpi__note">{_e(k.note)}</div>' if k.note else ""
        accent = " ui-kpi--teal" if k.accent == "teal" else ""
        cards.append(f'<div class="ui-kpi{accent}"><div class="ui-kpi__label">{icon}{_e(k.label)}</div>'
                     f'<div class="ui-kpi__value">{_e(k.value)}{unit}</div>{note}</div>')
    _html('<div class="ui-kpis">' + "".join(cards) + "</div>")


def compare_row(items: list[tuple[str, str, str, str]]) -> None:
    """Before/after tiles. items = [(label, before_text, after_text, delta_text), ...];
    a tile is highlighted when its delta is not '0' / '±0' / ''."""
    tiles = []
    for label, before, after, delta in items:
        changed = delta not in ("", "0", "±0", "0.0", "±0.0", "no change")
        tiles.append(
            f'<div class="ui-compare__tile{" ui-compare__tile--changed" if changed else ""}">'
            f'<div class="ui-compare__label">{_e(label)}</div>'
            f'<div class="ui-compare__values"><span class="ui-compare__before">{_e(before)}</span>'
            f'<span class="ui-compare__arrow">→</span><span class="ui-compare__after">{_e(after)}</span></div>'
            f'<span class="ui-delta{" ui-delta--changed" if changed else ""}">{_e(delta or "no change")}</span></div>')
    _html('<div class="ui-compare">' + "".join(tiles) + "</div>")


def section(title: str, caption: str = "", icon: str = "") -> None:
    """Section header with an icon tile, title and one-line caption."""
    _html('<div class="ui-section">'
          + (f'<div class="ui-section__icon">{_e(icon)}</div>' if icon else "")
          + f'<div><div class="ui-section__title" role="heading" aria-level="2">{_e(title)}</div>'
          + (f'<div class="ui-section__caption">{_e(caption)}</div>' if caption else "")
          + "</div></div>")


def pipeline(steps: list[tuple[str, str, str, str]]) -> None:
    """Horizontal flow of steps. steps = [(tag, name, meta, tone), ...]
    tone: source | bronze | silver | gold (colours the tag)."""
    parts = []
    for i, (tag, name, meta, tone) in enumerate(steps):
        if i:
            parts.append('<div class="ui-flow__arrow" aria-hidden="true"></div>')
        tone_cls = f" ui-flow__tag--{tone}" if tone in ("bronze", "silver", "gold") else ""
        parts.append(f'<div class="ui-flow__step"><span class="ui-flow__tag{tone_cls}">{_e(tag)}</span>'
                     f'<div class="ui-flow__name">{_e(name)}</div><div class="ui-flow__meta">{_e(meta)}</div></div>')
    _html('<div class="ui-flow">' + "".join(parts) + "</div>")


def badge_html(text: str, tone: str = "neutral") -> str:
    """Status pill (icon + label + colour, never colour alone). Returns HTML for use inside other markup."""
    color, tint, icon = STATUS.get(tone, STATUS["neutral"])
    return f'<span class="ui-badge" style="color:{color};background:{tint}">{icon} {_e(text)}</span>'


def card(title: str, rows: list[tuple[str, str]]) -> None:
    """Small white info card with label/value rows."""
    body = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in rows)
    _html(f'<div class="ui-card"><div class="ui-card__title">{_e(title)}</div><dl class="ui-kv">{body}</dl></div>')


def note(text: str) -> None:
    """Muted helper text."""
    _html(f'<div class="ui-note">{_e(text)}</div>')


def footer(left: str = "IT8417 · Group 2 · Airline Flight Booking",
           right: str = "PostgreSQL · Databricks · MongoDB · pgvector") -> None:
    _html(f'<div class="ui-footer"><span>{_e(left)}</span><span>{_e(right)}</span></div>')


def card_container(key: str):
    """A white card around Streamlit elements (charts, tables, buttons):
        with ui.card_container("ontime"):
            st.altair_chart(chart)
    The key must be unique on the page."""
    return st.container(key=f"uicard_{key}")


def page_card(number: str, icon: str, title: str, text: str, tags: list[str], gold_tag: str = "") -> None:
    """Card describing one dashboard page (used on the home page, inside ui.card_container)."""
    tag_html = (f'<span class="ui-tag ui-tag--gold">{_e(gold_tag)}</span>' if gold_tag else "") + \
        "".join(f'<span class="ui-tag">{_e(t)}</span>' for t in tags)
    _html(f'<div class="ui-page"><div class="ui-page__top"><span class="ui-page__icon">{_e(icon)}</span>'
          f'<span class="ui-page__num">{_e(number)}</span></div>'
          f'<div class="ui-page__title" title="{_e(title)}">{_e(title)}</div><div class="ui-page__text">{_e(text)}</div>'
          f'<div class="ui-tags">{tag_html}</div></div>')


def coming_soon(text: str) -> None:
    """Placeholder the same size as an 'Open page' link (for pages not built yet)."""
    _html(f'<span class="ui-soon">⏳ {_e(text)}</span>')


def flow_cards(flows: list[tuple[str, str, str]]) -> None:
    """Grid of numbered data-flow cards. flows = [(number, 'From → To', purpose), ...]"""
    _html('<div class="ui-flows">' + "".join(
        f'<div class="ui-flowcard"><div class="ui-flowcard__num">{_e(n)}</div><div>'
        f'<div class="ui-flowcard__route">{_e(route)}</div><div class="ui-flowcard__text">{_e(text)}</div></div></div>'
        for n, route, text in flows) + "</div>")


def team_cards(members: list[tuple[str, str, str]]) -> None:
    """Grid of team member cards. members = [(name, role, owns), ...]"""
    _html('<div class="ui-team">' + "".join(
        f'<div class="ui-member"><div class="ui-member__avatar">{_e(name[:1])}</div><div>'
        f'<div class="ui-member__name">{_e(name)}</div><div class="ui-member__role">{_e(role)}<br>{_e(owns)}</div></div></div>'
        for name, role, owns in members) + "</div>")


def sidebar_status() -> None:
    """Small 'live databases' card for the bottom of the sidebar (call inside `with st.sidebar:`)."""
    rows = [("#336791", "Supabase PostgreSQL"), ("#7C4DFF", "pgvector"), ("#FF3621", "Databricks"), ("#00A35C", "MongoDB Atlas")]
    _html('<div class="ui-side"><div class="ui-side__title">Live databases</div>' + "".join(
        f'<div class="ui-side__row"><span class="ui-dot" style="background:{c}"></span>{_e(n)}</div>' for c, n in rows)
        + '<div style="margin-top:9px">IT8417 · Group 2</div></div>')

