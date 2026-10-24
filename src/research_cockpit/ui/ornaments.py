"""Engraving-style SVG line art and header helpers for the light-academia UI.

Everything is inline SVG in the palette's ink/sepia tones: no external images,
works offline, negligible page weight. Pure strings - no Streamlit imports -
so the art can be tested/rendered independently.
"""

from __future__ import annotations

import re

INK = "#2E2A24"
SEPIA = "#5C5346"
BORDER = "#D8CFBE"
GOLD = "#E8DCC4"
FOREST = "#4A5D45"


def _compact(svg: str) -> str:
    """Collapse to one line: markdown treats 4-space-indented lines inside
    injected HTML as code blocks, which would print the SVG source."""
    return " ".join(svg.split())


def static(svg: str) -> str:
    """The same art with its <style> (and thus all keyframes) stripped, for
    decorative placements - watermarks, empty states - that shouldn't add to
    the one-ambient-animation-per-page motion budget."""
    return re.sub(r"<style>.*?</style>", "", svg)


# ------------------------------------------------------------------ artwork

TEMPLE = _compact(f"""
<svg viewBox="0 0 320 150" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.6" stroke-linecap="round">
  <!-- pediment -->
  <path d="M20 52 L160 10 L300 52 Z"/>
  <path d="M40 48 L160 20 L280 48 Z" stroke-width="1"/>
  <circle cx="160" cy="36" r="6" fill="{GOLD}" stroke="{SEPIA}"/>
  <!-- acroteria -->
  <path d="M160 10 q 0 -6 5 -8 M160 10 q 0 -6 -5 -8"/>
  <path d="M20 52 q -6 -2 -8 -8 M300 52 q 6 -2 8 -8"/>
  <!-- entablature -->
  <path d="M20 52 H300 M26 59 H294 M20 66 H300"/>
  <!-- columns -->
  <g stroke-width="1.4">
    <g transform="translate(48 0)">
      <path d="M-12 70 H12 M-9 75 H9 M-7 75 V119 M7 75 V119 M0 77 V117"
            stroke-width="1"/>
      <path d="M-9 119 H9 M-12 124 H12"/>
    </g>
    <g transform="translate(104 0)">
      <path d="M-12 70 H12 M-9 75 H9 M-7 75 V119 M7 75 V119 M0 77 V117"
            stroke-width="1"/>
      <path d="M-9 119 H9 M-12 124 H12"/>
    </g>
    <g transform="translate(160 0)">
      <path d="M-12 70 H12 M-9 75 H9 M-7 75 V119 M7 75 V119 M0 77 V117"
            stroke-width="1"/>
      <path d="M-9 119 H9 M-12 124 H12"/>
    </g>
    <g transform="translate(216 0)">
      <path d="M-12 70 H12 M-9 75 H9 M-7 75 V119 M7 75 V119 M0 77 V117"
            stroke-width="1"/>
      <path d="M-9 119 H9 M-12 124 H12"/>
    </g>
    <g transform="translate(272 0)">
      <path d="M-12 70 H12 M-9 75 H9 M-7 75 V119 M7 75 V119 M0 77 V117"
            stroke-width="1"/>
      <path d="M-9 119 H9 M-12 124 H12"/>
    </g>
  </g>
  <!-- stylobate steps -->
  <path d="M16 130 H304 M10 137 H310 M4 144 H316"/>
</svg>
""")

_LAUREL_BRANCH = f"""
    <g fill="none" stroke="{SEPIA}" stroke-width="1.2" stroke-linecap="round">
      <path d="M112 14 C 92 12 66 13 34 17"/>
      <path d="M100 13 q -3 -8 -12 -9 q 3 8 12 9" fill="{GOLD}"/>
      <path d="M100 14 q -5 6 -14 5 q 5 -7 14 -5" fill="{GOLD}"/>
      <path d="M82 13 q -3 -8 -12 -9 q 3 8 12 9" fill="{GOLD}"/>
      <path d="M82 14 q -5 6 -14 5 q 5 -7 14 -5" fill="{GOLD}"/>
      <path d="M64 14 q -3 -8 -12 -9 q 3 8 12 9" fill="{GOLD}"/>
      <path d="M64 15 q -5 6 -14 5 q 5 -7 14 -5" fill="{GOLD}"/>
      <path d="M46 15 q -3 -7 -11 -8 q 3 7 11 8" fill="{GOLD}"/>
    </g>
"""

