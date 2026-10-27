// Run with NODE_PATH pointing at a Playwright installation. No live radio or server needed.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');

(async () => {
    const browser = await chromium.launch({ channel: 'msedge', headless: true });
    try {
        const page = await browser.newPage();
        await page.route('**/*', async route => {
            const url = new URL(route.request().url());
            if (url.pathname.startsWith('/static/')) {
                const file = path.join(root, url.pathname);
                if (fs.existsSync(file)) return route.fulfill({ path: file });
            }
            if (url.pathname === '/mobile') return route.fulfill({ path: path.join(root, 'static/mobile.html'), contentType: 'text/html' });
            if (url.pathname.startsWith('/api/')) return route.fulfill({ json: { web: {}, station: {}, stations: [], packets: [], messages: [], authenticated: false } });
            return route.fulfill({ contentType: 'text/html', body: '<div id="map" style="height:600px;width:800px"></div><div id="list"></div><div id="wx-alerts-container"></div>' });
        });
        await page.goto('http://propview.test/');
        for (const file of ['vendor/leaflet/leaflet.js', 'js/icons.js', 'js/ui-updates.js', 'js/map.js', 'js/stations.js', 'js/weather.js']) {
            await page.addScriptTag({ path: path.join(root, 'static', file) });
        }
        const payload = `N0X" onmouseover="window.__xss=1" data-extra="');window.__xss=2;//<&`;
        await page.evaluate(call => {
            window.__xss = 0;
            window.formatDist = String;
            window.formatBearing = String;
            window.MaidenheadGrid = class {};
            window.pvMessages = { startNewMessage: value => { window.__messageCall = value; } };
            window.auditMap = new PropViewMap();
            for (const name of ['_loadMapTileConfig', '_initPacketAnimationCanvas', '_addLegend', '_bindControls', '_restoreUIState', '_applyVisualizationClasses']) auditMap[name] = () => {};
            auditMap.init(34, -89);
            const station = { callsign: call, source: 'aprs_is', latitude: 34, longitude: -89, last_comment: '<img src=x onerror="window.__xss=3">', last_path: call, last_heard: 1, packet_count: 1 };
            auditMap.addOrUpdateStation(station);
            auditMap.isMarkers[call].openPopup();
            const manager = new StationManager();
            document.getElementById('list').innerHTML = manager._stationItemHTML(station);
        }, payload);
        assert.equal(await page.locator('#list .station-item').getAttribute('data-callsign'), payload);
        assert.equal(await page.locator('#list [onmouseover], #list img, .leaflet-popup [onerror]').count(), 0);
        await page.locator('.leaflet-popup [data-message-call]').evaluate(button => {
            button.innerHTML = '<span>Send Message</span>';
            button.querySelector('span').click();
        });
        assert.equal(await page.evaluate(() => window.__messageCall), payload);
        assert.equal(await page.evaluate(() => window.__xss), 0);
        console.log('PASS desktop station attributes, popup escaping, nested click through Leaflet');

        await page.evaluate(async key => {
            window.fetch = async () => ({ json: async () => ({ enabled: true, configured: true, current: {}, alerts: [{ id: key, event: key, headline: key, severity: 'Severe', alert_type: 'warning' }] }) });
            pvWeather.init();
            await pvWeather.fetchWeather();
        }, payload);
        assert.equal(await page.locator('.wx-alert-dismiss').getAttribute('data-alert-key'), payload);
        assert.equal(await page.locator('.wx-alert [onmouseover], .wx-alert img').count(), 0);
        await page.locator('.wx-alert-dismiss').evaluate(button => {
            button.innerHTML = '<span>Dismiss</span>';
            button.querySelector('span').click();
        });
        assert.equal(await page.locator('.wx-alert').count(), 0);
        await page.evaluate(() => pvWeather.rerender());
        assert.equal(await page.locator('.wx-alert').count(), 0);
        console.log('PASS weather escaping, nested dismiss click, dismissal survives rerender');

        await page.goto('http://propview.test/mobile');
        await page.waitForFunction(() => typeof addMapMarker === 'function');
        await page.evaluate(call => {
            window.__xss = 0;
            startMessageTo = (value, source) => { window.__mobileMessage = [value, source]; };
            if (!S.map) initMap();
            addMapMarker({ callsign: call, source: 'aprs_is', latitude: 34, longitude: -89, last_heard: 1, last_comment: '<img src=x onerror="window.__xss=3">' });
            S.isMarkers[call].openPopup();
        }, payload);
        await page.locator('.leaflet-popup [data-message-call]').evaluate(button => {
            button.innerHTML = '<span>Send Message</span>';
            button.querySelector('span').click();
        });
        assert.deepEqual(await page.evaluate(() => window.__mobileMessage), [payload, 'aprs_is']);
        assert.equal(await page.locator('.leaflet-popup [onmouseover], .leaflet-popup img').count(), 0);
        assert.equal(await page.evaluate(() => window.__xss), 0);
        console.log('PASS mobile popup escaping and nested message click through Leaflet');
        await page.route('**/api/heard-me', route => route.fulfill({ json: { aprs_is_connected: true, observations: [{
            source_call: 'K5ABC-1', receiver: 'W1GATE', route_calls: ['W1GATE'], direct: true, path_known: true,
            latitude: 34, longitude: -89, last_heard: Date.now()/1000, packet_count: 1, transport: 'aprs_is',
            hops: [{ callsign: 'W1GATE', latitude: 35, longitude: -88 }]
        }] } }));
        await page.evaluate(() => { activateTab('mtab-map'); document.getElementById('m-heard-me').click(); });
        await page.waitForFunction(() => document.querySelectorAll('.heard-me-path').length === 1);
        await page.evaluate(() => setLinesVisible(false));
        assert.equal(await page.locator('.heard-me-path').count(), 1);
        await page.locator('#m-heard-me').evaluate(button => button.click());
        assert.equal(await page.locator('.heard-me-path').count(), 0);
        console.log('PASS mobile Heard me overlay toggles independently of received lines');

    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
