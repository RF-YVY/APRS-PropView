/** Independent, opt-in outbound RF reception overlay for desktop and mobile. */
(() => {
    'use strict';
    const storageKey = 'propview.heard-me.visible';
    let visible = false;
    try { visible = localStorage.getItem(storageKey) === 'true'; } catch (_) {}
    let layer = null, attachedMap = null, busy = false, data = { observations: [] };
    const valid = (lat, lon) => Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && (lat !== 0 || lon !== 0);
    const mapContext = () => {
        if (window.pvMap?.map) return { map: window.pvMap.map, lookup: call => window.pvMap._getStationPosition(call) };
        if (typeof S !== 'undefined' && S.map) return { map: S.map, lookup: call => {
            const marker = S.rfMarkers[call] || S.isMarkers[call];
            const point = marker?.getLatLng();
            return point ? [point.lat, point.lng] : null;
        } };
        return null;
    };

    function textElement(tag, text) {
        const element = document.createElement(tag);
        element.textContent = text;
        return element;
    }

    function render() {
        const buttons = document.querySelectorAll('[data-heard-me-toggle]');
        buttons.forEach(button => {
            button.classList.toggle('active', visible);
            button.setAttribute('aria-pressed', String(visible));
        });
        const context = mapContext();
        if (!context || typeof L === 'undefined') return;
        if (attachedMap !== context.map) {
            layer?.remove();
            attachedMap = context.map;
            layer = L.layerGroup();
        }
        let readingPopup = false;
        layer.eachLayer(item => { if (item.getPopup?.()?.isOpen()) readingPopup = true; });
        if (visible && readingPopup) return;
        layer.clearLayers();
        if (!visible) { layer.remove(); return; }
        layer.addTo(attachedMap);
        const now = Date.now() / 1000;
        let drawn = 0, pending = 0;
        for (const observation of data.observations || []) {
            const age = now - observation.last_heard;
            if (age > 3600 || !valid(observation.latitude, observation.longitude)) continue;
            const points = [[observation.latitude, observation.longitude]];
            let complete = observation.path_known;
            for (const hop of observation.hops || []) {
                const point = valid(hop.latitude, hop.longitude) ? [hop.latitude, hop.longitude] : context.lookup(hop.callsign);
                if (!point || !valid(point[0], point[1])) { complete = false; break; }
                points.push(point);
            }
            if (!complete || points.length < 2) { pending++; continue; }
            for (let i = 1; i < points.length; i++) {
                points[i] = [...points[i]];
                while (points[i][1] - points[i - 1][1] > 180) points[i][1] -= 360;
                while (points[i][1] - points[i - 1][1] < -180) points[i][1] += 360;
            }
            const opacity = Math.max(0.25, 0.9 - Math.max(0, age) / 3600 * 0.65);
            const color = '#e6a23c';
            const line = L.polyline(points, { color, weight: 3, opacity,
                dashArray: observation.direct ? null : '7 5', className: 'heard-me-path' }).addTo(layer);
            const popup = document.createElement('div');
            popup.append(textElement('strong', `Heard me: ${observation.receiver}`), document.createElement('br'),
                textElement('span', observation.direct ? 'Reported direct reception' : 'Reported relayed reception'), document.createElement('br'),
                textElement('span', [observation.source_call, ...observation.route_calls].join(' → ')), document.createElement('br'),
                textElement('span', `${observation.packet_count} matched transmission(s) · ${(observation.transports || [observation.transport]).map(source => source === 'rf' ? 'RF return' : 'APRS-IS report').join(' / ')}`), document.createElement('br'),
                textElement('span', `Last heard ${new Date(observation.last_heard * 1000).toLocaleTimeString()}`));
            line.bindPopup(popup);
            // A marker at each segment midpoint points in the direction of travel.
            for (let i = 1; i < points.length; i++) {
                const from = points[i - 1], to = points[i];
                const a = attachedMap.project(L.latLng(from), 8), b = attachedMap.project(L.latLng(to), 8);
                if (a.distanceTo(b) < 0.1) continue;
                const angle = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
                const midpoint = attachedMap.unproject(L.point((a.x + b.x) / 2, (a.y + b.y) / 2), 8);
                L.marker(midpoint, { interactive: false, opacity, icon: L.divIcon({ className: 'heard-me-arrow',
                    html: `<span style="display:block;color:${color};font-size:22px;transform:rotate(${angle}deg)">➤</span>`,
                    iconSize: [22, 22], iconAnchor: [11, 11] }) }).addTo(layer);
            }
            drawn++;
        }
        const status = document.getElementById('heard-me-status');
        if (status) status.textContent = `${drawn} route(s) · ${pending} awaiting path positions. Last hour, this session. Reports are incomplete; missing reports do not mean nobody heard you.${data.aprs_is_connected ? '' : ' APRS-IS disconnected; RF returns can still appear.'}`;
    }

    async function refresh() {
        if (!visible || busy || document.hidden) return;
        busy = true;
        try {
            const response = await fetch('/api/heard-me', { cache: 'no-store' });
            if (!response.ok) throw new Error('Reception reports unavailable');
            data = await response.json();
            render();
        } catch (_) {
            render();
            const status = document.getElementById('heard-me-status');
            if (status) status.textContent = 'Reception reports unavailable. Retrying shortly.';
        } finally { busy = false; }
    }

    function toggle() {
        visible = !visible;
        try { localStorage.setItem(storageKey, String(visible)); } catch (_) {}
        const status = document.getElementById('heard-me-status');
        if (status) status.hidden = !visible;
        render();
        if (visible) refresh();
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-heard-me-toggle]').forEach(button => button.addEventListener('click', toggle));
        const status = document.getElementById('heard-me-status');
        if (status) status.hidden = !visible;
        render();
        refresh();
        setInterval(refresh, 15000);
        // Resolve paths when station positions or the mobile map arrive later.
        setInterval(() => { if (visible && !document.hidden) render(); }, 5000);
        document.addEventListener('visibilitychange', refresh);
    });
    window.pvHeardMe = { refresh, render, toggle, get visible() { return visible; } };
})();
