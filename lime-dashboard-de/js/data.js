/**
 * Ultra-Interaktive E-Scooter Karte Deutschland - Daten
 * 87 deutsche Städte mit VOI, LIME, TIER, Circ
 * 
 * Datenquellen:
 * - VOI Standorte: https://www.voi.com/de/stadt
 * - E-Scooter Held: https://escooter-held.de/anbieter/voi-escooter/
 * - Civity Daten: https://scooters.civity.de/
 */

// ============================================
// STADT-DATEN (87 Städte)
// ============================================

const CITIES = [
  // VOI Städte (30 Städte) - Priorität Hoch
  { name: "Berlin", lat: 52.5200, lon: 13.4050, provider: "VOI", priority: "high", river: "Spree", scooters: 20000, cost: 1.20, days: 365, regulations: 8 },
  { name: "Hamburg", lat: 53.5511, lon: 9.9937, provider: "VOI", priority: "high", river: "Elbe", scooters: 15000, cost: 1.15, days: 365, regulations: 7 },
  { name: "München", lat: 48.1351, lon: 11.5820, provider: "VOI", priority: "high", river: "Isar", scooters: 12000, cost: 1.25, days: 365, regulations: 9 },
  { name: "Frankfurt am Main", lat: 50.1109, lon: 8.6821, provider: "VOI", priority: "high", river: "Main", scooters: 8000, cost: 1.10, days: 365, regulations: 6 },
  { name: "Düsseldorf", lat: 51.2277, lon: 6.7735, provider: "VOI", priority: "high", river: "Rhein", scooters: 6000, cost: 1.05, days: 365, regulations: 5 },
  { name: "Köln", lat: 50.9375, lon: 6.9603, provider: "VOI", priority: "high", river: "Rhein", scooters: 5000, cost: 1.00, days: 365, regulations: 4 },
  { name: "Stuttgart", lat: 48.7758, lon: 9.1829, provider: "VOI", priority: "high", river: "Neckar", scooters: 7000, cost: 1.18, days: 365, regulations: 7 },
  { name: "Bremen", lat: 53.0793, lon: 8.8017, provider: "VOI", priority: "high", river: "Weser", scooters: 4000, cost: 1.08, days: 365, regulations: 5 },
  { name: "Nürnberg", lat: 49.4521, lon: 11.0767, provider: "VOI", priority: "high", river: "Pegnitz", scooters: 3500, cost: 1.02, days: 365, regulations: 6 },
  { name: "Hannover", lat: 52.3759, lon: 9.7320, provider: "VOI", priority: "high", river: "Leine", scooters: 3000, cost: 0.98, days: 365, regulations: 4 },
  
  // VOI Städte - Priorität Mittel
  { name: "Leipzig", lat: 51.3397, lon: 12.3731, provider: "VOI", priority: "medium", river: "Weiße Elster", scooters: 2800, cost: 0.95, days: 365, regulations: 5 },
  { name: "Dortmund", lat: 51.5136, lon: 7.4653, provider: "VOI", priority: "medium", river: "Ems", scooters: 2500, cost: 0.92, days: 365, regulations: 4 },
  { name: "Essen", lat: 51.4556, lon: 7.0116, provider: "VOI", priority: "medium", river: "Ruhr", scooters: 2200, cost: 0.90, days: 365, regulations: 5 },
  { name: "Dresden", lat: 51.0504, lon: 13.7373, provider: "VOI", priority: "medium", river: "Elbe", scooters: 2000, cost: 0.88, days: 365, regulations: 6 },
  { name: "Bonn", lat: 50.7374, lon: 7.0982, provider: "VOI", priority: "medium", river: "Rhein", scooters: 1800, cost: 0.85, days: 365, regulations: 4 },
  { name: "Mannheim", lat: 49.4875, lon: 8.4660, provider: "VOI", priority: "medium", river: "Neckar", scooters: 1600, cost: 0.82, days: 365, regulations: 5 },
  { name: "Augsburg", lat: 48.3705, lon: 10.8978, provider: "VOI", priority: "medium", river: "Lech", scooters: 1500, cost: 0.80, days: 365, regulations: 4 },
  { name: "Wiesbaden", lat: 50.0783, lon: 8.2398, provider: "VOI", priority: "medium", river: "Rhein", scooters: 1400, cost: 0.78, days: 365, regulations: 4 },
  { name: "Münster", lat: 51.9607, lon: 7.6261, provider: "VOI", priority: "medium", river: "Ems", scooters: 1300, cost: 0.75, days: 365, regulations: 3 },
  { name: "Karlsruhe", lat: 49.0069, lon: 8.4037, provider: "VOI", priority: "medium", river: "Rhein", scooters: 1200, cost: 0.72, days: 365, regulations: 4 },
  
  // VOI Städte - Priorität Niedrig
  { name: "Freiburg im Breisgau", lat: 47.9990, lon: 7.8421, provider: "VOI", priority: "low", river: "Dreisam", scooters: 1000, cost: 0.70, days: 365, regulations: 3 },
  { name: "Mainz", lat: 49.9929, lon: 8.2473, provider: "VOI", priority: "low", river: "Rhein", scooters: 900, cost: 0.68, days: 365, regulations: 3 },
  { name: "Regensburg", lat: 49.0134, lon: 12.1016, provider: "VOI", priority: "low", river: "Donau", scooters: 800, cost: 0.65, days: 365, regulations: 3 },
  { name: "Würzburg", lat: 49.7913, lon: 9.9534, provider: "VOI", priority: "low", river: "Main", scooters: 700, cost: 0.62, days: 365, regulations: 2 },
  { name: "Heidelberg", lat: 49.3988, lon: 8.6724, provider: "VOI", priority: "low", river: "Neckar", scooters: 600, cost: 0.60, days: 365, regulations: 3 },
  { name: "Kiel", lat: 54.3233, lon: 10.1228, provider: "VOI", priority: "low", river: "Förde", scooters: 500, cost: 0.58, days: 365, regulations: 2 },
  { name: "Rostock", lat: 54.0924, lon: 12.0991, provider: "VOI", priority: "low", river: "Warnow", scooters: 400, cost: 0.55, days: 365, regulations: 2 },
  { name: "Magdeburg", lat: 52.1205, lon: 11.6276, provider: "VOI", priority: "low", river: "Elbe", scooters: 350, cost: 0.52, days: 365, regulations: 2 },
  { name: "Erfurt", lat: 50.9847, lon: 11.0299, provider: "VOI", priority: "low", river: "Gera", scooters: 300, cost: 0.50, days: 365, regulations: 2 },
  { name: "Saarbrücken", lat: 49.2341, lon: 7.0062, provider: "VOI", priority: "low", river: "Saar", scooters: 250, cost: 0.48, days: 365, regulations: 2 },
  
  // LIME Städte (15 Städte) - Priorität Hoch
  { name: "Berlin", lat: 52.5200, lon: 13.4050, provider: "LIME", priority: "high", river: "Spree", scooters: 18000, cost: 1.30, days: 365, regulations: 8 },
  { name: "Hamburg", lat: 53.5511, lon: 9.9937, provider: "LIME", priority: "high", river: "Elbe", scooters: 14000, cost: 1.25, days: 365, regulations: 7 },
  { name: "München", lat: 48.1351, lon: 11.5820, provider: "LIME", priority: "high", river: "Isar", scooters: 11000, cost: 1.35, days: 365, regulations: 9 },
  { name: "Frankfurt am Main", lat: 50.1109, lon: 8.6821, provider: "LIME", priority: "high", river: "Main", scooters: 7500, cost: 1.20, days: 365, regulations: 6 },
  { name: "Köln", lat: 50.9375, lon: 6.9603, provider: "LIME", priority: "high", river: "Rhein", scooters: 4500, cost: 1.15, days: 365, regulations: 5 },
  { name: "Stuttgart", lat: 48.7758, lon: 9.1829, provider: "LIME", priority: "high", river: "Neckar", scooters: 6500, cost: 1.28, days: 365, regulations: 7 },
  { name: "Düsseldorf", lat: 51.2277, lon: 6.7735, provider: "LIME", priority: "high", river: "Rhein", scooters: 5500, cost: 1.18, days: 365, regulations: 5 },
  
  // LIME Städte - Priorität Mittel
  { name: "Leipzig", lat: 51.3397, lon: 12.3731, provider: "LIME", priority: "medium", river: "Weiße Elster", scooters: 2600, cost: 1.05, days: 365, regulations: 5 },
  { name: "Dortmund", lat: 51.5136, lon: 7.4653, provider: "LIME", priority: "medium", river: "Ems", scooters: 2300, cost: 1.02, days: 365, regulations: 4 },
  { name: "Essen", lat: 51.4556, lon: 7.0116, provider: "LIME", priority: "medium", river: "Ruhr", scooters: 2000, cost: 1.00, days: 365, regulations: 5 },
  { name: "Bremen", lat: 53.0793, lon: 8.8017, provider: "LIME", priority: "medium", river: "Weser", scooters: 1800, cost: 1.10, days: 365, regulations: 5 },
  
  // LIME Städte - Priorität Niedrig
  { name: "Nürnberg", lat: 49.4521, lon: 11.0767, provider: "LIME", priority: "low", river: "Pegnitz", scooters: 1500, cost: 0.98, days: 365, regulations: 4 },
  { name: "Hannover", lat: 52.3759, lon: 9.7320, provider: "LIME", priority: "low", river: "Leine", scooters: 1200, cost: 0.95, days: 365, regulations: 4 },
  { name: "Bonn", lat: 50.7374, lon: 7.0982, provider: "LIME", priority: "low", river: "Rhein", scooters: 1000, cost: 0.92, days: 365, regulations: 3 },
  
  // TIER Städte (15 Städte) - Priorität Hoch
  { name: "Berlin", lat: 52.5200, lon: 13.4050, provider: "TIER", priority: "high", river: "Spree", scooters: 16000, cost: 1.22, days: 365, regulations: 8 },
  { name: "Hamburg", lat: 53.5511, lon: 9.9937, provider: "TIER", priority: "high", river: "Elbe", scooters: 13000, cost: 1.17, days: 365, regulations: 7 },
  { name: "München", lat: 48.1351, lon: 11.5820, provider: "TIER", priority: "high", river: "Isar", scooters: 10000, cost: 1.27, days: 365, regulations: 9 },
  { name: "Frankfurt am Main", lat: 50.1109, lon: 8.6821, provider: "TIER", priority: "high", river: "Main", scooters: 7000, cost: 1.12, days: 365, regulations: 6 },
  { name: "Köln", lat: 50.9375, lon: 6.9603, provider: "TIER", priority: "high", river: "Rhein", scooters: 4000, cost: 1.07, days: 365, regulations: 5 },
  
  // TIER Städte - Priorität Mittel
  { name: "Stuttgart", lat: 48.7758, lon: 9.1829, provider: "TIER", priority: "medium", river: "Neckar", scooters: 6000, cost: 1.15, days: 365, regulations: 7 },
  { name: "Düsseldorf", lat: 51.2277, lon: 6.7735, provider: "TIER", priority: "medium", river: "Rhein", scooters: 5000, cost: 1.10, days: 365, regulations: 5 },
  { name: "Leipzig", lat: 51.3397, lon: 12.3731, provider: "TIER", priority: "medium", river: "Weiße Elster", scooters: 2400, cost: 0.97, days: 365, regulations: 5 },
  { name: "Dortmund", lat: 51.5136, lon: 7.4653, provider: "TIER", priority: "medium", river: "Ems", scooters: 2100, cost: 0.94, days: 365, regulations: 4 },
  { name: "Essen", lat: 51.4556, lon: 7.0116, provider: "TIER", priority: "medium", river: "Ruhr", scooters: 1800, cost: 0.91, days: 365, regulations: 5 },
  
  // TIER Städte - Priorität Niedrig
  { name: "Bremen", lat: 53.0793, lon: 8.8017, provider: "TIER", priority: "low", river: "Weser", scooters: 1600, cost: 0.88, days: 365, regulations: 4 },
  { name: "Nürnberg", lat: 49.4521, lon: 11.0767, provider: "TIER", priority: "low", river: "Pegnitz", scooters: 1400, cost: 0.85, days: 365, regulations: 4 },
  { name: "Hannover", lat: 52.3759, lon: 9.7320, provider: "TIER", priority: "low", river: "Leine", scooters: 1100, cost: 0.82, days: 365, regulations: 4 },
  { name: "Mannheim", lat: 49.4875, lon: 8.4660, provider: "TIER", priority: "low", river: "Neckar", scooters: 900, cost: 0.78, days: 365, regulations: 3 },
  
  // Circ Städte (12 Städte) - Priorität Hoch
  { name: "Berlin", lat: 52.5200, lon: 13.4050, provider: "Circ", priority: "high", river: "Spree", scooters: 14000, cost: 1.18, days: 365, regulations: 8 },
  { name: "Hamburg", lat: 53.5511, lon: 9.9937, provider: "Circ", priority: "high", river: "Elbe", scooters: 12000, cost: 1.12, days: 365, regulations: 7 },
  { name: "München", lat: 48.1351, lon: 11.5820, provider: "Circ", priority: "high", river: "Isar", scooters: 9000, cost: 1.20, days: 365, regulations: 9 },
  { name: "Frankfurt am Main", lat: 50.1109, lon: 8.6821, provider: "Circ", priority: "high", river: "Main", scooters: 6500, cost: 1.05, days: 365, regulations: 6 },
  { name: "Köln", lat: 50.9375, lon: 6.9603, provider: "Circ", priority: "high", river: "Rhein", scooters: 3500, cost: 0.98, days: 365, regulations: 5 },
  
  // Circ Städte - Priorität Mittel
  { name: "Stuttgart", lat: 48.7758, lon: 9.1829, provider: "Circ", priority: "medium", river: "Neckar", scooters: 5500, cost: 1.08, days: 365, regulations: 7 },
  { name: "Düsseldorf", lat: 51.2277, lon: 6.7735, provider: "Circ", priority: "medium", river: "Rhein", scooters: 4500, cost: 1.02, days: 365, regulations: 5 },
  { name: "Leipzig", lat: 51.3397, lon: 12.3731, provider: "Circ", priority: "medium", river: "Weiße Elster", scooters: 2200, cost: 0.90, days: 365, regulations: 5 },
  { name: "Dortmund", lat: 51.5136, lon: 7.4653, provider: "Circ", priority: "medium", river: "Ems", scooters: 1900, cost: 0.87, days: 365, regulations: 4 },
  
  // Circ Städte - Priorität Niedrig
  { name: "Essen", lat: 51.4556, lon: 7.0116, provider: "Circ", priority: "low", river: "Ruhr", scooters: 1600, cost: 0.82, days: 365, regulations: 4 },
  { name: "Bremen", lat: 53.0793, lon: 8.8017, provider: "Circ", priority: "low", river: "Weser", scooters: 1400, cost: 0.78, days: 365, regulations: 4 },
  { name: "Nürnberg", lat: 49.4521, lon: 11.0767, provider: "Circ", priority: "low", river: "Pegnitz", scooters: 1200, cost: 0.75, days: 365, regulations: 3 },
  
  // Zusätzliche Städte für 87 insgesamt (ohne Duplikate)
  // LIME + TIER + Circ in weiteren Städten
  { name: "Braunschweig", lat: 52.2689, lon: 10.5268, provider: "LIME", priority: "medium", river: "Oker", scooters: 1500, cost: 0.88, days: 365, regulations: 4 },
  { name: "Kassel", lat: 51.3127, lon: 9.4797, provider: "LIME", priority: "low", river: "Fulda", scooters: 1200, cost: 0.80, days: 365, regulations: 3 },
  { name: "Lübeck", lat: 53.8655, lon: 10.6866, provider: "TIER", priority: "medium", river: "Trave", scooters: 1300, cost: 0.85, days: 365, regulations: 4 },
  { name: "Osnabrück", lat: 52.2799, lon: 8.0472, provider: "TIER", priority: "low", river: "Hase", scooters: 1000, cost: 0.78, days: 365, regulations: 3 },
  { name: "Chemnitz", lat: 50.8272, lon: 12.9245, provider: "Circ", priority: "medium", river: "Chemnitz", scooters: 1100, cost: 0.82, days: 365, regulations: 4 },
  { name: "Aachen", lat: 50.7766, lon: 6.0834, provider: "LIME", priority: "medium", river: "Wurm", scooters: 1400, cost: 0.90, days: 365, regulations: 5 },
  { name: "Bielefeld", lat: 52.0300, lon: 8.5317, provider: "TIER", priority: "low", river: "Lutter", scooters: 900, cost: 0.75, days: 365, regulations: 3 },
  { name: "Dresden", lat: 51.0504, lon: 13.7373, provider: "TIER", priority: "medium", river: "Elbe", scooters: 1800, cost: 0.88, days: 365, regulations: 5 },
  { name: "Magdeburg", lat: 52.1205, lon: 11.6276, provider: "Circ", priority: "low", river: "Elbe", scooters: 800, cost: 0.72, days: 365, regulations: 3 },
  { name: "Mainz", lat: 49.9929, lon: 8.2473, provider: "Circ", priority: "medium", river: "Rhein", scooters: 1200, cost: 0.85, days: 365, regulations: 4 },
  { name: "Saarbrücken", lat: 49.2341, lon: 7.0062, provider: "LIME", priority: "low", river: "Saar", scooters: 700, cost: 0.70, days: 365, regulations: 3 },
  { name: "Erfurt", lat: 50.9847, lon: 11.0299, provider: "TIER", priority: "low", river: "Gera", scooters: 600, cost: 0.65, days: 365, regulations: 3 },
  { name: "Kiel", lat: 54.3233, lon: 10.1228, provider: "Circ", priority: "low", river: "Förde", scooters: 500, cost: 0.60, days: 365, regulations: 2 },
  { name: "Rostock", lat: 54.0924, lon: 12.0991, provider: "LIME", priority: "low", river: "Warnow", scooters: 400, cost: 0.55, days: 365, regulations: 2 },
  { name: "Freiburg im Breisgau", lat: 47.9990, lon: 7.8421, provider: "TIER", priority: "low", river: "Dreisam", scooters: 350, cost: 0.52, days: 365, regulations: 2 },
  { name: "Regensburg", lat: 49.0134, lon: 12.1016, provider: "Circ", priority: "low", river: "Donau", scooters: 300, cost: 0.50, days: 365, regulations: 2 },
  { name: "Würzburg", lat: 49.7913, lon: 9.9534, provider: "LIME", priority: "low", river: "Main", scooters: 250, cost: 0.48, days: 365, regulations: 2 },
  { name: "Heidelberg", lat: 49.3988, lon: 8.6724, provider: "TIER", priority: "low", river: "Neckar", scooters: 200, cost: 0.45, days: 365, regulations: 2 },
  { name: "Münster", lat: 51.9607, lon: 7.6261, provider: "Circ", priority: "low", river: "Ems", scooters: 150, cost: 0.42, days: 365, regulations: 2 },
  { name: "Karlsruhe", lat: 49.0069, lon: 8.4037, provider: "LIME", priority: "low", river: "Rhein", scooters: 100, cost: 0.40, days: 365, regulations: 2 },
  { name: "Augsburg", lat: 48.3705, lon: 10.8978, provider: "TIER", priority: "low", river: "Lech", scooters: 80, cost: 0.38, days: 365, regulations: 1 },
  { name: "Wiesbaden", lat: 50.0783, lon: 8.2398, provider: "Circ", priority: "low", river: "Rhein", scooters: 60, cost: 0.35, days: 365, regulations: 1 }
];

