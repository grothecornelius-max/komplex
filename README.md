# Foto-basierte Schaden-Zähler – mit +1-Buttons pro Mitarbeiter & Schadenart

Neu: In der Mitarbeiter-Ansicht gibt es pro **Schadenart** (z. B. *Regulierer*, *Sachverständiger*) einen **+1-Button**, plus optional **+1 Gesamt**.
Die Schadenarten-Liste ist in der Sidebar pflegbar und wird automatisch aus OCR-Ergebnissen ergänzt.

## Installation
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Start
```bash
streamlit run app.py
```

## Nutzung
- **Foto verarbeiten:** OCR liest `<Anzahl> <Name> <RD_ID>` und bucht Summen.
- **Mitarbeitende:** Personen hinzufügen/entfernen; pro Schadenart **+1** buchen.
- **Übersicht & Export:** Totals und Pivot nach Schadenart, CSV-Export.
