/**
 * Weather module — fetches and displays current weather + NWS severe alerts.
 */

window.pvWeather = (function () {
    'use strict';

    let refreshTimer = null;
    let lastAlertCount = 0;

    function init() {
        // Refresh button
        document.getElementById('wx-refresh-btn')?.addEventListener('click', () => {
            fetchWeather(true);
        });

        // Location lookup button in settings
        document.getElementById('btn-wx-resolve')?.addEventListener('click', lookupLocation);

        // Enter key in location field triggers lookup
        document.getElementById('cfg-wx-location')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                lookupLocation();
            }
        });

        // Force uppercase for ICAO codes
        document.getElementById('cfg-wx-location')?.addEventListener('input', (e) => {
            const v = e.target.value.trim();
            // If it looks like letters (ICAO), uppercase it
            if (/^[a-zA-Z]+$/.test(v)) {
                const start = e.target.selectionStart;
                const end = e.target.selectionEnd;
                e.target.value = v.toUpperCase();
                e.target.setSelectionRange(start, end);
            }
        });

        // Start fetch cycle — initial fetch after brief delay
        setTimeout(() => fetchWeather(), 2000);
    }

    async function fetchWeather(force) {
        try {
            const endpoint = force ? '/api/weather/refresh' : '/api/weather';
            const resp = await fetch(endpoint);
            const data = await resp.json();
            renderWeather(data);
            scheduleRefresh(data);
        } catch (e) {
            console.error('Weather fetch failed:', e);
        }
    }

    function scheduleRefresh(data) {
        if (refreshTimer) clearTimeout(refreshTimer);
        // Default 15 min, or configured interval
        const interval = (data?.current?.refresh_minutes || 15) * 60 * 1000;
        // Re-refresh weather periodically; alerts refresh more often (5 min)
        const alertInterval = 5 * 60 * 1000;
        const nextRefresh = Math.min(interval, alertInterval);
        refreshTimer = setTimeout(() => fetchWeather(), nextRefresh);
    }

    function renderWeather(data) {
        const banner = document.getElementById('wx-banner');
        const alertsContainer = document.getElementById('wx-alerts-container');

        if (!data || !data.enabled || !data.configured || !data.current) {
            if (banner) banner.style.display = 'none';
            if (alertsContainer) alertsContainer.innerHTML = '';
            return;
        }

        const wx = data.current;

        // Show current weather banner
        if (banner) banner.style.display = 'flex';

        setText('wx-icon', wx.icon || '❓');
        setText('wx-temp', wx.temperature_f != null ? Math.round(wx.temperature_f) + '°F' : '--°F');
        setText('wx-desc', wx.description || '--');
        setText('wx-feels', wx.feels_like_f != null ? Math.round(wx.feels_like_f) : '--');
        setText('wx-wind', formatWind(wx));
        setText('wx-humidity', wx.humidity != null ? Math.round(wx.humidity) : '--');
        setText('wx-pressure', wx.pressure_mb != null ? Math.round(wx.pressure_mb) : '--');
        setText('wx-location', wx.location_name || wx.location_code || '--');

        // Ducting index
        const ductingEl = document.getElementById('wx-ducting');
        const ductingVal = document.getElementById('wx-ducting-value');
        if (ductingEl && data.ducting && data.ducting.ducting_index != null) {
            const idx = data.ducting.ducting_index;
            const level = data.ducting.level || 'low';
            ductingEl.style.display = 'inline';
            ductingVal.textContent = `${Math.round(idx)}/100 (${level})`;
            // Color code
            const colors = { low: '#484f58', moderate: '#d29922', high: '#f85149', extreme: '#da3633' };
            ductingVal.style.color = colors[level] || '#8b949e';
            ductingEl.title = `Tropospheric Ducting Index: ${Math.round(idx)}/100 — ${level}`;
        } else if (ductingEl) {
            ductingEl.style.display = 'none';
        }

        // Thunderstorm indicator
        if (wx.is_thunderstorm) {
            const iconEl = document.getElementById('wx-icon');
            if (iconEl) iconEl.title = '⚡ Thunderstorm activity detected — lightning possible';
        }

        // Render severe weather alerts
        renderAlerts(data.alerts || [], data.has_lightning);
    }

    function formatWind(wx) {
        if (wx.wind_speed_mph == null) return '--';
        let wind = `${Math.round(wx.wind_speed_mph)} mph`;
        if (wx.wind_direction_label) wind += ` ${wx.wind_direction_label}`;
        if (wx.wind_gusts_mph && wx.wind_gusts_mph > wx.wind_speed_mph + 5) {
            wind += ` (G${Math.round(wx.wind_gusts_mph)})`;
        }
        return wind;
    }

    function renderAlerts(alerts, hasLightning) {
        const container = document.getElementById('wx-alerts-container');
        if (!container) return;

        if (!alerts || alerts.length === 0) {
            container.innerHTML = '';
            lastAlertCount = 0;
            return;
        }

        // Flash effect when new alerts appear
        const isNew = alerts.length > lastAlertCount;
        lastAlertCount = alerts.length;

        container.innerHTML = alerts.map((alert, i) => {
            const isWarning = alert.alert_type === 'warning';
            const cls = isWarning ? 'wx-alert-warning' : 'wx-alert-watch';
            const icon = isWarning ? '🔴' : '🟠';
            const lightningIcon = alert.has_lightning ? ' ⚡' : '';
            const flashCls = isNew && i === 0 ? ' wx-alert-flash' : '';

            return `
                <div class="wx-alert ${cls}${flashCls}" title="${escHtml(alert.headline)}">
                    <span class="wx-alert-icon">${icon}${lightningIcon}</span>
                    <span class="wx-alert-event">${escHtml(alert.event)}</span>
                    <span class="wx-alert-severity">${escHtml(alert.severity)}</span>
                    <button class="wx-alert-expand" onclick="pvWeather.toggleAlertDetail(this)" title="Show details">▼</button>
                    <div class="wx-alert-detail" style="display:none;">
                        <p>${escHtml(alert.headline)}</p>
                        ${alert.description ? `<p class="wx-alert-desc">${escHtml(alert.description)}</p>` : ''}
                        ${alert.instruction ? `<p class="wx-alert-instruction"><b>Action:</b> ${escHtml(alert.instruction)}</p>` : ''}
                        ${alert.expires ? `<p class="wx-alert-expires">Expires: ${formatExpires(alert.expires)}</p>` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }

    function toggleAlertDetail(btn) {
        const detail = btn.parentElement.querySelector('.wx-alert-detail');
        if (!detail) return;
        const showing = detail.style.display !== 'none';
        detail.style.display = showing ? 'none' : 'block';
        btn.textContent = showing ? '▼' : '▲';
    }

    function formatExpires(isoStr) {
        try {
            const d = new Date(isoStr);
            return d.toLocaleString([], {
                month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        } catch { return isoStr; }
    }

    // ── Settings: location lookup ──────────────────────────────

    async function lookupLocation() {
        const input = document.getElementById('cfg-wx-location');
        const resolved = document.getElementById('cfg-wx-resolved');
        const btn = document.getElementById('btn-wx-resolve');
        if (!input) return;

        const code = input.value.trim();
        if (!code) { input.focus(); return; }

        if (btn) btn.disabled = true;
        if (resolved) resolved.textContent = 'Looking up...';

        try {
            const resp = await fetch('/api/weather/resolve-location', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code }),
            });
            const data = await resp.json();

            if (data.success && data.location) {
                const loc = data.location;
                if (resolved) {
                    resolved.textContent = `${loc.name} (${loc.latitude.toFixed(4)}, ${loc.longitude.toFixed(4)})`;
                    resolved.title = `Lat: ${loc.latitude}, Lon: ${loc.longitude}`;
                }
            } else {
                if (resolved) resolved.textContent = data.message || 'Not found';
            }
        } catch (e) {
            console.error('Location lookup failed:', e);
            if (resolved) resolved.textContent = 'Network error';
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    // ── Helpers ────────────────────────────────────────────────

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str || '';
        return div.innerHTML;
    }

    return {
        init,
        fetchWeather,
        toggleAlertDetail,
    };
})();
