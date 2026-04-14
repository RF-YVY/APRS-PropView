/**
 * Main application — initializes all components and wires them together.
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────
    let serverConfig = null;
    let uptimeStart = 0;

    // ── Distance unit helpers (mi / km) ────────────────────────
    // Default to miles; persisted in localStorage
    window.pvDistUnit = localStorage.getItem('pvDistUnit') || 'mi';
    const KM_TO_MI = 0.621371;

    /** Convert km to the active display unit. */
    window.convertDist = function (km) {
        if (km == null) return null;
        return window.pvDistUnit === 'mi' ? km * KM_TO_MI : km;
    };

    /** Format km as a display string in the active unit. */
    window.formatDist = function (km, decimals) {
        if (decimals === undefined) decimals = 1;
        if (km == null || km === 0) return 'N/A';
        const val = window.pvDistUnit === 'mi' ? km * KM_TO_MI : km;
        return `${val.toFixed(decimals)} ${window.pvDistUnit}`;
    };

    /** Return the current unit label ('mi' or 'km'). */
    window.distLabel = function () { return window.pvDistUnit; };

    /** Toggle the distance unit and refresh all displays. */
    window.toggleDistUnit = function () {
        window.pvDistUnit = window.pvDistUnit === 'mi' ? 'km' : 'mi';
        localStorage.setItem('pvDistUnit', window.pvDistUnit);
        _refreshAllDistanceDisplays();
    };

    /** Convert a km value to the active unit for settings fields that store in km. */
    window.distToDisplay = function (km) {
        return window.pvDistUnit === 'mi' ? Math.round(km * KM_TO_MI) : km;
    };

    /** Convert a display-unit value back to km for settings fields. */
    window.displayToDist = function (val) {
        return window.pvDistUnit === 'mi' ? val / KM_TO_MI : val;
    };

    /** Refresh every distance-related display after a unit toggle. */
    function _refreshAllDistanceDisplays() {
        const u = window.pvDistUnit;
        // Update all .dist-unit spans
        document.querySelectorAll('.dist-unit').forEach(el => { el.textContent = u; });
        // Update distance filter dropdowns (values stay in km, labels change)
        const miLabels = { '50': '31 mi', '100': '62 mi', '200': '124 mi', '500': '311 mi' };
        const kmLabels = { '50': '50 km', '100': '100 km', '200': '200 km', '500': '500 km' };
        const labels = u === 'mi' ? miLabels : kmLabels;
        document.querySelectorAll('#rf-dist-filter option, #is-dist-filter option').forEach(opt => {
            if (labels[opt.value]) opt.textContent = labels[opt.value];
        });
        // Re-render station lists
        if (window.pvStations) window.pvStations.render();
        // Refresh map legend
        if (window.pvMap) window.pvMap.refreshLegend();
        // Refresh map popups (will update on next open)
    }

    // ── Initialize ─────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {
        // Apply saved distance unit to all labels
        _refreshAllDistanceDisplays();

        // Init tab switching
        initTabs();

        // Init station manager
        window.pvStations.init();

        // Init map (will be re-centered once we get config)
        window.pvMap.init();

        // Init APRS icon picker
        window.pvIconPicker.init();

        // Init analytics module
        window.pvAnalytics.init();

        // Init messaging module
        window.pvMessages.init();

        // Init weather module
        window.pvWeather.init();

        // Wire up WebSocket events
        wireWebSocket();

        // Sidebar toggle
        initSidebarToggle();

        // Force callsign field to uppercase on input
        document.getElementById('cfg-callsign')?.addEventListener('input', (e) => {
            const start = e.target.selectionStart;
            const end = e.target.selectionEnd;
            e.target.value = e.target.value.toUpperCase();
            e.target.setSelectionRange(start, end);
        });

        // Connect WebSocket
        window.pvWebSocket.connect();

        // Start uptime timer
        setInterval(updateUptime, 1000);

        // Periodically refresh station lists
        setInterval(() => {
            window.pvStations._renderStationList('rf');
            window.pvStations._renderStationList('aprs_is');
        }, 15000);

        // Periodically ghost stale markers (every 30s)
        window._ghostMinutes = 60; // default, overwritten by loadSettings
        window._expireMinutes = 0; // default, overwritten by loadSettings
        setInterval(() => {
            window.pvMap?.ghostStaleMarkers(window._ghostMinutes);
        }, 30000);

        // Periodically expire stale stations (every 60s)
        setInterval(() => {
            if (window._expireMinutes > 0) {
                window.pvMap?.expireStaleStations(window._expireMinutes);
            }
        }, 60000);
    });

    // ── Tab switching ──────────────────────────────────────────

    function initTabs() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;
                // Deactivate all
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                // Activate selected
                btn.classList.add('active');
                document.getElementById(tabId)?.classList.add('active');

                // If sidebar was collapsed, expand it
                const panel = document.getElementById('side-panel');
                if (panel?.classList.contains('collapsed')) {
                    panel.classList.remove('collapsed');
                    const toggle = document.getElementById('sidebar-toggle');
                    if (toggle) toggle.textContent = '▶';
                    setTimeout(() => window.pvMap?.map?.invalidateSize(), 300);
                }
            });
        });
    }

    // ── Sidebar toggle ─────────────────────────────────────────

    function initSidebarToggle() {
        const toggle = document.getElementById('sidebar-toggle');
        const panel = document.getElementById('side-panel');
        if (!toggle || !panel) return;

        toggle.addEventListener('click', () => {
            const isCollapsed = panel.classList.contains('collapsed');
            if (isCollapsed) {
                // Expanding: keep tab content hidden until width transition finishes
                panel.classList.remove('collapsed');
                toggle.textContent = '▶';
                // Show tabs after width transition completes (250ms + buffer)
                setTimeout(() => {
                    panel.querySelectorAll('.tab-bar, .tab-content').forEach(el => el.style.removeProperty('display'));
                    window.pvMap?.map?.invalidateSize();
                }, 280);
            } else {
                // Collapsing
                panel.classList.add('collapsed');
                toggle.textContent = '◀';
                setTimeout(() => window.pvMap?.map?.invalidateSize(), 300);
            }
        });
    }

    // ── WebSocket event wiring ─────────────────────────────────

    function wireWebSocket() {
        const ws = window.pvWebSocket;

        ws.on('status', (msg) => {
            handleStatus(msg.data);
        });

        ws.on('initial_stations', (msg) => {
            window.pvStations.loadInitialStations(msg.rf || [], msg.aprs_is || []);
        });

        ws.on('station_update', (msg) => {
            if (msg.station) {
                window.pvStations.updateStation(msg.station);
            }
        });

        ws.on('packet', (msg) => {
            if (msg.data) {
                window.pvStations.addPacket(msg.data);
            }
        });

        ws.on('propagation', (msg) => {
            if (msg.data) {
                updatePropagation(msg.data);
            }
        });

        ws.on('alert', (msg) => {
            if (msg.data) {
                showAlertNotification(msg.data);
                window.pvAnalytics.loadAlerts();
            }
        });

        ws.on('message', (msg) => {
            if (msg.data) {
                window.pvMessages.addMessage(msg.data);
            }
        });

        ws.on('message_ack', (msg) => {
            if (msg.data) {
                window.pvMessages.handleAck(msg.data);
            }
        });

        ws.on('message_rej', (msg) => {
            if (msg.data) {
                window.pvMessages.handleRej(msg.data);
            }
        });

        ws.on('station_removed', (msg) => {
            if (msg.data && msg.data.callsign) {
                window.pvMap?.removeStation(msg.data.callsign);
                window.pvStations?.removeStation(msg.data.callsign, msg.data.source);
            }
        });

        ws.on('connected', () => {
            // Fetch propagation history for charts
            fetchPropagationHistory();
        });
    }

    // ── Status handling ────────────────────────────────────────

    function handleStatus(status) {
        if (!status) return;

        serverConfig = status;
        uptimeStart = Date.now() / 1000 - (status.uptime_seconds || 0);

        // Update station callsign
        const callEl = document.getElementById('station-call');
        if (callEl) callEl.textContent = status.station || 'N0CALL';

        // Update connection indicators
        const rfEl = document.getElementById('rf-status');
        const isEl = document.getElementById('is-status');
        if (rfEl) {
            rfEl.classList.toggle('connected', status.rf_connected);
            rfEl.classList.toggle('disconnected', !status.rf_connected);
        }
        if (isEl) {
            isEl.classList.toggle('connected', status.aprs_is_connected);
            isEl.classList.toggle('disconnected', !status.aprs_is_connected);
        }

        // Update stats
        if (status.stats) {
            setTextById('stat-rf-rx', status.stats.rf_rx || 0);
            setTextById('stat-rf-tx', status.stats.rf_tx || 0);
            setTextById('stat-is-rx', status.stats.is_rx || 0);
            setTextById('stat-is-tx', status.stats.is_tx || 0);
            setTextById('stat-digi', status.stats.digipeated || 0);
            setTextById('stat-gated', (status.stats.gated_rf_to_is || 0) + (status.stats.gated_is_to_rf || 0));
        }

        // Set map position
        if (status.latitude && status.longitude && status.latitude !== 0) {
            window.pvMap.setMyPosition(status.latitude, status.longitude, status.station);
            window.pvMap.centerOnStation();
        }
    }

    // ── Propagation updates ────────────────────────────────────

    function updatePropagation(data) {
        if (!data) return;

        const score = data.score || 0;
        const level = data.level || 'none';

        // Update header gauge
        const bar = document.getElementById('prop-bar');
        if (bar) {
            bar.style.width = `${Math.min(score, 100)}%`;
            bar.className = `prop-bar ${level}`;
        }

        setTextById('prop-level', level.toUpperCase());
        setTextById('prop-score', `Score: ${score.toFixed(0)}`);

        // Header stats
        setTextById('rf-count-1h', data.rf_stations_1h || 0);
        setTextById('is-count-1h', data.is_stations_1h || 0);
        setTextById('max-distance', data.max_distance_km ? window.convertDist(data.max_distance_km).toFixed(0) : '0');

        // Propagation tab cards
        setTextById('prop-rf-1h', data.rf_stations_1h || 0);
        setTextById('prop-rf-6h', data.rf_stations_6h || 0);
        setTextById('prop-rf-24h', data.rf_stations_24h || 0);
        setTextById('prop-max-dist', window.formatDist(data.max_distance_km || 0, 0));
        setTextById('prop-avg-dist', window.formatDist(data.avg_distance_km || 0, 0));
        setTextById('prop-is-1h', data.is_stations_1h || 0);

        // Draw distance distribution chart
        if (data.distances && data.distances.length > 0) {
            drawDistanceChart(data.distances);
        }
    }

    // ── Charts ─────────────────────────────────────────────────

    function drawDistanceChart(distances) {
        const canvas = document.getElementById('distance-chart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 15, bottom: 30, left: 45 };

        ctx.clearRect(0, 0, w, h);

        if (distances.length === 0) return;

        // Create histogram bins
        const maxDist = Math.max(...distances, 50);
        const binSize = Math.max(10, Math.ceil(maxDist / 15 / 10) * 10);
        const numBins = Math.ceil(maxDist / binSize) + 1;
        const bins = new Array(numBins).fill(0);

        distances.forEach(d => {
            const bin = Math.floor(d / binSize);
            if (bin < numBins) bins[bin]++;
        });

        const maxCount = Math.max(...bins, 1);
        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;
        const barW = chartW / numBins - 2;

        // Draw axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.lineTo(w - padding.right, h - padding.bottom);
        ctx.stroke();

        // Draw bars
        bins.forEach((count, i) => {
            if (count === 0) return;
            const x = padding.left + (i * (chartW / numBins)) + 1;
            const barH = (count / maxCount) * chartH;
            const y = h - padding.bottom - barH;

            // Gradient by distance
            const dist = (i + 0.5) * binSize;
            let color;
            if (dist > 200) color = '#bc8cff';
            else if (dist > 100) color = '#3fb950';
            else if (dist > 50) color = '#d29922';
            else color = '#f85149';

            ctx.fillStyle = color;
            ctx.fillRect(x, y, barW, barH);

            // Count label
            if (count > 0) {
                ctx.fillStyle = '#e6edf3';
                ctx.font = '10px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(count, x + barW / 2, y - 4);
            }
        });

        // X-axis labels
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        for (let i = 0; i <= numBins; i += Math.max(1, Math.floor(numBins / 6))) {
            const x = padding.left + (i * (chartW / numBins));
            const label = `${Math.round(window.convertDist(i * binSize))}`;
            ctx.fillText(label, x, h - padding.bottom + 14);
        }

        // Labels
        ctx.fillStyle = '#6e7681';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`Distance (${window.distLabel()})`, w / 2, h - 4);

        ctx.save();
        ctx.translate(12, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText('Stations', 0, 0);
        ctx.restore();
    }

    function drawPropHistoryChart(history) {
        const canvas = document.getElementById('prop-history-chart');
        if (!canvas || !history || history.length === 0) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 15, bottom: 30, left: 45 };

        ctx.clearRect(0, 0, w, h);

        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;

        const counts = history.map(p => p.rf_station_count || 0);
        const maxCount = Math.max(...counts, 1);
        const times = history.map(p => p.timestamp);
        const minTime = Math.min(...times);
        const maxTime = Math.max(...times);
        const timeRange = maxTime - minTime || 1;

        // Draw axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.lineTo(w - padding.right, h - padding.bottom);
        ctx.stroke();

        // Draw line chart for station count
        ctx.beginPath();
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 2;
        history.forEach((point, i) => {
            const x = padding.left + ((point.timestamp - minTime) / timeRange) * chartW;
            const y = h - padding.bottom - ((point.rf_station_count || 0) / maxCount) * chartH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Fill area under curve
        ctx.lineTo(padding.left + chartW, h - padding.bottom);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.closePath();
        ctx.fillStyle = 'rgba(88, 166, 255, 0.1)';
        ctx.fill();

        // Draw max distance on secondary axis
        const maxDists = history.map(p => p.max_distance_km || 0);
        const maxDistVal = Math.max(...maxDists, 1);

        ctx.beginPath();
        ctx.strokeStyle = '#3fb950';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        history.forEach((point, i) => {
            const x = padding.left + ((point.timestamp - minTime) / timeRange) * chartW;
            const y = h - padding.bottom - ((point.max_distance_km || 0) / maxDistVal) * chartH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);

        // X-axis time labels
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        const numLabels = 6;
        for (let i = 0; i <= numLabels; i++) {
            const t = minTime + (timeRange * i / numLabels);
            const x = padding.left + (chartW * i / numLabels);
            const d = new Date(t * 1000);
            ctx.fillText(d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), x, h - padding.bottom + 14);
        }

        // Legend
        ctx.fillStyle = '#58a6ff';
        ctx.fillRect(padding.left + 10, padding.top + 2, 12, 3);
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Stations', padding.left + 26, padding.top + 7);

        ctx.fillStyle = '#3fb950';
        ctx.fillRect(padding.left + 90, padding.top + 2, 12, 3);
        ctx.fillStyle = '#8b949e';
        ctx.fillText('Max Dist', padding.left + 106, padding.top + 7);
    }

    async function fetchPropagationHistory() {
        try {
            const resp = await fetch('/api/propagation/history?hours=24');
            const data = await resp.json();
            if (data.history) {
                drawPropHistoryChart(data.history);
            }
        } catch (e) {
            console.error('Failed to fetch propagation history:', e);
        }
    }

    // ── Uptime ─────────────────────────────────────────────────

    function updateUptime() {
        if (!uptimeStart) return;
        const seconds = Math.floor(Date.now() / 1000 - uptimeStart);
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        const str = `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        setTextById('footer-uptime', `Uptime: ${str}`);
    }

    // ── Helpers ────────────────────────────────────────────────

    function setTextById(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function showAlertNotification(alert) {
        // Create a floating notification banner
        const div = document.createElement('div');
        div.className = 'alert-notification';
        div.innerHTML = `<span class="alert-notif-icon">🚨</span> <b>Band Opening!</b> ` +
            `RF: ${alert.rf_stations} stations · Max: ${window.formatDist(alert.max_distance_km, 0)} · ` +
            `${(alert.level || '').toUpperCase()}`;
        document.body.appendChild(div);
        // Auto-dismiss after 15 seconds
        setTimeout(() => { div.classList.add('fade-out'); }, 12000);
        setTimeout(() => { div.remove(); }, 15000);
    }

    // ── About info ──────────────────────────────────────────────

    async function loadAboutInfo() {
        try {
            const resp = await fetch('/api/version');
            const data = await resp.json();
            const v = data.version || '1.0.0';
            const el1 = document.getElementById('about-version');
            const el2 = document.getElementById('about-version-detail');
            if (el1) el1.textContent = 'v' + v;
            if (el2) el2.textContent = v;
        } catch (e) { /* keep static defaults */ }
    }

    // ── Font management ──────────────────────────────────────────

    function applyFont(fontFamily) {
        if (fontFamily) {
            document.documentElement.style.setProperty('--font-family', fontFamily);
        } else {
            document.documentElement.style.removeProperty('--font-family');
        }
    }

    // Apply saved font on initial load
    (async function initFont() {
        try {
            const resp = await fetch('/api/config');
            const cfg = await resp.json();
            applyFont(cfg.web?.font_family || '');
            window._ghostMinutes = cfg.web?.ghost_after_minutes ?? 60;
            window._expireMinutes = cfg.web?.expire_after_minutes ?? 0;
        } catch (e) { /* use default */ }
    })();

    // ── Settings load/save ─────────────────────────────────────

    async function loadSettings() {
        try {
            const resp = await fetch('/api/config');
            const cfg = await resp.json();

            // Station
            setVal('cfg-callsign', cfg.station?.callsign);
            setVal('cfg-ssid', cfg.station?.ssid);
            setVal('cfg-latitude', cfg.station?.latitude);
            setVal('cfg-longitude', cfg.station?.longitude);
            setVal('cfg-symbol-table', cfg.station?.symbol_table);
            setVal('cfg-symbol-code', cfg.station?.symbol_code);
            setVal('cfg-comment', cfg.station?.comment);
            setVal('cfg-beacon-interval', Math.round((cfg.station?.beacon_interval || 0) / 60));
            setVal('cfg-beacon-path', cfg.station?.beacon_path || 'WIDE1-1');

            // Digipeater
            setChk('cfg-digi-enabled', cfg.digipeater?.enabled);
            setVal('cfg-digi-aliases', (cfg.digipeater?.aliases || []).join(', '));
            setVal('cfg-digi-dedupe', parseFloat(((cfg.digipeater?.dedupe_interval || 0) / 60).toFixed(1)));

            // IGate
            setChk('cfg-igate-enabled', cfg.igate?.enabled);
            setChk('cfg-igate-rf2is', cfg.igate?.rf_to_is);
            setChk('cfg-igate-is2rf', cfg.igate?.is_to_rf);

            // APRS-IS
            setChk('cfg-is-enabled', cfg.aprs_is?.enabled);
            setVal('cfg-is-server', cfg.aprs_is?.server);
            setVal('cfg-is-port', cfg.aprs_is?.port);
            setVal('cfg-is-passcode', cfg.aprs_is?.passcode);
            parseFilterIntoFields(cfg.aprs_is?.filter || '');

            // KISS Serial
            setChk('cfg-ks-enabled', cfg.kiss_serial?.enabled);
            setVal('cfg-ks-port', cfg.kiss_serial?.port);
            setVal('cfg-ks-baud', cfg.kiss_serial?.baudrate);

            // KISS TCP
            setChk('cfg-kt-enabled', cfg.kiss_tcp?.enabled);
            setVal('cfg-kt-host', cfg.kiss_tcp?.host);
            setVal('cfg-kt-port', cfg.kiss_tcp?.port);

            // Web
            setVal('cfg-web-host', cfg.web?.host);
            setVal('cfg-web-port', cfg.web?.port);
            setVal('cfg-web-font', cfg.web?.font_family || '');
            applyFont(cfg.web?.font_family || '');
            setVal('cfg-web-ghost', cfg.web?.ghost_after_minutes ?? 60);
            window._ghostMinutes = cfg.web?.ghost_after_minutes ?? 60;
            window.pvMap?.ghostStaleMarkers(window._ghostMinutes);
            setVal('cfg-web-expire', cfg.web?.expire_after_minutes ?? 0);
            window._expireMinutes = cfg.web?.expire_after_minutes ?? 0;

            // Tracking
            setVal('cfg-track-age', Math.round((cfg.tracking?.max_station_age || 0) / 60));
            setVal('cfg-track-cleanup', Math.round((cfg.tracking?.cleanup_interval || 0) / 60));

            // Alerts
            setChk('cfg-alerts-enabled', cfg.alerts?.enabled);
            setVal('cfg-alerts-min-stations', cfg.alerts?.min_stations);
            setVal('cfg-alerts-min-dist', Math.round(window.distToDisplay(cfg.alerts?.min_distance_km || 0)));
            setVal('cfg-alerts-cooldown', Math.round((cfg.alerts?.cooldown_seconds || 0) / 60));
            setVal('cfg-alerts-quiet-start', cfg.alerts?.quiet_start || '');
            setVal('cfg-alerts-quiet-end', cfg.alerts?.quiet_end || '');
            setChk('cfg-alerts-msg-discord', cfg.alerts?.msg_discord_enabled);
            setChk('cfg-alerts-msg-email', cfg.alerts?.msg_email_enabled);
            setChk('cfg-alerts-msg-sms', cfg.alerts?.msg_sms_enabled);
            setChk('cfg-alerts-discord', cfg.alerts?.discord_enabled);
            setVal('cfg-alerts-discord-url', cfg.alerts?.discord_webhook_url);
            setChk('cfg-alerts-email', cfg.alerts?.email_enabled);
            setVal('cfg-alerts-smtp', cfg.alerts?.email_smtp_server);
            setVal('cfg-alerts-smtp-port', cfg.alerts?.email_smtp_port);
            setVal('cfg-alerts-email-from', cfg.alerts?.email_from);
            setVal('cfg-alerts-email-to', cfg.alerts?.email_to);
            setVal('cfg-alerts-email-pw', cfg.alerts?.email_password);
            setChk('cfg-alerts-sms', cfg.alerts?.sms_enabled);
            setVal('cfg-alerts-sms-addr', cfg.alerts?.sms_gateway_address);

            // Weather
            setChk('cfg-wx-enabled', cfg.weather?.enabled);
            setVal('cfg-wx-location', cfg.weather?.location_code);
            setVal('cfg-wx-range', cfg.weather?.alert_range_miles);
            setVal('cfg-wx-refresh', cfg.weather?.refresh_minutes);

        } catch (e) {
            console.error('Failed to load settings:', e);
        }

        // Update icon picker preview with loaded symbol
        window.pvIconPicker.updatePreviewFromConfig();
    }

    async function saveSettings() {
        const btn = document.getElementById('btn-save-settings');
        const statusEl = document.getElementById('settings-status');
        if (btn) btn.disabled = true;

        const body = {
            station: {
                callsign: (getVal('cfg-callsign') || '').toUpperCase(),
                ssid: getVal('cfg-ssid'),
                latitude: getVal('cfg-latitude'),
                longitude: getVal('cfg-longitude'),
                symbol_table: getVal('cfg-symbol-table'),
                symbol_code: getVal('cfg-symbol-code'),
                comment: getVal('cfg-comment'),
                beacon_interval: (parseInt(getVal('cfg-beacon-interval')) || 0) * 60,
                beacon_path: getVal('cfg-beacon-path'),
            },
            digipeater: {
                enabled: getChk('cfg-digi-enabled'),
                aliases: getVal('cfg-digi-aliases'),
                dedupe_interval: Math.round((parseFloat(getVal('cfg-digi-dedupe')) || 0) * 60),
            },
            igate: {
                enabled: getChk('cfg-igate-enabled'),
                rf_to_is: getChk('cfg-igate-rf2is'),
                is_to_rf: getChk('cfg-igate-is2rf'),
            },
            aprs_is: {
                enabled: getChk('cfg-is-enabled'),
                server: getVal('cfg-is-server'),
                port: getVal('cfg-is-port'),
                passcode: getVal('cfg-is-passcode'),
                filter: buildFilterString(),
            },
            kiss_serial: {
                enabled: getChk('cfg-ks-enabled'),
                port: getVal('cfg-ks-port'),
                baudrate: getVal('cfg-ks-baud'),
            },
            kiss_tcp: {
                enabled: getChk('cfg-kt-enabled'),
                host: getVal('cfg-kt-host'),
                port: getVal('cfg-kt-port'),
            },
            web: {
                host: getVal('cfg-web-host'),
                port: getVal('cfg-web-port'),
                font_family: getVal('cfg-web-font') || '',
                ghost_after_minutes: parseInt(getVal('cfg-web-ghost')) || 0,
                expire_after_minutes: parseInt(getVal('cfg-web-expire')) || 0,
            },
            tracking: {
                max_station_age: (parseInt(getVal('cfg-track-age')) || 0) * 60,
                cleanup_interval: (parseInt(getVal('cfg-track-cleanup')) || 0) * 60,
            },
            alerts: {
                enabled: getChk('cfg-alerts-enabled'),
                min_stations: getVal('cfg-alerts-min-stations'),
                min_distance_km: Math.round(window.displayToDist(parseFloat(getVal('cfg-alerts-min-dist')) || 0)),
                cooldown_seconds: (parseInt(getVal('cfg-alerts-cooldown')) || 0) * 60,
                quiet_start: getVal('cfg-alerts-quiet-start') || '',
                quiet_end: getVal('cfg-alerts-quiet-end') || '',
                msg_notify_enabled: getChk('cfg-alerts-msg-discord') || getChk('cfg-alerts-msg-email') || getChk('cfg-alerts-msg-sms'),
                msg_discord_enabled: getChk('cfg-alerts-msg-discord'),
                msg_email_enabled: getChk('cfg-alerts-msg-email'),
                msg_sms_enabled: getChk('cfg-alerts-msg-sms'),
                discord_enabled: getChk('cfg-alerts-discord'),
                discord_webhook_url: getVal('cfg-alerts-discord-url'),
                email_enabled: getChk('cfg-alerts-email'),
                email_smtp_server: getVal('cfg-alerts-smtp'),
                email_smtp_port: getVal('cfg-alerts-smtp-port'),
                email_from: getVal('cfg-alerts-email-from'),
                email_to: getVal('cfg-alerts-email-to'),
                email_password: getVal('cfg-alerts-email-pw'),
                sms_enabled: getChk('cfg-alerts-sms'),
                sms_gateway_address: getVal('cfg-alerts-sms-addr'),
            },
            weather: {
                enabled: getChk('cfg-wx-enabled'),
                location_code: getVal('cfg-wx-location'),
                alert_range_miles: getVal('cfg-wx-range'),
                refresh_minutes: getVal('cfg-wx-refresh'),
            },
        };

        try {
            const resp = await fetch('/api/config/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const result = await resp.json();

            if (statusEl) {
                statusEl.style.display = 'block';
                const cls = result.success
                    ? (result.needRestart ? 'warning' : 'success')
                    : 'error';
                statusEl.className = 'settings-status ' + cls;
                statusEl.textContent = result.message || (result.success ? 'Saved!' : 'Error saving.');
                const delay = result.needRestart ? 10000 : 5000;
                setTimeout(() => { statusEl.style.display = 'none'; }, delay);
            }
        } catch (e) {
            console.error('Failed to save settings:', e);
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.className = 'settings-status error';
                statusEl.textContent = 'Network error saving configuration.';
                setTimeout(() => { statusEl.style.display = 'none'; }, 5000);
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    function setVal(id, val) {
        const el = document.getElementById(id);
        if (el && val !== undefined && val !== null) el.value = val;
    }

    function setChk(id, val) {
        const el = document.getElementById(id);
        if (el) el.checked = !!val;
    }

    function getVal(id) {
        const el = document.getElementById(id);
        return el ? el.value : '';
    }

    function getChk(id) {
        const el = document.getElementById(id);
        return el ? el.checked : false;
    }

    // ── APRS-IS filter helpers ──────────────────────────────────

    /**
     * Parse a stored filter string like "r/35.1234/-80.5678/160.9 b/CALL" into
     * the range-miles field and extra-filters field.
     * APRS-IS range filter: r/lat/lon/range_km
     */
    function parseFilterIntoFields(filterStr) {
        const rangeEl = document.getElementById('cfg-is-range-miles');
        const extraEl = document.getElementById('cfg-is-extra-filters');
        if (!rangeEl || !extraEl) return;

        // Match r/lat/lon/km pattern
        const rMatch = filterStr.match(/r\/([\-\d.]+)\/([\-\d.]+)\/([\d.]+)/);
        const parts = filterStr.split(/\s+/).filter(Boolean);

        if (rMatch) {
            const rangeKm = parseFloat(rMatch[3]);
            const rangeMiles = Math.round(rangeKm / 1.60934);
            rangeEl.value = rangeMiles;
            // Everything except the r/ part goes into extra filters
            const extras = parts.filter(p => !p.startsWith('r/')).join(' ');
            extraEl.value = extras;
        } else {
            rangeEl.value = '';
            extraEl.value = filterStr;
        }
        updateFilterPreview();
    }

    /**
     * Build the combined APRS-IS filter string from range-miles + lat/lon + extras.
     */
    function buildFilterString() {
        const miles = parseFloat(getVal('cfg-is-range-miles'));
        const lat = parseFloat(getVal('cfg-latitude'));
        const lng = parseFloat(getVal('cfg-longitude'));
        const extras = getVal('cfg-is-extra-filters').trim();

        let parts = [];

        if (miles > 0 && !isNaN(lat) && !isNaN(lng) && (lat !== 0 || lng !== 0)) {
            const rangeKm = (miles * 1.60934).toFixed(1);
            parts.push(`r/${lat.toFixed(4)}/${lng.toFixed(4)}/${rangeKm}`);
        }

        if (extras) {
            parts.push(extras);
        }

        return parts.join(' ');
    }

    /**
     * Update the preview spans showing the generated filter.
     */
    function updateFilterPreview() {
        const combined = buildFilterString();

        const miles = parseFloat(getVal('cfg-is-range-miles'));
        const lat = parseFloat(getVal('cfg-latitude'));
        const lng = parseFloat(getVal('cfg-longitude'));

        const rangePreview = document.getElementById('cfg-is-range-preview');
        const combinedPreview = document.getElementById('cfg-is-filter-combined');

        if (rangePreview) {
            if (miles > 0 && !isNaN(lat) && !isNaN(lng) && (lat !== 0 || lng !== 0)) {
                const rangeKm = (miles * 1.60934).toFixed(1);
                rangePreview.textContent = `r/${lat.toFixed(4)}/${lng.toFixed(4)}/${rangeKm}`;
                rangePreview.title = `${miles} mi = ${rangeKm} km around ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
            } else if (miles > 0) {
                rangePreview.textContent = 'Set lat/lon first';
                rangePreview.title = '';
            } else {
                rangePreview.textContent = '\u2014';
                rangePreview.title = '';
            }
        }

        if (combinedPreview) {
            combinedPreview.textContent = combined || '\u2014';
            combinedPreview.title = combined;
        }

        // Also update hidden field
        setVal('cfg-is-filter', combined);
    }

    // Live-update preview when any relevant field changes
    ['cfg-is-range-miles', 'cfg-is-extra-filters', 'cfg-latitude', 'cfg-longitude'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', updateFilterPreview);
        document.getElementById(id)?.addEventListener('change', updateFilterPreview);
    });

    // ── Init settings ──────────────────────────────────────────

    // Load settings when settings tab is clicked
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.tab === 'tab-settings') {
                loadSettings();
            }
            if (btn.dataset.tab === 'tab-analytics') {
                window.pvAnalytics.loadAllData();
            }
            if (btn.dataset.tab === 'tab-messages') {
                window.pvMessages.loadMessages();
            }
            if (btn.dataset.tab === 'tab-about') {
                loadAboutInfo();
            }
        });
    });

    // Save button
    document.getElementById('btn-save-settings')?.addEventListener('click', saveSettings);

    // Live font preview when changed in settings
    document.getElementById('cfg-web-font')?.addEventListener('change', (e) => {
        applyFont(e.target.value || '');
    });

    // Clear packets button
    document.getElementById('btn-clear-packets')?.addEventListener('click', () => {
        window.pvStations.clearPackets();
    });

    // Help modal
    document.getElementById('btn-open-help')?.addEventListener('click', () => {
        document.getElementById('help-modal').style.display = 'flex';
    });
    document.getElementById('help-modal-close')?.addEventListener('click', () => {
        document.getElementById('help-modal').style.display = 'none';
    });
    document.getElementById('help-modal')?.addEventListener('click', (e) => {
        if (e.target.id === 'help-modal') e.target.style.display = 'none';
    });

})();
