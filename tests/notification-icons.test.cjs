const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const utils = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname,
    '../modules/common/widgets/notification_utils.js'), 'utf8'), utils);
const lookup = name => name === 'known-icon' ? 'image://icon/known-icon' : '';

test('missing notification theme names leave room for sender-specific fallback', () => {
    assert.equal(utils.resolveAppIcon('drive-removable-media', lookup), '');
    assert.equal(utils.resolveAppIcon('battery', lookup), '');
    assert.equal(utils.findSuitableMaterialSymbol('Device added', 'udiskie'), 'usb');
    assert.equal(utils.findSuitableMaterialSymbol('Connected', 'blueman'), 'bluetooth');
    assert.equal(utils.findSuitableMaterialSymbol(null, null), 'chat');
});

test('existing theme icons are used without a missing-image request', () => {
    assert.equal(utils.resolveAppIcon('known-icon', lookup), 'image://icon/known-icon');
    assert.equal(utils.resolveAppIcon('image://icon/known-icon', lookup), 'image://icon/known-icon');
    assert.equal(utils.resolveAppIcon('image://icon/missing?fallback=known-icon', lookup), 'image://icon/known-icon');
    assert.equal(utils.resolveAppIcon('image://icon/missing?fallback=image-missing', lookup), '');
    assert.equal(utils.resolveAppIcon('image://icon/%ZZ', lookup), '');
});

test('absolute icon paths are encoded while existing local/provider URLs are preserved', () => {
    assert.equal(utils.resolveAppIcon('/tmp/example icon#1%.png', lookup),
        'file:///tmp/example%20icon%231%25.png');
    for (const source of ['file:///tmp/example%20icon.png', 'qrc:/example.svg',
        'image://qsimage/example/1', 'image://icon/example?path=/opt/example/icons']) {
        assert.equal(utils.resolveAppIcon(source, lookup), source);
    }
});

test('empty and remote app icons cannot create unwanted image requests', () => {
    for (const source of ['', null, undefined, 'https://example.invalid/icon.png']) {
        assert.equal(utils.resolveAppIcon(source, lookup), '');
    }
});
