"""Offscreen production-QML lifecycle tests; ONLY temporary fake helpers run.

Run: python3 -B -m unittest discover -s tests -p test_desktop_policy_qml.py -v
Missing qs skips these integration tests. No desktop session or backend is used.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
QS = shutil.which("qs")
PASS = "DESKTOP_POLICY_PASS:"

CONFIG = """
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
Singleton {
    id: root
    property bool ready: false
    property bool loaded: false
    property alias options: settings
    function release() { gate.setText("ready"); ready = true; }
    FileView {
        id: gate
        path: Quickshell.shellPath("night-ready")
        blockWrites: true
    }
    Timer { id: save; interval: 30; onTriggered: file.writeAdapter() }
    FileView {
        id: file
        path: Quickshell.shellPath("config.json")
        blockWrites: true
        onLoaded: root.loaded = true
        onAdapterUpdated: if (root.loaded && root.ready) save.restart()
        JsonAdapter {
            id: settings
            property JsonObject light: JsonObject {
                property JsonObject night: JsonObject {
                    property bool automatic: true
                    property bool manualEnabled: false
                    property string from: "19:00"
                    property string to: "06:30"
                    property int colorTemperature: 5000
                }
            }
        }
    }
}
"""

PERSISTENT = """
pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
Singleton {
    id: root
    property bool ready: Quickshell.env("FIXTURE_EARLY_READY") === "1"
    property bool loaded: false
    property bool isNewHyprlandInstance: Quickshell.env("FIXTURE_NEW_SESSION") === "1"
    property alias states: saved
    function release() { gate.setText("ready"); ready = true; }
    FileView {
        id: gate
        path: Quickshell.shellPath("idle-ready")
        blockWrites: true
    }
    Timer { id: save; interval: 30; onTriggered: file.writeAdapter() }
    FileView {
        id: file
        path: Quickshell.shellPath("persistent.json")
        blockWrites: true
        onLoaded: { root.loaded = true; if (root.ready) gate.setText("ready"); }
        onAdapterUpdated: if (root.loaded && root.ready) save.restart()
        JsonAdapter {
            id: saved
            property JsonObject idle: JsonObject {
                property bool inhibit: false
                property string instanceSignature: ""
            }
        }
    }
}
"""

DATETIME = """
pragma Singleton
import QtQuick
import Quickshell
Singleton {
    property QtObject clock: QtObject {
        property int hours: 22
        property int minutes: 0
    }
}
"""

# The only executable on the fixture PATH. Even an accidental production-helper
# path is refused, and fake helpers cannot start subprocesses or signal processes.
LAUNCHER = r"""
import os
from pathlib import Path
import runpy
import sys
root = Path(os.environ["FIXTURE_ROOT"]).resolve()
allowed = {root / "scripts/session/night-light.py", root / "scripts/session/keep-awake.py"}
if len(sys.argv) < 4 or sys.argv[1] != "-B" or Path(sys.argv[2]).resolve() not in allowed:
    print("FORBIDDEN_HELPER_PATH", file=sys.stderr)
    sys.exit(90)
def audit(event, args):
    if event.startswith(("subprocess.", "os.exec", "os.spawn", "os.posix_spawn")) or event in (
        "os.system", "os.kill", "os.killpg"):
        raise RuntimeError("Real subprocesses and process signals are forbidden")
sys.addaudithook(audit)
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""

