/**
 * Map module — Leaflet map with station markers and propagation lines.
 */

class PropViewMap {
    constructor() {
        this.map = null;
        this.myMarker = null;
        this.myPosition = null; // {lat, lng}
        this.rfMarkers = {};    // callsign -> marker
        this.isMarkers = {};    // callsign -> marker
        this.rfLines = {};      // callsign -> polyline
        this.rfLineData = {};   // callsign -> {last_heard, distance_km}
        this.showLines = true;
        this.showRF = true;
        this.showIS = true;
        this.lineTimeFilter = 24; // hours, 0 = all time
        this.rfLayer = null;
        this.isLayer = null;
        this.lineLayer = null;
        this.rangeCircles = null;
        this.pickMode = false;
        this.pickMarker = null;
        this.onLocationPicked = null; // callback(lat, lng)
        this.darkMode = true;
        this.typeFilters = new Set();  // empty = show all, otherwise set of visible category keys
        // Track station symbol metadata for type filtering
        this.stationMeta = {};  // callsign -> {source, symbol_table, symbol_code, category}
    }

    init(lat, lng) {
        // Default to center of US if no position
        lat = lat || 39.8;
        lng = lng || -98.5;
        const zoom = (lat === 39.8 && lng === -98.5) ? 5 : 10;

        this.map = L.map('map', {
            center: [lat, lng],
            zoom: zoom,
            zoomControl: true,
            attributionControl: true,
        });

        // Dark tile layer
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(this.map);

        // Default to dark mode
        this.map.getContainer().classList.add('dark-tiles');

        // Create layer groups
        this.lineLayer = L.layerGroup().addTo(this.map);
        this.rfLayer = L.layerGroup().addTo(this.map);
        this.isLayer = L.layerGroup().addTo(this.map);

        // Add legend
        this._addLegend();

        // Bind map controls
        this._bindControls();

        return this;
    }

    setMyPosition(lat, lng, callsign) {
        this.myPosition = { lat, lng };

        if (this.myMarker) {
            this.myMarker.setLatLng([lat, lng]);
        } else {
            const icon = L.divIcon({
                className: 'my-station-marker',
                html: `<div style="
                    background: #39d5ff;
                    width: 18px; height: 18px;
                    border-radius: 50%;
                    border: 3px solid #fff;
                    box-shadow: 0 0 12px rgba(57,213,255,0.6), 0 0 24px rgba(57,213,255,0.3);
                "></div>`,
                iconSize: [18, 18],
                iconAnchor: [9, 9],
            });

            this.myMarker = L.marker([lat, lng], { icon, zIndexOffset: 1000 })
                .addTo(this.map)
                .bindPopup(`
                    <div class="popup-call" style="color: #39d5ff;">${callsign || 'My Station'}</div>
                    <div class="popup-detail">
                        ${lat.toFixed(4)}, ${lng.toFixed(4)}<br>
                        Digipeater / IGate
                    </div>
                `);
        }

        // Add range circles
        if (this.rangeCircles) {
            this.rangeCircles.forEach(c => c.remove());
        }
        this.rangeCircles = [50, 100, 200].map(km =>
            L.circle([lat, lng], {
                radius: km * 1000,
                color: 'rgba(88,166,255,0.15)',
                fillColor: 'transparent',
                weight: 1,
                dashArray: '4 6',
                interactive: false,
            }).addTo(this.map)
        );
    }

    centerOnStation() {
        if (this.myPosition) {
            this.map.setView([this.myPosition.lat, this.myPosition.lng], 10);
        }
    }

    addOrUpdateStation(station) {
        if (!station.latitude || !station.longitude) return;
        if (station.latitude === 0 && station.longitude === 0) return;

        const source = station.source;
        const call = station.callsign;
        const lat = station.latitude;
        const lng = station.longitude;
        const dist = station.distance_km;
        const markers = source === 'rf' ? this.rfMarkers : this.isMarkers;
        const layer = source === 'rf' ? this.rfLayer : this.isLayer;

        // Build popup content
        const distStr = dist ? `${dist.toFixed(1)} km` : 'N/A';
        const headingStr = station.heading ? `${station.heading.toFixed(0)}°` : '';
        const timeStr = station.last_heard
            ? new Date(station.last_heard * 1000).toLocaleTimeString()
            : '';
        const countStr = station.packet_count || 1;
        const sourceLabel = source === 'rf' ? 'RF' : 'APRS-IS';
        const sourceClass = source === 'rf' ? 'popup-rf' : 'popup-is';

        // Build icon from APRS symbol sprite sheet
        const symTable = station.symbol_table || '/';
        const symCode = station.symbol_code || '-';
        const emoji = (typeof getAPRSEmoji === 'function') ? getAPRSEmoji(symTable, symCode) : '📍';
        const symName = (typeof getAPRSSymbolName === 'function') ? getAPRSSymbolName(symTable, symCode) : '';
        const category = (typeof getAPRSCategory === 'function') ? getAPRSCategory(symTable, symCode) : 'other';
        const spriteHtml = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, 20) : emoji;

