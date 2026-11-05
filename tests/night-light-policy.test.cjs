const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'modules/common/functions/NightLightPolicy.js'), 'utf8');
function loadPolicy() {
    const context = vm.createContext({});
    vm.runInContext(source.replace(/^\.pragma library\s*/, ''), context);
    return context;
}
const policy = loadPolicy();
const defaults = { automatic: true, manualEnabled: false, from: '19:00', to: '06:30' };

function assertSchedule(from, to, cases) {
    for (const [hour, minute, expected] of cases) {
        assert.equal(policy.scheduled(hour, minute, from, to), expected,
            `${from}–${to} at ${hour}:${minute}`);
    }
}

test('parses valid times, including the supported single-digit hour', () => {
    for (const [value, expected] of [['00:00', 0], ['06:30', 390], ['9:05', 545], ['23:59', 1439]]) {
        assert.equal(policy.minutes(value), expected, value);
    }
});

test('rejects invalid HH:mm inputs and disables schedules with either invalid endpoint', () => {
    const invalid = ['', null, undefined, false, 1234, '24:00', '25:10', '12:60', '-1:00',
        '01:-1', '1:2', '001:00', '12', 'noon', '12:00:00', ' 12:00', '12:00 ', '12:00\n'];
    for (const value of invalid) {
        assert.equal(policy.minutes(value), null, `invalid time ${JSON.stringify(value)}`);
        assert.equal(policy.scheduled(12, 0, value, '19:00'), false);
        assert.equal(policy.scheduled(12, 0, '06:30', value), false);
    }
});

test('same-day schedule has an inclusive start and exclusive end', () => {
    assertSchedule('06:30', '19:00', [
        [0, 0, false], [6, 29, false], [6, 30, true], [12, 0, true],
        [18, 59, true], [19, 0, false], [23, 59, false],
    ]);
});

test('overnight schedule crosses midnight without losing boundary semantics', () => {
    assertSchedule('19:00', '06:30', [
        [18, 59, false], [19, 0, true], [23, 59, true], [0, 0, true],
        [6, 29, true], [6, 30, false], [12, 0, false],
    ]);
});

test('midnight can be an inclusive start or exclusive end', () => {
    assertSchedule('00:00', '06:30', [[23, 59, false], [0, 0, true], [6, 29, true], [6, 30, false]]);
    assertSchedule('19:00', '00:00', [[18, 59, false], [19, 0, true], [23, 59, true], [0, 0, false]]);
});

test('equal valid endpoints mean a full day, not an empty interval', () => {
    for (const endpoint of ['00:00', '06:30', '23:59']) {
        for (const [hour, minute] of [[0, 0], [6, 30], [12, 0], [23, 59]]) {
            assert.equal(policy.scheduled(hour, minute, endpoint, endpoint), true);
        }
    }
    assert.equal(policy.scheduled(12, 0, 'invalid', 'invalid'), false);
});

test('out-of-range clock values cannot enable even a full-day schedule', () => {
    for (const [hour, minute] of [[-1, 0], [24, 0], [12, -1], [12, 60]]) {
        assert.equal(policy.scheduled(hour, minute, '00:00', '00:00'), false);
    }
});

for (const enabled of [true, false]) {
    test(`manual ${enabled ? 'on' : 'off'} overrides the schedule without mutating preferences`, () => {
        const options = { ...defaults, automatic: false, manualEnabled: enabled };
        const before = { ...options };
        for (const [hour, minute] of [[0, 0], [6, 30], [12, 0], [19, 0], [23, 59]]) {
            assert.equal(policy.desired(options, hour, minute), enabled);
        }
        assert.equal(policy.desired({ ...options, from: 'invalid', to: 'invalid' }, -1, 99), enabled);
        assert.deepEqual(options, before);
    });
}

test('re-enabling Auto resumes the schedule regardless of the saved manual choice', () => {
    for (const manualEnabled of [true, false]) {
        const options = { ...defaults, automatic: false, manualEnabled };
        assert.equal(policy.desired(options, 12, 0), manualEnabled);
        options.automatic = true;
        for (const [hour, minute, expected] of [[18, 59, false], [19, 0, true], [0, 0, true], [6, 30, false]]) {
            assert.equal(policy.desired(options, hour, minute), expected);
        }
        assert.equal(options.manualEnabled, manualEnabled);
    }
});

test('manual mode requires an explicit boolean true rather than a truthy saved value', () => {
    for (const manualEnabled of [undefined, null, false, 0, 1, 'true', 'false']) {
        assert.equal(policy.desired({ ...defaults, automatic: false, manualEnabled }, 19, 0), false);
    }
});