LAUREL = _compact(f"""
<svg viewBox="0 0 240 28" xmlns="http://www.w3.org/2000/svg">
  {_LAUREL_BRANCH}
  <g transform="translate(240 0) scale(-1 1)">{_LAUREL_BRANCH}</g>
  <path d="M120 8 L126 14 L120 20 L114 14 Z" fill="{GOLD}" stroke="{SEPIA}"
        stroke-width="1.2"/>
</svg>
""")

ASK_TRIPOD = _compact(f"""
<svg viewBox="0 0 100 124" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.5" stroke-linecap="round">
  <style>
    .rc-tripod-flame {{
      transform-box: view-box; transform-origin: 50px 34px;
      animation: rc-tripod-flame 3.2s ease-in-out infinite;
    }}
    @keyframes rc-tripod-flame {{
      0%, 100% {{ transform: scale(1); opacity: .9; }}
      50% {{ transform: scale(.88) translateY(1.5px); opacity: .55; }}
    }}
  </style>
  <!-- oracle flame -->
  <g class="rc-tripod-flame">
    <path d="M50 14 Q 43 24 50 34 Q 57 24 50 14 Z" fill="{GOLD}"/>
  </g>
  <!-- bowl -->
  <ellipse cx="50" cy="38" rx="26" ry="6"/>
  <path d="M24 38 C 26 50 38 56 50 56 C 62 56 74 50 76 38"/>
  <!-- ring handles -->
  <circle cx="24" cy="35" r="4" stroke-width="1.2"/>
  <circle cx="76" cy="35" r="4" stroke-width="1.2"/>
  <!-- meander band -->
  <path d="M36 47 h4 v-3 h4 v3 h4 v-3 h4 v3 h4 v-3 h4 v3" stroke-width="0.9"/>
  <!-- legs -->
  <path d="M34 53 C 30 74 26 92 20 108"/>
  <path d="M66 53 C 70 74 74 92 80 108"/>
  <path d="M50 56 V 108"/>
  <!-- stretcher ring -->
  <path d="M28 86 C 36 91 64 91 72 86" stroke-width="1"/>
  <!-- feet -->
  <path d="M15 108 H25 M75 108 H85 M45 108 H55" stroke-width="1.3"/>
</svg>
""")

