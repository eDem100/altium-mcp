"""Relocate output references and register the one MCP-created working copy."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
SERVER=ROOT/'server'
sys.path.insert(0,str(SERVER))
from pilot_policy import Policy, strict_json, canonical
from bridge_service import checked_child

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def relocate(data, original_root, copied_root):
    pattern=re.compile(re.escape(original_root.rstrip('\\').encode('ascii'))+rb'(?=[\\/])',re.IGNORECASE)
    result,count=pattern.subn(lambda match:copied_root.rstrip('\\').encode('ascii'),data)
    if pattern.search(result): raise RuntimeError('Original project path remains')
    return result,count

def main():
    policy_path=SERVER/'pilot_policy.json'; policy=Policy(policy_path)
    if policy.data['workspaces']: raise RuntimeError('A copy is already registered; reuse it')
    results=Path(policy.data['results_root'])
    marker=results/'working-copy.json'
    registration=strict_json(marker.read_text(encoding='ascii'))
    wid=registration['workspace_id']
    if not re.fullmatch('[a-f0-9]{32}',wid): raise RuntimeError('Invalid workspace identity')
    expected=checked_child(results,results/'workspaces'/wid)
    if canonical(registration['root'])!=canonical(str(expected)): raise RuntimeError('Unexpected copy root')
    reg_path=expected/'registration.json'
    if strict_json(reg_path.read_text(encoding='ascii'))!=registration: raise RuntimeError('Copy registration mismatch')
    candidate=dict(policy.data)
    candidate['workspaces']=[{key:registration[key] for key in ('workspace_id','root','project_path','board_path')}]
    base=Path(policy.data['pilot_root'])
    sources=[Path(policy.data['project_path']),*(Path(p) for p in policy.data['document_paths'])]
    for source in sources:
        target=checked_child(expected,expected/source.relative_to(base))
        if digest(source)!=registration['source_hashes'][str(source)] or digest(target)!=digest(source):
            raise RuntimeError('Source or initial copy changed: '+source.name)
    project=Path(registration['project_path'])
    old=project.read_bytes()
    updated,count=relocate(old,str(base),str(expected))
    changes=[i for i,(a,b) in enumerate(zip(old.splitlines(),updated.splitlines()),1) if a!=b]
    backup=results/'evidence'/('copy-preparation-'+wid)
    backup.mkdir(parents=True,exist_ok=False)
    shutil.copy2(policy_path,backup/'policy-before.json')
    shutil.copy2(project,backup/'project-before.PrjPcb')
    shutil.copy2(reg_path,backup/'registration-before.json')
    proposed=backup/'policy-candidate.json'
    proposed.write_text(json.dumps(candidate,indent=2,ensure_ascii=True)+'\n',encoding='ascii')
    checked=Policy(proposed); checked.registered_workspace()
    project.write_bytes(updated)
    prepared={str(p.relative_to(expected)):digest(p) for p in (expected/source.relative_to(base) for source in sources)}
    proof={'prepared_at':datetime.now(timezone.utc).isoformat(),'workspace_id':wid,
           'source_project_sha256':registration['source_hashes'][str(sources[0])],
           'copied_project_sha256':digest(project),'relocated_path_occurrences':count,
           'changed_project_lines':changes,'prepared_file_hashes':prepared,
           'dependencies':'not_verified','native_activation':'not_verified',
           'original_write_enabled':False}
    for source in sources:
        if digest(source)!=registration['source_hashes'][str(source)]: raise RuntimeError('Original changed during preparation')
    registration['copy_preparation']=proof
    reg_path.write_text(json.dumps(registration,indent=2,ensure_ascii=True)+'\n',encoding='ascii')
    marker.write_text(json.dumps(registration,indent=2,ensure_ascii=True)+'\n',encoding='ascii')
    policy_path.write_bytes(proposed.read_bytes())
    proof['registered_policy_id']=Policy(policy_path).identity
    (backup/'preparation-result.json').write_text(json.dumps(proof,indent=2,ensure_ascii=True)+'\n',encoding='ascii')
    print(json.dumps({'workspace_id':wid,'verified_source_and_copy_files':len(sources),
                      'relocated_references':count,'changed_project_lines':changes,
                      'policy_id':proof['registered_policy_id'],'original_changed':False,
                      'native_activation':'not_verified','evidence':str(backup)},ensure_ascii=True))

if __name__=='__main__': main()
