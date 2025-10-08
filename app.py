import streamlit as st
from io import BytesIO
from PIL import Image
import re
import json
from collections import defaultdict

ENGINES = []
try:
    import easyocr
    ENGINES.append("EasyOCR")
except Exception:
    pass
try:
    import pytesseract
    ENGINES.append("Tesseract")
except Exception:
    pass

st.set_page_config(page_title="Foto → Schaden-Zähler (Ziele je Schadenart)", layout="wide")
st.title("Schaden-Zähler – Ziele je Schadenart (Blockparser & +1-Buttons)")
st.caption("Ziel je Schadenart = höchster Wert über alle Mitarbeitenden (außer: **CGrothe** mit 25% weniger Ziel).")

# -------------------------------------------------------------------
# Initialisierung
# -------------------------------------------------------------------
def init_state():
    if "counts_total" not in st.session_state:
        st.session_state.counts_total = {}
    if "counts_by_type" not in st.session_state:
        st.session_state.counts_by_type = {}
    if "history" not in st.session_state:
        st.session_state.history = []
    if "known_types" not in st.session_state:
        st.session_state.known_types = ["Regulierer", "Sachverständiger"]

init_state()

# -------------------------------------------------------------------
# Hilfsfunktionen: Zielermittlung
# -------------------------------------------------------------------
def normalize_name(n: str) -> str:
    return (n or "").strip().lower()

def compute_type_max(counts_by_type: dict) -> dict:
    """Ermittelt pro Schadenart den höchsten Wert."""
    max_per_type = defaultdict(int)
    for _, d in counts_by_type.items():
        for t, c in d.items():
            try:
                c_int = int(c)
            except:
                continue
            if c_int > max_per_type[t]:
                max_per_type[t] = c_int
    return dict(max_per_type)

