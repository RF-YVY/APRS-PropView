const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
let chromium;
try { ({chromium} = require('playwright')); } catch (_) {}
const root = path.resolve(__dirname, '..');

test('appearance preferences persist, render text safely, and keep dashboards usable', {skip: !chromium}, async () => {
    const browser = await chromium.launch({channel: process.env.PV_TEST_BROWSER || (process.platform === 'win32' ? 'msedge' : undefined), headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
        if (process.env.PV_DEBUG_BROWSER) page.on('pageerror', error => console.error(error.message));
        page.setDefaultTimeout(10000);
        await page.route('**/*', async route => {
            const url = new URL(route.request().url());
            if (url.hostname !== 'appearance.test') return route.abort();
            if (url.pathname === '/api/auth/status') return route.fulfill({json: {authenticated:true,configured:true,expires_at:Date.now()/1000+3600,csrf_token:'test'}});
            if (url.pathname === '/api/header-image') return route.fulfill({path:path.join(root,'static/img/app-icon.webp'),contentType:'image/webp'});
            if (url.pathname.startsWith('/api/')) return route.fulfill({json:{station:{callsign:'K5YVY',ssid:1,latitude:34,longitude:-88},web:{},stations:[],packets:[],history:[],messages:[],contacts:[]}});
            const relative = url.pathname === '/' ? 'static/index.html' : url.pathname.slice(1);
            const file = path.resolve(root,relative);
            if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) return route.fulfill({status:404,body:''});
            const type = file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : undefined;
            return route.fulfill({path:file,contentType:type});
        });
        await page.addInitScript(() => localStorage.setItem('pvQuickStartSeenV1', '1'));
        async function openAppearance() {
            if (!await page.locator('#tab-settings').evaluate(el=>el.classList.contains('active'))) await page.locator('.tab-btn[data-tab="tab-settings"]').click();
            await page.evaluate(() => window.pvActivateSettingsCategory('display'));
            await page.locator('[data-settings-key="appearance"]').evaluate(el=>el.classList.remove('collapsed'));
        }
        await page.goto('http://appearance.test/');
        await page.waitForFunction(()=>typeof window.pvActivateSettingsCategory === 'function');
        await openAppearance();
        assert.equal(await page.locator('[data-settings-key="appearance"] #cfg-header-image').count(),1);
        await page.locator('#cfg-station-label').fill('<img src=x onerror=alert(1)>');
        assert.equal(await page.locator('#station-custom-label img').count(),0);
        assert.equal(await page.locator('#station-custom-label').textContent(),'<img src=x onerror=alert(1)>');
        await page.locator('#cfg-station-label').fill('YVY Radio Club');
        await page.locator('#cfg-ui-accent').selectOption('amber');
        await page.locator('#cfg-ui-density').selectOption('comfortable');
        await page.locator('#appearance-tab-order button[data-view="tab-prop"][data-action="up"]').click();
        await page.locator('#appearance-panel-order button[data-panel="history"][data-action="up"]').click();
        const cardIds = await page.locator('#tab-prop .prop-detail > [id]').evaluateAll(els=>els.map(el=>el.id));
        assert.ok(cardIds.indexOf('prop-history-heading') < cardIds.indexOf('prop-distance-heading'));
        await page.locator('#cfg-dashboard-watched-paths').uncheck();
        assert.ok(await page.locator('#watched-paths-panel').evaluate(el=>el.classList.contains('dashboard-panel-user-hidden')));
        await page.locator('#appearance-tab-order input[data-view="tab-rf"]').uncheck();
        await page.reload();
        await openAppearance();
        assert.equal(await page.locator('#cfg-station-label').inputValue(),'YVY Radio Club');
        assert.equal(await page.locator('html').getAttribute('data-ui-accent'),'amber');
        assert.equal(await page.locator('html').getAttribute('data-ui-density'),'comfortable');
        assert.equal(await page.locator('.tab-btn[data-tab="tab-rf"]').isVisible(),false);
        assert.equal(await page.locator('#cfg-dashboard-watched-paths').isChecked(),false);
        assert.ok(await page.locator('#tab-prop .prop-detail').evaluate(el=>[...el.children].findIndex(e=>e.id==='prop-history-heading') < [...el.children].findIndex(e=>e.id==='prop-distance-heading')));
        await page.locator('#appearance-layout-reset').click();
        assert.equal(await page.locator('.tab-btn[data-tab="tab-rf"]').getAttribute('hidden'),null);
        for (const id of ['tab-rf','tab-is','tab-packets','tab-messages','tab-prop']) await page.locator(`#appearance-tab-order input[data-view="${id}"]`).uncheck();
        await page.locator('#appearance-tab-order input[data-view="tab-analytics"]').click();
        assert.equal(await page.locator('#appearance-tab-order input[data-view="tab-analytics"]').isChecked(),true);
        assert.match(await page.locator('#appearance-layout-status').textContent(),/at least one/);
        await page.locator('#appearance-layout-reset').click();
        if (process.env.PV_APPEARANCE_SCREENSHOT) {
            await page.locator('#cfg-station-label').scrollIntoViewIfNeeded();
            await page.screenshot({path:process.env.PV_APPEARANCE_SCREENSHOT.replace('.png','-desktop.png')});
        }
        await page.setViewportSize({width:390,height:844});
        await page.locator('#cfg-station-label').scrollIntoViewIfNeeded();
        assert.equal(await page.locator('#appearance-tab-order').evaluate(el=>el.scrollWidth <= el.clientWidth),true);
        if (process.env.PV_APPEARANCE_SCREENSHOT) await page.screenshot({path:process.env.PV_APPEARANCE_SCREENSHOT});
    } finally { await browser.close(); }
});
