"""
╔══════════════════════════════════════════════════════════════╗
║  Bewerbungs-Tracker  |  Google Sheets + Streamlit           ║
║  inkl. Agentur-Statusbericht als PDF                        ║
╚══════════════════════════════════════════════════════════════╝
Einmalig installieren:
  pip install streamlit pandas gspread google-auth reportlab openpyxl

Starten:
  streamlit run bewerbungen.py
"""

import io
import os
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_JUSTIFY

# ═══════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════
SHEET_NAME       = "Bewerbungen"
CREDENTIALS_FILE = "credentials.json"
WORKSHEET_NAME   = "Bewerbungen"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

STATUS_FARBEN = {
    "Versendet":        "#2E75B6",
    "Rückmeldung":      "#E8A838",
    "Gespräch geplant": "#BC8CFF",
    "Gespräch geführt": "#1ABC9C",
    "Angebot erhalten": "#3FB950",
    "Absage":           "#F85149",
    "Zurückgezogen":    "#8B949E",
}

SPALTEN = [
    "Datum", "Firma", "Stelle", "Ort", "Quelle",
    "Status", "Gehaltsvorstellung", "Nächster Schritt", "Wiedervorlage", "Notiz"
]

# ── Dein Profil ───────────────────────────────────────────────
PROFIL = {
    "name":        "Jens Stein",
    "adresse":     "La-Roche-Str. 53, 44629 Herne",
    "telefon":     "0176-43239370",
    "email":       "J.stein2802@gmail.com",
    "linkedin":    "https://www.linkedin.com/in/jens-stein-/",
    "erfahrung":   "20+ Jahre Erfahrung im Großhandel (METRO Deutschland GmbH) — Supply Chain, Stammdaten, Einkauf",
    "skills":      "SAP-basierte Systeme, MS Excel (Power Query, Pivot), Power BI, ETL-Pipelines, Stammdatenmanagement, JDA, ERP",
    "staerken":    "Verbinde operative Handelserfahrung mit modernen Daten-Tools. Eigenständige Entwicklung von ETL-Systemen und Power BI Dashboards.",
    "verfuegbar":  "Ab sofort",
    "gehalt":      "ab 55.000 € brutto p.a. (je nach Position)",
    "zielregion":  "Ruhrgebiet | Homeoffice möglich",
    "zielrollen":  "Stammdatenmanagement, Supply Chain Analyst, Data Analyst, Business Analyst",
}

