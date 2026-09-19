/** Optional PSK Reporter VHF/UHF corroboration card. */
(() => {
    function set(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    }

    function render(data) {
        const card = document.getElementById('external-propagation-card');
        const heading = document.getElementById('external-propagation-heading');
        if (!card || !heading) return;
        const visible = data.enabled === true;
        card.hidden = !visible;
        heading.hidden = !visible;
        if (!visible) return;
        card.classList.toggle('stale', Boolean(data.stale));
        set('external-propagation-count', data.report_count ?? 0);
        set('external-propagation-peers', data.unique_peers ?? 0);
        const distance = Number(data.max_distance_km);
        set('external-propagation-distance', Number.isFinite(distance)
            ? `${Math.round(window.distToDisplay ? window.distToDisplay(distance) : distance)} ${window.distLabel ? window.distLabel() : 'km'}`
            : '--');
        set('external-propagation-bands', Object.keys(data.bands || {}).join(', ') || '--');
        set('external-propagation-note', data.last_error || data.note || 'Independent digital-mode reports; supporting context only.');
        const age = data.age_seconds == null ? 'Waiting for data…'
            : data.age_seconds < 60 ? `Updated ${data.age_seconds}s ago`
            : `Updated ${Math.round(data.age_seconds / 60)}m ago`;
        set('external-propagation-age', age);
    }

    async function refresh() {
        try {
            const response = await fetch('/api/external-propagation', {cache: 'no-store'});
            if (response.ok) render(await response.json());
        } catch (_) {}
    }

    document.addEventListener('DOMContentLoaded', () => {
        refresh();
        window.setInterval(refresh, 300000);
        window.pvWebSocket?.on('external_propagation', message => render(message.data || {}));
    });
})();