LIBRARY_CAT = _compact(f"""
<svg viewBox="0 0 132 116" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.6" stroke-linecap="round"
     stroke-linejoin="round">
  <!-- stack of books -->
  <path d="M20 92 H116 V104 H20 Z"/>
  <path d="M14 104 H118 V115 H14 Z"/>
  <path d="M28 98 H62 M74 98 H104" stroke-width="1"/>
  <path d="M22 110 H56 M68 110 H100" stroke-width="1"/>
  <!-- curled sleeping cat -->
  <path d="M28 92 C 24 66 44 46 68 46 C 92 46 108 60 108 76 C 108 86 102 92 94 92 Z"/>
  <!-- head resting on paws, at the right -->
  <circle cx="90" cy="66" r="16"/>
  <!-- ears -->
  <path d="M80 56 L 77 43 L 89 50 Z" fill="{GOLD}"/>
  <path d="M94 51 L 101 40 L 104 54 Z" fill="{GOLD}"/>
  <!-- closed, contented eyes -->
  <path d="M82 66 q 3.5 3 7 0 M94 65 q 3.5 3 7 0" stroke-width="1.4"/>
  <!-- nose + smile -->
  <path d="M89 72 q 2 2 4 0" stroke-width="1.2"/>
  <path d="M90 70 l 1.5 1.5 l 1.5 -1.5 Z" fill="{SEPIA}" stroke-width="1"/>
  <!-- whiskers -->
  <path d="M78 70 q -6 -1 -11 1 M78 73 q -6 1 -10 3 M104 69 q 6 -1 11 1 M104 72 q 6 1 10 3"
        stroke-width="1"/>
  <!-- tucked front paws -->
  <path d="M70 92 q 4 -6 10 -4 M60 92 q 4 -6 10 -4" stroke-width="1.2"/>
  <!-- tail tucked along the body -->
  <path d="M30 91 C 20 91 15 84 20 78 Q 24 73 30 77" stroke-width="1.4"/>
  <!-- stripes on the back -->
  <path d="M46 52 q 4 6 2 12 M58 48 q 3 6 2 12 M70 47 q 2 6 1 12" stroke-width="1.1"/>
  <!-- a few zzz, floating -->
  <style>
    .rc-cat-zz {{ animation: rc-cat-zz 3.4s ease-in-out infinite; }}
    @keyframes rc-cat-zz {{
      0% {{ transform: translateY(2px); opacity: .15; }}
      45% {{ opacity: .95; }}
      100% {{ transform: translateY(-6px); opacity: 0; }}
    }}
  </style>
  <g class="rc-cat-zz">
    <path d="M112 44 h7 l-7 7 h7 M120 30 h6 l-6 6 h6" stroke-width="1.3"/>
  </g>
</svg>
""")

OPEN_BOOK = _compact(f"""
<svg viewBox="0 0 130 100" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.5" stroke-linecap="round">
  <style>
    .rc-book-flip {{
      transform-box: view-box; transform-origin: 65px 80px;
      animation: rc-book-flip 7s ease-in-out infinite;
    }}
    @keyframes rc-book-flip {{
      0%, 54% {{ transform: none; opacity: 0; }}
      60% {{ opacity: .9; }}
      74% {{ transform: rotate(-22deg) scaleX(.72); opacity: .9; }}
      88% {{ transform: rotate(-42deg) scaleX(.3); opacity: 0; }}
      100% {{ opacity: 0; }}
    }}
    .rc-book-ribbon {{
      transform-box: view-box; transform-origin: 94px 18px;
      animation: rc-book-ribbon 5s ease-in-out infinite;
    }}
    @keyframes rc-book-ribbon {{
      0%, 100% {{ transform: rotate(-2.5deg); }}
      50% {{ transform: rotate(2.5deg); }}
    }}
  </style>
  <!-- pages -->
  <path d="M65 26 C 50 14 32 14 14 20 V 76 C 32 70 50 70 65 82 Z"/>
  <path d="M65 26 C 80 14 98 14 116 20 V 76 C 98 70 80 70 65 82 Z"/>
  <!-- cover beneath -->
  <path d="M14 26 L8 30 V 84 C 30 76 52 78 65 90 C 78 78 100 76 122 84 V 30 L116 26"
        stroke-width="1.2"/>
  <!-- text lines following the page curl -->
  <g stroke-width="1">
    <path d="M22 32 Q 42 26 58 34 M22 43 Q 42 37 58 45 M22 54 Q 42 48 58 56
             M22 65 Q 42 59 58 67"/>
    <path d="M108 32 Q 88 26 72 34 M108 43 Q 88 37 72 45 M108 54 Q 88 48 72 56
             M108 65 Q 88 59 72 67"/>
  </g>
  <!-- a leaf mid-turn -->
  <path class="rc-book-flip" d="M65 26 C 80 14 98 14 116 20 V 76 C 98 70 80 70 65 82 Z"
        fill="#FBF8F1" stroke-width="1.2"/>
  <!-- ribbon marker -->
  <path class="rc-book-ribbon" d="M90 18 V 40 L 94 36 L 98 40 V 19" fill="{GOLD}"
        stroke-width="1.1"/>
</svg>
""")

