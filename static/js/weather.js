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
        const interval = (data?.refresh_minutes || 15) * 60 * 1000;
        const alertInterval = Math.max(30, data?.alert_polling?.current_interval_seconds || 300) * 1000;
        const nextRefresh = Math.min(interval, alertInterval);
        refreshTimer = setTimeout(() => fetchWeather(), nextRefresh);
    }

    function renderWeather(data) {
        const banner = document.getElementById('wx-banner');
        const alertsContainer = document.getElementById('wx-alerts-container');
        syncMapOverlays(data);

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

        // Render severe weather alerts
        renderAlerts(data.alerts || []);
    }

    function syncMapOverlays(data) {
        const map = window.pvMap;
        if (!map) return;
        const overlayConfig = {
            ...(data?.map_overlays || {}),
        };
        if (!data?.enabled || !data?.configured) {
            overlayConfig.radar_enabled = false;
            overlayConfig.alert_overlay_enabled = false;
        }
        map.setWeatherOverlayConfig(overlayConfig);
        map.updateWeatherAlerts(data?.alerts || []);
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

    function renderAlerts(alerts) {
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
            const icon = isWarning ? '&#128308;' : '&#128992;';
            const flashCls = isNew && i === 0 ? ' wx-alert-flash' : '';
            const alertId = `wx-alert-${i}`;
            const detailId = `${alertId}-detail`;

            return `
                <div class="wx-alert ${cls}${flashCls}" title="${escHtml(alert.headline || alert.event)}" id="${alertId}">
                    <button
                        type="button"
                        class="wx-alert-summary"
                        onclick="pvWeather.toggleAlertDetail(${i})"
                        aria-expanded="false"
                        aria-controls="${detailId}"
                        title="Show alert details"
                    >
                        <span class="wx-alert-icon">${icon}</span>
                        <span class="wx-alert-event">${escHtml(alert.event)}</span>
                        <span class="wx-alert-severity">${escHtml(alert.severity)}</span>
                        <span class="wx-alert-expand">Show details</span>
                    </button>
                    <div class="wx-alert-detail" id="${detailId}" hidden>
                        ${renderAlertMeta(alert)}
                        ${renderAlertDetail(alert)}
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderAlertMeta(alert) {
        const items = [];
        if (alert.headline) items.push(`<span class="wx-alert-meta-pill">${escHtml(alert.headline)}</span>`);
        if (alert.area_desc) items.push(`<span class="wx-alert-meta-pill">${escHtml(alert.area_desc)}</span>`);
        if (alert.expires) items.push(`<span class="wx-alert-meta-pill">Expires ${escHtml(formatExpires(alert.expires))}</span>`);
        if (alert.sender) items.push(`<span class="wx-alert-meta-pill">${escHtml(alert.sender)}</span>`);
        if (alert.certainty && alert.certainty !== 'Unknown') items.push(`<span class="wx-alert-meta-pill">Certainty ${escHtml(alert.certainty)}</span>`);
        if (alert.urgency && alert.urgency !== 'Unknown') items.push(`<span class="wx-alert-meta-pill">Urgency ${escHtml(alert.urgency)}</span>`);
        return items.length ? `<div class="wx-alert-meta">${items.join('')}</div>` : '';
    }

    function renderAlertDetail(alert) {
        const sections = [];
        if (alert.description) {
            sections.push(renderAlertSection('Summary', alert.description, 'wx-alert-desc'));
        }
        if (alert.instruction) {
            sections.push(renderAlertSection('Recommended Action', alert.instruction, 'wx-alert-instruction'));
        }
        if (!sections.length && alert.headline) {
            sections.push(renderAlertSection('Alert', alert.headline, 'wx-alert-desc'));
        }
        return sections.join('');
    }

    function renderAlertSection(label, text, bodyClass) {
        return `
            <section class="wx-alert-section">
                <div class="wx-alert-section-label">${escHtml(label)}</div>
                <div class="${bodyClass}">${formatAlertText(text)}</div>
            </section>
        `;
    }

    function formatAlertText(text) {
        const normalized = String(text || '')
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n')
            .trim();
        if (!normalized) return '';

        return normalized
            .split(/\n{2,}/)
            .map((block) => {
                const lines = block.split('\n').map((line) => line.trim()).filter(Boolean);
                if (!lines.length) return '';
                if (lines.length > 1 && lines.every((line) => /^[-*]/.test(line))) {
                    return `<ul class="wx-alert-list">${lines.map((line) => `<li>${escHtml(line.replace(/^[-*]\s*/, ''))}</li>`).join('')}</ul>`;
                }
                return `<p>${lines.map((line) => escHtml(line)).join('<br>')}</p>`;
            })
            .filter(Boolean)
            .join('');
    }

    function toggleAlertDetail(index) {
        const card = document.getElementById(`wx-alert-${index}`);
        if (!card) return;
        const detail = card.querySelector('.wx-alert-detail');
        const summary = card.querySelector('.wx-alert-summary');
        const expand = card.querySelector('.wx-alert-expand');
        if (!detail || !summary || !expand) return;

        const showing = !detail.hasAttribute('hidden');
        if (showing) {
            detail.setAttribute('hidden', '');
            summary.setAttribute('aria-expanded', 'false');
            card.classList.remove('is-expanded');
            expand.textContent = 'Show details';
        } else {
            detail.removeAttribute('hidden');
            summary.setAttribute('aria-expanded', 'true');
            card.classList.add('is-expanded');
            expand.textContent = 'Hide details';
        }
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
