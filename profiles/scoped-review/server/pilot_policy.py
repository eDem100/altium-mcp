"""Read-only pilot policy. No process launch or filesystem mutation on import."""
import hashlib
import json
import ntpath
import re
import math
from pathlib import Path

TOOLS = frozenset({
    "get_server_status", "get_read_context", "get_all_designators",
    "get_component_data", "get_component_pins", "get_all_nets",
    "get_pcb_layers", "get_pcb_rules", "get_schematic_data",
    'bridge_get_capabilities', 'bridge_capture_snapshot', 'bridge_read_dataset',
    'bridge_measure_geometry', 'bridge_get_manufacturing_data', 'bridge_create_working_copy',
    'bridge_prepare_change_set', 'bridge_apply_change_set', 'bridge_run_analysis_job',
    'bridge_get_messages',
})
COMMANDS = frozenset({
    "get_read_context", "get_all_component_data", "get_component_pins",
    "get_all_nets", "get_pcb_layers", "get_pcb_rules", "get_schematic_data",
    "bridge_snapshot", "bridge_measure", "bridge_apply", "bridge_restore", "bridge_analysis",
    "bridge_messages",
})


def canonical(path):
    if not isinstance(path, str) or not ntpath.isabs(path):
        raise ValueError("Expected an absolute Windows path")
    return ntpath.normcase(ntpath.normpath(path))


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON constant")


def strict_json(text):
    return json.loads(text, object_pairs_hook=no_duplicate_keys,
                      parse_constant=reject_constant)


def validate_command(command, params):
    if command not in COMMANDS:
        raise PermissionError("COMMAND_NOT_ALLOWED")
    if not isinstance(params, dict):
        raise ValueError("Parameters must be an object")
    if command.startswith('bridge_'):
        validate_extended_command(command, params)
        return
    expected = {"designators"} if command == "get_component_pins" else set()
    if set(params) != expected:
        raise PermissionError("PARAMETERS_NOT_ALLOWED")
    if expected:
        names = params["designators"]
        if not isinstance(names, list) or not 1 <= len(names) <= 128:
            raise ValueError("Expected 1 to 128 pilot designators")
        if any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", x)
               for x in names):
            raise ValueError("Invalid pilot designator")


def validate_extended_command(command, params):
    expected = {
        'bridge_snapshot': {'dataset', 'offset', 'limit', 'kind', 'component'},
        'bridge_measure': {'a', 'b', 'metric', 'layer'},
        'bridge_apply': {'change_id', 'workspace_id'},
        'bridge_restore': {'change_id', 'workspace_id'},
        'bridge_analysis': {'job', 'workspace_id'},
        'bridge_messages': {'offset', 'limit'},
    }[command]
    if set(params) != expected:
        raise PermissionError('PARAMETERS_NOT_ALLOWED')
    if command == 'bridge_messages':
        if type(params['offset']) is not int or not 0 <= params['offset'] <= 1000000:
            raise ValueError('INVALID_MESSAGE_OFFSET')
        if type(params['limit']) is not int or not 1 <= params['limit'] <= 100:
            raise ValueError('INVALID_MESSAGE_LIMIT')
    elif command == 'bridge_snapshot':
        if params['dataset'] not in ('pcb', 'schematic'):
            raise ValueError('INVALID_NATIVE_DATASET')
        if type(params['offset']) is not int or not 0 <= params['offset'] <= 1000000:
            raise ValueError('INVALID_NATIVE_PAGE_OFFSET')
        if type(params['limit']) is not int or not 1 <= params['limit'] <= 100:
            raise ValueError('INVALID_NATIVE_PAGE_LIMIT')
        if params['kind'] not in ('all','component','rule','pad','via','track','arc','text','fill','polygon','region'):
            raise ValueError('INVALID_NATIVE_KIND_FILTER')
        if not isinstance(params['component'],str) or (params['component'] and
                not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}',params['component'])):
            raise ValueError('INVALID_COMPONENT_FILTER')
        if params['dataset']=='schematic' and (params['kind']!='all' or params['component']):
            raise ValueError('SCHEMATIC_FILTER_NOT_IMPLEMENTED')
        if params['component'] and params['kind'] not in ('all','component','pad','text'):
            raise ValueError('COMPONENT_FILTER_NOT_APPLICABLE')
    elif command == 'bridge_measure':
        if params['metric'] not in ('pad_center_distance', 'primitive_edge_clearance'):
            raise ValueError('UNSUPPORTED_MEASUREMENT')
        if any(not isinstance(params[k], str) or not re.fullmatch(r'[0-9]{1,12}', params[k]) for k in ('a', 'b')):
            raise ValueError('Expected snapshot-local object address')
        if not isinstance(params['layer'], str) or not re.fullmatch(r'[A-Za-z0-9 _-]{1,64}', params['layer']):
            raise ValueError('Invalid layer')
    elif command in ('bridge_apply', 'bridge_restore'):
        if any(not isinstance(params[k], str) or not re.fullmatch(r'[a-f0-9]{32}', params[k]) for k in expected):
            raise ValueError('Invalid change/workspace identifier')
    elif command == 'bridge_analysis':
        if params['job'] not in ('compile', 'drc', 'repour', 'export'):
            raise PermissionError('ANALYSIS_JOB_NOT_ALLOWED')
        if not re.fullmatch(r'[a-f0-9]{32}', params['workspace_id']):
            raise ValueError('Invalid workspace identifier')