AMPHORA = _compact(f"""
<svg viewBox="0 0 90 132" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.5" stroke-linecap="round">
  <path d="M28 8 H62 M31 14 H59"/>
  <path d="M33 14 C 33 26 20 34 20 52 C 20 84 32 102 41 116"/>
  <path d="M57 14 C 57 26 70 34 70 52 C 70 84 58 102 49 116"/>
  <path d="M41 116 H49 M35 122 H55 M31 128 H59"/>
  <!-- handles -->
  <path d="M31 20 C 12 24 10 42 22 48 M59 20 C 78 24 80 42 68 48"/>
  <!-- bands + meander -->
  <path d="M22 56 H68" stroke-width="1"/>
  <path d="M23 64 h6 v-4 h6 v4 h6 v-4 h6 v4 h6 v-4 h6 v4 h6" stroke-width="1"/>
  <path d="M24 72 H66" stroke-width="1"/>
</svg>
""")

HOURGLASS = _compact(f"""
<svg viewBox="0 0 90 112" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.5" stroke-linecap="round">
  <style>
    .rc-hg-rock {{
      transform-box: view-box; transform-origin: 45px 104px;
      animation: rc-hg-rock 6s ease-in-out infinite;
    }}
    @keyframes rc-hg-rock {{
      0%, 100% {{ transform: rotate(-2.5deg); }}
      50% {{ transform: rotate(2.5deg); }}
    }}
    .rc-hg-stream {{ animation: rc-hg-fall 1.2s linear infinite; }}
    @keyframes rc-hg-fall {{ to {{ stroke-dashoffset: -10; }} }}
  </style>
  <g class="rc-hg-rock">
    <path d="M14 8 H76 M14 104 H76"/>
    <path d="M10 5 H80 M10 107 H80" stroke-width="1.1"/>
    <!-- glass bulbs -->
    <path d="M21 11 C 21 36 41 44 44 56 C 41 68 21 76 21 101"/>
    <path d="M69 11 C 69 36 49 44 46 56 C 49 68 69 76 69 101"/>
    <!-- sand -->
    <path d="M27 16 C 31 28 38 35 45 41 C 52 35 59 28 63 16 Z" fill="{GOLD}"
          stroke-width="1"/>
    <path class="rc-hg-stream" d="M45 58 V 84" stroke-dasharray="1.5 3.5"
          stroke-width="1.2"/>
    <path d="M33 95 L45 82 L57 95 Z" fill="{GOLD}" stroke-width="1"/>
    <!-- side posts -->
    <path d="M16 8 V 104 M74 8 V 104" stroke-width="1.1"/>
  </g>
</svg>
""")

ASTROLABE = _compact(f"""
<svg viewBox="0 0 124 124" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.4" stroke-linecap="round">
  <circle cx="62" cy="66" r="52"/>
  <circle cx="62" cy="66" r="43" stroke-width="0.9" stroke-dasharray="3 5"/>
  <path d="M62 6 V 14 M56 10 q 6 -6 12 0" stroke-width="1.1"/>
  <!-- constellation -->
  <g stroke-width="1">
    <path d="M34 52 L52 44 L70 58 L88 46 M52 44 L58 78 L82 88 M58 78 L38 84"/>
  </g>
  <style>
    .rc-astro-a {{ animation: rc-astro-tw 4.2s ease-in-out infinite; }}
    .rc-astro-b {{ animation: rc-astro-tw 4.2s ease-in-out 2.1s infinite; }}
    @keyframes rc-astro-tw {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: .3; }}
    }}
  </style>
  <g fill="{SEPIA}" stroke="none">
    <g class="rc-astro-a">
      <circle cx="34" cy="52" r="2.6"/><circle cx="70" cy="58" r="2.4"/>
      <circle cx="58" cy="78" r="3.2"/><circle cx="38" cy="84" r="2.4"/>
    </g>
    <g class="rc-astro-b">
      <circle cx="52" cy="44" r="3.4"/><circle cx="88" cy="46" r="3"/>
      <circle cx="82" cy="88" r="2.6"/>
    </g>
  </g>
  <g stroke="{SEPIA}" stroke-width="1">
    <path d="M52 36 v-5 M52 44 m 8 0 h 5 M28 52 h-4 M88 38 v-4"/>
  </g>
</svg>
""")

