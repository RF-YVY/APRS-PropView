const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');

function loadUsability() {
    const handlers = {};
    const tabClicks = [];
    const settingsTab = {classList: {contains: () => false}, click: () => tabClicks.push('tab-settings')};
    const document = {
        addEventListener: (type, fn) => { handlers[type] = fn; },
        querySelector: (selector) => selector.includes('tab-settings') ? settingsTab : null,
        querySelectorAll: () => [],
        getElementById: () => null,
    };
    const context = {document, window: {}, setTimeout: () => 0, console};
    vm.runInNewContext(fs.readFileSync(path.join(root, 'static/js/usability.js'), 'utf8'), context);
    return {click: handlers.click, tabClicks};
}

function overlay(id) {
    return {id, style: {display: 'flex'}};
}

function clickJump(handler, container, data) {
    const button = {
        dataset: data,
        closest: (selector) => selector === '.modal-overlay' ? container : (selector.includes('[data-go-settings]') ? button : null),
    };
    let prevented = false;
    handler({target: button, preventDefault: () => { prevented = true; }});
    return prevented;
}

test('Open settings in Connection Diagnostics closes the diagnostics modal', () => {
    const {click, tabClicks} = loadUsability();
    const diagnostics = overlay('connection-diagnostics-modal');
    assert.equal(clickJump(click, diagnostics, {goSettings: 'radio', goSection: 'aprs-is'}), true);
    assert.equal(diagnostics.style.display, 'none');
    assert.deepEqual(tabClicks, ['tab-settings']);
});

test('a settings jump inside any modal overlay closes that overlay', () => {
    const {click} = loadUsability();
    const terms = overlay('terminology-modal');
    clickJump(click, terms, {goSettings: 'overview'});
    assert.equal(terms.style.display, 'none');
});

test('a settings jump outside any overlay still navigates', () => {
    const {click, tabClicks} = loadUsability();
    clickJump(click, null, {settingsJump: 'station'});
    assert.deepEqual(tabClicks, ['tab-settings']);
});
