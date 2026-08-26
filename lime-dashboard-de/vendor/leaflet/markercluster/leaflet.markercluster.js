/*
 * Leaflet.markercluster - Marker Clustering plugin for Leaflet
 * Version: 1.4.1
 * https://github.com/Leaflet/Leaflet.markercluster
 * 
 * Licensed under the MIT license.
 */

(function (factory, window) {
	// define an AMD module that relies on 'leaflet'
	if (typeof define === 'function' && define.amd) {
		define(['leaflet'], factory);
	// define a Common JS module that relies on 'leaflet'
	} else if (typeof exports === 'object') {
		module.exports = factory(require('leaflet'));
	}
	// attach your plugin to the global 'L' variable
	if (typeof window !== 'undefined' && window.L) {
		window.L.markerClusterGroup = factory(L);
	}
}(function (L) {
	L.MarkerClusterGroup = L.FeatureGroup.extend({
		initialize: function (options) {
			L.FeatureGroup.prototype.initialize.call(this);

			options = options || {};

			this._markers = [];
			this._nonClusteredPoints = {};
			this._featureGroup = L.featureGroup();
			this._featureGroup.addEventParent(this);

			this._iconCreateFunction = options.iconCreateFunction || this._defaultIconCreateFunction;
			this._custers = [];
			this._nonPointMarkers = [];

			this._spiderfier = new L.MarkerClusterGroup.Spiderfier(this, options);

			this._options = {
				maxClusterRadius: options.maxClusterRadius || 80,
				spiderfyOnMaxZoom: options.spiderfyOnMaxZoom !== false,
				showCoverageOnHover: options.showCoverageOnHover !== false,
				zoomToBoundsOnClick: options.zoomToBoundsOnClick !== false,
				singleMarkerMode: options.singleMarkerMode || false,
				spiderfyDistanceMultiplier: options.spiderfyDistanceMultiplier || 1,
				disableClusteringAtZoom: options.disableClusteringAtZoom || null
			};
		},

		addLayer: function (layer) {
			if (layer instanceof L.LayerGroup) {
				for (var i = layer.getLayers().length - 1; i >= 0; i--) {
					this.addLayer(layer.getLayers()[i]);
				}
				return this;
			}

			//If it is a marker, check if it has a latlng, if not we can't cluster it.
			if (layer instanceof L.Marker) {
				if (layer.getLatLng()) {
					this._markers.push(layer);
					this._addToClusters(layer);
				} else {
					this._nonPointMarkers.push(layer);
				}
			} else {
				this._nonPointMarkers.push(layer);
			}

			this._featureGroup.addLayer(layer);

			return this;
		},

		removeLayer: function (layer) {
			if (this._markers.indexOf(layer) >= 0) {
				this._markers.splice(this._markers.indexOf(layer), 1);
				this._removeFromClusters(layer);
			} else if (this._nonPointMarkers.indexOf(layer) >= 0) {
				this._nonPointMarkers.splice(this._nonPointMarkers.indexOf(layer), 1);
			}

			this._featureGroup.removeLayer(layer);

			return this;
		},

		clearLayers: function () {
			this._markers = [];
			this._nonPointMarkers = [];
			this._custers = [];
			this._nonClusteredPoints = {};
			this._featureGroup.clearLayers();
			return this;
		},

		_getMarkerCluster: function (marker, zoom) {
			var map = this._map;
			if (!map) {
				return null;
			}

			var zoom = zoom !== undefined ? zoom : map.getZoom();
			var projection = map.options.crs.project;
			var mapZoom = map.getZoom();
			var scale = map.getZoomScale(zoom, mapZoom);

			var markers = this._markers;
			var clusters = [];

			//todo: use a spatial index like a quad tree
			for (var j = 0; j < markers.length; j++) {
				var marker = markers[j];
				if (marker === marker) {
					var markerPoint = projection(marker.getLatLng());
					var f = Math.pow(scale, -1);

					markerPoint.x = Math.round(markerPoint.x * f);
					markerPoint.y = Math.round(markerPoint.y * f);

					marker.__point = markerPoint;
				}

				if (marker.__point && marker.__point.equals) {
					var cluster = this._getOrCreateClusterWithKey(marker.__point);
					cluster._addChild(marker);
					clusters.push(cluster);
				}
			}

			var cluster;
			if (clusters.length > 0) {
				cluster = clusters[0];
				for (var i = 1, len = clusters.length; i < len; i++) {
					if (clusters[i]._childCount > cluster._childCount) {
						cluster = clusters[i];
					}
				}
			}

			return cluster;
		},

		_getOrCreateClusterWithKey: function (key) {
			var cluster = this._nonClusteredPoints[key.x + "," + key.y];
			if (!cluster) {
				cluster = new L.MarkerCluster(this, key);
				this._nonClusteredPoints[key.x + "," + key.y] = cluster;
			}
			return cluster;
		},

		_addToClusters: function (marker) {
			if (!this._map) {
				return;
			}
			var zoom = this._map.getZoom();
			var cluster = this._getMarkerCluster(marker, zoom);
			if (cluster) {
				cluster._addChild(marker);
				this._addClusterToMap(cluster);
			}
		},

		_removeFromClusters: function (marker) {
			if (!this._map) {
				return;
			}
			var zoom = this._map.getZoom();
			var cluster = this._getMarkerCluster(marker, zoom);
			if (cluster) {
				cluster._removeChild(marker);
				this._removeClusterFromMap(cluster);
			}
		},

		_addClusterToMap: function (cluster) {
			if (this._map && !this._map.hasLayer(cluster)) {
				this._featureGroup.addLayer(cluster);
				this._custers.push(cluster);
			}
		},

		_removeClusterFromMap: function (cluster) {
			if (this._map && this._map.hasLayer(cluster)) {
				this._featureGroup.removeLayer(cluster);
				var c = this._custers.indexOf(cluster);
				if (c !== -1) {
					this._custers.splice(c, 1);
				}
			}
		},

		_onMapViewReset: function () {
			var animated = this._map._animateToZoom;
			this._animateToZoom = animated;

			if (this._map.getZoom() < this._options.disableClusteringAtZoom) {
				this._clusterize();
				this._removeNonClusteredLayers();
			} else {
				this._unclusterize();
				this._addNonClusteredLayers();
			}
		},

		_clusterize: function () {
			this._unspiderfy();

			var childMarkers = [];
			var clusters = [];

			for (var i = 0, len = this._markers.length; i < len; i++) {
				var marker = this._markers[i];
				var cluster = this._getMarkerCluster(marker);
				if (cluster) {
					cluster._addChild(marker);
					clusters.push(cluster);
				} else {
					childMarkers.push(marker);
				}
			}

			//Remove old clusters
			for (var j = 0, len2 = this._custers.length; j < len2; j++) {
				this._featureGroup.removeLayer(this._custers[j]);
			}

			//Add new clusters
			this._custers = [];
			for (var k = 0, len3 = clusters.length; k < len3; k++) {
				this._featureGroup.addLayer(clusters[k]);
				this._custers.push(clusters[k]);
			}

			//Remove markers that are part of clusters
			for (var l = 0, len4 = this._markers.length; l < len4; l++) {
				var marker = this._markers[l];
				if (marker.__parent && this._map.hasLayer(marker)) {
					this._featureGroup.removeLayer(marker);
				}
			}

			//Add markers that are not part of clusters
			for (var m = 0, len5 = childMarkers.length; m < len5; m++) {
				if (!this._map.hasLayer(childMarkers[m])) {
					this._featureGroup.addLayer(childMarkers[m]);
				}
			}
		},

		_unclusterize: function () {
			this._unspiderfy();

			//Remove all clusters
			for (var j = 0, len2 = this._custers.length; j < len2; j++) {
				this._featureGroup.removeLayer(this._custers[j]);
			}
			this._custers = [];

			//Add all markers
			for (var i = 0, len = this._markers.length; i < len; i++) {
				var marker = this._markers[i];
				if (!this._map.hasLayer(marker)) {
					this._featureGroup.addLayer(marker);
				}
			}
		},

		_removeNonClusteredLayers: function () {
			for (var i = 0, len = this._nonPointMarkers.length; i < len; i++) {
				this._featureGroup.removeLayer(this._nonPointMarkers[i]);
			}
		},

		_addNonClusteredLayers: function () {
			for (var i = 0, len = this._nonPointMarkers.length; i < len; i++) {
				this._featureGroup.addLayer(this._nonPointMarkers[i]);
			}
		},

		_onClusterClick: function (e) {
			var cluster = e.layer;
			var map = this._map;

			if (this._options.zoomToBoundsOnClick) {
				var bounds = cluster.getBounds();
				if (bounds.isValid()) {
					if (this._options.singleMarkerMode && cluster._childCount <= 1) {
						// Single marker mode: zoom to the marker itself
						var markers = cluster._markers;
						if (markers.length === 1) {
							map.setView(markers[0].getLatLng(), map.getZoom() + 1);
							return;
						}
					}

					// If we have a spiderfier and we're not at the max zoom then spiderfy
					if (this._options.spiderfyOnMaxZoom && map.getZoom() !== map.getMaxZoom()) {
						this._spiderfier.spiderfy(cluster, bounds);
					} else {
						map.fitBounds(bounds, { padding: [20, 20, 20, 20] });
					}
				}
			}
		},

		_onClusterMouseOver: function (e) {
			if (this._options.showCoverageOnHover) {
				var cluster = e.layer;
				var bounds = cluster.getBounds();

				// Create a rectangle that shows the bounds of the cluster
				if (!cluster._rectangle) {
					cluster._rectangle = L.rectangle(bounds, { color: '#ff7800', weight: 2, clickable: false });
				}
				cluster._rectangle.setBounds(bounds);

				if (!cluster._rectangle._map) {
					cluster._rectangle.addTo(this._featureGroup);
				}
			}
		},

		_onClusterMouseOut: function (e) {
			if (this._options.showCoverageOnHover) {
				var cluster = e.layer;

				if (cluster._rectangle && cluster._rectangle._map) {
					cluster._rectangle.remove();
				}
			}
		},

		_onMapZoomEnd: function () {
			if (this._map.getZoom() < this._options.disableClusteringAtZoom) {
				this._clusterize();
				this._removeNonClusteredLayers();
			} else {
				this._unclusterize();
				this._addNonClusteredLayers();
			}
		},

		_defaultIconCreateFunction: function (cluster) {
			return new L.DivIcon({
				html: '<div><span>' + cluster._childCount + '</span></div>',
				className: 'marker-cluster-default',
				iconSize: new L.Point(40, 40)
			});
		},

		getLayers: function () {
			return this._featureGroup.getLayers();
		},

		getLayer: function (id) {
			return this._featureGroup.getLayer(id);
		},

		hasLayer: function (layer) {
			return this._featureGroup.hasLayer(layer);
		},

		removeLayer: function (layer) {
			if (this._markers.indexOf(layer) >= 0) {
				this._markers.splice(this._markers.indexOf(layer), 1);
				this._removeFromClusters(layer);
			} else if (this._nonPointMarkers.indexOf(layer) >= 0) {
				this._nonPointMarkers.splice(this._nonPointMarkers.indexOf(layer), 1);
			}

			this._featureGroup.removeLayer(layer);

			return this;
		},

		// Override addEventParent from L.LayerGroup
		addEventParent: function (obj) {
			this._featureGroup.addEventParent(obj);
		},

		// Override removeEventParent from L.LayerGroup
		removeEventParent: function (obj) {
			this._featureGroup.removeEventParent(obj);
		},

		// Override addEventListener from L.LayerGroup
		addEventListener: function (type, fn, context) {
			this._featureGroup.addEventListener(type, fn, context);
		},

		// Override removeEventListener from L.LayerGroup
		removeEventListener: function (type, fn, context) {
			this._featureGroup.removeEventListener(type, fn, context);
		},

		// Override fireEvent from L.LayerGroup
		fireEvent: function (type, data, propagate) {
			this._featureGroup.fireEvent(type, data, propagate);
		},

		// Override eachLayer from L.LayerGroup
		eachLayer: function (method, context) {
			this._featureGroup.eachLayer(method, context);
		},

		_onAdd: function (map) {
			this._map = map;

			this._featureGroup.addTo(map);

			if (this._options.singleMarkerMode) {
				this._map.on('click', this._unspiderfy, this);
			}

			map.on('zoomend', this._onMapZoomEnd, this);

			// Need to reclusterize on zoom start as the zoom animation might be cancelled
			// and zoomend not fired
			map.on('zoomanim', this._onMapViewReset, this);
			map.on('viewreset', this._onMapViewReset, this);

			this._clusterize();
			this._addNonClusteredLayers();
		},

		_onRemove: function (map) {
			this._featureGroup.removeFrom(map);

			if (this._options.singleMarkerMode) {
				map.off('click', this._unspiderfy, this);
			}

			map.off('zoomend', this._onMapZoomEnd, this);
			map.off('zoomanim', this._onMapViewReset, this);
			map.off('viewreset', this._onMapViewReset, this);
		}
	});

	L.markerClusterGroup = function (options) {
		return new L.MarkerClusterGroup(options);
	};

	L.MarkerCluster = L.Marker.extend({
		initialize: function (group, latlng, options) {
			L.Marker.prototype.initialize.call(this, latlng, options);

			this._group = group;
			this._childCount = 0;
			this._childClusters = [];
			this._markers = [];
			this._icon = null;
			this._zoom = group._map ? group._map.getZoom() : 0;
		},

		_addChild: function (marker) {
			this._childCount++;
			marker.__parent = this;

			if (marker instanceof L.MarkerCluster) {
				this._childClusters.push(marker);
			} else {
				this._markers.push(marker);
			}

			if (this._icon === null) {
				this._icon = this._group._iconCreateFunction(this);
				this.setIcon(this._icon);
			} else {
				this._updateIcon();
			}

			// Propagate the group events to the cluster
			marker.on('click', this._propagateEvent, this);
			marker.on('mouseover', this._propagateEvent, this);
			marker.on('mouseout', this._propagateEvent, this);
		},

		_removeChild: function (marker) {
			this._childCount--;
			marker.__parent = null;

			var c = this._markers.indexOf(marker);
			if (c >= 0) {
				this._markers.splice(c, 1);
			} else {
				c = this._childClusters.indexOf(marker);
				if (c >= 0) {
					this._childClusters.splice(c, 1);
				}
			}

			this._updateIcon();

			// Remove the group events from the cluster
			marker.off('click', this._propagateEvent, this);
			marker.off('mouseover', this._propagateEvent, this);
			marker.off('mouseout', this._propagateEvent, this);
		},

		_updateIcon: function () {
			this._icon = this._group._iconCreateFunction(this);
			this.setIcon(this._icon);
		},

		_propagateEvent: function (e) {
			var type = e.type;

			// if the child is a marker, stop propagation
			// so the cluster doesn't get the event as well
			if (e.source instanceof L.Marker) {
				L.DomEvent.stop(e);
			}

			// if the child is a cluster, propagate the event
			if (type === 'mouseover') {
				this.fire('mouseover', { layer: this });
			} else if (type === 'mouseout') {
				this.fire('mouseout', { layer: this });
			} else if (type === 'click') {
				this.fire('click', { layer: this });
			}
		},

		getAllChildMarkers: function () {
			var markers = [];
			var childClusters = [];

			for (var i = 0; i < this._markers.length; i++) {
				markers.push(this._markers[i]);
			}

			for (var j = 0; j < this._childClusters.length; j++) {
				childClusters.push(this._childClusters[j]);
			}

			return markers.concat(this._getChildMarkers(childClusters));
		},

		_getChildMarkers: function (childClusters) {
			var markers = [];

			for (var i = 0; i < childClusters.length; i++) {
				var childCluster = childClusters[i];
				var childMarkers = childCluster.getAllChildMarkers();

				for (var j = 0; j < childMarkers.length; j++) {
					markers.push(childMarkers[j]);
				}
			}

			return markers;
		},

		getBounds: function () {
			var bounds = new L.LatLngBounds();
			var markers = this.getAllChildMarkers();

			for (var i = 0, len = markers.length; i < len; i++) {
				bounds.extend(markers[i].getLatLng());
			}

			return bounds;
		},

		getChildCount: function () {
			return this._childCount;
		}
	});

	L.MarkerClusterGroup.Spiderfier = L.Class.extend({
		initialize: function (group, options) {
			this._group = group;
			this._overlay = new L.LayerGroup();
			this._overlay.addTo(group._featureGroup);
			this._unspiderfy = true;
			this._spiderfied = null;
			this._legPositions = [];
			this._legPositionsLength = 0;
			this._spiderfiedZoom = null;
		},

		spiderfy: function (cluster, bounds) {
			if (this._spiderfied === cluster) {
				return;
			}

			this._unspiderfy();

			var map = this._group._map;
			var center = bounds.getCenter();
			var markers = cluster.getAllChildMarkers();
			var count = markers.length;
			var mapZoom = map.getZoom();

			if (count > 1) {
				var averageDistance = this._getAverageDistance(center, markers);
				var twoPi = Math.PI * 2;
				var angleStep = this._spiderfyDistanceMultiplier * (twoPi / count);

				// Create the leg positions
				var legs = [];
				for (var i = 0; i < count; i++) {
					var angle = i * angleStep;
					var pos = L.point(center).subtract(L.point(
						averageDistance * this._group._options.spiderfyDistanceMultiplier * Math.cos(angle),
						averageDistance * this._group._options.spiderfyDistanceMultiplier * Math.sin(angle)
					));

					legs.push(pos);
				}

				// Create the spider legs
				for (var j = 0; j < count; j++) {
					var marker = markers[j];
					var leg = legs[j];

					// Create the line from the center to the marker
					var line = L.polyline([center, map.layerPointToLatLng(leg)], {
						color: '#ff7800',
						weight: 1.5,
						clickable: false
					});
					line.addTo(this._overlay);

					// Move the marker to the end of the leg
					marker._originalLatLng = marker.getLatLng();
					marker.setLatLng(map.layerPointToLatLng(leg));

					// Store the line and marker for later cleanup
					this._legPositions.push({
						line: line,
						marker: marker
					});
				}

				this._spiderfied = cluster;
				this._spiderfiedZoom = mapZoom;
				this._legPositionsLength = this._legPositions.length;

				// Center the map on the cluster
				map.panTo(center);
			}
		},

		_unspiderfy: function () {
			if (this._unspiderfy) {
				// Remove the spider legs
				for (var i = 0; i < this._legPositionsLength; i++) {
					var leg = this._legPositions[i];

					// Remove the line
					this._overlay.removeLayer(leg.line);

					// Move the marker back to its original position
					leg.marker.setLatLng(leg.marker._originalLatLng);
					leg.marker._originalLatLng = null;
				}

				this._legPositions = [];
				this._legPositionsLength = 0;
				this._spiderfied = null;
				this._spiderfiedZoom = null;

				this._unspiderfy = true;
			}
		},

		_getAverageDistance: function (center, markers) {
			var distances = [];

			for (var i = 0, len = markers.length; i < len; i++) {
				var marker = markers[i];
				var distance = center.distanceTo(marker.getLatLng());

				distances.push(distance);
			}

			return distances.reduce(function (a, b) { return a + b; }) / distances.length;
		}
	});

	L.MarkerClusterGroup.include({
		_spiderfier: null
	});

	L.markerClusterGroup = function (options) {
		return new L.MarkerClusterGroup(options);
	};

	return L;
}, window));
