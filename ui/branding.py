"""Fortna brand theme for the Streamlit UI."""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

FORTNA_BLUE = "#2B5CFF"
FORTNA_BLACK = "#000000"
FORTNA_WHITE = "#FFFFFF"
FORTNA_GRAY = "#757575"
FORTNA_DIVIDER = "#E0E0E0"
FORTNA_BG = "#F5F5F5"
HASLET_SITE_REF = (
    "https://fortna.atlassian.net/wiki/spaces/DS/pages/3064266909/UPS+-+Haslet+TX"
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
FORTNA_LOGO_PATH = _STATIC_DIR / "fortna_logo.png"
OPTISWEEP_SYSTEM_PATH = _STATIC_DIR / "optisweep_system.png"


def apply_fortna_theme() -> None:
    st.markdown(
        f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&display=swap');

  html, body, [class*="css"] {{
    font-family: Montserrat, "Helvetica Neue", Helvetica, Arial, sans-serif;
  }}

  [data-testid="stHeader"] {{
    background: {FORTNA_BLACK};
  }}
  [data-testid="stHeader"] * {{
    color: {FORTNA_WHITE} !important;
  }}
  [data-testid="stToolbar"] button {{
    color: {FORTNA_WHITE} !important;
  }}

  [data-testid="stSidebar"] {{
    background: {FORTNA_WHITE};
    border-right: 1px solid {FORTNA_DIVIDER};
  }}
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] a {{
    color: {FORTNA_GRAY};
  }}
  [data-testid="stSidebarNav"] a {{
    color: {FORTNA_GRAY} !important;
    border-bottom: 1px solid {FORTNA_DIVIDER};
    border-radius: 0 !important;
  }}
  [data-testid="stSidebarNav"] a[aria-current="page"],
  [data-testid="stSidebarNav"] a:hover {{
    color: {FORTNA_BLUE} !important;
    background: transparent !important;
  }}

  .stApp {{
    background: {FORTNA_WHITE};
  }}

  h1, h2, h3 {{
    color: {FORTNA_BLACK} !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
  }}

  a {{
    color: {FORTNA_BLUE} !important;
  }}

  div[data-testid="stButton"] > button[kind="primary"],
  button[data-testid="baseButton-primary"] {{
    background: {FORTNA_BLUE} !important;
    color: {FORTNA_WHITE} !important;
    border: none !important;
    border-radius: 999px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding-left: 1.25rem !important;
    padding-right: 1.25rem !important;
  }}
  div[data-testid="stButton"] > button[kind="secondary"],
  button[data-testid="baseButton-secondary"] {{
    border-radius: 999px !important;
    border: 1px solid {FORTNA_BLACK} !important;
    color: {FORTNA_BLACK} !important;
    background: {FORTNA_WHITE} !important;
    font-weight: 600 !important;
  }}

  [data-testid="stChatInput"] textarea,
  .stTextInput input,
  .stTextArea textarea {{
    border-radius: 8px !important;
  }}

  hr {{
    border-color: {FORTNA_DIVIDER} !important;
  }}

  div[data-testid="stHorizontalBlock"] {{
    align-items: center;
  }}

  .fortna-banner {{
    background: {FORTNA_BLACK};
    color: {FORTNA_WHITE};
    display: flex;
    align-items: center;
    gap: 1rem;
    width: 100vw;
    max-width: 100vw;
    margin-left: calc(50% - 50vw);
    margin-right: calc(50% - 50vw);
    margin-bottom: 0.75rem;
    padding: 0.55rem clamp(1rem, 3vw, 2.5rem);
    box-sizing: border-box;
  }}
  .fortna-banner img {{
    height: 28px;
    width: auto;
    display: block;
  }}
  .fortna-banner .fortna-product {{
    color: {FORTNA_WHITE};
    font-weight: 500;
    letter-spacing: 0.02em;
    font-size: 1.05rem;
    margin: 0;
  }}
  .fortna-hero {{
    display: flex;
    justify-content: center;
    margin: 0 0 1.25rem 0;
  }}
  .fortna-hero img {{
    width: min(420px, 100%);
    max-height: 220px;
    object-fit: contain;
    border-radius: 0;
  }}
</style>
""",
        unsafe_allow_html=True,
    )


def render_brand_banner(
    product_label: str = "OptiSweep AI Troubleshooting Assistant",
) -> None:
    logo_html = '<span class="fortna-product">FORTNA</span>'
    if FORTNA_LOGO_PATH.is_file():
        encoded = base64.b64encode(FORTNA_LOGO_PATH.read_bytes()).decode("ascii")
        logo_html = f'<img src="data:image/png;base64,{encoded}" alt="FORTNA" />'
    st.markdown(
        f'<div class="fortna-banner">{logo_html}'
        f'<p class="fortna-product">{product_label}</p></div>',
        unsafe_allow_html=True,
    )


def render_optisweep_hero() -> None:
    if not OPTISWEEP_SYSTEM_PATH.is_file():
        return
    encoded = base64.b64encode(OPTISWEEP_SYSTEM_PATH.read_bytes()).decode("ascii")
    st.markdown(
        f'<div class="fortna-hero">'
        f'<img src="data:image/png;base64,{encoded}" '
        f'alt="OptiSweep system" /></div>',
        unsafe_allow_html=True,
    )
