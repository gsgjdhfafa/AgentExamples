# Lime Dashboard — Deutschland

Ein eigenständiges Web-Dashboard, das **simulierte** Lime E-Scooter & E-Bikes
auf einer Deutschland-Karte (OpenStreetMap / CARTO Dark) anzeigt.

> ⚠️ **Wichtig:** Lime stellt keine öffentliche Live-API ohne Authentifizierung
> zur Verfügung. Alle Fahrzeugdaten in diesem Dashboard sind **realistisch
> modellierte Simulationen** (Standorte in deutschen Städten, Fahrzeugtypen,
> Batteriestände, Status). Sie dienen Demo- und Prototyping-Zwecken und
> spiegeln keine echten Lime-Fahrzeuge wider.

## Funktionen

- 🗺️ Deutschland-Karte (Leaflet + CARTO Dark Tiles, OpenStreetMap-Daten)
- 🛴🚲 Simulierte E-Scooter & E-Bikes in 30+ deutschen Städten
- 🔋 Batteriestand, Reichweite, Status (verfügbar / in Nutzung / schwacher Akku / Wartung)
- 🔎 Filter nach Status, Fahrzeugtyp, Stadt + Suche nach Fahrzeug-ID
- 📊 Live-Statistiken (Gesamtanzahl, verfügbare, Städte, Ø-Akku)
- 📋 Klickbare Fahrzeugliste ↔ Karten-Marker (Synchronisation)

## Starten

Keine Build-Schritte, keine Abhängigkeiten — einfach im Browser öffnen:

```bash
cd lime-dashboard-de
python3 -m http.server 8080
# dann im Browser: http://localhost:8080
```

Alternativ `index.html` direkt per Doppelklick öffnen (ein lokaler Server
wird wegen der externen Tile-/JS-Ressourcen empfohlen).

## Struktur

```
lime-dashboard-de/
├── index.html        # App-Gerüst
├── css/style.css     # Dark-Theme Lime-Optik
└── js/
    ├── data.js       # Simulationsdaten & Städte-Definition
    └── app.js        # Karten- & Filterlogik
```

## Hinweise

- Die Simulation ist deterministisch (Seed in `js/data.js`), d. h. die Daten
  bleiben zwischen Page-Reloads stabil, bis der Seed geändert wird.
- Um andere/wiederholbare Daten zu erzeugen, den `seed`-Wert in
  `generateVehicles(seed)` ändern.
- Für echte Live-Daten wäre ein authentifizierter Zugang zur Lime-API nötig,
  der hier bewusst nicht verwendet wird.

## Lizenzen

- Karten-Tiles: © OpenStreetMap-Mitwirkende, © CARTO (ODbL / CC-BY 3.0)
- Leaflet: BSD-2-Clause
- Code: siehe Repository-Lizenz
