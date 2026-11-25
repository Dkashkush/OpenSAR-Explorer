# Copyright (c) 2026 Deepa Kumari. All rights reserved. See LICENSE.
"""Look of the web app: one stylesheet and the small HTML pieces (hero, module banners, chips, footer) shared by
all pages. Colours: deep ocean blue for Ground Motion, forest green for Forests & Biomass, on a soft off-white page
with white cards. Fonts (Inter for text, Plus Jakarta Sans for headings) are served by the app itself
(static/fonts, SIL Open Font License), so visitors' browsers do not contact a font service."""

from __future__ import annotations

import html

ACCENTS = {
    "motion": {"accent": "#1f5f8b", "deep": "#0b2e4f", "soft": "#e8f1f8", "ink": "#123b5c"},
    "forest": {"accent": "#2a7a4f", "deep": "#0f3d28", "soft": "#e8f4ec", "ink": "#174a30"},
    "neutral": {"accent": "#1f5f8b", "deep": "#14324a", "soft": "#eef2f5", "ink": "#1f2933"},
}

CSS = """
<style>
:root{--accent:#1f5f8b;--accent-deep:#0b2e4f;--accent-soft:#e8f1f8;--accent-ink:#123b5c;
  --ink:#17212b;--ink2:#4a5561;--muted:#6b7682;--line:#e1e6ea;--card:#ffffff;--page:#f6f8f7;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.04)}
[data-testid="stMainBlockContainer"]{max-width:1220px;padding-top:4.2rem;padding-bottom:1rem}
[data-testid="stHeader"]{background:rgba(246,248,247,.85);backdrop-filter:blur(6px)}
h1,h2,h3,h4{letter-spacing:-.01em;color:var(--ink)}

/* ---------- hero (Home) */
.hero{position:relative;overflow:hidden;border-radius:20px;padding:44px 44px 38px;margin:4px 0 26px;color:#fff;
  background:radial-gradient(circle at 88% 18%,rgba(255,255,255,.10) 0 2px,transparent 3px),
  radial-gradient(circle at 86% 30%,transparent 0 70px,rgba(255,255,255,.08) 71px 72px,transparent 73px 120px,
  rgba(255,255,255,.07) 121px 122px,transparent 123px 175px,rgba(255,255,255,.06) 176px 177px,transparent 178px),
  linear-gradient(120deg,#0b2e4f 0%,#1f5f8b 55%,#2a7a4f 100%)}
.hero .eyebrow{display:inline-block;font-size:.8rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  color:#cfe3f3;margin-bottom:10px}
.hero h1{color:#fff;font-size:2.6rem;line-height:1.1;margin:0 0 12px;padding:0;font-weight:800}
.hero p.lead{font-size:1.12rem;line-height:1.55;color:#e4eef6;max-width:720px;margin:0 0 18px}
.hero .by{font-size:.95rem;color:#cfe3f3;margin:0}
.hero .by strong{color:#fff}
.hero .pills{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.hero .pill{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);color:#fff;border-radius:999px;
  padding:4px 12px;font-size:.85rem;font-weight:500}

/* ---------- module banner (module pages) */
.banner{position:relative;overflow:hidden;display:flex;gap:18px;align-items:center;border-radius:16px;
  padding:22px 26px;margin:2px 0 18px;color:#fff;
  background:radial-gradient(circle at 92% 50%,transparent 0 46px,rgba(255,255,255,.08) 47px 48px,transparent 49px 86px,
  rgba(255,255,255,.07) 87px 88px,transparent 89px),linear-gradient(110deg,var(--accent-deep),var(--accent))}
.banner .icon{flex:none;width:54px;height:54px;border-radius:14px;background:rgba(255,255,255,.16);
  border:1px solid rgba(255,255,255,.3);display:flex;align-items:center;justify-content:center;font-size:1.7rem}
.banner .kicker{font-size:.78rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:rgba(255,255,255,.75)}
.banner h1{color:#fff;font-size:1.65rem;line-height:1.2;margin:2px 0 4px;padding:0;font-weight:800}
.banner p{margin:0;color:rgba(255,255,255,.88);font-size:.98rem;line-height:1.45;max-width:820px}

/* ---------- cards: every keyed container whose key starts with card_ or step_ */
[class*="st-key-card_"],[class*="st-key-step_"],[class*="st-key-panel_"]{background:var(--card);border-color:var(--line)!important;
  border-radius:16px!important;box-shadow:var(--shadow)}
[class*="st-key-step_"]{padding:6px 8px 8px}
[class*="st-key-card_"] img,[class*="st-key-panel_"] img{border-radius:10px}
.card-title{display:flex;align-items:center;gap:10px;font-family:"Plus Jakarta Sans",Inter,sans-serif;font-weight:700;
  font-size:1.25rem;color:var(--ink);margin:4px 0 6px}
.card-title .dot{width:34px;height:34px;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;
  font-size:1.1rem}
.card-text{color:var(--ink2);font-size:.97rem;line-height:1.55;margin:0 0 10px}
ul.ticks{list-style:none;padding:0;margin:0 0 12px}
ul.ticks li{position:relative;padding:4px 0 4px 26px;color:var(--ink2);font-size:.95rem;line-height:1.45}
ul.ticks li:before{content:"";position:absolute;left:2px;top:9px;width:14px;height:14px;border-radius:50%;
  background:var(--tick,#1f5f8b);opacity:.16}
ul.ticks li:after{content:"";position:absolute;left:7px;top:12px;width:4px;height:7px;border:solid var(--tick,#1f5f8b);
  border-width:0 2px 2px 0;transform:rotate(45deg)}

/* ---------- step headers */
.step{display:flex;align-items:center;gap:12px;font-family:"Plus Jakarta Sans",Inter,sans-serif;font-size:1.16rem;
  font-weight:700;margin:4px 0 4px;color:var(--ink)}
.step .n{background:var(--accent);color:#fff;border-radius:10px;min-width:30px;height:30px;display:inline-flex;
  align-items:center;justify-content:center;font-size:.92rem;font-weight:700}
.hint{color:var(--muted);font-size:.93rem;margin:0 0 12px 42px}

/* ---------- section titles */
.section{display:flex;align-items:baseline;gap:12px;margin:30px 0 12px}
.section h2{font-size:1.45rem;margin:0;padding:0;font-weight:800}
.section .sub{color:var(--muted);font-size:.95rem}
.eyebrow-dark{font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);
  margin:28px 0 4px}

/* ---------- how-it-works tiles */
.how{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:6px 0 4px}
@media(max-width:800px){.how{grid-template-columns:1fr}}
.how .tile{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 18px 16px;box-shadow:var(--shadow)}
.how .num{display:inline-flex;width:30px;height:30px;border-radius:9px;align-items:center;justify-content:center;
  background:var(--accent-soft);color:var(--accent);font-weight:700;margin-bottom:8px}
.how h4{margin:0 0 4px;padding:0;font-size:1.05rem}
.how p{margin:0;color:var(--ink2);font-size:.93rem;line-height:1.5}

/* ---------- chips */
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 2px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:.86rem;
  color:var(--ink2)}
.chip b{color:var(--ink);font-weight:600}
.badge{display:inline-block;background:#fff4d6;color:#7a5200;border:1px solid #f0d58a;border-radius:999px;
  padding:2px 10px;font-size:.8rem;font-weight:600;vertical-align:middle}

/* ---------- widgets */
[data-testid="stMetric"]{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;
  box-shadow:var(--shadow)}
[data-testid="stMetricLabel"]{color:var(--muted)}
[data-testid="stMetricValue"]{font-family:"Plus Jakarta Sans",Inter,sans-serif;font-weight:700;color:var(--accent-ink)}
[data-testid="stBaseButton-primary"]{background:var(--accent);border-color:var(--accent);font-weight:600;
  box-shadow:0 1px 2px rgba(16,24,40,.12)}
[data-testid="stBaseButton-primary"]:hover{background:var(--accent-deep);border-color:var(--accent-deep)}
[data-testid="stPageLink-NavLink"]{background:var(--accent);border-radius:10px;padding:6px 14px;width:fit-content}
[data-testid="stPageLink-NavLink"] p,[data-testid="stPageLink-NavLink"] span{color:#fff!important;font-weight:600}
[data-testid="stPageLink-NavLink"]:hover{background:var(--accent-deep)}
[data-testid="stTabs"] [data-baseweb="tab-list"]{gap:4px;border-bottom:1px solid var(--line)}
[data-testid="stTab"]{padding:8px 14px;border-radius:10px 10px 0 0}
[data-testid="stTabPanel"]{background:var(--card);border:1px solid var(--line);border-top:0;
  border-radius:0 0 16px 16px;padding:18px 22px 20px;box-shadow:var(--shadow)}
[data-testid="stTab"][aria-selected="true"] p{color:var(--accent);font-weight:700}
[data-testid="stExpander"] details{background:var(--card);border-color:var(--line);border-radius:12px}
[data-testid="stExpander"] summary p{font-weight:600}
.st-key-in_short{background:var(--accent-soft)!important;border:1px solid transparent!important;
  border-left:5px solid var(--accent)!important;border-radius:14px!important}
.st-key-in_short h4{margin-top:0}

.st-key-card_home_forest [data-testid="stPageLink-NavLink"]{background:#2a7a4f}
.st-key-card_home_forest [data-testid="stPageLink-NavLink"]:hover{background:#0f3d28}
[class*="st-key-card_home_"]{padding:6px 6px 10px}
[data-testid="stHorizontalBlock"]:has(.st-key-card_home_motion){align-items:stretch}
[data-testid="stHorizontalBlock"]:has(.st-key-card_home_motion) [data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"]:has(.st-key-card_home_motion) [data-testid="stColumn"] > div > div{height:100%}
[class*="st-key-card_home_"]{height:100%}
[class*="st-key-card_home_"] [data-testid="stElementContainer"]:has([data-testid="stPageLink"]){margin-top:auto}
[class*="st-key-card_home_"] img{aspect-ratio:2.6/1;object-fit:cover;object-position:center top;
  border:1px solid var(--line)}

.st-key-downloads [data-testid="stDownloadButton"] button{width:100%;justify-content:flex-start}

/* ---------- phones */
@media(max-width:640px){
  .hero{padding:28px 22px 26px;border-radius:16px}
  .hero h1{font-size:2rem}
  .hero p.lead{font-size:1rem}
  .banner{padding:18px 18px}
  .banner .icon{display:none}
  .banner h1{font-size:1.35rem}
  .section{flex-wrap:wrap;gap:2px 12px}
  .hint{margin-left:0}
  [data-testid="stMainBlockContainer"]{padding-top:3.6rem}
}

/* ---------- footer */
.app-footer{display:grid;grid-template-columns:1.3fr 1.6fr 1fr;gap:28px;border-top:1px solid var(--line);
  margin-top:48px;padding:22px 2px 6px;color:var(--muted);font-size:.84rem;line-height:1.55}
@media(max-width:900px){.app-footer{grid-template-columns:1fr}}
.app-footer h5{font-family:"Plus Jakarta Sans",Inter,sans-serif;font-size:.8rem;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink2);margin:0 0 8px;padding:0}
.app-footer a{color:var(--accent);text-decoration:none}
.app-footer a:hover{text-decoration:underline}
.app-footer .brand{font-family:"Plus Jakarta Sans",Inter,sans-serif;font-weight:800;color:var(--ink);font-size:1rem}
.app-footer ul{list-style:none;padding:0;margin:0}
.app-footer li{margin:0 0 4px}
</style>
"""


