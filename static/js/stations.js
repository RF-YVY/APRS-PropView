/**
 * Station list management - renders and updates RF and APRS-IS station lists.
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
        this._listClickBound = false;
        this.hasLoadedInitialStations = false;
    }

    init() {
        this._bindFilters();
        this._populateTypeDropdowns();
        this._bindListClicks();
    }

    updateStation(station) {
        const call = station.callsign;
        const source = station.source;

        if (source === 'rf') {
            this.rfStations[call] = station;
        } else {
            this.isStations[call] = station;
        }

        window.pvMap.addOrUpdateStation(station);
        this._renderStationList(source);
    }

    loadInitialStations(rfList, isList) {
        this.hasLoadedInitialStations = true;
        rfList.forEach((s) => {
            this.rfStations[s.callsign] = s;
            window.pvMap.addOrUpdateStation(s);
        });
        isList.forEach((s) => {
            this.isStations[s.callsign] = s;
            window.pvMap.addOrUpdateStation(s);
        });
        this._renderStationList('rf');
        this._renderStationList('aprs_is');
    }

    syncStations(rfList, isList) {
        this.hasLoadedInitialStations = true;
        this._syncSourceStations('rf', rfList || []);
        this._syncSourceStations('aprs_is', isList || []);
        this.render();
    }

    removeStation(callsign, source) {
        if (source === 'rf' && this.rfStations[callsign]) {
            delete this.rfStations[callsign];
            this._renderStationList('rf');
        } else if (this.isStations[callsign]) {
            delete this.isStations[callsign];
            this._renderStationList('aprs_is');
        }
    }

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

    render() {
        this._renderStationList('rf');
        this._renderStationList('aprs_is');
    }

    refreshRelativeTimes() {
        document.querySelectorAll('.station-item').forEach((item) => {
            const timeEl = item.querySelector('.station-time');
            if (!timeEl) return;
            const ts = parseFloat(item.dataset.lastHeard || '0');
            const count = parseInt(item.dataset.packetCount || '0', 10) || 0;
            timeEl.textContent = `${this._timeAgo(ts)} | ${count} pkt${count === 1 ? '' : 's'}`;
        });
    }

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

        const filtered = Object.values(stations)
            .filter((s) => {
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
            })
            .sort((a, b) => (b.last_heard || 0) - (a.last_heard || 0));

        if (countEl) {
            if (isRF) {
                const directCount = filtered.filter((s) => this._isDirectHeard(s.last_path)).length;
                const digiCount = filtered.length - directCount;
                countEl.textContent = `${filtered.length} stn${filtered.length !== 1 ? 's' : ''} (${directCount} direct, ${digiCount} via digi)`;
            } else {
                countEl.textContent = `${filtered.length} station${filtered.length !== 1 ? 's' : ''}`;
            }
        }

        if (!filtered.length) {
            listEl.innerHTML = this._emptyStateHTML(source, timeFilter);
            return;
        }

        listEl.innerHTML = filtered.map((s) => this._stationItemHTML(s)).join('');
    }

    _stationItemHTML(station) {
        const call = this._escapeHTML(station.callsign || '???');
        const source = station.source === 'rf' ? 'rf' : 'aprs_is';
        const dist = station.distance_km ? window.formatDist(station.distance_km) : '';
        const heading = station.heading ? `${station.heading.toFixed(0)}&deg;` : '';
        const elapsed = this._timeAgo(station.last_heard);
        const count = station.packet_count || 1;
        const comment = this._escapeHTML(station.last_comment || '');
        const path = this._escapeHTML(station.last_path || '');
        const icon = this._symbolToEmoji(station.symbol_table, station.symbol_code);
        const escapedCallAttr = this._escapeHTML(station.callsign || '');
        const direct = source === 'rf' ? this._isDirectHeard(station.last_path) : false;
        const directBadge = source === 'rf'
            ? `<span class="heard-badge ${direct ? 'direct' : 'via-digi'}">${direct ? 'DIRECT' : 'VIA DIGI'}</span>`
            : '';

        return `
            <div class="station-item ${source}" data-callsign="${escapedCallAttr}" data-source="${source}" data-last-heard="${station.last_heard || 0}" data-packet-count="${count}">
                <div class="station-icon">${icon}</div>
                <div class="station-info">
                    <div class="station-call">${call} ${directBadge}</div>
                    <div class="station-detail">${comment || path || '&mdash;'}</div>
                </div>
                <div class="station-meta">
                    <div class="station-distance">${dist} ${heading}</div>
                    <div class="station-time">${elapsed} | ${count} pkt${count > 1 ? 's' : ''}</div>
                </div>
            </div>
        `;
    }

    _renderPacketItem(pkt) {
        const list = document.getElementById('packet-list');
        if (!list) return;

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

        list.insertBefore(el, list.firstChild);

        while (list.children.length > 200) {
            list.removeChild(list.lastChild);
        }
    }

    _bindFilters() {
        document.getElementById('rf-time-filter')?.addEventListener('change', (e) => {
            this.rfTimeFilter = parseFloat(e.target.value);
            this._renderStationList('rf');
        });

        document.getElementById('rf-dist-filter')?.addEventListener('change', (e) => {
            this.rfDistFilter = parseFloat(e.target.value);
            this._renderStationList('rf');
        });

        document.getElementById('is-time-filter')?.addEventListener('change', (e) => {
            this.isTimeFilter = parseFloat(e.target.value);
            this._renderStationList('aprs_is');
        });

        document.getElementById('rf-type-filter')?.addEventListener('change', (e) => {
            this.rfTypeFilter = e.target.value;
            this._renderStationList('rf');
        });

        document.getElementById('is-type-filter')?.addEventListener('change', (e) => {
            this.isTypeFilter = e.target.value;
            this._renderStationList('aprs_is');
        });

        document.getElementById('packet-source-filter')?.addEventListener('change', () => {
            this._rerenderPackets();
        });

        document.getElementById('btn-clear-packets')?.addEventListener('click', () => {
            this.clearPackets();
        });
    }

    _rerenderPackets() {
        const list = document.getElementById('packet-list');
        if (!list) return;
        list.innerHTML = '';
        this.packetBuffer.forEach((pkt) => this._renderPacketItem(pkt));
    }

    _populateTypeDropdowns() {
        if (typeof APRS_CATEGORY_ORDER === 'undefined') return;
        ['rf-type-filter', 'is-type-filter'].forEach((id) => {
            const sel = document.getElementById(id);
            if (!sel) return;
            APRS_CATEGORY_ORDER.forEach((key) => {
                const opt = document.createElement('option');
                opt.value = key;
                opt.textContent = APRS_CATEGORIES[key].label;
                sel.appendChild(opt);
            });
        });
    }

    _timeAgo(timestamp) {
        if (!timestamp) return '--';
        const seconds = Math.floor(Date.now() / 1000 - timestamp);
        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    }

    _symbolToEmoji(table, code) {
        if (typeof getAPRSSpriteHTML === 'function') {
            return getAPRSSpriteHTML(table || '/', code || '-', 20);
        }
        if (typeof getAPRSEmoji === 'function') {
            return getAPRSEmoji(table || '/', code || '-');
        }
        return '&#128205;';
    }

    _escapeHTML(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    _isDirectHeard(path) {
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

    _bindListClicks() {
        if (this._listClickBound) return;
        this._listClickBound = true;

        ['rf-station-list', 'is-station-list'].forEach((id) => {
            document.getElementById(id)?.addEventListener('click', (e) => {
                const el = e.target.closest('.station-item');
                if (!el) return;

                const call = el.dataset.callsign;
                const src = el.dataset.source;
                const station = src === 'rf' ? this.rfStations[call] : this.isStations[call];
                if (station && station.latitude && station.longitude) {
                    window.pvMap.map.setView([station.latitude, station.longitude], 13);
                    const markers = src === 'rf' ? window.pvMap.rfMarkers : window.pvMap.isMarkers;
                    if (markers[call]) markers[call].openPopup();
                }
            });
        });
    }

    _emptyStateHTML(source, timeFilter) {
        const isRF = source === 'rf';
        const connected = !!window.pvWebSocket?.isConnected;
        if (!this.hasLoadedInitialStations) {
            return `
                <div class="empty-state loading">
                    <div class="empty-state-title">Loading live station data</div>
                    <div class="empty-state-copy">Waiting for the first station snapshot from the live feed.</div>
                </div>
            `;
        }

        const title = isRF ? 'No RF stations in view' : 'No APRS-IS stations in view';
        let copy = isRF
            ? 'Nothing matches the current filter window yet. If you expected traffic, check your antenna, TNC, or time filter.'
            : 'Nothing matches the current filter window yet. If you expected APRS-IS traffic, confirm the connection and filter settings.';

        if (!connected) {
            copy = isRF
                ? 'The live connection is offline, so the list will update once the WebSocket reconnects.'
                : 'The live connection is offline, so APRS-IS updates will appear once the WebSocket reconnects.';
        } else if (timeFilter > 0) {
            copy = isRF
                ? `No RF stations have been heard in the last ${timeFilter} hour${timeFilter === 1 ? '' : 's'} for this filter.`
                : `No APRS-IS stations have appeared in the last ${timeFilter} hour${timeFilter === 1 ? '' : 's'} for this filter.`;
        }

        return `
            <div class="empty-state">
                <div class="empty-state-title">${title}</div>
                <div class="empty-state-copy">${copy}</div>
            </div>
        `;
    }

    _syncSourceStations(source, nextList) {
        const isRF = source === 'rf';
        const current = isRF ? this.rfStations : this.isStations;
        const nextMap = {};

        nextList.forEach((station) => {
            nextMap[station.callsign] = station;
        });

        Object.keys(current).forEach((callsign) => {
            if (!nextMap[callsign]) {
                delete current[callsign];
                window.pvMap?.removeStation(callsign, source);
            }
        });

        nextList.forEach((station) => {
            current[station.callsign] = station;
            window.pvMap?.addOrUpdateStation(station);
        });
    }
}

window.pvStations = new StationManager();
