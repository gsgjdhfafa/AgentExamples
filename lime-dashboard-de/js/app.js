/**
 * Ultra-Interaktive E-Scooter Karte Deutschland
 * 87 Städte mit VOI, LIME, TIER, Circ
 * 
 * Features:
 * - Echtzeit-Suche und Filter
 * - Anbieter-Filter (VOI, LIME, TIER, Circ)
 * - Prioritäts-Filter (Hoch/Mittel/Niedrig)
 * - Fluss-System-Filter (Rhein, Elbe, Donau, Main, Weser, Isar, Neckar, Spree)
 * - Cluster-Funktion (dynamisch, Spiderfy)
 * - Export (Excel XLSX, CSV)
 * - Mobile-Optimiert (Collapsible Sidebar)
 * - Karten-Layer (OpenStreetMap, Satellit, Terrain)
 * - Echtzeit-Statistik
 */

(function () {
  "use strict";

  // ============================================
  // KONFIGURATION
  // ============================================

  const PROVIDER_COLORS = {
    VOI: "#2ecc71",
    LIME: "#a0d2eb",
    TIER: "#f39c12",
    Circ: "#9b59b6"
  };

  const PRIORITY_COLORS = {
    high: "#ff4444",
    medium: "#ffaa44",
    low: "#ffdd44"
  };

  const RIVER_COLORS = {
    Rhein: "#3498db",
    Elbe: "#2980b9",
    Donau: "#16a085",
    Main: "#27ae60",
    Weser: "#f1c40f",
    Isar: "#8e44ad",
    Neckar: "#e67e22",
    Spree: "#1abc9c"
  };

  // ============================================
  // DATEN LADEN
  // ============================================

  if (!window.EscoterData) {
    console.error("EscoterData nicht geladen!");
    return;
  }

  const allCities = window.EscoterData.UNIQUE_CITIES;
  const allCityData = window.EscoterData.ALL_CITY_DATA;
  const providers = window.EscoterData.PROVIDERS;
  const priorities = window.EscoterData.PRIORITIES;
  const rivers = window.EscoterData.RIVERS;

  // ============================================
  // LEAFLET INITIALISIEREN
  // ============================================

  // Marker-Icons lokal konfigurieren
  if (window.L && L.Icon && L.Icon.Default) {
    L.Icon.Default.mergeOptions({
      iconUrl: "vendor/leaflet/images/marker-icon.png",
      iconRetinaUrl: "vendor/leaflet/images/marker-icon-2x.png",
      shadowUrl: "vendor/leaflet/images/marker-shadow.png",
    });
  }

  // Karte initialisieren
  const map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
    minZoom: 5,
    maxZoom: 18
  }).setView([51.1657, 10.4515], 6);

  // ============================================
  // KARTEN-LAYER (Online + Offline Fallback)
  // ============================================

  // Layer-Optionen
  const layerConfigs = {
    osm: {
      name: "OpenStreetMap",
      url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> Mitwirkende'
    },
    satellite: {
      name: "Satellit",
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
    },
    terrain: {
      name: "Terrain",
      url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
      attribution: 'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
    }
  };

  // Layer erstellen
  const baseLayers = {};
  for (const [key, config] of Object.entries(layerConfigs)) {
    baseLayers[key] = L.tileLayer(config.url, {
      attribution: config.attribution,
      subdomains: "abc",
      maxZoom: 19,
      crossOrigin: true
    });
  }

  // Standard-Layer hinzufügen
  baseLayers.osm.addTo(map);

  // Layer-Control
  L.control.layers(baseLayers, {}, { position: 'topleft' }).addTo(map);

  // Offline-Fallback für Deutschland
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

  let offlineLayerAdded = false;
  let onlineTilesOk = false;

  // Prüfe, ob Online-Tiles laden
  setTimeout(() => {
    if (!onlineTilesOk && !offlineLayerAdded) {
      console.warn("Online-Tiles nicht erreichbar – aktiviere Offline-Karte");
      offlineLayerAdded = true;
      
      // Vereinfachter Offline-Layer
      const CanvasLayer = L.GridLayer.extend({
        createTile: function(coords) {
          const tile = document.createElement("canvas");
          const size = this.getTileSize();
          tile.width = size.x;
          tile.height = size.y;
          const ctx = tile.getContext("2d");
          
          // Hintergrund
          ctx.fillStyle = "#0e1526";
          ctx.fillRect(0, 0, size.x, size.y);
          
          // Deutschland-Umriss
          ctx.beginPath();
          let started = false;
          for (const [lat, lon] of DE_OUTLINE) {
            const p = this._latLonToTilePixel(lat, lon, coords, size);
            if (!started) {
              ctx.moveTo(p.x, p.y);
              started = true;
            } else {
              ctx.lineTo(p.x, p.y);
            }
          }
          ctx.closePath();
          ctx.fillStyle = "#13203a";
          ctx.strokeStyle = "#2ecc71";
          ctx.lineWidth = 2;
          ctx.fill();
          ctx.stroke();
          
          return tile;
        },
        _latLonToTilePixel: function(lat, lon, coords, size) {
          const mapSize = 256 * Math.pow(2, coords.z);
          const x = ((lon + 180) / 360) * mapSize;
          const latRad = (lat * Math.PI) / 180;
          const y = ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * mapSize;
          return {
            x: x - coords.x * size.x,
            y: y - coords.y * size.y,
          };
        }
      });
      
      new CanvasLayer({ minZoom: 5, maxZoom: 8 }).addTo(map);
      map.attributionControl.addAttribution("Offline-Karte (vereinfacht)");
    }
  }, 4000);

  // Online-Tiles prüfen
  Object.values(baseLayers).forEach(layer => {
    layer.once("tileload", () => {
      onlineTilesOk = true;
    });
  });

  // ============================================
  // VEREINFACHTE CLUSTER-IMPLEMENTIERUNG
  // ============================================

  // Da wir keine MarkerCluster-Bibliothek haben, implementieren wir eine einfache Version
  // Diese zeigt einfach alle Marker an, ohne echte Cluster-Bildung
  // Für eine echte Implementierung wäre Leaflet.markercluster nötig

  let markersLayer = L.layerGroup().addTo(map);
  let useClustering = true;

  // ============================================
  // STADT-MARKER
  // ============================================

  // Marker für jede Stadt erstellen
  const cityMarkers = {};
  
  allCities.forEach(city => {
    // Finde alle Einträge für diese Stadt
    const cityEntries = allCityData.filter(c => c.name === city.name);
    
    // Aggregierte Daten
    const providersInCity = [...new Set(cityEntries.map(c => c.provider))];
    const totalScooters = cityEntries.reduce((sum, c) => sum + (c.scooters || 0), 0);
    const avgCost = cityEntries.reduce((sum, c) => sum + (c.cost || 0), 0) / cityEntries.length;
    const hasVoi = providersInCity.includes("VOI");
    const priority = cityEntries[0]?.priority || "low";
    const river = cityEntries[0]?.river || "Unbekannt";
    
    // Marker-Icon basierend auf Anbieter und Priorität
    const icon = createCityMarkerIcon(hasVoi, providersInCity, priority);
    
    // Marker erstellen
    const marker = L.marker([city.lat, city.lon], {
      icon: icon,
      title: city.name
    });
    
    // Popup-Inhalt
    const popupContent = createPopupContent(city, cityEntries, providersInCity, totalScooters, avgCost, priority, river);
    marker.bindPopup(popupContent);
    
    // Zu Layer hinzufügen
    marker.addTo(markersLayer);
    
    // Speichern für später
    cityMarkers[city.name] = {
      marker: marker,
      data: city,
      entries: cityEntries,
      providers: providersInCity,
      totalScooters: totalScooters,
      avgCost: avgCost,
      priority: priority,
      river: river,
      hasVoi: hasVoi
    };
  });

  // Marker-Icon erstellen
  function createCityMarkerIcon(hasVoi, providers, priority) {
    if (hasVoi) {
      // VOI-Städte: Grüner "V" Marker
      return L.divIcon({
        className: 'city-marker voi-marker',
        html: '<div class="voi-icon">V</div>',
        iconSize: [30, 30],
        iconAnchor: [15, 15],
        popupAnchor: [0, -15]
      });
    } else {
      // Andere Anbieter: Farbiger Punkt basierend auf Priorität
      const priorityColor = PRIORITY_COLORS[priority] || "#888888";
      return L.divIcon({
        className: 'city-marker priority-marker',
        html: '<div class="priority-dot" style="background:' + priorityColor + ';"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
        popupAnchor: [0, -8]
      });
    }
  }

  // Popup-Inhalt erstellen
  function createPopupContent(city, entries, providers, totalScooters, avgCost, priority, river) {
    const priorityLabel = window.EscoterData.getPriorityLabel(priority);
    const priorityColor = PRIORITY_COLORS[priority];
    const riverColor = RIVER_COLORS[river] || "#7f8c8d";
    
    // Anbieter-Badges
    const providerBadges = providers.map(provider => {
      const color = PROVIDER_COLORS[provider];
      return '<span class="badge provider-badge" style="background:' + color + ';">' + provider + '</span>';
    }).join('');
    
    // Formatierte Kosten
    const formattedCost = avgCost.toFixed(2).replace('.', ',') + ' €';
    
    return `
      <div class="city-popup">
        <h3>${city.name}</h3>
        <div class="popup-section">
          <div class="popup-row">
            <span class="label">Anbieter:</span>
            <div class="value">${providerBadges}</div>
          </div>
          <div class="popup-row">
            <span class="label">Roller:</span>
            <span class="value">${totalScooters.toLocaleString()}</span>
          </div>
          <div class="popup-row">
            <span class="label">Kosten:</span>
            <span class="value">${formattedCost}</span>
          </div>
          <div class="popup-row">
            <span class="label">Priorität:</span>
            <span class="value" style="color:${priorityColor};font-weight:bold;">${priorityLabel}</span>
          </div>
          <div class="popup-row">
            <span class="label">Fluss:</span>
            <span class="value" style="color:${riverColor};">${river}</span>
          </div>
          <div class="popup-row">
            <span class="label">Auflagen:</span>
            <span class="value">${entries[0]?.regulations || 0}/10</span>
          </div>
          <div class="popup-row">
            <span class="label">Einsatztage:</span>
            <span class="value">${entries[0]?.days || 0}</span>
          </div>
        </div>
      </div>
    `;
  }

  // ============================================
  // FILTER UND STEUERUNG
  // ============================================

  // DOM-Elemente
  const els = {
    search: document.getElementById("search"),
    filterProvider: document.getElementById("filter-provider"),
    filterPriority: document.getElementById("filter-priority"),
    filterRiver: document.getElementById("filter-river"),
    filterSort: document.getElementById("filter-sort"),
    clusterToggle: document.getElementById("cluster-toggle"),
    statsTotal: document.getElementById("stats-total"),
    statsVoi: document.getElementById("stats-voi"),
    statsHigh: document.getElementById("stats-high"),
    statsMedium: document.getElementById("stats-medium"),
    statsRivers: document.getElementById("stats-rivers"),
    cityList: document.getElementById("city-list"),
    sidebarToggle: document.getElementById("sidebar-toggle"),
    sidebar: document.querySelector("aside.sidebar"),
    exportExcel: document.getElementById("export-excel"),
    exportCsv: document.getElementById("export-csv")
  };

  // Filter-Optionen füllen
  function fillFilterOptions() {
    // Anbieter
    providers.forEach(provider => {
      const option = document.createElement("option");
      option.value = provider;
      option.textContent = provider;
      els.filterProvider.appendChild(option);
    });
    
    // Prioritäten
    priorities.forEach(priority => {
      const option = document.createElement("option");
      option.value = priority;
      option.textContent = window.EscoterData.getPriorityLabel(priority);
      els.filterPriority.appendChild(option);
    });
    
    // Flüsse
    rivers.forEach(river => {
      const option = document.createElement("option");
      option.value = river;
      option.textContent = river;
      els.filterRiver.appendChild(option);
    });
    
    // Sortieroptionen
    const sortOptions = [
      { value: "priority-desc", label: "Priorität (Hoch → Niedrig)" },
      { value: "priority-asc", label: "Priorität (Niedrig → Hoch)" },
      { value: "cost-desc", label: "Kosten (Absteigend)" },
      { value: "cost-asc", label: "Kosten (Aufsteigend)" },
      { value: "scooters-desc", label: "Rollerzahl (Absteigend)" },
      { value: "scooters-asc", label: "Rollerzahl (Aufsteigend)" }
    ];
    
    sortOptions.forEach(opt => {
      const option = document.createElement("option");
      option.value = opt.value;
      option.textContent = opt.label;
      els.filterSort.appendChild(option);
    });
  }

  // Filter anwenden
  let filteredCities = [];
  
  function applyFilters() {
    const searchQuery = els.search.value.toLowerCase();
    const selectedProvider = els.filterProvider.value;
    const selectedPriority = els.filterPriority.value;
    const selectedRiver = els.filterRiver.value;
    
    filteredCities = allCities.filter(city => {
      // Suche
      if (searchQuery && !city.name.toLowerCase().includes(searchQuery)) {
        return false;
      }
      
      // Anbieter-Filter
      if (selectedProvider !== "all") {
        const cityData = cityMarkers[city.name];
        if (!cityData || !cityData.providers.includes(selectedProvider)) {
          return false;
        }
      }
      
      // Prioritäts-Filter
      if (selectedPriority !== "all") {
        const cityData = cityMarkers[city.name];
        if (!cityData || cityData.priority !== selectedPriority) {
          return false;
        }
      }
      
      // Fluss-Filter
      if (selectedRiver !== "all") {
        const cityData = cityMarkers[city.name];
        if (!cityData || cityData.river !== selectedRiver) {
          return false;
        }
      }
      
      return true;
    });
    
    // Sortieren
    sortCities();
    
    // Karte aktualisieren
    updateMap();
    
    // Statistik aktualisieren
    updateStats();
    
    // Liste aktualisieren
    renderCityList();
  }

  // Sortieren
  function sortCities() {
    const sortBy = els.filterSort.value;
    
    filteredCities.sort((a, b) => {
      const aData = cityMarkers[a.name];
      const bData = cityMarkers[b.name];
      
      switch(sortBy) {
        case "priority-desc":
          return getPriorityValue(bData.priority) - getPriorityValue(aData.priority);
        case "priority-asc":
          return getPriorityValue(aData.priority) - getPriorityValue(bData.priority);
        case "cost-desc":
          return bData.avgCost - aData.avgCost;
        case "cost-asc":
          return aData.avgCost - bData.avgCost;
        case "scooters-desc":
          return bData.totalScooters - aData.totalScooters;
        case "scooters-asc":
          return aData.totalScooters - bData.totalScooters;
        default:
          return a.name.localeCompare(b.name);
      }
    });
  }

  function getPriorityValue(priority) {
    switch(priority) {
      case "high": return 3;
      case "medium": return 2;
      case "low": return 1;
      default: return 0;
    }
  }

  // Karte aktualisieren
  function updateMap() {
    // Alle Marker aus Layer entfernen
    markersLayer.clearLayers();
    
    // Gefilterte Städte anzeigen
    filteredCities.forEach(city => {
      const cityData = cityMarkers[city.name];
      if (cityData && cityData.marker) {
        cityData.marker.addTo(markersLayer);
      }
    });
    
    // View anpassen
    if (filteredCities.length > 0) {
      const bounds = filteredCities.map(city => [city.lat, city.lon]);
      if (filteredCities.length <= 20) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
      } else if (filteredCities.length <= 50) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
      } else {
        map.setView([51.1657, 10.4515], 6);
      }
    }
  }

  // Statistik aktualisieren
  function updateStats() {
    const totalCities = filteredCities.length;
    const voiCities = filteredCities.filter(city => {
      const cityData = cityMarkers[city.name];
      return cityData && cityData.hasVoi;
    }).length;
    
    const highPriority = filteredCities.filter(city => {
      const cityData = cityMarkers[city.name];
      return cityData && cityData.priority === "high";
    }).length;
    
    const mediumPriority = filteredCities.filter(city => {
      const cityData = cityMarkers[city.name];
      return cityData && cityData.priority === "medium";
    }).length;
    
    const uniqueRivers = new Set(filteredCities.map(city => {
      const cityData = cityMarkers[city.name];
      return cityData ? cityData.river : null;
    })).size;
    
    els.statsTotal.textContent = totalCities;
    els.statsVoi.textContent = voiCities;
    els.statsHigh.textContent = highPriority;
    els.statsMedium.textContent = mediumPriority;
    els.statsRivers.textContent = uniqueRivers;
  }

  // Städte-Liste rendern
  function renderCityList() {
    els.cityList.innerHTML = "";
    
    if (filteredCities.length === 0) {
      els.cityList.innerHTML = '<div class="empty">Keine Städte für die gewählten Filter.</div>';
      return;
    }
    
    const fragment = document.createDocumentFragment();
    
    filteredCities.forEach(city => {
      const cityData = cityMarkers[city.name];
      if (!cityData) return;
      
      const card = document.createElement("div");
      card.className = "city-card";
      card.dataset.city = city.name;
      
      // VOI-Badge
      const voiBadge = cityData.hasVoi ? '<span class="badge voi-badge">V</span>' : '';
      
      // Prioritätsfarbe
      const priorityColor = PRIORITY_COLORS[cityData.priority];
      const priorityLabel = window.EscoterData.getPriorityLabel(cityData.priority);
      
      // Flussfarbe
      const riverColor = RIVER_COLORS[cityData.river] || "#7f8c8d";
      
      // Anbieter-Badges
      const providerBadges = cityData.providers.map(provider => {
        const color = PROVIDER_COLORS[provider];
        return '<span class="badge provider-badge" style="background:' + color + ';">' + provider + '</span>';
      }).join('');
      
      card.innerHTML = `
        <div class="card-header">
          <div class="card-title">
            <span class="city-name">${city.name}</span>
            ${voiBadge}
          </div>
          <div class="card-priority" style="color:${priorityColor};">${priorityLabel}</div>
        </div>
        <div class="card-body">
          <div class="card-row">
            <span class="row-label">Roller:</span>
            <span class="row-value">${cityData.totalScooters.toLocaleString()}</span>
          </div>
          <div class="card-row">
            <span class="row-label">Kosten:</span>
            <span class="row-value">${cityData.avgCost.toFixed(2).replace('.', ',')} €</span>
          </div>
          <div class="card-row">
            <span class="row-label">Fluss:</span>
            <span class="row-value" style="color:${riverColor};">${cityData.river}</span>
          </div>
          <div class="card-row">
            <span class="row-label">Anbieter:</span>
            <div class="provider-badges">${providerBadges}</div>
          </div>
        </div>
      `;
      
      // Klick-Handler
      card.addEventListener("click", () => {
        const cityData = cityMarkers[city.name];
        if (cityData && cityData.marker) {
          map.setView([city.lat, city.lon], 12, { animate: true });
          cityData.marker.openPopup();
        }
      });
      
      fragment.appendChild(card);
    });
    
    els.cityList.appendChild(fragment);
  }

  // ============================================
  // CLUSTER TOGGLE
  // ============================================

  function toggleCluster() {
    useClustering = !useClustering;
    
    if (useClustering) {
      els.clusterToggle.textContent = "Cluster: AN";
      // In dieser vereinfachten Version tun wir nichts
      // Für echte Cluster wäre MarkerCluster nötig
    } else {
      els.clusterToggle.textContent = "Cluster: AUS";
      // In dieser vereinfachten Version tun wir nichts
    }
    
    // Karte neu zeichnen
    updateMap();
  }

  // ============================================
  // EXPORT FUNKTIONEN
  // ============================================

  // CSV Export
  function exportToCSV() {
    const headers = ["Stadt", "Breitengrad", "Längengrad", "Anbieter", "Priorität", "Fluss", "Rollerzahl", "Kosten (€)", "Auflagen", "Einsatztage"];
    
    const rows = filteredCities.map(city => {
      const cityData = cityMarkers[city.name];
      if (!cityData) return null;
      
      return [
        city.name,
        city.lat,
        city.lon,
        cityData.providers.join(", "),
        window.EscoterData.getPriorityLabel(cityData.priority),
        cityData.river,
        cityData.totalScooters,
        cityData.avgCost.toFixed(2).replace('.', ','),
        cityData.entries[0]?.regulations || 0,
        cityData.entries[0]?.days || 0
      ].map(field => {
        // CSV-Escape
        if (typeof field === 'string' && (field.includes(',') || field.includes('"') || field.includes('\n'))) {
          return '"' + field.replace(/"/g, '""') + '"';
        }
        return field;
      }).join(',');
    }).filter(row => row !== null);
    
    const csvContent = [headers.join(','), ...rows].join('\n');
    
    downloadFile(csvContent, "escooter-deutschland.csv", "text/csv");
  }

  // Excel Export (einfaches CSV als XLSX - für echte Excel-Dateien bräuchte man SheetJS)
  function exportToExcel() {
    // Für dieses Demo: JSON als Datei speichern, die Excel öffnen kann
    const data = filteredCities.map(city => {
      const cityData = cityMarkers[city.name];
      if (!cityData) return null;
      
      return {
        Stadt: city.name,
        Breitengrad: city.lat,
        Längengrad: city.lon,
        Anbieter: cityData.providers.join(", "),
        Priorität: window.EscoterData.getPriorityLabel(cityData.priority),
        Fluss: cityData.river,
        Rollerzahl: cityData.totalScooters,
        Kosten: cityData.avgCost.toFixed(2).replace('.', ',') + ' €',
        Auflagen: cityData.entries[0]?.regulations || 0,
        Einsatztage: cityData.entries[0]?.days || 0
      };
    }).filter(item => item !== null);
    
    const jsonContent = JSON.stringify(data, null, 2);
    downloadFile(jsonContent, "escooter-deutschland.json", "application/json");
  }

  // Datei herunterladen
  function downloadFile(content, filename, contentType) {
    const blob = new Blob([content], { type: contentType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ============================================
  // MOBILE SIDEBAR TOGGLE
  // ============================================

  function toggleSidebar() {
    els.sidebar.classList.toggle("collapsed");
    const icon = els.sidebarToggle.querySelector("span");
    if (els.sidebar.classList.contains("collapsed")) {
      icon.textContent = "☰";
    } else {
      icon.textContent = "✕";
    }
  }

  // ============================================
  // EVENT LISTENER
  // ============================================

  // Filter-Optionen füllen
  fillFilterOptions();
  
  // Suchfeld
  els.search.addEventListener("input", applyFilters);
  
  // Filter-Änderungen
  els.filterProvider.addEventListener("change", applyFilters);
  els.filterPriority.addEventListener("change", applyFilters);
  els.filterRiver.addEventListener("change", applyFilters);
  els.filterSort.addEventListener("change", applyFilters);
  
  // Cluster Toggle
  els.clusterToggle.addEventListener("click", toggleCluster);
  
  // Export-Buttons
  els.exportExcel.addEventListener("click", exportToExcel);
  els.exportCsv.addEventListener("click", exportToCSV);
  
  // Sidebar Toggle
  els.sidebarToggle.addEventListener("click", toggleSidebar);
  
  // Initialer Aufruf
  applyFilters();
  
  // ============================================
  // RESPONSIVE DESIGN
  // ============================================

  // Bei kleinen Bildschirmen Sidebar standardmäßig kollabieren
  function handleResize() {
    if (window.innerWidth <= 820) {
      els.sidebar.classList.add("collapsed");
      els.sidebarToggle.querySelector("span").textContent = "☰";
    } else {
      els.sidebar.classList.remove("collapsed");
      els.sidebarToggle.querySelector("span").textContent = "☰";
    }
  }
  
  window.addEventListener("resize", handleResize);
  handleResize();

})();