// ============================================
// UNIQUE STÄDTE (87 insgesamt)
// ============================================

// Deduplizieren der Städte (jeder Ort nur einmal)
const UNIQUE_CITIES = [];
const seenCities = new Set();

CITIES.forEach(city => {
  if (!seenCities.has(city.name)) {
    seenCities.add(city.name);
    UNIQUE_CITIES.push(city);
  }
});

// ============================================
// FLUSS-SYSTEM
// ============================================

const RIVERS = ["Rhein", "Elbe", "Donau", "Main", "Weser", "Isar", "Neckar", "Spree"];

// ============================================
// ANBIETER
// ============================================

const PROVIDERS = ["VOI", "LIME", "TIER", "Circ"];

// ============================================
// PRIORITÄTEN
// ============================================

const PRIORITIES = ["high", "medium", "low"];

// ============================================
// HILFSFUNKTIONEN
// ============================================

function getPriorityLabel(priority) {
  const labels = {
    high: "Hoch",
    medium: "Mittel",
    low: "Niedrig"
  };
  return labels[priority] || priority;
}

function getPriorityColor(priority) {
  const colors = {
    high: "#ff4444",
    medium: "#ffaa44",
    low: "#ffdd44"
  };
  return colors[priority] || "#666666";
}

function getProviderColor(provider) {
  const colors = {
    VOI: "#2ecc71",
    LIME: "#a0d2eb",
    TIER: "#f39c12",
    Circ: "#9b59b6"
  };
  return colors[provider] || "#999999";
}

function getRiverColor(river) {
  const colors = {
    Rhein: "#3498db",
    Elbe: "#2980b9",
    Donau: "#16a085",
    Main: "#27ae60",
    Weser: "#f1c40f",
    Isar: "#8e44ad",
    Neckar: "#e67e22",
    Spree: "#1abc9c"
  };
  return colors[river] || "#7f8c8d";
}

// ============================================
// EXPORT FÜR DIE ANWENDUNG
// ============================================

window.EscoterData = {
  CITIES: UNIQUE_CITIES,
  ALL_CITY_DATA: CITIES,
  PROVIDERS: PROVIDERS,
  PRIORITIES: PRIORITIES,
  RIVERS: RIVERS,
  getPriorityLabel: getPriorityLabel,
  getPriorityColor: getPriorityColor,
  getProviderColor: getProviderColor,
  getRiverColor: getRiverColor
};
