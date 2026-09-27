"""Host contracts and failure injection. Never starts MCP or Designer."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import ast
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT/'server'
sys.path.insert(0,str(SERVER))
from bridge_contract import ContractError, ChangeCoordinator, canonical_hash, validate_operations, verify_change, state_fingerprint, session_object_id
from bridge_geometry import pad_center, route_length
from pilot_policy import Policy, validate_command, strict_json, COMMANDS
from bridge_service import EvidenceService

def fixture():
    return {'schema_version':'2.0','snapshot_id':'a'*32,'dirty_state':'clean','data':{
        'pcb_coherence':'verified','dirty_state':'clean','origin_x_coord':0,'origin_y_coord':0,'coord_per_mil':10000,
        'page_coherence':'verified','pcb_inventory_complete':True,'dataset_total_count':4,
        'query':{'dataset':'pcb','offset':0,'limit':100,'kind':'all','component':''},'schematic_objects':[],
        'objects':[
            {'address_session':'1','kind':'pad','x_coord':0,'y_coord':0,'net':'SIG','layer':'Top Layer','component':'U1'},
            {'address_session':'2','kind':'pad','x_coord':30000,'y_coord':40000,'net':'SIG','layer':'Top Layer','component':'U2'},
            {'address_session':'3','kind':'track','x1_coord':0,'y1_coord':0,'x2_coord':30000,'y2_coord':40000,'net':'SIG','layer':'Top Layer','component':''},
            {'address_session':'4','kind':'text','moveable':True,'x_coord':100000,'y_coord':100000,'rotation_deg':0,'size_coord':40000,'text':'U1','layer':'Top Overlay'},
        ]}}

def operation():
    return {'object_id':'4','before':{'x_coord':100000},'after':{'x_coord':110000},'reason':'Move designator clear of pad'}

class Backend:
    def __init__(self, fault=None): self.value=fixture(); self.fault=fault; self.stopped=False; self.applies=0
    def snapshot(self):
        result=copy.deepcopy(self.value); result['fingerprint']=state_fingerprint(result['data']); return result
    def checkpoint(self): return copy.deepcopy(self.value)
    def apply(self, operations):
        self.applies+=1
        self.value['data']['objects'][3].update(operations[0]['after'])
        if self.fault in ('partial','restore_fail'): raise RuntimeError('injected partial native error')
        if self.fault=='unexpected': self.value['data']['objects'][0]['net']='WRONG'
    def restore(self, checkpoint):
        if self.fault=='restore_fail': raise RuntimeError('injected restore error')
        self.value=copy.deepcopy(checkpoint)
    def stop_writes(self, reason): self.stopped=True

class Contracts(unittest.TestCase):
    def test_pad_units_and_route_are_independent(self):
        s=fixture(); self.assertAlmostEqual(pad_center(s,'1','2')['value'],0.127)
        self.assertAlmostEqual(route_length(s,'1','2')['value'],0.127)
    def test_route_branch_rejected(self):
        s=fixture(); s['data']['objects'].append({'address_session':'5','kind':'track','net':'SIG','component':'','layer':'Top Layer','x1_coord':0,'y1_coord':0,'x2_coord':0,'y2_coord':10000})
        self.assertEqual(route_length(s,'1','2')['status'],'unsupported')
    def test_route_and_edit_reject_partial_inventory(self):
        s=fixture(); s['data']['pcb_inventory_complete']=False
        self.assertEqual(route_length(s,'1','2')['status'],'unsupported')
        with self.assertRaisesRegex(ContractError,'FULL_PCB_INVENTORY_REQUIRED'):
            validate_operations(s,[operation()])
    def test_route_and_edit_reject_partial_inventory(self):
        s=fixture(); s['data']['pcb_inventory_complete']=False
        self.assertEqual(route_length(s,'1','2')['status'],'unsupported')
        with self.assertRaisesRegex(ContractError,'FULL_PCB_INVENTORY_REQUIRED'):
            validate_operations(s,[operation()])
    def test_via_not_flattened_to_zero_length(self):
        s=fixture(); s['data']['objects'].append({'address_session':'5','kind':'via','net':'SIG','component':''})
        self.assertEqual(route_length(s,'1','2')['status'],'unsupported')
    def test_whole_preflight_no_partial_apply(self):
        backend=Backend(); start=backend.snapshot(); ops=[operation(),{'object_id':'99','before':{'x_coord':0},'after':{'x_coord':1},'reason':'missing'}]
        with self.assertRaisesRegex(ContractError,'OBJECT_NOT_FOUND'):
            ChangeCoordinator(backend).apply({'change_id':'b'*32,'base_fingerprint':start['fingerprint'],'operations':ops})
        self.assertEqual(backend.applies,0)
    def test_locked_object_denied(self):
        s=fixture(); s['data']['objects'][3]['moveable']=False
        with self.assertRaisesRegex(ContractError,'LOCKED'): validate_operations(s,[operation()])
    def test_text_content_and_side_change_denied(self):
        for key in ('text','layer','net'):
            op=operation(); op['before']={key:'U1'}; op['after']={key:'X'}
            with self.assertRaisesRegex(ContractError,'FIELD_NOT_ALLOWED'): validate_operations(fixture(),[op])
    def test_dirty_unknown_denied(self):
        for dirty in ('dirty','unknown'):
            s=fixture(); s['dirty_state']=dirty
            with self.assertRaisesRegex(ContractError,'UNVERIFIED'): validate_operations(s,[operation()])
    def test_nan_denied(self):
        op=operation(); op['after']['x_coord']=float('nan')
        with self.assertRaisesRegex(ContractError,'NUMBER'): validate_operations(fixture(),[op])
    def test_noop_does_not_claim_a_change(self):
        op=operation(); op['after']=copy.deepcopy(op['before'])
        with self.assertRaisesRegex(ContractError,'NO_CHANGE'): validate_operations(fixture(),[op])
    def test_replay_does_not_apply_twice(self):
        backend=Backend(); package={'change_id':'b'*32,'base_fingerprint':backend.snapshot()['fingerprint'],'operations':[operation()]}
        ChangeCoordinator(backend).apply(package)
        with self.assertRaisesRegex(ContractError,'STALE'): ChangeCoordinator(backend).apply(package)
        self.assertEqual(backend.applies,1)
    def test_stale_package(self):
        backend=Backend()
        with self.assertRaisesRegex(ContractError,'STALE'):
            ChangeCoordinator(backend).apply({'base_fingerprint':'0'*64,'operations':[operation()]})
        self.assertEqual(backend.applies,0)
    def test_success_readback(self):
        backend=Backend(); package={'change_id':'b'*32,'base_fingerprint':backend.snapshot()['fingerprint'],'operations':[operation()]}
        self.assertEqual(ChangeCoordinator(backend).apply(package)['status'],'ok')
    def test_partial_failure_restored(self):
        backend=Backend('partial'); base=backend.snapshot()['fingerprint']
        with self.assertRaisesRegex(ContractError,'FAILED_RESTORED'):
            ChangeCoordinator(backend).apply({'base_fingerprint':base,'operations':[operation()]})
        self.assertEqual(backend.snapshot()['fingerprint'],base)
    def test_unrelated_change_restored(self):
        backend=Backend('unexpected'); base=backend.snapshot()['fingerprint']
        with self.assertRaisesRegex(ContractError,'FAILED_RESTORED'):
            ChangeCoordinator(backend).apply({'base_fingerprint':base,'operations':[operation()]})
        self.assertEqual(backend.snapshot()['fingerprint'],base)
    def test_restore_failure_stops_writes(self):
        backend=Backend('restore_fail')
        with self.assertRaisesRegex(ContractError,'RECOVERY_REQUIRED'):
            ChangeCoordinator(backend).apply({'base_fingerprint':backend.snapshot()['fingerprint'],'operations':[operation()]})
        self.assertTrue(backend.stopped)
    def test_duplicate_object_ids_rejected(self):
        s=fixture(); s['data']['objects'].append(copy.deepcopy(s['data']['objects'][0]))
        with self.assertRaisesRegex(ContractError,'DUPLICATE'): state_fingerprint(s['data'])
    def test_object_address_normalization_is_exact_and_bounded(self):
        self.assertEqual(session_object_id(9335476864),'9335476864')
        self.assertEqual(session_object_id('9335476864'),'9335476864')
        for value in (True,False,0,-1,1.0,'001','1e3','',1000000000000):
            with self.assertRaisesRegex(ContractError,'INVALID_SESSION_OBJECT_ID'): session_object_id(value)

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy=Policy(SERVER/'pilot_policy.example.json')
        self.response={'request_id':'a'*32,'policy_id':self.policy.identity,'success':True,'result':[],
            'context':{'project_path':self.policy.data['project_path'],'board_path':self.policy.data['board_path'],
                       'documents':[{'path':p,'kind':'SCH' if p.lower().endswith('.schdoc') else 'PCB' if p.lower().endswith('.pcbdoc') else 'BOM'} for p in self.policy.data['document_paths']],
                       'virtual_documents':[],'scope_verified':True,'read_complete':True}}
    def test_bom_inventory_accepted(self):
        self.assertEqual(len(self.policy.documents),16)
        for command in COMMANDS: self.policy.validate_response(json.dumps(self.response),'a'*32,command)
    def test_missing_duplicate_foreign_documents_denied(self):
        variants=[]
        missing=copy.deepcopy(self.response); missing['context']['documents'].pop(); variants.append(missing)
        duplicate=copy.deepcopy(self.response); duplicate['context']['documents'].append(duplicate['context']['documents'][0]); variants.append(duplicate)
        foreign=copy.deepcopy(self.response); foreign['context']['documents'][0]['path']='G:\\Other\\Main.SchDoc'; variants.append(foreign)
        for response in variants:
            with self.assertRaisesRegex(PermissionError,'DOCUMENT_SCOPE_MISMATCH'):
                self.policy.validate_response(json.dumps(response),'a'*32,'get_read_context')
    def test_legacy_board_denied(self):
        self.response['context']['board_path']=self.policy.data['document_paths'][14]
        with self.assertRaisesRegex(PermissionError,'BOARD_SCOPE'):
            self.policy.validate_response(json.dumps(self.response),'a'*32,'get_read_context')
    def test_correlation_policy_and_nonfinite_denied(self):
        with self.assertRaisesRegex(ValueError,'CORRELATION'): self.policy.validate_response(json.dumps(self.response),'b'*32,'get_read_context')
        self.response['policy_id']='0'*64
        with self.assertRaisesRegex(ValueError,'POLICY'): self.policy.validate_response(json.dumps(self.response),'a'*32,'get_read_context')
        with self.assertRaises(ValueError): strict_json('{"x":NaN}')
        with self.assertRaises(ValueError): strict_json('{"x":1,"x":2}')
    def test_arbitrary_scripts_and_parameters_denied(self):
        with self.assertRaises(PermissionError): validate_command('run_altium_script',{'script':'anything'})
        with self.assertRaises(PermissionError): validate_command('bridge_snapshot',{'path':'G:\\Other'})
        with self.assertRaises(ValueError): validate_command('bridge_measure',{'a':'1','b':'2','metric':'guess','layer':'Top Layer'})
    def test_generator_is_deterministic(self):
        spec=importlib.util.spec_from_file_location('prepare_v2',ROOT/'scripts/Prepare-AltiumBridgeV2.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        generated=module.generate_policy(self.policy.data,self.policy.identity)
        self.assertEqual(generated,(SERVER/'AltiumScript/bridge_policy.pas').read_text(encoding='ascii'))
        self.assertIn(generated,(SERVER/'AltiumScript/Altium_API.pas').read_text(encoding='utf-8'))
    def test_native_v2_commands_have_dispatch_handlers(self):
        native=(SERVER/'AltiumScript/Altium_API.pas').read_text(encoding='utf-8')
        dispatcher=native.split('function ExecuteCommand',1)[1].split('// Function to extract',1)[0]
        self.assertIn("if CommandName = 'bridge_snapshot' then begin Result := BridgeReadSnapshot(Params); Exit; end;",dispatcher)
        self.assertIn("if CommandName = 'bridge_measure' then begin Result := BridgeMeasure(Params); Exit; end;",dispatcher)
        self.assertIn('BridgeControlledChange(CommandName, Params)',dispatcher)
        self.assertIn("CommandName = 'bridge_analysis'",dispatcher)
    def test_native_scope_uses_document_owner_not_workspace_focus(self):
        native=(SERVER/'AltiumScript/Altium_API.pas').read_text(encoding='utf-8')
        scope=native.split('function PilotValidateScope',1)[1].split('function PilotBuildContext',1)[0]
        self.assertNotIn('DM_FocusedProject',scope)
        self.assertIn('Project := PilotReadProject(0)',scope)
        self.assertIn('not BridgeApprovedProject(Project.DM_ProjectFullPath)',scope)
        self.assertIn('PilotAllowedDocument(Doc.DM_FullPath)',scope)
        self.assertIn('Seen.Count <> BridgeExpectedDocuments(0)',scope)
        self.assertIn('ExpandFileName(Board.FileName)) <> BridgeExpectedBoard(0)',scope)
    def test_schematic_port_reads_name_separately_from_labels(self):
        native=(SERVER/'AltiumScript/bridge_v2.pas').read_text(encoding='utf-8')
        collector=native.split('function BridgeSchematicObjects',1)[1].split('function BridgeReadSnapshot',1)[0]
        self.assertNotIn('eNetLabel, ePowerObject, ePort:',collector)
        self.assertNotRegex(collector,r'\bObj\.Text\b')
        self.assertNotIn('Obj.Designator.Text',collector)
        self.assertIn('Comp: ISch_Component',collector)
        self.assertIn('Parameter: ISch_Parameter',collector)
        port=collector.split('ePort:',1)[1].split('else',1)[0]
        self.assertIn('Port := Obj',port)
        self.assertIn("AddJSONProperty(P, 'text', Port.Name)",port)
        self.assertNotIn('Obj.Text',port)
    def test_only_one_explicit_copy_allowed(self):
        data=copy.deepcopy(self.policy.data)
        data['workspaces']=[{},{}]
        with tempfile.TemporaryDirectory(prefix='altium-v2-policy-') as folder:
            target=Path(folder)/'policy.json'; target.write_text(json.dumps(data),encoding='ascii')
            with self.assertRaisesRegex(PermissionError,'Only one'): Policy(target)
    def test_foreign_project_denied_without_registered_copy(self):
        self.response['context']['project_path']='F:\\SomeCopy\\Access_control_module.PrjPcb'
        with self.assertRaisesRegex(PermissionError,'PROJECT_SCOPE'):
            self.policy.validate_response(json.dumps(self.response),'a'*32,'get_read_context')
    def test_bad_native_measurement_ids_denied(self):
        for address in ('../1','1;run','0x123',None):
            with self.assertRaises(ValueError): validate_command('bridge_measure',{'a':address,'b':'2','metric':'pad_center_distance','layer':'Top Layer'})
    def test_native_query_bounds_and_scope(self):
        query={'dataset':'pcb','offset':0,'limit':100,'kind':'rule','component':''}
        validate_command('bridge_snapshot',query)
        for key,value in [('limit',101),('limit',0),('limit',True),('offset',-1),('offset',1.5),
                          ('dataset','foreign'),('kind','guess'),('component','../U14')]:
            with self.assertRaises(ValueError): validate_command('bridge_snapshot',{**query,key:value})
        with self.assertRaises(ValueError): validate_command('bridge_snapshot',{**query,'dataset':'schematic'})
    def test_native_query_bounds_and_scope(self):
        query={'dataset':'pcb','offset':0,'limit':100,'kind':'rule','component':''}
        validate_command('bridge_snapshot',query)
        for key,value in [('limit',101),('limit',0),('limit',True),('offset',-1),('offset',1.5),
                          ('dataset','foreign'),('kind','guess'),('component','../U14')]:
            with self.assertRaises(ValueError): validate_command('bridge_snapshot',{**query,key:value})
        with self.assertRaises(ValueError): validate_command('bridge_snapshot',{**query,'dataset':'schematic'})
    def test_registered_tool_names_match_allowlist(self):
        tree=ast.parse((SERVER/'main.py').read_text(encoding='utf-8'))
        registered={item.name for item in tree.body if isinstance(item,ast.AsyncFunctionDef) and any(
            isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and
            d.func.value.id=='mcp' and d.func.attr=='tool' for d in item.decorator_list)}
        from pilot_policy import TOOLS
        config=tomllib.loads((ROOT/'mcp-config.example.toml').read_text(encoding='utf-8'))
        self.assertEqual(registered,TOOLS)
        self.assertEqual(registered,set(config['mcp_servers']['altium_community_read']['enabled_tools']))
        self.assertEqual(len(registered),19)
    def test_context_and_messages_do_not_require_pcb_but_pcb_reads_do(self):
        response=copy.deepcopy(self.response); response['context']['board_path']='NOT_VERIFIED'
        for command in ('get_read_context','get_schematic_data','bridge_messages'):
            self.policy.validate_response(json.dumps(response),'a'*32,command)
        with self.assertRaises(ValueError):
            self.policy.validate_response(json.dumps(response),'a'*32,'bridge_snapshot')
    def test_native_read_target_does_not_depend_on_ui_focus(self):
        native=(SERVER/'AltiumScript/other_utils.pas').read_text(encoding='utf-8')
        resolver=native.split('function PilotReadProject',1)[1].split('function ScriptProjectPath',1)[0]
        self.assertIn('BridgeTargetProjectPath(0)',resolver)
        self.assertNotIn('DM_Focused',resolver)
        pcb=(SERVER/'AltiumScript/pcb_utils.pas').read_text(encoding='utf-8').split('function GetBoardSafe',1)[1].split('function GetPcbLibSafe',1)[0]
        self.assertIn('PCBServer.GetPCBBoardByPath(BridgeExpectedBoard(0))',pcb)
        self.assertNotIn('GetCurrentPCBBoard',pcb)
    def test_messages_are_bounded_and_have_no_mutation_calls(self):
        validate_command('bridge_messages',{'offset':0,'limit':50})
        for query in ({'offset':0,'limit':101},{'offset':True,'limit':1},{'offset':0,'limit':False}):
            with self.assertRaises(ValueError): validate_command('bridge_messages',query)
        native=(SERVER/'AltiumScript/bridge_v2.pas').read_text(encoding='utf-8')
        reader=native.split('function BridgeMessagesPage',1)[1].split('function BridgeControlledChange',1)[0]
        self.assertNotIn('ClearMessages',reader); self.assertNotIn('DM_Compile',reader)
        self.assertIn('Item: IMessageItem',reader)
    def test_registered_copy_scope_is_exact(self):
        data=copy.deepcopy(self.policy.data); wid='a'*32
        root=Path(data['results_root'])/'workspaces'/wid
        data['workspaces']=[{'workspace_id':wid,'root':str(root),
                            'project_path':str(root/Path(data['project_path']).name),
                            'board_path':str(root/Path(data['board_path']).name)}]
        with tempfile.TemporaryDirectory(prefix='altium-copy-scope-') as folder:
            path=Path(folder)/'policy.json'; path.write_text(json.dumps(data),encoding='ascii')
            self.policy=Policy(path)
            self.response['policy_id']=self.policy.identity
            workspace=self.policy.registered_workspace()
        self.assertIsNotNone(workspace)
        response=copy.deepcopy(self.response)
        response['context']['project_path']=workspace['project_path']
        response['context']['board_path']=workspace['board_path']
        base=Path(self.policy.data['pilot_root'])
        for item in response['context']['documents']:
            item['path']=str(Path(workspace['root'])/Path(item['path']).relative_to(base))
        self.policy.validate_response(json.dumps(response),'a'*32,'get_read_context')
        response['context']['board_path']=str(Path(workspace['root'])/'ACM_V1.PcbDoc')
        with self.assertRaisesRegex(PermissionError,'BOARD_SCOPE'):
            self.policy.validate_response(json.dumps(response),'a'*32,'get_read_context')
    def test_project_path_relocation_keeps_similar_foreign_path(self):
        spec=importlib.util.spec_from_file_location('prepare_copy',ROOT/'scripts/Prepare-AltiumWorkingCopy.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        original='G:\\Design\\Board'; copied='F:\\Task\\copy'
        data=b'[Document1]\r\nDocumentPath=Main.SchDoc\r\nX=DocumentPath=G:\\Design\\Board\\A.PcbDoc|Units=Metric\r\nY=G:\\Design\\Board_backup\\A.PcbDoc\r\n'
        result,count=module.relocate(data,original,copied)
        self.assertEqual(count,1)
        self.assertEqual(result,data.replace(b'G:\\Design\\Board\\A.PcbDoc',b'F:\\Task\\copy\\A.PcbDoc'))

class EvidenceIO(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='altium-v2-evidence-')
        self.folder=Path(self.directory.name).resolve()
        original=self.folder/'source'; original.mkdir()
        project=original/'A.PrjPcb'; project.write_text('[OutputGroup1]\nOutputType1=Gerber\n',encoding='ascii')
        pcb=original/'A.PcbDoc'; pcb.write_bytes(b'test fixture; not native CAD')
        class FixturePolicy:
            identity='f'*64
            data={'results_root':str(self.folder/'results'),'project_path':str(project),'board_path':str(pcb),
                  'pilot_root':str(original),'document_paths':[str(pcb)]}
            def registered_workspace(self): return None
        self.policy=FixturePolicy()
        self.policy.project=__import__('pilot_policy').canonical(str(project))
        ctx={'project_path':str(project),'board_path':str(pcb)}
        class FixtureBridge:
            data=fixture()['data']; calls=0
            async def execute_command(self,command,params):
                self.calls+=1
                result=copy.deepcopy(ctx)
                if command=='bridge_snapshot':
                    result=copy.deepcopy(self.data); result['query']=copy.deepcopy(params)
                    if params['dataset']=='pcb':
                        records=[obj for obj in result['objects'] if (params['kind']=='all' or obj['kind']==params['kind']) and
                                 (not params['component'] or (obj.get('designator') if obj['kind']=='component' else obj.get('component'))==params['component'])]
                        result['objects']=records[params['offset']:params['offset']+params['limit']]
                        result['schematic_objects']=[]
                    else:
                        records=result['schematic_objects']; result['objects']=[]
                        result['schematic_objects']=records[params['offset']:params['offset']+params['limit']]
                    result['dataset_total_count']=len(records)
                    result['pcb_inventory_complete']=(params['dataset']=='pcb' and params['kind']=='all' and
                        not params['component'] and params['offset']==0 and len(records)<=params['limit'])
                return {'success':True,'context':copy.deepcopy(ctx),'result':result}
        self.bridge=FixtureBridge()
        self.service=EvidenceService(self.bridge,self.policy)
        self.snapshot=await self.service.capture()
    async def asyncTearDown(self):
        # This directory was created by this fixture and resolved at creation.
        self.assertTrue(self.folder.name.startswith('altium-v2-evidence-'))
        self.directory.cleanup()
    async def test_partial_snapshot_not_promoted_to_full_project(self):
        self.assertEqual(self.snapshot['status'],'partial')
        self.assertEqual(self.snapshot['completeness']['whole_project'],'not_verified')
    async def test_native_page_has_explicit_partial_inventory(self):
        page=await self.service.capture(limit=2)
        self.assertEqual(page['returned_count'],2); self.assertEqual(page['dataset_total_count'],4)
        self.assertEqual(page['next_offset'],2)
        self.assertEqual(page['completeness']['pcb_inventory'],'page_only')
        self.assertEqual(page['data']['query']['limit'],2)
    async def test_point_query_filters_kind_and_exact_owner(self):
        page=await self.service.capture(kind='pad',component='U1')
        self.assertEqual(page['returned_count'],1)
        self.assertEqual(page['data']['objects'][0]['address_session'],'1')
        with self.assertRaisesRegex(ContractError,'DATASET_OUTSIDE_NATIVE_QUERY'):
            await self.service.page(page['snapshot_id'],'rules')
    async def test_unrequested_schematic_is_not_a_valid_empty_result(self):
        with self.assertRaisesRegex(ContractError,'DATASET_NOT_CAPTURED'):
            await self.service.page(self.snapshot['snapshot_id'],'schematic_objects')
    async def test_schematic_page_staleness_checks_its_records(self):
        self.bridge.data=copy.deepcopy(self.bridge.data)
        self.bridge.data['schematic_objects']=[{'sheet':'fixture','kind':'parameter','text':'original'}]
        page=await self.service.capture(dataset='schematic')
        self.assertEqual(page['returned_count'],1)
        self.assertEqual(page['completeness']['pcb_inventory'],'not_requested')
        self.bridge.data['schematic_objects'][0]['text']='changed'
        with self.assertRaisesRegex(ContractError,'STALE_LIVE'):
            await self.service.page(page['snapshot_id'],'schematic_objects')
    async def test_native_page_count_and_full_inventory_claims_are_checked(self):
        execute=self.bridge.execute_command
        async def bad_count(command,params):
            result=await execute(command,params)
            if command=='bridge_snapshot': result['result']['dataset_total_count']+=1
            return result
        self.bridge.execute_command=bad_count
        with self.assertRaisesRegex(ContractError,'NATIVE_PAGE_COUNT_MISMATCH'):
            await self.service.capture()
        async def false_complete(command,params):
            result=await execute(command,params)
            if command=='bridge_snapshot': result['result']['pcb_inventory_complete']=True
            return result
        self.bridge.execute_command=false_complete
        with self.assertRaisesRegex(ContractError,'FALSE_INVENTORY_COMPLETENESS'):
            await self.service.capture(kind='pad')
    async def test_native_page_has_explicit_partial_inventory(self):
        page=await self.service.capture(limit=2)
        self.assertEqual(page['returned_count'],2); self.assertEqual(page['dataset_total_count'],4)
        self.assertEqual(page['next_offset'],2)
        self.assertEqual(page['completeness']['pcb_inventory'],'page_only')
        self.assertEqual(page['data']['query']['limit'],2)
    async def test_point_query_filters_kind_and_exact_owner(self):
        page=await self.service.capture(kind='pad',component='U1')
        self.assertEqual(page['returned_count'],1)
        self.assertEqual(page['data']['objects'][0]['address_session'],'1')
        with self.assertRaisesRegex(ContractError,'DATASET_OUTSIDE_NATIVE_QUERY'):
            await self.service.page(page['snapshot_id'],'rules')
    async def test_unrequested_schematic_is_not_a_valid_empty_result(self):
        with self.assertRaisesRegex(ContractError,'DATASET_NOT_CAPTURED'):
            await self.service.page(self.snapshot['snapshot_id'],'schematic_objects')
    async def test_schematic_page_staleness_checks_its_records(self):
        self.bridge.data=copy.deepcopy(self.bridge.data)
        self.bridge.data['schematic_objects']=[{'sheet':'fixture','kind':'parameter','text':'original'}]
        page=await self.service.capture(dataset='schematic')
        self.assertEqual(page['returned_count'],1)
        self.assertEqual(page['completeness']['pcb_inventory'],'not_requested')
        self.bridge.data['schematic_objects'][0]['text']='changed'
        with self.assertRaisesRegex(ContractError,'STALE_LIVE'):
            await self.service.page(page['snapshot_id'],'schematic_objects')
    async def test_missing_native_dirty_state_is_invalid_not_clean(self):
        self.bridge.data=copy.deepcopy(self.bridge.data); del self.bridge.data['dirty_state']
        with self.assertRaisesRegex(ContractError,'NATIVE_DIRTY_STATE'): await self.service.capture()
    async def test_page_counts_and_end_marker(self):
        sid=self.snapshot['snapshot_id']
        first=await self.service.page(sid,'pcb_objects',0,3)
        last=await self.service.page(sid,'pcb_objects',first['next_offset'],3)
        self.assertEqual(first['returned_count'],3); self.assertFalse(first['complete'])
        self.assertEqual(last['returned_count'],1); self.assertTrue(last['complete']); self.assertIsNone(last['next_offset'])
    async def test_invalid_page_bounds(self):
        for offset,limit in [(-1,1),(0,0),(0,501),(True,1)]:
            with self.assertRaisesRegex(ContractError,'PAGE_BOUNDS'):
                await self.service.page(self.snapshot['snapshot_id'],'pcb_objects',offset,limit)
    async def test_live_geometry_change_rejects_page(self):
        self.bridge.data=copy.deepcopy(self.bridge.data); self.bridge.data['objects'][0]['net']='CHANGED'
        with self.assertRaisesRegex(ContractError,'STALE_LIVE'): await self.service.page(self.snapshot['snapshot_id'],'pcb_objects')
    async def test_disk_change_rejects_page(self):
        Path(self.policy.data['board_path']).write_bytes(b'changed saved fixture')
        with self.assertRaisesRegex(ContractError,'STALE_SAVED'): await self.service.page(self.snapshot['snapshot_id'],'pcb_objects')
    async def test_previous_session_rejected_before_native_read(self):
        other=EvidenceService(self.bridge,self.policy); calls=self.bridge.calls
        with self.assertRaisesRegex(ContractError,'PREVIOUS_SERVER_SESSION'): other.load_snapshot(self.snapshot['snapshot_id'])
        self.assertEqual(self.bridge.calls,calls)
    async def test_adapter_disk_change_blocks_capture_before_native_call(self):
        folder=self.folder/'adapter'; folder.mkdir()
        source=folder/'collector.py'; source.write_text('initial source',encoding='ascii')
        self.service.source_folder=folder
        self.service.source_hashes=self.service.current_source_hashes()
        source.write_text('changed source',encoding='ascii')
        calls=self.bridge.calls
        with self.assertRaisesRegex(ContractError,'ADAPTER_SOURCE_CHANGED_RELOAD_REQUIRED'):
            await self.service.capture()
        self.assertEqual(self.bridge.calls,calls)
        capability=self.service.capabilities()
        self.assertEqual(capability['status'],'blocked')
        self.assertEqual(capability['adapter_source_status'],'reload_required')
        with self.assertRaisesRegex(ContractError,'ADAPTER_SOURCE_CHANGED_RELOAD_REQUIRED'):
            self.service.load_snapshot(self.snapshot['snapshot_id'])
    async def test_adapter_change_during_context_blocks_snapshot_command(self):
        folder=self.folder/'adapter'; folder.mkdir()
        source=folder/'collector.py'; source.write_text('initial source',encoding='ascii')
        self.service.source_folder=folder
        self.service.source_hashes=self.service.current_source_hashes()
        execute=self.bridge.execute_command; calls=self.bridge.calls
        async def changing_execute(command,params):
            result=await execute(command,params)
            if command=='get_read_context': source.write_text('changed source',encoding='ascii')
            return result
        self.bridge.execute_command=changing_execute
        with self.assertRaisesRegex(ContractError,'ADAPTER_SOURCE_CHANGED_RELOAD_REQUIRED'):
            await self.service.capture()
        self.assertEqual(self.bridge.calls,calls+1)
    async def test_corrupt_snapshot_rejected(self):
        p=self.service.root/'snapshots'/(self.snapshot['snapshot_id']+'.json')
        data=json.loads(p.read_text()); data['data']['objects'][0]['x_coord']=999
        p.write_text(json.dumps(data),encoding='ascii')
        with self.assertRaisesRegex(ContractError,'CORRUPTED'): self.service.load_snapshot(self.snapshot['snapshot_id'])
    async def test_manufacturing_does_not_infer_export_freshness(self):
        info=self.service.manufacturing(self.snapshot['snapshot_id'])
        self.assertEqual(info['outputs']['OutputGroup1']['OutputType1'],'Gerber')
        self.assertEqual(info['export_execution_status'],'not_run'); self.assertEqual(info['status'],'partial')
    async def test_jobs_do_not_fall_through_to_unverified_native_actions(self):
        calls=self.bridge.calls
        result=await self.service.analysis('b'*32,'drc')
        self.assertEqual(result['status'],'blocked'); self.assertEqual(calls,self.bridge.calls)
    async def test_saved_copy_has_hash_proof_and_cannot_duplicate(self):
        result=await self.service.create_copy()
        registration=result['workspace']
        self.assertEqual(result['status'],'partial')
        self.assertTrue(Path(registration['root']).is_dir())
        self.assertEqual(Path(registration['board_path']).read_bytes(),Path(self.policy.data['board_path']).read_bytes())
        self.assertTrue((self.service.root/'working-copy.json').is_file())
        with self.assertRaisesRegex(ContractError,'EXPERIMENTAL_COPY_ALREADY_EXISTS'):
            await self.service.create_copy()
    async def test_integer_object_addresses_measure_the_same_snapshot(self):
        result=await self.service.measure(self.snapshot['snapshot_id'],1,2,'pad_center_distance')
        self.assertAlmostEqual(result['value'],0.127)
    async def test_measurement_rejects_foreign_address_before_native_read(self):
        calls=self.bridge.calls
        with self.assertRaisesRegex(ContractError,'OBJECT_NOT_FOUND_IN_SNAPSHOT'):
            await self.service.measure(self.snapshot['snapshot_id'],1,99,'primitive_edge_clearance','Top Layer')
        self.assertEqual(self.bridge.calls,calls)
    async def test_non_geometric_edge_request_is_rejected_before_native_read(self):
        calls=self.bridge.calls
        with self.assertRaisesRegex(ContractError,'NON_GEOMETRIC_OR_UNVERIFIED'):
            await self.service.measure(self.snapshot['snapshot_id'],1,4,'primitive_edge_clearance','Top Layer')
        self.assertEqual(self.bridge.calls,calls)
    async def test_messages_preserve_attribution_and_do_not_compile(self):
        requested=[]
        async def message_bridge(command,params):
            requested.append(command)
            return {'success':True,'request_id':'c'*32,
                'context':{'project_path':self.policy.data['project_path'],
                           'documents':[{'path':p} for p in self.policy.data['document_paths']]},
                'result':{'offset':0,'panel_total_count':2,'scanned_count':2,'records':[
                    {'panel_index':0,'document':self.policy.data['board_path'],'attribution':'exact_project_path','text':'fixture warning'},
                    {'panel_index':1,'document':'A.PcbDoc','attribution':'ambiguous_basename','text':'fixture warning'}]}}
        self.bridge.execute_command=message_bridge
        result=await self.service.messages(0,2)
        self.assertEqual(requested,['bridge_messages'])
        self.assertEqual(result['status'],'partial')
        self.assertFalse(result['validation_executed']); self.assertFalse(result['messages_cleared'])
        self.assertTrue(Path(result['artifact_path']).is_file())
    async def test_unscoped_message_bodies_are_rejected(self):
        async def message_bridge(command,params):
            return {'success':True,'request_id':'c'*32,
                'context':{'project_path':self.policy.data['project_path'],'documents':[]},
                'result':{'offset':0,'panel_total_count':1,'scanned_count':1,'records':[
                    {'panel_index':0,'document':'Other.SchDoc','attribution':'outside_selected_project','text':'not permitted'}]}}
        self.bridge.execute_command=message_bridge
        with self.assertRaisesRegex(ContractError,'UNSCOPED_MESSAGE_BODY'): await self.service.messages(0,1)

if __name__=='__main__': unittest.main(verbosity=2)
