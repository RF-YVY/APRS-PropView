const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');

// Dictionaries keyed by callsign. APRS-IS accepts lower-case callsigns, so a
// station named toString or valueOf must not find Object.prototype members.
const KEYED = ['rfMarkers', 'isMarkers', 'rfLines', 'isLines', 'rfArrows', 'rfLineData',
    'stationMeta', 'hopMarkers', 'rfStations', 'isStations', 'nextMap'];
const FILES = ['static/js/map.js', 'static/js/stations.js', 'static/mobile.html'];

test('callsign-keyed dictionaries never start from a plain object literal', () => {
    const plain = new RegExp(`\\b(${KEYED.join('|')})\\s*(=|:)\\s*\\{\\s*\\}`, 'g');
    for (const file of FILES) {
        const source = fs.readFileSync(path.join(root, file), 'utf8');
        assert.deepEqual([...source.matchAll(plain)].map((m) => m[0]), [], file);
    }
});

test('a null-prototype dictionary has no inherited callsigns', () => {
    const markers = Object.create(null);
    for (const call of ['toString', 'valueOf', 'constructor', 'hasOwnProperty']) {
        assert.equal(markers[call], undefined, call);
        assert.equal(call in markers, false, call);
    }
    markers.toString = 'marker';
    assert.deepEqual(Object.keys(markers), ['toString']);
});
