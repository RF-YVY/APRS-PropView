/** Rotating, read-only club display built from the live desktop views. */
(() => {
    'use strict';

    const isKiosk = window.location.pathname.replace(/\/+$/, '') === '/kiosk';
    if (!isKiosk) return;

    const DEFINITIONS = {
        map: {label: 'Live RF Map', detail: 'Full map view', tab: 'tab-rf'},
        propagation: {
            label: 'Propagation Conditions',
            detail: 'Auto-scrolling live dashboard',
            tab: 'tab-prop',
            scrollTarget: '#tab-prop .prop-detail',
        },
        weather: {
            label: 'Weather & APRS Mesh',
            detail: 'Auto-scrolling weather dashboard',
            tab: 'tab-analytics',
            analytics: 'sec-weather',
            scrollTarget: '#tab-analytics .analytics-panel',
        },
        activity: {
            label: 'Recent RF Activity',
            detail: 'Auto-scrolling station table',
            tab: 'tab-rf',
            scrollTarget: '#rf-station-list',
            kind: 'stations',
        },
        'aprs-is': {label: 'APRS-IS Activity', detail: 'Auto-scrolling station table', tab: 'tab-is', scrollTarget: '#is-station-list', kind: 'stations'},
        packets: {label: 'Live Packet Feed', detail: 'Auto-scrolling packet table', tab: 'tab-packets', scrollTarget: '#packet-list', kind: 'packets'},
        'longest-paths': {label: 'Longest Paths', detail: 'Propagation leaderboard', tab: 'tab-analytics', analytics: 'sec-leaderboard', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        heatmap: {label: 'Propagation Heatmap', detail: 'Activity by hour and distance', tab: 'tab-analytics', analytics: 'sec-heatmap', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        reliability: {label: 'Station Reliability', detail: 'Auto-scrolling station table', tab: 'tab-analytics', analytics: 'sec-reliability', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        'best-times': {label: 'Best Propagation Times', detail: 'Hourly and day-of-week trends', tab: 'tab-analytics', analytics: 'sec-besttime', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        alerts: {label: 'Band Opening Alerts', detail: 'Alert status and recent history', tab: 'tab-analytics', analytics: 'sec-alerts', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        anomaly: {label: 'Propagation Anomaly', detail: 'Current conditions vs baseline', tab: 'tab-analytics', analytics: 'sec-anomaly', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        bearing: {label: 'Bearing Sectors', detail: 'Directional RF activity', tab: 'tab-analytics', analytics: 'sec-bearing', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        history: {label: 'Historical Comparison', detail: 'Today and baseline trends', tab: 'tab-analytics', analytics: 'sec-historical', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        'sporadic-e': {label: 'Sporadic-E Monitor', detail: 'Possible opening candidates', tab: 'tab-analytics', analytics: 'sec-sporadic-e', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
        'first-heard': {label: 'First Heard Stations', detail: 'Auto-scrolling new-station table', tab: 'tab-analytics', analytics: 'sec-first-heard', scrollTarget: '#tab-analytics .analytics-panel', kind: 'analytics'},
    };
    let scenes = ['map', 'propagation', 'weather', 'activity'];
    let intervalSeconds = 20;
    let currentIndex = 0;
    let timer = null;
    let paused = false;
    let scrollTimer = null;
    let scrollStartTimer = null;
    let activeScrollTarget = null;

    function toolbar() {
        const element = document.createElement('aside');
        element.id = 'kiosk-toolbar';
        element.setAttribute('aria-label', 'Club display controls');
        element.innerHTML = `
            <div class="kiosk-scene-copy">
                <span>CLUB DISPLAY</span>
                <strong id="kiosk-scene-title">Starting…</strong>
                <small><span id="kiosk-scene-position"></span><span id="kiosk-scene-detail"></span></small>
            </div>
            <div class="kiosk-actions">
                <button type="button" id="kiosk-prev" title="Previous layout" aria-label="Previous layout">◀</button>
                <button type="button" id="kiosk-pause" title="Pause rotation" aria-label="Pause rotation">Ⅱ</button>
                <button type="button" id="kiosk-next" title="Next layout" aria-label="Next layout">▶</button>
                <button type="button" id="kiosk-fullscreen" title="Toggle fullscreen" aria-label="Toggle fullscreen">⛶</button>
                <a href="/" title="Exit club display" aria-label="Exit club display">×</a>
            </div>
            <div id="kiosk-progress" class="kiosk-progress"></div>
        `;
        document.body.appendChild(element);
        element.querySelector('#kiosk-prev')?.addEventListener('click', () => move(-1));
        element.querySelector('#kiosk-next')?.addEventListener('click', () => move(1));
        element.querySelector('#kiosk-pause')?.addEventListener('click', togglePause);
        element.querySelector('#kiosk-fullscreen')?.addEventListener('click', toggleFullscreen);
    }

    function restartProgress() {
        const progress = document.getElementById('kiosk-progress');
        if (!progress) return;
        progress.style.animation = 'none';
        void progress.offsetWidth;
        if (!paused && scenes.length > 1) {
            progress.style.animation = `kioskProgress ${intervalSeconds}s linear forwards`;
        }
    }

    function schedule() {
        window.clearTimeout(timer);
        timer = null;
        restartProgress();
        if (!paused && scenes.length > 1 && !document.hidden) {
            timer = window.setTimeout(() => move(1), intervalSeconds * 1000);
        }
    }

    function stopAutoScroll() {
        window.clearInterval(scrollTimer);
        window.clearTimeout(scrollStartTimer);
        scrollTimer = null;
        scrollStartTimer = null;
        activeScrollTarget = null;
    }

    function beginAutoScroll(definition) {
        stopAutoScroll();
        if (!definition.scrollTarget) return;
        activeScrollTarget = document.querySelector(definition.scrollTarget);
        if (!activeScrollTarget) return;
        activeScrollTarget.scrollTop = 0;
        scrollStartTimer = window.setTimeout(() => {
            const target = activeScrollTarget;
            if (!target) return;
            const maximum = Math.max(0, target.scrollHeight - target.clientHeight);
            if (maximum < 8) return;
            const travelSeconds = Math.max(5, intervalSeconds - 4);
            const pixelsPerTick = Math.max(1, maximum / (travelSeconds * 25));
            scrollTimer = window.setInterval(() => {
                if (paused || document.hidden || target !== activeScrollTarget) return;
                target.scrollTop = Math.min(maximum, target.scrollTop + pixelsPerTick);
            }, 40);
        }, 1400);
    }

    function showScene(index) {
        if (!scenes.length) scenes = ['map'];
        currentIndex = (index + scenes.length) % scenes.length;
        const scene = scenes[currentIndex];
        const definition = DEFINITIONS[scene] || DEFINITIONS.map;
        document.body.dataset.kioskScene = scene;
        document.body.dataset.kioskKind = definition.kind || scene;
        window.pvActivateTab?.(definition.tab, false);
        if (definition.analytics) window.pvAnalytics?.showSection?.(definition.analytics, false);
        const title = document.getElementById('kiosk-scene-title');
        const position = document.getElementById('kiosk-scene-position');
        const detail = document.getElementById('kiosk-scene-detail');
        if (title) title.textContent = definition.label;
        if (position) position.textContent = `${currentIndex + 1} / ${scenes.length} · ${intervalSeconds}s rotation`;
        if (detail) detail.textContent = definition.detail ? ` · ${definition.detail}` : '';
        window.setTimeout(() => window.pvMap?.map?.invalidateSize(), 320);
        beginAutoScroll(definition);
        schedule();
    }

    function move(delta) {
        showScene(currentIndex + delta);
    }

    function togglePause() {
        paused = !paused;
        const button = document.getElementById('kiosk-pause');
        if (button) {
            button.textContent = paused ? '▶' : 'Ⅱ';
            button.title = paused ? 'Resume rotation' : 'Pause rotation';
            button.setAttribute('aria-label', button.title);
        }
        document.body.classList.toggle('kiosk-paused', paused);
        if (!paused && activeScrollTarget) {
            const definition = DEFINITIONS[scenes[currentIndex]] || DEFINITIONS.map;
            beginAutoScroll(definition);
        }
        schedule();
    }

    async function toggleFullscreen() {
        try {
            if (document.fullscreenElement) await document.exitFullscreen();
            else await document.documentElement.requestFullscreen();
        } catch (_) {}
    }

    async function init() {
        document.body.classList.add('kiosk-mode');
        toolbar();
        try {
            const response = await fetch('/api/config', {cache: 'no-store'});
            if (response.ok) {
                const config = await response.json();
                intervalSeconds = Math.max(10, Math.min(300, Number(config.web?.club_display_rotation_seconds) || 20));
                const configured = Array.isArray(config.web?.club_display_scenes) ? config.web.club_display_scenes : [];
                scenes = configured.filter((scene) => Object.prototype.hasOwnProperty.call(DEFINITIONS, scene));
                if (!scenes.length) scenes = ['map'];
            }
        } catch (_) {}
        showScene(0);
    }

    document.addEventListener('visibilitychange', schedule);
    window.addEventListener('beforeunload', stopAutoScroll);
    document.addEventListener('keydown', (event) => {
        if (event.key === ' ' && !/INPUT|TEXTAREA|SELECT/.test(event.target?.tagName || '')) {
            event.preventDefault();
            togglePause();
        } else if (event.key === 'ArrowLeft') move(-1);
        else if (event.key === 'ArrowRight') move(1);
    });
    document.addEventListener('DOMContentLoaded', init);
})();
