/**
 * Analytics module — Longest Path, Heatmap, Reliability, Best Times, Alerts.
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────
    let _initialized = false;

    // ── Initialization ─────────────────────────────────────────

    function init() {
        if (_initialized) return;
        _initialized = true;

        // Sub-tab switching within Analytics
        document.querySelectorAll('.analytics-subtab').forEach(btn => {
            btn.addEventListener('click', () => {
                const sectionId = btn.dataset.section;
                document.querySelectorAll('.analytics-subtab').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.analytics-section').forEach(s => s.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(sectionId)?.classList.add('active');

                // Load data for the activated section
                loadSectionData(sectionId);
            });
        });

        // Filter change handlers
        document.getElementById('leaderboard-hours')?.addEventListener('change', () => loadLeaderboard());
        document.getElementById('heatmap-hours')?.addEventListener('change', () => loadHeatmap());
        document.getElementById('reliability-hours')?.addEventListener('change', () => loadReliability());
        document.getElementById('besttime-days')?.addEventListener('change', () => loadBestTimes());
    }

    function loadSectionData(sectionId) {
        switch (sectionId) {
            case 'sec-leaderboard': loadLeaderboard(); break;
            case 'sec-heatmap': loadHeatmap(); break;
            case 'sec-reliability': loadReliability(); break;
            case 'sec-besttime': loadBestTimes(); break;
            case 'sec-alerts': loadAlerts(); break;
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
                html += `<span class="lb-dist" title="${distMi} mi">${distKm} km</span>`;
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
            drawHeatmapChart('heatmap-distance-chart', data.grid, 'max_distance_km', 'Max Distance (km)');

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
                const displayVal = val >= 100 ? Math.round(val) : val.toFixed(1);
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
                const distLabel = s.distance_km ? `${s.distance_km} km` : '';

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
                    html += `<div class="best-hour-detail">${h.avg_stations} avg stations · ${h.avg_max_distance_km} km max</div>`;
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
                    badge.textContent = status.band_open ? '🔴 BAND OPEN' : '🟢 Monitoring';
                    badge.className = 'alert-badge ' + (status.band_open ? 'open' : 'on');
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
    };

})();
