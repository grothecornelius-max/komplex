
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

st.set_page_config(page_title="Foto → Schaden-Zähler (Mitarbeiter & Typ)", layout="wide")
st.title("Foto-basierte Schaden-Zähler – Mitarbeiter & Schadenart (MVP)")
st.caption("Extrahiert Zeilen: **<Anzahl> <ZUSTAENDIG> <RD_ID>**. Summen pro Mitarbeiter & Schadenart. **+1-Buttons** pro Mitarbeiter & Typ.")

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

with st.sidebar:
    st.header("Einstellungen")
    engine = st.selectbox("OCR-Engine", options=(ENGINES if ENGINES else ["(keine OCR-Engine gefunden)"]))
    st.markdown("---")
    st.subheader("Schadenarten (für Buttons)")
    add_type = st.text_input("Neue Schadenart")
    if st.button("Hinzufügen ➕", key="add_type"):
        t = (add_type or "").strip()
        if t and t not in st.session_state.known_types:
            st.session_state.known_types.append(t)
            st.success(f"'{t}' hinzugefügt.")
    if st.button("Auf Standard zurücksetzen", key="reset_type"):
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
            return "\\n".join(result)
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

def parse_lines_access_style(text, custom_regex=None):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    results = []
    default_rx = r'^(?P<count>\d+)\s+(?P<name>[A-Za-zÄÖÜäöüß]+)\s*(?P<rdid>[A-Za-zÄÖÜäöüß]+)?$'
    rx = re.compile(custom_regex or default_rx, re.UNICODE)
    for ln in lines:
        m = rx.search(ln)
        if m:
            try:
                count = int(m.group("count"))
            except:
                continue
            name = (m.group("name") or "").strip()
            rdid = m.group("rdid").strip() if m.groupdict().get("rdid") else None
            if name:
                results.append((count, name, rdid))
    return results

def incr(name, n=1, rdid=None):
    st.session_state.counts_total[name] = int(st.session_state.counts_total.get(name, 0)) + int(n)
    if name not in st.session_state.counts_by_type:
        st.session_state.counts_by_type[name] = {}
    if rdid:
        st.session_state.counts_by_type[name][rdid] = int(st.session_state.counts_by_type[name].get(rdid, 0)) + int(n)
    st.session_state.history.append({"op":"incr","name":name,"count":int(n),"rdid":rdid})

def set_count(name, total, by_type=None):
    st.session_state.counts_total[name] = int(total)
    st.session_state.counts_by_type[name] = dict(by_type or {})
    st.session_state.history.append({"op":"set","name":name,"total":int(total),"by_type":st.session_state.counts_by_type[name]})

def remove_employee(name):
    st.session_state.counts_total.pop(name, None)
    st.session_state.counts_by_type.pop(name, None)
    st.session_state.history.append({"op":"remove","name":name})

tab1, tab2, tab3 = st.tabs(["📸 Foto verarbeiten", "👥 Mitarbeitende", "📊 Übersicht & Export"])

with tab1:
    st.subheader("Fotos/Scans hochladen")
    imgs = st.file_uploader("Bilder (JPG/PNG)", type=["jpg","jpeg","png"], accept_multiple_files=True)
    st.markdown("**Standard-Parser:** `^(?P<count>\\d+)\\s+(?P<name>[A-Za-zÄÖÜäöüß]+)\\s*(?P<rdid>[A-Za-zÄÖÜäöüß]+)?$`")
    use_custom = st.checkbox("Benutzerdefiniertes Regex verwenden")
    custom_rx = None
    if use_custom:
        custom_rx = st.text_input(
            "Regex mit Gruppen count, name, rdid (rdid optional)",
            value=r"^(?P<count>\d+)\s+(?P<name>[A-Za-zÄÖÜäöüß]+)\s*(?P<rdid>[\wÄÖÜäöüß]+)?$"
        )
    run = st.button("Fotos auslesen & buchen", type="primary", disabled=not imgs)

    if run and imgs:
        aggregated = defaultdict(lambda: {"total":0, "types":defaultdict(int)})
        texts = []
        for up in imgs:
            b = up.read()
            txt = ocr_image(b, engine)
            if not txt:
                continue
            texts.append(txt)
            rows = parse_lines_access_style(txt, custom_rx)
            for cnt, name, rdid in rows:
                aggregated[name]["total"] += cnt
                if rdid:
                    aggregated[name]["types"][rdid] += cnt
                    if rdid not in st.session_state.known_types:
                        st.session_state.known_types.append(rdid)

        if not aggregated:
            st.warning("Keine passenden Zeilen erkannt. Regex/Fotoqualität prüfen.")
        else:
            st.success("Erkannte Summen (werden jetzt gebucht):")
            for name, payload in aggregated.items():
                if payload["types"]:
                    for t, c in payload["types"].items():
                        incr(name, c, t)
                else:
                    incr(name, payload["total"], None)
            st.json({k: {"total": v["total"], "types": dict(v["types"])} for k,v in aggregated.items()})

        with st.expander("OCR-Rohtext anzeigen"):
            for i, txt in enumerate(texts, 1):
                st.markdown(f"**Bild {i}**")
                st.code(txt)

