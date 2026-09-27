"""Backup the selected bridge and generate native scope from one manifest."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'server'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def generate_policy(data, identity):
    documents = data['document_paths']
    literals = lambda s: "'" + s.lower().replace("'", "''") + "'"
    root = data['pilot_root'].rstrip('\\')
    relative_documents = [p[len(root)+1:] for p in documents]
    predicates = ['(P = R + ' + literals('\\' + p) + ')' for p in relative_documents]
    workspaces = data['workspaces']
    if len(workspaces) > 1:
        raise ValueError('Only one explicitly registered experimental copy is permitted')
    projects = [data['project_path'], *(item['project_path'] for item in workspaces)]
    commands = data['command_modes']
    content = [
        '// Generated from pilot_policy.json. Do not edit independently.',
        'function BridgePolicyIdentity(Dummy: Integer): String;',
        'begin Result := ' + literals(identity) + '; end;',
        'function BridgeTargetProjectPath(Dummy: Integer): String;',
        'begin Result := ' + literals(projects[-1]) + '; end;',
        'function BridgeExpectedDocuments(Dummy: Integer): Integer;',
        'begin Result := ' + str(len(documents)) + '; end;',
        'function BridgeExpectedSchematics(Dummy: Integer): Integer;',
        'begin Result := ' + str(sum(p.lower().endswith('.schdoc') for p in documents)) + '; end;',
        'function BridgeApprovedProject(FilePath: String): Boolean;',
        'var P: String;',
        'begin',
        '  P := LowerCase(ExpandFileName(FilePath));',
        '  Result := ' + ' or '.join('(P = ' + literals(p) + ')' for p in projects) + ';',
        'end;',
        'function BridgeCurrentRoot(Dummy: Integer): String;',
        'var Project: IProject; R: String;',
        'begin',
        "  Result := ''; Project := PilotReadProject(0); if Project = nil then Exit;",
        '  if not BridgeApprovedProject(Project.DM_ProjectFullPath) then Exit;',
        '  R := LowerCase(ExtractFilePath(ExpandFileName(Project.DM_ProjectFullPath)));',
        "  if (Length(R) > 0) and (R[Length(R)] = '\\') then Delete(R, Length(R), 1);",
        '  Result := R;',
        'end;',
        'function BridgeExpectedBoard(Dummy: Integer): String;',
        'begin Result := BridgeCurrentRoot(0) + ' + literals('\\' + Path(data['board_path']).name) + '; end;',
        'function BridgeAllowedDocument(FilePath: String): Boolean;',
        'var P, R: String;',
        'begin',
        '  P := LowerCase(ExpandFileName(FilePath));',
        "  R := BridgeCurrentRoot(0); if R = '' then begin Result := False; Exit; end;",
        '  Result := ' + ' or\n    '.join(predicates) + ';',
        'end;',
        'function BridgeAllowedCommand(CommandName: String): Boolean;',
        'begin Result := ' + ' or\n    '.join("(CommandName = " + literals(c) + ')' for c in commands) + '; end;',
    ]
    return '\n'.join(content) + '\n'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', action='store_true')
    parser.add_argument('--generate', action='store_true')
    args = parser.parse_args()
    if args.backup:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        destination = ROOT / '.local/backups' / ('bridge-v2-' + stamp)
        destination.mkdir(parents=True)
        shutil.copytree(SERVER, destination / 'server')
        if (ROOT / '.codex/config.toml').is_file():
            shutil.copy2(ROOT / '.codex/config.toml', destination / 'project-config.toml')
        policy = json.loads((SERVER / 'pilot_policy.json').read_text())
        source_files = [Path(policy['project_path']), *(Path(p) for p in policy['document_paths'])]
        manifest = {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'workspace': str(ROOT), 'git_worktree': False,
            'bridge_files': {str(p.relative_to(destination)): digest(p) for p in destination.rglob('*') if p.is_file()},
            'design_files': {str(p): digest(p) for p in source_files},
        }
        (destination / 'baseline.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='ascii')
        print(json.dumps({'backup': str(destination), 'design_file_count': len(manifest['design_files'])}))
    if args.generate:
        policy_path = SERVER / 'pilot_policy.json'
        raw = policy_path.read_bytes()
        data = json.loads(raw.decode('ascii'))
        identity = hashlib.sha256(raw).hexdigest()
        target = SERVER / 'AltiumScript/bridge_policy.pas'
        generated = generate_policy(data, identity)
        target.write_text(generated, encoding='ascii')
        api = SERVER / 'AltiumScript/Altium_API.pas'
        text = api.read_text(encoding='utf-8-sig')
        exchange = data['exchange_dir'].rstrip('\\') + '\\'
        text = re.sub(r"ROOT_DIR := '[^']*';", lambda match: "ROOT_DIR := '" + exchange.replace("'", "''") + "';", text, count=1)
        start, end = '// BEGIN GENERATED BRIDGE POLICY', '// END GENERATED BRIDGE POLICY'
        if start in text:
            text = text[:text.index(start)] + start + '\n' + generated + end + text[text.index(end) + len(end):]
        else:
            position = text.index('function PilotAllowedCommand')
            text = text[:position] + start + '\n' + generated + end + '\n\n' + text[position:]
        text = re.sub(r"(Params.Values\['policy_id'\] <> )'[a-f0-9]{64}'", r'\1BridgePolicyIdentity(0)', text)
        text = re.sub(r"(AddJSONProperty\([^\n]*'policy_id', )'[a-f0-9]{64}'", r'\1BridgePolicyIdentity(0)', text)
        begin = text.index('function PilotAllowedCommand')
        finish = text.index('function PilotVirtualDocument', begin)
        text = text[:begin] + '''function PilotAllowedCommand(CommandName: String): Boolean;
begin Result := BridgeAllowedCommand(CommandName); end;

function PilotAllowedDocument(FilePath: String): Boolean;
begin Result := BridgeAllowedDocument(FilePath); end;

''' + text[finish:]
        text = text.replace('Seen.Count <> 15', 'Seen.Count <> BridgeExpectedDocuments(0)')
        text = text.replace('SchCount <> 13', 'SchCount <> BridgeExpectedSchematics(0)')
        original_project = data['project_path'].lower()
        original_board = data['board_path'].lower()
        root = data['pilot_root'].rstrip('\\')
        text = text.replace("LowerCase(ExpandFileName(Project.DM_ProjectFullPath)) <> '" + original_project + "'", 'not BridgeApprovedProject(Project.DM_ProjectFullPath)')
        text = text.replace("(P <> '" + original_project + "') and", '(not BridgeApprovedProject(P)) and')
        text = text.replace("LowerCase(ExpandFileName(Board.FileName)) <> '" + original_board + "'", 'LowerCase(ExpandFileName(Board.FileName)) <> BridgeExpectedBoard(0)')
        text = text.replace("LowerCase(ExpandFileName(FilePath)) = '" + root.lower() + "\\activebom.virtualbom'", "LowerCase(ExpandFileName(FilePath)) = BridgeCurrentRoot(0) + '\\activebom.virtualbom'")
        text = text.replace("begin Result := 'DOCUMENT_SCOPE_MISMATCH'; Exit; end;", "begin Result := 'DOCUMENT_SCOPE_MISMATCH unexpected_or_duplicate=' + Doc.DM_FullPath; Exit; end;")
        text = text.replace("AddJSONProperty(Props, 'dirty_state', 'NOT_VERIFIED');", "AddJSONProperty(Props, 'dirty_state', BridgeProjectDirtyState(0));")
        text = text.replace('Result := BridgeReadSnapshot(0)', 'Result := BridgeReadSnapshot(Params)')
        dispatcher = text.split('function ExecuteCommand', 1)[1]
        if 'Result := BridgeReadMessages(Params)' not in dispatcher:
            anchor = "    if CommandName = 'get_read_context' then begin Result := PilotContext; Exit; end;"
            text = text.replace(anchor,anchor + "\n    if CommandName = 'bridge_messages' then begin Result := BridgeReadMessages(Params); Exit; end;")
        if 'Result := BridgeReadMessages(Params)' not in dispatcher:
            anchor = "    if CommandName = 'get_read_context' then begin Result := PilotContext; Exit; end;"
            text = text.replace(anchor,anchor + "\n    if CommandName = 'bridge_messages' then begin Result := BridgeReadMessages(Params); Exit; end;")
        if 'Result := BridgeReadSnapshot(Params)' not in dispatcher:
            anchor = "    if CommandName = 'get_read_context' then begin Result := PilotContext; Exit; end;"
            text = text.replace(anchor, anchor + '''
    if CommandName = 'bridge_snapshot' then begin Result := BridgeReadSnapshot(Params); Exit; end;
    if CommandName = 'bridge_measure' then begin Result := BridgeMeasure(Params); Exit; end;
    if (CommandName = 'bridge_apply') or (CommandName = 'bridge_restore') then
        begin Result := BridgeControlledChange(CommandName, Params); Exit; end;
    if CommandName = 'bridge_analysis' then
        begin Result := 'ERROR: ANALYSIS_JOB_NATIVE_ACCEPTANCE_REQUIRED'; Exit; end;
''')
        api.write_text(text, encoding='utf-8')
        project = SERVER / 'AltiumScript/Altium_API.PrjScr'
        project_text = project.read_text(encoding='utf-8-sig')
        if 'DocumentPath=bridge_v2.pas' not in project_text:
            project_text = project_text.replace('[OutputGroup1]', '[Document7]\nDocumentPath=bridge_v2.pas\n\n[OutputGroup1]', 1)
            project.write_text(project_text, encoding='utf-8')
        print(json.dumps({'generated': str(target), 'policy_id': identity}))

if __name__ == '__main__':
    main()
