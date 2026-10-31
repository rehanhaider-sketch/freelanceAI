import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime
from html import escape

import streamlit as st
from google import genai
from google.genai import types

from translations import AI_LANGUAGE_NAME, LANGUAGES, POSITION, TEXTS

# ---------- Page setup ----------
def make_icon(size=128, dark=True):
    """The Gigflare icon: an arc floor lamp that is also the letter f. Used for the browser tab."""
    try:
        from PIL import Image, ImageDraw
        k = 4 * size / 120  # draw 4 times bigger, then shrink for smooth edges
        big = int(size * 4)
        fg = (180, 240, 128, 255) if dark else (13, 59, 42, 255)
        shade = (242, 251, 245, 255) if dark else (13, 59, 42, 255)
        tile = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        if dark:
            for y in range(big):  # soft top-left to bottom-right shade of dark green
                f = y / big
                c = (int(15 - 9 * f), int(74 - 39 * f), int(51 - 25 * f), 255)
                td.line([(0, y), (big, y)], fill=c)
        else:
            td.rectangle((0, 0, big, big), fill=(180, 240, 128, 255))
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(27 * k), fill=255)
        art = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        # light cone with a fading top-to-bottom glow
        cone = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cone)
        for y in range(48 * 10, 110 * 10):
            yy = y / 10
            u = (yy - 48) / 62
            left, right = 64 + (50 - 64) * u, 98 + (112 - 98) * u
            alpha = int(255 * (0.6 if dark else 0.4) * (1 - u))
            cd.line([(left * k, yy * k), (right * k, yy * k)], fill=fg[:3] + (alpha,), width=max(1, int(k / 5)))
        art.alpha_composite(cone)
        d = ImageDraw.Draw(art)

        def stroke(points, width):
            r = width * k / 2
            for (x1, y1), (x2, y2) in zip(points, points[1:]):  # stamp small circles along the path: smooth and round
                steps = max(2, int(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 * 4))
                for n in range(steps + 1):
                    x = x1 + (x2 - x1) * n / steps
                    y = y1 + (y2 - y1) * n / steps
                    d.ellipse((x * k - r, y * k - r, x * k + r, y * k + r), fill=fg)

        curve = []
        for n in range(41):  # the arm of the lamp: a smooth curve from the stem up and over
            u = n / 40
            x = (1 - u) ** 3 * 40 + 3 * (1 - u) ** 2 * u * 40 + 3 * (1 - u) * u ** 2 * 56 + u ** 3 * 78
            y = (1 - u) ** 3 * 56 + 3 * (1 - u) ** 2 * u * 32 + 3 * (1 - u) * u ** 2 * 22 + u ** 3 * 24
            curve.append((x, y))
        stroke([(40, 106), (40, 56)] + curve, 10)
        stroke([(24, 66), (58, 66)], 10)
        stroke([(80, 24), (80, 32)], 5)
        d.polygon([(70 * k, 32 * k), (90 * k, 32 * k), (100 * k, 48 * k), (60 * k, 48 * k)], fill=shade)
        out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        out.paste(tile, (0, 0), mask)
        out.alpha_composite(art)
        out.putalpha(Image.composite(out.getchannel("A"), Image.new("L", (big, big), 0), mask))
        return out.resize((size, size), Image.LANCZOS)
    except Exception:
        return "G"


# Always use the light theme, even if the phone or browser is in dark mode.
# (The same settings are in .streamlit/config.toml; this is a backup in case that file is missing.)
for _name, _value in {"theme.base": "light", "theme.primaryColor": "#16a05a", "theme.backgroundColor": "#ffffff",
                      "theme.secondaryBackgroundColor": "#f3faf5", "theme.textColor": "#0f2a1a"}.items():
    try:
        st._config.set_option(_name, _value)
    except Exception:
        pass

st.set_page_config(page_title="Gigflare", page_icon=make_icon(), layout="wide")

# ---------- Languages ----------
def t(text, **fill):
    """Give back the text in the chosen language. If there is no translation, the English text is used.
    Pieces like {ai} in the text are filled in from the extra arguments."""
    lang = st.session_state.get("lang", "en")
    if text and lang != "en" and text in TEXTS:
        text = TEXTS[text][POSITION[lang]]
    return text.format(**fill) if fill else text


def lang_picker(where):
    """A small globe button that opens the list of languages."""
    names = list(LANGUAGES)
    current = next(n for n, code in LANGUAGES.items() if code == st.session_state.get("lang", "en"))
    wkey = "widget_lang_" + where
    if st.session_state.get(wkey) != current:
        st.session_state[wkey] = current
    with st.popover(current, icon=":material/language:", key="langsel_" + where):
        st.markdown(f'<p class="aihead">{t("Language")}</p>', unsafe_allow_html=True)
        st.radio(
            "Language", names, key=wkey, label_visibility="collapsed",
            on_change=lambda: st.session_state.update(lang=LANGUAGES[st.session_state[wkey]]),
        )


# The Gigflare logo: a lamp with a glowing bulb (drawn as a tiny picture)
LOGO_SVG = (
    '<svg viewBox="0 0 120 120" width="100%" height="100%" aria-hidden="true">'
    '<defs><linearGradient id="gfbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f4a33"/><stop offset="1" stop-color="#06231a"/></linearGradient>'
    '<linearGradient id="gfbeam" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#b4f080" stop-opacity=".6"/><stop offset="1" stop-color="#b4f080" stop-opacity="0"/></linearGradient></defs>'
    '<rect width="120" height="120" rx="27" fill="url(#gfbg)"/><rect x="1" y="1" width="118" height="118" rx="26" fill="none" stroke="#9be564" stroke-opacity=".35" stroke-width="2"/>'
    '<path d="M64 48L98 48L112 110L50 110Z" fill="url(#gfbeam)"/>'
    '<path d="M40 106V56C40 32 56 22 78 24" fill="none" stroke="#b4f080" stroke-width="10" stroke-linecap="round"/>'
    '<line x1="24" y1="66" x2="58" y2="66" stroke="#b4f080" stroke-width="10" stroke-linecap="round"/>'
    '<line x1="80" y1="24" x2="80" y2="32" stroke="#b4f080" stroke-width="5" stroke-linecap="round"/>'
    '<path d="M70 32L90 32L100 48L60 48Z" fill="#f2fbf5"/></svg>'
)

