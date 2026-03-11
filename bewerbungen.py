"""
╔══════════════════════════════════════════════════════════════╗
║  Bewerbungs-Tracker  |  Google Sheets + Streamlit           ║
║  inkl. Nachweis Eigenbemühungen als PDF                     ║
╚══════════════════════════════════════════════════════════════╝
pip install streamlit pandas gspread google-auth reportlab openpyxl
streamlit run bewerbungen.py
"""

import io
import os
from datetime import date, timedelta, datetime
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ═══════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════
SHEET_NAME     = "Bewerbungen"
WORKSHEET_NAME = "Bewerbungen"
CREDENTIALS_FILE = "credentials.json"
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
    "Datum", "Firma", "Stelle", "Ort", "Quelle", "Link",
    "Status", "Gehaltsvorstellung", "Nächster Schritt",
    "Wiedervorlage", "Notiz", "Gesprächsnotizen"
]

PROFIL = {
    "name":       "Jens Stein",
    "adresse":    "La-Roche-Str. 53, 44629 Herne",
    "telefon":    "0176-43239370",
    "email":      "J.stein2802@gmail.com",
    "gehalt":     "ab 55.000 € brutto p.a. (je nach Position)",
    "zielregion": "Ruhrgebiet | Homeoffice möglich",
    "zielrollen": "Stammdatenmanagement, Supply Chain Analyst, Data Analyst, Business Analyst",
}

WOCHENZIEL_DEFAULT = 5

# ═══════════════════════════════════════════════════════════════
# SCHRIFTART
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
            PDF_FONT = "DVS"; PDF_FONT_BOLD = "DVSB"
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
        ws.update([SPALTEN], "A1")
        return ws
    if ws.col_count < len(SPALTEN):
        ws.resize(rows=ws.row_count, cols=len(SPALTEN))
    ws.update([SPALTEN], "A1")
    return ws

@st.cache_data(ttl=30)
def load_data() -> pd.DataFrame:
    ws = get_worksheet()
    alle = ws.get_all_values()
    if len(alle) < 2:
        return pd.DataFrame(columns=SPALTEN)
    df = pd.DataFrame(alle[1:], columns=alle[0])
    df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].copy()
    for col in SPALTEN:
        if col not in df.columns:
            df[col] = ""
    df["_row"] = range(2, len(df) + 2)
    return df

def save_row(datum, firma, stelle, ort, quelle, link, status,
             gehalt_v, naechster, wiedervorlage, notiz, gespraechsnotizen=""):
    ws = get_worksheet()
    ws.append_row([
        str(datum), firma, stelle, ort, quelle, link,
        status, gehalt_v, naechster,
        str(wiedervorlage) if wiedervorlage else "",
        notiz, gespraechsnotizen,
    ])
    load_data.clear()

# ═══════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════
def parse_datum(s) -> date | None:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except Exception:
            pass
    return None

def badge_html(s):
    f = STATUS_FARBEN.get(s, "#8B949E")
    return (f'<span style="background:{f};color:#fff;padding:2px 8px;'
            f'border-radius:10px;font-size:0.8em;white-space:nowrap">{s}</span>')

def woche_montag() -> date:
    h = date.today()
    return h - timedelta(days=h.weekday())

