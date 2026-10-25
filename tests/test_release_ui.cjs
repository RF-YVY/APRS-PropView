const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');

test('desktop and mobile uptime roll over at 24 hours and retain seconds', () => {
    for (const file of ['static/js/app.js', 'static/mobile.html']) {
        const source = fs.readFileSync(path.join(root, file), 'utf8');
        const start = source.indexOf('function updateUptime()');
        const end = source.indexOf('\n}', start) >= 0 && file.endsWith('.html')
            ? source.indexOf('\n}', start)+2 : source.indexOf('\n    }', start)+6;
        const fn = source.slice(start, end);
        for (const [seconds, expected] of [[0,'00:00:00'],[86399,'23:59:59'],[86400,'01:00:00:00'],[176461,'02:01:01:01'],[8640000,'100:00:00:00']]) {
            let actual;
            const context = {Date: {now: () => 1e12}, uptimeStart: 1e9-seconds,
                S: {startTime: 1e9-seconds}, $: () => ({set textContent(value){actual=value;}}),
                setTextById: (_, value) => {actual=value.replace('Uptime: ', '');}};
            vm.runInNewContext(fn+'\nupdateUptime();', context);
            assert.equal(actual, expected, `${file} at ${seconds}s`);
        }
    }
});

test('primary modem controls are adjacent and WAV test UI is removed', () => {
    const source = fs.readFileSync(path.join(root,'static/js/software-modem.js'),'utf8');
    const panel = source.slice(source.indexOf('<div class="modem-primary-controls"'), source.indexOf('</div>', source.indexOf('<div class="modem-primary-controls"')));
    assert.equal((source.match(/id="modem-tx-enabled"/g)||[]).length,1);
    assert.equal((source.match(/id="modem-tx-wait-clear"/g)||[]).length,1);
    assert.match(panel,/id="modem-tx-enabled"/);
    assert.match(panel,/id="modem-tx-wait-clear"[^>]*checked/);
    assert.doesNotMatch(source,/id="modem-tx-enabled"[^>]*checked/);
    assert.match(source,/<details id="modem-tx-panel" open>/);
    assert.doesNotMatch(source,/Test with a WAV|modem-decode|modem-wav|test-wav/);
});

test('toolbar session control includes visible Login text', () => {
    const source=fs.readFileSync(path.join(root,'static/js/operator-auth.js'),'utf8');
    assert.match(source,/<\/svg><span>Login<\/span><\/button>/);
});
