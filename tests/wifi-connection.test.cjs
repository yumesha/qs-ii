const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../services/network/WifiConnection.js'), 'utf8')
    .replace(/^\.pragma library\s*/, ''), context);
const plain = value => JSON.parse(JSON.stringify(value));

test('builds a stdin request rather than an executable password command', () => {
    const ap = { ssid: 'Demo network', bssid: '02:00:00:00:00:01', device: 'wlan-test', security: 'WPA2' };
    assert.deepEqual(plain(context.connectRequest(ap, 'fictional-test-password')), {
        ssid: ap.ssid, bssid: ap.bssid, device: ap.device, security: 'wpa-psk', hidden: false,
        password: 'fictional-test-password',
    });
    assert.equal(context.connectCommand, undefined);
});

test('keeps spaces, quotes, and shell metacharacters literal', () => {
    const ssid = 'Cafe: \\"$(not-a-command); network';
    const password = '  fictional \\"$(); password  ';
    const request = plain(context.connectRequest({ ssid, security: 'WPA2' }, password));
    assert.equal(request.ssid, ssid);
    assert.equal(request.password, password);
});

test('use-saved omits a password rather than submitting an empty one', () => {
    assert.ok(!Object.hasOwn(plain(context.connectRequest({ ssid: 'Demo', security: 'WPA2' })), 'password'));
});

test('decodes escaped SSIDs and BSSIDs without a placeholder collision', () => {
    const fields = plain(context.splitFields(String.raw`no:75:5180:Cafe\: West\\Guest:02\:00\:00\:00\:00\:01:WPA2`));
    assert.deepEqual(fields, ['no', '75', '5180', 'Cafe: West\\Guest', '02:00:00:00:00:01', 'WPA2']);
});

test('maps personal, enterprise, and legacy security without silently changing type', () => {
    for (const [input, expected] of [['WPA2', 'wpa-psk'], ['WPA2 WPA3', 'wpa-psk'], ['WPA3', 'sae'],
        ['WPA2 802.1X', 'wpa-eap'], ['WEP', 'wep'], ['', 'open'], ['--', 'open']]) {
        assert.equal(context.securityType(input), expected);
    }
});

test('saved selection matches SSID and security rather than display name', () => {
    const profiles = [{uuid: 'one', name: 'Renamed profile', ssid: 'Demo', security: 'wpa-psk'},
        {uuid: 'two', name: 'Demo', ssid: 'Other', security: 'wpa-psk'},
        {uuid: 'three', name: 'Demo', ssid: 'Demo', security: 'sae'}];
    assert.deepEqual(plain(context.matchingSavedProfiles({ssid: 'Demo', security: 'WPA2'}, profiles)), [profiles[0]]);
});

test('multiple matching saved profiles remain explicit rather than picking one', () => {
    const profiles = [{uuid: 'one', ssid: 'Demo', security: 'wpa-psk'},
        {uuid: 'two', ssid: 'Demo', security: 'wpa-psk'}];
    assert.equal(context.matchingSavedProfiles({ssid: 'Demo', security: 'WPA2'}, profiles).length, 2);
    assert.equal(context.matchingSavedProfiles({ssid: 'New', security: 'WPA2'}, profiles).length, 0);
});

test('active network names ignore bridges and loopback even when listed first', () => {
    const state = plain(context.activeConnectionInfo('Docker:bridge:br-demo\nLoopback:loopback:lo\nExample Profile:802-11-wireless:wlan-demo\n'));
    assert.deepEqual(state, {ethernet: false, wifi: true, ethernetName: '', wifiName: 'Example Profile', wifiDevice: 'wlan-demo'});
});

test('wired and wireless names remain separate when both are connected', () => {
    const state = plain(context.activeConnectionInfo('Example Wired:802-3-ethernet:eth-demo\nExample Profile:802-11-wireless:wlan-demo\n'));
    assert.equal(state.ethernet, true);
    assert.equal(state.wifi, true);
    assert.equal(state.ethernetName, 'Example Wired');
    assert.equal(state.wifiName, 'Example Profile');
});

test('connection-name parsing preserves escaped colons, backslashes, and spaces', () => {
    const state = plain(context.activeConnectionInfo(String.raw`  Example\: Wired\\Home  :802-3-ethernet:eth-demo`));
    assert.equal(state.ethernetName, '  Example: Wired\\Home  ');
});

test('disconnected snapshots clear names instead of retaining stale connectivity', () => {
    for (const input of ['', 'Loopback:loopback:lo\nDocker:bridge:br-demo\n', 'malformed']) {
        assert.deepEqual(plain(context.activeConnectionInfo(input)), {ethernet: false, wifi: false, ethernetName: '', wifiName: '', wifiDevice: ''});
    }
});

test('wireless display uses the active SSID on the selected adapter', () => {
    const networks = [
        {ssid: 'Inactive', active: false, device: 'wlan-demo'},
        {ssid: 'Other adapter', active: true, device: 'wlan-other'},
        {ssid: 'Example <b>Wi-Fi</b>', active: true, device: 'wlan-demo'},
    ];
    assert.equal(context.connectedWifiName(networks, 'wlan-demo'), 'Example <b>Wi-Fi</b>');
    assert.equal(context.connectedWifiName(networks, 'wlan-missing'), '');
    assert.equal(context.connectedWifiName([], 'wlan-demo'), '');
});
