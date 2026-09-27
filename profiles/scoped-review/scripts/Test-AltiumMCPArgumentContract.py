"""Installed MCP argument binding regression; no server or Designer launch."""
import ast
import asyncio
import json
from pathlib import Path
import sys
import unittest
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from pydantic import StrictInt, ValidationError

ROOT=Path(__file__).resolve().parents[1]
SERVER=ROOT/'server'
sys.path.insert(0,str(SERVER))
from bridge_contract import session_object_id

class Sink:
    async def measure(self,snapshot_id,a,b,metric,layer):
        return {'a':session_object_id(a),'b':session_object_id(b)}

tree=ast.parse((SERVER/'main.py').read_text(encoding='utf-8'))
nodes=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and
       node.name in ('bridge_v2_json','bridge_measure_geometry')]
for node in nodes: node.decorator_list=[]
namespace={'json':json,'StrictInt':StrictInt,'Context':object,'bridge_v2_service':Sink()}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'production_measure_binding','exec'),namespace)
production=namespace['bridge_measure_geometry']

class Binding(unittest.IsolatedAsyncioTestCase):
    async def test_original_string_signature_reproduces_sdk_rejection(self):
        async def original(a:str,b:str): return a,b
        meta=func_metadata(original)
        with self.assertRaises(ValidationError):
            await meta.call_fn_with_arg_validation(original,True,{'a':'9335476864','b':'9334322944'},None)
    async def test_production_signature_preserves_decimal_addresses(self):
        meta=func_metadata(production,skip_names=['ctx'])
        for a,b in [('9335476864','9334322944'),(9335476864,9334322944)]:
            result=await meta.call_fn_with_arg_validation(production,True,
                {'snapshot_id':'a'*32,'a':a,'b':b,'metric':'pad_center_distance'},{'ctx':None})
            self.assertEqual(json.loads(result),{'a':'9335476864','b':'9334322944'})
    async def test_production_signature_rejects_fraction_boolean_and_scientific_text(self):
        meta=func_metadata(production,skip_names=['ctx'])
        for bad in (True,1.5,'1e3'):
            with self.assertRaises(ValidationError):
                await meta.call_fn_with_arg_validation(production,True,
                    {'snapshot_id':'a'*32,'a':bad,'b':'9334322944','metric':'pad_center_distance'},{'ctx':None})

if __name__=='__main__': unittest.main(verbosity=2)
