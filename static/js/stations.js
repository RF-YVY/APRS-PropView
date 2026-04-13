/**
 * Station list management — renders and updates RF and APRS-IS station lists.
 */

class StationManager {
    constructor() {
        this.rfStations = {};      // callsign -> station data
        this.isStations = {};      // callsign -> station data
        this.rfTimeFilter = 24;    // hours
        this.rfDistFilter = 0;     // km, 0 = any
        this.rfTypeFilter = '';    // '' = all, or category key
        this.isTimeFilter = 24;    // hours
        this.isTypeFilter = '';    // '' = all, or category key
        this.packetBuffer = [];    // recent packets for display
        this.maxPackets = 500;
    }

    init() {
        this._bindFilters();
        this._populateTypeDropdowns();
    }

    // ── Station updates ────────────────────────────────────────

    updateStation(station) {
        const call = station.callsign;
        const source = station.source;

        if (source === 'rf') {
            this.rfStations[call] = station;
        } else {
            this.isStations[call] = station;
        }

        // Update map
        window.pvMap.addOrUpdateStation(station);

        // Re-render list
        this._renderStationList(source);
    }

    loadInitialStations(rfList, isList) {
        rfList.forEach(s => {
            this.rfStations[s.callsign] = s;
            window.pvMap.addOrUpdateStation(s);
        });
        isList.forEach(s => {
            this.isStations[s.callsign] = s;
            window.pvMap.addOrUpdateStation(s);
        });
        this._renderStationList('rf');
        this._renderStationList('aprs_is');
    }

    // ── Packet tracking ────────────────────────────────────────

    addPacket(pkt) {
        this.packetBuffer.unshift(pkt);
        if (this.packetBuffer.length > this.maxPackets) {
            this.packetBuffer.pop();
        }
        this._renderPacketItem(pkt);
    }

    clearPackets() {
        this.packetBuffer = [];
        const list = document.getElementById('packet-list');
        if (list) list.innerHTML = '';
    }

    // ── Rendering ──────────────────────────────────────────────

    _renderStationList(source) {
        const isRF = source === 'rf';
        const stations = isRF ? this.rfStations : this.isStations;
        const listEl = document.getElementById(isRF ? 'rf-station-list' : 'is-station-list');
        const countEl = document.getElementById(isRF ? 'rf-filter-count' : 'is-filter-count');

        if (!listEl) return;

        const now = Date.now() / 1000;
        const timeFilter = isRF ? this.rfTimeFilter : this.isTimeFilter;
        const distFilter = isRF ? this.rfDistFilter : 0;
        const typeFilter = isRF ? this.rfTypeFilter : this.isTypeFilter;

        // Filter stations
        let filtered = Object.values(stations).filter(s => {
            if (timeFilter > 0 && s.last_heard && (now - s.last_heard) > timeFilter * 3600) {
                return false;
            }
            if (distFilter > 0 && s.distance_km && s.distance_km > distFilter) {
                return false;
            }
            if (typeFilter) {
                const cat = (typeof getAPRSCategory === 'function')
                    ? getAPRSCategory(s.symbol_table || '/', s.symbol_code || '-')
                    : 'other';
                if (cat !== typeFilter) return false;
            }
            return true;
        });

        // Sort by last heard (most recent first)
        filtered.sort((a, b) => (b.last_heard || 0) - (a.last_heard || 0));

        // Update count
        if (countEl) {
            countEl.textContent = `${filtered.length} station${filtered.length !== 1 ? 's' : ''}`;
        }

        // Render
        listEl.innerHTML = filtered.map(s => this._stationItemHTML(s)).join('');

        // Bind click handlers
        listEl.querySelectorAll('.station-item').forEach(el => {
            el.addEventListener('click', () => {
                const call = el.dataset.callsign;
                const src = el.dataset.source;
                const station = src === 'rf' ? this.rfStations[call] : this.isStations[call];
                if (station && station.latitude && station.longitude) {
                    window.pvMap.map.setView([station.latitude, station.longitude], 13);
                    // Open popup
                    const markers = src === 'rf' ? window.pvMap.rfMarkers : window.pvMap.isMarkers;
                    if (markers[call]) {
                        markers[call].openPopup();
                    }
                }
            });
        });
    }

