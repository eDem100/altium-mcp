"""Unit tests for main._bridge_json (no Altium needed: the bridge is faked).

Run from server/:  python -m unittest tests.test_bridge_json -v
"""
import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import main  # noqa: E402


def run(response):
    async def fake(command, params, timeout=None):
        return response
    with mock.patch.object(main.altium_bridge, "execute_command", fake):
        return asyncio.run(main._bridge_json("x", {}))


def route(replies, **kw):
    """route_path with the bridge answering each geometry operation from
    replies; returns the reply and the operations asked for."""
    asked = []

    async def fake(command, params, timeout=None):
        asked.append(params.get("geometry"))
        return replies.get(params.get("geometry")), ""
    with mock.patch.object(main, "_bridge_json", fake):
        out = asyncio.run(main.route_path(None, **kw))
    return json.loads(out), asked


class RoutePathTest(unittest.TestCase):
    LOCATE = {"located": ["pad|0|0|Multi Layer|1|SIG"]}

    def test_through_hole_start_by_flag(self):
        # Altium names the layer "Multi Layer"; the flag says through-hole
        out, _ = route({"locate": self.LOCATE}, net="SIG", start="J1-1", waypoints=[[150, 0]], dry_run=True)
        self.assertTrue(out["success"])
        self.assertEqual(out["tracks"][0][0], "Top Layer")

    def test_removed_route_is_no_success(self):
        made = "track|Top Layer|SIG||0|0|1500000|0|100000|0"
        out, asked = route({"locate": self.LOCATE, "route": {"created": [made], "violations": [],
                                                              "removed_again": True}},
                           net="SIG", start="J1-1", waypoints=[[150, 0]], undo_on_violation=True)
        self.assertEqual(asked, ["locate", "route"])
        self.assertFalse(out["success"])
        self.assertEqual((out["tracks"], out["vias"]), ([], []))
        self.assertIn("plan", out)

    def test_undo_needs_the_check(self):
        out, asked = route({}, net="SIG", start=[0, 0, "Top Layer"], waypoints=[[150, 0]], check=False,
                           undo_on_violation=True)
        self.assertFalse(out["success"])
        self.assertIn("needs check", out["error"])
        self.assertEqual(asked, [])

    def test_route_is_a_change(self):
        self.assertTrue(main._is_mutating("geometry", {"geometry": "route"}))
        self.assertFalse(main._is_mutating("geometry", {"geometry": "locate"}))


class BridgeJsonTest(unittest.TestCase):
    def test_replies(self):
        self.assertEqual(run({"success": True, "result": {"a": 1}}), ({"a": 1}, ""))
        self.assertEqual(run({"success": True, "result": '{"a": "x\ty"}'}), ({"a": "x\ty"}, ""))
        self.assertEqual(run({"success": False, "error": "boom"}), (None, "boom"))
        self.assertEqual(run({"success": True, "result": "ERROR: no board"}), (None, "ERROR: no board"))
        self.assertIn("unexpected", run({"success": True, "result": "garbage"})[1])
        self.assertIn("unexpected", run({"success": True, "result": [1, 2]})[1])


class FakeLock:
    async def acquire(self, timeout):
        return True

    def release(self):
        pass


