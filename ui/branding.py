"""Fortna brand theme for the Streamlit UI."""

from __future__ import annotations

import streamlit as st

FORTNA_BLUE = "#2B5CFF"
FORTNA_BLACK = "#000000"
FORTNA_WHITE = "#FFFFFF"
FORTNA_GRAY = "#757575"
FORTNA_DIVIDER = "#E0E0E0"
FORTNA_BG = "#F5F5F5"
FORTNA_SITE = "https://www.fortna.com/"
HASLET_SITE_REF = (
    "https://fortna.atlassian.net/wiki/spaces/DS/pages/3064266909/UPS+-+Haslet+TX"
)


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

  .fortna-banner {{
    background: {FORTNA_BLACK};
    color: {FORTNA_WHITE};
    padding: 0.85rem 1.25rem;
    margin: -1rem -1rem 1.5rem -1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }}
  .fortna-banner a {{
    color: {FORTNA_WHITE} !important;
    text-decoration: none !important;
    font-weight: 700;
    letter-spacing: 0.12em;
    font-size: 1.05rem;
  }}
  .fortna-banner .fortna-product {{
    color: {FORTNA_WHITE};
    font-weight: 500;
    letter-spacing: 0.02em;
    opacity: 0.92;
  }}
  .fortna-banner .fortna-accent {{
    display: inline-block;
    width: 3px;
    height: 1.1rem;
    background: {FORTNA_BLUE};
    margin: 0 0.75rem;
    vertical-align: middle;
  }}
  .fortna-cta {{
    display: inline-block;
    border: 1px solid {FORTNA_WHITE};
    border-radius: 999px;
    padding: 0.35rem 0.9rem;
    color: {FORTNA_WHITE} !important;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    text-decoration: none !important;
  }}
</style>
""",
        unsafe_allow_html=True,
    )


def render_brand_banner(product_label: str = "OptiSweep Playbook Runtime") -> None:
    st.markdown(
        f"""
<div class="fortna-banner">
  <div>
    <a href="{FORTNA_SITE}" target="_blank" rel="noopener noreferrer">FORTNA</a>
    <span class="fortna-accent"></span>
    <span class="fortna-product">{product_label}</span>
  </div>
  <a class="fortna-cta" href="{FORTNA_SITE}" target="_blank" rel="noopener noreferrer">fortna.com</a>
</div>
""",
        unsafe_allow_html=True,
    )