    _stationItemHTML(station) {
        const call = this._escapeHTML(station.callsign || '???');
        const source = station.source === 'rf' ? 'rf' : 'aprs_is';
        const dist = station.distance_km ? `${station.distance_km.toFixed(1)} km` : '';
        const heading = station.heading ? `${station.heading.toFixed(0)}°` : '';
        const elapsed = this._timeAgo(station.last_heard);
        const count = station.packet_count || 1;
        const comment = this._escapeHTML(station.last_comment || '');
        const path = this._escapeHTML(station.last_path || '');
        const icon = this._symbolToEmoji(station.symbol_table, station.symbol_code);
        const escapedCallAttr = this._escapeHTML(station.callsign || '');

        return `
            <div class="station-item ${source}" data-callsign="${escapedCallAttr}" data-source="${source}">
                <div class="station-icon">${icon}</div>
                <div class="station-info">
                    <div class="station-call">${call}</div>
                    <div class="station-detail">${comment || path || '—'}</div>
                </div>
                <div class="station-meta">
                    <div class="station-distance">${dist} ${heading}</div>
                    <div class="station-time">${elapsed} · ${count} pkt${count > 1 ? 's' : ''}</div>
                </div>
            </div>
        `;
    }

    _renderPacketItem(pkt) {
        const list = document.getElementById('packet-list');
        if (!list) return;

        // Check source filter
        const filter = document.getElementById('packet-source-filter')?.value || '';
        if (filter && pkt.source !== filter) return;

        const time = pkt.timestamp
            ? new Date(pkt.timestamp * 1000).toLocaleTimeString()
            : '';
        const sourceLabel = pkt.source === 'rf' ? 'RF' : 'IS';
        const sourceClass = pkt.source || 'rf';

        const el = document.createElement('div');
        el.className = 'packet-item';
        el.innerHTML = `
            <span class="pkt-time">${time}</span>
            <span class="pkt-source ${sourceClass}">[${sourceLabel}]</span>
            <span class="pkt-raw">${this._escapeHTML(pkt.raw || '')}</span>
        `;

        // Prepend (newest first)
        list.insertBefore(el, list.firstChild);

        // Limit displayed items
        while (list.children.length > 200) {
            list.removeChild(list.lastChild);
        }
    }

    // ── Filters ────────────────────────────────────────────────

    _bindFilters() {
        // RF time filter
        document.getElementById('rf-time-filter')?.addEventListener('change', (e) => {
            this.rfTimeFilter = parseFloat(e.target.value);
            this._renderStationList('rf');
        });

        // RF distance filter
        document.getElementById('rf-dist-filter')?.addEventListener('change', (e) => {
            this.rfDistFilter = parseFloat(e.target.value);
            this._renderStationList('rf');
        });

        // IS time filter
        document.getElementById('is-time-filter')?.addEventListener('change', (e) => {
            this.isTimeFilter = parseFloat(e.target.value);
            this._renderStationList('aprs_is');
        });

        // RF type filter
        document.getElementById('rf-type-filter')?.addEventListener('change', (e) => {
            this.rfTypeFilter = e.target.value;
            this._renderStationList('rf');
        });

        // IS type filter
        document.getElementById('is-type-filter')?.addEventListener('change', (e) => {
            this.isTypeFilter = e.target.value;
            this._renderStationList('aprs_is');
        });

        // Packet source filter
        document.getElementById('packet-source-filter')?.addEventListener('change', () => {
            this._rerenderPackets();
        });

        // Clear packets button
        document.getElementById('btn-clear-packets')?.addEventListener('click', () => {
            this.clearPackets();
        });
    }

    _rerenderPackets() {
        const list = document.getElementById('packet-list');
        if (!list) return;
        list.innerHTML = '';
        // Re-render from buffer (most recent first, already sorted)
        this.packetBuffer.forEach(pkt => this._renderPacketItem(pkt));
    }

    /**
     * Populate the type filter dropdowns from the APRS category definitions.
     */
    _populateTypeDropdowns() {
        if (typeof APRS_CATEGORY_ORDER === 'undefined') return;
        ['rf-type-filter', 'is-type-filter'].forEach(id => {
            const sel = document.getElementById(id);
            if (!sel) return;
            APRS_CATEGORY_ORDER.forEach(key => {
                const opt = document.createElement('option');
                opt.value = key;
                opt.textContent = APRS_CATEGORIES[key].label;
                sel.appendChild(opt);
            });
        });
    }

    // ── Helpers ────────────────────────────────────────────────

    _timeAgo(timestamp) {
        if (!timestamp) return '—';
        const seconds = Math.floor(Date.now() / 1000 - timestamp);
        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }

    _symbolToEmoji(table, code) {
        // Use sprite sheet from icons.js (falls back to emoji)
        if (typeof getAPRSSpriteHTML === 'function') {
            return getAPRSSpriteHTML(table || '/', code || '-', 20);
        }
        if (typeof getAPRSEmoji === 'function') {
            return getAPRSEmoji(table || '/', code || '-');
        }
        return '📍';
    }

    _escapeHTML(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Global instance
window.pvStations = new StationManager();
