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
        this.showDirectRFOnly = false;
        this.lineTimeFilter = 24; // hours, 0 = all time
        this.rfLayer = null;
        this.isLayer = null;
        this.lineLayer = null;
        this.spiderLayer = null;
        this.rangeCircles = null;
        this.observedRangeLayer = null;
        this.pickMode = false;
        this.objectMode = false;
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
        this.radarStaticLayer = null;
        this.radarFrameIndex = 0;
        this.radarAnimationTimer = null;
        this.radarMetadata = null;
        this.radarMetadataFetchedAt = 0;
        this.radarMetadataRequest = null;
        this.baseTileLayer = null;
        this.mapTileConfig = this._defaultTileConfig();
        this.myStationInfo = { symbol_table: '/', symbol_code: '#' };
        this.stationSymbolScale = 1;
        this.lineStyle = {
            colorMode: 'distance',
            customColor: '#58a6ff',
            weight: 2,
            pattern: 'solid',
            opacity: 0.7,
        };
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

        this._loadMapTileConfig();

        // Default to dark mode
        this.map.getContainer().classList.add('dark-tiles');

        // Create layer groups
        this.lineLayer = L.layerGroup().addTo(this.map);
        this.rfLayer = L.layerGroup().addTo(this.map);
        this.isLayer = L.layerGroup().addTo(this.map);
        this.spiderLayer = L.layerGroup().addTo(this.map);
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
        this.map.on('click zoomstart movestart', () => this._clearSpiderfiedStations());

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

    _defaultTileConfig() {
        return {
            map_tile_source: 'osm',
            map_tile_url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            map_tile_attribution: '&copy; OpenStreetMap contributors',
            map_tile_max_zoom: 19,
        };
    }

    _normalizeTileConfig(config) {
        const defaults = this._defaultTileConfig();
        const source = (config?.map_tile_source || defaults.map_tile_source).trim().toLowerCase();
        if (source === 'custom' && config?.map_tile_url) {
            return {
                map_tile_source: 'custom',
                map_tile_url: '/api/map-tiles/{z}/{x}/{y}',
                upstream_tile_url: config.map_tile_url,
                map_tile_attribution: config.map_tile_attribution || '',
                map_tile_max_zoom: parseInt(config.map_tile_max_zoom, 10) || defaults.map_tile_max_zoom,
            };
        }
        return {
            ...defaults,
            map_tile_url: '/api/map-tiles/{z}/{x}/{y}',
            upstream_tile_url: defaults.map_tile_url,
        };
    }

    async _loadMapTileConfig() {
        try {
            const cfg = window.pvConfigPromise
                ? await window.pvConfigPromise
                : await fetch('/api/config').then((resp) => resp.json());
            this.setMapTileConfig(cfg.web || {});
        } catch (e) {
            console.warn('Failed to load map tile config, using default OSM tiles:', e);
            this.setMapTileConfig(this._defaultTileConfig());
        }
    }

    setMapTileConfig(config) {
        if (!this.map) return;
        const next = this._normalizeTileConfig(config);
        const prev = this.mapTileConfig || {};
        if (
            this.baseTileLayer &&
            prev.map_tile_source === next.map_tile_source &&
            prev.upstream_tile_url === next.upstream_tile_url &&
            prev.map_tile_attribution === next.map_tile_attribution &&
            prev.map_tile_max_zoom === next.map_tile_max_zoom
        ) {
            return;
        }

        if (this.baseTileLayer) {
            this.map.removeLayer(this.baseTileLayer);
        }

        const options = {
            maxZoom: Math.min(22, Math.max(1, parseInt(next.map_tile_max_zoom, 10) || 19)),
            attribution: next.map_tile_attribution,
        };
        if (next.map_tile_url.includes('{s}')) {
            options.subdomains = next.map_tile_source === 'custom' ? 'abc' : 'abc';
        }

        this.baseTileLayer = L.tileLayer(next.map_tile_url, options).addTo(this.map);
        this.mapTileConfig = next;
    }

    _markerMetrics(isMine = false) {
        const scale = Math.max(0.65, Math.min(1.8, Number(this.stationSymbolScale) || 1));
        const box = Math.round((isMine ? 26 : 22) * scale);
        const sprite = Math.round((isMine ? 20 : 16) * scale);
        const font = Math.round((isMine ? 15 : 14) * scale);
        const icon = Math.max(18, box + 4);
        return { box, sprite, font, icon };
    }

    _markerStyle(isMine = false) {
        const m = this._markerMetrics(isMine);
        return `width:${m.box}px;height:${m.box}px;line-height:${m.box}px;font-size:${m.font}px;`;
    }

    _markerIconSize(isMine = false) {
        const m = this._markerMetrics(isMine);
        return [m.icon, m.icon];
    }

    _markerIconAnchor(isMine = false) {
        const m = this._markerMetrics(isMine);
        const center = Math.round(m.icon / 2);
        return [center, center];
    }

    setStationSymbolScale(scale, persist = true) {
        this.stationSymbolScale = Math.max(0.65, Math.min(1.8, Number(scale) || 1));
        this._syncSymbolSizeControls();
        if (this.myPosition) {
            this.setMyPosition(
                this.myPosition.lat,
                this.myPosition.lng,
                this.myCallsign,
                this.myStationInfo,
            );
        }
        Object.values(this.stationMeta || {}).forEach((meta) => {
            if (meta.station) this.addOrUpdateStation(meta.station);
        });
        this._applyLabelsToAll();
        if (persist) this._saveUIState();
    }

    setMyPosition(lat, lng, callsign, stationInfo = {}) {
        this.myPosition = { lat, lng };
        this.myCallsign = (callsign || '').toUpperCase();
        const symTable = stationInfo?.symbol_table || '/';
        const symCode = stationInfo?.symbol_code || '#';
        this.myStationInfo = { symbol_table: symTable, symbol_code: symCode };
        const markerSprite = (typeof getAPRSSpriteHTML === 'function')
            ? getAPRSSpriteHTML(symTable, symCode, this._markerMetrics(true).sprite)
            : 'MY';
        const popupSprite = (typeof getAPRSSpriteHTML === 'function')
            ? getAPRSSpriteHTML(symTable, symCode, 32)
            : '';
        const symName = (typeof getAPRSSymbolName === 'function')
            ? getAPRSSymbolName(symTable, symCode)
            : '';
        const icon = L.divIcon({
            className: 'aprs-icon-wrapper my-station-icon-wrapper',
            html: `<div class="aprs-emoji-marker aprs-emoji-my" style="${this._markerStyle(true)}">${markerSprite}</div>`,
            iconSize: this._markerIconSize(true),
            iconAnchor: this._markerIconAnchor(true),
            popupAnchor: [0, -this._markerIconAnchor(true)[1]],
        });
        const popup = `
            <div class="popup-header">
                ${popupSprite ? `<span class="popup-sym-inline">${popupSprite}</span>` : ''}
                <span class="popup-call" style="color: #39d5ff;">${this._escapeHtml(callsign || 'My Station')}</span>
            </div>
            <div class="popup-detail">
                ${lat.toFixed(4)}, ${lng.toFixed(4)}<br>
                ${this._escapeHtml(symName || 'My Station')}
            </div>
        `;

        if (this.myMarker) {
            this.myMarker.setLatLng([lat, lng]);
            this.myMarker.setIcon(icon);
            this.myMarker.setPopupContent(popup);
        } else {
            this.myMarker = L.marker([lat, lng], { icon, zIndexOffset: 1000 })
                .addTo(this.map)
                .bindPopup(popup);
        }
        this.refreshLegend();

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

    searchStation(query) {
        const needle = (query || '').trim().toUpperCase();
        if (!needle) return { found: false, message: 'Enter a callsign to search.' };

        const candidates = Object.keys(this.stationMeta);
        const exact = candidates.find(call => call.toUpperCase() === needle);
        const prefix = candidates.find(call => call.toUpperCase().startsWith(needle));
        const partial = candidates.find(call => call.toUpperCase().includes(needle));
        const call = exact || prefix || partial;
        if (!call) return { found: false, message: `Station ${needle} is not on the map.` };

        const meta = this.stationMeta[call];
        const markers = meta.source === 'rf' ? this.rfMarkers : this.isMarkers;
        const layer = meta.source === 'rf' ? this.rfLayer : this.isLayer;
        const marker = markers[call];
        if (!marker) return { found: false, message: `Station ${call} has no marker yet.` };
        if (layer && !layer.hasLayer(marker)) layer.addLayer(marker);

        const ll = marker.getLatLng();
        this._runProgrammaticViewportChange(() => {
            this.map.setView(ll, Math.max(this.map.getZoom(), 11), { animate: true });
        });
        marker.openPopup();
        this._saveUIState();
        return { found: true, callsign: call };
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
        const safeCall = this._escapeHtml(call);
        const lat = station.latitude;
        const lng = station.longitude;
        const dist = station.distance_km;
        const markers = source === 'rf' ? this.rfMarkers : this.isMarkers;
        const layer = source === 'rf' ? this.rfLayer : this.isLayer;

        // Build popup content
        const distStr = dist ? window.formatDist(dist) : 'N/A';
        const headingStr = this._formatBearing(station.heading);
        const timeStr = station.last_heard
            ? new Date(station.last_heard * 1000).toLocaleTimeString()
            : '';
        const countStr = station.packet_count || 1;
        const sourceLabel = source === 'rf' ? 'RF' : 'APRS-IS';
        const sourceClass = source === 'rf' ? 'popup-rf' : 'popup-is';
        const portName = source === 'rf' && station.last_port_name
            ? this._escapeHtml(station.last_port_name)
            : '';

        // Build icon from APRS symbol sprite sheet
        const symTable = station.symbol_table || '/';
        const symCode = station.symbol_code || '-';
        const emoji = (typeof getAPRSEmoji === 'function') ? getAPRSEmoji(symTable, symCode) : '📍';
        const symName = (typeof getAPRSSymbolName === 'function') ? getAPRSSymbolName(symTable, symCode) : '';
        const category = (typeof getAPRSCategory === 'function') ? getAPRSCategory(symTable, symCode) : 'other';
        const spriteHtml = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, 28) : emoji;

        const popupSprite = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, 32) : emoji;
        const aprsFiUrl = `https://aprs.fi/info/a/${encodeURIComponent(call || '')}`;

        // Determine direct-heard vs via-digi for RF stations
        const isDirect = source === 'rf' ? this._isDirectPath(station.last_path) : null;
        // Store metadata for type and path filtering
        this.stationMeta[call] = { source, symbol_table: symTable, symbol_code: symCode, category, last_heard: station.last_heard || 0, is_direct: isDirect, station: { ...station } };

        const heardViaHtml = isDirect === true
            ? '<span style="color:#3fb950;font-weight:600;">Direct</span>'
            : isDirect === false
                ? '<span style="color:#d29922;font-weight:600;">Via Digipeater</span>'
                : '';
        const weatherRows = this._weatherRowsHTML(station, category);
        const commentHtml = station.last_comment ? this._escapeHtml(station.last_comment) : '';
        const pathHtml = station.last_path ? this._escapeHtml(station.last_path) : '';

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
                <span class="popup-call ${sourceClass}">${safeCall}</span>
                <span class="popup-source-tag popup-tag-${source}">${sourceLabel}</span>
            </div>
            <table class="popup-table">
                <tr><td class="popup-lbl">Type</td><td>${this._escapeHtml(symName || 'Unknown')}</td></tr>
                <tr><td class="popup-lbl">Distance</td><td>${distStr}${headingStr ? ' · ' + headingStr : ''}</td></tr>
                <tr><td class="popup-lbl">Heard</td><td>${timeStr}${agoStr ? ' (' + agoStr + ')' : ''}</td></tr>
                <tr><td class="popup-lbl">Packets</td><td>${countStr}</td></tr>
                ${portName ? `<tr><td class="popup-lbl">Port</td><td>${portName}</td></tr>` : ''}
                ${weatherRows}
                ${commentHtml && !weatherRows ? `<tr><td class="popup-lbl">Comment</td><td>${commentHtml}</td></tr>` : ''}
                ${pathHtml ? `<tr><td class="popup-lbl">Path</td><td class="popup-path">${pathHtml}</td></tr>` : ''}
                ${heardViaHtml ? `<tr><td class="popup-lbl">Via</td><td>${heardViaHtml}</td></tr>` : ''}
                <tr><td class="popup-lbl">Position</td><td>${lat.toFixed(4)}, ${lng.toFixed(4)}</td></tr>
            </table>
            <div class="popup-actions">
                <button type="button" class="popup-action-btn" onclick="window.pvMessages?.startNewMessage?.('${safeCall}')">Send Message</button>
                <a class="popup-action-btn" href="${aprsFiUrl}" target="_blank" rel="noopener noreferrer">aprs.fi</a>
            </div>
        `;

        const borderColor = source === 'rf' ? '#f85149' : '#58a6ff';
        const markerSprite = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(symTable, symCode, this._markerMetrics(false).sprite) : emoji;

        const iconHtml = `<div class="aprs-emoji-marker aprs-emoji-${source}" style="border-color:${borderColor};${this._markerStyle(false)}">${markerSprite}</div>`;
        const aprsIcon = L.divIcon({
            className: 'aprs-icon-wrapper',
            html: iconHtml,
            iconSize: this._markerIconSize(false),
            iconAnchor: this._markerIconAnchor(false),
            popupAnchor: [0, -this._markerIconAnchor(false)[1]],
        });

        if (markers[call]) {
            // Update existing marker
            markers[call].setLatLng([lat, lng]).setPopupContent(popup);
            markers[call].setIcon(aprsIcon);
        } else {
            markers[call] = L.marker([lat, lng], { icon: aprsIcon })
                .bindPopup(popup)
                .bindTooltip(safeCall, {
                    permanent: true,
                    direction: 'top',
                    offset: [0, -14],
                    className: 'callsign-label',
                })
                .addTo(layer);
            markers[call].on('click', (e) => this._handleStationMarkerClick(call, source, e));
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
        this._refreshLinesUsingStation(call);

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

        if (source === 'rf') {
            this._clearLineVisuals(callsign);
            delete this.rfLineData[callsign];
        }

        delete this.stationMeta[callsign];
    }

    removeRfMapMarker(callsign) {
        if (this.rfMarkers[callsign]) {
            this.rfLayer.removeLayer(this.rfMarkers[callsign]);
            delete this.rfMarkers[callsign];
        }
        this._clearLineVisuals(callsign);
        delete this.rfLineData[callsign];
    }

    _handleStationMarkerClick(callsign, source, event) {
        const marker = this._markerForStation(callsign, source);
        if (!marker || !this.map) return;
        const stack = this._overlappingStationMarkers(marker);
        if (stack.length <= 1) {
            this._clearSpiderfiedStations();
            return;
        }

        if (event?.originalEvent) L.DomEvent.stop(event.originalEvent);
        marker.closePopup();
        this.map.closePopup();
        this._showSpiderfiedStations(stack, marker.getLatLng());
    }

    _markerForStation(callsign, source) {
        const markers = source === 'rf' ? this.rfMarkers : this.isMarkers;
        return markers?.[callsign] || null;
    }

    _overlappingStationMarkers(marker) {
        const center = this.map.latLngToLayerPoint(marker.getLatLng());
        const threshold = Math.max(24, Math.round(this._markerMetrics(false).icon * 0.95));
        const records = [];
        for (const [callsign, meta] of Object.entries(this.stationMeta || {})) {
            const candidate = this._markerForStation(callsign, meta.source);
            const layer = meta.source === 'rf' ? this.rfLayer : this.isLayer;
            if (!candidate || !layer?.hasLayer(candidate)) continue;
            const point = this.map.latLngToLayerPoint(candidate.getLatLng());
            if (center.distanceTo(point) <= threshold) {
                records.push({ callsign, source: meta.source, marker: candidate, meta });
            }
        }
        records.sort((a, b) => {
            const heardA = Number(a.meta?.last_heard || 0);
            const heardB = Number(b.meta?.last_heard || 0);
            if (heardA !== heardB) return heardB - heardA;
            return String(a.callsign).localeCompare(String(b.callsign));
        });
        return records;
    }

    _showSpiderfiedStations(records, centerLatLng) {
        this._clearSpiderfiedStations();
        if (!this.spiderLayer || !records.length) return;

        const centerPoint = this.map.latLngToLayerPoint(centerLatLng);
        const radius = Math.max(34, Math.min(58, 26 + records.length * 3));
        const startAngle = -Math.PI / 2;
        records.forEach((record, index) => {
            const angle = startAngle + (Math.PI * 2 * index / records.length);
            const point = L.point(
                centerPoint.x + Math.cos(angle) * radius,
                centerPoint.y + Math.sin(angle) * radius,
            );
            const latLng = this.map.layerPointToLatLng(point);
            const leg = L.polyline([centerLatLng, latLng], {
                color: record.source === 'rf' ? '#f85149' : '#58a6ff',
                weight: 1.5,
                opacity: 0.75,
                interactive: false,
                dashArray: '3 4',
            }).addTo(this.spiderLayer);
            const pickMarker = L.marker(latLng, {
                icon: record.marker.options.icon,
                zIndexOffset: 2500,
                riseOnHover: true,
            })
                .bindTooltip(this._escapeHtml(record.callsign), {
                    permanent: true,
                    direction: 'top',
                    offset: [0, -14],
                    className: 'callsign-label spider-callsign-label',
                })
                .addTo(this.spiderLayer);
            pickMarker.on('click', (clickEvent) => {
                if (clickEvent?.originalEvent) L.DomEvent.stop(clickEvent.originalEvent);
                this._clearSpiderfiedStations();
                record.marker.openPopup();
            });
            leg.bringToBack?.();
            setTimeout(() => pickMarker.getElement?.()?.classList.add('spider-station-marker'), 0);
        });
    }

    _clearSpiderfiedStations() {
        if (this.spiderLayer) this.spiderLayer.clearLayers();
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
     * Parse a digipeater path string to extract real used digipeater callsigns
     * (skipping WIDE/RELAY/TRACE/TCPIP/qA aliases and own callsign).
     */
    _parseDigiPath(path) {
        if (!path) return [];
        const aliasRe = /^(WIDE|RELAY|TRACE|TCPIP|qA[A-Z])\d?/i;
        const digis = [];
        for (const part of path.split(',')) {
            const hop = part.trim();
            if (!hop.endsWith('*')) continue;
            const call = hop.replace(/\*$/, '');
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
            path: path || '',
        };

        // Build multi-hop points: origin station → digis → my station
        const myPos = [this.myPosition.lat, this.myPosition.lng];
        const stationPos = [lat, lng];
        const digis = this._parseDigiPath(path);
        const points = [stationPos];
        const hopPositions = [];
        const missingDigis = [];

        for (const digi of digis) {
            const pos = this._getStationPosition(digi);
            if (pos) {
                points.push(pos);
                hopPositions.push({ call: digi, pos });
            } else {
                missingDigis.push(digi);
            }
        }
        if (missingDigis.length > 0) {
            this._clearLineVisuals(callsign);
            return;
        }
        points.push(myPos);

        const lineOptions = this._lineOptionsForDistance(distance);
        const { color, weight, opacity } = lineOptions;

        if (this.rfLines[callsign]) {
            this.rfLines[callsign].setLatLngs(points);
            this.rfLines[callsign].setStyle(lineOptions);
        } else {
            this.rfLines[callsign] = L.polyline(points, lineOptions).addTo(this.lineLayer);
        }

        // Update arrowhead markers
        if (this.rfArrows[callsign]) {
            this.rfArrows[callsign].forEach(m => this.lineLayer.removeLayer(m));
        }
        this.rfArrows[callsign] = this._createArrowheads(points, color, opacity, weight);

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

    _clearLineVisuals(callsign) {
        if (this.rfLines[callsign]) {
            this.lineLayer.removeLayer(this.rfLines[callsign]);
            delete this.rfLines[callsign];
        }
        if (this.rfArrows[callsign]) {
            this.rfArrows[callsign].forEach(m => this.lineLayer.removeLayer(m));
            delete this.rfArrows[callsign];
        }
        if (this.hopMarkers[callsign]) {
            this.hopMarkers[callsign].forEach(m => this.lineLayer.removeLayer(m));
            delete this.hopMarkers[callsign];
        }
    }

    _refreshLinesUsingStation(callsign) {
        const normalized = (callsign || '').toUpperCase();
        if (!normalized) return;
        Object.entries(this.rfLineData).forEach(([lineCall, data]) => {
            if (!data || lineCall.toUpperCase() === normalized) return;
            const digis = this._parseDigiPath(data.path || '').map(call => call.toUpperCase());
            if (!digis.includes(normalized)) return;
            this._updateLine(
                lineCall,
                data.lat,
                data.lng,
                data.distance_km,
                data.last_heard,
                data.path || '',
            );
        });
    }

    _distanceLineColor(distance) {
        if (!distance) return '#f85149';
        if (distance > 200) return '#bc8cff';
        if (distance > 100) return '#3fb950';
        if (distance > 50) return '#d29922';
        return '#f85149';
    }

    _lineOptionsForDistance(distance) {
        const style = this.lineStyle || {};
        const weight = Math.max(1, Math.min(8, parseFloat(style.weight) || 2));
        const opacity = Math.max(0.2, Math.min(1, parseFloat(style.opacity) || 0.7));
        const color = style.colorMode === 'custom'
            ? (style.customColor || '#58a6ff')
            : this._distanceLineColor(distance);
        const dashArray = this._lineDashArray(style.pattern, weight);
        return {
            color,
            weight,
            opacity,
            dashArray,
            lineCap: style.pattern === 'dot' ? 'round' : 'butt',
            lineJoin: 'round',
        };
    }

    _lineDashArray(pattern, weight) {
        const w = Math.max(1, parseFloat(weight) || 2);
        switch (pattern) {
            case 'dash':
                return `${w * 4} ${w * 2.5}`;
            case 'dot':
                return `1 ${w * 2.4}`;
            case 'dashdot':
                return `${w * 4} ${w * 2} 1 ${w * 2}`;
            case 'solid':
            default:
                return null;
        }
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
                const call = hop.slice(0, -1);
                if (!aliasRe.test(call)) return false;
            }
        }
        return true;
    }

    _formatBearing(heading) {
        if (heading == null || Number.isNaN(Number(heading))) return '';
        const sectors = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        const normalized = ((Number(heading) % 360) + 360) % 360;
        return sectors[Math.floor((normalized + 22.5) / 45) % 8];
    }

    refreshOpenPopups() {
        for (const [call, meta] of Object.entries(this.stationMeta || {})) {
            const markers = meta.source === 'rf' ? this.rfMarkers : this.isMarkers;
            const marker = markers[call];
            if (marker?.isPopupOpen?.() && meta.station) {
                this.addOrUpdateStation(meta.station);
                marker.openPopup();
            }
        }
    }

    _weatherRowsHTML(station, category) {
        const symCode = station.symbol_code || '';
        const isWeather = category === 'weather' || symCode === '_' || station.packet_type === 'weather';
        if (!isWeather) return '';

        const wx = this._parseWeatherTelemetry(station.last_comment || station.last_raw || '');
        if (!wx) return '';

        const rows = [];
        if (wx.temp_f !== undefined) rows.push(['Temp', window.formatTempF ? window.formatTempF(wx.temp_f) : `${wx.temp_f}&deg;F`]);
        if (wx.wind_mph !== undefined) {
            const dir = wx.wind_dir_deg !== undefined ? `${wx.wind_dir_deg}&deg; ` : '';
            rows.push(['Wind', `${dir}${window.formatWindMph ? window.formatWindMph(wx.wind_mph) : `${wx.wind_mph} mph`}`]);
        }
        if (wx.gust_mph !== undefined) rows.push(['Gust', window.formatWindMph ? window.formatWindMph(wx.gust_mph) : `${wx.gust_mph} mph`]);
        if (wx.humidity !== undefined) rows.push(['Humidity', `${wx.humidity}%`]);
        if (wx.pressure_mb !== undefined) rows.push(['Pressure', `${wx.pressure_mb.toFixed(1)} mb`]);
        if (wx.rain_1h_in !== undefined) rows.push(['Rain 1h', window.formatRainIn ? window.formatRainIn(wx.rain_1h_in) : `${wx.rain_1h_in.toFixed(2)} in`]);
        if (wx.rain_24h_in !== undefined) rows.push(['Rain 24h', window.formatRainIn ? window.formatRainIn(wx.rain_24h_in) : `${wx.rain_24h_in.toFixed(2)} in`]);
        if (wx.rain_midnight_in !== undefined) rows.push(['Rain Today', window.formatRainIn ? window.formatRainIn(wx.rain_midnight_in) : `${wx.rain_midnight_in.toFixed(2)} in`]);
        if (wx.luminosity !== undefined) rows.push(['Luminosity', `${wx.luminosity}`]);
        if (wx.snow_24h_in !== undefined) rows.push(['Snow 24h', window.formatRainIn ? window.formatRainIn(wx.snow_24h_in, 1) : `${wx.snow_24h_in.toFixed(1)} in`]);

        if (!rows.length) return '';
        return rows
            .map(([label, value]) => `<tr class="popup-weather-row"><td class="popup-lbl">${label}</td><td>${value}</td></tr>`)
            .join('');
    }

    _parseWeatherTelemetry(text) {
        if (!text) return null;
        const raw = String(text);
        const wx = {};
        const read = (token, width) => {
            const match = raw.match(new RegExp(`${token}(-?\\d{${width}})`));
            return match ? parseInt(match[1], 10) : undefined;
        };

        const windDir = read('c', 3);
        if (windDir !== undefined && windDir <= 360) wx.wind_dir_deg = windDir;
        const wind = read('s', 3);
        if (wind !== undefined) wx.wind_mph = wind;
        const slashWind = raw.match(/^(\d{3})\/(\d{3})/);
        if (slashWind) {
            const dir = parseInt(slashWind[1], 10);
            if (dir <= 360) wx.wind_dir_deg = dir;
            wx.wind_mph = parseInt(slashWind[2], 10);
        }
        const gust = read('g', 3);
        if (gust !== undefined) wx.gust_mph = gust;
        const temp = read('t', 3);
        if (temp !== undefined) wx.temp_f = temp;
        const rain1h = read('r', 3);
        if (rain1h !== undefined) wx.rain_1h_in = rain1h / 100;
        const rain24h = read('p', 3);
        if (rain24h !== undefined) wx.rain_24h_in = rain24h / 100;
        const rainMidnight = read('P', 3);
        if (rainMidnight !== undefined) wx.rain_midnight_in = rainMidnight / 100;
        const humidity = read('h', 2);
        if (humidity !== undefined) wx.humidity = humidity === 0 ? 100 : humidity;
        const pressure = read('b', 5);
        if (pressure !== undefined) wx.pressure_mb = pressure / 10;
        const luminosity = read('L', 3) ?? read('l', 3);
        if (luminosity !== undefined) wx.luminosity = luminosity;
        const snow = read('S', 3) ?? read('s', 3);
        if (snow !== undefined && raw.includes('S')) wx.snow_24h_in = snow / 10;

        return Object.keys(wx).length ? wx : null;
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
     * Places arrows off-center so reverse-direction paths do not overlap.
     */
    _createArrowheads(points, color, opacity, lineWeight = 2) {
        const arrows = [];
        for (let i = 0; i < points.length - 1; i++) {
            const from = L.latLng(points[i]);
            const to = L.latLng(points[i + 1]);
            const angle = this._bearing(from, to);
            const fraction = this._arrowFractionForSegment(from, to);
            const pos = L.latLng(
                from.lat + (to.lat - from.lat) * fraction,
                from.lng + (to.lng - from.lng) * fraction
            );
            const arrowWidth = Math.max(10, Math.min(18, lineWeight * 4 + 4));
            const arrowHeight = Math.max(9, Math.min(16, lineWeight * 4 + 3));
            const arrowIcon = L.divIcon({
                className: 'arrow-icon',
                html: `<div style="
                    width: 0; height: 0;
                    border-left: ${arrowWidth / 2}px solid transparent;
                    border-right: ${arrowWidth / 2}px solid transparent;
                    border-bottom: ${arrowHeight}px solid ${color};
                    opacity: ${opacity};
                    transform: rotate(${angle}deg);
                    transform-origin: center center;
                "></div>`,
                iconSize: [arrowWidth, arrowHeight],
                iconAnchor: [arrowWidth / 2, arrowHeight / 2],
            });
            arrows.push(
                L.marker(pos, { icon: arrowIcon, interactive: false }).addTo(this.lineLayer)
            );
        }
        return arrows;
    }

    _arrowFractionForSegment(from, to) {
        const fromKey = `${from.lat.toFixed(4)},${from.lng.toFixed(4)}`;
        const toKey = `${to.lat.toFixed(4)},${to.lng.toFixed(4)}`;
        return fromKey < toKey ? 0.42 : 0.58;
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

    setLineStyle(nextStyle = {}) {
        const current = this.lineStyle || {};
        const colorMode = nextStyle.colorMode || current.colorMode || 'distance';
        const pattern = nextStyle.pattern || current.pattern || 'solid';
        this.lineStyle = {
            colorMode: colorMode === 'custom' ? 'custom' : 'distance',
            customColor: /^#[0-9a-f]{6}$/i.test(nextStyle.customColor || '')
                ? nextStyle.customColor
                : (current.customColor || '#58a6ff'),
            weight: Math.max(1, Math.min(8, parseFloat(nextStyle.weight ?? current.weight) || 2)),
            pattern: ['solid', 'dash', 'dot', 'dashdot'].includes(pattern) ? pattern : 'solid',
            opacity: Math.max(0.2, Math.min(1, parseFloat(nextStyle.opacity ?? current.opacity) || 0.7)),
        };
        this._syncLineStyleControls();
        this._redrawAllLines();
        this._saveUIState();
    }

    _redrawAllLines() {
        Object.entries(this.rfLineData).forEach(([callsign, data]) => {
            if (!data) return;
            this._updateLine(
                callsign,
                data.lat,
                data.lng,
                data.distance_km,
                data.last_heard,
                data.path || '',
            );
        });
    }

    /**
     * Apply time filter to a single line by callsign.
     */
    _applyLineTimeFilter(callsign) {
        const line = this.rfLines[callsign];
        const data = this.rfLineData[callsign];
        if (!line || !data) return;
        const meta = this.stationMeta[callsign];

        const hops = this.hopMarkers[callsign] || [];
        const arrows = this.rfArrows[callsign] || [];
        let visible = true;

        if (this.lineTimeFilter !== 0) {
            const now = Date.now() / 1000;
            const cutoff = now - (this.lineTimeFilter * 3600);
            visible = data.last_heard >= cutoff;
        }
        if (meta && !this._stationPassesMapFilters(meta)) {
            visible = false;
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

        const visible = this._stationPassesMapFilters(meta);

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

    _stationPassesMapFilters(meta) {
        const typeVisible = this.typeFilters.size === 0 || this.typeFilters.has(meta.category);
        const pathVisible = !this.showDirectRFOnly
            || (meta.source === 'rf' && meta.is_direct !== false);
        return typeVisible && pathVisible;
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
            showDirectRFOnly: this.showDirectRFOnly,
            showLabels: this.showLabels,
            autoFit: this.autoFit,
            darkMode: this.darkMode,
            lineTimeFilter: this.lineTimeFilter,
            stationSymbolScale: this.stationSymbolScale,
            lineStyle: this.lineStyle,
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
        if (state.showDirectRFOnly === true) {
            this.showDirectRFOnly = true;
            const btn = document.getElementById('btn-toggle-direct-rf');
            if (btn) btn.classList.add('active');
            this.applyAllTypeFilters();
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

        if (state.stationSymbolScale !== undefined) {
            this.stationSymbolScale = Math.max(0.65, Math.min(1.8, Number(state.stationSymbolScale) || 1));
        }
        this._syncSymbolSizeControls();

        if (state.lineStyle) {
            const savedStyle = state.lineStyle || {};
            const pattern = savedStyle.pattern || 'solid';
            this.lineStyle = {
                colorMode: savedStyle.colorMode === 'custom' ? 'custom' : 'distance',
                customColor: /^#[0-9a-f]{6}$/i.test(savedStyle.customColor || '')
                    ? savedStyle.customColor
                    : '#58a6ff',
                weight: Math.max(1, Math.min(8, parseFloat(savedStyle.weight) || 2)),
                pattern: ['solid', 'dash', 'dot', 'dashdot'].includes(pattern) ? pattern : 'solid',
                opacity: Math.max(0.2, Math.min(1, parseFloat(savedStyle.opacity) || 0.7)),
            };
        }
        this._syncLineStyleControls();

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

    toggleDirectRFOnly() {
        this.showDirectRFOnly = !this.showDirectRFOnly;
        this.applyAllTypeFilters();
        this._saveUIState();
        return this.showDirectRFOnly;
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

        document.getElementById('btn-toggle-direct-rf')?.addEventListener('click', (e) => {
            const active = this.toggleDirectRFOnly();
            e.target.classList.toggle('active', active);
        });

        document.getElementById('line-time-filter')?.addEventListener('change', (e) => {
            const hours = parseInt(e.target.value, 10);
            this.setLineTimeFilter(hours);
        });

        this._initLineStyleControls();
        this._initSymbolSizeControls();

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

        document.getElementById('btn-cache-map')?.addEventListener('click', (e) => {
            this.cacheCurrentView(e.currentTarget);
        });

        // Station type filter — multi-select checkboxes
        this._initTypeFilterCheckboxes();

        document.getElementById('btn-pick-location')?.addEventListener('click', (e) => {
            this.togglePickMode();
            e.target.classList.toggle('active', this.pickMode);
        });

        document.getElementById('btn-pick-location-settings')?.addEventListener('click', () => {
            if (typeof window.pvCloseSettingsPane === 'function') {
                window.pvCloseSettingsPane();
            }
            this.enablePickMode();
        });

        document.getElementById('btn-create-object')?.addEventListener('click', (e) => {
            this.enableObjectMode();
            e.target.classList.add('active');
        });

        document.getElementById('btn-toggle-theme')?.addEventListener('click', (e) => {
            const dark = this.toggleTheme();
            e.target.classList.toggle('active', dark);
            e.target.textContent = dark ? '🌙' : '☀️';
            e.target.title = dark ? 'Switch to light map' : 'Switch to dark map';
        });
    }

    _initLineStyleControls() {
        const btn = document.getElementById('line-style-btn');
        const popover = document.getElementById('line-style-popover');
        const colorMode = document.getElementById('line-color-mode');
        const customColor = document.getElementById('line-custom-color');
        const weight = document.getElementById('line-weight');
        const pattern = document.getElementById('line-pattern');
        const opacity = document.getElementById('line-opacity');
        if (!btn || !popover) return;

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            popover.classList.toggle('open');
        });
        document.addEventListener('click', (e) => {
            if (!popover.contains(e.target) && e.target !== btn) {
                popover.classList.remove('open');
            }
        });

        const update = () => this.setLineStyle({
            colorMode: colorMode?.value,
            customColor: customColor?.value,
            weight: weight?.value,
            pattern: pattern?.value,
            opacity: opacity?.value,
        });

        [colorMode, customColor, weight, pattern, opacity].forEach((el) => {
            el?.addEventListener('input', update);
            el?.addEventListener('change', update);
        });
        this._syncLineStyleControls();
    }

    _syncLineStyleControls() {
        const style = this.lineStyle || {};
        const setValue = (id, value) => {
            const el = document.getElementById(id);
            if (el && el.value !== String(value)) el.value = String(value);
        };
        setValue('line-color-mode', style.colorMode || 'distance');
        setValue('line-custom-color', style.customColor || '#58a6ff');
        setValue('line-weight', style.weight || 2);
        setValue('line-pattern', style.pattern || 'solid');
        setValue('line-opacity', style.opacity || 0.7);
        const customColor = document.getElementById('line-custom-color');
        if (customColor) customColor.disabled = style.colorMode !== 'custom';
    }

    _initSymbolSizeControls() {
        const btn = document.getElementById('symbol-size-btn');
        const popover = document.getElementById('symbol-size-popover');
        const slider = document.getElementById('station-symbol-size');
        if (!btn || !popover || !slider) return;

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            popover.classList.toggle('open');
        });
        document.addEventListener('click', (e) => {
            if (!popover.contains(e.target) && e.target !== btn) {
                popover.classList.remove('open');
            }
        });
        slider.addEventListener('input', () => this.setStationSymbolScale(slider.value));
        slider.addEventListener('change', () => this.setStationSymbolScale(slider.value));
        this._syncSymbolSizeControls();
    }

    _syncSymbolSizeControls() {
        const slider = document.getElementById('station-symbol-size');
        const value = document.getElementById('station-symbol-size-value');
        const percent = Math.round((Number(this.stationSymbolScale) || 1) * 100);
        if (slider && slider.value !== String(this.stationSymbolScale)) {
            slider.value = String(this.stationSymbolScale);
        }
        if (value) value.textContent = `${percent}%`;
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

    async cacheCurrentView(button) {
        if (!this.map) return;
        const bounds = this.map.getBounds();
        const zoom = this.map.getZoom();
        const btn = button || document.getElementById('btn-cache-map');
        const original = btn?.textContent || 'Cache';
        if (btn) {
            btn.disabled = true;
            btn.textContent = '...';
            btn.title = 'Caching visible map tiles';
        }
        try {
            const resp = await fetch('/api/map-tiles/cache-current-view', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    zoom,
                    min_zoom: zoom,
                    max_zoom: zoom,
                    bounds: {
                        north: bounds.getNorth(),
                        south: bounds.getSouth(),
                        east: bounds.getEast(),
                        west: bounds.getWest(),
                    },
                }),
            });
            const result = await resp.json();
            if (!resp.ok || !result.success) {
                throw new Error(result.message || 'Tile cache failed.');
            }
            if (btn) {
                btn.textContent = 'Done';
                btn.title = `Cached ${result.downloaded + result.cached}/${result.requested} visible tiles`;
            }
            setTimeout(() => {
                if (btn) {
                    btn.textContent = original;
                    btn.title = 'Cache visible map tiles for offline use';
                }
            }, 2500);
        } catch (error) {
            console.error('Map tile cache failed:', error);
            if (btn) {
                btn.textContent = 'Fail';
                btn.title = error.message || 'Tile cache failed';
            }
            setTimeout(() => {
                if (btn) {
                    btn.textContent = original;
                    btn.title = 'Cache visible map tiles for offline use';
                }
            }, 3500);
        } finally {
            if (btn) btn.disabled = false;
        }
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
            const { lat, lng } = this._normalizeLatLng(e.latlng);
            this._placePickMarker(lat, lng);

            // Fill settings fields
            const latEl = document.getElementById('cfg-latitude');
            const lngEl = document.getElementById('cfg-longitude');
            if (latEl) latEl.value = lat.toFixed(4);
            if (lngEl) lngEl.value = lng.toFixed(4);
            latEl?.dispatchEvent(new Event('input', { bubbles: true }));
            lngEl?.dispatchEvent(new Event('input', { bubbles: true }));

            // Fire callback if set
            if (this.onLocationPicked) {
                this.onLocationPicked(lat, lng);
            }

            setTimeout(() => {
                if (typeof window.pvActivateTab === 'function') {
                    window.pvActivateTab('tab-settings');
                }
                if (typeof window.pvMarkSettingsDirty === 'function') {
                    window.pvMarkSettingsDirty('Station coordinates picked from map. Save Configuration to keep this location.');
                }
            }, 250);
            this.disablePickMode();
        };
        this.map.once('click', this._pickHandler);
    }

    _normalizeLatLng(latlng) {
        const lat = Math.max(-90, Math.min(90, Number(latlng?.lat) || 0));
        let lng = Number(latlng?.lng) || 0;
        lng = ((lng + 180) % 360 + 360) % 360 - 180;
        return { lat, lng };
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
            this.pickMarker.setPopupContent(this._pickPopupHTML(lat, lng));
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
                .bindPopup(this._pickPopupHTML(lat, lng));
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

    enableObjectMode() {
        this.objectMode = true;
        this.map.getContainer().style.cursor = 'crosshair';
        let banner = document.getElementById('pick-mode-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'pick-mode-banner';
            document.getElementById('map-panel').appendChild(banner);
        }
        banner.innerHTML = 'Click on the map to create an APRS object <button id="pick-mode-cancel">Cancel</button>';
        banner.style.display = 'flex';
        document.getElementById('pick-mode-cancel')?.addEventListener('click', () => this.disableObjectMode());

        this._objectHandler = (e) => {
            const { lat, lng } = e.latlng;
            this.disableObjectMode();
            this._showObjectCreatePopup(lat, lng);
        };
        this.map.once('click', this._objectHandler);
    }

    disableObjectMode() {
        this.objectMode = false;
        this.map.getContainer().style.cursor = '';
        document.getElementById('btn-create-object')?.classList.remove('active');
        const banner = document.getElementById('pick-mode-banner');
        if (banner) banner.style.display = 'none';
        if (this._objectHandler) {
            this.map.off('click', this._objectHandler);
            this._objectHandler = null;
        }
    }

    _showObjectCreatePopup(lat, lng) {
        const symbolOptions = this._objectSymbolOptionsHTML('/', 'r');
        const mapSize = this.map?.getSize?.();
        const controlsHeight = document.getElementById('map-controls')?.offsetHeight || 0;
        const wxBannerHeight = document.getElementById('wx-banner')?.offsetHeight || 0;
        const alertHeight = document.getElementById('wx-alerts-container')?.offsetHeight || 0;
        const reservedBottom = controlsHeight + 28;
        const reservedTop = wxBannerHeight + alertHeight + 36;
        const availableMapHeight = (mapSize?.y || window.innerHeight || 720) - reservedTop - reservedBottom;
        const popupMaxHeight = Math.max(180, Math.min(520, availableMapHeight));
        const popupMaxWidth = Math.max(300, Math.min(430, (mapSize?.x || window.innerWidth || 480) - 40));
        const popup = L.popup({
            autoPan: true,
            autoPanPaddingTopLeft: [20, reservedTop],
            autoPanPaddingBottomRight: [20, reservedBottom],
            className: 'object-create-leaflet-popup',
            keepInView: true,
            maxWidth: popupMaxWidth,
            minWidth: Math.min(320, popupMaxWidth),
        })
            .setLatLng([lat, lng])
            .setContent(`
                <div class="object-create-popup" style="--object-popup-max-height:${popupMaxHeight}px;">
                    <div class="popup-header object-popup-header"><span class="popup-call">Create Object</span></div>
                    <div class="object-popup-scroll">
                        <div class="object-popup-grid">
                            <label>Name <input id="obj-create-name" maxlength="9" placeholder="NETCTRL"></label>
                            <label>Scope
                                <select id="obj-create-scope">
                                    <option value="global">Global</option>
                                    <option value="local">Local RF only</option>
                                    <option value="private">Private</option>
                                </select>
                            </label>
                            <label class="object-popup-check"><input id="obj-create-enabled" type="checkbox" checked> Enabled</label>
                            <label class="object-popup-check"><input id="obj-create-active" type="checkbox" checked> Active/live</label>
                            <label class="object-popup-check"><input id="obj-create-permanent" type="checkbox"> Permanent item</label>
                            <label>Transmit
                                <select id="obj-create-mode">
                                    <option value="">Use object setting</option>
                                    <option value="both">RF + APRS-IS</option>
                                    <option value="rf">RF only</option>
                                    <option value="aprs_is">APRS-IS only</option>
                                </select>
                            </label>
                            <label>Table
                                <select id="obj-create-table">
                                    <option value="/">Primary /</option>
                                    <option value="\\">Alternate \\</option>
                                </select>
                            </label>
                            <label>Symbol
                                <select id="obj-create-symbol">${symbolOptions}</select>
                            </label>
                            <label>Overlay <input id="obj-create-overlay" maxlength="1" placeholder="A"></label>
                            <label>Speed mph <input id="obj-create-speed" type="number" min="0" max="999" value="0"></label>
                            <label>Course <input id="obj-create-course" type="number" min="0" max="359" value="0"></label>
                            <label>Frequency <input id="obj-create-frequency" maxlength="12" placeholder="146.520"></label>
                            <label>Tone <input id="obj-create-tone" maxlength="8" placeholder="100.0"></label>
                            <label>Duplex <input id="obj-create-duplex" maxlength="3" placeholder="+"></label>
                            <label>QRU <input id="obj-create-qru" maxlength="12" placeholder="CLUB"></label>
                            <label>Path <input id="obj-create-path" maxlength="40" placeholder="Use global path"></label>
                        </div>
                        <input id="obj-create-comment" maxlength="80" placeholder="Comment">
                        <div class="object-symbol-preview" id="obj-create-preview"></div>
                        <div class="popup-detail">${lat.toFixed(5)}, ${lng.toFixed(5)}</div>
                    </div>
                    <div class="popup-actions object-popup-actions">
                        <button type="button" class="popup-action-btn" id="obj-create-save">Save Object</button>
                    </div>
                </div>
            `)
            .openOn(this.map);
        setTimeout(() => {
            popup.update();
            this.map?.panInside?.(popup.getLatLng(), {
                paddingTopLeft: [20, reservedTop],
                paddingBottomRight: [20, reservedBottom],
            });
        }, 0);
        setTimeout(() => {
            const nameEl = document.getElementById('obj-create-name');
            const commentEl = document.getElementById('obj-create-comment');
            const tableEl = document.getElementById('obj-create-table');
            const symbolEl = document.getElementById('obj-create-symbol');
            const previewEl = document.getElementById('obj-create-preview');
            const btn = document.getElementById('obj-create-save');
            const refreshPreview = () => {
                const overlay = document.getElementById('obj-create-overlay')?.value || '';
                const table = overlay || tableEl?.value || '/';
                const code = symbolEl?.value || 'r';
                const sprite = (typeof getAPRSSpriteHTML === 'function') ? getAPRSSpriteHTML(table, code, 28) : `${table}${code}`;
                const name = (typeof getAPRSSymbolName === 'function') ? getAPRSSymbolName(table, code) : '';
                if (previewEl) previewEl.innerHTML = `${sprite}<span>${this._escapeHtml(name || `${table}${code}`)}</span>`;
            };
            tableEl?.addEventListener('change', () => {
                if (symbolEl) symbolEl.innerHTML = this._objectSymbolOptionsHTML(tableEl.value || '/', symbolEl.value || 'r');
                refreshPreview();
            });
            symbolEl?.addEventListener('change', refreshPreview);
            document.getElementById('obj-create-overlay')?.addEventListener('input', refreshPreview);
            refreshPreview();
            nameEl?.focus();
            btn?.addEventListener('click', async () => {
                const name = (nameEl?.value || '').trim().toUpperCase();
                if (!name) {
                    nameEl?.focus();
                    return;
                }
                btn.disabled = true;
                try {
                    const resp = await fetch('/api/objects/create', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name,
                            latitude: lat,
                            longitude: lng,
                            enabled: document.getElementById('obj-create-enabled')?.checked ?? true,
                            active: document.getElementById('obj-create-active')?.checked ?? true,
                            permanent: document.getElementById('obj-create-permanent')?.checked ?? false,
                            scope: document.getElementById('obj-create-scope')?.value || 'global',
                            mode: document.getElementById('obj-create-mode')?.value || '',
                            symbol_table: tableEl?.value || '/',
                            symbol_code: symbolEl?.value || 'r',
                            overlay: document.getElementById('obj-create-overlay')?.value || '',
                            speed_mph: parseInt(document.getElementById('obj-create-speed')?.value, 10) || 0,
                            course_deg: parseInt(document.getElementById('obj-create-course')?.value, 10) || 0,
                            frequency: document.getElementById('obj-create-frequency')?.value || '',
                            tone: document.getElementById('obj-create-tone')?.value || '',
                            duplex: document.getElementById('obj-create-duplex')?.value || '',
                            qru: document.getElementById('obj-create-qru')?.value || '',
                            path: document.getElementById('obj-create-path')?.value || '',
                            comment: commentEl?.value || '',
                        }),
                    });
                    const result = await resp.json();
                    if (!resp.ok || !result.success) throw new Error(result.message || 'Object save failed.');
                    popup.setContent(`<b>${this._escapeHtml(name)}</b><br>Object saved and transmitted if a path was available.`);
                    window.pvRefreshScheduledControls?.();
                } catch (err) {
                    popup.setContent(`<b>Object failed</b><br>${this._escapeHtml(err.message || 'Unable to save object.')}`);
                }
            });
        }, 0);
    }

    _objectSymbolOptionsHTML(table, selectedCode) {
        const symbols = (typeof APRS_SYMBOLS !== 'undefined' && APRS_SYMBOLS[table]) ? APRS_SYMBOLS[table] : [];
        if (!symbols.length) {
            return `<option value="${this._escapeHtml(selectedCode || 'r')}">${this._escapeHtml(table || '/')}${this._escapeHtml(selectedCode || 'r')}</option>`;
        }
        return symbols.map((sym) => {
            const selected = sym.code === selectedCode ? ' selected' : '';
            return `<option value="${this._escapeHtml(sym.code)}"${selected}>${this._escapeHtml(sym.name)} (${this._escapeHtml(table)}${this._escapeHtml(sym.code)})</option>`;
        }).join('');
    }

    _pickPopupHTML(lat, lng) {
        return `
            <div class="popup-header">
                <span class="popup-call" style="color:#f0883e;">Picked Location</span>
            </div>
            <div class="popup-detail">
                ${lat.toFixed(5)}, ${lng.toFixed(5)}<br>
                Settings reopened with these coordinates. Save Configuration to keep them.
            </div>
        `;
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
        const symTable = this.myStationInfo?.symbol_table || '/';
        const symCode = this.myStationInfo?.symbol_code || '#';
        const mySprite = (typeof getAPRSSpriteHTML === 'function')
            ? getAPRSSpriteHTML(symTable, symCode, 16)
            : 'MY';
        this._legendEl.innerHTML = `
            <div class="legend-title">Legend</div>
            <div class="legend-body">
            <div class="legend-item">
                <div class="legend-emoji legend-my-station">${mySprite}</div>
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
        const provider = cfg.radar_provider || 'rainviewer';
        if (provider !== 'rainviewer') {
            this._updateStaticRadarOverlay(provider);
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

    _updateStaticRadarOverlay(provider) {
        this._clearRadarOverlay();
        const cfg = this.weatherOverlayConfig || {};
        let layer = null;
        const opacity = cfg.radar_opacity || 0.55;

        if (provider === 'iem_nexrad') {
            layer = L.tileLayer.wms('https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q.cgi', {
                pane: 'weatherRadarPane',
                layers: 'nexrad-n0q-900913',
                format: 'image/png',
                transparent: true,
                opacity,
                attribution: 'Radar: Iowa State IEM',
            });
        } else if (provider === 'custom_wms' && cfg.radar_custom_url && cfg.radar_custom_layer) {
            layer = L.tileLayer.wms(this._radarUrlWithKey(cfg.radar_custom_url), {
                pane: 'weatherRadarPane',
                layers: cfg.radar_custom_layer,
                format: 'image/png',
                transparent: true,
                opacity,
                attribution: cfg.radar_custom_attribution || '',
            });
        } else if (provider === 'custom_xyz' && cfg.radar_custom_url) {
            layer = L.tileLayer(this._radarUrlWithKey(cfg.radar_custom_url), {
                pane: 'weatherRadarPane',
                opacity,
                maxZoom: 19,
                attribution: cfg.radar_custom_attribution || '',
                className: 'weather-radar-tile-layer',
            });
        }

        if (layer) {
            this.radarStaticLayer = layer.addTo(this.map);
        }
    }

    _radarUrlWithKey(url) {
        const key = this.weatherOverlayConfig?.radar_custom_api_key || '';
        return String(url || '').replaceAll('{key}', encodeURIComponent(key));
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
        if (this.radarStaticLayer) {
            this.radarStaticLayer.remove();
            this.radarStaticLayer = null;
        }
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