def compute_targets(counts_by_type: dict):
    """Erstellt pro Mitarbeiter die Zielwerte je Schadenart."""
    max_per_type = compute_type_max(counts_by_type)
    targets = {}
    all_names = set(counts_by_type.keys()) | set(st.session_state.counts_total.keys())
    for name in all_names:
        tmap = {}
        for rd_id, m in max_per_type.items():
            if normalize_name(name) == "cgrothe":
                tmap[rd_id] = int((m * 0.75) // 1)  # 25 % weniger, abrunden
            else:
                tmap[rd_id] = int(m)
        targets[name] = tmap
    return targets, max_per_type

# -------------------------------------------------------------------
# Sidebar
# -------------------------------------------------------------------
with st.sidebar:
    st.header("Einstellungen")
    engine = st.selectbox("OCR-Engine", options=(ENGINES if ENGINES else ["(keine OCR-Engine gefunden)"]))
    st.markdown("---")
    st.subheader("Schadenarten (für Buttons)")
    add_type = st.text_input("Neue Schadenart")
    colA, colB = st.columns(2)
    if colA.button("Hinzufügen ➕"):
        t = (add_type or "").strip()
        if t and t not in st.session_state.known_types:
            st.session_state.known_types.append(t)
            st.success(f"'{t}' hinzugefügt.")
    if colB.button("Auf Standard zurücksetzen"):
        st.session_state.known_types = ["Regulierer", "Sachverständiger"]
        st.success("Zurückgesetzt.")
    if st.session_state.known_types:
        st.caption("Aktuell: " + ", ".join(st.session_state.known_types))

    st.markdown("---")
    st.subheader("Persistenz")
    data = json.dumps({
        "counts_total": st.session_state.counts_total,
        "counts_by_type": st.session_state.counts_by_type,
        "history": st.session_state.history,
        "known_types": st.session_state.known_types,
    }, ensure_ascii=False, indent=2)
    st.download_button("State als JSON", data, file_name="state.json", mime="application/json")
    up = st.file_uploader("State importieren (JSON)", type=["json"])
    if up is not None:
        try:
            content = json.load(up)
            st.session_state.counts_total = dict(content.get("counts_total", {}))
            st.session_state.counts_by_type = {k: dict(v) for k,v in content.get("counts_by_type", {}).items()}
            st.session_state.history = list(content.get("history", []))
            kt = content.get("known_types")
            if isinstance(kt, list):
                st.session_state.known_types = kt
            st.success("State importiert.")
        except Exception as e:
            st.error(f"Import fehlgeschlagen: {e}")

# -------------------------------------------------------------------
# OCR
# -------------------------------------------------------------------
def ocr_image(img_bytes, engine_name):
    try:
        image = Image.open(BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        st.error(f"Bild konnte nicht geöffnet werden: {e}")
        return ""
    if engine_name == "EasyOCR":
        try:
            import easyocr, numpy as np
            reader = easyocr.Reader(['de','en'], gpu=False)
            result = reader.readtext(np.array(image), detail=0, paragraph=True)
            return "\n".join(result)
        except Exception as e:
            st.error(f"EasyOCR-Fehler: {e}")
            return ""
    elif engine_name == "Tesseract":
        try:
            import pytesseract
            return pytesseract.image_to_string(image, lang="deu+eng")
        except Exception as e:
            st.error(f"Tesseract-Fehler: {e}")
            return ""
    else:
        st.warning("Keine OCR-Engine verfügbar.")
        return ""

# -------------------------------------------------------------------
# Parsing
# -------------------------------------------------------------------
def parse_block_access_style(text):
    """Erkennt dein OCR-Format: 'AnzahlvonSCHADEN ... RD ID ...'."""
    t = text.replace("\\n", " ").replace("\\r", " ").replace("\u00a0", " ").replace("\u200b", " ")
    t = re.sub(r'\s+', ' ', t).strip()
    tokens = t.split(' ')
    if not tokens:
        return []
    rd_idx = None
    for i, tok in enumerate(tokens):
        u = tok.upper().replace("_","").replace("-","")
        if (u == "RD" and i+1 < len(tokens) and tokens[i+1].upper().startswith("ID")) or u.startswith("RDID"):
            rd_idx = i; break
    if rd_idx is None:
        for i in range(len(tokens)-1, -1, -1):
            if tokens[i].upper().startswith("RD"):
                rd_idx = i; break

    left = tokens if rd_idx is None else tokens[:rd_idx]
    right = [] if rd_idx is None else tokens[rd_idx:]
    left_heads = {"ANZAHLVONSCHADEN","ZUSTAENDIG","ZUSTÄNDIG"}
    left_clean = [tok for tok in left if tok.upper() not in left_heads]
    right_clean = [t for t in right if t.upper() not in {"RD","ID","RD_ID","RDID"}]

    pairs = []
    i = 0
    while i < len(left_clean)-1:
        c = left_clean[i]; n = left_clean[i+1]
        if re.fullmatch(r'[\d\.,]+', c):
            count = int(re.sub(r'\D','', c)); name = n
            pairs.append((count, name)); i += 2
        else:
            i += 1

    types = [tok for tok in right_clean if re.search(r'[A-Za-zÄÖÜäöüß]', tok)]
    results = []
    for idx, (count, name) in enumerate(pairs):
        rdid = types[idx] if idx < len(types) else None
        if rdid:
            results.append((count, name, rdid))
    return results

# -------------------------------------------------------------------
# Buchungsfunktionen
# -------------------------------------------------------------------
def incr(name, n=1, rdid=None):
    st.session_state.counts_total[name] = int(st.session_state.counts_total.get(name, 0)) + int(n)
    if name not in st.session_state.counts_by_type:
        st.session_state.counts_by_type[name] = {}
    if rdid:
        st.session_state.counts_by_type[name][rdid] = int(st.session_state.counts_by_type[name].get(rdid, 0)) + int(n)

# -------------------------------------------------------------------
# Tabs
# -------------------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📸 Foto verarbeiten", "👥 Mitarbeitende", "📊 Übersicht & Export"])

# -------------------------------------------------------------------
# Tab 1
# -------------------------------------------------------------------
with tab1:
    st.subheader("Fotos/Scans hochladen")
    imgs = st.file_uploader("Bilder (JPG/PNG)", type=["jpg","jpeg","png"], accept_multiple_files=True)
    run = st.button("Fotos auslesen & buchen", type="primary", disabled=not imgs)
    if run and imgs:
        aggregated = defaultdict(lambda: {"total":0, "types":defaultdict(int)})
        for up in imgs:
            b = up.read()
            txt = ocr_image(b, engine)
            if not txt:
                continue
            rows = parse_block_access_style(txt)
            for cnt, name, rdid in rows:
                aggregated[name]["total"] += cnt
                aggregated[name]["types"][rdid] += cnt
                if rdid not in st.session_state.known_types:
                    st.session_state.known_types.append(rdid)
        if not aggregated:
            st.error("Keine passenden Daten erkannt.")
        else:
            for name, payload in aggregated.items():
                for t, c in payload["types"].items():
                    incr(name, c, t)
            st.success("Daten erfolgreich übernommen.")
            st.json(aggregated)

# -------------------------------------------------------------------
# Tab 2: Mitarbeitende – vereinfachte, kompakte Anzeige
# -------------------------------------------------------------------
with tab2:
    st.subheader("Mitarbeitende – Übersicht & Buchung")

    # Ziele berechnen
    targets, max_per_type = compute_targets(st.session_state.counts_by_type)

    if not st.session_state.counts_total:
        st.info("Noch keine Mitarbeitenden vorhanden.")
    else:
        for name in sorted(st.session_state.counts_total.keys(), key=lambda s: s.lower()):
            total = int(st.session_state.counts_total.get(name, 0))
            by_type = st.session_state.counts_by_type.get(name, {})
            emp_targets = targets.get(name, {})

            st.markdown(f"### {name} – Gesamt: **{total}**")

            # +1-Buttons je Schadenart (ohne Rerun)
            if st.session_state.known_types:
                cols = st.columns(len(st.session_state.known_types))
                for i, t in enumerate(st.session_state.known_types):
                    if cols[i].button(f"+1 {t}", key=f"{name}_{t}"):
                        incr(name, 1, t)

            # Tabelle: Ist / Ziel / Δ
            if max_per_type:
                st.markdown("**Schadenarten – Ist / Ziel / Δ**")
                table_md = "| Schadenart | Ist | Ziel | Δ |\n|---|---|---|---|\n"
                for t in sorted(max_per_type.keys()):
                    ist = int(by_type.get(t, 0))
                    ziel = int(emp_targets.get(t, 0))
                    delta = ist - ziel
                    if delta > 0:
                        delta_str = f"**+{delta}** 🚨"
                    elif delta < 0:
                        delta_str = f"{delta} ⬇️"
                    else:
                        delta_str = "0 ✅"
                    special = " _(–25 % CGrothe)_" if normalize_name(name) == "cgrothe" and ziel > 0 else ""
                    table_md += f"| {t} | {ist} | {ziel}{special} | {delta_str} |\n"
                st.markdown(table_md)

            st.markdown("---")

    # ---------------------------------------------------------------
    # Hauptbereich: Übersicht + Buttons
    # ---------------------------------------------------------------
    with col1:
        st.markdown("...")
        if not st.session_state.counts_total:
            st.info("Noch keine Mitarbeitenden vorhanden.")
        else:
            for name in sorted(st.session_state.counts_total.keys(), key=lambda s: s.lower()):
                total = int(st.session_state.counts_total.get(name, 0))
                by_type = st.session_state.counts_by_type.get(name, {})
                emp_targets = targets.get(name, {})

                st.markdown(f"### {name} – Gesamt: **{total}**")

                # +1-Buttons für Schadenarten (ohne Rerun!)
                if st.session_state.known_types:
                    cols = st.columns(len(st.session_state.known_types))
                    for i, t in enumerate(st.session_state.known_types):
                        if cols[i].button(f"+1 {t}", key=f"{name}_{t}"):
                            incr(name, 1, t)
                            st.session_state["last_click"] = f"{name}-{t}"  # kein rerun nötig

                # Tabelle mit Ist/Ziel/Delta sofort sichtbar
                if max_per_type:
                    st.markdown("**Schadenarten – Ist / Ziel / Δ**")
                    table_md = "| Schadenart | Ist | Ziel | Δ |\n|---|---|---|---|\n"
                    for t in sorted(max_per_type.keys()):
                        ist = int(by_type.get(t, 0))
                        ziel = int(emp_targets.get(t, 0))
                        delta = ist - ziel
                        if delta > 0:
                            delta_str = f"**+{delta}** 🚨"
                        elif delta < 0:
                            delta_str = f"{delta} ⬇️"
                        else:
                            delta_str = "0 ✅"
                        special = " _(–25 % CGrothe)_" if normalize_name(name) == "cgrothe" and ziel > 0 else ""
                        table_md += f"| {t} | {ist} | {ziel}{special} | {delta_str} |\n"
                    st.markdown(table_md)

                st.markdown("---")

    # ---------------------------------------------------------------
    # Seitenbereich: Mitarbeiter hinzufügen/entfernen
    # ---------------------------------------------------------------
    with col2:
        st.markdown("**Neuen Mitarbeiter hinzufügen**")
        new_name = st.text_input("Name", key="new_emp_name")
        if st.button("Hinzufügen", type="primary"):
            nn = (new_name or "").strip()
            if not nn:
                st.error("Name darf nicht leer sein.")
            elif nn in st.session_state.counts_total:
                st.warning("Name existiert bereits.")
            else:
                st.session_state.counts_total[nn] = 0
                st.session_state.counts_by_type[nn] = {}
                st.success(f"{nn} hinzugefügt (Gesamt = 0).")

        st.markdown("---")
        st.markdown("**Mitarbeiter entfernen oder Zahl setzen**")
        if st.session_state.counts_total:
            sel = st.selectbox("Mitarbeiter auswählen", options=list(st.session_state.counts_total.keys()))
            new_total = st.number_input("Gesamt setzen", value=int(st.session_state.counts_total[sel]), min_value=0, step=1)
            if st.button("Gesamt übernehmen"):
                set_count(sel, new_total, st.session_state.counts_by_type.get(sel, {}))
                st.success(f"{sel}: Gesamt auf {new_total} gesetzt.")
            if st.button("Mitarbeiter entfernen", type="secondary"):
                remove_employee(sel)
                st.warning(f"{sel} entfernt.")
        else:
            st.info("Noch keine Mitarbeitenden angelegt.")


# -------------------------------------------------------------------
# Tab 3
# -------------------------------------------------------------------
with tab3:
    st.subheader("Übersicht & Export")
    targets, max_per_type = compute_targets(st.session_state.counts_by_type)
    if not st.session_state.counts_total:
        st.info("Keine Daten vorhanden.")
    else:
        all_types = sorted(max_per_type.keys())
        data = []
        for name in sorted(st.session_state.counts_total.keys(), key=lambda s: s.lower()):
            row = {"Mitarbeiter:in": name}
            for t in all_types:
                ist = int(st.session_state.counts_by_type.get(name, {}).get(t, 0))
                ziel = int(targets.get(name, {}).get(t, 0))
                delta = ist - ziel
                row[f"{t} (Ist)"] = ist
                row[f"{t} (Ziel)"] = ziel
                row[f"{t} (Δ)"] = delta
            row["Gesamt"] = int(st.session_state.counts_total.get(name, 0))
            data.append(row)
        st.table(data)

st.markdown("---")
st.caption("Zieldefinition: pro Schadenart = Maximum über alle Mitarbeitenden; Ausnahme **CGrothe**: 25% weniger.")