def accent_css(module: str) -> str:
    """Page colours for one module (the CSS variables above), injected by that page only."""
    a = ACCENTS.get(module, ACCENTS["neutral"])
    return (f"<style>:root{{--accent:{a['accent']};--accent-deep:{a['deep']};--accent-soft:{a['soft']};"
            f"--accent-ink:{a['ink']}}}ul.ticks{{--tick:{a['accent']}}}</style>")


def hero(title: str, lead: str, author: str, pills: list[str]) -> str:
    e = html.escape
    chips = "".join(f'<span class="pill">{e(p)}</span>' for p in pills)
    return (f'<div class="hero"><div class="eyebrow">Satellite radar, explained in plain language</div>'
            f"<h1>{e(title)}</h1><p class=\"lead\">{e(lead)}</p>"
            f'<p class="by">Created by <strong>{e(author)}</strong></p><div class="pills">{chips}</div></div>')


def banner(icon: str, kicker: str, title: str, text: str) -> str:
    e = html.escape
    return (f'<div class="banner"><div class="icon">{icon}</div><div><div class="kicker">{e(kicker)}</div>'
            f"<h1>{e(title)}</h1><p>{e(text)}</p></div></div>")


def card_title(icon: str, title: str, module: str) -> str:
    a = ACCENTS.get(module, ACCENTS["neutral"])
    return (f'<div class="card-title"><span class="dot" style="background:{a["soft"]}">{icon}</span>'
            f"{html.escape(title)}</div>")


def ticks(items: list[str], module: str = "neutral") -> str:
    a = ACCENTS.get(module, ACCENTS["neutral"])
    lis = "".join(f"<li>{html.escape(i)}</li>" for i in items)
    return f'<ul class="ticks" style="--tick:{a["accent"]}">{lis}</ul>'


def chips(items: list[tuple[str, str]]) -> str:
    return '<div class="chips">' + "".join(f'<span class="chip"><b>{html.escape(a)}</b> {html.escape(b)}</span>'
                                           for a, b in items) + "</div>"


def section(title: str, sub: str = "") -> str:
    s = f'<span class="sub">{html.escape(sub)}</span>' if sub else ""
    return f'<div class="section"><h2>{html.escape(title)}</h2>{s}</div>'


def how(tiles: list[tuple[str, str]]) -> str:
    cells = "".join(f'<div class="tile"><div class="num">{i + 1}</div><h4>{html.escape(t)}</h4>'
                    f"<p>{html.escape(d)}</p></div>" for i, (t, d) in enumerate(tiles))
    return f'<div class="how">{cells}</div>'