SCROLL = _compact(f"""
<svg viewBox="0 0 130 96" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.5" stroke-linecap="round"
     stroke-linejoin="round">
  <!-- parchment sheet, slightly bowed -->
  <path d="M24 20 C 48 25 82 25 106 20 V 72 C 82 77 48 77 24 72 Z"/>
  <!-- left roller with knobs -->
  <rect x="13" y="15" width="11" height="62" rx="5.5"/>
  <path d="M18.5 15 V 8 M15 8 H22 M18.5 77 V 84 M15 84 H22" stroke-width="1.2"/>
  <path d="M19 20 V 72" stroke-width="0.9"/>
  <!-- right roller with knobs -->
  <rect x="106" y="15" width="11" height="62" rx="5.5"/>
  <path d="M111.5 15 V 8 M108 8 H115 M111.5 77 V 84 M108 84 H115" stroke-width="1.2"/>
  <path d="M112 20 V 72" stroke-width="0.9"/>
  <!-- text lines following the bow -->
  <g stroke-width="1">
    <path d="M32 33 C 52 36 78 36 98 33 M32 43 C 52 46 78 46 98 43
             M32 53 C 52 56 78 56 90 54"/>
  </g>
  <!-- wax seal with ribbon tails -->
  <circle cx="94" cy="62" r="6.5" fill="{GOLD}" stroke-width="1.1"/>
  <path d="M91 67 l -3 7 M97 67 l 3 7" stroke-width="1.1"/>
  <circle cx="94" cy="62" r="2.6" stroke-width="0.9"/>
</svg>
""")

CONSTELLATION_STAR = _compact(f"""
<svg viewBox="0 0 124 124" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.4" stroke-linecap="round">
  <style>
    .rc-con-pulse {{ animation: rc-con-pulse 3s ease-in-out infinite; }}
    @keyframes rc-con-pulse {{
      0%, 100% {{ opacity: .85; }}
      50% {{ opacity: .4; }}
    }}
  </style>
  <!-- constellation of notes (connected dots) -->
  <g stroke-width="1.1">
    <path d="M28 62 L48 38 L78 44 L98 30 M48 38 L56 72 L84 86 M56 72 L32 90"/>
    <path d="M78 44 L92 70 L84 86" stroke-dasharray="3 4"/>
  </g>
  <g fill="{SEPIA}" stroke="none">
    <g class="rc-con-pulse">
      <circle cx="28" cy="62" r="4"/><circle cx="78" cy="44" r="3.5"/>
      <circle cx="56" cy="72" r="4.5"/><circle cx="32" cy="90" r="3"/>
    </g>
    <circle cx="48" cy="38" r="5"/><circle cx="98" cy="30" r="4"/>
    <circle cx="84" cy="86" r="3.5"/><circle cx="92" cy="70" r="3"/>
  </g>
  <!-- label lines radiating from the larger nodes -->
  <g stroke-width="0.8" stroke="{SEPIA}">
    <path d="M48 33 v-8 h12"/><path d="M56 67 v-8 h10"/>
  </g>
</svg>
""")

CLAIMS_QUILL = _compact(f"""
<svg viewBox="0 0 100 120" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.4" stroke-linecap="round"
     stroke-linejoin="round">
  <!-- scroll/document -->
  <path d="M18 30 H82 V100 H18 Z"/>
  <path d="M18 30 Q12 30 12 36 V94 Q12 100 18 100" stroke-width="1.1"/>
  <!-- text lines -->
  <g stroke-width="0.9">
    <path d="M26 44 H70 M26 54 H66 M26 64 H60 M26 74 H50"/>
  </g>
  <!-- quill pen at an angle -->
  <path d="M60 88 L88 12 Q92 6 86 8 L62 82 Z" fill="{GOLD}" stroke-width="1.2"/>
  <path d="M62 82 L60 88 L66 86 Z" fill="{SEPIA}" stroke="none"/>
  <!-- nib -->
  <path d="M60 88 L58 94" stroke-width="1.5"/>
</svg>
""")

