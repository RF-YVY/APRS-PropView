/** NOAA SWPC context card for the Propagation tab. */
(() => {
    function set(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    }

    function render(data) {
        const card = document.getElementById('space-weather-card');
        if (!card) return;
        card.hidden = data.enabled === false;
        if (card.hidden) return;
        card.className = `space-weather-card ${data.context?.level || 'quiet'}${data.stale ? ' stale' : ''}`;
        set('space-weather-kp', data.kp == null ? '--' : Number(data.kp).toFixed(1));
        set('space-weather-g', `G${data.g_scale ?? '--'}`);
        set('space-weather-r', `R${data.r_scale ?? '--'}`);
        set('space-weather-s', `S${data.s_scale ?? '--'}`);
        set('space-weather-context', data.context?.text || data.last_error || 'Waiting for NOAA SWPC data.');
        const age = data.age_seconds == null ? 'Waiting for data…'
            : data.age_seconds < 60 ? `Updated ${data.age_seconds}s ago`
            : `Updated ${Math.round(data.age_seconds / 60)}m ago`;
        set('space-weather-age', age);
    }

    async function refresh() {
        try {
            const response = await fetch('/api/space-weather', {cache: 'no-store'});
            if (response.ok) render(await response.json());
        } catch (_) {}
    }

    document.addEventListener('DOMContentLoaded', () => {
        refresh();
        window.setInterval(refresh, 300000);
        window.pvWebSocket?.on('space_weather', message => render(message.data || {}));
    });
})();
