/**
 * Lime Dashboard Deutschland — Simulationsdaten
 *
 * Hinweis: Lime bietet keine öffentliche Live-API ohne Authentifizierung.
 * Diese Daten sind realistisch modellierte SIMULATIONEN (Standorte in DE,
 * Fahrzeugtypen, Batteriestände, Status). Sie dienen Demo-/Prototyping-Zwecken
 * und spiegeln keine echten Lime-Fahrzeuge wider.
 */

const GERMAN_CITIES = [
  { name: "Berlin", lat: 52.5200, lon: 13.4050 },
  { name: "Hamburg", lat: 53.5511, lon: 9.9937 },
  { name: "München", lat: 48.1351, lon: 11.5820 },
  { name: "Köln", lat: 50.9375, lon: 6.9603 },
  { name: "Frankfurt am Main", lat: 50.1109, lon: 8.6821 },
  { name: "Stuttgart", lat: 48.7758, lon: 9.1829 },
  { name: "Düsseldorf", lat: 51.2277, lon: 6.7735 },
  { name: "Leipzig", lat: 51.3397, lon: 12.3731 },
  { name: "Dortmund", lat: 51.5136, lon: 7.4653 },
  { name: "Essen", lat: 51.4556, lon: 7.0116 },
  { name: "Bremen", lat: 53.0793, lon: 8.8017 },
  { name: "Dresden", lat: 51.0504, lon: 13.7373 },
  { name: "Hannover", lat: 52.3759, lon: 9.7320 },
  { name: "Nürnberg", lat: 49.4521, lon: 11.0767 },
  { name: "Freiburg im Breisgau", lat: 47.9990, lon: 7.8421 },
  { name: "Münster", lat: 51.9607, lon: 7.6261 },
  { name: "Karlsruhe", lat: 49.0069, lon: 8.4037 },
  { name: "Mannheim", lat: 49.4875, lon: 8.4660 },
  { name: "Augsburg", lat: 48.3705, lon: 10.8978 },
  { name: "Wiesbaden", lat: 50.0783, lon: 8.2398 },
  { name: "Kiel", lat: 54.3233, lon: 10.1228 },
  { name: "Rostock", lat: 54.0924, lon: 12.0991 },
  { name: "Magdeburg", lat: 52.1205, lon: 11.6276 },
  { name: "Mainz", lat: 49.9929, lon: 8.2473 },
  { name: "Saarbrücken", lat: 49.2341, lon: 7.0062 },
  { name: "Erfurt", lat: 50.9847, lon: 11.0299 },
  { name: "Bonn", lat: 50.7374, lon: 7.0982 },
  { name: "Münster", lat: 51.9607, lon: 7.6261 },
  { name: "Chemnitz", lat: 50.8272, lon: 12.9245 },
  { name: "Braunschweig", lat: 52.2689, lon: 10.5268 },
  { name: "Kassel", lat: 51.3127, lon: 9.4797 },
  { name: "Lübeck", lat: 53.8655, lon: 10.6866 },
  { name: "Osnabrück", lat: 52.2799, lon: 8.0472 },
  { name: "Regensburg", lat: 49.0134, lon: 12.1016 },
  { name: "Würzburg", lat: 49.7913, lon: 9.9534 },
  { name: "Heidelberg", lat: 49.3988, lon: 8.6724 },
];

const VEHICLE_TYPES = [
  { type: "scooter", label: "E-Scooter", baseRange: 45, speed: 20 },
  { type: "bike", label: "E-Bike", baseRange: 70, speed: 25 },
];

const STATUSES = ["available", "in_use", "low_battery", "maintenance"];

const VEHICLE_COUNT_PER_CITY = 6;

/**
 * Deterministischer PRNG (Mulberry32), damit die Simulation zwischen
 * Page-Reloads stabil bleibt, solange der Seed nicht geändert wird.
 */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pickWeightedStatus(rnd) {
  const r = rnd();
  if (r < 0.62) return "available";
  if (r < 0.85) return "in_use";
  if (r < 0.95) return "low_battery";
  return "maintenance";
}

function generateVehicles(seed = 20240517) {
  const rnd = mulberry32(seed);
  const vehicles = [];
  let id = 100000;

  for (const city of GERMAN_CITIES) {
    for (let i = 0; i < VEHICLE_COUNT_PER_CITY; i++) {
      const vt = VEHICLE_TYPES[Math.floor(rnd() * VEHICLE_TYPES.length)];
      const status = pickWeightedStatus(rnd);
      // Streuung der Fahrzeuge rund um das Stadtzentrum (~±0.04°).
      const lat = city.lat + (rnd() - 0.5) * 0.08;
      const lon = city.lon + (rnd() - 0.12) * 0.12;
      let battery;
      if (status === "low_battery") battery = 5 + Math.floor(rnd() * 15);
      else if (status === "maintenance") battery = Math.floor(rnd() * 40);
      else battery = 20 + Math.floor(rnd() * 80);
      const range = Math.round((battery / 100) * vt.baseRange);

      vehicles.push({
        id: `LIME-${id++}`,
        city: city.name,
        lat: parseFloat(lat.toFixed(5)),
        lon: parseFloat(lon.toFixed(5)),
        vehicleType: vt.type,
        vehicleLabel: vt.label,
        status,
        battery,
        rangeKm: range,
        maxSpeedKmh: vt.speed,
        lastSeenMin: Math.floor(rnd() * 90),
      });
    }
  }
  return vehicles;
}

// Expose globally for the (non-module) dashboard script.
window.LimeData = { generateVehicles, GERMAN_CITIES, STATUSES };