QUESTIONS_LANTERN = _compact(f"""
<svg viewBox="0 0 90 120" xmlns="http://www.w3.org/2000/svg" fill="none"
     stroke="{SEPIA}" stroke-width="1.4" stroke-linecap="round">
  <style>
    .rc-lantern-glow {{ animation: rc-lantern-glow 4s ease-in-out infinite; }}
    @keyframes rc-lantern-glow {{
      0%, 100% {{ opacity: .3; }}
      50% {{ opacity: .8; }}
    }}
  </style>
  <!-- top ring and chain -->
  <path d="M45 8 V16 M40 16 H50"/>
  <ellipse cx="45" cy="22" rx="14" ry="5"/>
  <!-- glass body -->
  <path d="M31 22 V78 Q31 88 45 88 Q59 88 59 78 V22"/>
  <!-- frame bars -->
  <path d="M31 42 H59 M31 62 H59" stroke-width="0.9"/>
  <!-- flame/glow -->
  <g class="rc-lantern-glow">
    <path d="M45 45 Q40 55 45 65 Q50 55 45 45 Z" fill="{GOLD}" stroke="none"/>
  </g>
  <!-- base -->
  <path d="M35 88 H55 M33 93 H57"/>
  <!-- question mark shadow -->
  <path d="M41 100 Q38 105 45 108 Q52 105 49 100" stroke-width="1"/>
  <circle cx="45" cy="114" r="1.5" fill="{SEPIA}" stroke="none"/>
</svg>
""")

# maps pages to their emblem - the sleeping cat guards the Library; Ask gets
# the Delphic tripod (consult the oracle)
EMBLEMS = {
    "Ask": ASK_TRIPOD,
    "Library": LIBRARY_CAT,
    "Reader": OPEN_BOOK,
    "Review": HOURGLASS,
    "Graph": ASTROLABE,
    "Citations": SCROLL,
    "Constellation": CONSTELLATION_STAR,
    "Claims": CLAIMS_QUILL,
    "Questions": QUESTIONS_LANTERN,
}

# every page: evocative H1 (set at the page_header call site) + a quieter
# functional kicker here - one voice across all nine pages
KICKERS = {
    "Ask": "consult the corpus",
    "Library": "the collection",
    "Reader": "folios & marginalia",
    "Review": "memoria technica",
    "Graph": "citations, mapped",
    "Citations": "styled & exported",
    "Constellation": "ideas, linked",
    "Claims": "outline & evidence",
    "Questions": "asked & pursued",
}


# ------------------------------------------------------------------ helpers


def sidebar_hero() -> str:
    return _compact(f"""
    <div class="rc-hero">
      <div class="rc-hero-temple">{TEMPLE}</div>
      <div class="rc-hero-title">Research Cockpit</div>
      <div class="rc-hero-tagline">a sunlit library for your papers</div>
    </div>
    """)


def page_header(page: str, title: str) -> str:
    emblem = EMBLEMS.get(page, "")
    kicker = KICKERS.get(page, "")
    return _compact(f"""
    <div class="rc-page-head">
      <div class="rc-emblem">{emblem}</div>
      <div class="rc-head-text">
        <div class="rc-kicker">{kicker}</div>
        <h1 class="rc-h1">{title}</h1>
      </div>
    </div>
    <div class="rc-laurel">{LAUREL}</div>
    """)


def watermark(page: str) -> str:
    # static copy: at 7% opacity an animation is invisible work and busts the
    # motion budget (the page emblem is each page's one ambient animation)
    return f'<div class="rc-watermark">{static(EMBLEMS.get(page, ""))}</div>'


def empty_state(page: str) -> str:
    """A large, faint, still emblem to set the mood above an empty-state
    message (the message itself stays a plain st.info for accessibility)."""
    return f'<div class="rc-empty">{static(EMBLEMS.get(page, ""))}</div>'
