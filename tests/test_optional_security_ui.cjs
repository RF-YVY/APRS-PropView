// Run with NODE_PATH set to a Playwright installation; no radio or external feeds.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
(async () => {
    const browser = await chromium.launch({ channel: 'msedge', headless: true });
    try {
        let enabled = false, authenticated = true, saves = 0;
        const page = await browser.newPage({ viewport: {width: 1000, height: 780} });
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        const section = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8')
            .split('<div class="settings-section" data-settings-key="security"')[1].split('<!-- Web Interface -->')[0];
        await page.route('**/*', async route => {
            const url = new URL(route.request().url());
            if (url.pathname.startsWith('/static/')) return route.fulfill({ path: path.join(root, url.pathname) });
            if (url.pathname === '/api/auth/security') {
                const body = route.request().postDataJSON();
                assert.equal(route.request().headers()['x-propview-csrf'], 'test-csrf');
                assert.equal(body.password, body.enabled ? 'new test password' : undefined);
                enabled = body.enabled; authenticated = true; saves++;
            }
            if (url.pathname.startsWith('/api/')) return route.fulfill({json: { enabled,
                authenticated, configured: enabled, expires_at: enabled ? Date.now()/1000+3600 : null,
                csrf_token: 'test-csrf', durations: [900,3600,28800] }});
            return route.fulfill({contentType: 'text/html', body: `<!doctype html><html><head>
                <link rel="stylesheet" href="/static/css/operator-auth.css">
                <script src="/static/js/operator-auth.js"></script></head><body style="background:#101820;color:white;font:16px system-ui;padding:30px">
                <h1>Settings</h1><div class="settings-section" data-settings-key="security"${section}
                <div id="map-controls"></div><button data-operator-only id="test-transmit">Transmit</button></body></html>` });
        });
        await page.goto('http://propview.test/');
        await page.waitForFunction(() => window.pvOperator?.authenticated);
        assert.equal(await page.locator('#operator-access').isVisible(), false);
        assert.equal(await page.locator('#test-transmit').isVisible(), true);
        assert.equal(await page.locator('#cfg-security-enabled').isChecked(), false);
        await page.locator('#cfg-security-enabled').check();
        await page.locator('#security-setup-dialog').waitFor({state:'visible'});
        await page.locator('#security-new-password').fill('new test password');
        await page.locator('#security-confirm-password').fill('mismatched password');
        await page.locator('#security-setup-submit').click();
        assert.match(await page.locator('#security-setup-error').innerText(), /do not match/);
        assert.equal(saves, 0);
        await page.locator('#security-setup-cancel').click();
        await page.waitForFunction(() => !document.getElementById('cfg-security-enabled').checked);
        assert.equal(await page.locator('#security-new-password').inputValue(), '');
        await page.locator('#cfg-security-enabled').check();
        await page.locator('#security-new-password').fill('new test password');
        await page.locator('#security-confirm-password').fill('new test password');
        await Promise.all([page.waitForEvent('load'), page.locator('#security-setup-submit').click()]);
        await page.locator('#operator-access').waitFor({state:'visible'});
        assert.equal(await page.locator('#cfg-security-enabled').isChecked(), true);
        assert.equal(saves, 1);
        await Promise.all([page.waitForEvent('load'), page.locator('#cfg-security-enabled').uncheck()]);
        await page.waitForFunction(() => window.pvOperator?.authenticated);
        assert.equal(await page.locator('#operator-access').isVisible(), false);
        assert.equal(saves, 2);
        enabled = true; authenticated = false;
        await page.reload();
        await page.locator('#operator-access').waitFor({state:'visible'});
        assert.equal(await page.locator('#test-transmit').isVisible(), false);
        await page.locator('#operator-session-toggle').click();
        await page.locator('#operator-login').click();
        assert.equal(await page.locator('#operator-login-dialog').isVisible(), true);
        assert.deepEqual(errors, []);
        console.log('PASS: default unlocked/hidden login, password mismatch/cancel, enable, disable, protected viewer login');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