class ListenerGateTest(unittest.TestCase):
    """FORK: with Altium running and its listener silent, AltiumBridge sends
    nothing and starts no X2.EXE, and a request no bridge script took never
    stays behind. Windows and Altium are faked; the exchange files go to a
    temporary folder, never to the real one a live listener polls."""

    def patch(self, target, attribute, value):
        p = mock.patch.object(target, attribute, value)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        self.patch(main, "EXCHANGE_DIR", folder)
        for name, file_name in (("REQUEST_FILE", "request.json"), ("RESPONSE_FILE", "response.json"),
                                ("PROGRESS_FILE", "progress.txt"), ("STUCK_MARKER", "stuck.txt")):
            self.patch(main, name, folder / file_name)
        # Altium and the script project "exist", so a launch that slipped
        # through would get as far as Popen (a mock) and fail the test there,
        # quickly: a request nobody takes is given up after START_TIMEOUT
        for file_name in ("X2.EXE", "Altium_API.PrjScr"):
            (folder / file_name).write_bytes(b"")
        self.patch(main, "START_TIMEOUT", 0.2)
        # Anything that would reach the real Altium is a mock that must stay unused
        self.popen = mock.Mock(name="Popen")
        self.patch(main.subprocess, "Popen", self.popen)
        self.dismiss = mock.Mock(name="_dismiss_altium_dialogs", return_value=[])
        self.patch(main, "_dismiss_altium_dialogs", self.dismiss)
        self.patch(main, "_guard_foreground", mock.Mock(name="_guard_foreground"))
        self.patch(main, "altium_limit_problem", lambda: None)
        self.patch(main.sandbox, "altium_hung", lambda: False)
        self.set_state(listener=False, running=True)

        bridge = main.AltiumBridge.__new__(main.AltiumBridge)
        bridge.config = types.SimpleNamespace(altium_exe_path=str(folder / "X2.EXE"),
                                              script_path=str(folder / "Altium_API.PrjScr"))
        bridge._asked_for_paths = True
        bridge._command_lock = asyncio.Lock()
        bridge._exchange_lock = FakeLock()
        bridge._leave_altium_in_front = False
        bridge._via_listener = False

        async def ensure_paths(need_script=True):
            return None

        bridge.ensure_paths = ensure_paths
        self.bridge = bridge

    def set_state(self, listener, running):
        self.patch(main, "listener_is_live", lambda: listener)
        self.patch(main.AltiumBridge, "_altium_running", staticmethod(lambda: running))

    def assert_nothing_launched(self):
        self.popen.assert_not_called()
        self.dismiss.assert_not_called()
        self.assertFalse(main.REQUEST_FILE.exists())

    def test_nothing_sent_while_altium_runs_without_the_listener(self):
        response = asyncio.run(self.bridge.execute_command("get_all_designators", {}))
        self.assertFalse(response["success"])
        for advice in ("Nothing was sent", "Ctrl+F3", "McpListener.pas", "StartMcpListener"):
            self.assertIn(advice, response["error"])
        self.assert_nothing_launched()

    def test_nothing_sent_without_altium(self):
        self.set_state(listener=False, running=False)
        response = asyncio.run(self.bridge.execute_command("get_all_designators", {}))
        self.assertFalse(response["success"])
        self.assertIn("Altium Designer is not running", response["error"])
        self.assert_nothing_launched()

    def test_follow_up_command_of_a_failed_query_is_refused(self):
        # 2026-11-22: query_objects failed after its script paused in Altium's
        # debugger, which silenced the listener; the query_restore that
        # _run_query sends next opened a second Altium on the command line
        import pcb_query
        calls = []

        async def execute(command, params, timeout=main.RESPONSE_TIMEOUT, watcher=None, **kw):
            calls.append(command)
            if command == "query_objects":
                await watcher(asyncio.Event())
                return {"success": False, "error": "No response from Altium"}
            return await main.AltiumBridge.execute_command(self.bridge, command, params,
                                                           timeout=timeout, watcher=watcher, **kw)

        async def watch_errors(errors, abort):
            errors.append("Continue execution?")

        self.bridge.execute_command = execute
        with mock.patch.object(main, "altium_bridge", self.bridge), \
                mock.patch.object(pcb_query, "watch_errors", watch_errors):
            result, error = asyncio.run(main._run_query("query_objects", {"board_path": "b.PcbDoc"}))
        self.assertEqual(calls, ["query_objects", "query_restore"])
        self.assertIsNone(result)
        self.assertIn("could not be restored", error)
        self.assertIn("Ctrl+F3", error)
        self.assert_nothing_launched()

    def test_launchers_refuse_while_altium_runs(self):
        self.assertFalse(asyncio.run(self.bridge.run_altium_script()))
        asyncio.run(self.bridge.stop_script_debugger())
        self.popen.assert_not_called()
        self.dismiss.assert_not_called()

    def listener_takes(self, reply):
        """_wait_for_start as a live listener runs it: takes the request, answers."""
        async def take(timeout):
            request = json.loads(main.REQUEST_FILE.read_text())
            main.REQUEST_FILE.unlink()
            main.RESPONSE_FILE.write_text(json.dumps({**reply, "request_id": request["request_id"]}))
            return True
        return take

    def test_listener_path_answers_and_launches_nothing(self):
        # The control: the harness can succeed, so the refusals above are the gate's
        self.set_state(listener=True, running=True)
        self.bridge._wait_for_start = self.listener_takes({"success": True, "result": {"n": 1}})
        response = asyncio.run(self.bridge.execute_command("get_all_designators", {}))
        self.assertTrue(response["success"], response)
        self.assertEqual(response["result"], {"n": 1})
        self.assert_nothing_launched()

    def test_request_not_picked_up_is_removed(self):
        self.set_state(listener=True, running=True)

        async def not_taken(timeout):
            return False
        self.bridge._wait_for_start = not_taken
        response = asyncio.run(self.bridge.execute_command("get_all_designators", {}))
        self.assertFalse(response["success"])
        self.assertIn("did not pick", response["error"])
        self.assert_nothing_launched()

    def test_request_removed_when_waiting_for_the_listener_fails(self):
        self.set_state(listener=True, running=True)
        seen = []

        async def broken(timeout):
            seen.append(main.REQUEST_FILE.exists())
            raise OSError("exchange folder unreadable")
        self.bridge._wait_for_start = broken
        response = asyncio.run(self.bridge.execute_command("get_all_designators", {}))
        self.assertEqual(seen, [True])
        self.assertFalse(response["success"])
        self.assertIn("exchange folder unreadable", response["error"])
        self.assert_nothing_launched()

    def test_request_removed_when_the_call_is_cancelled(self):
        self.set_state(listener=True, running=True)

        async def never(timeout):
            await asyncio.sleep(60)
            return False
        self.bridge._wait_for_start = never

        async def cancel_while_waiting():
            task = asyncio.create_task(self.bridge.execute_command("get_all_designators", {}))
            for _ in range(500):
                if main.REQUEST_FILE.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(main.REQUEST_FILE.exists())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(cancel_while_waiting())
        self.assert_nothing_launched()

    def test_withdraw_leaves_another_request_alone(self):
        main.REQUEST_FILE.write_text(json.dumps({"command": "x", "request_id": "theirs"}))
        self.assertFalse(main._withdraw_request("mine"))
        self.assertTrue(main.REQUEST_FILE.exists())
        self.assertTrue(main._withdraw_request("theirs"))
        self.assertFalse(main.REQUEST_FILE.exists())
        self.assertFalse(main._withdraw_request("theirs"))  # nothing left: no error


if __name__ == "__main__":
    unittest.main()
