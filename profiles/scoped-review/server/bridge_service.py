"""Bounded V2 evidence service. Native jobs/writes require acceptance receipts."""
import configparser
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import ntpath
import shutil
import uuid

from bridge_contract import (VERSION, ContractError, envelope, canonical_hash, identifier,
                             snapshot_result, state_fingerprint, validate_operations, READ_DATASETS,
                             session_object_id, object_records)
from bridge_geometry import pad_center, route_length
from pilot_policy import canonical, strict_json

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def checked_child(root, path):
    root, path = Path(root).resolve(), Path(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(root): raise PermissionError('ARTIFACT_PATH_OUTSIDE_ROOT')
    for part in [path, *path.parents]:
        if part.is_symlink() or part.is_junction(): raise PermissionError('REPARSE_POINT_NOT_ALLOWED')
        if part.resolve() == root: break
    return resolved

def publish_new(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='ascii') as stream:
        json.dump(payload, stream, ensure_ascii=True, indent=2, allow_nan=False)
        stream.write('\n')

class EvidenceService:
    def __init__(self, bridge, policy):
        self.bridge, self.policy = bridge, policy
        self.root = Path(policy.data['results_root'])
        self.session_id = uuid.uuid4().hex
        self.source_folder = Path(__file__).resolve().parent
        self.source_hashes = self.current_source_hashes()

    def current_source_hashes(self):
        folder = self.source_folder
        return {str(p.relative_to(folder)): file_hash(p) for p in
                              [*folder.glob('*.py'), *folder.glob('AltiumScript/*.pas')]}

    def assert_adapter_current(self):
        if self.current_source_hashes() != self.source_hashes:
            raise ContractError('ADAPTER_SOURCE_CHANGED_RELOAD_REQUIRED')

    def capabilities(self):
        current_hashes = self.current_source_hashes()
        adapter_current = current_hashes == self.source_hashes
        native = {
            'pcb_objects': 'implemented_pending_native_acceptance',
            'schematic_objects': 'implemented_pending_native_acceptance',
            'pad_center_distance': 'implemented_pending_native_acceptance',
            'primitive_edge_clearance': 'implemented_pending_native_acceptance',
            'rule_identity_scope_priority_enabled': 'implemented_pending_native_acceptance',
            'stackup': 'not_native_verified',
            'effective_rules': 'not_native_verified',
            'compiled_connectivity': 'not_native_verified',
            'current_pours': 'not_native_verified',
            'drc': 'not_native_verified',
            'controlled_edit': 'blocked_pending_native_write_and_restore_acceptance',
            'original_transfer': 'requires_review_and_explicit_package_authorization',
            'constraint_manager': 'unsupported',
            'bounded_query_pages': 'implemented_pending_native_acceptance',
            'point_component_filter': 'implemented_pending_native_acceptance',
            'full_project_snapshot_assembly': 'not_implemented',
            'existing_messages': 'implemented_pending_native_acceptance',
            'document_access_by_manifest_path': 'implemented_pending_native_acceptance',
        }
        receipt = self.root / 'native-acceptance.json'
        if adapter_current and receipt.is_file():
            accepted = strict_json(receipt.read_text(encoding='ascii'))
            if accepted.get('policy_id') == self.policy.identity and accepted.get('adapter_source_hashes') == self.source_hashes:
                for name, value in accepted.get('capabilities', {}).items():
                    if name in native and value == 'verified': native[name] = value
        return envelope('ok' if adapter_current else 'blocked', provider='AltiumCommunityBridge', policy_id=self.policy.identity,
                        target_project_path=(self.policy.registered_workspace() or {}).get('project_path',self.policy.data['project_path']),
                        session_id=self.session_id, adapter_source_hashes=self.source_hashes,
                        adapter_source_hashes_scope='server_session_start',
                        adapter_source_status='current' if adapter_current else 'reload_required',
                        current_adapter_source_hashes=current_hashes,
                        max_native_records_per_page=100,
                        installed_file_version='26.10.1.5', version_scope='installation_baseline_not_runtime_probe',
                        modes=['read_only','analysis_job','controlled_edit'], capabilities=native)

    def disk_manifest(self, project_path=None):
        selected = project_path or self.policy.data['project_path']
        if canonical(selected) == self.policy.project:
            paths = [self.policy.data['project_path'], *self.policy.data['document_paths']]
        else:
            workspace = self.policy.registered_workspace()
            if workspace is None or canonical(selected) != canonical(workspace['project_path']):
                raise ContractError('PROJECT_SCOPE_MISMATCH')
            base=Path(workspace['root']); original=Path(self.policy.data['pilot_root'])
            paths=[workspace['project_path'], *(str(base/Path(p).relative_to(original)) for p in self.policy.data['document_paths'])]
        return {path: file_hash(path) for path in paths}

    async def messages(self, offset=0, limit=50):
        from pilot_policy import validate_command
        query={'offset':offset,'limit':limit}; validate_command('bridge_messages',query)
        self.assert_adapter_current()
        response=await self.bridge.execute_command('bridge_messages',query)
        self.assert_adapter_current()
        if not response.get('success'): return envelope('error',error=response.get('error'))
        data=response['result']; rows=data.get('records'); total=data.get('panel_total_count')
        if type(total) is not int or total<0 or not isinstance(rows,list) or data.get('offset')!=offset:
            raise ContractError('INVALID_MESSAGES_RESULT')
        if offset>total or len(rows)!=min(limit,total-offset) or data.get('scanned_count')!=len(rows):
            raise ContractError('MESSAGE_PAGE_COUNT_MISMATCH')
        allowed_paths={canonical(item['path']) for item in response['context']['documents']}
        allowed_paths.add(canonical(response['context']['project_path']))
        for i,row in enumerate(rows,offset):
            if row.get('panel_index')!=i or row.get('attribution') not in (
                'exact_project_path','ambiguous_basename','outside_selected_project','unattributed'):
                raise ContractError('INVALID_MESSAGE_RECORD')
            if row['attribution'] in ('outside_selected_project','unattributed') and row.get('text') is not None:
                raise ContractError('UNSCOPED_MESSAGE_BODY')
            if row['attribution']=='exact_project_path' and canonical(row.get('document')) not in allowed_paths:
                raise ContractError('MESSAGE_DOCUMENT_SCOPE_MISMATCH')
            if row['attribution']=='ambiguous_basename' and (
                ntpath.basename(row.get('document',''))!=row.get('document') or
                row['document'].lower() not in {ntpath.basename(p).lower() for p in allowed_paths}):
                raise ContractError('MESSAGE_DOCUMENT_SCOPE_MISMATCH')
        result=envelope('partial',source='live_existing_messages',project_path=response['context']['project_path'],
                        request_id=response['request_id'],policy_id=self.policy.identity,session_id=self.session_id,
                        captured_at=datetime.now(timezone.utc).isoformat(),adapter_source_hashes=self.source_hashes,
                        context=response['context'],validation_run_provenance='not_automatically_correlated',
                        validation_executed=False,messages_cleared=False,
                        next_offset=offset+len(rows) if offset+len(rows)<total else None,**data)
        artifact=self.root/'messages'/(response['request_id']+'.json')
        publish_new(artifact,result); result['artifact_path']=str(artifact)
        return result

    async def capture(self, dataset='pcb', offset=0, limit=100, kind='all', component=''):
        self.assert_adapter_current()
        query={'dataset':dataset,'offset':offset,'limit':limit,'kind':kind,'component':component}
        from pilot_policy import validate_command
        validate_command('bridge_snapshot',query)
        context = await self.bridge.execute_command('get_read_context',{})
        self.assert_adapter_current()
        if not context.get('success'): return envelope('error',error=context.get('error'))
        selected=context['context']['project_path']
        before = self.disk_manifest(selected)
        response = await self.bridge.execute_command('bridge_snapshot', query)
        self.assert_adapter_current()
        if response.get('success') and canonical(response['context']['project_path']) != canonical(selected):
            raise ContractError('PROJECT_CHANGED_DURING_CAPTURE')
        if response.get('success') and response['result'].get('query')!=query:
            raise ContractError('NATIVE_QUERY_MISMATCH')
        after = self.disk_manifest(selected)
        if before != after: raise ContractError('SAVED_FILES_CHANGED_DURING_SNAPSHOT')
        snapshot = snapshot_result(response, self.policy.identity, before)
        if snapshot['status'] == 'error': return snapshot
        snapshot['session_id'] = self.session_id
        snapshot['adapter_source_hashes'] = self.source_hashes
        publish_new(self.root / 'snapshots' / (snapshot['snapshot_id'] + '.json'), snapshot)
        return snapshot

    def load_snapshot(self, snapshot_id):
        identifier(snapshot_id)
        self.assert_adapter_current()
        path = checked_child(self.root, self.root / 'snapshots' / (snapshot_id + '.json'))
        data = strict_json(path.read_text(encoding='ascii'))
        if data.get('snapshot_id') != snapshot_id or data.get('policy_id') != self.policy.identity:
            raise ContractError('STALE_OR_FOREIGN_SNAPSHOT')
        if data.get('session_id') != self.session_id: raise ContractError('SNAPSHOT_FROM_PREVIOUS_SERVER_SESSION')
        if data.get('adapter_source_hashes') != self.source_hashes: raise ContractError('SNAPSHOT_ADAPTER_VERSION_CHANGED')
        if data.get('fingerprint') != state_fingerprint(data['data']): raise ContractError('SNAPSHOT_FILE_CORRUPTED')
        return data

    async def assert_current(self, snapshot):
        self.assert_adapter_current()
        if self.disk_manifest(snapshot['project_path']) != snapshot['disk_files']: raise ContractError('STALE_SAVED_FILE_SNAPSHOT')
        response = await self.bridge.execute_command('bridge_snapshot', snapshot['data']['query'])
        self.assert_adapter_current()
        if not response.get('success'): raise ContractError(response.get('error', 'NATIVE_SNAPSHOT_FAILED'))
        current = response['result']
        if current.get('page_coherence') != 'verified' or state_fingerprint(current) != snapshot['fingerprint']:
            raise ContractError('STALE_LIVE_SNAPSHOT')
        if self.disk_manifest(snapshot['project_path']) != snapshot['disk_files']:
            raise ContractError('SAVED_FILES_CHANGED_DURING_VALIDATION')
        if current.get('dirty_state') != snapshot.get('dirty_state'): raise ContractError('DOCUMENT_DIRTY_STATE_CHANGED')
        if response['context']['project_path'] != snapshot['project_path'] or response['context']['board_path'] != snapshot['board_path']:
            raise ContractError('SNAPSHOT_CONTEXT_CHANGED')

    async def page(self, snapshot_id, dataset, offset=0, limit=100, kind=None):
        if dataset not in READ_DATASETS: raise ContractError('UNKNOWN_DATASET')
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ContractError('INVALID_PAGE_BOUNDS')
        snapshot = self.load_snapshot(snapshot_id)
        query=snapshot['data']['query']
        if (dataset=='schematic_objects') != (query['dataset']=='schematic'):
            raise ContractError('DATASET_NOT_CAPTURED')
        requested_kind={'rules':'rule','components':'component'}.get(dataset)
        if requested_kind and query['kind'] not in ('all',requested_kind):
            raise ContractError('DATASET_OUTSIDE_NATIVE_QUERY')
        if kind and query['kind'] not in ('all',kind):
            raise ContractError('KIND_FILTER_OUTSIDE_NATIVE_QUERY')
        await self.assert_current(snapshot)
        if dataset == 'schematic_objects': records=snapshot['data']['schematic_objects']
        else:
            records=snapshot['data']['objects']
            selected={'rules':'rule','components':'component'}.get(dataset)
            if selected: records=[obj for obj in records if obj.get('kind') == selected]
        if kind is not None:
            if not isinstance(kind,str) or len(kind)>64: raise ContractError('INVALID_KIND_FILTER')
            records=[obj for obj in records if obj.get('kind') == kind]
        if offset > len(records): raise ContractError('PAGE_OFFSET_OUT_OF_RANGE')
        end=min(offset+limit,len(records))
        partial=any(obj.get('status') in ('partial','unavailable') or obj.get('field_read_status') == 'partial' or
                    any(k.endswith('_unavailable_reason') for k in obj) for obj in records[offset:end])
        return envelope('partial' if partial else 'ok', snapshot_id=snapshot_id, dataset=dataset,
                        total_count=len(records), offset=offset, returned_count=end-offset,
                        next_offset=end if end<len(records) else None, complete=end==len(records), records=records[offset:end])

    async def measure(self, snapshot_id, a, b, metric, layer=None):
        snapshot=self.load_snapshot(snapshot_id)
        a,b=session_object_id(a),session_object_id(b)
        records=object_records(snapshot['data'])
        if a not in records or b not in records:
            raise ContractError('OBJECT_NOT_FOUND_IN_SNAPSHOT')
        if metric=='primitive_edge_clearance':
            allowed={'pad','via','track','arc','fill','region'}
            if records[a].get('kind') not in allowed or records[b].get('kind') not in allowed:
                raise ContractError('NON_GEOMETRIC_OR_UNVERIFIED_PRIMITIVE')
        await self.assert_current(snapshot)
        if metric == 'pad_center_distance': return pad_center(snapshot,a,b)
        if metric == 'routed_length': return route_length(snapshot,a,b)
        if metric != 'primitive_edge_clearance' or layer is None:
            raise ContractError('UNKNOWN_METRIC_OR_MISSING_LAYER')
        response=await self.bridge.execute_command('bridge_measure',{'a':a,'b':b,'metric':metric,'layer':layer})
        if not response.get('success'): return envelope('error',error=response['error'],snapshot_id=snapshot_id)
        await self.assert_current(snapshot)
        return envelope('ok',snapshot_id=snapshot_id,measurement=response['result'])

    def manufacturing(self, snapshot_id):
        snapshot=self.load_snapshot(snapshot_id)
        if self.disk_manifest(snapshot['project_path'])!=snapshot['disk_files']: raise ContractError('STALE_SAVED_FILE_SNAPSHOT')
        project=Path(snapshot['project_path'])
        parser=configparser.RawConfigParser(interpolation=None,strict=True); parser.optionxform=str
        parser.read_string(project.read_text(encoding='utf-8-sig'))
        outputs={name:dict(parser.items(name)) for name in parser.sections() if name.startswith(('OutputGroup','GeneratedDocument','Publish'))}
        variants={name:dict(parser.items(name)) for name in parser.sections() if name.startswith('Variant')}
        artifacts=[]; folder=project.parent/('Project Outputs for '+project.stem)
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    checked_child(project.parent,path)
                    artifacts.append({'path':str(path),'sha256':file_hash(path),'bytes':path.stat().st_size,
                                      'freshness':'not_verified','source_snapshot_id':None})
        return envelope('partial',snapshot_id=snapshot_id,source='saved_project_configuration',
                        source_sha256=snapshot['disk_files'][str(project)],outputs=outputs,variants=variants,
                        artifacts=artifacts,activebom_native_status='not_checked',
                        assembly_instruction_status='Separate Excel DNI instructions are not an Altium variant',
                        export_execution_status='not_run')

    async def create_copy(self):
        marker=self.root/'working-copy.json'
        if marker.exists() or self.policy.registered_workspace() is not None:
            raise ContractError('EXPERIMENTAL_COPY_ALREADY_EXISTS; reuse the single copy')
        source=await self.capture()
        if source.get('dirty_state')!='clean': raise ContractError('CLEAN_SOURCE_REQUIRED_FOR_DISK_COPY')
        if canonical(source['project_path']) != self.policy.project: raise ContractError('ORIGINAL_SOURCE_PROJECT_REQUIRED')
        wid=uuid.uuid4().hex; dest=checked_child(self.root,self.root/'workspaces'/wid)
        dest.mkdir(parents=True,exist_ok=False)
        base=Path(self.policy.data['pilot_root'])
        paths=[Path(self.policy.data['project_path']), *(Path(p) for p in self.policy.data['document_paths'])]
        for path in paths:
            relative=path.relative_to(base); target=dest/relative; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target)
            if file_hash(target)!=source['disk_files'][str(path)]: raise ContractError('WORKING_COPY_HASH_MISMATCH')
        await self.assert_current(source)
        registration={'schema_version':VERSION,'workspace_id':wid,'root':str(dest),
                      'project_path':str(dest/Path(self.policy.data['project_path']).name),
                      'board_path':str(dest/Path(self.policy.data['board_path']).name),
                      'source_snapshot_id':source['snapshot_id'],'source_hashes':source['disk_files'],
                      'native_activation':'not_verified','write_acceptance':'not_verified'}
        publish_new(dest/'registration.json',registration)
        publish_new(marker,registration)
        return envelope('partial',workspace=registration,reason='Copy created; native activation and dependency completeness require verification')

    def prepare(self,snapshot_id,workspace_id,operations):
        identifier(workspace_id); snapshot=self.load_snapshot(snapshot_id)
        registration_path=checked_child(self.root,self.root/'workspaces'/workspace_id/'registration.json')
        registration=strict_json(registration_path.read_text(encoding='ascii'))
        if canonical(snapshot['board_path'])!=canonical(registration['board_path']):
            raise ContractError('CHANGE_REQUIRES_WORKING_COPY_SNAPSHOT')
        validate_operations(snapshot,operations)
        cid=uuid.uuid4().hex
        package={'schema_version':VERSION,'change_id':cid,'workspace_id':workspace_id,
                 'base_snapshot_id':snapshot_id,'base_fingerprint':snapshot['fingerprint'],
                 'operations':operations,'state':'prepared','original_transfer_approved':False}
        package['package_hash']=canonical_hash(package)
        publish_new(self.root/'changes'/(cid+'.json'),package)
        return envelope('ok',change_set=package,execution='not_applied')

    async def apply(self,change_id):
        identifier(change_id)
        package=strict_json(checked_child(self.root,self.root/'changes'/(change_id+'.json')).read_text(encoding='ascii'))
        expected_hash=package.pop('package_hash')
        if canonical_hash(package)!=expected_hash: raise ContractError('CHANGE_PACKAGE_CORRUPTED')
        snapshot=self.load_snapshot(package['base_snapshot_id']); await self.assert_current(snapshot)
        if self.capabilities()['capabilities']['controlled_edit']!='verified':
            return envelope('blocked',change_id=change_id,reason='Native write and restore acceptance receipt absent; no design changed')
        # No fall-through to unverified upstream placement functions.
        return envelope('blocked',change_id=change_id,reason='Native transactional adapter must be activated for this exact copy')

    async def analysis(self,workspace_id,job):
        identifier(workspace_id)
        if job not in ('compile','drc','repour','export'): raise ContractError('UNKNOWN_ANALYSIS_JOB')
        return envelope('blocked',job=job,workspace_id=workspace_id,
                        reason='Version-bound native job completion and output verification not yet accepted; no job started')