FAKE_HELPER = r"""
# FIXTURE ONLY: never import or invoke a real desktop helper.
import json
from pathlib import Path
import sys
import time
root = Path(__file__).resolve().parents[2]
name = Path(__file__).name
kind = "night" if name == "night-light.py" else "idle"
args = sys.argv[1:]
control = json.loads((root / "control.json").read_text())
ready = (root / (kind + "-ready")).read_text() == "ready"
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps({"kind": kind, "args": args, "ready": ready}) + "\n")
if not ready:
    print(json.dumps({"ok": False, "error": "HELPER_BEFORE_READY"}))
    sys.exit(91)
if control.get("hold_first") and len((root / "calls.jsonl").read_text().splitlines()) == 1:
    # Keep busy deterministic: the QML scenario explicitly releases its first
    # helper after testing in-flight actions, even on a heavily loaded host.
    for _ in range(300):
        if (root / "helper-release").read_text() == "go":
            break
        time.sleep(0.01)
    else:
        raise RuntimeError("FAKE_HELPER_HOLD_TIMEOUT")
time.sleep(0.12)  # Bounded fake latency only; no desktop operation occurs.
state_path = root / (kind + "-backend.json")
state = json.loads(state_path.read_text()) if state_path.exists() else None
failed = control.get("fail_kind") == kind and control.get("fail_action") == args[0]
if kind == "night":
    assert len(args) == 2 and args[0] in ("on", "off") and args[1] == "5000"
    if not failed:
        state = {"active": args[0] == "on", "temperature": 5000 if args[0] == "on" else None}
else:
    assert args in (["restore"], ["restore", "--legacy-on"], ["on"], ["off"])
    if not failed:
        if args[0] == "restore":
            if state is None:
                state = {"inhibit": "--legacy-on" in args}
        else:
            state = {"inhibit": args[0] == "on"}
    if state is None:
        state = {"inhibit": False}
    state = {"inhibit": state["inhibit"], "backendActive": state["inhibit"]}
if not failed:
    state_path.write_text(json.dumps(state))
response = {"ok": not failed, **(state or {"active": False})}
if failed:
    response["error"] = "Synthetic " + kind + " failure."
print(json.dumps(response))
sys.exit(1 if failed else 0)
"""

SHELL = """
import QtQuick
import Quickshell
import Quickshell.Io
import qs.modules.common
import qs.services
ShellRoot {
    id: root
    property int step: 0
    property int age: 0
    Component.onCompleted: {
        console.log("FIXTURE_ISOLATION: WAYLAND_DISPLAY=" + String(Quickshell.env("WAYLAND_DISPLAY")));
        check(!Quickshell.env("WAYLAND_DISPLAY"), "fixture cannot use a Wayland session");
        check(Quickshell.env("QT_QPA_PLATFORM") === "offscreen", "fixture must be offscreen");
        check(Quickshell.env("QT_QUICK_BACKEND") === "software", "fixture must use software rendering");
    }
    function check(ok, message) {
        if (!ok) {
            console.error("DESKTOP_POLICY_FAIL: " + message);
            Qt.quit();
            throw new Error(message);
        }
    }
    function next() { step++; age = 0; }
    function done() { console.log("__PASS_MARKER__"); Qt.quit(); }
    function tick() {
        age++;
        __SCENARIO__
    }
    FileView {
        id: releaseBackend
        path: Quickshell.shellPath("helper-release")
        blockWrites: true
    }
    Timer { interval: 20; running: true; repeat: true; onTriggered: root.tick() }
    Timer {
        interval: 8000; running: true
        onTriggered: { console.error("DESKTOP_POLICY_TIMEOUT step=" + root.step); Qt.quit(); }
    }
}
"""


