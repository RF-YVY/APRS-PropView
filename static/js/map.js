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
        this.rfArrows = {};     // callsign -> [arrowhead markers]
        this.rfLineData = {};   // callsign -> {last_heard, distance_km}
        this.showLines = true;
        this.showRF = true;
        this.showIS = true;
        this.lineTimeFilter = 24; // hours, 0 = all time
        this.rfLayer = null;
        this.isLayer = null;
        this.lineLayer = null;
        this.rangeCircles = null;
        this.observedRangeLayer = null;
        this.pickMode = false;
        this.pickMarker = null;
        this.onLocationPicked = null; // callback(lat, lng)
        this.darkMode = true;
        this.typeFilters = new Set();  // empty = show all, otherwise set of visible category keys
        // Track station symbol metadata for type filtering
        this.stationMeta = {};  // callsign -> {source, symbol_table, symbol_code, category}
        this.myCallsign = '';   // own callsign for path filtering
        this.hopMarkers = {};   // callsign -> [circleMarker, ...] for digi hop waypoints
        this.showLabels = false;   // callsign labels toggle
        this.autoFit = false;      // auto-zoom to fit all stations
        this._userInteracted = false; // true when user manually pans/zooms
        this._autoFitPending = false; // debounce flag
        this._programmaticViewportChange = false;
        this._observedRangeFetchedAt = 0;
        this._observedRangeRequest = null;
        this.weatherOverlayConfig = {
            radar_enabled: false,
            radar_provider: 'rainviewer',
            radar_opacity: 0.55,
            radar_animate: true,
            alert_overlay_enabled: false,
            alert_overlay_groups: ['warnings', 'watches', 'flood', 'winter', 'marine', 'fire_heat', 'other'],
        };
        this.weatherAlerts = [];
        this.weatherAlertLayer = null;
        this.radarFrames = [];
        this.radarTileLayers = [];
        this.radarFrameIndex = 0;
        this.radarAnimationTimer = null;
        this.radarMetadata = null;
        this.radarMetadataFetchedAt = 0;
        this.radarMetadataRequest = null;
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
        this.map.createPane('weatherRadarPane');
        this.map.getPane('weatherRadarPane').style.zIndex = 320;
        this.map.getPane('weatherRadarPane').style.pointerEvents = 'none';
        this.map.createPane('weatherAlertPane');
        this.map.getPane('weatherAlertPane').style.zIndex = 430;

        // Add legend
        this._addLegend();

        // Bind map controls
        this._bindControls();

        // Manual pan/zoom should take ownership of the viewport.
        this.map.on('dragstart', () => this._handleManualViewportChange());
        this.map.on('zoomstart', () => {
            if (!this._autoFitPending) this._handleManualViewportChange();
        });

        // Save map position on moveend (debounced)
        let _moveTimer = null;
        this.map.on('moveend', () => {
            clearTimeout(_moveTimer);
            _moveTimer = setTimeout(() => this._saveUIState(), 500);
        });

        // Restore saved UI state from localStorage
        this._restoreUIState();

        return this;
    }

    setMyPosition(lat, lng, callsign) {
        this.myPosition = { lat, lng };
        this.myCallsign = (callsign || '').toUpperCase();

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
            this._runProgrammaticViewportChange(() => {
                this.map.panTo([this.myPosition.lat, this.myPosition.lng]);
            });
            this._saveUIState();
        }
    }

    async updateObservedRange(propTimestamp) {
        if (!this.myPosition) return;
        const now = Date.now();
        const cacheMs = 5 * 60 * 1000;
        const serverTsMs = propTimestamp ? propTimestamp * 1000 : 0;
        const freshEnough = this._observedRangeFetchedAt && (now - this._observedRangeFetchedAt) < cacheMs;
        if (freshEnough && (!serverTsMs || serverTsMs <= this._observedRangeFetchedAt)) return;
        if (this._observedRangeRequest) return this._observedRangeRequest;

        this._observedRangeRequest = (async () => {
            const resp = await fetch('/api/analytics/observed-range?hours=24');
            const data = await resp.json();

            // Remove old observed range layer
            if (this.observedRangeLayer) {
                this.observedRangeLayer.remove();
                this.observedRangeLayer = null;
            }

            if (!data.sectors || data.sectors.length === 0) return;

            const lat = this.myPosition.lat;
            const lng = this.myPosition.lng;

            // Build polygon from sector max distances
            const sectorAngles = { 'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5, 'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5, 'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5, 'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5 };

            const points = [];
            data.sectors.forEach(s => {
                const angleDeg = sectorAngles[s.sector];
                if (angleDeg === undefined || !s.current_max_km || s.current_max_km <= 0) return;

                // Calculate point at bearing and distance from center
                const distKm = s.current_max_km;
                const R = 6371; // Earth radius km
                const latR = lat * Math.PI / 180;
                const lngR = lng * Math.PI / 180;
                const bearing = angleDeg * Math.PI / 180;
                const d = distKm / R;

                const newLat = Math.asin(Math.sin(latR) * Math.cos(d) + Math.cos(latR) * Math.sin(d) * Math.cos(bearing));
                const newLng = lngR + Math.atan2(Math.sin(bearing) * Math.sin(d) * Math.cos(latR), Math.cos(d) - Math.sin(latR) * Math.sin(newLat));

                points.push([newLat * 180 / Math.PI, newLng * 180 / Math.PI]);
            });

            if (points.length < 3) return;

            // Close the polygon
            points.push(points[0]);

            this.observedRangeLayer = L.polygon(points, {
                color: 'rgba(63,185,80,0.5)',
                fillColor: 'rgba(63,185,80,0.08)',
                weight: 1.5,
                dashArray: '6 4',
                interactive: false,
            }).addTo(this.map);
            this._observedRangeFetchedAt = Date.now();
        })().catch((e) => {
            console.error('Observed range update error:', e);
        }).finally(() => {
            this._observedRangeRequest = null;
        });

        return this._observedRangeRequest;
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
        const distStr = dist ? window.formatDist(dist) : 'N/A';
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
        const spriteHtml = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, 28) : emoji;

        // Store metadata for type filtering
        this.stationMeta[call] = { source, symbol_table: symTable, symbol_code: symCode, category, last_heard: station.last_heard || 0 };

        const popupSprite = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, 32) : emoji;

        // Determine direct-heard vs via-digi for RF stations
        const isDirect = source === 'rf' ? this._isDirectPath(station.last_path) : null;
        const heardViaHtml = isDirect === true
            ? '<span style="color:#3fb950;font-weight:600;">Direct</span>'
            : isDirect === false
                ? '<span style="color:#d29922;font-weight:600;">Via Digipeater</span>'
                : '';

        // Time ago string
        let agoStr = '';
        if (station.last_heard) {
            const secs = Math.floor(Date.now() / 1000 - station.last_heard);
            if (secs < 60) agoStr = `${secs}s ago`;
            else if (secs < 3600) agoStr = `${Math.floor(secs / 60)}m ago`;
            else agoStr = `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m ago`;
        }

        const popup = `
            <div class="popup-header">
                <span class="popup-sym-inline">${popupSprite}</span>
                <span class="popup-call ${sourceClass}">${call}</span>
                <span class="popup-source-tag popup-tag-${source}">${sourceLabel}</span>
            </div>
            <table class="popup-table">
                <tr><td class="popup-lbl">Type</td><td>${symName || 'Unknown'}</td></tr>
                <tr><td class="popup-lbl">Distance</td><td>${distStr}${headingStr ? ' · ' + headingStr : ''}</td></tr>
                <tr><td class="popup-lbl">Heard</td><td>${timeStr}${agoStr ? ' (' + agoStr + ')' : ''}</td></tr>
                <tr><td class="popup-lbl">Packets</td><td>${countStr}</td></tr>
                ${station.last_comment ? `<tr><td class="popup-lbl">Comment</td><td>${station.last_comment}</td></tr>` : ''}
                ${station.last_path ? `<tr><td class="popup-lbl">Path</td><td class="popup-path">${station.last_path}</td></tr>` : ''}
                ${heardViaHtml ? `<tr><td class="popup-lbl">Via</td><td>${heardViaHtml}</td></tr>` : ''}
                <tr><td class="popup-lbl">Position</td><td>${lat.toFixed(4)}, ${lng.toFixed(4)}</td></tr>
            </table>
        `;

        const borderColor = source === 'rf' ? '#f85149' : '#58a6ff';
        const markerSprite = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, 16) : emoji;

        const iconHtml = `<div class="aprs-emoji-marker aprs-emoji-${source}" style="border-color:${borderColor};">${markerSprite}</div>`;
        const aprsIcon = L.divIcon({
            className: 'aprs-icon-wrapper',
            html: iconHtml,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
            popupAnchor: [0, -12],
        });

        if (markers[call]) {
            // Update existing marker
            markers[call].setLatLng([lat, lng]).setPopupContent(popup);
            markers[call].setIcon(aprsIcon);
        } else {
            markers[call] = L.marker([lat, lng], { icon: aprsIcon })
                .bindPopup(popup)
                .bindTooltip(call, {
                    permanent: true,
                    direction: 'top',
                    offset: [0, -14],
                    className: 'callsign-label',
                })
                .addTo(layer);
            // Respect current label visibility
            if (!this.showLabels) markers[call].closeTooltip();
        }

        // Remove ghost class on fresh update
        this._setGhost(call, source, false);

        // Apply type filter visibility
        this._applyTypeFilterToStation(call, source);

        // Draw propagation line for RF stations
        if (source === 'rf' && this.myPosition) {
            this._updateLine(call, lat, lng, dist, station.last_heard, station.last_path);
        }

        // Auto-fit if enabled
        if (this.autoFit && !this._userInteracted) this.autoFitNow();
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

        // Remove arrow markers
        if (this.rfArrows[callsign]) {
            this.rfArrows[callsign].forEach(m => this.lineLayer.removeLayer(m));
            delete this.rfArrows[callsign];
        }

        // Remove hop markers
        if (this.hopMarkers[callsign]) {
            this.hopMarkers[callsign].forEach(m => this.lineLayer.removeLayer(m));
            delete this.hopMarkers[callsign];
        }

        delete this.stationMeta[callsign];
    }

    /** Apply or remove ghhost CSS on a marker's icon element. */
    _setGhost(callsign, source, ghosted) {
        const markers = source === 'rf' ? this.rfMarkers : this.isMarkers;
        const marker = markers[callsign];
        if (!marker) return;
        const el = marker.getElement();
        if (!el) return;
        const inner = el.querySelector('.aprs-emoji-marker');
        if (!inner) return;
        if (ghosted) {
            inner.classList.add('ghosted');
        } else {
            inner.classList.remove('ghosted');
        }
    }

    /** Check all markers and ghost/unghost based on last_heard age. */
    ghostStaleMarkers(ghostMinutes) {
        if (!ghostMinutes || ghostMinutes <= 0) {
            // Ghosting disabled — remove all ghost classes
            for (const [call, meta] of Object.entries(this.stationMeta)) {
                this._setGhost(call, meta.source, false);
            }
            return;
        }
        const cutoff = Date.now() / 1000 - ghostMinutes * 60;
        for (const [call, meta] of Object.entries(this.stationMeta)) {
            const isStale = meta.last_heard > 0 && meta.last_heard < cutoff;
            this._setGhost(call, meta.source, isStale);
        }
    }

    clearAll() {
        this.rfLayer.clearLayers();
        this.isLayer.clearLayers();
        this.lineLayer.clearLayers();
        this.rfMarkers = {};
        this.isMarkers = {};
        this.rfLines = {};
        this.rfArrows = {};
        this.rfLineData = {};
        this.hopMarkers = {};
    }

    /**
     * Parse a digipeater path string to extract real callsigns
     * (skipping WIDE/RELAY/TRACE/TCPIP/qA aliases and own callsign).
     */
    _parseDigiPath(path) {
        if (!path) return [];
        const aliasRe = /^(WIDE|RELAY|TRACE|TCPIP|qA[A-Z])\d?/i;
        const digis = [];
        for (const part of path.split(',')) {
            const call = part.trim().replace(/\*$/, '');
            if (!call) continue;
            if (aliasRe.test(call)) continue;
            if (this.myCallsign && call.toUpperCase() === this.myCallsign) continue;
            digis.push(call);
        }
        return digis;
    }

    /**
     * Look up a station's position from existing markers.
     * Returns [lat, lng] or null.
     */
    _getStationPosition(callsign) {
        const m = this.rfMarkers[callsign] || this.isMarkers[callsign];
        if (m) {
            const ll = m.getLatLng();
            return [ll.lat, ll.lng];
        }
        return null;
    }

    _updateLine(callsign, lat, lng, distance, lastHeard, path) {
        if (!this.myPosition) return;

        // Store metadata for time filtering
        this.rfLineData[callsign] = {
            last_heard: lastHeard || (Date.now() / 1000),
            distance_km: distance || 0,
            lat, lng,
        };

        // Build multi-hop points: origin station → digis → my station
        const myPos = [this.myPosition.lat, this.myPosition.lng];
        const stationPos = [lat, lng];
        const digis = this._parseDigiPath(path);
        const points = [stationPos];
        const hopPositions = [];

        for (const digi of digis) {
            const pos = this._getStationPosition(digi);
            if (pos) {
                points.push(pos);
                hopPositions.push({ call: digi, pos });
            }
        }
        points.push(myPos);

        // Color based on distance
        let color;
        if (!distance) {
            color = '#f85149';
        } else if (distance > 200) {
            color = '#bc8cff'; // Purple for long DX
        } else if (distance > 100) {
            color = '#3fb950'; // Green for good
        } else if (distance > 50) {
            color = '#d29922'; // Orange for medium
        } else {
            color = '#f85149'; // Red for close
        }

        const weight = distance && distance > 100 ? 2.5 : 1.5;
        const opacity = 0.7;

        if (this.rfLines[callsign]) {
            this.rfLines[callsign].setLatLngs(points);
            this.rfLines[callsign].setStyle({ color, weight, opacity });
        } else {
            this.rfLines[callsign] = L.polyline(points, {
                color,
                weight,
                opacity,
            }).addTo(this.lineLayer);
        }

        // Update arrowhead markers
        if (this.rfArrows[callsign]) {
            this.rfArrows[callsign].forEach(m => this.lineLayer.removeLayer(m));
        }
        this.rfArrows[callsign] = this._createArrowheads(points, color, opacity);

        // Update hop waypoint markers
        if (this.hopMarkers[callsign]) {
            this.hopMarkers[callsign].forEach(m => this.lineLayer.removeLayer(m));
        }
        this.hopMarkers[callsign] = hopPositions.map(({ call, pos }) =>
            L.circleMarker(pos, {
                radius: 5,
                color: '#fff',
                fillColor: color,
                fillOpacity: 0.9,
                weight: 2,
            }).bindTooltip(call, { permanent: false, direction: 'top', offset: [0, -6] })
              .addTo(this.lineLayer)
        );

        // Apply time filter to this new/updated line
        this._applyLineTimeFilter(callsign);
    }

    /**
     * Determine if an RF station was heard directly (no used digi callsign hops).
     */
    _isDirectPath(path) {
        if (!path) return true;
        const aliasRe = /^(WIDE|RELAY|TRACE|TCPIP|qA[A-Z])\d?(-\d)?$/i;
        for (const part of path.split(',')) {
            const hop = part.trim();
            if (!hop) continue;
            if (hop.endsWith('*')) {
                const call = hop.replace('*', '');
                if (!aliasRe.test(call)) return false;
            }
        }
        return true;
    }

    /**
     * Calculate bearing in degrees from point A to point B.
     * Returns degrees clockwise from north (CSS: 0° = up).
     */
    _bearing(from, to) {
        const toRad = Math.PI / 180;
        const lat1 = from.lat * toRad;
        const lat2 = to.lat * toRad;
        const dLng = (to.lng - from.lng) * toRad;
        const y = Math.sin(dLng) * Math.cos(lat2);
        const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
        return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
    }

    /**
     * Create arrowhead triangle markers along a polyline.
     * Places an arrow at the midpoint of each segment, pointing toward myPos.
     */
    _createArrowheads(points, color, opacity) {
        const arrows = [];
        for (let i = 0; i < points.length - 1; i++) {
            const from = L.latLng(points[i]);
            const to = L.latLng(points[i + 1]);
            const angle = this._bearing(from, to);
            const mid = L.latLng(
                (from.lat + to.lat) / 2,
                (from.lng + to.lng) / 2
            );
            const arrowIcon = L.divIcon({
                className: 'arrow-icon',
                html: `<div style="
                    width: 0; height: 0;
                    border-left: 6px solid transparent;
                    border-right: 6px solid transparent;
                    border-bottom: 10px solid ${color};
                    opacity: ${opacity};
                    transform: rotate(${angle}deg);
                    transform-origin: center center;
                "></div>`,
                iconSize: [12, 10],
                iconAnchor: [6, 5],
            });
            arrows.push(
                L.marker(mid, { icon: arrowIcon, interactive: false }).addTo(this.lineLayer)
            );
        }
        return arrows;
    }

    /**
     * Set line time filter and re-apply to all lines.
     * @param {number} hours - 0 for all time, otherwise hours
     */
    setLineTimeFilter(hours) {
        this.lineTimeFilter = hours;
        this.applyAllLineTimeFilters();
        this._saveUIState();
    }

    /**
     * Apply time filter to a single line by callsign.
     */
    _applyLineTimeFilter(callsign) {
        const line = this.rfLines[callsign];
        const data = this.rfLineData[callsign];
        if (!line || !data) return;

        const hops = this.hopMarkers[callsign] || [];
        const arrows = this.rfArrows[callsign] || [];
        let visible = true;

        if (this.lineTimeFilter !== 0) {
            const now = Date.now() / 1000;
            const cutoff = now - (this.lineTimeFilter * 3600);
            visible = data.last_heard >= cutoff;
        }

        if (visible) {
            if (!this.lineLayer.hasLayer(line)) this.lineLayer.addLayer(line);
            hops.forEach(m => { if (!this.lineLayer.hasLayer(m)) this.lineLayer.addLayer(m); });
            arrows.forEach(m => { if (!this.lineLayer.hasLayer(m)) this.lineLayer.addLayer(m); });
        } else {
            if (this.lineLayer.hasLayer(line)) this.lineLayer.removeLayer(line);
            hops.forEach(m => { if (this.lineLayer.hasLayer(m)) this.lineLayer.removeLayer(m); });
            arrows.forEach(m => { if (this.lineLayer.hasLayer(m)) this.lineLayer.removeLayer(m); });
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
        // When showing, re-apply time filter so stale lines don't reappear
        if (source === 'rf' && this.rfLines[callsign]) {
            if (visible) {
                this._applyLineTimeFilter(callsign);
            } else {
                const line = this.rfLines[callsign];
                if (this.lineLayer.hasLayer(line)) this.lineLayer.removeLayer(line);
                const hops = this.hopMarkers[callsign] || [];
                hops.forEach(m => { if (this.lineLayer.hasLayer(m)) this.lineLayer.removeLayer(m); });
                const arrows = this.rfArrows[callsign] || [];
                arrows.forEach(m => { if (this.lineLayer.hasLayer(m)) this.lineLayer.removeLayer(m); });
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
        this._saveUIState();
    }

    // ── Callsign labels ────────────────────────────────────────

    toggleLabels() {
        this.showLabels = !this.showLabels;
        this._applyLabelsToAll();
        this._saveUIState();
        return this.showLabels;
    }

    setLabels(show) {
        this.showLabels = show;
        this._applyLabelsToAll();
    }

    _applyLabelsToAll() {
        const allMarkers = { ...this.rfMarkers, ...this.isMarkers };
        for (const marker of Object.values(allMarkers)) {
            if (this.showLabels) {
                marker.openTooltip();
            } else {
                marker.closeTooltip();
            }
        }
    }

    // ── Auto-fit to visible stations ───────────────────────────

    toggleAutoFit() {
        this.autoFit = !this.autoFit;
        this._userInteracted = false;
        if (this.autoFit) this.autoFitNow();
        this._saveUIState();
        return this.autoFit;
    }

    setAutoFit(enabled) {
        this.autoFit = enabled;
        this._userInteracted = false;
        if (enabled) this.autoFitNow();
        this._syncAutoFitButton();
    }

    _syncAutoFitButton() {
        const btn = document.getElementById('btn-toggle-autofit');
        if (btn) btn.classList.toggle('active', this.autoFit);
    }

    _handleManualViewportChange() {
        if (this._programmaticViewportChange || this._autoFitPending) return;
        this._userInteracted = true;
        if (this.autoFit) {
            this.autoFit = false;
            this._syncAutoFitButton();
        }
        this._saveUIState();
    }

    _runProgrammaticViewportChange(callback) {
        this._programmaticViewportChange = true;
        try {
            callback();
        } finally {
            setTimeout(() => {
                this._programmaticViewportChange = false;
            }, 500);
        }
    }

    /**
     * Fit map to show all visible station markers + my position.
     * Only acts if autoFit is on and user hasn't manually interacted.
     */
    autoFitNow() {
        if (!this.autoFit || this._userInteracted) return;
        const points = [];
        if (this.myPosition) {
            points.push([this.myPosition.lat, this.myPosition.lng]);
        }
        // Only include visible markers (respect layer and type filter)
        const addVisible = (markers, layer) => {
            for (const [call, marker] of Object.entries(markers)) {
                if (layer.hasLayer(marker)) {
                    const ll = marker.getLatLng();
                    points.push([ll.lat, ll.lng]);
                }
            }
        };
        if (this.showRF) addVisible(this.rfMarkers, this.rfLayer);
        if (this.showIS) addVisible(this.isMarkers, this.isLayer);

        if (points.length > 1) {
            this._autoFitPending = true;
            this._runProgrammaticViewportChange(() => {
                this.map.fitBounds(L.latLngBounds(points).pad(0.1));
            });
            setTimeout(() => { this._autoFitPending = false; }, 500);
        }
    }

    // ── Station expiry (remove from map after N minutes) ───────

    expireStaleStations(expireMinutes) {
        if (!expireMinutes || expireMinutes <= 0) return;
        const cutoff = Date.now() / 1000 - expireMinutes * 60;
        const toRemove = [];
        for (const [call, meta] of Object.entries(this.stationMeta)) {
            if (meta.last_heard > 0 && meta.last_heard < cutoff) {
                toRemove.push({ call, source: meta.source });
            }
        }
        for (const { call, source } of toRemove) {
            this.removeStation(call, source);
            // Also remove from pvStations data
            window.pvStations?.removeStation(call, source);
        }
        if (toRemove.length > 0 && this.autoFit && !this._userInteracted) {
            this.autoFitNow();
        }
    }

    // ── UI state persistence (localStorage) ────────────────────

    _saveUIState() {
        const state = {
            showLines: this.showLines,
            showRF: this.showRF,
            showIS: this.showIS,
            showLabels: this.showLabels,
            autoFit: this.autoFit,
            darkMode: this.darkMode,
            lineTimeFilter: this.lineTimeFilter,
            zoom: this.map?.getZoom(),
            center: this.map ? [this.map.getCenter().lat, this.map.getCenter().lng] : null,
            typeFilters: this.typeFilters.size > 0 ? [...this.typeFilters] : [],
        };
        try { localStorage.setItem('pvMapUI', JSON.stringify(state)); } catch {}
    }

    _restoreUIState() {
        let state;
        try { state = JSON.parse(localStorage.getItem('pvMapUI')); } catch {}
        if (!state) return;

        // Restore toggles
        if (state.showLines === false) {
            this.showLines = false;
            this.map.removeLayer(this.lineLayer);
            const btn = document.getElementById('btn-toggle-lines');
            if (btn) btn.classList.remove('active');
        }
        if (state.showRF === false) {
            this.showRF = false;
            this.map.removeLayer(this.rfLayer);
            const btn = document.getElementById('btn-toggle-rf');
            if (btn) btn.classList.remove('active');
        }
        if (state.showIS === false) {
            this.showIS = false;
            this.map.removeLayer(this.isLayer);
            const btn = document.getElementById('btn-toggle-is');
            if (btn) btn.classList.remove('active');
        }

        // Restore dark/light theme
        if (state.darkMode === false) {
            this.darkMode = false;
            this.map.getContainer().classList.remove('dark-tiles');
            const btn = document.getElementById('btn-toggle-theme');
            if (btn) { btn.classList.remove('active'); btn.textContent = '☀️'; btn.title = 'Switch to dark map'; }
        }

        // Restore labels
        if (state.showLabels === true) {
            this.showLabels = true;
            const btn = document.getElementById('btn-toggle-labels');
            if (btn) btn.classList.add('active');
        }

        // Restore auto-fit
        if (state.autoFit === true) {
            this.autoFit = true;
            this._userInteracted = false;
            this._syncAutoFitButton();
        }

        // Restore line time filter
        if (state.lineTimeFilter !== undefined) {
            this.lineTimeFilter = state.lineTimeFilter;
            const sel = document.getElementById('line-time-filter');
            if (sel) sel.value = String(state.lineTimeFilter);
        }

        // Restore type filters
        if (state.typeFilters && state.typeFilters.length > 0) {
            this.typeFilters = new Set(state.typeFilters);
            // Sync checkboxes
            const container = document.getElementById('map-type-checkboxes');
            const allCb = document.getElementById('map-type-all');
            if (container && allCb) {
                container.querySelectorAll('input[type=checkbox]').forEach(cb => {
                    cb.checked = this.typeFilters.has(cb.dataset.cat);
                });
                this._syncTypeFilters(container, allCb);
            }
        }

        // Restore zoom and center (only if no auto-fit and no myPosition from server)
        if (state.zoom && state.center && !state.autoFit) {
            this._runProgrammaticViewportChange(() => {
                this.map.setView(state.center, state.zoom);
            });
        }
    }

    toggleLines() {
        this.showLines = !this.showLines;
        if (this.showLines) {
            this.map.addLayer(this.lineLayer);
        } else {
            this.map.removeLayer(this.lineLayer);
        }
        this._saveUIState();
        return this.showLines;
    }

    toggleRF() {
        this.showRF = !this.showRF;
        if (this.showRF) {
            this.map.addLayer(this.rfLayer);
        } else {
            this.map.removeLayer(this.rfLayer);
        }
        this._saveUIState();
        return this.showRF;
    }

    toggleIS() {
        this.showIS = !this.showIS;
        if (this.showIS) {
            this.map.addLayer(this.isLayer);
        } else {
            this.map.removeLayer(this.isLayer);
        }
        this._saveUIState();
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

        // Callsign label toggle
        document.getElementById('btn-toggle-labels')?.addEventListener('click', (e) => {
            const active = this.toggleLabels();
            e.target.classList.toggle('active', active);
        });

        // Auto-fit toggle
        document.getElementById('btn-toggle-autofit')?.addEventListener('click', (e) => {
            const active = this.toggleAutoFit();
            e.target.classList.toggle('active', active);
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
        this._saveUIState();
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
        this._legendEl = document.createElement('div');
        this._legendEl.className = 'map-legend';
        this._updateLegendContent();
        document.getElementById('map-panel').appendChild(this._legendEl);
    }

    _updateLegendContent() {
        if (!this._legendEl) return;
        const u = window.distLabel ? window.distLabel() : 'mi';
        const isMi = u === 'mi';
        const d50 = isMi ? '31' : '50';
        const d100l = isMi ? '31' : '50';
        const d100h = isMi ? '62' : '100';
        const d200l = isMi ? '62' : '100';
        const d200h = isMi ? '124' : '200';
        const d200p = isMi ? '124' : '200';
        this._legendEl.innerHTML = `
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
                <span>&lt; ${d50} ${u}</span>
            </div>
            <div class="legend-item">
                <div class="legend-line" style="background: #d29922;"></div>
                <span>${d100l}-${d100h} ${u}</span>
            </div>
            <div class="legend-item">
                <div class="legend-line" style="background: #3fb950;"></div>
                <span>${d200l}-${d200h} ${u}</span>
            </div>
            <div class="legend-item">
                <div class="legend-line" style="background: #bc8cff;"></div>
                <span>&gt; ${d200p} ${u} (DX)</span>
            </div>
            <div class="legend-unit-toggle">
                <button id="btn-dist-unit" title="Toggle miles / kilometers">${u.toUpperCase()} ↔ ${isMi ? 'KM' : 'MI'}</button>
            </div>
        `;
        // Wire toggle button
        this._legendEl.querySelector('#btn-dist-unit')?.addEventListener('click', () => {
            if (window.toggleDistUnit) window.toggleDistUnit();
        });
    }

    refreshLegend() {
        this._updateLegendContent();
    }

    setWeatherOverlayConfig(config) {
        this.weatherOverlayConfig = {
            ...this.weatherOverlayConfig,
            ...(config || {}),
        };
        this._applyWeatherOverlayConfig();
    }

    updateWeatherAlerts(alerts) {
        this.weatherAlerts = Array.isArray(alerts) ? alerts : [];
        this._renderWeatherAlertLayer();
    }

    _applyWeatherOverlayConfig() {
        this._renderWeatherAlertLayer();
        this._updateRadarOverlay();
    }

    _renderWeatherAlertLayer() {
        if (this.weatherAlertLayer) {
            this.weatherAlertLayer.remove();
            this.weatherAlertLayer = null;
        }

        const cfg = this.weatherOverlayConfig || {};
        if (!cfg.alert_overlay_enabled) return;

        const enabledGroups = new Set(cfg.alert_overlay_groups || []);
        const features = (this.weatherAlerts || [])
            .filter((alert) => alert?.geometry && this._alertMatchesOverlayGroups(alert, enabledGroups))
            .map((alert) => ({
                type: 'Feature',
                geometry: alert.geometry,
                properties: alert,
            }));

        if (!features.length) return;

        this.weatherAlertLayer = L.geoJSON(features, {
            pane: 'weatherAlertPane',
            style: (feature) => this._weatherAlertStyle(feature.properties),
            onEachFeature: (feature, layer) => {
                const alert = feature.properties || {};
                const expires = alert.expires ? new Date(alert.expires).toLocaleString() : 'Unknown';
                layer.bindPopup(`
                    <div class="popup-header">
                        <span class="popup-call popup-rf">${this._escapeHtml(alert.event || 'Weather Alert')}</span>
                    </div>
                    <table class="popup-table">
                        <tr><td class="popup-lbl">Type</td><td>${this._escapeHtml(alert.alert_type || '--')}</td></tr>
                        <tr><td class="popup-lbl">Severity</td><td>${this._escapeHtml(alert.severity || '--')}</td></tr>
                        <tr><td class="popup-lbl">Expires</td><td>${this._escapeHtml(expires)}</td></tr>
                    </table>
                    ${alert.headline ? `<div class="popup-detail">${this._escapeHtml(alert.headline)}</div>` : ''}
                `);
            },
        }).addTo(this.map);
    }

    _alertMatchesOverlayGroups(alert, enabledGroups) {
        const categories = Array.isArray(alert?.overlay_categories) ? alert.overlay_categories : [];
        if (!enabledGroups.size) return false;
        return categories.some((category) => enabledGroups.has(category));
    }

    _weatherAlertStyle(alert) {
        const warning = alert?.alert_type === 'warning';
        return {
            color: warning ? '#ff5a5f' : '#ffb347',
            weight: warning ? 2.5 : 2,
            opacity: 0.9,
            dashArray: warning ? null : '8 6',
            fillColor: warning ? '#ff5a5f' : '#ffb347',
            fillOpacity: warning ? 0.14 : 0.1,
        };
    }

    async _updateRadarOverlay() {
        const cfg = this.weatherOverlayConfig || {};
        if (!cfg.radar_enabled) {
            this._clearRadarOverlay();
            return;
        }
        if ((cfg.radar_provider || 'rainviewer') !== 'rainviewer') {
            this._clearRadarOverlay();
            return;
        }

        const frames = await this._getRadarFrames();
        if (!frames.length) {
            this._clearRadarOverlay();
            return;
        }

        const urls = frames.map((frame) => `${frame.host}${frame.path}/512/{z}/{x}/{y}/6/1_1.png`);
        const needsRebuild =
            this.radarFrames.length !== urls.length ||
            this.radarFrames.some((url, idx) => url !== urls[idx]);

        this.radarFrames = urls;
        if (needsRebuild) this._rebuildRadarLayers();
        this._applyRadarOpacity();
        this._startRadarAnimationIfNeeded();
    }

    async _getRadarFrames(force = false) {
        const cacheMs = 5 * 60 * 1000;
        if (!force && this.radarMetadata && (Date.now() - this.radarMetadataFetchedAt) < cacheMs) {
            return this.radarMetadata;
        }
        if (this.radarMetadataRequest) return this.radarMetadataRequest;

        this.radarMetadataRequest = fetch('https://api.rainviewer.com/public/weather-maps.json')
            .then((resp) => resp.json())
            .then((data) => {
                const host = data?.host;
                const frames = (data?.radar?.past || []).slice(-6).map((frame) => ({
                    host,
                    path: frame.path,
                    time: frame.time,
                }));
                this.radarMetadata = frames;
                this.radarMetadataFetchedAt = Date.now();
                return frames;
            })
            .catch((error) => {
                console.error('Radar metadata fetch failed:', error);
                this.radarMetadata = [];
                return [];
            })
            .finally(() => {
                this.radarMetadataRequest = null;
            });

        return this.radarMetadataRequest;
    }

    _rebuildRadarLayers() {
        const frameUrls = [...this.radarFrames];
        this._clearRadarOverlay(true);
        if (!frameUrls.length) return;

        this.radarFrames = frameUrls;
        this.radarTileLayers = frameUrls.map((url, idx) => {
            const layer = L.tileLayer(url, {
                pane: 'weatherRadarPane',
                opacity: 0,
                maxZoom: 19,
                maxNativeZoom: 7,
                updateWhenIdle: false,
                updateWhenZooming: false,
                className: 'weather-radar-tile-layer',
            }).addTo(this.map);
            layer.setOpacity(idx === this.radarFrames.length - 1 ? (this.weatherOverlayConfig.radar_opacity || 0.55) : 0);
            return layer;
        });
        this.radarFrameIndex = Math.max(0, this.radarTileLayers.length - 1);
    }

    _applyRadarOpacity() {
        const opacity = this.weatherOverlayConfig?.radar_opacity || 0.55;
        this.radarTileLayers.forEach((layer, idx) => {
            layer.setOpacity(idx === this.radarFrameIndex ? opacity : 0);
        });
    }

    _startRadarAnimationIfNeeded() {
        this._stopRadarAnimation();
        if (!this.radarTileLayers.length) return;

        this._applyRadarOpacity();

        if (!this.weatherOverlayConfig?.radar_animate || this.radarTileLayers.length < 2) return;

        this.radarAnimationTimer = setInterval(() => {
            const current = this.radarFrameIndex;
            const next = (current + 1) % this.radarTileLayers.length;
            const opacity = this.weatherOverlayConfig?.radar_opacity || 0.55;
            this.radarTileLayers[current]?.setOpacity(0);
            this.radarTileLayers[next]?.setOpacity(opacity);
            this.radarFrameIndex = next;
        }, 450);
    }

    _stopRadarAnimation() {
        if (this.radarAnimationTimer) {
            clearInterval(this.radarAnimationTimer);
            this.radarAnimationTimer = null;
        }
    }

    _clearRadarOverlay(preserveFrames = false) {
        this._stopRadarAnimation();
        this.radarTileLayers.forEach((layer) => layer.remove());
        this.radarTileLayers = [];
        if (!preserveFrames) {
            this.radarFrames = [];
        }
        this.radarFrameIndex = 0;
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
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
