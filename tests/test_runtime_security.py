import unittest
from unittest.mock import Mock,patch
from django.core.exceptions import ImproperlyConfigured
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('runtime_security',str(Path(__file__).resolve().parents[1] / 'config/runtime_security.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
load_runtime_security=module.load_runtime_security
from django.conf import settings
if not settings.configured:settings.configure(DEFAULT_CHARSET='utf-8',FUNNEL_INGEST_SECRET='test-current',FUNNEL_INGEST_PREVIOUS_SECRET='test-previous')
from django.test import RequestFactory,override_settings
from users.funnel_ingest import funnel_ingest
class RuntimeTests(unittest.TestCase):
 def setUp(self):
  context=override_settings(FUNNEL_INGEST_SECRET='test-current',FUNNEL_INGEST_PREVIOUS_SECRET='test-previous');context.enable();self.addCleanup(context.disable)
 def load(self,value,debug=False):return load_runtime_security(secret_name='test/secret',debug=debug,fetch=Mock(return_value=value),read_env=Mock(side_effect=AssertionError('env must not override managed secret')))
 def test_managed_secret_wins(self):self.assertEqual(self.load({'ADMIN_PATH':'control-test-randomized','FUNNEL_INGEST_SECRET':'new'})['FUNNEL_INGEST_SECRET'],'new')
 def test_no_production_env_fallback(self):
  with self.assertRaises(ImproperlyConfigured):load_runtime_security(secret_name='',debug=False,fetch=Mock(),read_env=Mock(return_value='leaked'))
 def test_unavailable_secret_redacts_error(self):
  with self.assertRaisesRegex(ImproperlyConfigured,'^Runtime security secret is unavailable$'):load_runtime_security(secret_name='name',debug=False,fetch=Mock(side_effect=ValueError('sensitive')),read_env=Mock())
 def test_rejects_bad_paths_and_payloads(self):
  for value in ['not-json',{'ADMIN_PATH':'confio-control-panel','FUNNEL_INGEST_SECRET':'s'},{'ADMIN_PATH':'x/../../admin','FUNNEL_INGEST_SECRET':'s'},{'ADMIN_PATH':'control-valid-path','FUNNEL_INGEST_SECRET':''},{'ADMIN_PATH':123}]:
   with self.subTest(value=type(value).__name__),self.assertRaises(ImproperlyConfigured):self.load(value)
 def test_local_debug_explicit_fallback(self):
  v=load_runtime_security(secret_name='',debug=True,fetch=Mock(),read_env=lambda k,d:d);self.assertEqual(v['ADMIN_PATH'],'local-control-panel')
 def test_auth_rotation_and_retirement(self):
  def send(secret):return funnel_ingest(RequestFactory().post('/api/funnel/ingest/',data='{"event_name":"referral_link_clicked"}',content_type='application/json',HTTP_X_FUNNEL_SECRET=secret))
  with patch('users.funnel.emit_event') as emit:
   self.assertEqual(send('test-current').status_code,200);self.assertEqual(send('test-previous').status_code,200);self.assertEqual(send('wrong').status_code,401);self.assertEqual(emit.call_count,2)
   with override_settings(FUNNEL_INGEST_PREVIOUS_SECRET=''):self.assertEqual(send('test-previous').status_code,401)
 def test_missing_current_fails_closed(self):
  with override_settings(FUNNEL_INGEST_SECRET=''):
   r=funnel_ingest(RequestFactory().post('/api/funnel/ingest/',HTTP_X_FUNNEL_SECRET='test-previous'));self.assertEqual(r.status_code,503)
if __name__=='__main__':unittest.main()