with tab2:
    st.subheader("Mitarbeitende verwalten & buchen")
    col1, col2 = st.columns([2,1])
    with col1:
        if not st.session_state.counts_total:
            st.info("Noch keine Mitarbeitenden vorhanden.")
        else:
            for name in sorted(st.session_state.counts_total.keys(), key=lambda s: s.lower()):
                total = int(st.session_state.counts_total.get(name, 0))
                by_type = st.session_state.counts_by_type.get(name, {})
                st.markdown(f"### {name}  –  Gesamt: **{total}**")
                # +1 Buttons je Schadenart
                if st.session_state.known_types:
                    cols = st.columns(len(st.session_state.known_types) + 1)
                    for i, t in enumerate(st.session_state.known_types):
                        if cols[i].button(f"+1 {t}", key=f"plus1_{name}_{t}"):
                            incr(name, 1, t)
                            st.success(f"+1 für {name} / {t}")
                    if cols[-1].button("+1 Gesamt", key=f"plus1_{name}___total"):
                        incr(name, 1, None)
                        st.success(f"+1 für {name} (ohne Schadenart)")
                # Anzeige je Schadenart
                if by_type:
                    with st.expander("Schadenarten & Zähler"):
                        tcols = st.columns(3)
                        for idx, (t, v) in enumerate(sorted(by_type.items())):
                            tcols[idx % 3].metric(t, int(v))
                st.markdown("---")

    with col2:
        st.markdown("**Hinzufügen**")
        new_name = st.text_input("Name", key="new_emp_name")
        if st.button("Hinzufügen", type="primary"):
            nn = (new_name or "").strip()
            if not nn:
                st.error("Name darf nicht leer sein.")
            elif nn in st.session_state.counts_total:
                st.error("Name existiert bereits.")
            else:
                st.session_state.counts_total[nn] = 0
                st.session_state.counts_by_type[nn] = {}
                st.success(f"{nn} hinzugefügt (Gesamt=0).")

        st.markdown("---")
        st.markdown("**Entfernen / Setzen**")
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
            st.info("Bitte zuerst einen Mitarbeitenden anlegen.")

with tab3:
    st.subheader("Übersicht")
    if not st.session_state.counts_total:
        st.info("Keine Daten.")
    else:
        rows_total = [{"Mitarbeiter:in": k, "Gesamt": v} for k,v in sorted(st.session_state.counts_total.items(), key=lambda x: (-int(x[1]), x[0].lower()))]
        st.markdown("**Gesamtsummen**")
        st.table(rows_total)

        st.markdown("**Nach Schadenart (RD_ID)**")
        all_types = sorted({t for m in st.session_state.counts_by_type.values() for t in m.keys()})
        if all_types:
            data = []
            for name in sorted(st.session_state.counts_total.keys(), key=lambda s: s.lower()):
                row = {"Mitarbeiter:in": name}
                for t in all_types:
                    row[t] = int(st.session_state.counts_by_type.get(name, {}).get(t, 0))
                row["Gesamt"] = int(st.session_state.counts_total.get(name, 0))
                data.append(row)
            st.table(data)
        else:
            st.info("Noch keine Schadenarten gebucht.")

        from io import StringIO
        from datetime import datetime
        import csv
        st.markdown("---")
        st.markdown("**Export**")
        buf1 = StringIO()
        w1 = csv.writer(buf1); w1.writerow(["name","total"])
        for k,v in st.session_state.counts_total.items(): w1.writerow([k, v])
        st.download_button("Export Totals (CSV)", buf1.getvalue().encode("utf-8"), file_name=f"totals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")

        buf2 = StringIO()
        w2 = csv.writer(buf2); w2.writerow(["name","rd_id","count"])
        for name, d in st.session_state.counts_by_type.items():
            for t, c in d.items(): w2.writerow([name, t, c])
        st.download_button("Export Nach Schadenart (CSV)", buf2.getvalue().encode("utf-8"), file_name=f"by_type_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")

st.markdown("---")
st.caption("Für OCR bitte 'pip install easyocr' oder 'pip install pytesseract' (plus Tesseract-Binary). Alle Daten verbleiben lokal.")
