/* Lime Dashboard Deutschland — App-Logik */
(function () {
  "use strict";

  const STATUS_LABELS = {
    available: "Verfügbar",
    in_use: "In Nutzung",
    low_battery: "Schwacher Akku",
    maintenance: "Wartung",
  };

  const TYPE_EMOJI = { scooter: "🛴", bike: "🚲" };

  // Leaflet die lokalen Marker-Bilder bekannt machen (offline-fähig).
  if (window.L && L.Icon && L.Icon.Default) {
    L.Icon.Default.mergeOptions({
      iconUrl: "vendor/leaflet/images/marker-icon.png",
      iconRetinaUrl: "vendor/leaflet/images/marker-icon-2x.png",
      shadowUrl: "vendor/leaflet/images/marker-shadow.png",
    });
  }

  const allVehicles = window.LimeData.generateVehicles();

  const map = L.map("map", { zoomControl: true, attributionControl: true }).setView(
    [51.1657, 10.4515],
    6
  );

  // Dunkler Online-Tile-Layer (CARTO). Schlägt fehl, wenn offline.
  const tileLayer = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
        '· &copy; <a href="https://carto.com/attributions">CARTO</a> · Demo-Daten',
      subdomains: "abcd",
      maxZoom: 19,
      crossOrigin: true,
    }
  ).addTo(map);

  // --- Offline-Fallback: Canvas-basierte Deutschland-Hintergrundkarte ---
  // Wenn die Online-Tiles nicht laden, zeichnen wir eine eigene
  // vereinfachte Deutschland-Umriss-Kachelebene. So bleibt das Dashboard
  // auch komplett offline nutzbar.
  const DE_OUTLINE = [
    [54.91, 8.58], [54.96, 9.95], [54.63, 12.92], [54.42, 13.62],
    [54.25, 14.42], [54.02, 14.27], [53.51, 14.41], [52.68, 14.60],
    [52.38, 14.26], [51.88, 14.50], [51.42, 14.58], [50.86, 15.02],
    [50.27, 14.97], [50.13, 15.32], [48.94, 16.06], [48.98, 17.09],
    [48.78, 17.23], [48.55, 16.88], [48.42, 16.70], [47.72, 16.65],
    [47.27, 16.20], [47.04, 15.06], [46.65, 13.46], [46.45, 12.78],
    [46.67, 11.91], [46.93, 11.16], [47.05, 9.92], [47.58, 9.60],
    [47.54, 8.08], [47.28, 7.62], [48.04, 7.40], [49.02, 7.59],
    [49.52, 7.10], [49.92, 6.78], [50.13, 6.36], [50.17, 6.05],
    [49.47, 6.36], [49.49, 5.90], [50.18, 5.90], [51.10, 5.96],
    [51.51, 6.10], [51.96, 6.96], [52.34, 7.39], [53.25, 7.12],
    [53.62, 7.12], [53.70, 7.90], [53.58, 8.60], [54.07, 8.56],
    [54.32, 8.46], [54.63, 8.35], [54.91, 8.58],
  ];

  const OfflineLayer = L.GridLayer.extend({
    createTile: function (coords) {
      const tile = document.createElement("canvas");
      const size = this.getTileSize();
      tile.width = size.x;
      tile.height = size.y;
      const ctx = tile.getContext("2d");
      ctx.fillStyle = "#0e1526";
      ctx.fillRect(0, 0, size.x, size.y);

      // Deutschland-Umriss in Tile-Koordinaten zeichnen.
      ctx.beginPath();
      let started = false;
      for (const [lat, lon] of DE_OUTLINE) {
        const ll = map.project([lat, lon], coords.z).subtract(coords.multiplyBy(size.x).subtract(map.getPixelOrigin()));
        // Projektion: LatLon -> Tile-Pixel via Leaflet-eigener Projektion
        const p = this._latLonToTilePixel(lat, lon, coords, size);
        if (!started) { ctx.moveTo(p.x, p.y); started = true; }
        else ctx.lineTo(p.x, p.y);
      }
      ctx.closePath();
      ctx.fillStyle = "#13203a";
      ctx.strokeStyle = "#2ecc71";
      ctx.lineWidth = 2;
      ctx.fill();
      ctx.stroke();
      return tile;
    },
    _latLonToTilePixel: function (lat, lon, coords, size) {
      const mapSize = 256 * Math.pow(2, coords.z);
      const x = ((lon + 180) / 360) * mapSize;
      const latRad = (lat * Math.PI) / 180;
      const y =
        ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) *
        mapSize;
      return {
        x: x - coords.x * size.x,
        y: y - coords.y * size.y,
      };
    },
  });

  let offlineAdded = false;
  let onlineOk = false;
  tileLayer.once("tileload", function () {
    onlineOk = true;
  });

  // Nach 4s ohne erfolgreich geladene Kachel: Fallback einblenden.
  setTimeout(function () {
    if (!onlineOk && !offlineAdded) {
      console.warn("Online-Tiles nicht erreichbar — aktiviere Offline-Karte.");
      offlineAdded = true;
      new OfflineLayer({ minZoom: 5, maxZoom: 8 }).addTo(map);
      map.attributionControl.addAttribution("Offline-Karte (vereinfacht)");
    }
  }, 4000);

  let markersLayer = L.layerGroup().addTo(map);
  let activeVehicleId = null;

  const els = {
    status: document.getElementById("filter-status"),
    type: document.getElementById("filter-type"),
    city: document.getElementById("filter-city"),
    search: document.getElementById("search"),
    list: document.getElementById("vehicle-list"),
    stats: document.getElementById("stats"),
    ovCount: document.getElementById("ov-count"),
    ovCities: document.getElementById("ov-cities"),
    ovBattery: document.getElementById("ov-battery"),
  };

  (function fillCities() {
    const cities = Array.from(new Set(allVehicles.map((v) => v.city))).sort();
    const frag = document.createDocumentFragment();
    const allOpt = document.createElement("option");
    allOpt.value = "all";
    allOpt.textContent = "Alle Städte";
    frag.appendChild(allOpt);
    cities.forEach((c) => {
      const o = document.createElement("option");
      o.value = c;
      o.textContent = c;
      frag.appendChild(o);
    });
    els.city.appendChild(frag);
  })();

  function batteryClass(b) {
    if (b >= 60) return "l4";
    if (b >= 35) return "l3";
    if (b >= 15) return "l2";
    return "l1";
  }

  function applyFilters() {
    const s = els.status.value;
    const t = els.type.value;
    const c = els.city.value;
    const q = els.search.value.trim().toUpperCase();

    return allVehicles.filter((v) => {
      if (s !== "all" && v.status !== s) return false;
      if (t !== "all" && v.vehicleType !== t) return false;
      if (c !== "all" && v.city !== c) return false;
      if (q && !v.id.toUpperCase().includes(q)) return false;
      return true;
    });
  }

  function markerIcon(status) {
    return L.divIcon({
      className: "",
      html: `<div class="lime-marker ${status}"></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
  }

  function popupHtml(v) {
    const bc = batteryClass(v.battery);
    return `
      <h3>${TYPE_EMOJI[v.vehicleType]} ${v.id}</h3>
      <div><span class="badge ${v.status}">${STATUS_LABELS[v.status]}</span></div>
      <div style="margin-top:6px"><b>${v.city}</b></div>
      <div style="margin-top:4px">Typ: ${v.vehicleLabel}</div>
      <div>Akku: ${v.battery}% (≈ ${v.rangeKm} km Reichweite)
        <div class="battery" style="margin-top:4px">
          <span class="bar"><span class="${bc}" style="width:${v.battery}%"></span></span>
        </div>
      </div>
      <div>Max. ${v.maxSpeedKmh} km/h · zuletzt gesehen vor ${v.lastSeenMin} Min.</div>
    `;
  }

  function renderMarkers(vehicles) {
    markersLayer.clearLayers();
    const bounds = [];

    vehicles.forEach((v) => {
      const m = L.marker([v.lat, v.lon], { icon: markerIcon(v.status) });
      m.bindPopup(popupHtml(v));
      m.on("click", () => {
        activeVehicleId = v.id;
        highlightActiveCard();
      });
      m.addTo(markersLayer);
      v._marker = m;
      bounds.push([v.lat, v.lon]);
    });

    if (vehicles.length > 0) {
      if (vehicles.length <= 40) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
      } else if (!map.getZoom()) {
        map.setView([51.1657, 10.4515], 6);
      }
    }
  }

  function renderList(vehicles) {
    els.list.innerHTML = "";
    if (vehicles.length === 0) {
      els.list.innerHTML =
        '<div class="empty">Keine Fahrzeuge für die gewählten Filter.</div>';
      return;
    }
    const frag = document.createDocumentFragment();
    vehicles.forEach((v) => {
      const card = document.createElement("div");
      card.className = "vehicle-card";
      card.dataset.id = v.id;
      const bc = batteryClass(v.battery);
      card.innerHTML = `
        <div class="vc-top">
          <div>
            <div class="vc-id">${TYPE_EMOJI[v.vehicleType]} ${v.id}</div>
            <div class="vc-city">${v.city}</div>
          </div>
          <span class="badge ${v.status}">${STATUS_LABELS[v.status]}</span>
        </div>
        <div class="vc-row"><span>Akku</span>
          <span class="battery">
            <span class="bar"><span class="${bc}" style="width:${v.battery}%"></span></span>
            <b>${v.battery}%</b>
          </span>
        </div>
        <div class="vc-row"><span>Reichweite</span><b>${v.rangeKm} km</b></div>
        <div class="vc-row"><span>Zuletzt gesehen</span><b>vor ${v.lastSeenMin} Min.</b></div>
      `;
      card.addEventListener("click", () => {
        activeVehicleId = v.id;
        if (v._marker) {
          map.setView([v.lat, v.lon], 15, { animate: true });
          v._marker.openPopup();
        }
        highlightActiveCard();
      });
      frag.appendChild(card);
    });
    els.list.appendChild(frag);
    highlightActiveCard();
  }

  function highlightActiveCard() {
    els.list.querySelectorAll(".vehicle-card").forEach((c) => {
      c.classList.toggle("active", c.dataset.id === activeVehicleId);
    });
  }

  function renderStats(vehicles) {
    const total = vehicles.length;
    const cities = new Set(vehicles.map((v) => v.city)).size;
    const avgBattery =
      total === 0
        ? 0
        : Math.round(vehicles.reduce((a, v) => a + v.battery, 0) / total);
    const available = vehicles.filter((v) => v.status === "available").length;
    const inUse = vehicles.filter((v) => v.status === "in_use").length;
    const lowBat = vehicles.filter((v) => v.status === "low_battery").length;
    const maint = vehicles.filter((v) => v.status === "maintenance").length;

    els.stats.innerHTML = `
      <div class="stat"><div class="k">Fahrzeuge</div><div class="v lime">${total}</div></div>
      <div class="stat"><div class="k">Verfügbar</div><div class="v" style="color:var(--good)">${available}</div></div>
      <div class="stat"><div class="k">In Nutzung</div><div class="v" style="color:var(--info)">${inUse}</div></div>
      <div class="stat"><div class="k">Städte</div><div class="v">${cities}</div></div>
      <div class="stat"><div class="k">Schwacher Akku</div><div class="v" style="color:var(--warn)">${lowBat}</div></div>
      <div class="stat"><div class="k">Wartung</div><div class="v" style="color:var(--bad)">${maint}</div></div>
    `;

    els.ovCount.textContent = total;
    els.ovCities.textContent = cities;
    els.ovBattery.textContent = avgBattery + "%";
  }

  function update() {
    const filtered = applyFilters();
    renderMarkers(filtered);
    renderList(filtered);
    renderStats(filtered);
  }

  [els.status, els.type, els.city].forEach((el) =>
    el.addEventListener("change", update)
  );
  els.search.addEventListener("input", update);

  update();
})();