# ---------- Look and feel (CSS) ----------
# CSS is the language that controls colours, shapes and spacing of a web page.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    /* Fonts (only on text, so the icons keep working) */
    h1, h2, h3, h4, p, li, label, button, input, textarea, summary {
        font-family: 'Inter', 'Noto Sans', sans-serif;
    }

    /* ----- Background: dark green, soft grid and a slanted green panel ----- */
    .stApp {
        background:
            radial-gradient(circle at 12% 8%, rgba(22,160,90, 0.10) 0%, transparent 38%),
            linear-gradient(180deg, #ffffff 0%, #ffffff 55%, #ffffff 100%);
        color: #0f2a1a;
    }
    .stApp::before {                      /* slanted panel on the right, like the sample designs */
        content: ""; position: fixed; top: 0; right: 0; width: 58vw; height: 100vh;
        z-index: 0; pointer-events: none;
        background: linear-gradient(160deg, rgba(10,107,71, 0.55) 0%, rgba(10,107,71, 0) 70%);
        clip-path: polygon(32% 0, 100% 0, 100% 100%, 0 100%);
    }
    .stApp::after {                       /* faint grid lines */
        content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
        background-image:
            linear-gradient(rgba(22,160,90, 0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(22,160,90, 0.04) 1px, transparent 1px);
        background-size: 64px 64px;
    }
    div[data-testid="stAppViewContainer"] { position: relative; z-index: 1; }
    header[data-testid="stHeader"] { background: transparent; }

    /* ----- Sidebar ----- */
    section[data-testid="stSidebar"] { background: #06180f; border-right: 1px solid #cfe8d6; }
    .brand { display: flex; align-items: center; gap: 12px; margin: 8px 0 22px 0; }
    .logo {
        width: 40px; height: 40px; border-radius: 10px; color: #ffffff; font-size: 20px; font-weight: 700;
        background: #16a05a; display: flex; align-items: center; justify-content: center;
    }
    .brand b { font-size: 17px; color: #fff; }
    .brand small { color: #5a7766; font-size: 12px; }

    /* Menu: radio buttons turned into a simple list */
    div[role="radiogroup"] { gap: 4px; }
    div[role="radiogroup"] > div { width: 100%; }
    label[data-testid="stRadioOption"] {
        display: flex; box-sizing: border-box; width: 100%;
        padding: 9px 14px; border-radius: 8px; background: transparent;
        border: 1px solid transparent; transition: background 0.15s ease;
    }
    label[data-testid="stRadioOption"] > div > div:first-child { display: none; }   /* hide the round dot */
    label[data-testid="stRadioOption"]:hover { background: #f3faf5; }
    label[data-testid="stRadioOption"][data-selected="true"] {
        background: rgba(22,160,90, 0.14); box-shadow: inset 3px 0 0 #16a05a;
    }
    label[data-testid="stRadioOption"] p { color: #3d5c4a; font-weight: 500; }
    label[data-testid="stRadioOption"][data-selected="true"] p { color: #fff; }

    /* Account box in the sidebar */
    .account { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .avatar {
        width: 38px; height: 38px; border-radius: 50%; background: #0a6b47; color: #fff;
        display: flex; align-items: center; justify-content: center; font-weight: 700;
    }
    .account b { color: #fff; font-size: 14px; }
    .account small { color: #5a7766; }

    /* ----- Small pieces ----- */
    .chip { display: inline-block; padding: 5px 12px; border-radius: 6px; font-size: 13px; font-weight: 500; }
    .chip-ok { background: rgba(22,160,90, 0.14); color: #16a05a; border: 1px solid rgba(22,160,90, 0.4); }
    .chip-no { background: rgba(227, 179, 65, 0.15); color: #e3b341; border: 1px solid rgba(227, 179, 65, 0.4); }
    .chip-line { background: rgba(255, 255, 255, 0.06); color: #14693a; border: 1px solid #cfe8d6; margin: 0 8px 8px 0; }
    .tag {
        display: inline-block; padding: 4px 10px; border-radius: 4px;
        background: rgba(22,160,90, 0.13); color: #16a05a;
        font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
    }
    .lime { color: #16a05a; }
    .msym {
        font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal;
        font-size: 28px; line-height: 1; display: inline-block; white-space: nowrap;
    }

    /* ----- Top bar and big headings ----- */
    .topbar { display: flex; align-items: center; justify-content: space-between; padding: 6px 0 24px 0; }
    .topbar .brand { margin: 0; }
    .bighead { font-size: 46px; line-height: 1.1; font-weight: 800; color: #fff; margin: 18px 0 14px 0; }
    .lead { color: #3d5c4a; font-size: 18px; line-height: 1.6; margin: 0 0 20px 0; }
    div[data-testid="stMarkdownContainer"] p.sectionhead { font-size: 30px; font-weight: 700; color: #fff; margin: 40px 0 6px 0; }
    div[data-testid="stMarkdownContainer"] p.sectionsub { color: #5a7766; font-size: 16px; margin: 0 0 22px 0; }

    /* ----- Page banner (top of every tool page) ----- */
    .pagebanner {
        display: flex; align-items: center; gap: 18px; position: relative; overflow: hidden;
        background: linear-gradient(120deg, #0a6b47 0%, #0d3b2a 75%);
        border: 1px solid #cfe8d6; border-radius: 16px; padding: 22px 26px; margin-bottom: 22px;
    }
    .pagebanner .ic {
        width: 54px; height: 54px; border-radius: 14px; background: #16a05a; color: #ffffff;
        display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }
    .pagebanner h1 { margin: 0; padding: 0; font-size: 30px; font-weight: 700; color: #fff; }
    .pagebanner p { margin: 4px 0 0 0; color: #cfe8d8; }

    /* ----- Dashboard hero ----- */
    .hero2 {
        background: linear-gradient(120deg, #0a6b47 0%, #0d3b2a 70%);
        border: 1px solid #cfe8d6; border-radius: 18px; padding: 34px 36px; margin-bottom: 24px;
    }
    .hero2 h1 { font-size: 38px; font-weight: 800; color: #fff; margin: 14px 0 8px 0; padding: 0; }
    .hero2 p { color: #cfe8d8; font-size: 17px; margin: 0; }

    /* ----- Cards ----- */
    .card {
        background: #f3faf5; border: 1px solid #cfe8d6; border-radius: 14px;
        padding: 22px; min-height: 200px; margin-bottom: 10px; transition: border-color 0.15s ease;
    }
    .card:hover { border-color: #16a05a; }
    .card h3 { margin: 14px 0 6px 0; padding: 0; color: #fff; font-size: 19px; font-weight: 600; }
    .card p { color: #5a7766; margin: 0; font-size: 15px; line-height: 1.55; }
    .stepcard { min-height: 150px; }
    .num {
        display: inline-flex; width: 34px; height: 34px; border-radius: 50%; background: #16a05a; color: #ffffff;
        align-items: center; justify-content: center; font-weight: 700;
    }
    .tip {
        background: #f3faf5; border: 1px solid #cfe8d6; border-left: 3px solid #16a05a;
        border-radius: 10px; padding: 14px 16px; color: #5a7766; font-size: 14px; line-height: 1.5; height: 100%;
    }
    .tip b { display: block; color: #fff; margin-bottom: 4px; font-size: 15px; }
    .expect { background: #f3faf5; border: 1px dashed #8fd0a3; border-radius: 14px; padding: 22px 24px; }
    .expect h3 { margin: 12px 0 8px 0; padding: 0; color: #fff; font-size: 20px; }
    .expect ul { margin: 0; padding-left: 20px; color: #3d5c4a; line-height: 1.9; }
    .step {
        background: #f3faf5; border: 1px solid #cfe8d6; border-radius: 10px;
        padding: 13px 18px; margin-bottom: 10px; color: #0f2a1a;
    }
    .step span {
        display: inline-block; width: 26px; height: 26px; line-height: 26px; text-align: center;
        border-radius: 50%; margin-right: 12px; font-weight: 700; color: #ffffff; background: #16a05a;
    }

    /* ----- Sample result card (white, like the sample designs) ----- */
    .mock {
        background: #ffffff; color: #0b1f17; border-radius: 16px; padding: 22px 24px;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.35);
    }
    .mock-head { display: flex; align-items: center; justify-content: space-between; font-weight: 700; margin-bottom: 12px; }
    .mock-chip { background: #dff6c8; color: #25570b; font-size: 12px; padding: 4px 10px; border-radius: 6px; font-weight: 600; }
    .mock p { color: #24362c; line-height: 1.65; margin: 0 0 14px 0; }
    .mock-tags span { display: inline-block; background: #eef2ef; color: #3b4d43; font-size: 12px; padding: 4px 10px; border-radius: 6px; margin-right: 6px; }

    /* ----- Green call-to-action band and footer ----- */
    .cta {
        background: linear-gradient(120deg, #0a6b47, #06452d); border: 1px solid #cfe8d6;
        border-radius: 20px; padding: 40px 30px; text-align: center; margin: 40px 0 10px 0;
    }
    .cta h2 { color: #fff; margin: 0 0 8px 0; padding: 0; font-size: 30px; font-weight: 700; }
    .cta p { color: #cfe8d8; margin: 0; }
    .footer {
        border-top: 1px solid #cfe8d6; margin-top: 40px; padding: 20px 0 6px 0; color: #5a7766;
        font-size: 14px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
    }

    /* ----- Developer page ----- */
    .devcard {
        display: flex; align-items: center; gap: 24px; flex-wrap: wrap;
        background: linear-gradient(120deg, #0a6b47 0%, #0d3b2a 70%);
        border: 1px solid #cfe8d6; border-radius: 18px; padding: 30px; margin-bottom: 24px;
    }
    .devavatar {
        width: 96px; height: 96px; border-radius: 50%; background: #16a05a; color: #ffffff;
        display: flex; align-items: center; justify-content: center; font-size: 36px; font-weight: 800;
    }
    .devcard h2 { color: #fff; margin: 0 0 4px 0; padding: 0; font-size: 32px; font-weight: 800; }
    .devcard p { color: #cfe8d8; margin: 0 0 12px 0; }

    /* ----- Streamlit parts ----- */
    div[data-testid="stMetric"] {
        background: #f3faf5; border: 1px solid #cfe8d6; border-radius: 14px; padding: 16px 20px;
    }
    div[data-testid="stExpander"] { border-radius: 10px; border-color: #cfe8d6; background: #f3faf5; }
    div[data-testid="stAlert"] { border-radius: 10px; }
    div[data-testid="stForm"] { border: 0; padding: 0; }
    div[data-baseweb="textarea"], div[data-baseweb="input"], div[data-baseweb="select"] > div {
        border-radius: 8px !important;
    }
    button[data-baseweb="tab"] p { color: #5a7766; font-weight: 600; }
    button[data-baseweb="tab"][aria-selected="true"] p { color: #16a05a; }
    div[data-baseweb="tab-highlight"] { background-color: #16a05a !important; }

    /* Buttons: lime for the main action, outline for the rest */
    button[data-testid^="stBaseButton-primary"] {
        background: #16a05a; border: none; border-radius: 8px; padding: 8px 22px;
        transition: background 0.15s ease;
    }
    button[data-testid^="stBaseButton-primary"] p, button[data-testid^="stBaseButton-primary"] span { color: #ffffff; font-weight: 700; }
    button[data-testid^="stBaseButton-primary"]:hover { background: #0f7d44; }
    button[data-testid^="stBaseButton-secondary"] {
        border-radius: 8px; border: 1px solid #8fd0a3; background: transparent;
    }
    button[data-testid^="stBaseButton-secondary"]:hover { border-color: #16a05a; color: #16a05a; }

    /* ----- Chat-style input box ----- */
    div[class*="st-key-chatbox_"] {
        background: #f3faf5; border: 1px solid #cfe8d6; border-radius: 26px;
        padding: 16px 24px 24px 24px; margin-bottom: 18px; gap: 10px;
    }
    div[class*="st-key-chatbox_"]:focus-within { border-color: #8fd0a3; }
    div[class*="st-key-chatbox_"] div[data-baseweb="textarea"],
    div[class*="st-key-chatbox_"] div[data-baseweb="base-input"] { background: transparent; border: none; }
    div[class*="st-key-chatbox_"] textarea { background: transparent; font-size: 17px; padding: 6px 4px; }
    div[class*="st-key-chatbox_"] textarea::placeholder { color: #5a7766; }
    .chathint { color: #5a7766; font-size: 16px; margin: 4px 6px 10px 6px; }
    /* round + button and round send button */
    div[class*="st-key-plus_"] button, div[class*="st-key-send_"] button {
        width: 42px; height: 42px; min-height: 42px; padding: 0; border-radius: 10px;
        display: flex; align-items: center; justify-content: center;
    }
    div[class*="st-key-plus_"] button { background: #123828; border: none; color: #0f2a1a; }
    div[class*="st-key-plus_"] button > div:last-child:not(:first-child) { display: none; }
    div[class*="st-key-send_"] { margin-left: auto; }
    div[class*="st-key-send_"] button p { display: none; }
    div[class*="st-key-send_"] button [data-testid="stMarkdownContainer"] { display: none; }
    div[class*="st-key-send_"] button, div[class*="st-key-send_"] button > div, div[class*="st-key-send_"] button span[data-has-shortcut] {
        gap: 0 !important; margin: 0 !important; justify-content: center; align-items: center;
    }
    /* the AI picker: a soft pill button with a small menu */
    div[class*="st-key-aisel_"] { flex: 0 0 auto; width: auto; }
    div[class*="st-key-aisel_"] button {
        height: 42px; min-height: 42px; padding: 0 16px 0 12px; border-radius: 10px;
        background: #e3f3e8; border: 1px solid #bfe0cb; color: #0f2a1a; gap: 6px;
    }
    div[class*="st-key-aisel_"] button:focus, div[class*="st-key-aisel_"] button:focus-visible { box-shadow: 0 0 0 2px rgba(22,160,90,.25) !important; outline: none; }
    div[class*="st-key-aisel_"] button:hover { background: #d5ecdd; border-color: #8fd0a3; }
    div[class*="st-key-aisel_"] button, div[class*="st-key-aisel_"] button * { color: #0f2a1a; font-weight: 600; font-size: 15px; }
    .aihead { font-size: 12px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: #5a7766; margin: 2px 0 6px 0; }
    div[data-testid="stPopoverBody"] { border-radius: 16px; }
    /* no resize handle in the chat text area, so nothing sits next to the send button */
    div[class*="st-key-chatbox_"] textarea { resize: none; }
    /* log out button at the top right of every page */
    div[class*="st-key-logout_top"] button { border-radius: 10px; padding: 4px 16px; }
    @media (max-width: 640px) { div[class*="st-key-aisel_"] button { padding: 0 12px 0 10px; } }

    @media (max-width: 900px) {
        .bighead { font-size: 34px; }
        .hero2 h1 { font-size: 30px; }
    }

    .stApp { background: #ffffff !important; }
    .brand b, .account b, .bighead, .card h3, .tip b, .expect h3, .step, .sectionhead, .sectionsub,
    h1, h2, h3, h4, label, .stMarkdown p { color: #0f2a1a; }
    .lead, .card p, .expect ul, .brand small, .account small { color: #5a7766; }
    .pagebanner h1, .hero2 h1, .cta h2, .devcard h2 { color: #fff !important; }
    .pagebanner p, .hero2 p, .cta p, .devcard p { color: #cfe8d8 !important; }
    .pagebanner h1 *, .hero2 h1 *, .cta h2 *, .devcard h2 * { color:#fff !important; }
    button[data-testid^="stBaseButton-primary"], button[data-testid^="stBaseButton-primary"] * { color: #fff !important; }
    div[data-testid="stMarkdownContainer"] p.sectionhead { color: #0f2a1a !important; }
    div[data-testid="stMarkdownContainer"] p.sectionsub { color: #5a7766 !important; }
    label[data-testid="stRadioOption"] p { color: #3d5c4a; }
    label[data-testid="stRadioOption"][data-selected="true"] p { color: #0d3b2a !important; font-weight:700; }
    label[data-testid="stRadioOption"]:hover { background: #f3faf5; }
    .hero2 .tag, .pagebanner .tag, .cta .tag, .devcard .tag { background: rgba(255,255,255,.22) !important; color:#fff !important; }
    .pagebanner .ic { background:#fff !important; color: #0d3b2a !important; }
    .pagebanner .ic *, .hero2 .ic * { color: #0d3b2a !important; }
    .stApp::before, .stApp::after { opacity: .35; }
    .logo { color:#fff !important; }
    .avatar { color:#fff !important; }
    .num { color:#fff !important; }

    section[data-testid="stSidebar"] { background: #06180f !important; }
    section[data-testid="stSidebar"] .brand b, section[data-testid="stSidebar"] .account b { color:#fff !important; }
    section[data-testid="stSidebar"] .brand small, section[data-testid="stSidebar"] .account small { color:#9bb8a8 !important; }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p { color:#c3d9cb !important; }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover { background:#0e2a1e !important; }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] { background: rgba(155,229,100,.16) !important; box-shadow: inset 3px 0 0 #9be564 !important; }
    section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p { color:#fff !important; }
    section[data-testid="stSidebar"] hr { border-color:#1d4a36 !important; }
    section[data-testid="stSidebar"] .chip-ok { background: rgba(155,229,100,.14) !important; color:#9be564 !important; border:1px solid rgba(155,229,100,.4) !important; }
    section[data-testid="stSidebar"] button { background: transparent !important; color:#eaf5ee !important; border:1px solid #2a6b4f !important; }
    section[data-testid="stSidebar"] button * { color:#eaf5ee !important; }
    section[data-testid="stSidebar"] .logo { background:#9be564 !important; color:#06180f !important; }
    section[data-testid="stSidebar"] .avatar { background:#0a6b47 !important; color:#fff !important; }
    .pagebanner .ic { background:#9be564 !important; color:#06180f !important; }
    .pagebanner .ic *, .hero2 .ic * { color:#06180f !important; }
    .hero2 .tag, .pagebanner .tag, .cta .tag, .devcard .tag { background: rgba(155,229,100,.2) !important; color:#b4f080 !important; }
    .logo { background:#16a05a !important; color:#fff !important; }
    div[class*="st-key-plus_"] button { background:#dff0e5 !important; border:1px solid #bfe0cb !important; }
    div[class*="st-key-plus_"] button, div[class*="st-key-plus_"] button * { color:#0f2a1a !important; }
    .card { box-shadow: 0 2px 10px rgba(15,34,51,.06); }
    .devcard .chip-line, .hero2 .chip-line, .pagebanner .chip-line, .cta .chip-line { color:#e4f3ea !important; background: rgba(255,255,255,.10) !important; border:1px solid #3f8f6b !important; }

    /* ----- Small, quick animations (about 0.3 to 0.5 seconds) ----- */
    @keyframes fadeUp { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    @keyframes pulse  { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
    @keyframes breathe { from { opacity: 0.8; } to { opacity: 1; } }

    /* Banners, cards and results ease in when a page opens ("backwards" keeps hover effects working afterwards) */
    .topbar, .bighead, .lead, .pagebanner, .hero2, .devcard, .expect, .tip, .mock, .cta, .step, .stepcard,
    div[data-testid="stMetric"], div[data-testid="stVerticalBlockBorderWrapper"] {
        animation: fadeUp 0.45s ease backwards;
    }
    .card { animation: fadeUp 0.5s ease backwards; transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease; }
    .card:hover { box-shadow: 0 6px 16px rgba(15, 42, 26, 0.10); }
    /* cards appear one after another */
    div[data-testid="stColumn"]:nth-child(2) .card { animation-delay: 0.08s; }
    div[data-testid="stColumn"]:nth-child(3) .card { animation-delay: 0.16s; }
    div[data-testid="stColumn"]:nth-child(2) div[data-testid="stMetric"] { animation-delay: 0.08s; }
    div[data-testid="stColumn"]:nth-child(3) div[data-testid="stMetric"] { animation-delay: 0.16s; }

    /* Buttons and menu items react softly */
    button[data-testid^="stBaseButton"] { transition: transform 0.15s ease, box-shadow 0.2s ease, background-color 0.2s ease, border-color 0.2s ease; }
    button[data-testid^="stBaseButton"]:hover { transform: translateY(-1px); }
    button[data-testid^="stBaseButton"]:active { transform: scale(0.96); }
    button[data-testid="stBaseButton-primary"]:hover { box-shadow: 0 6px 16px rgba(22, 160, 90, 0.35); }
    label[data-testid="stRadioOption"] { transition: background 0.2s ease, transform 0.2s ease; }

    /* The chat box glows softly when you click inside it */
    div[class*="st-key-chatbox_"] { transition: border-color 0.2s ease, box-shadow 0.25s ease; }
    div[class*="st-key-chatbox_"]:focus-within { box-shadow: 0 0 0 4px rgba(22, 160, 90, 0.14); }

    /* While the AI is working, the message pulses; the answer fades in */
    div[data-testid="stSpinner"] { animation: pulse 1.2s ease-in-out infinite; }
    .stApp::after { animation: fadeIn 1s ease; }

    /* People who turned off motion in their system get no animations */
    @media (prefers-reduced-motion: reduce) {
        * { animation: none !important; transition: none !important; }
    }


    /* ----- Logo (letter F) ----- */
    .logo { color: #ffffff; }
    .logo svg { display: block; }
    .logo .dot { fill: #9be564; }
    .logo .ray { stroke: #9be564; fill: none; }
    .logo.lime { background: #9be564 !important; color: #06180f !important; }
    .logo.lime .dot { fill: #06180f; }
    .logo.lime .ray { stroke: #06180f; }
    .logo, .logo.lime { background: transparent !important; padding: 0; overflow: hidden; }

    /* ----- Top menu bar (dark green, replaces the sidebar) ----- */
    section[data-testid="stSidebar"], div[data-testid="stSidebarCollapsedControl"], button[data-testid="stExpandSidebarButton"] { display: none !important; }
    .stApp:has(.st-key-topnav) header[data-testid="stHeader"] { display: none; }
    .stApp:has(.st-key-topnav) div[data-testid="stMainBlockContainer"] { padding-top: 0 !important; }
    /* the wrapper around the bar sticks to the top and spans the whole window */
    div:has(> .st-key-topnav) {
        position: sticky; top: 0; z-index: 999; width: 100vw !important; max-width: none !important; margin-left: calc(50% - 50vw); margin-top: -1rem; margin-bottom: 10px;
    }
    div.st-key-topnav {
        background: #0d3b2a; width: 100% !important; max-width: none !important; padding: 12px 56px;
        flex-wrap: nowrap; justify-content: space-between; gap: 16px;
        box-shadow: 0 2px 14px rgba(6, 24, 15, 0.30);
    }
    div.st-key-topnav > div { flex: 0 0 auto; width: auto; }
    .navbrand { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
    .navbrand b { color: #ffffff; font-size: 18px; }
    .navbrand .logo { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; }
    div.st-key-topnav > .st-key-topnav_links { flex: 1 1 auto; min-width: 0; justify-content: center; flex-wrap: nowrap; gap: 6px; width: auto; }
    .st-key-topnav_menu { display: none; margin-left: auto; }
    .st-key-topnav_right { flex: 0 0 auto; flex-wrap: nowrap; gap: 10px; }
    /* bar buttons: no border, light text; the current page is lime */
    .st-key-topnav button { border: none !important; background: transparent !important; border-radius: 10px !important; padding: 8px 16px !important; box-shadow: none !important; }
    .st-key-topnav button, .st-key-topnav button * { color: #cfe8d9 !important; font-weight: 500 !important; font-size: 15px !important; }
    .st-key-topnav button:hover { background: rgba(255, 255, 255, 0.09) !important; }
    .st-key-topnav button[data-testid^="stBaseButton-primary"] { background: rgba(155, 229, 100, 0.18) !important; }
    .st-key-topnav button[data-testid^="stBaseButton-primary"], .st-key-topnav button[data-testid^="stBaseButton-primary"] * { color: #9be564 !important; font-weight: 700 !important; }
    .st-key-topnav .st-key-logout_top button { border: 1px solid #3f8f6b !important; border-radius: 10px !important; padding: 7px 18px !important; }
    .st-key-topnav .st-key-logout_top button:hover { border-color: #9be564 !important; }
    .st-key-topnav [class*="st-key-navtoolson_"] button { background: rgba(155, 229, 100, 0.18) !important; }
    .st-key-topnav [class*="st-key-navtoolson_"] button, .st-key-topnav [class*="st-key-navtoolson_"] button * { color: #9be564 !important; font-weight: 700 !important; }
    div[data-testid="stPopoverBody"] div[data-testid="stVerticalBlock"] { gap: 0.15rem; }
    /* menu lists that open from the bar */
    div[class*="st-key-navt_"] button, div[class*="st-key-navm_"] button {
        width: 100%; justify-content: flex-start; border: none; border-radius: 10px; background: transparent; padding: 9px 12px;
    }
    div[class*="st-key-navt_"] button p, div[class*="st-key-navm_"] button p { color: #0f2a1a; font-weight: 500; }
    div[class*="st-key-navt_"] button:hover, div[class*="st-key-navm_"] button:hover { background: #eef7f1; }
    div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"], div[class*="st-key-navm_"] button[data-testid^="stBaseButton-primary"] { background: #e3f3e8; }
    div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"] p, div[class*="st-key-navm_"] button[data-testid^="stBaseButton-primary"] p, div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"] span, div[class*="st-key-navm_"] button[data-testid^="stBaseButton-primary"] span { color: #0a6b47 !important; font-weight: 700 !important; }
    /* ----- Tools menu: icon tile, title and a short hint ----- */
    div[data-testid="stPopoverBody"]:has([class*="st-key-navt_"]) { min-width: 330px; padding: 10px 10px 12px 10px; border-radius: 18px; }
    .toolshead { font-size: 12px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: #5a7766; margin: 6px 8px 10px 8px; }
    div[class*="st-key-navt_"] button { padding: 8px 12px 8px 8px !important; gap: 12px; height: auto; border-radius: 14px; border: 1px solid transparent !important; transition: background .15s ease, border-color .15s ease, transform .15s ease; }
    div[class*="st-key-navt_"] button > div { width: 100%; justify-content: flex-start; align-items: center; }
    div[class*="st-key-navt_"] button > div > span { display: flex; width: 100%; align-items: center; justify-content: flex-start; gap: 12px; }
    div[class*="st-key-navt_"] button > div > span > span:first-child { display: flex; align-items: center; justify-content: center; width: 40px; height: 40px; flex: 0 0 40px; border-radius: 12px; background: #e3f3e8; }
    div[class*="st-key-navt_"] button [data-testid="stIconMaterial"] { color: #0a6b47 !important; font-size: 22px !important; }
    div[class*="st-key-navt_"] button [data-testid="stMarkdownContainer"] { text-align: left; }
    div[class*="st-key-navt_"] button [data-testid="stMarkdownContainer"] p { text-align: left; font-size: 13px; line-height: 1.35; color: #5a7766 !important; margin: 0; }
    div[class*="st-key-navt_"] button [data-testid="stMarkdownContainer"] strong { display: block; font-size: 15px; color: #0f2a1a; font-weight: 700; }
    div[class*="st-key-navt_"] button:hover { background: #f1f9f4; border-color: #cfe8d6 !important; transform: translateX(3px); }
    div[class*="st-key-navt_"] button:hover > div > span > span:first-child { background: #16a05a; }
    div[class*="st-key-navt_"] button:hover [data-testid="stIconMaterial"] { color: #ffffff !important; }
    div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"] { background: #e9f6ee; border-color: #8fd0a3 !important; }
    div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"] > div > span > span:first-child { background: #16a05a; }
    div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"] [data-testid="stIconMaterial"] { color: #ffffff !important; }
    div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"] [data-testid="stMarkdownContainer"] p { color: #3d5c4a !important; font-weight: 500 !important; }
    div[class*="st-key-navt_"] button[data-testid^="stBaseButton-primary"] [data-testid="stMarkdownContainer"] strong { color: #0a6b47 !important; }
    /* language button */
    div[class*="st-key-langsel_land"] { display: flex; justify-content: flex-end; }
    div[class*="st-key-langsel_land"] button { border-radius: 10px; background: #e3f3e8; border: 1px solid #bfe0cb; padding: 6px 16px; }
    div[class*="st-key-langsel_land"] button, div[class*="st-key-langsel_land"] button * { color: #0f2a1a; font-weight: 600; }
    .account b { color: #0f2a1a; }
    .account small { color: #5a7766; }
    @media (max-width: 900px) {
        div.st-key-topnav { padding: 10px 12px; gap: 4px; }
        .st-key-topnav_right { gap: 2px !important; }
        .st-key-topnav button { padding: 8px 8px !important; }
        .st-key-topnav_links, .st-key-logout_top { display: none !important; }
        .st-key-topnav_menu { display: block; }
        .st-key-topnav .st-key-navaccount button p, .st-key-topnav [class*="st-key-langsel_top"] button p { display: none; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Settings and fixed text ----------
USERS_FILE = "users.json"
DATA_DIR = "userdata"
MODELS = ["gemini-2.5-flash", "gemini-flash-latest"]   # second one is a backup name

# The AIs the user can choose from. Each one has its own key in .streamlit/secrets.toml.
# Groq and OpenRouter use the same simple "OpenAI style" web address, so one function can call both.
PROVIDERS = {
    "OpenRouter": {
        "secret": "OPENROUTER_API_KEY", "link": "openrouter.ai/keys",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models": ["openrouter/free", "nvidia/nemotron-3-super-120b-a12b:free", "minimax/minimax-m3.1-flash:free"],
    },
    "Groq": {
        "secret": "GROQ_API_KEY", "link": "console.groq.com/keys",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
    },
    "Gemini": {"secret": "GEMINI_API_KEY", "link": "aistudio.google.com/apikey"},
}

EMPTY_PROFILE = {"name": "", "title": "", "rate": "", "skills": "", "experience": "", "past_work": ""}

# Details shown on the Developer page. Change them here.
DEVELOPER = {
    "name": "Rehan Ali",
    "role": "BSCS student",
    "university": "Superior University, Gold Campus",
    "semester": "2nd semester",
    "roll": "Roll no. 20",
    "course": "Generative AI course",
}

# Shown on the Privacy and Terms pages. Fill this in before launch (the contact line stays hidden while it is empty).
CONTACT_EMAIL = ""

SAMPLE_JOB = (
    "We are a small online clothing store and we need a freelancer to build a simple "
    "Python script that reads our daily orders from an Excel file and creates a summary "
    "report (total sales, best selling items). We also want the report emailed to us "
    "every morning. Budget: $150. Please tell us about similar work you have done."
)

# Names shown above each result
LABELS = {
    "Proposal": "Your proposal",
    "Analysis": "Job analysis",
    "Bid": "Bid suggestion",
    "Reply": "Your reply",
    "Suggestions": "Suggestions",
}

# What the empty result box tells the user to expect
EXPECT = {
    "Proposal": ["A short proposal that starts with the client's problem", "Only the skills that match the job", "A clear next step at the end"],
    "Analysis": ["What the client really wants", "A match score out of 10", "Red flags and smart questions to ask"],
    "Bid": ["Estimated hours of work", "A low, fair and high price in USD", "Delivery time and a negotiation tip"],
    "Reply": ["A reply in the tone you choose", "Written in English, Urdu or Roman Urdu", "Short and ready to send"],
    "Suggestions": ["A better profile headline", "A short, strong bio", "Tips for describing your projects"],
}

# Menu name -> menu icon (Material icons, clean and simple)
PAGES = {
    "Home": ":material/home:",
    "My Profile": ":material/person:",
    "Job Analyzer": ":material/search:",
    "Proposal Generator": ":material/description:",
    "Bid Helper": ":material/payments:",
    "Client Reply": ":material/chat_bubble:",
    "Portfolio Tips": ":material/palette:",
    "History": ":material/history:",
    "FAQ": ":material/help:",
    "Developer": ":material/code:",
}
# Page name -> (banner icon, one line under the banner title)
PAGE_INFO = {
    "My Profile": ("person", "The AI uses this in every proposal, bid and reply."),
    "Job Analyzer": ("search", "Check a job post before you spend time on a proposal."),
    "Proposal Generator": ("description", "Paste a job post, get a proposal that sounds like you."),
    "Bid Helper": ("payments", "Get a fair price and delivery time for a job."),
    "Client Reply": ("chat_bubble", "Paste their message, pick a tone, send the perfect reply."),
    "Portfolio Tips": ("palette", "Improve your headline, bio and project descriptions."),
    "History": ("history", "Everything the AI wrote for you, saved on this laptop."),
    "FAQ": ("help", "Quick answers to common questions."),
    "Developer": ("code", "The person and the tools behind this project."),
}

# (page, tag, title, text) for the tool cards
TOOLS = [
    ("Job Analyzer", "Analyze", "Understand a job post", "See what the client wants, spot red flags and get questions to ask."),
    ("Proposal Generator", "Proposals", "Write a proposal", "Paste a job post and get a personal proposal that uses your skills and past work."),
    ("Bid Helper", "Pricing", "Price your bid", "Get a price range and delivery time so you do not charge too little or too much."),
    ("Client Reply", "Replies", "Reply to clients", "Pick a tone and a language, and get a clear reply ready to send."),
    ("Portfolio Tips", "Portfolio", "Improve your profile", "Get a better headline, bio and project descriptions."),
    ("History", "History", "Find your past results", "Everything the AI wrote for you is saved here, ready to download."),
]

FAQ = [
    ("What is Gigflare?", "It is an AI assistant for freelancers. It helps you check job posts, write proposals, price your bids and reply to clients."),
    ("Who is it for?", "It is for freelancers, the person doing the work. The client is the person you write to, not the person who uses the app."),
    ("Is it free?", "The app is free. It can use Google Gemini, Groq and OpenRouter, and the free plans of these APIs have daily and per-minute limits."),
    ("How do I choose or add another AI?", "Use the AI menu in the box where you type, next to the + button. Gemini, Groq and OpenRouter each need their own free key. Put each key in .streamlit/secrets.toml. An AI without a key shows (no key) in the menu."),
    ("Where is my data saved?", "In a Google Firebase Firestore database that belongs to this project. Your account, profile and history are saved there, and each account has its own entries. If Firebase is not set up (for example on a laptop), they are saved in local files instead."),
    ("Is my password safe?", "Your password is never saved as it is. The app saves only a scrambled version (a salted hash), so the real password cannot be read from the file."),
    ("The AI gave a generic answer. Why?", "The AI only knows what is in your profile and your pasted text. Add more skills, projects and results to My Profile to get better answers."),
    ("I see a quota or 429 error. What do I do?", "You used the free limit for now. Wait one minute and try again."),
    ("Can I get replies in Urdu?", "Yes. In Client Reply you can choose English, Urdu or Roman Urdu."),
    ("Does it send proposals to Upwork or Fiverr for me?", "No. You copy or download the proposal and send it yourself. The AI can make mistakes, so read it before you send it."),
    ("Can I reset a forgotten password?", "Yes. On the login page open the Forgot password tab, enter your email, your recovery word and a new password. You set the recovery word when you signed up."),
]


# ---------- Helper functions ----------
# ---------- Saving data ----------
# If the secret FIREBASE_JSON is set, everything is saved in Firebase Firestore (it survives restarts).
# If not, everything is saved in local files (fine on your own computer, but lost when free hosting restarts).
@st.cache_resource
def firestore_client():
    """Connect to Firestore once. Returns None if there is no Firebase key."""
    try:
        raw = st.secrets.get("FIREBASE_JSON", "")
    except Exception:
        raw = ""
    raw = raw or os.environ.get("FIREBASE_JSON", "")
    if not raw:
        return None
    from google.cloud import firestore
    return firestore.Client.from_service_account_info(json.loads(raw))


def store_get(name, default):
    """Read one saved item (for example 'users' or '<id>_profile')."""
    try:
        client = firestore_client()
        if client is not None:
            doc = client.collection("gigflare").document(name).get()
            return json.loads(doc.to_dict()["data"]) if doc.exists else default
    except Exception as e:
        st.session_state["db_error"] = str(e)[:200]
        raise
    path = os.path.join(DATA_DIR, f"{name}.json") if name != "users" else USERS_FILE
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default


def store_set(name, data):
    """Save one item."""
    try:
        client = firestore_client()
        if client is not None:
            client.collection("gigflare").document(name).set({"data": json.dumps(data)})
            return
    except Exception as e:
        st.session_state["db_error"] = str(e)[:200]
        raise
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{name}.json") if name != "users" else USERS_FILE
    with open(path, "w") as f:
        json.dump(data, f)


def load_users():
    """Read all accounts (email -> name, salt, password hash)."""
    return store_get("users", {})


def save_users(users):
    store_set("users", users)


def hash_password(password, salt_hex):
    """Scramble a password with a random salt. The scrambled text is what we save."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200000).hex()


def make_user(email, name):
    """The small dictionary that says who is logged in."""
    return {"email": email, "name": name, "id": hashlib.sha256(email.encode()).hexdigest()[:16]}


def user_file(kind, user_id=None):
    """Path of a user's own file, for example userdata/<id>_profile.json"""
    os.makedirs(DATA_DIR, exist_ok=True)
    user_id = user_id or st.session_state.user["id"]
    return os.path.join(DATA_DIR, f"{user_id}_{kind}.json")


def import_old_files(user_id):
    """Move the old single-user profile and history to the first new account."""
    for old, kind in (("profile.json", "profile"), ("history.json", "history")):
        if os.path.exists(old):
            shutil.copy(old, user_file(kind, user_id))
            os.rename(old, old + ".imported")


def sign_up(name, email, password, confirm, recovery=""):
    """Create an account. Returns (user, error message)."""
    name = name.strip()
    email = email.strip().lower()
    users = load_users()
    if not name:
        return None, t("Please enter your name.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return None, t("Please enter a valid email.")
    if len(password) < 8:
        return None, t("Your password needs at least 8 characters.")
    if password != confirm:
        return None, t("The two passwords do not match.")
    if len(recovery.strip()) < 3:
        return None, t("Please enter a recovery word (at least 3 characters). You need it if you forget your password.")
    if email in users:
        return None, t("This email already has an account. Please log in.")
    salt = secrets.token_hex(16)
    rsalt = secrets.token_hex(16)
    users[email] = {
        "name": name,
        "salt": salt,
        "hash": hash_password(password, salt),
        "rsalt": rsalt,
        "rhash": hash_password(recovery.strip().lower(), rsalt),
        "created": datetime.now().strftime("%d %b %Y"),
    }
    save_users(users)
    user = make_user(email, name)
    import_old_files(user["id"])
    return user, ""


def log_in(email, password):
    """Check email and password. Returns the user, or None if wrong."""
    email = email.strip().lower()
    record = load_users().get(email)
    if record and hmac.compare_digest(hash_password(password, record["salt"]), record["hash"]):
        return make_user(email, record["name"])
    return None


def reset_password(email, recovery, new_password, confirm):
    """Set a new password if the recovery word is right. Returns (ok, message)."""
    email = email.strip().lower()
    if st.session_state.get("reset_tries", 0) >= 5:
        return False, t("Too many tries. Please refresh the page and try again later.")
    users = load_users()
    record = users.get(email)
    if not record or "rhash" not in record:
        st.session_state["reset_tries"] = st.session_state.get("reset_tries", 0) + 1
        return False, t("We could not reset this account. Check the email and the recovery word. Older accounts without a recovery word need a new account.")
    if not hmac.compare_digest(hash_password(recovery.strip().lower(), record["rsalt"]), record["rhash"]):
        st.session_state["reset_tries"] = st.session_state.get("reset_tries", 0) + 1
        return False, t("We could not reset this account. Check the email and the recovery word. Older accounts without a recovery word need a new account.")
    if len(new_password) < 8:
        return False, t("Your new password needs at least 8 characters.")
    if new_password != confirm:
        return False, t("The two passwords do not match.")
    salt = secrets.token_hex(16)
    record["salt"] = salt
    record["hash"] = hash_password(new_password, salt)
    save_users(users)
    st.session_state["reset_tries"] = 0
    return True, t("Password changed. You can log in now.")


# ---------- Staying logged in after a reload ----------
# After login a random token is saved in a browser cookie. Only a scrambled copy of the token is saved in the database.
COOKIE_NAME = "gf_session"
SESSION_DAYS = 14


def token_key(token):
    return "session_" + hashlib.sha256(token.encode()).hexdigest()[:40]


def start_session(email):
    """Make a login token. The page puts it in a cookie after the next run."""
    token = secrets.token_urlsafe(32)
    store_set(token_key(token), {"email": email, "exp": time.time() + SESSION_DAYS * 86400})
    st.session_state["pending_cookie"] = token


@st.cache_resource
def login_components():
    """Three tiny Streamlit components that keep, read and forget the login code in the browser."""
    save_js = """
    export default function(component) {
        const { data } = component;
        try {
            localStorage.setItem('%s', data.token);
            document.cookie = '%s=' + data.token + '; max-age=' + data.seconds + '; path=/; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
        } catch (e) {}
    }
    """ % (COOKIE_NAME, COOKIE_NAME)
    clear_js = """
    export default function(component) {
        try {
            localStorage.removeItem('%s');
            document.cookie = '%s=; max-age=0; path=/; SameSite=Lax';
        } catch (e) {}
    }
    """ % (COOKIE_NAME, COOKIE_NAME)
    read_js = """
    export default function(component) {
        const { setTriggerValue } = component;
        let token = '';
        try { token = localStorage.getItem('%s') || ''; } catch (e) {}
        setTriggerValue('token', token);
    }
    """ % COOKIE_NAME
    return (st.components.v2.component("gf_login_save", js=save_js),
            st.components.v2.component("gf_login_clear", js=clear_js),
            st.components.v2.component("gf_login_read", js=read_js))


def cookie_script(token, days):
    """Save the login code in the browser (days > 0) or remove it (days = 0)."""
    save, clear, _ = login_components()
    if days > 0:
        save(data={"token": token, "seconds": int(days * 86400)}, key="gf_save_" + token[:8])
    else:
        clear(key="gf_clear_" + str(int(time.time())))


def browser_token():
    """Ask the browser for the saved login code. The answer arrives on the next run of the page."""
    _, _, read = login_components()
    result = read(key="gf_read", on_token_change=lambda: None)
    return getattr(result, "token", None)  # None means the browser has not answered yet


def restore_session(token=None):
    """If there is a valid login code (cookie or browser storage), return that user. Otherwise None."""
    try:
        token = token or st.context.cookies.get(COOKIE_NAME)
        if not token:
            return None
        saved = store_get(token_key(token), None)
        if not saved or saved.get("exp", 0) < time.time():
            st.session_state["bad_token"] = True
            return None
        record = load_users().get(saved["email"])
        return make_user(saved["email"], record["name"]) if record else None
    except Exception:
        return None


def end_session():
    """Forget the login token on the server."""
    try:
        token = st.context.cookies.get(COOKIE_NAME)
        if token:
            store_set(token_key(token), {})
    except Exception:
        pass


def log_out():
    end_session()
    lang = st.session_state.get("lang", "en")
    st.session_state.clear()
    st.session_state["lang"] = lang
    st.session_state["clear_cookie"] = True
    st.session_state["ls_checked"] = True


def load_profile():
    """Read the saved profile of the logged-in user. Missing fields stay empty."""
    profile = dict(EMPTY_PROFILE)
    profile.update(store_get(f"{st.session_state.user['id']}_profile", {}))
    return profile


def save_profile(profile):
    store_set(f"{st.session_state.user['id']}_profile", profile)


def load_history():
    """Read all saved AI results of the logged-in user."""
    return store_get(f"{st.session_state.user['id']}_history", [])


def save_history(history):
    store_set(f"{st.session_state.user['id']}_history", history)


def profile_text(profile):
    """Turn the profile into text that we send to the AI."""
    return (
        f"Name: {profile['name']}\n"
        f"Title: {profile['title']}\n"
        f"Hourly rate: {profile['rate']}\n"
        f"Skills: {profile['skills']}\n"
        f"Experience: {profile['experience']}\n"
        f"Past work: {profile['past_work']}"
    )


def get_key(provider):
    """Look for the key in the secrets file, then in an environment variable, then in the sidebar box."""
    name = PROVIDERS[provider]["secret"]
    try:
        key = st.secrets.get(name, "")
    except Exception:
        key = ""
    return key or os.environ.get(name, "") or st.session_state.get("saved_key_" + provider, "")


def ask_gemini(prompt, api_key, files=()):
    """Send the prompt (and any images or PDFs) to Gemini and return its answer as text."""
    client = genai.Client(api_key=api_key)
    contents = [prompt] + [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in files]
    last_error = None
    for model in MODELS:
        try:
            response = client.models.generate_content(model=model, contents=contents)
            return response.text
        except Exception as e:
            last_error = e
    raise last_error


def fetch_json(url, key=""):
    """Download a small JSON answer from a web address."""
    headers = {"User-Agent": "Gigflare/1.0"}
    if key:
        headers["Authorization"] = "Bearer " + key
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as reply:
        return json.loads(reply.read())


@st.cache_data(ttl=3600, show_spinner=False)
def current_models(provider, _key):
    """Ask Groq or OpenRouter which models they offer right now (model names change often).
    Returns the best free chat models first. If the list cannot be loaded, the saved list is used."""
    info = PROVIDERS[provider]
    try:
        if provider == "Groq":
            rows = fetch_json("https://api.groq.com/openai/v1/models", _key)["data"]
            names = [r["id"] for r in rows if r.get("active", True)
                     and not any(bad in r["id"] for bad in ("whisper", "guard", "tts", "orpheus", "playai", "embed"))]
        else:
            rows = fetch_json("https://openrouter.ai/api/v1/models")["data"]
            names = [r["id"] for r in rows if r["id"].endswith(":free")
                     and "text" in r.get("architecture", {}).get("output_modalities", ["text"])]
        # Put the best known models first, then the rest. (Groq's free keys no longer run Llama, so Llama goes last.)
        if provider == "Groq":
            best = ("gpt-oss-120b", "gpt-oss-20b", "qwen3", "compound", "kimi", "deepseek", "llama")
        else:
            best = ("nemotron-3-ultra", "minimax", "nemotron-3-super", "gpt-oss", "qwen", "laguna", "gemma", "llama")
        names.sort(key=lambda n: next((i for i, w in enumerate(best) if w in n), len(best)))
        if provider == "OpenRouter":
            names = ["openrouter/free"] + names      # this one picks any free model that is working right now
        return names[:6] or info["models"]
    except Exception:
        return info["models"]


FILE_AIS = ("Gemini", "OpenRouter")      # the AIs that can read images and PDFs


def ask_openai_style(prompt, api_key, url, models, files=()):
    """Groq and OpenRouter: send the prompt to their web address and read the answer.
    Images and PDFs (OpenRouter only) are sent as extra parts of the message.
    If one model is busy or gone, the next one is tried."""
    import base64
    content = prompt
    if files:
        content = [{"type": "text", "text": prompt}]
        for number, (data, mime) in enumerate(files, 1):
            link = f"data:{mime};base64," + base64.b64encode(data).decode()
            if mime == "application/pdf":
                content.append({"type": "file", "file": {"filename": f"file{number}.pdf", "file_data": link}})
            else:
                content.append({"type": "image_url", "image_url": {"url": link}})
        # openrouter/free only picks free models that can handle the files; the second one is a vision model
        models = ["openrouter/free", "nvidia/nemotron-3.5-super-vl:free"]
    last_error = None
    for model in models:
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": content}]}).encode()
        request = urllib.request.Request(
            url, data=body,
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json", "User-Agent": "Gigflare/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as reply:
                return json.loads(reply.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last_error = RuntimeError(f"{model}: {e.code} {e.read().decode(errors='ignore')[:150]}")
        except Exception as e:
            last_error = RuntimeError(f"{model}: {e}")
    raise RuntimeError(f"No model answered. Last problem: {last_error}")


def ask_ai(prompt, provider, files=()):
    """Send the prompt to the AI the user chose and return the answer as text.
    If that AI is busy or fails, the other AIs that have a key are tried (with attached files, only Gemini and OpenRouter can be used)."""
    others = [n for n in PROVIDERS if n != provider and get_key(n) and (not files or n in FILE_AIS)]
    order = [provider] + others
    first_error = None
    for name in order:
        try:
            key = get_key(name)
            if name == "Gemini":
                return ask_gemini(prompt, key, files)
            info = PROVIDERS[name]
            return ask_openai_style(prompt, key, info["url"], current_models(name, key), files)
        except Exception as e:
            first_error = first_error or e
    raise first_error


FILE_TYPES = ["png", "jpg", "jpeg", "webp", "pdf", "txt", "md", "csv"]
MAX_FILE_MB = 10


def read_attachments(uploaded, provider):
    """Turn the uploaded files into (text to add to the prompt, files for Gemini, notes for the user).
    Text files are added to the prompt. 
    Gemini and OpenRouter read images and PDFs directly. Groq only reads text, so for it we pull the text out of a PDF and skip images."""
    extra_text, gemini_files, notes = "", [], []
    for f in uploaded or []:
        ext = f.name.rsplit(".", 1)[-1].lower()
        data = f.getvalue()
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            notes.append(f"{f.name} is bigger than {MAX_FILE_MB} MB, so it was skipped.")
        elif ext in ("txt", "md", "csv"):
            extra_text += f"\n\nATTACHED FILE ({f.name}):\n{data.decode('utf-8', errors='ignore')[:8000]}"
        elif provider in FILE_AIS:
            mime = "application/pdf" if ext == "pdf" else "image/" + ("jpeg" if ext == "jpg" else ext)
            gemini_files.append((data, mime))
        elif ext == "pdf":
            try:
                from io import BytesIO
                from pypdf import PdfReader
                pages = [p.extract_text() or "" for p in PdfReader(BytesIO(data)).pages]
                extra_text += f"\n\nATTACHED FILE ({f.name}):\n{chr(10).join(pages)[:8000]}"
            except Exception:
                notes.append(f"{f.name}: {provider} cannot read PDFs here. Choose Gemini or OpenRouter, or install pypdf (see the FAQ).")
        else:
            notes.append(f"{f.name}: images only work with Gemini or OpenRouter. Choose one of them to use it.")
    return extra_text, gemini_files, notes


AI_INFO = {
    "Gemini": "Best answers. Reads images and PDFs.",
    "Groq": "Very fast. Reads text only.",
    "OpenRouter": "Many AI models in one. Reads images and PDFs.",
}


def ai_picker(name):
    """A pill button that opens a small menu to choose which AI answers. The choice is kept on every page."""
    names = list(PROVIDERS)
    key = "aisel_" + name
    wkey = "widget_" + key
    if st.session_state.get(wkey) != st.session_state.ai_pick:
        st.session_state[wkey] = st.session_state.ai_pick
    with st.popover(st.session_state.ai_pick, icon=":material/auto_awesome:", key=key):
        st.markdown(f'<p class="aihead">{t("Choose the AI")}</p>', unsafe_allow_html=True)
        st.radio(
            "AI", names, key=wkey, label_visibility="collapsed",
            captions=[t(AI_INFO.get(n, "")) + ("" if get_key(n) else " " + t("Needs an API key.")) for n in names],
            on_change=lambda: st.session_state.update(ai_pick=st.session_state[wkey]),
        )


def chat_box(name, placeholder, text_key=None, sample=None, options=None, height=130):
    """A chat-style box: text on top, small round buttons below. Returns True when Send is pressed."""
    placeholder = t(placeholder)
    with st.container(key="chatbox_" + name):
        if text_key:
            st.text_area("Your text", key=text_key, placeholder=placeholder, height=height, label_visibility="collapsed")
        else:
            st.markdown(f'<p class="chathint">{placeholder}</p>', unsafe_allow_html=True)
        with st.container(horizontal=True, vertical_alignment="center"):
            with st.popover("", icon=":material/add:", key="plus_" + name):
                if sample:
                    st.button(
                        t("Use a sample job post"), icon=":material/content_paste:", key="sample_" + name,
                        on_click=lambda: st.session_state.update({text_key: sample}),
                    )
                st.file_uploader(
                    t("Add files or images (PNG, JPG, PDF, TXT, CSV)"), type=FILE_TYPES,
                    accept_multiple_files=True, key="files_" + name,
                )
                if options:
                    options()
            ai_picker(name)
            attached = st.session_state.get("files_" + name) or []
            if attached:
                st.markdown(f'<span class="chip chip-line">{t("{n} attached", n=len(attached))}</span>', unsafe_allow_html=True)
            sent = st.button(t("Send"), icon=":material/arrow_upward:", type="primary", key="send_" + name, help=t("Send"))
            if sent:
                st.session_state["attached"] = attached
            return sent


def banner(name):
    """Big green banner at the top of a page."""
    icon, subtitle = PAGE_INFO[name]
    st.markdown(
        f'<div class="pagebanner"><div class="ic"><span class="msym">{icon}</span></div>'
        f"<div><h1>{t(name)}</h1><p>{t(subtitle)}</p></div></div>",
        unsafe_allow_html=True,
    )


def tips(items):
    """A row of small tip cards: items = [(title, text), ...]"""
    cols = st.columns(len(items))
    for col, (title, text) in zip(cols, items):
        col.markdown(f'<div class="tip"><b>{t(title)}</b>{t(text)}</div>', unsafe_allow_html=True)


def tool_cards(with_buttons):
    """The six tool cards (two rows of three)."""
    for row in (TOOLS[:3], TOOLS[3:]):
        cols = st.columns(3)
        for col, (page_name, tag, title, text) in zip(cols, row):
            col.markdown(
                f'<div class="card"><span class="tag">{t(tag)}</span><h3>{t(title)}</h3><p>{t(text)}</p></div>',
                unsafe_allow_html=True,
            )
            if with_buttons:
                col.button(t("Open"), key="open_" + page_name, on_click=go, args=(page_name,))
        st.write("")


def how_it_works():
    steps = [
        ("1", "Save your profile", "Add your skills, experience and past work once."),
        ("2", "Paste the text", "Paste a job post or a client message."),
        ("3", "Get your result", "The AI writes it using your profile. You read it, then send it."),
    ]
    cols = st.columns(3)
    for col, (num, title, text) in zip(cols, steps):
        col.markdown(
            f'<div class="card stepcard"><span class="num">{num}</span><h3>{t(title)}</h3><p>{t(text)}</p></div>',
            unsafe_allow_html=True,
        )


def footer():
    st.markdown(
        f'<div class="footer"><span>© {datetime.now().year} Gigflare</span>'
        f'<span>{t("Built by {name} · {university} · {course} project", name=escape(DEVELOPER["name"]), university=escape(DEVELOPER["university"]), course=escape(DEVELOPER["course"]))}</span>'
        f'<span><a href="?doc=privacy" target="_blank" rel="noopener">{t("Privacy")}</a> &nbsp; <a href="?doc=terms" target="_blank" rel="noopener">{t("Terms")}</a></span></div>',
        unsafe_allow_html=True,
    )


def demo_media():
    """Read the demo video and a still picture from the static folder. Missing files are fine."""
    import base64
    here = os.path.dirname(os.path.abspath(__file__))
    folders = [os.path.join(here, "static"), here]  # the files can sit in a static folder or next to app.py

    def read(name, mime):
        for folder in folders:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f"data:{mime};base64," + base64.b64encode(f.read()).decode()
        return ""

    video = read("demo.webm", "video/webm") or read("demo.mp4", "video/mp4")
    return video, read("poster.jpg", "image/jpeg")


def home_banner(first_name):
    """The green welcome banner with a phone that plays a short demo of the app."""
    video, poster = demo_media()
    screen = (
        f'<video id="v" autoplay loop muted playsinline poster="{poster}" src="{video}"></video>'
        if video else (f'<img src="{poster}">' if poster else '<div class="empty">Gigflare</div>')
    )
    tag_text = t("Dashboard")
    welcome = t("Welcome back, {name}", name=escape(first_name))
    intro = t("Analyse job posts, write proposals, price your bids and reply to clients, all in one place.")
    chips = "".join(f"<span>{t(c)}</span>" for c in ("Job analyzer", "Proposals", "Bid helper", "Client replies"))
    html = f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
      html, body {{ margin: 0; padding: 0; background: transparent; font-family: 'Inter', 'Noto Sans', sans-serif; }}
      .hero {{ box-sizing: border-box; height: 470px; display: flex; align-items: center; justify-content: space-between; gap: 32px;
        background: linear-gradient(120deg, #0a6b47 0%, #0d3b2a 70%); border: 1px solid #cfe8d6; border-radius: 18px; padding: 28px 36px; }}
      .tag {{ display: inline-block; padding: 4px 10px; border-radius: 4px; background: rgba(155,229,100,.2); color: #b4f080;
        font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }}
      h1 {{ font-size: 38px; font-weight: 800; color: #fff; margin: 14px 0 8px 0; }}
      p {{ color: #cfe8d8; font-size: 17px; line-height: 1.55; margin: 0; }}
      .chips {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }}
      .chips span {{ padding: 7px 14px; border-radius: 8px; font-size: 15px; font-weight: 600; color: #e4f3ea;
        background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.28); }}
      .text {{ flex: 1; min-width: 0; }}
      .phone {{ flex: 0 0 auto; width: 214px; height: 414px; box-sizing: border-box; padding: 9px; border-radius: 38px; position: relative;
        background: #0a1a12; border: 2px solid #2c5a45; box-shadow: 0 24px 50px rgba(0,0,0,.45); animation: floaty 6s ease-in-out infinite; }}
      .phone::before {{ content: ""; position: absolute; top: 14px; left: 50%; width: 58px; height: 14px; margin-left: -29px;
        border-radius: 6px; background: #0a1a12; z-index: 2; }}
      .phone video, .phone img, .phone .empty {{ width: 100%; height: 100%; display: block; object-fit: cover; border-radius: 30px;
        background: #0d3b2a; }}
      .phone .empty {{ display: flex !important; align-items: center; justify-content: center; color: #9be564; font-weight: 800; font-size: 20px; letter-spacing: .5px; }}
      @keyframes floaty {{ 0%, 100% {{ transform: translateY(0) rotate(2deg); }} 50% {{ transform: translateY(-10px) rotate(2deg); }} }}
      @media (max-width: 700px) {{ .phone {{ display: none; }} .hero {{ height: auto; }} }}
      @media (prefers-reduced-motion: reduce) {{ .phone {{ animation: none; }} }}
    </style>
    <div class="hero">
      <div class="text"><span class="tag">{tag_text}</span><h1>{welcome}</h1>
        <p>{intro}</p>
        <div class="chips">{chips}</div></div>
      <div class="phone" id="phone">{screen}</div>
    </div>
    <script>
      var v = document.getElementById('v');
      if (v) {{ v.muted = true; var p = v.play(); if (p && p.catch) p.catch(function () {{}});
                document.getElementById('phone').onclick = function () {{ v.play(); }}; }}
    </script>
    """
    st.components.v1.html(html, height=496)


def go(page_name):
    """Used by the buttons on the Home page to open another page."""
    st.session_state.page = page_name


def check_ready(*needed):
    """True if the chosen AI has a key and every needed input is filled in."""
    ai = st.session_state.ai_pick
    if not get_key(ai):
        st.warning(t("{ai} has no key yet. Choose another AI, or add the key (see the FAQ).", ai=ai))
        return False
    for value, message in needed:
        if not value:
            st.warning(message)
            return False
    return True


def run_ai(kind, prompt):
    """Call the chosen AI, show the answer, and save it to the history file."""
    ai = st.session_state.ai_pick
    extra_text, files, notes = read_attachments(st.session_state.get("attached"), ai)
    for note in notes:
        st.warning(note)
    if extra_text or files:
        prompt += "\n\nThe user also attached files or images. Use them together with the text above." + extra_text
    lang = st.session_state.get("lang", "en")
    if lang != "en" and kind in ("Analysis", "Bid", "Suggestions"):
        prompt += f"\n\nWrite your whole answer in {AI_LANGUAGE_NAME[lang]}."
    with st.spinner(t("{ai} is writing...", ai=ai)):
        try:
            text = ask_ai(prompt, ai, files)
        except Exception as e:
            st.error(t("Something went wrong with {ai}: {e}", ai=ai, e=e))
            return
    st.session_state["last_" + kind] = text
    history = load_history()
    history.append({"kind": kind, "text": text, "ai": ai, "time": datetime.now().strftime("%d %b %Y, %H:%M")})
    save_history(history)


def show_result(kind, filename):
    """Show the latest result in a box with a download button."""
    text = st.session_state.get("last_" + kind)
    if text:
        with st.container(border=True):
            st.subheader(t(LABELS[kind]))
            st.write(text)
        st.download_button(
            t("Download as text file"), text, file_name=filename,
            icon=":material/download:", key="dl_" + kind,
        )
    else:
        items = "".join(f"<li>{t(x)}</li>" for x in EXPECT[kind])
        st.markdown(
            f'<div class="expect"><span class="tag">{t("Result")}</span>'
            f"<h3>{t('{label} will appear here', label=t(LABELS[kind]))}</h3><ul>{items}</ul></div>",
            unsafe_allow_html=True,
        )



# ---------- Lamp intro: pull the string, the light turns on, the login card appears ----------
LAMP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;1,500&display=swap');
/* The whole page turns dark green while the lamp login is shown */
.stApp { background: radial-gradient(ellipse 80% 70% at 30% 50%, #062319 0%, #041710 55%, #020b07 100%) !important; }
.stApp::after { display: none !important; }
/* The soft light that spreads over the page. It is always there and fades in and out. */
.stApp::before { display: block !important; content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none; opacity: 0;
    background: radial-gradient(ellipse 85% 95% at 27% 48%, rgba(200, 248, 150, 0.38) 0%, rgba(140, 220, 110, 0.20) 30%, rgba(90, 190, 100, 0.09) 58%, transparent 85%);
    transform-origin: 27% 50%; transform: scale(0.55);
    width: auto; height: auto; right: auto; left: 0; clip-path: none; animation: none; }
header[data-testid="stHeader"] { background: transparent !important; }
.topbar .brand b { color: #ffffff !important; }
.topbar .brand small { color: #9bc4ae !important; }
div[class*="st-key-langsel_land"] { width: 100%; }
div[class*="st-key-langsel_land"] > div { margin-left: auto; width: fit-content; }
div[class*="st-key-langsel_land"] button { background: rgba(255, 255, 255, 0.08) !important; border: 1px solid rgba(155, 229, 100, 0.35) !important; }
div[class*="st-key-langsel_land"] button, div[class*="st-key-langsel_land"] button * { color: #e8f7ee !important; }

/* Lamp stage: same size in both states so nothing jumps */
.st-key-lampwrap { will-change: transform; backface-visibility: hidden; position: relative; width: 300px; max-width: 100%; margin: 0 auto; }
.lamp-svg { shape-rendering: geometricPrecision; transform: translateZ(0); display: block; width: 300px; max-width: 100%; height: auto; overflow: visible; }
.lamp-svg .sway { transform-origin: 205px 150px; animation: sway 3.2s ease-in-out infinite; }
.lamp-svg .pullg { transform-origin: 205px 150px; }
.lamp-svg .lit { opacity: 0; }
.legal { text-align: center; margin: 18px 0 0 0; }
.legal a { color: #9bc4ae !important; font-size: 13px; margin: 0 12px; text-decoration: none; }
.legal a:hover { color: #9be564 !important; text-decoration: underline; }
.lamphint { text-align: center; color: #7fa892 !important; font-size: 14px; letter-spacing: 0.05em; margin: 6px 0 0 0; animation: pulse 2.4s ease-in-out infinite; }
.st-key-lamp_pull { position: absolute; left: 170px; top: 270px; width: 70px; z-index: 5; }
.st-key-lamp_pull button { width: 70px; height: 110px; opacity: 0; cursor: pointer; padding: 0; }

/* Login card: dark glass, like a real login panel */
.st-key-lampcard { max-width: 460px; margin: 0 0 0 auto; will-change: opacity, transform;
    background: rgba(8, 38, 27, 0.72) !important; backdrop-filter: blur(14px); border: 1px solid rgba(155, 229, 100, 0.25) !important; border-radius: 22px;
    padding: 22px 22px 14px !important; box-shadow: 0 30px 90px rgba(0, 0, 0, 0.55), 0 0 70px rgba(155, 229, 100, 0.10); }
.st-key-lampcard > div { background: transparent; box-shadow: none; border: none; }
.cardhead { padding: 0 2px 12px; }
.cardhead small { display: block; letter-spacing: 0.18em; font-size: 11px; color: #9be564; margin-bottom: 8px; }
.cardhead b { display: block; font-family: 'Playfair Display', Georgia, serif; font-weight: 600; font-size: 34px; line-height: 1.1; color: #f2fbf5; }
.cardhead span { display: block; font-family: 'Playfair Display', Georgia, serif; font-style: italic; font-size: 26px; line-height: 1.2; color: #a9cdb8; margin-top: 2px; }
.st-key-lampcard label, .st-key-lampcard label p, .st-key-lampcard [data-testid="stWidgetLabel"] p { color: #cfe8d9 !important; }
div.st-key-lampcard [role="tab"], div.st-key-lampcard [role="tab"] * { color: #b9d8c6 !important; }
div.st-key-lampcard [role="tab"][aria-selected="true"], div.st-key-lampcard [role="tab"][aria-selected="true"] * { color: #9be564 !important; }
.st-key-lampcard div[data-baseweb="tab-border"] { background: rgba(155, 229, 100, 0.18) !important; }
.st-key-lampcard div[data-baseweb="input"], .st-key-lampcard div[data-baseweb="base-input"] { background: rgba(255, 255, 255, 0.06) !important; border-radius: 12px; }
.st-key-lampcard div[data-baseweb="input"] { border: 1px solid rgba(155, 229, 100, 0.22) !important; }
.st-key-lampcard div[data-baseweb="input"]:focus-within { border-color: #9be564 !important; box-shadow: 0 0 0 3px rgba(155, 229, 100, 0.18); }
.st-key-lampcard [data-testid="stTextInputRootElement"], .st-key-lampcard div[data-baseweb="input"] > div, .st-key-lampcard input { background: transparent !important; }
.st-key-lampcard [data-testid="stTextInputRootElement"] { background: rgba(255, 255, 255, 0.07) !important; border: 1px solid rgba(155, 229, 100, 0.22) !important; border-radius: 12px; }
.st-key-lampcard input { color: #f2fbf5 !important; -webkit-text-fill-color: #f2fbf5; }
.st-key-lampcard [data-testid="stTextInputRootElement"] svg, .st-key-lampcard div[data-baseweb="input"] svg { fill: #cfe8d9 !important; color: #cfe8d9 !important; }
.st-key-lampcard button[data-testid^="stBaseButton-primary"], .st-key-lampcard button[data-testid^="stFormSubmitButton"] { background: linear-gradient(180deg, #b4f080, #7fd44c) !important; border: none !important; border-radius: 12px !important; }
.st-key-lampcard button[data-testid^="stBaseButton-primary"] *, .st-key-lampcard button[data-testid^="stFormSubmitButton"] * { color: #0a2a1c !important; font-weight: 700 !important; }
.st-key-lampcard [data-testid="stTextInputRootElement"] button, .st-key-lampcard [data-testid="stTextInputRootElement"] button * { color: #cfe8d9 !important; fill: #cfe8d9 !important; background: transparent !important; }
.st-key-lampcard [data-testid="stTooltipIcon"] * { color: #9bc4ae !important; fill: #9bc4ae !important; }
/* Browser autofill: keep it dark and readable (it used to turn light blue) */
.st-key-lampcard input:-webkit-autofill, .st-key-lampcard input:-webkit-autofill:hover, .st-key-lampcard input:-webkit-autofill:focus, .st-key-lampcard input:-webkit-autofill:active {
    -webkit-box-shadow: 0 0 0 1000px #1a3a2d inset !important; box-shadow: 0 0 0 1000px #1a3a2d inset !important;
    -webkit-text-fill-color: #f2fbf5 !important; caret-color: #f2fbf5; border-radius: 12px; transition: background-color 9999s ease-out 0s; }
.st-key-lampcard input:autofill { box-shadow: 0 0 0 1000px #1a3a2d inset !important; -webkit-text-fill-color: #f2fbf5 !important; }
.st-key-lampcard [data-testid="InputInstructions"], .st-key-lampcard [data-testid="InputInstructions"] * { color: #9bc4ae !important; background: transparent !important; }
.st-key-lampcard [data-testid="stForm"] { border: none !important; padding: 0 !important; }

@keyframes fadeup { from { opacity: 0; } to { opacity: 1; } }
@keyframes flick { 0% { opacity: 0; } 30% { opacity: 0.85; } 45% { opacity: 0.7; } 100% { opacity: 1; } }
@keyframes sway { 0%, 100% { transform: rotate(-1.5deg); } 50% { transform: rotate(1.5deg); } }
@keyframes tugA { 0% { transform: translateY(0) rotate(0); } 12% { transform: translateY(18px) rotate(0); } 30% { transform: translateY(-4px) rotate(5deg); } 50% { transform: rotate(-4deg); } 70% { transform: rotate(2.5deg); } 100% { transform: rotate(0); } }
@keyframes tugB { 0% { transform: translateY(0) rotate(0); } 12% { transform: translateY(18px) rotate(0); } 30% { transform: translateY(-4px) rotate(5deg); } 50% { transform: rotate(-4deg); } 70% { transform: rotate(2.5deg); } 100% { transform: rotate(0); } }
@keyframes pulse { 0%, 100% { opacity: 0.55; } 50% { opacity: 1; } }
@media (max-width: 900px) { .st-key-lampcard { margin: 0 auto; } .cardhead b { font-size: 28px; } .cardhead span { font-size: 22px; } }
</style>
"""

def lamp_state_css(n):
    """CSS for the current state. n counts the pulls: 0 = never pulled, odd = light on, even = light off again.
    The page keeps the same elements, so these changes fade smoothly instead of jumping."""
    on = n % 2 == 1
    if on:
        css = """
.lamp-svg .lit { opacity: 1; transition: opacity 1.4s ease 0.15s; }
.stApp::before { opacity: 1; transform: scale(1); transition: opacity 2.6s ease 0.1s, transform 3.4s cubic-bezier(0.2, 0.6, 0.2, 1) 0.1s; }
.st-key-lampwrap { transform: translateX(0); transition: transform 1.5s cubic-bezier(0.65, 0, 0.35, 1) 0.1s; }
.st-key-lampcard { opacity: 1; transform: none; visibility: visible; pointer-events: auto;
    transition: opacity 1.2s ease 1s, transform 1.2s cubic-bezier(0.2, 0.7, 0.2, 1) 1s, visibility 0s; }
.lamphint { opacity: 0; transition: opacity 0.4s ease; }
.lamp-svg .pullg { animation: tugA 1.6s ease-out both; }
"""
    else:
        sway = "animation: sway 3.2s ease-in-out infinite;" if n == 0 else "animation: tugB 1.6s ease-out both;"
        css = """
.lamp-svg .lit { opacity: 0; transition: opacity 0.9s ease; }
.stApp::before { opacity: 0; transform: scale(0.55); transition: opacity 1.1s ease, transform 1.6s ease; }
.st-key-lampwrap { transform: translateX(calc(25vw - 40px)); transition: transform 1.5s cubic-bezier(0.65, 0, 0.35, 1) 0.5s; }
.st-key-lampcard { opacity: 0; transform: translateX(34px); visibility: hidden; pointer-events: none;
    transition: opacity 0.7s ease, transform 0.7s ease, visibility 0s linear 0.7s; }
.lamphint { opacity: 1; transition: opacity 1s ease 1.6s; }
.lamp-svg .pullg { %s }
@media (max-width: 900px) {
  .st-key-lampwrap { transform: none; }
  .st-key-lampcard { position: absolute; width: calc(100%% - 2rem); }
}
""" % sway
    return "<style>" + css + "</style>"


def lamp_svg():
    """The lamp as a small picture. The light layers are always there; the state CSS fades them in and out."""
    return (
        '<svg class="lamp-svg" viewBox="0 0 300 540" xmlns="http://www.w3.org/2000/svg">'
        '<defs>'
        '<linearGradient id="shadeOff" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#071c13"/><stop offset="0.35" stop-color="#143c2c"/><stop offset="1" stop-color="#071c13"/></linearGradient>'
        '<linearGradient id="shadeOn" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#3fae6b"/><stop offset="0.45" stop-color="#c4f594"/><stop offset="1" stop-color="#3fae6b"/></linearGradient>'
        '<linearGradient id="cone" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d3f9ae" stop-opacity="0.46"/><stop offset="1" stop-color="#9be564" stop-opacity="0.02"/></linearGradient>'
        '<radialGradient id="spread"><stop offset="0" stop-color="#d3f9ae" stop-opacity="0.34"/><stop offset="0.45" stop-color="#9be564" stop-opacity="0.14"/><stop offset="1" stop-color="#9be564" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="hx" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000"/><stop offset="0.3" stop-color="#888"/><stop offset="0.5" stop-color="#fff"/><stop offset="0.7" stop-color="#888"/><stop offset="1" stop-color="#000"/></linearGradient>'
        '<mask id="conemask" maskUnits="userSpaceOnUse" x="-60" y="140" width="420" height="400"><rect x="-60" y="140" width="420" height="400" fill="url(#hx)"/></mask>'
        '<radialGradient id="pool"><stop offset="0" stop-color="#9be564" stop-opacity="0.55"/><stop offset="1" stop-color="#9be564" stop-opacity="0"/></radialGradient>'
        '<radialGradient id="glow"><stop offset="0" stop-color="#f4ffd9" stop-opacity="0.95"/><stop offset="1" stop-color="#9be564" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="pole" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#091f16"/><stop offset="0.4" stop-color="#184834"/><stop offset="1" stop-color="#091f16"/></linearGradient>'
        '<radialGradient id="base" cx="0.4" cy="0.3"><stop offset="0" stop-color="#215740"/><stop offset="1" stop-color="#071c13"/></radialGradient>'
        '</defs>'
        '<g class="lit">'
        '<ellipse cx="150" cy="300" rx="340" ry="360" fill="url(#spread)"/>'
        '<polygon points="70,160 230,160 345,520 -45,520" fill="url(#cone)" mask="url(#conemask)"/>'
        '<ellipse cx="150" cy="506" rx="210" ry="30" fill="url(#pool)"/>'
        '<circle cx="150" cy="168" r="50" fill="url(#glow)"/>'
        '</g>'
        '<ellipse cx="150" cy="510" rx="62" ry="12" fill="#030c08" opacity="0.8"/>'
        '<ellipse cx="150" cy="500" rx="56" ry="11" fill="url(#base)"/>'
        '<rect x="145" y="150" width="10" height="352" rx="4" fill="url(#pole)"/>'
        '<rect x="143" y="326" width="14" height="6" rx="2" fill="#9be564" opacity="0.55"/>'
        '<rect x="143" y="190" width="14" height="4" rx="2" fill="#9be564" opacity="0.45"/>'
        '<path d="M105 40 L195 40 L228 150 L72 150 Z" fill="url(#shadeOff)"/>'
        '<ellipse cx="150" cy="40" rx="45" ry="5" fill="#030c08" opacity="0.6"/>'
        '<ellipse cx="150" cy="166" rx="13" ry="15" fill="#143c2c"/>'
        '<g class="lit"><path d="M105 40 L195 40 L228 150 L72 150 Z" fill="url(#shadeOn)"/>'
        '<ellipse cx="150" cy="150" rx="78" ry="9" fill="#e9ffc9" opacity="0.55"/>'
        '<ellipse cx="150" cy="166" rx="13" ry="15" fill="#f4ffd9"/></g>'
        '<g class="pullg"><line x1="205" y1="150" x2="205" y2="330" stroke="#9be564" stroke-width="2"/>'
        '<circle cx="205" cy="338" r="7" fill="#9be564"/></g>'
        '</svg>'
    )


def lamp_scene():
    """The lamp and the login card are always on the page. Pulling the string toggles the light with smooth fades."""
    n = st.session_state.get("lamp_n", 0)
    st.markdown(LAMP_CSS, unsafe_allow_html=True)
    st.markdown(lamp_state_css(n), unsafe_allow_html=True)
    left, right = st.columns(2, gap="large", vertical_alignment="center")
    with left:
        with st.container(key="lampwrap"):
            st.markdown(lamp_svg(), unsafe_allow_html=True)
            if st.button(" ", key="lamp_pull", help=t("Pull the string")):
                st.session_state.lamp_n = n + 1
                st.rerun()
            st.markdown(f'<p class="lamphint">{t("Pull the string to turn on the light")}</p>', unsafe_allow_html=True)
    st.markdown(legal_links(), unsafe_allow_html=True)
    return right


# ---------- Privacy and Terms pages (open with ?doc=privacy or ?doc=terms, no login needed) ----------
LEGAL_UPDATED = "23 October 2026"

PRIVACY_TEXT = [
    ("Who runs Gigflare",
     "Gigflare is a university project made by {name} ({university}) for the {course}. It is free to use."),
    ("What we save",
     "When you sign up we save your name, your email, and your password and recovery word in scrambled form (a salted hash), "
     "so nobody can read them back. If you fill in My Profile, we save that profile. We also save the history of your requests and "
     "the AI answers, so you can see them again on the History page. This data is saved in a Google Firebase Firestore database (a Google service that stores data online)."),
    ("What is sent to the AI companies",
     "When you press send, your text, your saved profile and any file you attached are sent to the AI you chose: Google Gemini, Groq or OpenRouter. "
     "OpenRouter may pass your request on to another company that runs the model. These companies have their own privacy policies. "
     "Please do not enter passwords, bank details or other private information into the tools."),
    ("Staying logged in",
     "When you log in, Gigflare puts one cookie in your browser. It keeps you logged in for {days} days, even if you reload the page. "
     "The cookie holds a random code, not your password. Pressing Log out removes it."),
    ("Your own API key",
     "If you type your own API key in the account menu, it is kept only while your session is open. It is not saved in our files."),
    ("Ads and tracking",
     "Gigflare shows no ads and has no analytics or tracking code of its own. The login cookie above is the only cookie we set. The hosting service may keep technical logs and may use its own cookies to run the app."),
    ("Sharing",
     "We do not sell your data. Your data is shared only as described above, to get an answer from the AI you chose."),
    ("How long we keep data",
     "Your data stays until it is deleted. It is kept in the database, so it is not lost when the app goes to sleep or restarts."),
    ("Your choices",
     "You can ask for your account and saved data to be deleted. {contact}"),
    ("Changes",
     "If this page changes, the date at the top changes too."),
]

TERMS_TEXT = [
    ("About these terms",
     "By using Gigflare you agree to these terms. Gigflare is a free university project and is provided as it is."),
    ("Your account",
     "Give correct information when you sign up and keep your password and recovery word private. You are responsible for what happens in your account."),
    ("AI answers",
     "The answers are written by AI models from other companies. They can be wrong or incomplete. Read every proposal, price and reply, and fix it before you send it to a client. "
     "You are responsible for what you send. Suggested prices and match scores are only estimates. Nothing here is legal, tax or financial advice."),
    ("What you may not do",
     "Do not use Gigflare for anything illegal, to mislead or spam clients, or to harm others. Do not upload files you have no right to share. "
     "Do not try to break the app, overload it, or get into other people's accounts."),
    ("Other companies",
     "Gigflare is not connected to Upwork, Fiverr or Freelancer. Their names are used only to describe the style of a proposal. "
     "The terms of the AI companies you choose also apply when your request is sent to them."),
    ("Availability",
     "The app runs on free hosting and free AI plans, which have limits. It can be slow or stop working, and features can change or be removed. "
     "We may delete accounts that break these terms."),
    ("Liability",
     "Gigflare is provided without any promise that it will work without errors. As far as the law allows, the developer is not responsible for losses "
     "that come from using Gigflare or from the AI answers."),
    ("Changes",
     "If these terms change, the date at the top changes too. {contact}"),
]


def legal_page(kind):
    """A plain page for the Privacy Policy or the Terms and Conditions."""
    title, rows = ("Privacy Policy", PRIVACY_TEXT) if kind == "privacy" else ("Terms and Conditions", TERMS_TEXT)
    contact = f"Contact: {escape(CONTACT_EMAIL)}." if CONTACT_EMAIL else ""
    fill = {"name": escape(DEVELOPER["name"]), "university": escape(DEVELOPER["university"]), "course": escape(DEVELOPER["course"]), "contact": contact, "days": SESSION_DAYS}
    body = "".join(f"<h3>{escape(head)}</h3><p>{text.format(**fill)}</p>" for head, text in rows)
    st.markdown(
        """<style>
        .stApp::before, .stApp::after { display: none !important; }
        .legal-wrap { max-width: 760px; margin: 0 auto; }
        .legal-wrap h1 { margin-bottom: 4px; }
        .legal-wrap h3 { margin: 26px 0 6px 0; font-size: 19px; }
        .legal-wrap p { line-height: 1.65; color: #2c4a39; }
        .legal-wrap small { color: #5a7766; }
        </style>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="legal-wrap"><div class="brand"><div class="logo">{LOGO_SVG}</div><div><b>Gigflare</b></div></div>'
        f'<h1>{title}</h1><small>Last updated {LEGAL_UPDATED}</small>{body}'
        f'<p style="margin-top:30px"><a href="./" target="_self">Back to Gigflare</a></p></div>',
        unsafe_allow_html=True,
    )


def legal_links():
    """Small Privacy and Terms links. They open in a new tab so nobody gets logged out."""
    return (f'<p class="legal"><a href="?doc=privacy" target="_blank" rel="noopener">{t("Privacy")}</a>'
            f'<a href="?doc=terms" target="_blank" rel="noopener">{t("Terms")}</a></p>')


# ---------- Landing page (shown before login) ----------
def landing_page():
    top_left, top_right = st.columns([5, 1.6], vertical_alignment="center")
    top_left.markdown(
        '<div class="topbar"><div class="brand"><div class="logo">' + LOGO_SVG + "</div>"
        f'<div><b>Gigflare</b><br><small>{t("AI assistant for freelancers")}</small></div></div></div>',
        unsafe_allow_html=True,
    )
    with top_right:
        lang_picker("land")

    right = lamp_scene()

    with right:
        with st.container(border=True, key="lampcard"):
            st.markdown(f'<div class="cardhead"><small>GIGFLARE</small><b>{t("Welcome back")}.</b><span>{t("Log in or create your account")}</span></div>', unsafe_allow_html=True)
            tab_in, tab_up, tab_fp = st.tabs([t("Log in"), t("Sign up"), t("Forgot password")])

            with tab_in:
                with st.form("login_form"):
                    email = st.text_input(t("Email"), key="login_email")
                    password = st.text_input(t("Password"), type="password", key="login_password")
                    submit_in = st.form_submit_button(t("Log in"), type="primary")
                if submit_in:
                    user = log_in(email, password)
                    if user:
                        st.session_state.user = user
                        st.session_state.just_logged_in = True
                        start_session(user["email"])
                        st.rerun()
                    else:
                        st.error(t("Wrong email or password."))

            with tab_up:
                with st.form("signup_form"):
                    name = st.text_input(t("Full name"), key="signup_name")
                    email = st.text_input(t("Email"), key="signup_email")
                    password = st.text_input(t("Password (8 or more characters)"), type="password", key="signup_password")
                    confirm = st.text_input(t("Confirm password"), type="password", key="signup_confirm")
                    recovery = st.text_input(t("Recovery word (to reset your password later)"), key="signup_recovery",
                                             help=t("A word only you know, for example your first school or favourite food. Remember it."))
                    submit_up = st.form_submit_button(t("Create account"), type="primary")
                if submit_up:
                    user, error = sign_up(name, email, password, confirm, recovery)
                    if user:
                        st.session_state.user = user
                        st.session_state.just_logged_in = True
                        start_session(user["email"])
                        st.rerun()
                    else:
                        st.error(error)

            with tab_fp:
                with st.form("forgot_form"):
                    fp_email = st.text_input(t("Email"), key="fp_email")
                    fp_word = st.text_input(t("Recovery word"), key="fp_word")
                    fp_new = st.text_input(t("New password (8 or more characters)"), type="password", key="fp_new")
                    fp_confirm = st.text_input(t("Confirm new password"), type="password", key="fp_confirm")
                    submit_fp = st.form_submit_button(t("Reset password"), type="primary")
                if submit_fp:
                    ok, message = reset_password(fp_email, fp_word, fp_new, fp_confirm)
                    (st.success if ok else st.error)(message)


# ---------- Privacy / Terms pages need no login ----------
if st.query_params.get("doc") in ("privacy", "terms"):
    legal_page(st.query_params.get("doc"))
    st.stop()

# ---------- Not logged in? Show the landing page and stop ----------
WAIT_CSS = """
<style>
[data-testid="stAppViewContainer"]::after { content: ""; position: fixed; inset: 0; z-index: 100000; pointer-events: none;
    background: radial-gradient(ellipse 80% 70% at 30% 50%, #062319 0%, #041710 55%, #020b07 100%);
    animation: gfwait 0.6s ease 4s forwards; }
@keyframes gfwait { to { opacity: 0; visibility: hidden; } }
</style>
"""

if "user" not in st.session_state:
    restored = restore_session()
    if restored:
        st.session_state.user = restored
        st.session_state.just_logged_in = True
if "user" not in st.session_state:
    if st.session_state.pop("clear_cookie", False) or st.session_state.pop("bad_token", False):
        cookie_script("", 0)
        st.session_state["ls_checked"] = True
    if not st.session_state.get("ls_checked"):
        saved_token = browser_token()
        if saved_token is None:
            # The browser has not answered yet. Show a calm dark screen instead of flashing the login page.
            st.markdown(WAIT_CSS, unsafe_allow_html=True)
            landing_page()
            st.stop()
        st.session_state["ls_checked"] = True
        if saved_token:
            restored = restore_session(saved_token)
            if restored:
                st.session_state.user = restored
                st.session_state.just_logged_in = True
if "user" not in st.session_state:
    landing_page()
    st.stop()

# ---------- From here on, the user is logged in ----------
user = st.session_state.user

# Put the login cookie in the browser (only right after logging in)
if st.session_state.get("pending_cookie"):
    cookie_script(st.session_state.pop("pending_cookie"), SESSION_DAYS)

# Smooth entrance right after logging in: the dark green of the lamp page fades away,
# the top bar slides down and the page content rises in.
if st.session_state.pop("just_logged_in", False):
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"]::after { content: ""; position: fixed; inset: 0; z-index: 100000; pointer-events: none;
            background: radial-gradient(ellipse 80% 70% at 30% 50%, #062319 0%, #041710 55%, #020b07 100%);
            animation: enterfade 1.1s ease-out 0.05s both; }
        div:has(> .st-key-topnav) { animation: navdown 0.8s cubic-bezier(0.2, 0.7, 0.2, 1) 0.35s both; }
        div[data-testid="stMainBlockContainer"] > div > div:not(:has(.st-key-topnav)) { animation: pagerise 0.9s cubic-bezier(0.2, 0.7, 0.2, 1) 0.5s both; }
        @keyframes enterfade { from { opacity: 1; } to { opacity: 0; } }
        @keyframes navdown { from { transform: translateY(-100%); opacity: 0; } to { transform: none; opacity: 1; } }
        @keyframes pagerise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
        </style>
        """,
        unsafe_allow_html=True,
    )
profile = load_profile()
history = load_history()
done = sum(1 for v in profile.values() if v.strip())

# ---------- Top menu bar (replaces the old sidebar) ----------
TOOL_PAGES = ["Job Analyzer", "Proposal Generator", "Bid Helper", "Client Reply", "Portfolio Tips"]

if "page" not in st.session_state:
    st.session_state.page = "Home"
page = st.session_state.page

# Keys stay hidden: they are read from .streamlit/secrets.toml.
# If the chosen AI has no key, a small box inside the account menu lets the user type one.
if "ai_pick" not in st.session_state:
    st.session_state.ai_pick = next((n for n in PROVIDERS if get_key(n)), "Gemini")
ai = st.session_state.ai_pick


def slug(text):
    return text.lower().replace(" ", "_")


TOOL_HINTS = {
    "Job Analyzer": "Check a job post before you bid",
    "Proposal Generator": "Write a proposal that sounds like you",
    "Bid Helper": "Get a fair price and delivery time",
    "Client Reply": "Answer a client in the right tone",
    "Portfolio Tips": "Improve your headline and bio",
}


def nav_button(name, prefix):
    """One menu button. The page you are on is shown as the highlighted (primary) one."""
    label = f"**{t(name)}**  \n{t(TOOL_HINTS[name])}" if prefix == "navt" else t(name)
    st.button(
        label, key=f"{prefix}_{slug(name)}", on_click=go, args=(name,),
        type="primary" if st.session_state.page == name else "secondary",
        icon=PAGES[name] if prefix != "navd" else None,
    )


def top_nav():
    page_now = st.session_state.page
    with st.container(key="topnav", horizontal=True, vertical_alignment="center"):
        st.markdown(
            f'<div class="navbrand"><div class="logo lime">{LOGO_SVG}</div><b>Gigflare</b></div>',
            unsafe_allow_html=True,
        )
        # Links (hidden on phones)
        with st.container(key="topnav_links", horizontal=True, vertical_alignment="center"):
            for name in ("Home", "My Profile"):
                nav_button(name, "navd")
            # the key includes the page, so the menu is closed again after you pick a tool
            tools_key = ("navtoolson_" if page_now in TOOL_PAGES else "navtools_") + slug(page_now)
            with st.popover(t("Tools"), key=tools_key):
                st.markdown(f'<p class="toolshead">{t("Your tools")}</p>', unsafe_allow_html=True)
                for name in TOOL_PAGES:
                    nav_button(name, "navt")
            for name in ("History", "FAQ", "Developer"):
                nav_button(name, "navd")
        # Menu button (phones only)
        with st.container(key="topnav_menu"):
            with st.popover("", icon=":material/menu:", key=f"navmenu_{slug(page_now)}"):
                for name in PAGES:
                    nav_button(name, "navm")
        # Account menu and Log out
        with st.container(key="topnav_right", horizontal=True, vertical_alignment="center"):
            lang_picker("top")
            has_key = bool(get_key(ai))
            with st.popover(
                user["name"].split()[0], key="navaccount",
                icon=":material/account_circle:" if has_key else ":material/warning:",
            ):
                st.markdown(
                    f'<div class="account"><div class="avatar">{escape(user["name"][:1].upper())}</div>'
                    f'<div><b>{escape(user["name"])}</b><br><small>{escape(user["email"])}</small></div></div>',
                    unsafe_allow_html=True,
                )
                if has_key:
                    st.markdown(f'<span class="chip chip-ok">● {ai} {t("connected")}</span>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<span class="chip chip-no">● {ai}: {t("no key")}</span>', unsafe_allow_html=True)
                    st.text_input(
                        f"{ai} key", type="password", label_visibility="collapsed", placeholder=t("Paste your {ai} key", ai=ai),
                        key="typed_" + ai,
                        on_change=lambda: st.session_state.update({"saved_key_" + ai: st.session_state["typed_" + ai]}),
                    )
                    st.caption(t("Free key:") + " " + PROVIDERS[ai]["link"])
                st.button(t("Log out"), icon=":material/logout:", on_click=log_out, key="logout_acct")
            st.button(t("Log out"), icon=":material/logout:", on_click=log_out, key="logout_top")


top_nav()

# ---------- Home ----------
if page == "Home":
    home_banner(user['name'].split()[0])

    c1, c2, c3 = st.columns(3)
    c1.metric(t("Profile complete"), t("{n} / 6 fields", n=done))
    c2.metric(t("Proposals written"), sum(1 for h in history if h["kind"] == "Proposal"))
    c3.metric(t("Results saved"), len(history))

    st.markdown(f'<p class="sectionhead">{t("Your tools")}</p>'
                f'<p class="sectionsub">{t("Pick a tool to get started.")}</p>', unsafe_allow_html=True)
    tool_cards(with_buttons=True)

    st.markdown(f'<p class="sectionhead">{t("How it works")}</p>'
                f'<p class="sectionsub">{t("Three simple steps.")}</p>', unsafe_allow_html=True)
    how_it_works()

    st.markdown(f'<p class="sectionhead">{t("Recent activity")}</p>', unsafe_allow_html=True)
    if history:
        for h in reversed(history[-5:]):
            with st.expander(f"{t(h['kind'])} · {h['time']}" + (f" · {h['ai']}" if h.get("ai") else "")):
                st.write(h["text"])
    else:
        st.info(t("Nothing yet. Your results will show here."))

# ---------- Profile ----------
elif page == "My Profile":
    banner("My Profile")
    left, right = st.columns(2)

    with left:
        name = st.text_input(t("Your name"), value=profile["name"] or user["name"])
        a, b = st.columns(2)
        title = a.text_input(t("Your title"), value=profile["title"], placeholder=t("e.g. Python Developer"))
        rate = b.text_input(t("Hourly rate"), value=profile["rate"], placeholder=t("e.g. $10 per hour"))
        skills = st.text_area(t("Your skills"), value=profile["skills"], height=110)
        experience = st.text_area(t("Your experience"), value=profile["experience"], height=110)
        past_work = st.text_area(t("Past work / projects"), value=profile["past_work"], height=110)
        if st.button(t("Save Profile"), type="primary", icon=":material/save:"):
            profile = {
                "name": name,
                "title": title,
                "rate": rate,
                "skills": skills,
                "experience": experience,
                "past_work": past_work,
            }
            save_profile(profile)
            done = sum(1 for v in profile.values() if v.strip())
            st.success(t("Profile saved!"))

    with right:
        st.subheader(t("Saved profile"))
        st.progress(done / 6, text=t("{done} of 6 fields filled", done=done))
        with st.container(border=True):
            st.markdown(f"**{t('Name:')}** {profile['name'] or t('Not set')}")
            st.markdown(f"**{t('Title:')}** {profile['title'] or t('Not set')}")
            st.markdown(f"**{t('Hourly rate:')}** {profile['rate'] or t('Not set')}")
            st.markdown(f"**{t('Skills:')}** {profile['skills'] or t('Not set')}")
            st.markdown(f"**{t('Experience:')}** {profile['experience'] or t('Not set')}")
            st.markdown(f"**{t('Past work:')}** {profile['past_work'] or t('Not set')}")

    st.write("")
    tips([
        ("Use real details", "The AI can only use what you write here, so be honest and specific."),
        ("List skills clearly", "Name tools and languages, for example Python, Excel, Streamlit."),
        ("Add past work", "Even small projects help the AI write proposals that sound real."),
    ])

# ---------- Job Analyzer ----------
elif page == "Job Analyzer":
    banner("Job Analyzer")
    send = chat_box("analyze", "Paste the job post here...", text_key="analyze_post", sample=SAMPLE_JOB, height=170)

    if send and check_ready((st.session_state.analyze_post, t("Please paste a job post."))):
        prompt = (
            "You are a helpful assistant for a freelancer. Read the job post and the freelancer profile.\n"
            "Use simple words. Give these parts, each with a short heading:\n"
            "1. What the client wants (2 lines)\n"
            "2. Skills needed\n"
            "3. Match with my profile (score out of 10 and one line why)\n"
            "4. Red flags (write 'none' if there are none)\n"
            "5. Three smart questions to ask the client\n\n"
            f"FREELANCER PROFILE:\n{profile_text(profile)}\n\n"
            f"JOB POST:\n{st.session_state.analyze_post}"
        )
        run_ai("Analysis", prompt)
    show_result("Analysis", "job_analysis.txt")

    st.write("")
    tips([
        ("Paste the whole post", "More detail gives a better match score."),
        ("Read the red flags", "Be careful with unclear pay or a very big job for a small budget."),
        ("Ask the questions", "Smart questions show the client you are serious."),
    ])

# ---------- Proposal Generator ----------
elif page == "Proposal Generator":
    banner("Proposal Generator")

    def proposal_options():
        a, b = st.columns(2)
        a.selectbox(t("Platform"), ["Upwork", "Fiverr", "Freelancer"], key="prop_platform")
        b.selectbox(t("Tone"), ["Professional", "Friendly", "Confident"], key="prop_tone", format_func=t)
        st.slider(t("Maximum words"), 100, 300, 200, step=50, key="prop_words")

    send = chat_box("proposal", "Paste the job post here, then press send...", text_key="job_post",
                    sample=SAMPLE_JOB, options=proposal_options, height=170)

    if send and check_ready((st.session_state.job_post, t("Please paste a job post."))):
        platform, tone, words = st.session_state.prop_platform, st.session_state.prop_tone, st.session_state.prop_words
        prompt = (
            "You are an expert freelance proposal writer.\n"
            f"Write a short, personal {platform} proposal (under {words} words) in a {tone.lower()} tone.\n"
            "Use the freelancer's profile. Start by showing you understood the client's problem. "
            "Mention only skills and work that match the job. "
            "Use simple, natural words. No buzzwords, no emojis. "
            "Do not sound generic. End with a clear next step. Write it in the same language as the job post.\n\n"
            f"FREELANCER PROFILE:\n{profile_text(profile)}\n\n"
            f"JOB POST:\n{st.session_state.job_post}"
        )
        run_ai("Proposal", prompt)
    show_result("Proposal", "proposal.txt")

    st.write("")
    tips([
        ("Start with their problem", "Clients read the first two lines. Show you understood the job."),
        ("Keep it short", "Under 200 words is easier to read."),
        ("Finish with a next step", "Ask one clear question, like when you can talk."),
    ])

# ---------- Bid Helper ----------
elif page == "Bid Helper":
    banner("Bid Helper")

    def bid_options():
        st.selectbox(t("Your level"), ["Beginner", "Intermediate", "Expert"], key="bid_level", format_func=t)

    send = chat_box("bid", "Paste the job post here, then press send...", text_key="bid_post",
                    sample=SAMPLE_JOB, options=bid_options, height=170)

    if send and check_ready((st.session_state.bid_post, t("Please paste a job post."))):
        level = st.session_state.bid_level
        prompt = (
            "You are a freelance pricing advisor. Use simple words.\n"
            f"The freelancer's level is: {level}.\n"
            "Based on the job post and the freelancer profile, give:\n"
            "1. Estimated hours of work\n"
            "2. Suggested price range in USD (low, fair, high)\n"
            "3. Suggested delivery time\n"
            "4. What to include in the offer so it looks worth the price\n"
            "5. One tip for negotiation\n"
            "If the client states a budget, say whether it is fair.\n\n"
            f"FREELANCER PROFILE:\n{profile_text(profile)}\n\n"
            f"JOB POST:\n{st.session_state.bid_post}"
        )
        run_ai("Bid", prompt)
    show_result("Bid", "bid_suggestion.txt")

    st.write("")
    tips([
        ("Choose your level honestly", "Beginner, Intermediate or Expert changes the price a lot."),
        ("Check the client's budget", "The AI tells you if the budget is fair for the work."),
        ("Sell more than the price", "List what is included, like revisions and delivery time."),
    ])

# ---------- Client Reply ----------
elif page == "Client Reply":
    banner("Client Reply")

    def reply_options():
        a, b = st.columns(2)
        a.selectbox(t("Tone of reply"), ["Polite", "Friendly", "Firm", "Professional"], key="reply_tone", format_func=t)
        b.selectbox(t("Language"), ["English", "Urdu", "Roman Urdu"], key="reply_language")

    send = chat_box("reply", "Paste the client's message here, then press send...", text_key="client_message",
                    options=reply_options, height=170)

    if send and check_ready((st.session_state.client_message, t("Please paste the client's message."))):
        tone, language = st.session_state.reply_tone, st.session_state.reply_language
        prompt = (
            f"Write a {tone.lower()} reply to this client message from a freelancer.\n"
            f"Write it in {language}"
            + (" (Urdu written in English letters)." if language == "Roman Urdu" else ".")
            + "\nKeep it short and clear.\n\n"
            f"FREELANCER PROFILE:\n{profile_text(profile)}\n\n"
            f"CLIENT MESSAGE:\n{st.session_state.client_message}"
        )
        run_ai("Reply", prompt)
    show_result("Reply", "reply.txt")

    st.write("")
    tips([
        ("Pick the right tone", "Use Firm only when you need to set a limit. Open the + button to change tone and language."),
        ("Match the client's language", "Use Urdu or Roman Urdu if the client writes that way."),
        ("Read before you send", "Check names, dates and prices in the reply."),
    ])

# ---------- Portfolio Tips ----------
elif page == "Portfolio Tips":
    banner("Portfolio Tips")
    steps = ["A better profile headline", "A short, strong bio", "Tips to describe your past projects", "Skills to add or highlight"]
    st.markdown("".join(f'<div class="step"><span>{i}</span>{t(x)}</div>' for i, x in enumerate(steps, 1)), unsafe_allow_html=True)
    st.write("")
    send = chat_box("portfolio", "The AI will review your saved profile. Choose an AI and press send.")

    if send and check_ready((profile["skills"], t("Please fill and save your profile first."))):
        prompt = (
            "You are a freelancing career coach.\n"
            "Based on this freelancer profile, give:\n"
            "1. A better profile headline\n"
            "2. A short, strong bio (3-4 lines)\n"
            "3. Tips to describe past projects better\n"
            "4. Skills they should add or highlight\n\n"
            f"FREELANCER PROFILE:\n{profile_text(profile)}"
        )
        run_ai("Suggestions", prompt)
    show_result("Suggestions", "suggestions.txt")

    st.write("")
    tips([
        ("Fill your profile first", "The tips use your saved skills and projects."),
        ("Be specific", "Name the tools you used and what the result was."),
        ("Update often", "Add every new project when you finish it."),
    ])

# ---------- History ----------
elif page == "History":
    banner("History")

    kinds = ["All"] + sorted({h["kind"] for h in history})
    choice = st.selectbox(t("Show"), kinds, format_func=t)
    items = [h for h in reversed(history) if choice == "All" or h["kind"] == choice]

    if not items:
        st.info(t("Nothing saved yet. Create a proposal or a reply and it will be saved here."))
    for h in items:
        with st.expander(f"{t(h['kind'])} · {h['time']}"):
            st.write(h["text"])

    if history:
        all_text = "\n\n----------\n\n".join(f"{h['kind']} ({h['time']})\n{h['text']}" for h in history)
        a, b, _ = st.columns([1, 1, 2])
        a.download_button(t("Download all"), all_text, file_name="history.txt", icon=":material/download:")
        if b.button(t("Clear history"), icon=":material/delete:"):
            save_history([])
            st.rerun()

# ---------- FAQ ----------
elif page == "FAQ":
    banner("FAQ")
    for question, answer in FAQ:
        with st.expander(question):
            st.write(answer)

# ---------- Developer ----------
elif page == "Developer":
    banner("Developer")
    initials = "".join(w[0] for w in DEVELOPER["name"].split()[:2]).upper()
    st.markdown(
        f'<div class="devcard"><div class="devavatar">{escape(initials)}</div><div>'
        f'<h2>{escape(DEVELOPER["name"])}</h2><p>{escape(DEVELOPER["role"])} at {escape(DEVELOPER["university"])}</p>'
        f'<span class="chip chip-line">{escape(DEVELOPER["semester"])}</span>'
        f'<span class="chip chip-line">{escape(DEVELOPER["roll"])}</span>'
        f'<span class="chip chip-line">{escape(DEVELOPER["course"])}</span></div></div>',
        unsafe_allow_html=True,
    )

    a, b = st.columns(2, gap="large")
    with a:
        st.markdown('<p class="sectionhead" style="margin-top:0">About this project</p>', unsafe_allow_html=True)
        st.write(
            "Gigflare is my individual project for the Generative AI course. "
            "It helps freelancers check job posts, write proposals, price their bids and reply to clients. "
            "The AI uses the freelancer's saved profile as context, so every answer is personal."
        )
    with b:
        st.markdown('<p class="sectionhead" style="margin-top:0">Tools used</p>', unsafe_allow_html=True)
        st.markdown(
            '<span class="chip chip-line">Python</span><span class="chip chip-line">Streamlit</span>'
            '<span class="chip chip-line">Google Gemini API</span><span class="chip chip-line">Groq</span><span class="chip chip-line">OpenRouter</span><span class="chip chip-line">Prompt engineering</span>'
            '<span class="chip chip-line">JSON files</span><span class="chip chip-line">AI assistant (Claude) for coding help</span>',
            unsafe_allow_html=True,
        )

    st.markdown('<p class="sectionhead">What I learned</p>', unsafe_allow_html=True)
    tips([
        ("How LLMs and APIs work", "I send a prompt to the AI the user chooses (Gemini, Groq or OpenRouter) and show the answer."),
        ("Prompts control the output", "Clear instructions and a profile as context give better results."),
        ("Keep keys private", "The API key lives in a secrets file, and passwords are saved scrambled."),
    ])

footer()
