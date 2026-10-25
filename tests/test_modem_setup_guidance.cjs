const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function guidance(status, external = []) {
    const fields = {
        'cfg-digi-enabled': {checked: true}, 'cfg-digi-aliases': {value: 'WIDE1-1'},
        'cfg-igate-enabled': {checked: true}, 'cfg-igate-rf2is': {checked: true},
        'cfg-igate-is2rf': {checked: true}, 'cfg-is-enabled': {checked: false},
        'cfg-beacon-interval': {value: '10'}, 'cfg-callsign': {value: 'K5TEST'},
        'cfg-latitude': {value: '34'}, 'cfg-longitude': {value: '-89'},
        'setup-configuration-summary': {}, 'setup-context-checklist': {},
    };
    const context = {window: {}, document: {
        getElementById: id => fields[id],
        querySelectorAll: () => external,
        querySelector: () => null,
        addEventListener: () => {},
    }};
    let source = fs.readFileSync(path.join(__dirname, '../static/js/usability.js'), 'utf8');
    const end = source.lastIndexOf('})();');
    source = source.slice(0, end) + 'window.inspect = status => { modemStatus = status; updateSetupGuidance(CUSTOM_PRESET); return readinessItems(); };' + source.slice(end);
    vm.runInNewContext(source, context);
    const readiness = context.window.inspect(status);
    return {summary: fields['setup-configuration-summary'].innerHTML,
        html: fields['setup-context-checklist'].innerHTML, readiness};
}

test('active built-in RX/TX supplies radio, digipeater and beacon routes', () => {
    const result = guidance({running: true, connected: true, transmit: {enabled: true}});
    assert.match(result.summary, /Built-in modem \(RX \+ TX\)/);
    assert.match(result.html, /Built-in modem receiving/);
    assert.match(result.html, /Built-in modem RF transmit available/);
    assert.match(result.html, /Every 10 min over RF/);
    assert.doesNotMatch(result.html, /RF ports exist|No enabled RF transmit port/);
    assert.ok(!result.readiness.blockers.some(row => row[0] === 'No receive source is enabled.'));
    assert.doesNotMatch(result.html, /enable RF transmission|Allow APRS-IS/);
});

test('RX-only modem counts as reception but cannot provide RF transmission', () => {
    const result = guidance({running: true, connected: true, transmit: {enabled: false}});
    assert.match(result.summary, /Built-in modem \(RX only\)/);
    assert.match(result.html, /Built-in modem is RX only/);
    assert.match(result.html, /no transmit route/);
    assert.ok(!result.readiness.blockers.some(row => row[0] === 'No receive source is enabled.'));
});

test('modem TX supplies the route without a second gating setting', () => {
    const result = guidance({running: true, connected: true,
        transmit: {enabled: true, settings: {allow_is_to_rf: false}}});
    assert.doesNotMatch(result.html, /enable RF transmission and Allow|no enabled port permits/);
    assert.match(result.html, /IS→RF on/);
});

test('stopped or disconnected modem does not satisfy receive checks', () => {
    for (const status of [null, {running: false, connected: false}, {running: true, connected: false, transmit: {enabled: true}}]) {
        const result = guidance(status);
        assert.ok(result.readiness.blockers.some(row => row[0] === 'No receive source is enabled.'));
        assert.doesNotMatch(result.html, /Built-in modem RF transmit available/);
    }
});

test('external gated-transmit port remains available alongside modem', () => {
    const card = {querySelector: selector => {
        const field = selector.match(/data-field="([^"]+)"/)[1];
        return {checked: field === 'enabled', value: {name: 'External TNC', type: 'tcp', host: 'localhost', tcp_port: '8001'}[field] || ''};
    }};
    const result = guidance({running: true, connected: true, transmit: {enabled: false}}, [card]);
    assert.doesNotMatch(result.html, /does not allow IS→RF|no enabled port permits/);
    assert.match(result.html, /External TNC/);
    assert.match(result.html, /Every 10 min over RF/);
});
