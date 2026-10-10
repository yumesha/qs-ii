const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../modules/common/functions/QuickshellCli.js');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(sourcePath, 'utf8').replace(/^\.pragma library\s*/, ''), context);

function invoke(args, overrides = {}) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'qs-cli-test-'));
    try {
        // Exercise the real env command, but never launch a desktop shell.
        fs.symlinkSync(process.execPath, path.join(directory, 'qs'));
        const command = context.command(args);
        return spawnSync(command[0], command.slice(1), {
            encoding: 'utf8',
            timeout: 5000,
            env: {
                ...process.env,
                PATH: `${directory}:${process.env.PATH}`,
                __QUICKSHELL_CRASH_DUMP_PID: '12345',
                __QUICKSHELL_CRASH_INFO_FD: '33',
                QT_QPA_PLATFORM: 'wayland',
                QT_DISABLE_HW_TEXTURES_CONVERSION: '1',
                ...overrides,
            },
        });
    } finally {
        fs.rmSync(directory, { recursive: true, force: true });
    }
}

test('clears private crash flags and preserves graphics settings and literal arguments', () => {
    const unusualPath = '/tmp/wallpapers with spaces/$(not-a-command); "quoted".qml';
    const result = invoke(['-e', `console.log(JSON.stringify({
        crashPid: process.env.__QUICKSHELL_CRASH_DUMP_PID ?? null,
        crashFd: process.env.__QUICKSHELL_CRASH_INFO_FD ?? null,
        platform: process.env.QT_QPA_PLATFORM,
        textures: process.env.QT_DISABLE_HW_TEXTURES_CONVERSION,
        args: process.argv.slice(1)
    }))`, '--', unusualPath]);
    assert.ifError(result.error);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), {
        crashPid: null,
        crashFd: null,
        platform: 'wayland',
        textures: '1',
        args: [unusualPath],
    });
});

test('preserves IPC arguments without modifying the input', () => {
    const args = Object.freeze(['-c', 'ii', 'ipc', 'call', 'videoWallpaper', 'status']);
    const command = Array.from(context.command(args));
    assert.deepEqual(command, [
        'env', '-u', '__QUICKSHELL_CRASH_DUMP_PID',
        '-u', '__QUICKSHELL_CRASH_INFO_FD', 'qs', ...args,
    ]);
});

test('works without crash flags and propagates child failures', () => {
    const result = invoke(['-e', 'process.exit(7)'], {
        __QUICKSHELL_CRASH_DUMP_PID: undefined,
        __QUICKSHELL_CRASH_INFO_FD: undefined,
    });
    assert.ifError(result.error);
    assert.equal(result.status, 7, result.stderr);
});