# ═══════════════════════════════════════════════════════════════
# PDF — NACHWEIS EIGENBEMÜHUNGEN
# ═══════════════════════════════════════════════════════════════
def make_eigenbemuehungen_pdf(df: pd.DataFrame) -> bytes:
    from reportlab.pdfgen import canvas as rl_canvas
    buf  = io.BytesIO()
    W, H = A4
    c    = rl_canvas.Canvas(buf, pagesize=A4)
    BLAU  = HexColor("#1f4e79")
    HELL  = HexColor("#f0f4f8")
    GRAU  = HexColor("#666666")
    WEISS = HexColor("#ffffff")

    def draw_header():
        c.setFillColor(BLAU); c.setFont(PDF_FONT_BOLD, 14)
        c.drawString(20*mm, H-20*mm, "Nachweis Eigenbemühungen")
        c.setStrokeColor(BLAU); c.setLineWidth(1)
        c.line(20*mm, H-23*mm, W-20*mm, H-23*mm)
        c.setFillColor(HexColor("#1a1a2e")); c.setFont(PDF_FONT_BOLD, 10)
        c.drawString(20*mm, H-30*mm, PROFIL["name"])
        c.setFont(PDF_FONT, 9)
        c.drawString(20*mm, H-36*mm,
            f"{PROFIL['adresse']}  |  {PROFIL['telefon']}  |  {PROFIL['email']}")
        c.setFillColor(GRAU)
        c.drawRightString(W-20*mm, H-30*mm, f"Stand: {date.today().strftime('%d.%m.%Y')}")
        c.drawRightString(W-20*mm, H-36*mm, f"Anzahl Bewerbungen: {len(df)}")

    def draw_table_head(y):
        c.setFillColor(BLAU); c.rect(20*mm, y-5*mm, W-40*mm, 10*mm, fill=1, stroke=0)
        c.setFillColor(WEISS); c.setFont(PDF_FONT_BOLD, 9)
        c.drawString(22*mm,  y, "Nr.")
        c.drawString(32*mm,  y, "Datum")
        c.drawString(55*mm,  y, "Firma / Unternehmen")
        c.drawString(100*mm, y, "Stelle / Position")
        c.drawString(155*mm, y, "Quelle")
        c.drawString(173*mm, y, "Status")
        return y - 12*mm

    def draw_footer():
        c.setFillColor(GRAU); c.setFont(PDF_FONT, 7)
        c.drawString(20*mm, 18*mm, "Dieser Nachweis wurde maschinell erstellt.")

    draw_header()
    y = draw_table_head(H - 48*mm)

    for i, (_, row) in enumerate(df.iterrows()):
        if y < 28*mm:
            draw_footer(); c.showPage()
            draw_header(); y = draw_table_head(H - 48*mm)

        if i % 2 == 0:
            c.setFillColor(HELL)
            c.rect(20*mm, y-3*mm, W-40*mm, 8*mm, fill=1, stroke=0)

        c.setFillColor(HexColor("#1a1a2e")); c.setFont(PDF_FONT, 9)
        c.drawString(22*mm,  y, str(i+1))
        c.drawString(32*mm,  y, str(row.get("Datum",""))[:10])
        c.drawString(55*mm,  y, str(row.get("Firma",""))[:23])
        c.drawString(100*mm, y, str(row.get("Stelle",""))[:32])
        c.drawString(155*mm, y, str(row.get("Quelle",""))[:9])

        status = str(row.get("Status",""))
        c.setFillColor(HexColor(STATUS_FARBEN.get(status,"#8B949E")))
        c.roundRect(172*mm, y-2*mm, 18*mm, 6*mm, 1*mm, fill=1, stroke=0)
        c.setFillColor(WEISS); c.setFont(PDF_FONT_BOLD, 6)
        c.drawCentredString(181*mm, y, status[:14])
        y -= 9*mm

    draw_footer(); c.save()
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════════
st.set_page_config(page_title="Bewerbungs-Tracker", page_icon="💼",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    h2, h3 { color: #1f4e79; }
    textarea { font-size: 14px !important; }
    a { color: #1f4e79; }
</style>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 💼 Navigation")
    seite = st.radio("", ["📊 Übersicht","➕ Bewerbung erfassen","✏️ Status ändern"],
                     label_visibility="collapsed")
    st.divider()
    st.markdown("### 🔍 Filter")
    filter_status = st.multiselect("Status filtern",
        options=list(STATUS_FARBEN.keys()), default=list(STATUS_FARBEN.keys()))
    st.divider()
    st.markdown("### 🎯 Wochenziel")
    wochenziel = st.number_input("Bewerbungen pro Woche",
        min_value=1, max_value=20, value=WOCHENZIEL_DEFAULT)

# ═══════════════════════════════════════════════════════════════
# DATEN
# ═══════════════════════════════════════════════════════════════
try:
    df = load_data()
except FileNotFoundError:
    st.error("⚠️ credentials.json nicht gefunden."); st.stop()
except Exception as e:
    st.error(f"⚠️ Google Sheets Verbindung fehlgeschlagen:\n{e}"); st.stop()

hat_daten = not df.empty

# ═══════════════════════════════════════════════════════════════
# SEITE 1 — ÜBERSICHT
# ═══════════════════════════════════════════════════════════════
if seite == "📊 Übersicht":
    st.title("💼 Bewerbungs-Tracker")

    if not hat_daten:
        st.info("Noch keine Bewerbungen. Starte mit '➕ Bewerbung erfassen'.")
    else:
        # KPIs
        aktiv      = len(df[~df["Status"].isin(["Absage","Zurückgezogen"])])
        gespraeche = len(df[df["Status"].isin(["Gespräch geplant","Gespräch geführt"])])
        angebote   = len(df[df["Status"] == "Angebot erhalten"])
        absagen    = len(df[df["Status"] == "Absage"])
        rueckm     = len(df[df["Status"].isin([
            "Rückmeldung","Gespräch geplant","Gespräch geführt","Angebot erhalten"])])
        absage_quote = round(absagen / len(df) * 100) if len(df) else 0
        rueckm_quote = round(rueckm  / len(df) * 100) if len(df) else 0

        k1,k2,k3,k4,k5,k6 = st.columns(6)
        k1.metric("Gesamt",         len(df))
        k2.metric("Aktiv",          aktiv)
        k3.metric("Gespräche",      gespraeche)
        k4.metric("Angebote",       angebote)
        k5.metric("Rückmeldequote", f"{rueckm_quote} %")
        k6.metric("Absagequote",    f"{absage_quote} %")

        # Wochenziel
        montag = woche_montag()
        df["_dp"] = df["Datum"].apply(parse_datum)
        diese_woche = df[df["_dp"].apply(
            lambda d: d is not None and montag <= d <= date.today())]
        woche_count = len(diese_woche)

        st.divider()
        col_z, col_info = st.columns([3, 1])
        with col_z:
            st.markdown(f"**🎯 Wochenziel: {woche_count} von {wochenziel} Bewerbungen**"
                        f"  (ab {montag.strftime('%d.%m.')})")
            st.progress(min(woche_count / wochenziel, 1.0))
        with col_info:
            if woche_count >= wochenziel:
                st.success("✅ Ziel erreicht!")
            else:
                st.info(f"Noch {wochenziel - woche_count} diese Woche")

        # Wiedervorlage
        wv_df = df[df["Wiedervorlage"].astype(str) == str(date.today())]
        if not wv_df.empty:
            st.warning("📅 **Wiedervorlage heute:** " +
                       "  |  ".join(wv_df["Firma"].tolist()))

        st.divider()

        # Tabelle
        df_f = df[df["Status"].isin(filter_status)].copy() if filter_status else df.copy()
        df_f = df_f.drop(columns=["_row","_dp"], errors="ignore")

        anzeige = df_f[["Datum","Firma","Stelle","Ort","Quelle",
                         "Status","Gehaltsvorstellung","Nächster Schritt","Wiedervorlage"]].copy()

        # Klickbare Links einbauen
        def link_zelle(i):
            v = str(df_f.loc[i, "Link"]).strip() if "Link" in df_f.columns else ""
            return f'<a href="{v}" target="_blank">🔗</a>' if v.startswith("http") else ""
        anzeige.insert(2, "🔗", [link_zelle(i) for i in df_f.index])
        anzeige["Status"] = anzeige["Status"].apply(badge_html)
        st.markdown(anzeige.to_html(escape=False, index=False), unsafe_allow_html=True)

        # PDF Export
        st.divider()
        st.subheader("📤 Nachweis Eigenbemühungen")
        st.caption("Für die Agentur für Arbeit — einmal drücken, fertig")

        col_btn, col_zr = st.columns([2, 1])
        with col_zr:
            zeitraum = st.selectbox("Zeitraum",
                ["Alle","Letzte 4 Wochen","Letzte 2 Wochen","Diese Woche"], index=1)

        # Zeitraum filtern
        df_pdf = df_f.copy()
        if zeitraum != "Alle":
            if zeitraum == "Letzte 4 Wochen":
                grenze = date.today() - timedelta(weeks=4)
            elif zeitraum == "Letzte 2 Wochen":
                grenze = date.today() - timedelta(weeks=2)
            else:
                grenze = montag
            df_pdf = df_f[[parse_datum(df_f.loc[i,"Datum"]) is not None and
                           parse_datum(df_f.loc[i,"Datum"]) >= grenze
                           for i in df_f.index]].copy()

        with col_btn:
            st.download_button(
                label=f"📄 Nachweis als PDF ({len(df_pdf)} Einträge)",
                data=make_eigenbemuehungen_pdf(df_pdf),
                file_name=f"Nachweis_Eigenbemuehungen_{date.today()}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

# ═══════════════════════════════════════════════════════════════
# SEITE 2 — BEWERBUNG ERFASSEN
# ═══════════════════════════════════════════════════════════════
elif seite == "➕ Bewerbung erfassen":
    st.title("➕ Bewerbung erfassen")

    with st.form("neue_bewerbung", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            firma  = st.text_input("Firma *", placeholder="z.B. METRO AG")
            stelle = st.text_input("Stelle *", placeholder="z.B. Data Analyst")
            ort    = st.text_input("Ort", placeholder="z.B. Düsseldorf")
            quelle = st.selectbox("Quelle",
                ["LinkedIn","Indeed","Stepstone","Direkt","Agentur","Empfehlung","Sonstige"])
            link   = st.text_input("Link zur Stellenanzeige", placeholder="https://...")
        with c2:
            datum         = st.date_input("Datum", value=date.today())
            status        = st.selectbox("Status", list(STATUS_FARBEN.keys()))
            gehalt_v      = st.text_input("Gehaltsvorstellung",
                value=PROFIL["gehalt"], placeholder="z.B. 55.000 €")
            naechster     = st.text_input("Nächster Schritt",
                value="Auf Rückmeldung warten")
            wiedervorlage = st.date_input("Wiedervorlage (optional)", value=None)
            notiz         = st.text_area("Notiz", height=60)

        gespraechsnotizen = st.text_area(
            "Gesprächsnotizen (optional)",
            placeholder="Was wurde im Gespräch besprochen? Ansprechpartner, Konditionen, Eindruck ...",
            height=80)

        ok = st.form_submit_button("💾 Speichern", use_container_width=True)
        if ok:
            if not firma or not stelle:
                st.error("Bitte Firma und Stelle eingeben.")
            else:
                try:
                    save_row(datum, firma, stelle, ort, quelle, link,
                             status, gehalt_v, naechster, wiedervorlage,
                             notiz, gespraechsnotizen)
                    st.success(f"✅ {firma} — {stelle} gespeichert!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Fehler: {e}")

# ═══════════════════════════════════════════════════════════════
# SEITE 3 — STATUS ÄNDERN
# ═══════════════════════════════════════════════════════════════
elif seite == "✏️ Status ändern":
    st.title("✏️ Status aktualisieren")

    if not hat_daten:
        st.info("Noch keine Bewerbungen vorhanden.")
    else:
        optionen = [f"{r['Firma']} — {r['Stelle']} ({r['Status']})"
                    for _, r in df.iterrows()]
        auswahl  = st.selectbox("Bewerbung auswählen", optionen)
        idx      = optionen.index(auswahl)
        row      = df.iloc[idx]

        st.divider()
        c1, c2 = st.columns(2)

        with c1:
            st.markdown(f"**Firma:** {row['Firma']}")
            st.markdown(f"**Stelle:** {row['Stelle']}")
            st.markdown(f"**Datum:** {row['Datum']}")
            st.markdown(f"**Status:** {row['Status']}")
            link_v = str(row.get("Link","")).strip()
            if link_v.startswith("http"):
                st.markdown(f"[🔗 Zur Stellenanzeige]({link_v})")
            if row.get("Notiz"):
                st.markdown(f"**Notiz:** {row['Notiz']}")
            if row.get("Gesprächsnotizen"):
                st.markdown("**Gesprächsnotizen:**")
                st.info(row["Gesprächsnotizen"])

        with c2:
            neuer_status = st.selectbox("Neuer Status", list(STATUS_FARBEN.keys()),
                index=list(STATUS_FARBEN.keys()).index(row["Status"])
                      if row["Status"] in STATUS_FARBEN else 0)
            neues_gehalt = st.text_input("Gehaltsvorstellung",
                value=str(row.get("Gehaltsvorstellung","")),
                placeholder="z.B. 55.000 €")
            neuer_link = st.text_input("Link zur Stellenanzeige",
                value=str(row.get("Link","")), placeholder="https://...")
            neuer_schritt = st.text_input("Nächster Schritt",
                value=str(row.get("Nächster Schritt","")))
            neue_notiz = st.text_area("Notiz",
                value=str(row.get("Notiz","")), height=70)
            neue_gn = st.text_area("Gesprächsnotizen",
                value=str(row.get("Gesprächsnotizen","")), height=100,
                placeholder="Was wurde im Gespräch besprochen?")

            if st.button("✅ Speichern", use_container_width=True):
                try:
                    ws = get_worksheet()
                    ri = int(row["_row"])
                    ws.update_cell(ri, SPALTEN.index("Status")+1,            neuer_status)
                    ws.update_cell(ri, SPALTEN.index("Gehaltsvorstellung")+1, neues_gehalt)
                    ws.update_cell(ri, SPALTEN.index("Link")+1,              neuer_link)
                    ws.update_cell(ri, SPALTEN.index("Nächster Schritt")+1,  neuer_schritt)
                    ws.update_cell(ri, SPALTEN.index("Notiz")+1,             neue_notiz)
                    ws.update_cell(ri, SPALTEN.index("Gesprächsnotizen")+1,  neue_gn)
                    load_data.clear()
                    st.success(f"✅ {row['Firma']} → {neuer_status}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")
