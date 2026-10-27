const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const now = Date.now() / 1000;
const observation = (receiver, direct, hops) => ({ source_call: 'K5ABC-1', receiver, direct,
    latitude: 34, longitude: -89, last_heard: now, packet_count: 2,
    route_calls: hops.map(hop => hop.callsign), path_known: true, transport: 'aprs_is', hops });
const reports = { aprs_is_connected: true, observations: [
    observation('GATE1', true, [{ callsign: 'GATE1', latitude: 35, longitude: -88 }]),
    observation('GATE2', false, [{ callsign: 'DIGI1', latitude: 34.5, longitude: -88.5 }, { callsign: 'GATE2', latitude: 36, longitude: -87 }]),
    observation('UNKNOWN', false, [{ callsign: 'UNKNOWN', latitude: null, longitude: null }])
] };

(async () => {
    const browser = await chromium.launch({ channel: 'msedge', headless: true });
    const context = await browser.newContext();
    await context.route('**/*', route => route.fulfill(route.request().url().endsWith('/api/heard-me')
        ? { json: reports } : { contentType: 'text/html', body: '<button data-heard-me-toggle>Heard me</button><small id="heard-me-status"></small><div id="map" style="width:800px;height:600px"></div>' }));
    async function prepare(page) {
        await page.goto('http://heard-me.test/');
        for (const name of ['vendor/leaflet/leaflet.js', 'js/ui-updates.js', 'js/map.js'])
            await page.addScriptTag({ path: path.join(root, 'static', name) });
        await page.evaluate(() => {
            window.MaidenheadGrid = class {};
            window.pvMap = new PropViewMap();
            for (const name of ['_loadMapTileConfig', '_initPacketAnimationCanvas', '_addLegend', '_bindControls', '_restoreUIState', '_applyVisualizationClasses']) pvMap[name] = () => {};
            pvMap.init(34, -89);
            L.polyline([[33, -90], [34, -89]], { className: 'incoming-path' }).addTo(pvMap.lineLayer);
        });
        await page.addScriptTag({ path: path.join(root, 'static/js/heard-me.js') });
        await page.evaluate(() => document.dispatchEvent(new Event('DOMContentLoaded')));
    }
    try {
        const page = await context.newPage();
        await prepare(page);
        assert.equal(await page.locator('.heard-me-path').count(), 0);
        await page.locator('[data-heard-me-toggle]').click();
        await page.waitForFunction(() => document.querySelectorAll('.heard-me-path').length === 2);
        assert.equal(await page.locator('.incoming-path').count(), 1);
        assert.equal(await page.locator('.heard-me-arrow').count(), 3);
        assert.match(await page.locator('#heard-me-status').textContent(), /1 awaiting path positions/);
        assert.equal(await page.locator('.heard-me-path[stroke-dasharray]').count(), 1);
        await page.locator('[data-heard-me-toggle]').click();
        assert.equal(await page.locator('.heard-me-path').count(), 0);
        assert.equal(await page.locator('.incoming-path').count(), 1);
        await page.locator('[data-heard-me-toggle]').click();
        await page.waitForFunction(() => document.querySelectorAll('.heard-me-path').length === 2);
        await page.evaluate(() => pvMap.toggleLines());
        assert.equal(await page.locator('.incoming-path').count(), 0);
        assert.equal(await page.locator('.heard-me-path').count(), 2);
        const next = await context.newPage();
        await prepare(next);
        await next.waitForFunction(() => document.querySelectorAll('.heard-me-path').length === 2);
        assert.equal(await next.locator('[data-heard-me-toggle]').getAttribute('aria-pressed'), 'true');
        console.log('PASS Heard me: default off, independent received/sent layers, relay arrows, unresolved hop suppression, saved visibility');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
