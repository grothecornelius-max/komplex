import streamlit as st
from io import BytesIO
from PIL import Image, ImageOps
import re
import json
from collections import defaultdict
from pathlib import Path

# ===============================================================
# Konfiguration
# ===============================================================
DATA_FILE = Path("data/state.json")
DATA_FILE.parent.mkdir(exist_ok=True)

st.set_page_config(page_title="Schaden-Zähler", layout="wide")
st.title("📊 Schaden-Zähler mit Zielvorgaben und fairer Rotation")
st.caption("Ziel je Schadenart = höchster Wert aller Mitarbeitenden, außer **CGrothe** (–25 %).")

# ===============================================================
# Initialisierung
# ===============================================================
def init_state():
    st.session_state.setdefault("counts_total", {})
    st.session_state.setdefault("counts_by_type", {})
    st.session_state.setdefault("known_types", ["Regulierer", "Sachverständiger"])
    st.session_state.setdefault("rotation_index", {})  # Rotationsspeicher

# ===============================================================
# Persistenz
# ===============================================================
def save_state():
    data = {
        "counts_total": st.session_state.counts_total,
        "counts_by_type": st.session_state.counts_by_type,
        "known_types": st.session_state.known_types,
        "rotation_index": st.session_state.rotation_index,
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_state():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        st.session_state.counts_total = data.get("counts_total", {})
        st.session_state.counts_by_type = data.get("counts_by_type", {})
        st.session_state.known_types = data.get("known_types", ["Regulierer", "Sachverständiger"])
        st.session_state.rotation_index = data.get("rotation_index", {})

# ===============================================================
# Hilfsfunktionen
# ===============================================================
def normalize_name(n: str) -> str:
    return (n or "").strip().lower()

def compute_type_max(counts_by_type: dict) -> dict:
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
    max_per_type = compute_type_max(counts_by_type)
    targets = {}
    all_names = set(counts_by_type.keys()) | set(st.session_state.counts_total.keys())
    for name in all_names:
        tmap = {}
        for rd_id, m in max_per_type.items():
            if normalize_name(name) == "cgrothe":
                tmap[rd_id] = int((m * 0.75) // 1)
            else:
                tmap[rd_id] = int(m)
        targets[name] = tmap
    return targets, max_per_type

# ===============================================================
# Faire Rotation mit Zielprüfung
# ===============================================================
def get_next_assignments():
    """Ermittelt pro Schadenart den nächsten Mitarbeitenden nach Zielerreichung und Rotation."""
    next_for_type = {}
    targets, _ = compute_targets(st.session_state.counts_by_type)

    for t in st.session_state.known_types:
        names = sorted(st.session_state.counts_total.keys(), key=lambda s: s.lower())
        if not names:
            continue

        # Nur Mitarbeitende mit unerreichtem Ziel
        active = []
        for n in names:
            ist = int(st.session_state.counts_by_type.get(n, {}).get(t, 0))
            ziel = int(targets.get(n, {}).get(t, 0))
            if ist < ziel:
                active.append(n)

        # Wenn niemand mehr aktiv -> neue Runde mit allen
        if not active:
            active = names
            st.session_state.rotation_index[t] = 0

        idx = st.session_state.rotation_index.get(t, 0)
        if idx >= len(active):
            idx = 0

        next_name = active[idx]
        next_for_type[t] = next_name

        # Index erhöhen (rotierend)
        st.session_state.rotation_index[t] = (idx + 1) % len(active)

    save_state()
    return next_for_type

# ===============================================================
# OCR-Funktion
# ===============================================================
def ocr_image(img_bytes, engine_name):
    try:
        image = Image.open(BytesIO(img_bytes))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail((2000, 2000))
    except Exception as e:
        st.error(f"Bild konnte nicht geöffnet werden: {e}")
        return ""

    if engine_name == "Tesseract":
        try:
            import pytesseract
            return pytesseract.image_to_string(image, lang="deu+eng")
        except Exception as e:
            st.error(f"Tesseract-Fehler: {e}")
            return ""
    elif engine_name == "EasyOCR":
        try:
            import easyocr, numpy as np
            reader = easyocr.Reader(["de", "en"], gpu=False)
            result = reader.readtext(np.array(image), detail=0, paragraph=True)
            return "\n".join(result)
        except Exception as e:
            st.error(f"EasyOCR-Fehler: {e}")
            return ""
    else:
        return ""

# ===============================================================
# Parser
# ===============================================================
def parse_block_access_style(text):
    t = text.replace("\\n", " ").replace("\\r", " ").replace("\u00a0", " ").replace("\u200b", " ")
    t = re.sub(r"\s+", " ", t).strip()
    tokens = t.split(" ")
    if not tokens:
        return []
    rd_idx = None
    for i, tok in enumerate(tokens):
        u = tok.upper().replace("_", "").replace("-", "")
        if (u == "RD" and i + 1 < len(tokens) and tokens[i + 1].upper().startswith("ID")) or u.startswith("RDID"):
            rd_idx = i
            break
    if rd_idx is None:
        for i in range(len(tokens) - 1, -1, -1):
            if tokens[i].upper().startswith("RD"):
                rd_idx = i
                break
    left = tokens if rd_idx is None else tokens[:rd_idx]
    right = [] if rd_idx is None else tokens[rd_idx:]
    left_clean = [tok for tok in left if tok.upper() not in {"ANZAHLVONSCHADEN", "ZUSTAENDIG"}]
    right_clean = [t for t in right if t.upper() not in {"RD", "ID", "RD_ID", "RDID"}]
    pairs = []
    i = 0
    while i < len(left_clean) - 1:
        c = left_clean[i]
        n = left_clean[i + 1]
        if re.fullmatch(r"[\d\.,]+", c):
            count = int(re.sub(r"\D", "", c))
            name = n
            pairs.append((count, name))
            i += 2
        else:
            i += 1
    types = [tok for tok in right_clean if re.search(r"[A-Za-zÄÖÜäöüß]", tok)]
    results = []
    for idx, (count, name) in enumerate(pairs):
        rdid = types[idx] if idx < len(types) else None
        if rdid:
            results.append((count, name, rdid))
    return results

# ===============================================================
# Zähler
# ===============================================================
def incr(name, n=1, rdid=None):
    st.session_state.counts_total[name] = max(0, int(st.session_state.counts_total.get(name, 0)) + int(n))
    if name not in st.session_state.counts_by_type:
        st.session_state.counts_by_type[name] = {}
    if rdid:
        current = int(st.session_state.counts_by_type[name].get(rdid, 0))
        new_value = max(0, current + int(n))
        st.session_state.counts_by_type[name][rdid] = new_value
    save_state()

# ===============================================================
# Startzustand laden
# ===============================================================
init_state()
load_state()

# ===============================================================
# Seitenleiste (Rotation)
# ===============================================================
st.sidebar.header("📌 Nächste Zuweisung (nach Ziel & Rotation)")
if st.session_state.counts_by_type:
    next_targets = get_next_assignments()
    for t, name in next_targets.items():
        st.sidebar.write(f"**{t} → {name}**")
else:
    st.sidebar.info("Noch keine Daten vorhanden.")

# ===============================================================
# Tabs
# ===============================================================
tab1, tab2, tab3 = st.tabs(["📸 Foto verarbeiten", "👥 Mitarbeitende", "📊 Übersicht"])

# ---------------------------------------------------------------
# Tab 1
# ---------------------------------------------------------------
with tab1:
    st.subheader("Fotos/Scans hochladen")
    imgs = st.file_uploader("Bilder (JPG/PNG)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
    engine = st.selectbox("OCR-Engine wählen", ["Tesseract", "EasyOCR"])
    if st.button("Fotos auslesen & buchen", type="primary") and imgs:
        aggregated = defaultdict(lambda: {"total": 0, "types": defaultdict(int)})
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
            st.success("Daten übernommen.")

# ---------------------------------------------------------------
# Tab 2 – Mitarbeitende (Statusansicht)
# ---------------------------------------------------------------
with tab2:
    st.subheader("Mitarbeitende – Übersicht & Buchung")
    if not st.session_state.counts_total:
        st.info("Noch keine Mitarbeitenden vorhanden.")
    else:
        targets, max_per_type = compute_targets(st.session_state.counts_by_type)
        for name in sorted(st.session_state.counts_total.keys(), key=lambda s: s.lower()):
            total = int(st.session_state.counts_total.get(name, 0))
            by_type = st.session_state.counts_by_type.get(name, {})
            emp_targets = targets.get(name, {})
            st.markdown(f"### {name} – Gesamt: **{total}**")

            for t in st.session_state.known_types:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button(f"+1 {t}", key=f"plus_{name}_{t}".replace(" ", "_")):
                        incr(name, 1, t)
                with c2:
                    if st.button(f"–1 {t}", key=f"minus_{name}_{t}".replace(" ", "_")):
                        incr(name, -1, t)

            # Tabellenanzeige
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
# Tab 3
# ---------------------------------------------------------------
with tab3:
    st.subheader("Gesamtübersicht")
    targets, max_per_type = compute_targets(st.session_state.counts_by_type)
    if not st.session_state.counts_total:
        st.info("Keine Daten vorhanden.")
    else:
        all_types = sorted(max_per_type.keys())
        rows = []
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
            rows.append(row)
        st.table(rows)

st.markdown("---")
st.caption("Zieldefinition: pro Schadenart = Maximum über alle Mitarbeitenden; Ausnahme **CGrothe**: 25 % weniger.")