@unittest.skipUnless(QS, "qs is not installed")
class DesktopPolicyQmlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="desktop-policy-qml-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ("services/idle", "modules/common/functions", "scripts/session", "bin",
                          "home", "runtime", "config", "cache", "data", "state"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "runtime").chmod(0o700)
        # Isolate each service: Quickshell resolves every type in an imported
        # directory, even services the scenario never instantiates.
        service = "Idle" if self._testMethodName.startswith("test_idle_") else "Hyprsunset"
        for relative in ("services/" + service + ".qml", "services/idle/AwakeSurface.qml",
                         "modules/common/functions/NightLightPolicy.js"):
            shutil.copyfile(ROOT / relative, self.root / relative)
        # Idle imports qs; an uppercase root type makes Quickshell generate
        # that module even though the fixture has no production root singletons.
        self.put("FixtureRoot.qml", "import QtQuick\nQtObject {}\n")
        self.put("modules/common/Config.qml", CONFIG)
        self.put("modules/common/Persistent.qml", PERSISTENT)
        self.put("services/DateTime.qml", DATETIME)
        self.put("bin/python3", "#!" + sys.executable + "\n" + textwrap.dedent(LAUNCHER))
        (self.root / "bin/python3").chmod(0o700)
        for helper in ("night-light.py", "keep-awake.py"):
            self.put("scripts/session/" + helper, FAKE_HELPER)
        self.save("control.json", {})
        self.save("config.json", {"light": {"night": {
            "automatic": True, "manualEnabled": False, "from": "19:00", "to": "06:30",
            "colorTemperature": 5000}}})
        self.save("persistent.json", {"idle": {"inhibit": True}})
        self.put("calls.jsonl", "")

    def put(self, relative, text):
        (self.root / relative).write_text(textwrap.dedent(text), encoding="utf-8")

    def save(self, relative, value):
        self.put(relative, json.dumps(value))

    def saved(self, relative):
        return json.loads((self.root / relative).read_text())

    def night_options(self, **updates):
        config = self.saved("config.json")
        config["light"]["night"].update(updates)
        self.save("config.json", config)

    def run_engine(self, name, scenario, *, early=False, new_session=False):
        for kind in ("night", "idle"):
            self.put(kind + "-ready", "not-ready")
        self.put("helper-release", "wait")
        marker = PASS + name
        self.put("shell.qml", SHELL.replace("__PASS_MARKER__", marker).replace("__SCENARIO__", scenario))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("__QUICKSHELL_CRASH_", "QS_CONFIG_"))
               and key not in ("WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "QS_MANIFEST",
                               "QML_IMPORT_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME")}
        env.update({"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "NO_COLOR": "1",
                    "PATH": str(self.root / "bin"), "HOME": str(self.root / "home"),
                    "FIXTURE_ROOT": str(self.root), "FIXTURE_EARLY_READY": str(int(early)),
                    "FIXTURE_NEW_SESSION": str(int(new_session)), "PYTHONDONTWRITEBYTECODE": "1",
                    "HYPRLAND_INSTANCE_SIGNATURE": "fixture-current",
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(self.root / "no-session-bus")})
        for variable, directory in (("XDG_RUNTIME_DIR", "runtime"), ("XDG_CONFIG_HOME", "config"),
                                    ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data"),
                                    ("XDG_STATE_HOME", "state"), ("XDG_CONFIG_DIRS", "config"),
                                    ("XDG_DATA_DIRS", "data")):
            env[variable] = str(self.root / directory)
        result = subprocess.run([QS, "--no-color", "-p", str(self.root)], cwd=self.root,
                                env=env, capture_output=True, text=True, timeout=12,
                                stdin=subprocess.DEVNULL)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn(marker, output, output)  # Qt.quit() alone can exit zero on failures.
        for bad in ("DESKTOP_POLICY_FAIL", "DESKTOP_POLICY_TIMEOUT", "FORBIDDEN_HELPER_PATH",
                    "HELPER_BEFORE_READY", "Failed to load configuration", "ReferenceError", "TypeError",
                    "No PanelWindow backend loaded"):
            self.assertNotIn(bad, output, output)
        print(output.strip(), flush=True)
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertTrue(all(call["ready"] for call in calls), calls)
        return calls

    def test_night_ready_gate_and_saved_manual_off_survive_fresh_engine(self):
        self.run_engine("night-save-off", """
            if (step === 0) {
                if (!Config.loaded) return;
                Hyprsunset.load(); Hyprsunset.toggle(); Hyprsunset.toggleAutomatic();
                check(!Config.ready && Config.options.light.night.automatic, "early toggles changed Auto");
                check(!Config.options.light.night.manualEnabled, "early toggle changed manual flag");
                next();
            } else if (step === 1 && age > 6) {
                check(!Hyprsunset.applying && !Hyprsunset.active, "work before Config.ready");
                Config.release(); next();
            } else if (step === 2 && age > 8 && !Hyprsunset.applying) {
                check(Hyprsunset.active && Hyprsunset.desiredActive, "night Auto did not turn on");
                Hyprsunset.toggle(); next();
            } else if (step === 3 && age > 12 && !Hyprsunset.applying) {
                check(!Hyprsunset.active && !Hyprsunset.desiredActive, "manual off not applied");
                check(!Config.options.light.night.automatic, "left-click did not leave Auto");
                check(!Config.options.light.night.manualEnabled, "manual off not saved");
                check(Hyprsunset.error === "", Hyprsunset.error); done();
            }
        """)
        saved = self.saved("config.json")["light"]["night"]
        self.assertIs(saved["automatic"], False)
        self.assertIs(saved["manualEnabled"], False)
        self.put("calls.jsonl", "")
        calls = self.run_engine("night-reload-off", """
            if (step === 0) {
                if (!Config.loaded) return;
                check(!Config.options.light.night.automatic, "saved manual mode lost");
                DateTime.clock.hours = 23;
                Hyprsunset.load(); Config.release(); next();
            } else if (step === 1 && age > 12 && !Hyprsunset.applying) {
                check(!Hyprsunset.desiredActive && !Hyprsunset.active, "reload re-enabled night light");
                DateTime.clock.hours = 12; next();
            } else if (step === 2 && age > 6 && !Hyprsunset.applying) {
                check(!Hyprsunset.desiredActive && !Hyprsunset.active, "clock changed manual off");
                done();
            }
        """)
        self.assertTrue(calls)
        self.assertTrue(all(call["kind"] == "night" and call["args"] == ["off", "5000"] for call in calls))
        self.assertEqual(self.saved("night-backend.json"), {"active": False, "temperature": None})

    def test_manual_on_ignores_daytime_and_busy_changes_until_auto_resumes(self):
        self.night_options(automatic=False, manualEnabled=True)
        self.save("control.json", {"hold_first": True})
        calls = self.run_engine("night-manual-on-auto", """
            if (step === 0) {
                if (!Config.loaded) return;
                Hyprsunset.load(); Config.release(); next();
            } else if (step === 1 && Hyprsunset.applying) {
                Hyprsunset.toggle(); Hyprsunset.toggle();
                check(Config.options.light.night.manualEnabled, "latest busy preference lost");
                releaseBackend.setText("go");
                DateTime.clock.hours = 12; next();
            } else if (step === 2 && age > 20 && !Hyprsunset.applying) {
                check(Hyprsunset.active && Hyprsunset.desiredActive, "daytime overrode manual on");
                check(!Config.options.light.night.automatic, "manual mode unexpectedly ended");
                Hyprsunset.toggleAutomatic(); next();
            } else if (step === 3 && age > 12 && !Hyprsunset.applying) {
                check(Config.options.light.night.automatic, "Auto not restored");
                check(!Hyprsunset.active && !Hyprsunset.desiredActive, "Auto ignored daytime");
                check(Hyprsunset.error === "", Hyprsunset.error); done();
            }
        """)
        self.assertEqual(calls[-1]["args"], ["off", "5000"])
        saved = self.saved("config.json")["light"]["night"]
        self.assertIs(saved["automatic"], True)
        self.assertIs(saved["manualEnabled"], True)

    def test_night_helper_error_is_surfaced_without_claiming_active(self):
        self.night_options(automatic=False, manualEnabled=True)
        self.save("control.json", {"fail_kind": "night", "fail_action": "on"})
        self.run_engine("night-error", """
            if (step === 0) {
                if (!Config.loaded) return;
                Hyprsunset.load(); Config.release(); next();
            } else if (step === 1 && age > 12 && !Hyprsunset.applying) {
                check(Hyprsunset.error === "Synthetic night failure.", "night error hidden: " + Hyprsunset.error);
                check(Hyprsunset.desiredActive && !Hyprsunset.active, "failure claimed success"); done();
            }
        """)
        self.assertFalse((self.root / "night-backend.json").exists())

    def test_idle_restores_when_already_ready_and_ignores_busy_toggles(self):
        self.save("control.json", {"hold_first": True})
        calls = self.run_engine("idle-early-busy", """
            if (step === 0) {
                if (!Persistent.loaded) return;
                check(Persistent.ready, "Persistent not ready before Idle singleton access");
                Idle.load(); next();
            } else if (step === 1 && Idle.busy) {
                check(Persistent.states.idle.inhibit, "startup default overwrote legacy true");
                Idle.toggleInhibit(); Idle.toggleInhibit(); releaseBackend.setText("go"); next();
            } else if (step === 2 && Idle.ready && !Idle.busy) {
                check(Idle.inhibit && Idle.backendActive, "legacy restore did not run");
                Idle.toggleInhibit(); Idle.toggleInhibit(); next();
            } else if (step === 3 && age > 8 && !Idle.busy) {
                check(!Idle.inhibit && !Idle.backendActive, "off not applied");
                Idle.toggleInhibit(); Idle.toggleInhibit(); next();
            } else if (step === 4 && age > 12 && !Idle.busy) {
                check(Idle.inhibit && Idle.backendActive && Persistent.states.idle.inhibit, "on not applied");
                check(Idle.error === "", Idle.error); done();
            }
        """, early=True)
        self.assertEqual([call["args"] for call in calls], [["restore", "--legacy-on"], ["off"], ["on"]])
        self.assertIs(self.saved("persistent.json")["idle"]["inhibit"], True)
        self.assertEqual(self.saved("idle-backend.json"), {"inhibit": True, "backendActive": True})

    def test_idle_late_ready_preserves_authoritative_off_despite_stale_legacy_true(self):
        self.save("idle-backend.json", {"inhibit": False, "backendActive": False})
        calls = self.run_engine("idle-late-authoritative-off", """
            if (step === 0) {
                if (!Persistent.loaded) return;
                check(!Persistent.ready, "Persistent should start unready");
                Idle.load(); Idle.toggleInhibit(); next();
            } else if (step === 1 && age > 6) {
                check(!Idle.ready && !Idle.busy, "Idle started before persistence readiness");
                check(Persistent.states.idle.inhibit, "default clobbered legacy before restore");
                Persistent.release(); next();
            } else if (step === 2 && age > 12 && Idle.ready && !Idle.busy) {
                check(!Idle.inhibit && !Idle.backendActive, "stale legacy revived authoritative off");
                check(!Persistent.states.idle.inhibit, "persistent mirror not updated"); done();
            }
        """)
        self.assertEqual([call["args"] for call in calls], [["restore", "--legacy-on"]])
        self.assertIs(self.saved("persistent.json")["idle"]["inhibit"], False)
        self.assertEqual(self.saved("idle-backend.json"), {"inhibit": False, "backendActive": False})

    def test_idle_new_session_does_not_import_legacy_true(self):
        calls = self.run_engine("idle-new-session", """
            if (step === 0) {
                if (!Persistent.loaded) return;
                check(Persistent.ready && Persistent.isNewHyprlandInstance, "new session fixture invalid");
                Idle.load(); next();
            } else if (step === 1 && age > 12 && Idle.ready && !Idle.busy) {
                check(!Idle.inhibit && !Idle.backendActive, "new session inherited legacy true");
                check(!Persistent.states.idle.inhibit, "new session mirror is stale"); done();
            }
        """, early=True, new_session=True)
        self.assertEqual([call["args"] for call in calls], [["restore"]])
        self.assertEqual(self.saved("idle-backend.json"), {"inhibit": False, "backendActive": False})

    def test_idle_old_choice_tag_wins_over_a_matching_global_session(self):
        self.save("persistent.json", {"idle": {"inhibit": True, "instanceSignature": "fixture-previous"}})
        self.assertFalse((self.root / "idle-backend.json").exists())
        calls = self.run_engine("idle-stale-choice-tag", """
            if (step === 0) {
                if (!Persistent.loaded) return;
                check(Persistent.ready && !Persistent.isNewHyprlandInstance, "global session fixture invalid");
                check(Persistent.states.idle.inhibit, "stale choice should start true");
                check(Persistent.states.idle.instanceSignature === "fixture-previous", "old choice tag lost");
                Idle.load(); next();
            } else if (step === 1 && age > 12 && Idle.ready && !Idle.busy) {
                check(!Idle.inhibit && !Idle.backendActive, "global session revived old-session choice");
                check(!Persistent.states.idle.inhibit, "stale true mirror not corrected");
                check(Persistent.states.idle.instanceSignature === "fixture-current", "mirror not retagged");
                check(Idle.error === "", Idle.error); done();
            }
        """, early=True)
        self.assertEqual([call["args"] for call in calls], [["restore"]])
        self.assertEqual(self.saved("idle-backend.json"), {"inhibit": False, "backendActive": False})
        self.assertEqual(self.saved("persistent.json")["idle"],
                         {"inhibit": False, "instanceSignature": "fixture-current"})

    def test_idle_helper_error_is_surfaced_and_authoritative_off_is_preserved(self):
        self.save("idle-backend.json", {"inhibit": False, "backendActive": False})
        self.save("control.json", {"fail_kind": "idle", "fail_action": "on"})
        calls = self.run_engine("idle-error", """
            if (step === 0) {
                if (!Persistent.loaded) return;
                Idle.load(); next();
            } else if (step === 1 && Idle.ready && !Idle.busy) {
                check(!Idle.inhibit, "initial authoritative off lost");
                Idle.toggleInhibit(); next();
            } else if (step === 2 && age > 12 && !Idle.busy) {
                check(Idle.error === "Synthetic idle failure.", "idle error hidden: " + Idle.error);
                check(!Idle.inhibit && !Idle.backendActive, "failed on claimed success");
                check(!Persistent.states.idle.inhibit, "failure changed authoritative mirror"); done();
            }
        """, early=True)
        self.assertEqual([call["args"] for call in calls], [["restore", "--legacy-on"], ["on"]])
        self.assertEqual(self.saved("idle-backend.json"), {"inhibit": False, "backendActive": False})


if __name__ == "__main__":
    unittest.main()
