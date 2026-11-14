# SPDX-License-Identifier: GPL-3.0-only
# AyuGhost: modified source version, 2026-11-14.
# AyuGhost changes maintained by @internetmodel and @skerbio.
# Original feature basis: re:extera by @bleizix and @shikaatux.
# See LICENSE and NOTICE for licensing and attribution.

import ast
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
import zipfile
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from policy import request_action,DEFAULTS,silent_mode
from storage import Archive

class PrivacyTests(unittest.TestCase):
 def test_default_does_not_change_requests(self):
  self.assertEqual(request_action('TL_messages_readHistory',False,DEFAULTS.get),'pass')
 def test_enabled_hides_reads_typing_and_stories(self):
  for req in ('TL_messages_readHistory','TL_messages_setTyping','TL_stories_readStories'):
   self.assertEqual(request_action(req,True,DEFAULTS.get),'cancel')
 def test_per_chat_allow_overrides_ghost(self):
  self.assertEqual(request_action('TL_messages_readHistory',True,DEFAULTS.get,1,0),'pass')
 def test_per_chat_block_works_without_global_ghost(self):
  self.assertEqual(request_action('TL_messages_setTyping',False,DEFAULTS.get,0,2),'cancel')
 def test_online_becomes_offline_without_cancelling(self):
  self.assertEqual(request_action('updateStatus',True,DEFAULTS.get),'offline')
 def test_other_requests_pass(self):
  self.assertEqual(request_action('TL_messages_sendMessage',True,DEFAULTS.get),'pass')
 def test_silent_three_modes(self):
  self.assertFalse(silent_mode(0,True));self.assertFalse(silent_mode(1,False))
  self.assertTrue(silent_mode(1,True));self.assertTrue(silent_mode(2,False))

class StoreTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.db';self.a=Archive(self.path)
 def tearDown(self):self.a.close();self.temp.cleanup()
 def test_snapshot_edit_history_and_dedup(self):
  self.a.snapshot(0,10,12,100,'old',b'old')
  self.a.snapshot(0,10,12,120,'new',b'new',True)
  self.a.snapshot(0,10,12,120,'new',b'new',True)
  self.assertEqual([r[1] for r in self.a.history(0,10,12)],['old','new'])
 def test_snapshots_separate_accounts(self):
  self.a.snapshot(0,10,12,1,'first');self.a.snapshot(1,10,12,1,'second')
  self.a.mark(0,10,[12]);self.assertEqual(self.a.list_deleted(0)[0][3],'first')
  self.assertEqual(self.a.list_deleted(1),[])
 def test_deleted_mark_survives_another_snapshot(self):
  self.a.snapshot(0,10,12,1,'x');self.a.mark(0,10,[12]);self.a.snapshot(0,10,12,1,'x')
  self.assertEqual(len(self.a.list_deleted(0)),1)
 def test_exception_and_hidden_persist(self):
  self.a.set_exception(-9,1,2);self.a.set_hidden(55,False,True);self.a.set_filters(['spam','test'])
  self.a.close();self.a=Archive(self.path)
  self.assertEqual(self.a.exception(-9),(1,2));self.assertEqual(self.a.hidden[55],(False,True))
  self.assertEqual(self.a.filters,['spam','test'])
 def test_clear_preserves_configuration(self):
  self.a.set_exception(1,1,0);self.a.set_hidden(55);self.a.mark(0,1,[1]);self.a.clear_archive()
  self.assertFalse(self.a.is_deleted(1,1));self.assertEqual(self.a.exception(1),(1,0));self.assertIn(55,self.a.hidden)
 def test_legacy_tables_are_preserved(self):
  self.a.db.execute('INSERT INTO message_edits VALUES(10,12,0,20,?)',(b'original',));self.a.db.commit()
  self.a.close();self.a=Archive(self.path)
  self.assertEqual(self.a.legacy_history(10,12),[(20,b'original')])

def mod(name,**kw):
 m=types.ModuleType(name);m.__dict__.update(kw);sys.modules[name]=m
class Proxy:
 def __init__(self):pass
class JavaClass:
 def getSimpleName(self):return self.name
class Request:
 def __init__(self,n):self.n=n;self.offline=False
 def hashCode(self):return id(self)
 def getClass(self):return types.SimpleNamespace(getSimpleName=lambda:self.n)
class Param:
 def __init__(self,*args):self.args=list(args);self.thisObject=types.SimpleNamespace(currentAccount=0);self.result='untouched'
 def setResult(self,result):self.result=result
class FakePattern:
 @staticmethod
 def compile(value):return value

class NativeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  mod('java',jclass=lambda n:FakePattern if n=='java.util.regex.Pattern' else Proxy,dynamic_proxy=lambda *a:Proxy)
  mod('base_plugin',MethodHook=Proxy)
  mod('hook_utils',find_class=lambda n:None,get_private_field=lambda o,k:getattr(o,k,None),set_private_field=lambda o,k,v:setattr(o,k,v) or True)
  mod('client_utils',get_last_fragment=lambda:None)
  cls.native=importlib.import_module('native')
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.archive=Archive(Path(self.tmp.name)/'test.db')
  self.options=dict(DEFAULTS);self.plugin=types.SimpleNamespace(archive=self.archive,option=self.options.get,log=lambda x:None,unhook_method=lambda h:self.unhooks.append(h))
  self.unhooks=[];self.n=self.native.Native(self.plugin)
 def tearDown(self):self.archive.close();self.tmp.cleanup()
 def test_read_cancel_and_exception(self):
  self.options['ghostEnabled']=True;r=Request('TL_messages_readHistory');p=Param(r)
  self.n.request(p);self.assertIsNone(p.result)
  self.archive.set_exception(0,1,0);p=Param(r);self.n.request(p);self.assertEqual(p.result,'untouched')
 def test_online_request_is_changed(self):
  self.options['ghostEnabled']=True;r=Request('updateStatus');p=Param(r);self.n.request(p)
  self.assertTrue(r.offline);self.assertEqual(p.result,'untouched')
 def test_owned_manual_read_bypasses_rule(self):
  self.options['ghostEnabled']=True;r=Request('TL_messages_readHistory');self.n.unfiltered.add(r.hashCode())
  p=Param(r);self.n.request(p);self.assertEqual(p.result,'untouched')
 def test_unload_stops_callbacks_and_clears_handles(self):
  self.n.handles=[1,2,3];self.n.stop();self.assertEqual(self.unhooks,[3,2,1]);self.assertFalse(self.n.active);self.assertEqual(self.n.handles,[])
 def test_registration_uses_chaquopy_class_object(self):
  from unittest.mock import patch
  registered=[]
  method=types.SimpleNamespace(getName=lambda:'target',getParameterTypes=lambda:[1,2],setAccessible=lambda value:None)
  reflected=types.SimpleNamespace(getDeclaredMethods=lambda:[method])
  class Wrapper:
   @staticmethod
   def getClass():return reflected
  self.plugin.hook_method=lambda m,cb:registered.append(m) or 'handle'
  with patch.object(self.native,'find_class',return_value=Wrapper):
   self.n.hook('sample.JavaClass','target',counts={2})
  self.assertEqual(registered,[method]);self.assertEqual(self.n.handles,['handle']);self.assertEqual(self.n.failures,[])
 def test_registration_accepts_raw_reflection_class(self):
  from unittest.mock import patch
  method=types.SimpleNamespace(getName=lambda:'target',getParameterTypes=lambda:[],setAccessible=lambda value:None)
  reflected=types.SimpleNamespace(getDeclaredMethods=lambda:[method])
  self.plugin.hook_method=lambda m,cb:'handle'
  with patch.object(self.native,'find_class',return_value=reflected):self.n.hook('sample.JavaClass','target',counts={0})
  self.assertEqual(self.n.handles,['handle']);self.assertEqual(self.n.failures,[])
 def test_reflection_error_does_not_abort_other_hooks(self):
  from unittest.mock import patch
  class Broken:
   @staticmethod
   def getClass():raise RuntimeError('unavailable')
  with patch.object(self.native,'find_class',return_value=Broken):self.n.hook('broken','target')
  self.assertIn('reflection failed: unavailable',self.n.failures[0])
  self.n.hook('missing','other');self.assertEqual(len(self.n.failures),2)
 def test_registration_failure_is_reported(self):
  self.n.hook('missing','x');self.assertIn('class missing',self.n.failures[0])

class SourceSafetyTests(unittest.TestCase):
 def test_no_executable_assets_or_dynamic_loader(self):
  for p in [ROOT/name for name in ('main.py','native.py','policy.py','storage.py')]:
   source=p.read_text();ast.parse(source)
   for forbidden in ('DexClassLoader','InMemoryDexClassLoader','load_dex','subprocess','urllib.request','requests.get'):
    self.assertNotIn(forbidden,source)
   for n in ast.walk(ast.parse(source)):
    if isinstance(n,ast.Call) and isinstance(n.func,ast.Name):self.assertNotIn(n.func.id,('eval','exec','compile','__import__'))
 def test_preview_is_separate_and_limitations_disclosed(self):
  s=(ROOT/'main.py').read_text()
  self.assertIn("__id__='ayughost_source_test'",s)
  self.assertIn("'ayughost_source_test.db'",s)
  doc=(ROOT/'KNOWN_LIMITATIONS.md').read_text()
  self.assertIn('НЕ перенесены полностью',doc)

if __name__=='__main__':unittest.main()
