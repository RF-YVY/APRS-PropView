/**
 * Analytics module — Longest Path, Heatmap, Reliability, Best Times, Alerts.
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────
    let _initialized = false;
    const ANALYTICS_SECTION_KEY = 'pvAnalyticsSection';

    // ── Initialization ─────────────────────────────────────────

    function init() {
        if (_initialized) return;
        _initialized = true;

        // Sub-tab switching within Analytics
        document.querySelectorAll('.analytics-subtab').forEach(btn => {
            btn.addEventListener('click', () => {
                const sectionId = btn.dataset.section;
                setActiveSection(sectionId);
                loadSectionData(sectionId);
            });
        });

        // Filter change handlers
        document.getElementById('leaderboard-hours')?.addEventListener('change', () => loadLeaderboard());
        document.getElementById('heatmap-hours')?.addEventListener('change', () => loadHeatmap());
        document.getElementById('reliability-hours')?.addEventListener('change', () => loadReliability());
        document.getElementById('besttime-days')?.addEventListener('change', () => loadBestTimes());
        document.getElementById('bearing-hours')?.addEventListener('change', () => loadBearingSectors());
        document.getElementById('first-heard-hours')?.addEventListener('change', () => loadFirstHeard());

        const savedSection = localStorage.getItem(ANALYTICS_SECTION_KEY);
        if (savedSection && document.getElementById(savedSection)) {
            setActiveSection(savedSection);
        }
    }

    function setActiveSection(sectionId) {
        document.querySelectorAll('.analytics-subtab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.analytics-section').forEach(s => s.classList.remove('active'));
        document.querySelector(`.analytics-subtab[data-section="${sectionId}"]`)?.classList.add('active');
        document.getElementById(sectionId)?.classList.add('active');
        localStorage.setItem(ANALYTICS_SECTION_KEY, sectionId);
    }

    function loadSectionData(sectionId) {
        switch (sectionId) {
            case 'sec-leaderboard': loadLeaderboard(); break;
            case 'sec-heatmap': loadHeatmap(); break;
            case 'sec-reliability': loadReliability(); break;
            case 'sec-besttime': loadBestTimes(); break;
            case 'sec-alerts': loadAlerts(); break;
            case 'sec-anomaly': loadAnomaly(); break;
            case 'sec-bearing': loadBearingSectors(); break;
            case 'sec-historical': loadHistorical(); break;
            case 'sec-sporadic-e': loadSporadicE(); break;
            case 'sec-first-heard': loadFirstHeard(); break;
        }
    }

    function loadAllData() {
        // Load whichever section is currently active
        const active = document.querySelector('.analytics-section.active');
        if (active) loadSectionData(active.id);
    }

    // ── Longest Path Leaderboard ───────────────────────────────

    async function loadLeaderboard() {
        const hours = document.getElementById('leaderboard-hours')?.value || 24;
        const container = document.getElementById('leaderboard-list');
        if (!container) return;

        try {
            const resp = await fetch(`/api/analytics/longest-paths?hours=${hours}&limit=25`);
            const data = await resp.json();

            if (!data.paths || data.paths.length === 0) {
                container.innerHTML = '<div class="analytics-empty">No RF stations with distance data in this time window.</div>';
                return;
            }

            let html = '<div class="leaderboard-table">';
            html += '<div class="lb-header"><span class="lb-rank">#</span><span class="lb-call">Station</span><span class="lb-dist">Distance</span><span class="lb-time">Last Heard</span></div>';

            data.paths.forEach(p => {
                const medal = p.rank <= 3 ? ['🥇', '🥈', '🥉'][p.rank - 1] : p.rank;
                const time = new Date(p.last_heard * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                const distKm = p.distance_km.toFixed(1);
                const distMi = p.distance_mi.toFixed(1);

                html += `<div class="lb-row${p.rank <= 3 ? ' lb-top' : ''}">`;
                html += `<span class="lb-rank">${medal}</span>`;
                html += `<span class="lb-call">${_esc(p.callsign)}</span>`;
                html += `<span class="lb-dist">${window.formatDist(p.distance_km)}</span>`;
                html += `<span class="lb-time">${time}</span>`;
                html += `</div>`;
            });

            html += '</div>';
            container.innerHTML = html;

        } catch (e) {
            container.innerHTML = '<div class="analytics-empty">Failed to load leaderboard.</div>';
            console.error('Leaderboard error:', e);
        }
    }

    // ── Propagation Heatmap ────────────────────────────────────

    async function loadHeatmap() {
        const hours = document.getElementById('heatmap-hours')?.value || 24;

        try {
            const resp = await fetch(`/api/analytics/heatmap?hours=${hours}`);
            const data = await resp.json();

            drawHeatmapChart('heatmap-stations-chart', data.grid, 'avg_stations', 'Avg Stations');
            drawHeatmapChart('heatmap-distance-chart', data.grid, 'max_distance_km', `Max Distance (${window.distLabel()})`);

        } catch (e) {
            console.error('Heatmap error:', e);
        }
    }

    function drawHeatmapChart(canvasId, grid, field, label) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !grid || grid.length === 0) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 10, bottom: 30, left: 40 };

        ctx.clearRect(0, 0, w, h);

        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;
        const barW = chartW / 24 - 1;

        const values = grid.map(g => g[field] || 0);
        const maxVal = Math.max(...values, 1);

        // Draw axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.lineTo(w - padding.right, h - padding.bottom);
        ctx.stroke();

        // Draw bars with heatmap colors
        grid.forEach((g, i) => {
            const val = g[field] || 0;
            const ratio = val / maxVal;
            const barH = ratio * chartH;
            const x = padding.left + (i * (chartW / 24)) + 0.5;
            const y = h - padding.bottom - barH;

            // Color gradient: dark blue → cyan → green → yellow → red
            const color = heatColor(ratio);
            ctx.fillStyle = color;
            ctx.fillRect(x, y, barW, barH);

            // Value label on tall bars
            if (ratio > 0.15 && val > 0) {
                ctx.fillStyle = '#e6edf3';
                ctx.font = '9px sans-serif';
                ctx.textAlign = 'center';
                const dv = field.includes('distance') ? (window.convertDist ? window.convertDist(val) : val) : val;
                const displayVal = dv >= 100 ? Math.round(dv) : dv.toFixed(1);
                ctx.fillText(displayVal, x + barW / 2, y - 3);
            }
        });

        // X-axis labels (every 3 hours)
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        for (let i = 0; i < 24; i += 3) {
            const x = padding.left + (i * (chartW / 24)) + barW / 2;
            ctx.fillText(`${i.toString().padStart(2, '0')}`, x, h - padding.bottom + 14);
        }

        // Y-axis label
        ctx.fillStyle = '#6e7681';
        ctx.font = '10px sans-serif';
        ctx.save();
        ctx.translate(12, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textAlign = 'center';
        ctx.fillText(label, 0, 0);
        ctx.restore();
    }

    function heatColor(ratio) {
        // 0 = cold (dark blue), 1 = hot (red)
        if (ratio <= 0) return '#1a1e2e';
        if (ratio < 0.2) return '#1e3a5f';
        if (ratio < 0.4) return '#0d7377';
        if (ratio < 0.6) return '#3fb950';
        if (ratio < 0.8) return '#d29922';
        return '#f85149';
    }

    // ── Station Reliability ────────────────────────────────────

    async function loadReliability() {
        const hours = document.getElementById('reliability-hours')?.value || 24;
        const container = document.getElementById('reliability-list');
        if (!container) return;

        try {
            const resp = await fetch(`/api/analytics/reliability?hours=${hours}`);
            const data = await resp.json();

            if (!data.stations || data.stations.length === 0) {
                container.innerHTML = '<div class="analytics-empty">No stations with enough packets to score.</div>';
                return;
            }

            let html = '<div class="reliability-table">';
            html += '<div class="rel-header"><span class="rel-grade">Grade</span><span class="rel-call">Station</span><span class="rel-score">Score</span><span class="rel-pkts">Packets</span><span class="rel-int">Avg Interval</span></div>';

            data.stations.forEach(s => {
                const gradeClass = `grade-${s.grade.toLowerCase()}`;
                const intLabel = s.avg_interval_min > 0 ? `${s.avg_interval_min} min` : '—';
                const distLabel = s.distance_km ? window.formatDist(s.distance_km) : '';

                html += `<div class="rel-row">`;
                html += `<span class="rel-grade ${gradeClass}">${s.grade}</span>`;
                html += `<span class="rel-call">${_esc(s.callsign)}<span class="rel-dist">${distLabel}</span></span>`;
                html += `<span class="rel-score">${s.score}</span>`;
                html += `<span class="rel-pkts">${s.packet_count}</span>`;
                html += `<span class="rel-int">${intLabel}</span>`;
                html += `</div>`;
            });

            html += '</div>';
            container.innerHTML = html;

        } catch (e) {
            container.innerHTML = '<div class="analytics-empty">Failed to load reliability data.</div>';
            console.error('Reliability error:', e);
        }
    }

    // ── Best Time of Day ───────────────────────────────────────

    async function loadBestTimes() {
        const days = document.getElementById('besttime-days')?.value || 7;

        try {
            const resp = await fetch(`/api/analytics/best-times?days=${days}`);
            const data = await resp.json();

            // Best hours summary
            const summaryEl = document.getElementById('best-hours-summary');
            if (summaryEl && data.best_hours && data.best_hours.length > 0) {
                let html = '<div class="best-hours-cards">';
                data.best_hours.forEach((h, i) => {
                    const medals = ['🥇', '🥈', '🥉'];
                    html += `<div class="best-hour-card">`;
                    html += `<div class="best-hour-medal">${medals[i] || ''}</div>`;
                    html += `<div class="best-hour-time">${h.label}</div>`;
                    html += `<div class="best-hour-score">Score: ${h.composite_score}</div>`;
                    html += `<div class="best-hour-detail">${h.avg_stations} avg stations \u00b7 ${window.formatDist(h.avg_max_distance_km, 0)} max</div>`;
                    html += `</div>`;
                });
                html += '</div>';
                summaryEl.innerHTML = html;
            } else if (summaryEl) {
                summaryEl.innerHTML = '<div class="analytics-empty">Not enough data. Check back once propagation data accumulates.</div>';
            }

            // Hourly chart
            drawBestTimeChart(data.hours || []);

            // Day of week stats
            const dowEl = document.getElementById('dow-stats');
            if (dowEl && data.day_of_week) {
                let html = '<div class="dow-grid">';
                data.day_of_week.forEach(d => {
                    html += `<div class="dow-card">`;
                    html += `<div class="dow-name">${d.name.substring(0, 3)}</div>`;
                    html += `<div class="dow-val">${d.avg_stations} stn</div>`;
                    html += `<div class="dow-val">${d.avg_max_distance_km} km</div>`;
                    html += `</div>`;
                });
                html += '</div>';
                dowEl.innerHTML = html;
            }

        } catch (e) {
            console.error('Best times error:', e);
        }
    }

    function drawBestTimeChart(hours) {
        const canvas = document.getElementById('besttime-chart');
        if (!canvas || !hours || hours.length === 0) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 10, bottom: 30, left: 40 };

        ctx.clearRect(0, 0, w, h);

        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;
        const barW = chartW / 24 - 1;

        const scores = hours.map(h => h.composite_score || 0);
        const maxScore = Math.max(...scores, 1);

        // Axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.lineTo(w - padding.right, h - padding.bottom);
        ctx.stroke();

        // Bars
        hours.forEach((hr, i) => {
            const score = hr.composite_score || 0;
            const ratio = score / maxScore;
            const barH = ratio * chartH;
            const x = padding.left + (i * (chartW / 24)) + 0.5;
            const y = h - padding.bottom - barH;

            // Score-based color
            let color;
            if (score >= 75) color = '#58a6ff';
            else if (score >= 50) color = '#3fb950';
            else if (score >= 25) color = '#d29922';
            else if (score > 0) color = '#f85149';
            else color = '#21262d';

            ctx.fillStyle = color;
            ctx.fillRect(x, y, barW, barH);

            if (score > 0) {
                ctx.fillStyle = '#e6edf3';
                ctx.font = '8px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(Math.round(score), x + barW / 2, y - 3);
            }
        });

        // X-axis
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        for (let i = 0; i < 24; i += 3) {
            const x = padding.left + (i * (chartW / 24)) + barW / 2;
            ctx.fillText(`${i.toString().padStart(2, '0')}:00`, x, h - padding.bottom + 14);
        }

        // Y label
        ctx.fillStyle = '#6e7681';
        ctx.font = '10px sans-serif';
        ctx.save();
        ctx.translate(12, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textAlign = 'center';
        ctx.fillText('Score', 0, 0);
        ctx.restore();
    }

    // ── Alerts ─────────────────────────────────────────────────

    async function loadAlerts() {
        // Status badge
        try {
            const statusResp = await fetch('/api/alerts/status');
            const status = await statusResp.json();
            const badge = document.getElementById('alert-status-badge');
            if (badge) {
                if (status.enabled) {
                    const bandOpen = status.my_band_open || status.regional_band_open;
                    badge.textContent = bandOpen ? '🔴 BAND OPEN' : '🟢 Monitoring';
                    badge.className = 'alert-badge ' + (bandOpen ? 'open' : 'on');
                } else {
                    badge.textContent = 'OFF';
                    badge.className = 'alert-badge off';
                }
            }
        } catch (e) { /* ignore */ }

        // History
        try {
            const histResp = await fetch('/api/alerts/history');
            const data = await histResp.json();
            const container = document.getElementById('alert-history');
            if (!container) return;

            if (!data.alerts || data.alerts.length === 0) {
                container.innerHTML = '<div class="analytics-empty">No alerts triggered yet.</div>';
                return;
            }

            let html = '';
            data.alerts.forEach(a => {
                const time = new Date(a.timestamp * 1000).toLocaleString();
                html += `<div class="alert-item">`;
                html += `<div class="alert-time">${time}</div>`;
                html += `<div class="alert-msg">${_esc(a.message).replace(/\n/g, '<br>')}</div>`;
                html += `</div>`;
            });
            container.innerHTML = html;

        } catch (e) {
            console.error('Alert history error:', e);
        }
    }

    // ── Anomaly Detection ────────────────────────────────────────

    async function loadAnomaly() {
        const container = document.getElementById('anomaly-status');
        if (!container) return;

        try {
            const resp = await fetch('/api/analytics/anomaly');
            const data = await resp.json();

            const level = data.anomaly_level || 'normal';
            const score = (data.anomaly_score || 0).toFixed(1);
            const countPct = (data.count_pct_above_avg || 0).toFixed(0);
            const distPct = (data.dist_pct_above_avg || 0).toFixed(0);

            const levelColors = {
                extreme: '#f85149',
                significant: '#d29922',
                notable: '#58a6ff',
                slight: '#3fb950',
                normal: '#484f58'
            };
            const color = levelColors[level] || '#484f58';

            let html = `<div class="anomaly-card" style="border-left: 4px solid ${color};">`;
            html += `<div class="anomaly-level" style="color:${color};">${level.toUpperCase()}</div>`;
            html += `<div class="anomaly-score">${score}σ from baseline</div>`;
            html += `<div class="anomaly-details">`;
            html += `<span>Stations: <b>${countPct >= 0 ? '+' : ''}${countPct}%</b> vs avg</span>`;
            html += `<span>Distance: <b>${distPct >= 0 ? '+' : ''}${distPct}%</b> vs avg</span>`;
            html += `</div>`;
            html += `</div>`;

            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = '<div class="analytics-empty">Failed to load anomaly data.</div>';
            console.error('Anomaly error:', e);
        }
    }

    // ── Bearing Sectors ───────────────────────────────────────────

    async function loadBearingSectors() {
        const hours = document.getElementById('bearing-hours')?.value || 24;
        const container = document.getElementById('bearing-sector-list');
        if (!container) return;

        try {
            const resp = await fetch(`/api/analytics/bearing-sectors?hours=${hours}`);
            const data = await resp.json();

            if (!data.sectors || data.sectors.length === 0) {
                container.innerHTML = '<div class="analytics-empty">No directional data yet.</div>';
                return;
            }

            // Draw radar chart
            drawBearingRadar(data.sectors);

            // Sector list
            let html = '';
            data.sectors.forEach(s => {
                if (s.station_count === 0) return;
                const isDominant = data.dominant_sectors && data.dominant_sectors.includes(s.sector);
                html += `<div class="bearing-sector-item${isDominant ? ' dominant' : ''}">`;
                html += `<span class="sector-name">${s.sector}</span>`;
                html += `<span class="sector-count">${s.station_count} stn</span>`;
                html += `<span class="sector-dist">max ${window.formatDist(s.max_distance_km)}</span>`;
                if (s.top_stations && s.top_stations.length > 0) {
                    html += `<span class="sector-calls">${s.top_stations.map(t => _esc(t.callsign)).join(', ')}</span>`;
                }
                html += `</div>`;
            });

            container.innerHTML = html || '<div class="analytics-empty">No active sectors.</div>';
        } catch (e) {
            container.innerHTML = '<div class="analytics-empty">Failed to load sector data.</div>';
            console.error('Bearing error:', e);
        }
    }

    function drawBearingRadar(sectors) {
        const canvas = document.getElementById('bearing-radar-chart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const cx = w / 2;
        const cy = h / 2;
        const r = Math.min(cx, cy) - 30;

        ctx.clearRect(0, 0, w, h);

        // Background rings
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 0.5;
        for (let i = 1; i <= 4; i++) {
            ctx.beginPath();
            ctx.arc(cx, cy, r * (i / 4), 0, 2 * Math.PI);
            ctx.stroke();
        }

        // Sector labels
        const sectorAngles = { 'N': -90, 'NE': -45, 'E': 0, 'SE': 45, 'S': 90, 'SW': 135, 'W': 180, 'NW': -135 };
        ctx.fillStyle = '#8b949e';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        Object.entries(sectorAngles).forEach(([name, deg]) => {
            const rad = deg * Math.PI / 180;
            const lx = cx + (r + 18) * Math.cos(rad);
            const ly = cy + (r + 18) * Math.sin(rad);
            ctx.fillText(name, lx, ly);
        });

        // Find max for scaling
        const maxDist = Math.max(...sectors.map(s => s.max_distance_km || 0), 1);

        // Draw filled polygon
        ctx.beginPath();
        const sectorNames = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        sectorNames.forEach((name, i) => {
            const sector = sectors.find(s => s.sector === name) || { max_distance_km: 0 };
            const ratio = (sector.max_distance_km || 0) / maxDist;
            const rad = sectorAngles[name] * Math.PI / 180;
            const px = cx + r * ratio * Math.cos(rad);
            const py = cy + r * ratio * Math.sin(rad);
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        });
        ctx.closePath();
        ctx.fillStyle = 'rgba(88, 166, 255, 0.2)';
        ctx.fill();
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Draw dots
        sectorNames.forEach(name => {
            const sector = sectors.find(s => s.sector === name) || { max_distance_km: 0 };
            const ratio = (sector.max_distance_km || 0) / maxDist;
            const rad = sectorAngles[name] * Math.PI / 180;
            const px = cx + r * ratio * Math.cos(rad);
            const py = cy + r * ratio * Math.sin(rad);

            ctx.beginPath();
            ctx.arc(px, py, 4, 0, 2 * Math.PI);
            ctx.fillStyle = ratio > 0 ? '#58a6ff' : '#30363d';
            ctx.fill();
        });
    }

    // ── Historical Comparison ──────────────────────────────────────

    async function loadHistorical() {
        try {
            const resp = await fetch('/api/analytics/historical');
            const data = await resp.json();

            drawHistoricalChart('historical-count-chart', data, 'rf_station_count', 'Stations');
            drawHistoricalChart('historical-dist-chart', data, 'max_distance_km', `Distance (${window.distLabel()})`);
        } catch (e) {
            console.error('Historical error:', e);
        }
    }

    function drawHistoricalChart(canvasId, data, field, label) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;
        const padding = { top: 20, right: 10, bottom: 30, left: 45 };

        ctx.clearRect(0, 0, w, h);

        const chartW = w - padding.left - padding.right;
        const chartH = h - padding.top - padding.bottom;

        // Gather all values to find max
        const allVals = [];
        ['today', 'yesterday', 'week_avg', 'avg_7d'].forEach(key => {
            (data[key] || []).forEach(h => {
                const v = h[field] ?? (field === 'rf_station_count' ? (h.station_count || 0) : 0);
                allVals.push(field.includes('distance') && window.convertDist ? window.convertDist(v) : v);
            });
        });
        const maxVal = Math.max(...allVals, 1);

        // Axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, h - padding.bottom);
        ctx.lineTo(w - padding.right, h - padding.bottom);
        ctx.stroke();

        // Line series config
        const series = [
            { key: (data.week_avg ? 'week_avg' : 'avg_7d'), color: '#484f58', width: 1, dash: [4, 4], label: '7d avg' },
            { key: 'yesterday', color: '#d29922', width: 1.5, dash: [], label: 'Yesterday' },
            { key: 'today', color: '#58a6ff', width: 2, dash: [], label: 'Today' },
        ];

        series.forEach(s => {
            const points = data[s.key] || [];
            if (points.length === 0) return;

            ctx.beginPath();
            ctx.strokeStyle = s.color;
            ctx.lineWidth = s.width;
            ctx.setLineDash(s.dash);

            points.forEach((p, i) => {
                let v = p[field] ?? (field === 'rf_station_count' ? (p.station_count || 0) : 0);
                if (field.includes('distance') && window.convertDist) v = window.convertDist(v);
                const x = padding.left + (i / 23) * chartW;
                const y = h - padding.bottom - (v / maxVal) * chartH;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            ctx.stroke();
            ctx.setLineDash([]);
        });

        // Legend
        let lx = padding.left + 5;
        series.forEach(s => {
            ctx.fillStyle = s.color;
            ctx.fillRect(lx, padding.top - 14, 16, 3);
            ctx.fillStyle = '#8b949e';
            ctx.font = '9px sans-serif';
            ctx.fillText(s.label, lx + 20, padding.top - 10);
            lx += 70;
        });

        // X-axis
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        for (let i = 0; i < 24; i += 3) {
            const x = padding.left + (i / 23) * chartW;
            ctx.fillText(`${i.toString().padStart(2, '0')}`, x, h - padding.bottom + 14);
        }

        // Y label
        ctx.fillStyle = '#6e7681';
        ctx.font = '10px sans-serif';
        ctx.save();
        ctx.translate(12, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textAlign = 'center';
        ctx.fillText(label, 0, 0);
        ctx.restore();
    }

    // ── Sporadic-E Detection ──────────────────────────────────────

    async function loadSporadicE() {
        const statusEl = document.getElementById('es-status');
        const listEl = document.getElementById('es-candidates');
        if (!statusEl) return;

        try {
            const resp = await fetch('/api/analytics/sporadic-e');
            const data = await resp.json();

            const level = data.es_level || 'none';
            const score = (data.es_score ?? data.max_score ?? 0).toFixed(0);

            const levelConfig = {
                likely: { color: '#f85149', icon: '⚡' },
                possible: { color: '#d29922', icon: '⚡' },
                unlikely: { color: '#484f58', icon: '—' },
                none: { color: '#30363d', icon: '—' }
            };
            const cfg = levelConfig[level] || levelConfig.none;

            let html = `<div class="es-card" style="border-left: 4px solid ${cfg.color};">`;
            html += `<div class="es-level" style="color:${cfg.color};">${cfg.icon} ${level.toUpperCase()}</div>`;
            html += `<div class="es-score">Score: ${score}/100</div>`;
            html += `</div>`;
            statusEl.innerHTML = html;

            if (listEl && data.candidates && data.candidates.length > 0) {
                let chtml = '<h4>Candidate Stations</h4>';
                chtml += '<div class="es-candidate-list">';
                data.candidates.forEach(c => {
                    chtml += `<div class="es-candidate-item">`;
                    chtml += `<span class="es-c-call">${_esc(c.callsign)}</span>`;
                    chtml += `<span class="es-c-dist">${window.formatDist(c.distance_km)}</span>`;
                    const candidateScore = c.es_score ?? c.score ?? 0;
                    chtml += `<span class="es-c-score">score ${candidateScore}</span>`;
                    chtml += `</div>`;
                });
                chtml += '</div>';
                listEl.innerHTML = chtml;
            } else if (listEl) {
                listEl.innerHTML = '';
            }
        } catch (e) {
            statusEl.innerHTML = '<div class="analytics-empty">Failed to load Es data.</div>';
            console.error('Sporadic-E error:', e);
        }
    }

    // ── First Heard Log ───────────────────────────────────────────

    async function loadFirstHeard() {
        const hours = document.getElementById('first-heard-hours')?.value || 24;
        const container = document.getElementById('first-heard-list');
        if (!container) return;

        try {
            const resp = await fetch(`/api/first-heard?hours=${hours}`);
            const data = await resp.json();

            if (!data.log || data.log.length === 0) {
                container.innerHTML = '<div class="analytics-empty">No new stations heard in this time window.</div>';
                return;
            }

            let html = '<div class="first-heard-table">';
            html += '<div class="fh-header"><span class="fh-time">Time</span><span class="fh-call">Station</span><span class="fh-dist">Distance</span></div>';

            data.log.forEach(entry => {
                const time = new Date(entry.timestamp * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                const dist = entry.distance_km ? window.formatDist(entry.distance_km) : '—';
                html += `<div class="fh-row">`;
                html += `<span class="fh-time">${time}</span>`;
                html += `<span class="fh-call">${_esc(entry.callsign)}</span>`;
                html += `<span class="fh-dist">${dist}</span>`;
                html += `</div>`;
            });

            html += '</div>';
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = '<div class="analytics-empty">Failed to load first heard data.</div>';
            console.error('First heard error:', e);
        }
    }

    // ── Data Export ───────────────────────────────────────────────

    async function exportData(type, format) {
        try {
            const url = `/api/export/${type}?fmt=${format}`;
            if (format === 'csv') {
                window.open(url, '_blank');
                return;
            }
            const resp = await fetch(url);
            const data = await resp.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `${type}.json`;
            link.click();
            URL.revokeObjectURL(link.href);
        } catch (e) {
            console.error('Export error:', e);
            alert('Export failed — check console for details.');
        }
    }

    // ── Helpers ────────────────────────────────────────────────

    function _esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ── Public API ─────────────────────────────────────────────

    window.pvAnalytics = {
        init,
        loadAllData,
        loadLeaderboard,
        loadHeatmap,
        loadReliability,
        loadBestTimes,
        loadAlerts,
        loadAnomaly,
        loadBearingSectors,
        loadHistorical,
        loadSporadicE,
        loadFirstHeard,
        exportData,
    };

})();
