"""V2 contracts and change preflight, independent of MCP and Designer."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import uuid

VERSION = '2.0'
COORD_PER_MIL = 10000
COORD_TO_MM = 0.0254 / COORD_PER_MIL
READ_DATASETS = frozenset({'pcb_objects', 'schematic_objects', 'rules', 'components'})
EDIT_FIELDS = {
    'component': frozenset({'x_coord', 'y_coord', 'rotation_deg'}),
    'text': frozenset({'x_coord', 'y_coord', 'rotation_deg', 'size_coord'}),
    'rule': frozenset({'gap_coord', 'min_width_coord', 'preferred_width_coord', 'max_width_coord',
                       'min_length_coord', 'max_length_coord', 'tolerance_coord',
                       'min_via_size_coord', 'max_via_size_coord', 'min_via_hole_coord', 'max_via_hole_coord'}),
}

class ContractError(ValueError):
    pass

def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError('NONFINITE_NUMBER')
    if isinstance(value, dict):
        for item in value.values(): finite_tree(item)
    elif isinstance(value, list):
        for item in value: finite_tree(item)

def canonical_hash(value):
    finite_tree(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()

def identifier(value):
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{32}', value) is None:
        raise ContractError('INVALID_IDENTIFIER')
    return value

def session_object_id(value):
    # MCP may decode a decimal string as an integer before argument validation.
    # Addresses here are exact positive integers of at most 12 decimal digits.
    if type(value) is int:
        value=str(value)
    if type(value) is not str or not re.fullmatch(r'[1-9][0-9]{0,11}',value):
        raise ContractError('INVALID_SESSION_OBJECT_ID')
    return value

def object_records(data):
    objects = data.get('objects')
    if not isinstance(objects, list): raise ContractError('MISSING_OBJECT_COLLECTION')
    records = {}
    for obj in objects:
        if not isinstance(obj, dict): raise ContractError('INVALID_OBJECT_RECORD')
        address = obj.get('address_session')
        if not isinstance(address, str) or not re.fullmatch('[0-9]{1,12}', address):
            raise ContractError('MISSING_SESSION_OBJECT_ADDRESS')
        if address in records: raise ContractError('DUPLICATE_OBJECT_ADDRESS')
        records[address] = obj
    return records

def state_fingerprint(data):
    records = object_records(data)
    return canonical_hash({'objects': [records[k] for k in sorted(records)],
                           'origin_x_coord': data['origin_x_coord'], 'origin_y_coord': data['origin_y_coord'],
                           'coord_per_mil': data['coord_per_mil'],
                           'query': data.get('query'), 'dataset_total_count': data.get('dataset_total_count'),
                           'schematic_objects': data.get('schematic_objects'),
                           'pcb_inventory_complete': data.get('pcb_inventory_complete')})

def snapshot_result(response, policy_id, disk_files):
    if not response.get('success'):
        return envelope('error', error=response.get('error'), policy_id=policy_id)
    data = response.get('result')
    if not isinstance(data, dict): raise ContractError('INVALID_SNAPSHOT_RESULT')
    finite_tree(data)
    if data.get('coord_per_mil') != COORD_PER_MIL: raise ContractError('NATIVE_COORDINATE_SCALE_MISMATCH')
    if data.get('dirty_state') not in ('clean','dirty','unknown'): raise ContractError('MISSING_OR_INVALID_NATIVE_DIRTY_STATE')
    object_records(data)
    if data.get('page_coherence') != 'verified': raise ContractError('MIXED_NATIVE_PAGE')
    query=data.get('query')
    if not isinstance(query,dict): raise ContractError('MISSING_NATIVE_QUERY')
    from pilot_policy import validate_command
    validate_command('bridge_snapshot',query)
    total=data.get('dataset_total_count')
    if type(total) is not int or total<0: raise ContractError('INVALID_NATIVE_TOTAL_COUNT')
    if query['offset']>total: raise ContractError('NATIVE_PAGE_OFFSET_OUT_OF_RANGE')
    records=data['objects'] if query['dataset']=='pcb' else data.get('schematic_objects')
    if not isinstance(records,list) or len(records)!=min(query['limit'],max(0,total-query['offset'])):
        raise ContractError('NATIVE_PAGE_COUNT_MISMATCH')
    if query['dataset']=='pcb':
        for obj in records:
            if query['kind']!='all' and obj.get('kind')!=query['kind']:
                raise ContractError('NATIVE_KIND_FILTER_MISMATCH')
            if query['component'] and (obj.get('designator') if obj.get('kind')=='component' else obj.get('component'))!=query['component']:
                raise ContractError('NATIVE_COMPONENT_FILTER_MISMATCH')
    if type(data.get('pcb_inventory_complete')) is not bool: raise ContractError('MISSING_INVENTORY_COMPLETENESS')
    expected_complete=(query['dataset']=='pcb' and query['kind']=='all' and not query['component'] and
                       query['offset']==0 and total<=query['limit'])
    if data['pcb_inventory_complete']!=expected_complete: raise ContractError('FALSE_INVENTORY_COMPLETENESS')
    context = response['context']
    sid = uuid.uuid4().hex
    partial = any(obj.get('field_read_status') == 'partial' or
                  any(k.endswith('_unavailable_reason') for k in obj) for obj in data['objects'])
    partial = partial or not data['pcb_inventory_complete'] or data.get('whole_project_coherence') != 'verified' or any(
        obj.get('status') in ('partial','unavailable') for obj in data.get('schematic_objects',[]))
    return envelope('partial' if partial else 'ok', snapshot_id=sid, policy_id=policy_id,
                    project_path=context['project_path'], board_path=context['board_path'],
                    source='live_native', dirty_state=data['dirty_state'],
                    units='native_coord', coord_per_mil=COORD_PER_MIL,
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    query=query, dataset_total_count=total, returned_count=len(records),
                    pagination_scope='next_offset_starts_an_independent_query_snapshot',
                    next_offset=query['offset']+len(records) if query['offset']+len(records)<total else None,
                    completeness={'pcb_inventory': 'native_reported' if data['pcb_inventory_complete'] else
                                  ('not_requested' if query['dataset']!='pcb' else 'page_only'),
                                  'pcb_fields': 'partial' if partial else 'native_reported',
                                  'whole_project': data.get('whole_project_coherence', 'not_verified')},
                    disk_files=disk_files, fingerprint=state_fingerprint(data), data=data)

def envelope(status, **fields):
    if status not in ('ok', 'partial', 'unsupported', 'error', 'blocked'):
        raise ContractError('INVALID_RESULT_STATUS')
    return {'schema_version': VERSION, 'status': status, **fields}

def validate_operations(snapshot, operations):
    if snapshot.get('dirty_state') != 'clean' or snapshot['data'].get('pcb_coherence') != 'verified':
        raise ContractError('UNVERIFIED_BASELINE')
    if snapshot['data'].get('pcb_inventory_complete') is not True:
        raise ContractError('FULL_PCB_INVENTORY_REQUIRED_FOR_EDIT')
    if not isinstance(operations, list) or not 1 <= len(operations) <= 64:
        raise ContractError('INVALID_OPERATION_COUNT')
    records = object_records(snapshot['data'])
    targets = set()
    for op in operations:
        if not isinstance(op, dict) or set(op) != {'object_id', 'before', 'after', 'reason'}:
            raise ContractError('INVALID_OPERATION_SCHEMA')
        if not isinstance(op['reason'], str) or not op['reason'].strip() or len(op['reason']) > 1000:
            raise ContractError('MISSING_ENGINEERING_REASON')
        target = op['object_id']
        if target in targets: raise ContractError('DUPLICATE_CHANGE_TARGET')
        targets.add(target)
        if target not in records: raise ContractError('OBJECT_NOT_FOUND')
        obj = records[target]
        if obj.get('moveable') is not True: raise ContractError('OBJECT_LOCKED_OR_UNKNOWN')
        if obj.get('field_read_status') == 'partial': raise ContractError('PARTIAL_TARGET_RECORD')
        kind = obj.get('kind')
        if kind not in EDIT_FIELDS: raise ContractError('OBJECT_KIND_NOT_EDITABLE')
        before, after = op['before'], op['after']
        if not isinstance(before, dict) or not isinstance(after, dict) or not before or set(before) != set(after):
            raise ContractError('INVALID_CHANGE_FIELDS')
        if before == after: raise ContractError('NO_CHANGE_REQUESTED')
        if not set(after) <= EDIT_FIELDS[kind]: raise ContractError('CHANGE_FIELD_NOT_ALLOWED')
        for key, value in before.items():
            if key not in obj or obj[key] != value: raise ContractError('BEFORE_STATE_MISMATCH')
        for key, value in after.items():
            if type(value) not in (int, float) or not math.isfinite(value): raise ContractError('INVALID_CHANGE_NUMBER')
            if key.endswith('_coord') and (type(value) is not int or abs(value) > 2147483647):
                raise ContractError('INVALID_NATIVE_COORDINATE')
            if key == 'rotation_deg' and not 0 <= value < 360: raise ContractError('INVALID_ROTATION')
            if key == 'size_coord' and value <= 0: raise ContractError('INVALID_TEXT_SIZE')
            if kind == 'rule' and value < 0: raise ContractError('INVALID_RULE_LIMIT')
        merged = {**obj, **after}
        for lo, hi in [('min_width_coord','max_width_coord'),('min_length_coord','max_length_coord'),
                       ('min_via_size_coord','max_via_size_coord'),('min_via_hole_coord','max_via_hole_coord')]:
            if lo in merged and hi in merged and merged[lo] > merged[hi]: raise ContractError('REVERSED_RULE_LIMITS')
    return operations

def verify_change(before_data, after_data, operations):
    before, after = object_records(before_data), object_records(after_data)
    if set(before) != set(after): raise ContractError('OBJECT_INVENTORY_CHANGED')
    changes = {op['object_id']: op for op in operations}
    for target, original in before.items():
        expected = {**original, **changes[target]['after']} if target in changes else original
        if after[target] != expected: raise ContractError('UNEXPECTED_OR_MISSING_CHANGE ' + target)
    return {'target_count': len(changes), 'unrelated_objects_preserved': True}

class ChangeCoordinator:
    """Transactional orchestration. A backend must provide verified restoration."""
    def __init__(self, backend):
        self.backend = backend

    def apply(self, package):
        current = self.backend.snapshot()
        if current['fingerprint'] != package['base_fingerprint']: raise ContractError('STALE_CHANGE_SET')
        validate_operations(current, package['operations'])
        checkpoint = self.backend.checkpoint()
        try:
            self.backend.apply(package['operations'])
            after = self.backend.snapshot()
            verified = verify_change(current['data'], after['data'], package['operations'])
            return envelope('ok', change_id=package['change_id'], verification=verified, after=after)
        except Exception as error:
            try:
                self.backend.restore(checkpoint)
                if self.backend.snapshot()['fingerprint'] != current['fingerprint']:
                    raise ContractError('RESTORED_STATE_MISMATCH')
            except Exception as recovery:
                self.backend.stop_writes(str(recovery))
                raise ContractError('RECOVERY_REQUIRED: ' + str(recovery)) from error
            raise ContractError('CHANGE_FAILED_RESTORED: ' + str(error)) from error