        // Store metadata for type filtering
        this.stationMeta[call] = { source, symbol_table: symTable, symbol_code: symCode, category };

        const popup = `
            <div class="popup-call ${sourceClass}">${call}</div>
            <div class="popup-detail">
                Source: ${sourceLabel}<br>
                Type: <span class="popup-sym-inline">${spriteHtml}</span> ${symName}<br>
                Distance: ${distStr} ${headingStr}<br>
                Last heard: ${timeStr}<br>
                Packets: ${countStr}<br>
                ${station.last_comment ? 'Comment: ' + station.last_comment + '<br>' : ''}
                ${station.last_path ? 'Path: ' + station.last_path : ''}
            </div>
        `;

        const borderColor = source === 'rf' ? '#f85149' : '#58a6ff';
        const markerSprite = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, 20) : emoji;

        const iconHtml = `<div class="aprs-emoji-marker aprs-emoji-${source}" style="border-color:${borderColor};">${markerSprite}</div>`;
        const aprsIcon = L.divIcon({
            className: 'aprs-icon-wrapper',
            html: iconHtml,
            iconSize: [32, 32],
            iconAnchor: [16, 16],
            popupAnchor: [0, -16],
        });

        if (markers[call]) {
            // Update existing marker
            markers[call].setLatLng([lat, lng]).setPopupContent(popup);
            markers[call].setIcon(aprsIcon);
        } else {
            markers[call] = L.marker([lat, lng], { icon: aprsIcon })
                .bindPopup(popup)
                .addTo(layer);
        }

        // Apply type filter visibility
        this._applyTypeFilterToStation(call, source);

        // Draw propagation line for RF stations
        if (source === 'rf' && this.myPosition) {
            this._updateLine(call, lat, lng, dist, station.last_heard);
        }
    }

    removeStation(callsign, source) {
        const markers = source === 'rf' ? this.rfMarkers : this.isMarkers;
        const layer = source === 'rf' ? this.rfLayer : this.isLayer;

        if (markers[callsign]) {
            layer.removeLayer(markers[callsign]);
            delete markers[callsign];
        }

        if (source === 'rf' && this.rfLines[callsign]) {
            this.lineLayer.removeLayer(this.rfLines[callsign]);
            delete this.rfLines[callsign];
            delete this.rfLineData[callsign];
        }
    }

    clearAll() {
        this.rfLayer.clearLayers();
        this.isLayer.clearLayers();
        this.lineLayer.clearLayers();
        this.rfMarkers = {};
        this.isMarkers = {};
        this.rfLines = {};
        this.rfLineData = {};
    }

    _updateLine(callsign, lat, lng, distance, lastHeard) {
        if (!this.myPosition) return;

        // Store metadata for time filtering
        this.rfLineData[callsign] = {
            last_heard: lastHeard || (Date.now() / 1000),
            distance_km: distance || 0,
            lat, lng,
        };

        const points = [
            [this.myPosition.lat, this.myPosition.lng],
            [lat, lng]
        ];

        // Color based on distance
        let color;
        if (!distance) {
            color = 'rgba(248, 81, 73, 0.4)';
        } else if (distance > 200) {
            color = 'rgba(188, 140, 255, 0.7)'; // Purple for long DX
        } else if (distance > 100) {
            color = 'rgba(63, 185, 80, 0.6)';  // Green for good
        } else if (distance > 50) {
            color = 'rgba(210, 153, 34, 0.5)';  // Orange for medium
        } else {
            color = 'rgba(248, 81, 73, 0.4)';  // Red for close
        }

        const weight = distance && distance > 100 ? 2.5 : 1.5;

        if (this.rfLines[callsign]) {
            this.rfLines[callsign].setLatLngs(points);
            this.rfLines[callsign].setStyle({ color, weight });
        } else {
            this.rfLines[callsign] = L.polyline(points, {
                color,
                weight,
                opacity: 0.8,
                dashArray: distance && distance > 100 ? null : '6 4',
            }).addTo(this.lineLayer);
        }

        // Apply time filter to this new/updated line
        this._applyLineTimeFilter(callsign);
    }

    /**
     * Set line time filter and re-apply to all lines.
     * @param {number} hours - 0 for all time, otherwise hours
     */
    setLineTimeFilter(hours) {
        this.lineTimeFilter = hours;
        this.applyAllLineTimeFilters();
    }

    /**
     * Apply time filter to a single line by callsign.
     */
    _applyLineTimeFilter(callsign) {
        const line = this.rfLines[callsign];
        const data = this.rfLineData[callsign];
        if (!line || !data) return;

        if (this.lineTimeFilter === 0) {
            // All time — show everything
            if (!this.lineLayer.hasLayer(line)) {
                this.lineLayer.addLayer(line);
            }
            return;
        }

        const now = Date.now() / 1000;
        const cutoff = now - (this.lineTimeFilter * 3600);

        if (data.last_heard >= cutoff) {
            if (!this.lineLayer.hasLayer(line)) {
                this.lineLayer.addLayer(line);
            }
        } else {
            if (this.lineLayer.hasLayer(line)) {
                this.lineLayer.removeLayer(line);
            }
        }
    }

    /**
     * Re-apply time filter to all lines.
     */
    applyAllLineTimeFilters() {
        for (const callsign in this.rfLines) {
            this._applyLineTimeFilter(callsign);
        }
    }

    // ── Station type filtering ─────────────────────────────────

    /**
     * Set visible categories from a Set. Empty set = show all.
     * @param {Set<string>} categorySet
     */
    setTypeFilters(categorySet) {
        this.typeFilters = categorySet;
        this.applyAllTypeFilters();
    }

    /**
     * Apply type filter to a single station marker.
     */
    _applyTypeFilterToStation(callsign, source) {
        const meta = this.stationMeta[callsign];
        if (!meta) return;

        const markers = source === 'rf' ? this.rfMarkers : this.isMarkers;
        const layer = source === 'rf' ? this.rfLayer : this.isLayer;
        const marker = markers[callsign];
        if (!marker) return;

        const visible = this.typeFilters.size === 0 || this.typeFilters.has(meta.category);

        if (visible) {
            if (!layer.hasLayer(marker)) layer.addLayer(marker);
        } else {
            if (layer.hasLayer(marker)) layer.removeLayer(marker);
        }

        // Also hide/show the propagation line for RF stations
        if (source === 'rf' && this.rfLines[callsign]) {
            const line = this.rfLines[callsign];
            if (visible) {
                if (!this.lineLayer.hasLayer(line)) this.lineLayer.addLayer(line);
            } else {
                if (this.lineLayer.hasLayer(line)) this.lineLayer.removeLayer(line);
            }
        }
    }

    /**
     * Re-apply type filter to all station markers.
     */
    applyAllTypeFilters() {
        for (const callsign in this.stationMeta) {
            const meta = this.stationMeta[callsign];
            this._applyTypeFilterToStation(callsign, meta.source);
        }
    }

    /**
     * Build the multi-select checkbox dropdown for station type filtering.
     */
    _initTypeFilterCheckboxes() {
        const btn = document.getElementById('map-type-filter-btn');
        const dropdown = document.getElementById('map-type-filter-dropdown');
        const container = document.getElementById('map-type-checkboxes');
        const allCb = document.getElementById('map-type-all');
        if (!btn || !dropdown || !container || !allCb) return;
        if (typeof APRS_CATEGORY_ORDER === 'undefined') return;

        // Build one checkbox per category
        APRS_CATEGORY_ORDER.forEach(key => {
            const label = document.createElement('label');
            label.className = 'map-type-cb';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = true;
            cb.dataset.cat = key;
            const span = document.createElement('span');
            span.textContent = APRS_CATEGORIES[key].label;
            label.appendChild(cb);
            label.appendChild(span);
            container.appendChild(label);
        });

        // Toggle dropdown open/close
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('open');
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && e.target !== btn) {
                dropdown.classList.remove('open');
            }
        });

        // "All Types" master checkbox
        allCb.addEventListener('change', () => {
            const checked = allCb.checked;
            container.querySelectorAll('input[type=checkbox]').forEach(cb => {
                cb.checked = checked;
            });
            this._syncTypeFilters(container, allCb);
        });

        // Individual checkboxes
        container.addEventListener('change', () => {
            this._syncTypeFilters(container, allCb);
        });
    }

    /**
     * Read checkbox state and update typeFilters Set, then re-filter.
     */
    _syncTypeFilters(container, allCb) {
        const boxes = container.querySelectorAll('input[type=checkbox]');
        const checked = [];
        const unchecked = [];
        boxes.forEach(cb => {
            if (cb.checked) checked.push(cb.dataset.cat);
            else unchecked.push(cb.dataset.cat);
        });

        // Update the "All" checkbox state (checked if all are checked, indeterminate if partial)
        if (unchecked.length === 0) {
            allCb.checked = true;
            allCb.indeterminate = false;
        } else if (checked.length === 0) {
            allCb.checked = false;
            allCb.indeterminate = false;
        } else {
            allCb.checked = false;
            allCb.indeterminate = true;
        }

        // If all checked → empty set (show all). Otherwise → set of checked categories.
        if (unchecked.length === 0) {
            this.setTypeFilters(new Set());
        } else {
            this.setTypeFilters(new Set(checked));
        }

        // Update button label
        const btn = document.getElementById('map-type-filter-btn');
        if (unchecked.length === 0) {
            btn.textContent = '🏷️ Types ▾';
        } else if (checked.length === 0) {
            btn.textContent = '🏷️ None ▾';
        } else {
            btn.textContent = `🏷️ ${checked.length}/${boxes.length} ▾`;
        }
    }

    toggleLines() {
        this.showLines = !this.showLines;
        if (this.showLines) {
            this.map.addLayer(this.lineLayer);
        } else {
            this.map.removeLayer(this.lineLayer);
        }
        return this.showLines;
    }

    toggleRF() {
        this.showRF = !this.showRF;
        if (this.showRF) {
            this.map.addLayer(this.rfLayer);
        } else {
            this.map.removeLayer(this.rfLayer);
        }
        return this.showRF;
    }

    toggleIS() {
        this.showIS = !this.showIS;
        if (this.showIS) {
            this.map.addLayer(this.isLayer);
        } else {
            this.map.removeLayer(this.isLayer);
        }
        return this.showIS;
    }

    _bindControls() {
        document.getElementById('btn-center-map')?.addEventListener('click', () => {
            this.centerOnStation();
        });

        document.getElementById('btn-toggle-lines')?.addEventListener('click', (e) => {
            const active = this.toggleLines();
            e.target.classList.toggle('active', active);
        });

        document.getElementById('btn-toggle-rf')?.addEventListener('click', (e) => {
            const active = this.toggleRF();
            e.target.classList.toggle('active', active);
        });

        document.getElementById('btn-toggle-is')?.addEventListener('click', (e) => {
            const active = this.toggleIS();
            e.target.classList.toggle('active', active);
        });

        document.getElementById('line-time-filter')?.addEventListener('change', (e) => {
            const hours = parseInt(e.target.value, 10);
            this.setLineTimeFilter(hours);
        });

        // Station type filter — multi-select checkboxes
        this._initTypeFilterCheckboxes();

        document.getElementById('btn-pick-location')?.addEventListener('click', (e) => {
            this.togglePickMode();
            e.target.classList.toggle('active', this.pickMode);
        });

        document.getElementById('btn-pick-location-settings')?.addEventListener('click', () => {
            this.enablePickMode();
        });

        document.getElementById('btn-toggle-theme')?.addEventListener('click', (e) => {
            const dark = this.toggleTheme();
            e.target.classList.toggle('active', dark);
            e.target.textContent = dark ? '🌙' : '☀️';
            e.target.title = dark ? 'Switch to light map' : 'Switch to dark map';
        });
    }

    /**
     * Toggle between light and dark map tiles.
     */
    toggleTheme() {
        this.darkMode = !this.darkMode;
        this.map.getContainer().classList.toggle('dark-tiles', this.darkMode);
        return this.darkMode;
    }

    /**
     * Toggle pick-location mode on/off.
     */
    togglePickMode() {
        if (this.pickMode) {
            this.disablePickMode();
        } else {
            this.enablePickMode();
        }
    }

    /**
     * Enable pick-location mode — next map click sets station location.
     */
    enablePickMode() {
        this.pickMode = true;
        this.map.getContainer().style.cursor = 'crosshair';

        const pickBtn = document.getElementById('btn-pick-location');
        if (pickBtn) pickBtn.classList.add('active');

        // Show banner
        let banner = document.getElementById('pick-mode-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'pick-mode-banner';
            banner.innerHTML = '📌 Click on the map to set your station location <button id="pick-mode-cancel">Cancel</button>';
            document.getElementById('map-panel').appendChild(banner);
            document.getElementById('pick-mode-cancel')?.addEventListener('click', () => {
                this.disablePickMode();
            });
        }
        banner.style.display = 'flex';

        // One-time click handler
        this._pickHandler = (e) => {
            const { lat, lng } = e.latlng;
            this._placePickMarker(lat, lng);

            // Fill settings fields
            const latEl = document.getElementById('cfg-latitude');
            const lngEl = document.getElementById('cfg-longitude');
            if (latEl) latEl.value = lat.toFixed(4);
            if (lngEl) lngEl.value = lng.toFixed(4);

            // Fire callback if set
            if (this.onLocationPicked) {
                this.onLocationPicked(lat, lng);
            }

            this.disablePickMode();
        };
        this.map.once('click', this._pickHandler);
    }

    /**
     * Disable pick-location mode.
     */
    disablePickMode() {
        this.pickMode = false;
        this.map.getContainer().style.cursor = '';

        const pickBtn = document.getElementById('btn-pick-location');
        if (pickBtn) pickBtn.classList.remove('active');

        const banner = document.getElementById('pick-mode-banner');
        if (banner) banner.style.display = 'none';

        // Remove pending click handler if not yet fired
        if (this._pickHandler) {
            this.map.off('click', this._pickHandler);
            this._pickHandler = null;
        }
    }

    /**
     * Show a temporary marker where the user clicked.
     */
    _placePickMarker(lat, lng) {
        if (this.pickMarker) {
            this.pickMarker.setLatLng([lat, lng]);
        } else {
            const icon = L.divIcon({
                className: 'pick-marker',
                html: `<div style="
                    background: #f0883e;
                    width: 16px; height: 16px;
                    border-radius: 50%;
                    border: 3px solid #fff;
                    box-shadow: 0 0 10px rgba(240,136,62,0.7);
                "></div>`,
                iconSize: [16, 16],
                iconAnchor: [8, 8],
            });
            this.pickMarker = L.marker([lat, lng], { icon, zIndexOffset: 900 })
                .addTo(this.map)
                .bindPopup(`<b>Picked Location</b><br>${lat.toFixed(4)}, ${lng.toFixed(4)}<br><i>Save settings to apply</i>`);
        }
        this.pickMarker.openPopup();

        // Auto-remove after 10 seconds
        setTimeout(() => {
            if (this.pickMarker) {
                this.pickMarker.remove();
                this.pickMarker = null;
            }
        }, 10000);
    }

    _addLegend() {
        const legend = document.createElement('div');
        legend.className = 'map-legend';
        legend.innerHTML = `
            <div class="legend-item">
                <div class="legend-swatch" style="background: #39d5ff; border: 2px solid white;"></div>
                <span>My Station</span>
            </div>
            <div class="legend-item">
                <div class="legend-emoji" style="border-color: #f85149;">📡</div>
                <span>RF Station</span>
            </div>
            <div class="legend-item">
                <div class="legend-emoji" style="border-color: #58a6ff;">📡</div>
                <span>APRS-IS Station</span>
            </div>
            <div class="legend-item">
                <div class="legend-line" style="background: #f85149;"></div>
                <span>&lt; 50 km</span>
            </div>
            <div class="legend-item">
                <div class="legend-line" style="background: #d29922;"></div>
                <span>50-100 km</span>
            </div>
            <div class="legend-item">
                <div class="legend-line" style="background: #3fb950;"></div>
                <span>100-200 km</span>
            </div>
            <div class="legend-item">
                <div class="legend-line" style="background: #bc8cff;"></div>
                <span>&gt; 200 km (DX)</span>
            </div>
        `;
        document.getElementById('map-panel').appendChild(legend);
    }

    /**
     * Fit map bounds to show all RF stations and my position.
     */
    fitToStations() {
        const points = [];
        if (this.myPosition) {
            points.push([this.myPosition.lat, this.myPosition.lng]);
        }
        Object.values(this.rfMarkers).forEach(m => {
            const ll = m.getLatLng();
            points.push([ll.lat, ll.lng]);
        });
        if (points.length > 1) {
            this.map.fitBounds(L.latLngBounds(points).pad(0.1));
        }
    }
}

// Global instance
window.pvMap = new PropViewMap();
