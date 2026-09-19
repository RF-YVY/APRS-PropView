/** Unified data-source freshness panel. */
(() => {
    const STATE_LABELS = {
        live: 'LIVE', delayed: 'DELAYED', stale: 'STALE', offline: 'OFFLINE',
        waiting: 'WAITING', configured: 'CONFIGURED', disabled: 'OFF'
    };

    function escapeHTML(value) {
        return String(value ?? '').replace(/[&<>'"]/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        })[char]);
    }

    function ageLabel(seconds) {
        if (seconds == null) return 'No sample yet';
        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
        return `${Math.round(seconds / 3600)}h ago`;
    }

    function positionPanel() {
        const button = document.getElementById('btn-source-health');
        const panel = document.getElementById('source-health-panel');
        if (!button || !panel || panel.hidden) return;
        const rect = button.getBoundingClientRect();
        panel.style.top = `${Math.min(window.innerHeight - panel.offsetHeight - 12, rect.bottom + 8)}px`;
        panel.style.left = `${Math.max(12, Math.min(window.innerWidth - panel.offsetWidth - 12, rect.right - panel.offsetWidth))}px`;
    }

    function render(payload) {
        const button = document.getElementById('btn-source-health');
        const list = document.getElementById('source-health-list');
        const count = document.getElementById('source-health-count');
        const updated = document.getElementById('source-health-updated');
        if (!button || !list) return;

        const websocket = {
            id: 'websocket', label: 'Browser live link',
            state: window.pvWebSocket?.isConnected ? 'live' : 'offline',
            enabled: true, age_seconds: null,
            detail: window.pvWebSocket?.isConnected ? 'Receiving live dashboard updates' : 'Reconnecting to PropView', error: ''
        };
        const sources = [websocket, ...(payload.sources || [])];
        const attention = sources.filter(item => item.enabled && ['offline', 'stale'].includes(item.state)).length;
        const delayed = sources.some(item => item.enabled && ['delayed', 'waiting'].includes(item.state));
        button.dataset.state = attention ? 'attention' : delayed ? 'delayed' : 'healthy';
        count.hidden = attention === 0;
        count.textContent = attention;
        updated.textContent = `Updated ${new Date((payload.timestamp || Date.now() / 1000) * 1000).toLocaleTimeString()}`;
        list.innerHTML = sources.map(item => `
            <div class="source-health-item ${escapeHTML(item.state)}">
                <span class="source-health-state-dot"></span>
                <div class="source-health-copy">
                    <div><strong>${escapeHTML(item.label)}</strong><span>${escapeHTML(STATE_LABELS[item.state] || item.state)}</span></div>
                    <small>${escapeHTML(item.detail || '')}${item.age_seconds == null ? '' : ` · ${escapeHTML(ageLabel(item.age_seconds))}`}</small>
                    ${item.error ? `<em title="${escapeHTML(item.error)}">${escapeHTML(item.error)}</em>` : ''}
                </div>
            </div>`).join('');
        positionPanel();
    }

    async function refresh() {
        try {
            const response = await fetch('/api/source-health', { cache: 'no-store' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            render(await response.json());
        } catch (error) {
            const button = document.getElementById('btn-source-health');
            const list = document.getElementById('source-health-list');
            if (button) button.dataset.state = 'attention';
            if (list) list.innerHTML = `<div class="source-health-empty">Source health unavailable: ${escapeHTML(error.message)}</div>`;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const control = document.getElementById('source-health-control');
        const button = document.getElementById('btn-source-health');
        const panel = document.getElementById('source-health-panel');
        if (!control || !button || !panel) return;

        // Keep the open card outside header/theme stacking contexts so the map,
        // sidebar, and their overlays can never paint over it.
        document.body.appendChild(panel);

        button.addEventListener('click', () => {
            panel.hidden = !panel.hidden;
            button.setAttribute('aria-expanded', String(!panel.hidden));
            if (!panel.hidden) { refresh(); requestAnimationFrame(positionPanel); }
        });
        document.addEventListener('click', event => {
            if (!control.contains(event.target) && !panel.contains(event.target)) {
                panel.hidden = true;
                button.setAttribute('aria-expanded', 'false');
            }
        });
        window.addEventListener('resize', positionPanel);
        refresh();
        window.setInterval(refresh, 30000);
    });
})();
