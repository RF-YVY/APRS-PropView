/**
 * Weather module — fetches and displays current weather + NWS severe alerts.
 */

window.pvWeather = (function () {
    'use strict';

    let refreshTimer = null;
    let lastAlertCount = 0;
    let hasRenderedAlerts = false;
    let lastWeatherData = null;
    let alertPulseAcknowledged = false;
    let lastAlertSignature = '';
    const dismissedAlertKeys = new Set();

    function init() {
        updateMapSearchOffset();
        window.addEventListener('resize', updateMapSearchOffset);
        // Refresh button
        document.getElementById('wx-refresh-btn')?.addEventListener('click', () => {
            fetchWeather(true);
        });
        document.getElementById('wx-ducting')?.addEventListener('click', showDuctingDetails);
        document.getElementById('ducting-modal-close')?.addEventListener('click', closeDuctingDetails);
        document.getElementById('ducting-modal')?.addEventListener('click', (e) => {
            if (e.target?.id === 'ducting-modal') closeDuctingDetails();
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
            lastWeatherData = data;
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
            updateMapSearchOffset();
            return;
        }

        const wx = data.current;

        // Show current weather banner
        if (banner) banner.style.display = 'flex';

        setText('wx-icon', wx.icon || '❓');
        setText('wx-temp', window.formatTempF ? window.formatTempF(wx.temperature_f) : (wx.temperature_f != null ? Math.round(wx.temperature_f) + '°F' : '--°F'));
        setText('wx-desc', wx.description || '--');
        setText('wx-feels', window.formatTempF ? window.formatTempF(wx.feels_like_f) : (wx.feels_like_f != null ? Math.round(wx.feels_like_f) + '°F' : '--'));
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
            ductingEl.style.display = 'inline-flex';
            ductingVal.textContent = `${Math.round(idx)}/100 (${level})`;
            // Color code
            const colors = { low: '#4d5b6b', moderate: '#9a6700', high: '#cf222e', extreme: '#a40e26' };
            ductingVal.style.color = colors[level] || '#8b949e';
            ductingEl.title = `Tropospheric Ducting Index: ${Math.round(idx)}/100 - ${level}. Click for details.`;
        } else if (ductingEl) {
            ductingEl.style.display = 'none';
        }

        // Render severe weather alerts
        renderAlerts(data.alerts || []);
        updateMapSearchOffset();
    }

    function updateMapSearchOffset() {
        requestAnimationFrame(() => {
            const panel = document.getElementById('map-panel');
            const map = document.getElementById('map');
            if (!panel || !map) return;
            panel.style.setProperty('--map-overlay-top', `${map.offsetTop + 12}px`);
        });
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
        map.updateWeatherAlerts(data?.overlay_alerts || data?.alerts || []);
    }

    function formatWind(wx) {
        if (wx.wind_speed_mph == null) return '--';
        let wind = window.formatWindMph ? window.formatWindMph(wx.wind_speed_mph) : `${Math.round(wx.wind_speed_mph)} mph`;
        if (wx.wind_direction_label) wind += ` ${wx.wind_direction_label}`;
        if (wx.wind_gusts_mph && wx.wind_gusts_mph > wx.wind_speed_mph + 5) {
            const gust = window.formatWindMph ? window.formatWindMph(wx.wind_gusts_mph) : `${Math.round(wx.wind_gusts_mph)} mph`;
            wind += ` (G ${gust})`;
        }
        return wind;
    }

    function rerender() {
        if (lastWeatherData) renderWeather(lastWeatherData);
    }

    function showDuctingDetails() {
        const modal = document.getElementById('ducting-modal');
        const body = document.getElementById('ducting-modal-body');
        if (!modal || !body) return;
        body.innerHTML = renderDuctingDetails(lastWeatherData?.ducting);
        modal.style.display = 'flex';
    }

    function closeDuctingDetails() {
        const modal = document.getElementById('ducting-modal');
        if (modal) modal.style.display = 'none';
    }

    function renderDuctingDetails(ducting) {
        if (!ducting || ducting.ducting_index == null) {
            return '<p>Ducting data is not available. Enable weather and refresh current conditions.</p>';
        }

        const level = ducting.level || 'unknown';
        const score = Number(ducting.ducting_index || 0);
        const scoring = Array.isArray(ducting.scoring) ? ducting.scoring : [];
        const factors = ducting.factors || {};
        const rows = scoring.length
            ? scoring.map((item) => renderDuctingScoreRow(item)).join('')
            : Object.entries(factors).map(([key, detail]) => `
                <div class="ducting-factor-row">
                    <div>
                        <div class="ducting-factor-name">${escHtml(labelize(key))}</div>
                        <div class="ducting-factor-detail">${escHtml(detail)}</div>
                    </div>
                </div>
            `).join('');

        return `
            <div class="ducting-summary">
                <div>
                    <div class="ducting-score">${Math.round(score)}/100</div>
                    <div class="ducting-level ducting-level-${escHtml(level)}">${escHtml(level.toUpperCase())}</div>
                </div>
                <div class="ducting-summary-text">
                    APRS PropView estimates VHF tropo ducting from temperature inversion or reduced lapse rate,
                    surface pressure, pressure trend, humidity, and wind speed.
                </div>
            </div>
            <div class="ducting-measurements">
                ${renderDuctingMetric('Surface temp', formatNullable(ducting.surface_temp_f, 'F', 1))}
                ${renderDuctingMetric('850 hPa temp', formatNullable(ducting.temp_850hPa_f, 'F', 1))}
                ${renderDuctingMetric('Pressure', formatNullable(ducting.pressure_mb, 'mb', 0))}
                ${renderDuctingMetric('6h trend', formatSignedNullable(ducting.pressure_trend, 'mb', 1))}
                ${renderDuctingMetric('Humidity', formatNullable(ducting.humidity, '%', 0))}
                ${renderDuctingMetric('Wind', formatNullable(ducting.wind_speed_mph, 'mph', 0))}
            </div>
            <div class="ducting-factor-list">
                ${rows || '<p>No scoring factors were returned for this sample.</p>'}
            </div>
            <p class="ducting-note">Last updated ${escHtml(formatDuctingTime(ducting.timestamp))}. This index is a local weather-based estimate, not a guarantee of RF propagation.</p>
        `;
    }

    function renderDuctingScoreRow(item) {
        const points = Number(item.points || 0);
        const max = Number(item.max_points || 0);
        const pct = max > 0 ? Math.max(0, Math.min(100, (points / max) * 100)) : 0;
        return `
            <div class="ducting-factor-row">
                <div>
                    <div class="ducting-factor-name">${escHtml(item.label || labelize(item.key))}</div>
                    <div class="ducting-factor-detail">${escHtml(item.detail || '')}</div>
                </div>
                <div class="ducting-factor-points">${points.toFixed(points % 1 ? 1 : 0)} / ${max.toFixed(max % 1 ? 1 : 0)}</div>
                <div class="ducting-factor-bar" aria-hidden="true"><span style="width:${pct.toFixed(0)}%"></span></div>
            </div>
        `;
    }

    function renderDuctingMetric(label, value) {
        return `
            <div class="ducting-metric">
                <span>${escHtml(label)}</span>
                <b>${escHtml(value)}</b>
            </div>
        `;
    }

    function formatNullable(value, unit, decimals) {
        if (value == null || Number.isNaN(Number(value))) return '--';
        return `${Number(value).toFixed(decimals)} ${unit}`;
    }

    function formatSignedNullable(value, unit, decimals) {
        if (value == null || Number.isNaN(Number(value))) return '--';
        const numeric = Number(value);
        return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(decimals)} ${unit}`;
    }

    function formatDuctingTime(timestamp) {
        if (!timestamp) return 'unknown';
        try {
            return new Date(Number(timestamp) * 1000).toLocaleString();
        } catch {
            return 'unknown';
        }
    }

    function labelize(value) {
        return String(value || '')
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (ch) => ch.toUpperCase());
    }

    function renderAlerts(alerts) {
        const container = document.getElementById('wx-alerts-container');
        if (!container) return;

        const visibleAlerts = (alerts || []).filter((alert) => !dismissedAlertKeys.has(alertKey(alert)));

        if (!alerts || alerts.length === 0) {
            container.innerHTML = '';
            updateAlertStackState();
            lastAlertCount = 0;
            lastAlertSignature = '';
            alertPulseAcknowledged = false;
            hasRenderedAlerts = true;
            return;
        }

        if (visibleAlerts.length === 0) {
            container.innerHTML = '';
            updateAlertStackState();
            lastAlertCount = alerts.length;
            lastAlertSignature = alerts.map(alertKey).join('||');
            alertPulseAcknowledged = true;
            hasRenderedAlerts = true;
            return;
        }

        // Flash effect when new alerts appear
        const isNew = alerts.length > lastAlertCount;
        const alertSignature = visibleAlerts
            .map(alertKey)
            .join('||');
        if (alertSignature !== lastAlertSignature) {
            alertPulseAcknowledged = false;
            lastAlertSignature = alertSignature;
        }
        lastAlertCount = alerts.length;
        if (hasRenderedAlerts && isNew) {
            const firstAlertType = alerts[0]?.alert_type === 'warning' ? 'weather_warning' : 'weather_watch';
            window.pvAlertAudio?.play(firstAlertType);
        }
        hasRenderedAlerts = true;

        container.innerHTML = visibleAlerts.map((alert, i) => {
            const isWarning = alert.alert_type === 'warning';
            const cls = isWarning ? 'wx-alert-warning' : 'wx-alert-watch';
            const icon = isWarning ? '&#128308;' : '&#128992;';
            const alertId = `wx-alert-${i}`;
            const detailId = `${alertId}-detail`;
            const key = alertKey(alert);

            return `
                <div class="wx-alert ${cls}" title="${escHtml(alert.headline || alert.event)}" id="${alertId}" data-alert-key="${escHtml(key)}">
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
                    <button
                        type="button"
                        class="wx-alert-dismiss"
                        onclick="pvWeather.dismissAlert('${escapeJsString(key)}')"
                        aria-label="Clear ${escHtml(alert.event || 'weather alert')} from view"
                        title="Clear this alert from view"
                    >X</button>
                    <div class="wx-alert-detail" id="${detailId}" hidden>
                        ${renderAlertMeta(alert)}
                        ${renderAlertDetail(alert)}
                    </div>
                </div>
            `;
        }).join('');
        const hasWarning = visibleAlerts.some((alert) => alert.alert_type === 'warning');
        container.classList.toggle('has-unacknowledged-alerts', hasWarning && !alertPulseAcknowledged);
        updateAlertStackState();
    }

    function alertKey(alert) {
        return String(alert?.id || `${alert?.event || ''}|${alert?.headline || ''}|${alert?.expires || ''}|${alert?.area_desc || ''}`);
    }

    function escapeJsString(value) {
        return String(value || '')
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'")
            .replace(/\r/g, '\\r')
            .replace(/\n/g, '\\n')
            .replace(/\u2028/g, '\\u2028')
            .replace(/\u2029/g, '\\u2029');
    }

    function dismissAlert(key) {
        if (!key) return;
        dismissedAlertKeys.add(String(key));
        acknowledgeAlertPulse();

        const container = document.getElementById('wx-alerts-container');
        const card = container?.querySelector(`.wx-alert[data-alert-key="${cssEscape(String(key))}"]`);
        if (card) card.remove();
        if (container && !container.querySelector('.wx-alert')) {
            container.innerHTML = '';
        }
        updateAlertStackState();
        updateMapSearchOffset();
    }

    function cssEscape(value) {
        if (window.CSS?.escape) return window.CSS.escape(value);
        return String(value || '').replace(/["\\]/g, '\\$&');
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
        acknowledgeAlertPulse();
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
        updateAlertStackState();
    }

    function acknowledgeAlertPulse() {
        alertPulseAcknowledged = true;
        document
            .getElementById('wx-alerts-container')
            ?.classList.remove('has-unacknowledged-alerts');
    }

    function updateAlertStackState() {
        const container = document.getElementById('wx-alerts-container');
        if (!container) return;
        const hasExpanded = !!container.querySelector('.wx-alert.is-expanded');
        container.classList.toggle('has-expanded-alert', hasExpanded);
        document.getElementById('map-panel')?.classList.toggle('has-expanded-weather-alert', hasExpanded);
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
        rerender,
        toggleAlertDetail,
        dismissAlert,
        showDuctingDetails,
    };
})();