# ═══════════════════════════════════════════════════════════════
# SCHRIFTART FÜR PDF
# ═══════════════════════════════════════════════════════════════
PDF_FONT      = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
for _p in [
    "C:/Windows/Fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]:
    if os.path.exists(_p):
        try:
            pdfmetrics.registerFont(TTFont("DVS",  _p))
            pdfmetrics.registerFont(TTFont("DVSB", _p.replace("DejaVuSans.ttf","DejaVuSans-Bold.ttf")))
            PDF_FONT      = "DVS"
            PDF_FONT_BOLD = "DVSB"
        except Exception:
            pass
        break

# ═══════════════════════════════════════════════════════════════
# GOOGLE SHEETS
# ═══════════════════════════════════════════════════════════════
@st.cache_resource
def get_worksheet():
    if "gcp_service_account" in st.secrets:
        info  = {k: v for k, v in st.secrets["gcp_service_account"].items()}
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    elif os.path.exists(CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    else:
        raise FileNotFoundError("credentials.json nicht gefunden.")
    client = gspread.authorize(creds)
    sh = client.open(SHEET_NAME)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=500, cols=len(SPALTEN))
        ws.append_row(SPALTEN)
    return ws

@st.cache_data(ttl=30)
def load_data() -> pd.DataFrame:
    ws         = get_worksheet()
    alle_werte = ws.get_all_values()
    if len(alle_werte) < 2:
        return pd.DataFrame(columns=SPALTEN)
    df = pd.DataFrame(alle_werte[1:], columns=alle_werte[0])
    df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()
    # Fehlende Spalten (z.B. nach Updates) leer auffüllen
    for col in SPALTEN:
        if col not in df.columns:
            df[col] = ""
    df["_row"] = range(2, len(df) + 2)
    return df

def save_row(datum, firma, stelle, ort, quelle, status, gehalt_v,
             naechster, wiedervorlage, notiz):
    ws = get_worksheet()
    ws.append_row([
        str(datum), firma, stelle, ort, quelle, status, gehalt_v,
        naechster,
        str(wiedervorlage) if wiedervorlage else "",
        notiz,
    ])
    load_data.clear()

# ═══════════════════════════════════════════════════════════════
# AGENTUR-STATUSBERICHT PDF
# ═══════════════════════════════════════════════════════════════
def deutschen_monat(d):
    monate = {"January":"Januar","February":"Februar","March":"März",
               "April":"April","May":"Mai","June":"Juni","July":"Juli",
               "August":"August","September":"September","October":"Oktober",
               "November":"November","December":"Dezember"}
    s = d.strftime("%d. %B %Y")
    for en, de in monate.items():
        s = s.replace(en, de)
    return s


def make_eigenbemuehungen_pdf(df: pd.DataFrame) -> bytes:
    """Schlichter Nachweis Eigenbemühungen für die Agentur für Arbeit."""
    from reportlab.pdfgen import canvas as rl_canvas
    buf  = io.BytesIO()
    W, H = A4
    c    = rl_canvas.Canvas(buf, pagesize=A4)
    BLAU = HexColor("#1f4e79")
    HELL = HexColor("#f0f4f8")
    GRAU = HexColor("#666666")
    WEISS = HexColor("#ffffff")

    def header():
        # Titel
        c.setFillColor(BLAU)
        c.setFont(PDF_FONT_BOLD, 14)
        c.drawString(20*mm, H-20*mm, "Nachweis Eigenbemühungen")
        c.setStrokeColor(BLAU)
        c.setLineWidth(1)
        c.line(20*mm, H-23*mm, W-20*mm, H-23*mm)

        # Kontaktdaten
        c.setFillColor(HexColor("#1a1a2e"))
        c.setFont(PDF_FONT_BOLD, 10)
        c.drawString(20*mm, H-30*mm, PROFIL["name"])
        c.setFont(PDF_FONT, 9)
        c.drawString(20*mm, H-36*mm,
            f"{PROFIL['adresse']}  |  {PROFIL['telefon']}  |  {PROFIL['email']}")

        # Datum rechts
        c.setFont(PDF_FONT, 9)
        c.setFillColor(GRAU)
        c.drawRightString(W-20*mm, H-30*mm,
            f"Stand: {date.today().strftime('%d.%m.%Y')}")
        c.drawRightString(W-20*mm, H-36*mm,
            f"Anzahl Bewerbungen: {len(df)}")

    header()

    # Tabellenkopf
    y = H - 48*mm
    c.setFillColor(BLAU)
    c.rect(20*mm, y-5*mm, W-40*mm, 10*mm, fill=1, stroke=0)
    c.setFillColor(WEISS)
    c.setFont(PDF_FONT_BOLD, 9)
    c.drawString(22*mm,  y, "Nr.")
    c.drawString(32*mm,  y, "Datum")
    c.drawString(55*mm,  y, "Firma / Unternehmen")
    c.drawString(105*mm, y, "Stelle / Position")
    c.drawString(153*mm, y, "Quelle")
    c.drawString(175*mm, y, "Status")
    y -= 12*mm

    for i, (_, row) in enumerate(df.iterrows()):
        if y < 28*mm:
            # Footer
            c.setFillColor(GRAU)
            c.setFont(PDF_FONT, 7)
            c.drawString(20*mm, 18*mm,
                "Dieser Nachweis wurde maschinell erstellt.")
            c.drawRightString(W-20*mm, 18*mm,
                f"Seite 1")
            c.showPage()
            header()
            y = H - 48*mm
            # Kopf wiederholen
            c.setFillColor(BLAU)
            c.rect(20*mm, y-5*mm, W-40*mm, 10*mm, fill=1, stroke=0)
            c.setFillColor(WEISS)
            c.setFont(PDF_FONT_BOLD, 9)
            c.drawString(22*mm, y, "Nr.")
            c.drawString(32*mm, y, "Datum")
            c.drawString(55*mm, y, "Firma / Unternehmen")
            c.drawString(105*mm, y, "Stelle / Position")
            c.drawString(153*mm, y, "Quelle")
            c.drawString(175*mm, y, "Status")
            y -= 12*mm

        # Zebrastreifen
        if i % 2 == 0:
            c.setFillColor(HELL)
            c.rect(20*mm, y-3*mm, W-40*mm, 8*mm, fill=1, stroke=0)

        c.setFillColor(HexColor("#1a1a2e"))
        c.setFont(PDF_FONT, 9)
        c.drawString(22*mm,  y, str(i+1))
        c.drawString(32*mm,  y, str(row.get("Datum",""))[:10])
        c.drawString(55*mm,  y, str(row.get("Firma",""))[:25])
        c.drawString(105*mm, y, str(row.get("Stelle",""))[:24])
        c.drawString(153*mm, y, str(row.get("Quelle",""))[:10])

        status = str(row.get("Status",""))
        farbe  = STATUS_FARBEN.get(status, "#8B949E")
        c.setFillColor(HexColor(farbe))
        c.roundRect(174*mm, y-2*mm, 16*mm, 6*mm, 1*mm, fill=1, stroke=0)
        c.setFillColor(WEISS)
        c.setFont(PDF_FONT_BOLD, 6)
        c.drawCentredString(182*mm, y, status[:12])

        y -= 9*mm

    # Footer
    c.setFillColor(GRAU)
    c.setFont(PDF_FONT, 7)
    c.drawString(20*mm, 18*mm,
        "Dieser Nachweis wurde maschinell erstellt.")
    c.save()
    return buf.getvalue()

def make_agentur_pdf(df: pd.DataFrame,
                     verfuegbar: str,
                     gehalt: str,
                     zielrollen: str,
                     region: str,
                     anmerkung: str) -> bytes:
    from reportlab.pdfgen import canvas as rl_canvas
    buf  = io.BytesIO()
    W, H = A4
    c    = rl_canvas.Canvas(buf, pagesize=A4)
    BLAU  = HexColor("#1f4e79")
    HELL  = HexColor("#f0f4f8")
    GRUEN = HexColor("#3FB950")
    GRAU  = HexColor("#555555")
    WEISS = HexColor("#ffffff")

    aktiv_df = df[~df["Status"].isin(["Absage","Zurückgezogen"])].copy()

    # ── HEADER ────────────────────────────────────────────────────
    c.setFillColor(BLAU)
    c.rect(0, H-38*mm, W, 38*mm, fill=1, stroke=0)
    c.setFillColor(WEISS)
    c.setFont(PDF_FONT_BOLD, 18)
    c.drawString(20*mm, H-16*mm, "Bewerbungs-Statusbericht")
    c.setFont(PDF_FONT, 10)
    c.drawString(20*mm, H-24*mm, f"{PROFIL['name']}  |  {PROFIL['adresse']}")
    if PROFIL.get("telefon"):
        c.drawString(20*mm, H-30*mm, f"Tel: {PROFIL['telefon']}  |  {PROFIL.get('email','')}")
    else:
        c.drawString(20*mm, H-30*mm, PROFIL.get("email",""))
    c.setFont(PDF_FONT, 9)
    c.drawRightString(W-20*mm, H-16*mm, f"Stand: {deutschen_monat(date.today())}")

    y = H - 50*mm

    # ── PROFIL-BOX ────────────────────────────────────────────────
    c.setFillColor(HELL)
    c.roundRect(20*mm, y-28*mm, W-40*mm, 32*mm, 2*mm, fill=1, stroke=0)

    c.setFillColor(BLAU)
    c.setFont(PDF_FONT_BOLD, 10)
    c.drawString(24*mm, y-4*mm, "Profil")

    c.setFillColor(HexColor("#1a1a2e"))
    c.setFont(PDF_FONT, 9)
    c.drawString(24*mm, y-10*mm, f"Erfahrung:    {PROFIL['erfahrung']}")
    c.drawString(24*mm, y-16*mm, f"Skills:       {PROFIL['skills'][:80]}")
    if len(PROFIL['skills']) > 80:
        c.drawString(36*mm, y-21*mm, PROFIL['skills'][80:])
        c.drawString(24*mm, y-26*mm, f"Zielrollen:   {zielrollen or PROFIL['zielrollen']}")
    else:
        c.drawString(24*mm, y-21*mm, f"Zielrollen:   {zielrollen or PROFIL['zielrollen']}")

    y -= 38*mm

    # ── ECKDATEN ──────────────────────────────────────────────────
    c.setFillColor(BLAU)
    c.setFont(PDF_FONT_BOLD, 10)
    c.drawString(20*mm, y, "Eckdaten")
    y -= 7*mm

    felder = [
        ("Verfügbar ab",       verfuegbar or "Nach Absprache"),
        ("Gehaltsvorstellung", gehalt     or "Nach Absprache"),
        ("Region",             region     or PROFIL["zielregion"]),
        ("Arbeitsmodell",      "Festanstellung | Vollzeit | Homeoffice möglich"),
    ]
    for label, wert in felder:
        c.setFillColor(HELL)
        c.rect(20*mm, y-4*mm, W-40*mm, 8*mm, fill=1, stroke=0)
        c.setFillColor(BLAU)
        c.setFont(PDF_FONT_BOLD, 9)
        c.drawString(22*mm, y, label + ":")
        c.setFillColor(HexColor("#1a1a2e"))
        c.setFont(PDF_FONT, 9)
        c.drawString(72*mm, y, wert)
        y -= 10*mm

    y -= 4*mm

    # ── BEWERBUNGSAKTIVITÄTEN ──────────────────────────────────────
    c.setFillColor(BLAU)
    c.setFont(PDF_FONT_BOLD, 10)
    c.drawString(20*mm, y, f"Bewerbungsaktivitäten  ({len(aktiv_df)} aktiv / {len(df)} gesamt)")
    y -= 8*mm

    # Tabellenkopf
    c.setFillColor(BLAU)
    c.rect(20*mm, y-4*mm, W-40*mm, 9*mm, fill=1, stroke=0)
    c.setFillColor(WEISS)
    c.setFont(PDF_FONT_BOLD, 8)
    c.drawString(22*mm,  y, "Datum")
    c.drawString(44*mm,  y, "Firma")
    c.drawString(90*mm,  y, "Stelle")
    c.drawString(138*mm, y, "Ort")
    c.drawString(160*mm, y, "Status")
    y -= 11*mm

    # Zeilen — nur aktive zuerst, dann abgeschlossene
    df_sortiert = pd.concat([
        aktiv_df,
        df[df["Status"].isin(["Absage","Zurückgezogen"])]
    ])

    for i, (_, row) in enumerate(df_sortiert.iterrows()):
        if y < 30*mm:
            # Footer und neue Seite
            c.setFillColor(GRAU)
            c.setFont(PDF_FONT, 7)
            c.drawString(20*mm, 15*mm, "Vertraulich — nur für den internen Gebrauch der Agentur")
            c.drawRightString(W-20*mm, 15*mm, f"Erstellt: {date.today().strftime('%d.%m.%Y')}")
            c.showPage()
            # Neuer Header
            c.setFillColor(BLAU)
            c.rect(0, H-18*mm, W, 18*mm, fill=1, stroke=0)
            c.setFillColor(WEISS)
            c.setFont(PDF_FONT_BOLD, 11)
            c.drawString(20*mm, H-10*mm, f"Bewerbungs-Statusbericht — {PROFIL['name']} (Fortsetzung)")
            y = H - 28*mm
            # Tabellenkopf wiederholen
            c.setFillColor(BLAU)
            c.rect(20*mm, y-4*mm, W-40*mm, 9*mm, fill=1, stroke=0)
            c.setFillColor(WEISS)
            c.setFont(PDF_FONT_BOLD, 8)
            c.drawString(22*mm,  y, "Datum"); c.drawString(44*mm, y, "Firma")
            c.drawString(90*mm,  y, "Stelle"); c.drawString(138*mm, y, "Ort")
            c.drawString(160*mm, y, "Status")
            y -= 11*mm

        if i % 2 == 0:
            c.setFillColor(HELL)
            c.rect(20*mm, y-3*mm, W-40*mm, 8*mm, fill=1, stroke=0)

        c.setFillColor(HexColor("#1a1a2e"))
        c.setFont(PDF_FONT, 8)
        c.drawString(22*mm,  y, str(row.get("Datum",""))[:10])
        c.drawString(44*mm,  y, str(row.get("Firma",""))[:23])
        c.drawString(90*mm,  y, str(row.get("Stelle",""))[:23])
        c.drawString(138*mm, y, str(row.get("Ort",""))[:11])

        status = str(row.get("Status",""))
        farbe  = STATUS_FARBEN.get(status, "#8B949E")
        c.setFillColor(HexColor(farbe))
        c.roundRect(159*mm, y-2*mm, 30*mm, 6*mm, 1*mm, fill=1, stroke=0)
        c.setFillColor(WEISS)
        c.setFont(PDF_FONT_BOLD, 7)
        c.drawCentredString(174*mm, y, status[:15])

        naechster = str(row.get("Nächster Schritt","")).strip()
        if naechster:
            c.setFillColor(GRAU)
            c.setFont(PDF_FONT, 7)
            c.drawString(44*mm, y-5*mm, f"→ {naechster[:70]}")
            y -= 5*mm
        y -= 9*mm

    # ── ANMERKUNG ─────────────────────────────────────────────────
    if anmerkung.strip():
        y -= 4*mm
        c.setFillColor(BLAU)
        c.setFont(PDF_FONT_BOLD, 10)
        c.drawString(20*mm, y, "Anmerkungen")
        y -= 7*mm
        c.setFillColor(HELL)
        c.rect(20*mm, y-14*mm, W-40*mm, 18*mm, fill=1, stroke=0)
        c.setFillColor(HexColor("#1a1a2e"))
        c.setFont(PDF_FONT, 9)
        # Zeilenumbruch bei langen Texten
        worte = anmerkung.split()
        zeile = ""
        zeilen = []
        for w in worte:
            if len(zeile) + len(w) < 95:
                zeile += (" " if zeile else "") + w
            else:
                zeilen.append(zeile); zeile = w
        if zeile: zeilen.append(zeile)
        for j, z in enumerate(zeilen[:2]):
            c.drawString(22*mm, y-4*mm - j*6*mm, z)

    # ── FOOTER ────────────────────────────────────────────────────
    c.setFillColor(GRAU)
    c.setFont(PDF_FONT, 7)
    c.drawString(20*mm, 15*mm, "Vertraulich — nur für den internen Gebrauch der Agentur")
    c.drawRightString(W-20*mm, 15*mm, f"Erstellt: {date.today().strftime('%d.%m.%Y')}")

    c.save()
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════
# SEITEN-KONFIGURATION
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Bewerbungs-Tracker",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    h2, h3 { color: #1f4e79; }
    textarea { font-size: 14px !important; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 💼 Navigation")
    seite = st.radio("", [
        "📊 Übersicht",
        "➕ Bewerbung erfassen",
        "✏️ Status ändern",
    ], label_visibility="collapsed")
    st.divider()
    st.markdown("### 🔍 Filter")
    filter_status = st.multiselect(
        "Status filtern",
        options=list(STATUS_FARBEN.keys()),
        default=list(STATUS_FARBEN.keys()),
    )

# ═══════════════════════════════════════════════════════════════
# DATEN LADEN
# ═══════════════════════════════════════════════════════════════
try:
    df = load_data()
except FileNotFoundError:
    st.error("⚠️ credentials.json nicht gefunden.")
    st.stop()
except Exception as e:
    st.error(f"⚠️ Google Sheets Verbindung fehlgeschlagen:\n{e}")
    st.stop()

hat_daten = not df.empty

# ═══════════════════════════════════════════════════════════════
# ── SEITE 1: ÜBERSICHT
# ═══════════════════════════════════════════════════════════════
if seite == "📊 Übersicht":
    st.title("💼 Bewerbungs-Tracker")

    if not hat_daten:
        st.info("Noch keine Bewerbungen. Starte mit '➕ Bewerbung erfassen'.")
    else:
        aktiv    = len(df[~df["Status"].isin(["Absage","Zurückgezogen"])])
        gesprche = len(df[df["Status"].isin(["Gespräch geplant","Gespräch geführt"])])
        angebote = len(df[df["Status"] == "Angebot erhalten"])
        absagen  = len(df[df["Status"] == "Absage"])

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Gesamt",    len(df))
        k2.metric("Aktiv",     aktiv)
        k3.metric("Gespräche", gesprche)
        k4.metric("Angebote",  angebote)

        # Wiedervorlage heute
        heute  = str(date.today())
        wv_df  = df[df["Wiedervorlage"].astype(str) == heute]
        if not wv_df.empty:
            st.warning("📅 **Wiedervorlage heute:** " +
                       "  |  ".join(wv_df["Firma"].tolist()))

        st.divider()

        # Tabelle mit Farb-Labels
        df_f = df[df["Status"].isin(filter_status)].copy() if filter_status else df.copy()
        df_f = df_f.drop(columns=["_row"], errors="ignore")

        def badge(s):
            f = STATUS_FARBEN.get(s, "#8B949E")
            return f'<span style="background:{f};color:#fff;padding:2px 10px;border-radius:10px;font-size:0.8em;white-space:nowrap">{s}</span>'

        anzeige = df_f[["Datum","Firma","Stelle","Ort","Quelle",
                         "Status","Gehaltsvorstellung","Nächster Schritt","Wiedervorlage"]].copy()
        anzeige["Status"] = anzeige["Status"].apply(badge)
        st.markdown(anzeige.to_html(escape=False, index=False), unsafe_allow_html=True)

        st.divider()
        st.divider()
        st.subheader("📤 Nachweis Eigenbemühungen")
        st.caption("Für die Agentur für Arbeit — einmal drücken, fertig")

        pdf_bytes = make_eigenbemuehungen_pdf(df_f)
        st.download_button(
            label="📄 Nachweis Eigenbemühungen als PDF",
            data=pdf_bytes,
            file_name=f"Nachweis_Eigenbemuehungen_{date.today()}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
        st.caption("PDF per Mail einreichen oder ausdrucken.")

# ═══════════════════════════════════════════════════════════════
# ── SEITE 2: BEWERBUNG ERFASSEN
# ═══════════════════════════════════════════════════════════════
elif seite == "➕ Bewerbung erfassen":
    st.title("➕ Bewerbung manuell erfassen")

    with st.form("neue_bewerbung", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            firma     = st.text_input("Firma *", placeholder="z.B. METRO AG")
            stelle    = st.text_input("Stelle *", placeholder="z.B. Data Analyst")
            ort       = st.text_input("Ort", placeholder="z.B. Düsseldorf")
            quelle    = st.selectbox("Quelle", [
                "LinkedIn","Indeed","Stepstone","Direkt","Agentur","Empfehlung","Sonstige"])
        with c2:
            datum        = st.date_input("Datum", value=date.today())
            status       = st.selectbox("Status", list(STATUS_FARBEN.keys()))
            gehalt_v     = st.text_input(
                                "Gehaltsvorstellung",
                                placeholder="z.B. 55.000 € / 60.000 €",
                                value=PROFIL["gehalt"],
                                help="Kann je nach Stelle angepasst werden")
            naechster    = st.text_input("Nächster Schritt",
                                          placeholder="z.B. Auf Rückmeldung warten")
            wiedervorlage = st.date_input("Wiedervorlage (optional)", value=None)
            notiz        = st.text_area("Notiz", height=80)

        ok = st.form_submit_button("💾 Speichern", use_container_width=True)
        if ok:
            if not firma or not stelle:
                st.error("Bitte Firma und Stelle eingeben.")
            else:
                try:
                    save_row(datum, firma, stelle, ort, quelle,
                             status, gehalt_v, naechster, wiedervorlage, notiz)
                    st.success(f"✅ {firma} — {stelle} gespeichert!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Fehler: {e}")

# ═══════════════════════════════════════════════════════════════
# ── SEITE 3: STATUS ÄNDERN
# ═══════════════════════════════════════════════════════════════
elif seite == "✏️ Status ändern":
    st.title("✏️ Status aktualisieren")

    if not hat_daten:
        st.info("Noch keine Bewerbungen vorhanden.")
    else:
        optionen = [
            f"{row['Firma']} — {row['Stelle']} ({row['Status']})"
            for _, row in df.iterrows()
        ]
        auswahl = st.selectbox("Bewerbung auswählen", optionen)
        idx     = optionen.index(auswahl)
        row     = df.iloc[idx]

        st.divider()
        c1, c2 = st.columns(2)

        with c1:
            st.markdown(f"**Firma:** {row['Firma']}")
            st.markdown(f"**Stelle:** {row['Stelle']}")
            st.markdown(f"**Datum:** {row['Datum']}")
            st.markdown(f"**Aktueller Status:** {row['Status']}")
            if row.get("Notiz"):
                st.markdown(f"**Notiz:** {row['Notiz']}")

        with c2:
            neuer_status = st.selectbox(
                "Neuer Status",
                list(STATUS_FARBEN.keys()),
                index=list(STATUS_FARBEN.keys()).index(row["Status"])
                      if row["Status"] in STATUS_FARBEN else 0
            )
            neuer_schritt = st.text_input(
                "Nächster Schritt",
                value=str(row.get("Nächster Schritt", "")))
            neue_notiz = st.text_area(
                "Notiz",
                value=str(row.get("Notiz", "")),
                height=100)

            if st.button("✅ Speichern", use_container_width=True):
                try:
                    ws      = get_worksheet()
                    row_idx = int(row["_row"])
                    ws.update_cell(row_idx, SPALTEN.index("Status") + 1,         neuer_status)
                    ws.update_cell(row_idx, SPALTEN.index("Nächster Schritt") + 1, neuer_schritt)
                    ws.update_cell(row_idx, SPALTEN.index("Notiz") + 1,           neue_notiz)
                    load_data.clear()
                    st.success(f"✅ {row['Firma']} → {neuer_status}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")
