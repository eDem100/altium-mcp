"""Local transport for the approved Access Controller read-only profile."""
import atexit
import asyncio
import json
import logging
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

from mcp.server.fastmcp import FastMCP
from pilot_policy import Policy, validate_command, build_launch_args

MCP_DIR = Path(__file__).resolve().parent
POLICY = Policy(MCP_DIR / "pilot_policy.json")
POLICY.verify_paths()
EXCHANGE_DIR = Path(POLICY.data["exchange_dir"])
REQUEST_FILE = EXCHANGE_DIR / "request.json"
RECOVERY_FILE = EXCHANGE_DIR / "RECOVERY_REQUIRED.json"
ACTIVE_FILE = EXCHANGE_DIR / "IN_FLIGHT.json"


class SingleInstance:
    def __init__(self, path):
        self.handle = open(path, "a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            raise RuntimeError("PILOT_SERVER_ALREADY_RUNNING") from None

    def close(self):
        if not self.handle.closed:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            self.handle.close()


INSTANCE = SingleInstance(EXCHANGE_DIR / "server.lock")
atexit.register(INSTANCE.close)
if RECOVERY_FILE.exists() or ACTIVE_FILE.exists():
    raise RuntimeError("RECOVERY_REQUIRED: inspect the previous failed native call before restarting")

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("AltiumCommunityRead")
mcp = FastMCP("AltiumCommunityRead", description="Read-only manifest-scoped project; no design writes")


class PilotBridge:
    def __init__(self):
        self.config = SimpleNamespace(
            altium_exe_path=POLICY.data["altium_exe_path"],
            script_path=POLICY.data["script_path"],
        )
        self._command_lock = asyncio.Lock()

    def mark_recovery(self, request_id, reason):
        payload = {"request_id": request_id, "reason": reason,
                   "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        RECOVERY_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")

    async def execute_command(self, command, params):
        validate_command(command, params)
        async with self._command_lock:
            if RECOVERY_FILE.exists() or ACTIVE_FILE.exists():
                raise RuntimeError("RECOVERY_REQUIRED")
            POLICY.verify_paths()
            launch_args = build_launch_args(self.config.altium_exe_path, self.config.script_path)
            request_id = uuid.uuid4().hex
            response_file = EXCHANGE_DIR / ("response-" + request_id + ".json")
            request = {"command": command, "request_id": request_id,
                       "policy_id": POLICY.identity, **params}
            temporary = EXCHANGE_DIR / ("request-" + request_id + ".tmp")
            with temporary.open("x", encoding="ascii", newline="\n") as stream:
                json.dump(request, stream, ensure_ascii=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, REQUEST_FILE)
            with ACTIVE_FILE.open("x", encoding="ascii") as stream:
                json.dump({"request_id": request_id, "command": command}, stream)
            # Altium parses this parameter itself; CRT-escaped inner quotes
            # become literal backslashes. This fixed pilot path has no spaces.
            logger.info("Native read started command=%s request_id=%s", command, request_id)
            try:
                process = subprocess.Popen(
                    launch_args, shell=False,
                    stdin=subprocess.DEVNULL, stdout=sys.stderr, stderr=sys.stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError:
                self.mark_recovery(request_id, "LAUNCH_FAILED")
                raise
            deadline = time.monotonic() + 120.0
            try:
                while not response_file.is_file():
                    if time.monotonic() >= deadline:
                        self.mark_recovery(request_id, "NATIVE_RESPONSE_TIMEOUT")
                        raise TimeoutError("NATIVE_RESPONSE_TIMEOUT; no retry until native state is inspected")
                    process.poll()
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                self.mark_recovery(request_id, "NATIVE_CALL_CANCELLED")
                raise
            try:
                if response_file.stat().st_size > 32 * 1024 * 1024:
                    raise ValueError("RESPONSE_TOO_LARGE")
                raw = response_file.read_text(encoding="utf-8-sig")
                response = POLICY.validate_response(raw, request_id, command)
            except (ValueError, KeyError, TypeError, PermissionError, UnicodeError):
                self.mark_recovery(request_id, "RESPONSE_REJECTED")
                raise
            logger.info("Native read completed command=%s request_id=%s success=%s",
                        command, request_id, response["success"])
            ACTIVE_FILE.unlink()
            return response


altium_bridge = PilotBridge()