def build_launch_args(executable, script):
    canonical(executable)
    canonical(script)
    if any(c.isspace() or c in '"|<>' for c in script):
        raise ValueError("PILOT_SCRIPT_PATH_REQUIRES_UNSUPPORTED_QUOTING")
    return [executable, '-RScriptingSystem:RunScript(ProjectName=' + script
            + '|ProcName=Altium_API>Run)']


class Policy:
    def __init__(self, path):
        self.path = Path(path)
        raw = self.path.read_bytes()
        self.identity = hashlib.sha256(raw).hexdigest()
        self.data = strict_json(raw.decode("ascii"))
        expected = {"project_path", "board_path", "document_paths", "pilot_root",
                    "exchange_dir", "altium_exe_path", "script_path", "manifest_version",
                    "command_modes", "workspaces", "results_root", "original_write_enabled"}
        if set(self.data) != expected:
            raise ValueError("Policy fields mismatch")
        if self.data['manifest_version'] != 2 or self.data['original_write_enabled'] is not False:
            raise PermissionError('Unsupported manifest or original writes enabled')
        if set(self.data['command_modes']) != COMMANDS:
            raise ValueError('Native command inventory mismatch')
        if any(mode not in ('read_only', 'analysis_job', 'controlled_edit') for mode in self.data['command_modes'].values()):
            raise ValueError('Invalid operation mode')
        if not isinstance(self.data['workspaces'], list) or len(self.data['workspaces']) > 1:
            raise PermissionError('Only one explicitly registered working copy is permitted')
        self.project = canonical(self.data["project_path"])
        self.board = canonical(self.data["board_path"])
        self.documents = frozenset(canonical(p) for p in self.data["document_paths"])
        if len(self.documents) != len(self.data["document_paths"]) or self.board not in self.documents:
            raise ValueError("Invalid document allowlist")
        root = canonical(self.data["pilot_root"])
        for path in [self.project, *self.documents]:
            if ntpath.commonpath([root, path]) != root:
                raise ValueError("Policy document is outside pilot")

    def verify_paths(self):
        for key in ("project_path", "board_path", "altium_exe_path", "script_path"):
            if not Path(self.data[key]).is_file():
                raise FileNotFoundError("Missing configured " + key)
        if not Path(self.data["exchange_dir"]).is_dir():
            raise FileNotFoundError("Missing private exchange directory")
        for name in [self.data["pilot_root"], self.data["exchange_dir"], *self.data["document_paths"]]:
            path = Path(name)
            if not path.exists():
                raise FileNotFoundError("Missing policy path")
            for part in [path, *path.parents]:
                if part.is_symlink() or part.is_junction():
                    raise PermissionError("Policy path crosses a reparse point")

    def registered_workspace(self):
        if not self.data['workspaces']: return None
        item = self.data['workspaces'][0]
        if set(item) != {'workspace_id', 'root', 'project_path', 'board_path'}:
            raise ValueError('Workspace manifest fields mismatch')
        wid = item['workspace_id']
        if not isinstance(wid,str) or not re.fullmatch('[a-f0-9]{32}',wid): raise ValueError('Invalid copy identifier')
        expected_root = Path(self.data['results_root']) / 'workspaces' / wid
        if canonical(item['root']) != canonical(str(expected_root)):
            raise PermissionError('Working copy is outside the exact approved location')
        if canonical(item['project_path']) != canonical(str(expected_root / Path(self.data['project_path']).name)):
            raise PermissionError('Working-copy project mismatch')
        if canonical(item['board_path']) != canonical(str(expected_root / Path(self.data['board_path']).name)):
            raise PermissionError('Working-copy board mismatch')
        for parent in [expected_root,*expected_root.parents]:
            if parent.is_symlink() or parent.is_junction(): raise PermissionError('Workspace path crosses reparse point')
        copied = frozenset(canonical(str(expected_root / Path(p).relative_to(Path(self.data['pilot_root'])))) for p in self.data['document_paths'])
        return {**item, 'documents': copied}

    def validate_response(self, raw, request_id, command):
        response = strict_json(raw)
        if not isinstance(response, dict) or response.get("request_id") != request_id:
            raise ValueError("RESPONSE_CORRELATION_MISMATCH")
        if response.get("policy_id") != self.identity:
            raise ValueError("RESPONSE_POLICY_MISMATCH")
        if type(response.get("success")) is not bool:
            raise ValueError("Response success must be Boolean")
        if not response["success"]:
            if not isinstance(response.get("error"), str) or not response["error"]:
                raise ValueError("Missing native error")
            return response
        if "result" not in response:
            raise ValueError("Missing native result")
        context = response.get("context")
        if not isinstance(context, dict) or context.get("scope_verified") is not True:
            raise PermissionError("UNVERIFIED_RESPONSE_SCOPE")
        actual_project = canonical(context.get('project_path'))
        expected_documents = self.documents
        expected_board = self.board
        actual_root = self.data['pilot_root']
        if actual_project != self.project:
            workspace = self.registered_workspace()
            if workspace is None or actual_project != canonical(workspace['project_path']):
                raise PermissionError('PROJECT_SCOPE_MISMATCH')
            expected_documents = workspace['documents']; expected_board = canonical(workspace['board_path']); actual_root = workspace['root']
        documents = context.get("documents")
        if not isinstance(documents, list) or not documents:
            raise ValueError("Missing actual document inventory")
        seen = [canonical(item["path"]) for item in documents]
        if len(seen) != len(set(seen)) or set(seen) != expected_documents:
            raise PermissionError('DOCUMENT_SCOPE_MISMATCH missing=' + repr(sorted(expected_documents - set(seen))) +
                                  ' unexpected=' + repr(sorted(set(seen) - expected_documents)) +
                                  ' duplicate=' + repr(sorted({p for p in seen if seen.count(p) > 1})))
        for item in documents:
            suffix = ntpath.splitext(canonical(item["path"]))[1]
            expected_kind = {".schdoc": "SCH", ".pcbdoc": "PCB"}.get(suffix)
            # The exact BomDoc path is allowlisted. Preserve its observed native
            # kind; no BOM-specific native operation is permitted by this profile.
            if suffix == '.bomdoc' and isinstance(item.get('kind'), str) and item['kind']:
                continue
            if expected_kind is None or item.get("kind") != expected_kind:
                raise PermissionError("DOCUMENT_KIND_MISMATCH")
        virtual = context.get("virtual_documents")
        if not isinstance(virtual, list) or len(virtual) > 1:
            raise ValueError("Missing or duplicate virtual-document inventory")
        virtual_path = ntpath.join(actual_root, "ActiveBOM.VirtualBOM")
        for item in virtual:
            if (item.get("kind") != "VirtualBOM" or
                    canonical(item.get("path")) != canonical(virtual_path) or
                    Path(virtual_path).exists()):
                raise PermissionError("VIRTUAL_DOCUMENT_SCOPE_MISMATCH")
        board_path = context.get("board_path")
        if command not in ('get_schematic_data','get_read_context','bridge_messages') or board_path != 'NOT_VERIFIED':
            if canonical(board_path) != expected_board:
                raise PermissionError("BOARD_SCOPE_MISMATCH")
        if context.get("read_complete") is not True:
            raise ValueError("Native read is incomplete")
        return response
