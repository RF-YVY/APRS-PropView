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
    assert.doesNotMatch(source,/modem-tx-is-to-rf|allow_is_to_rf/);
});

test('toolbar session control includes visible Login text', () => {
    const source=fs.readFileSync(path.join(root,'static/js/operator-auth.js'),'utf8');
    assert.match(source,/<\/svg><span>Login<\/span><\/button>/);
});

test('desktop and mobile uptime follows server age across reloads and partial status updates', () => {
    for (const file of ['static/js/app.js', 'static/mobile.html']) {
        const source = fs.readFileSync(path.join(root,file),'utf8');
        const start = source.indexOf('function syncServerUptime(status)');
        const end = source.indexOf('function updateUptime()',start);
        const fn = source.slice(start,end);
        const context = {Date:{now:()=>1000000000}, uptimeStart:0, S:{startTime:0}, updateUptime:()=>{}};
        const getStart = () => file.endsWith('.html') ? context.S.startTime : context.uptimeStart;
        vm.runInNewContext(fn+'\nsyncServerUptime({uptime_seconds:7200});',context);
        assert.equal(getStart(),1000000-7200);
        for (const value of [undefined, null, -1, NaN, Infinity, '7200']) {
            context.status={uptime_seconds:value};
            vm.runInNewContext('syncServerUptime(status);',context);
            assert.equal(getStart(),1000000-7200,`${file}: partial/invalid update must preserve server age`);
        }
        // A new browser document resynchronizes to the same still-running server.
        context.uptimeStart=0; context.S.startTime=0;
        context.Date.now=()=>1000010000;
        vm.runInNewContext('syncServerUptime({uptime_seconds:7210});',context);
        assert.equal(getStart(),1000000-7200);
        // Only a restarted server reporting zero resets the displayed age.
        vm.runInNewContext('syncServerUptime({uptime_seconds:0});',context);
        assert.equal(getStart(),1000010);
    }
});
