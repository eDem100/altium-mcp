"""Conservative snapshot geometry. No guessed copper or implicit route choice."""
import math
from bridge_contract import ContractError, COORD_TO_MM, envelope, object_records

def pad_center(snapshot, a, b):
    records = object_records(snapshot['data'])
    if a not in records or b not in records: raise ContractError('OBJECT_NOT_FOUND')
    pa, pb = records[a], records[b]
    if pa.get('kind') != 'pad' or pb.get('kind') != 'pad': raise ContractError('PAD_OBJECTS_REQUIRED')
    distance = math.hypot(pa['x_coord']-pb['x_coord'], pa['y_coord']-pb['y_coord']) * COORD_TO_MM
    return envelope('ok', metric='pad_center_distance', value=distance, unit='mm',
                    snapshot_id=snapshot['snapshot_id'], object_ids=[a,b], method='snapshot_pad_centers')

def route_length(snapshot, a, b):
    if snapshot['data'].get('pcb_inventory_complete') is not True:
        return envelope('unsupported', reason='A page cannot establish complete routed connectivity; full PCB inventory is required')
    records = object_records(snapshot['data'])
    if a not in records or b not in records: raise ContractError('OBJECT_NOT_FOUND')
    start, finish = records[a], records[b]
    if start.get('kind') != 'pad' or finish.get('kind') != 'pad': raise ContractError('PAD_OBJECTS_REQUIRED')
    net = start.get('net')
    if not isinstance(net, str) or not net or net != finish.get('net'): raise ContractError('SAME_ASSIGNED_NET_REQUIRED')
    relevant = [obj for obj in records.values() if obj.get('net') == net and not obj.get('component')]
    if any(obj.get('kind') in ('polygon','region','fill','via','other') for obj in relevant):
        return envelope('unsupported', reason='Plane, region, via span or undecoded geometry prevents a complete routed path')
    layers = {obj.get('layer') for obj in relevant if obj.get('kind') in ('track','arc')}
    if len(layers) != 1: return envelope('unsupported', reason='A unique routed layer was not established')
    layer = next(iter(layers))
    graph = {}
    edge_ids = []
    for obj in relevant:
        if obj.get('kind') == 'track':
            u, v = (obj['x1_coord'],obj['y1_coord']), (obj['x2_coord'],obj['y2_coord'])
            length = math.dist(u,v)
        elif obj.get('kind') == 'arc':
            def endpoint(deg):
                rad=math.radians(deg)
                return (round(obj['x_coord']+obj['radius_coord']*math.cos(rad)), round(obj['y_coord']+obj['radius_coord']*math.sin(rad)))
            u,v=endpoint(obj['start_angle_deg']),endpoint(obj['end_angle_deg'])
            sweep=(obj['end_angle_deg']-obj['start_angle_deg']) % 360
            if sweep == 0: return envelope('unsupported', reason='Full-circle arc requires explicit native path resolution')
            length=obj['radius_coord']*math.radians(sweep)
        else: continue
        if obj.get('field_read_status') == 'partial': return envelope('unsupported', reason='Incomplete route primitive')
        eid=obj['address_session']; edge_ids.append(eid)
        graph.setdefault(u,[]).append((v,length,eid)); graph.setdefault(v,[]).append((u,length,eid))
    u=(start['x_coord'],start['y_coord']); goal=(finish['x_coord'],finish['y_coord'])
    if u == goal: return envelope('unsupported', reason='Coincident terminals require native connectivity resolution')
    previous=None; visited=set(); path=[]; total=0
    while u != goal:
        if u in visited: return envelope('unsupported', reason='Cycle in selected net')
        visited.add(u)
        candidates=[edge for edge in graph.get(u,[]) if edge[2] != previous]
        if len(candidates) != 1: return envelope('unsupported', reason='Branch, missing endpoint or ambiguous route')
        u,length,eid=candidates[0]; previous=eid; total+=length; path.append(eid)
    if len(graph.get(goal,[])) != 1 or set(path) != set(edge_ids):
        return envelope('unsupported', reason='Additional copper, branch or disconnected segment prevents unique-path acceptance')
    return envelope('ok', metric='routed_length', value=total*COORD_TO_MM, unit='mm',
                    snapshot_id=snapshot['snapshot_id'], object_ids=[a,b], path_object_ids=path,
                    method='explicit_single_layer_centerline_path', layer=layer,
                    excludes=['package_delay'], endpoint_matching='exact_native_coordinates')
