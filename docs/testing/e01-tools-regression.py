"""Independent CPU behavior checks for the teammate E01 patch.

All datasets are synthetic temporary fixtures, never the formal candidate.
Run with LLMCLOUD_TEST_REPO pointing to the patched isolated checkout.
"""
import copy
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

REPO = Path(os.environ['LLMCLOUD_TEST_REPO']).resolve()
sys.path.insert(0, str(REPO))
from scripts.prepare_dataset import plan_dataset, write_bundle, load_protocol, PreparationError
from trainer.contracts import DatasetSummary, TrainingError
from trainer.dataset import scan_dataset
from trainer.dataset_manifest import verify_prepared_metadata
import trainer.reload as reload_module

def module_at(name, relative):
    spec=importlib.util.spec_from_file_location(name, REPO/relative)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class PreparationPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='e01-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'synthetic.jsonl'
        self.curation=self.root/'curation.json'
        self.protocol=self.root/'eval-v2.json'
        self.catalog=self.root/'sources.json'
        self.source.write_text(''.join(json.dumps({'instruction':f'CPU合成独立问题 {i}', 'input':'', 'output':f'合成回答 {i}'},ensure_ascii=False)+'\n' for i in range(6)))
        self.metadata={'version':'1.0.0','rows':[{'row':i+1,'record_id':f'synthetic-{i}',
            'group_id':f'synthetic-family-{i}','source_ids':['test-source'],'reviewed':False} for i in range(6)]}
        self.curation.write_text(json.dumps(self.metadata))
        # A deliberately custom source and protocol proves CLI options are used.
        self.catalog.write_text(json.dumps({'sources':[{'id':'test-source','url':'https://example.invalid/synthetic','title':'Synthetic only'}]}))
        self.eval_doc={'version':'2.0.0','domain':'cloud-basics-zh','cases':[{'id':'S01',
            'prompt':'独立合成冻结题不得混入合成数据','group_id':'synthetic-reserved',
            'expected_points':['synthetic'],'critical_errors':['synthetic'],'source_ids':['test-source']}]}
        self.protocol.write_text(json.dumps(self.eval_doc))

    def cli(self, *extra):
        return subprocess.run([sys.executable,str(REPO/'scripts/prepare_dataset.py'),
            '--source',str(self.source),'--curation',str(self.curation),
            '--sources',str(self.catalog),'--eval-protocol',str(self.protocol),*extra],
            cwd=REPO,text=True,capture_output=True,timeout=30)

    def test_custom_cli_paths_v2_and_check_only_do_not_write(self):
        output=self.root/'must-not-exist'
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        result=self.cli('--allow-unreviewed','--check-only','--output',str(output))
        self.assertEqual(result.returncode,0,result.stderr)
        manifest=json.loads(result.stdout)
        self.assertEqual(manifest['protocol_version'],'2.0.0')
        self.assertEqual(manifest['review_status'],'draft_unreviewed')
        self.assertEqual(manifest['source_catalog_sha256'],hashlib.sha256(self.catalog.read_bytes()).hexdigest())
        self.assertEqual(manifest['protocol_sha256'],hashlib.sha256(self.protocol.read_bytes()).hexdigest())
        self.assertFalse(output.exists())
        self.assertEqual({p.name:p.read_bytes() for p in self.root.iterdir()},before)

    def test_custom_cli_still_rejects_unreviewed_for_formal_mode(self):
        result=self.cli('--check-only')
        self.assertEqual(result.returncode,2)
        self.assertIn('Unreviewed',result.stderr)
        self.assertEqual(result.stdout,'')

    def test_unknown_protocol_version_is_rejected_without_output(self):
        self.eval_doc['version']='3.0.0'
        self.protocol.write_text(json.dumps(self.eval_doc))
        result=self.cli('--allow-unreviewed','--check-only')
        self.assertEqual(result.returncode,2)
        self.assertIn('Unsupported evaluation protocol version',result.stderr)

    def test_v1_custom_protocol_remains_accepted(self):
        self.eval_doc['version']='1.0.0'
        self.protocol.write_text(json.dumps(self.eval_doc))
        result=self.cli('--allow-unreviewed','--check-only')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['protocol_version'],'1.0.0')

    def test_v2_manifest_consumer_accepts_real_synthetic_hashes_and_rejects_tamper(self):
        files,manifest=plan_dataset(self.source,self.curation,protocol_path=self.protocol,
            sources_path=self.catalog,allow_unreviewed=True)
        bundle=self.root/'synthetic-bundle'
        write_bundle(bundle,files)
        def summary(name):
            stats=scan_dataset(bundle/f'{name}.jsonl')
            return DatasetSummary(sha256=stats.sha256,size_bytes=stats.size_bytes,row_count=stats.row_count)
        checked=verify_prepared_metadata(bundle/'manifest.json',summary('train'),summary('validation'))
        self.assertEqual(checked['train'].review_status,'draft_unreviewed')
        self.assertEqual(checked['validation'].build_id,manifest['build_id'])
        invalid=copy.deepcopy(manifest)
        invalid['protocol_version']='3.0.0'
        (bundle/'manifest.json').write_text(json.dumps(invalid))
        with self.assertRaises(TrainingError):
            verify_prepared_metadata(bundle/'manifest.json',summary('train'))

class ReloadPatchTests(unittest.TestCase):
    def test_compare_request_and_default_are_forwarded_without_gpu_access(self):
        verified=SimpleNamespace(manifest=SimpleNamespace(model_revision='a'*40,chat_template_sha256='b'*64))
        cached=SimpleNamespace(manifest=SimpleNamespace(chat_template_sha256='b'*64))
        for options,expected in (({},False),({'compare':True},True)):
            with self.subTest(options=options), \
                patch.object(reload_module,'verify_training_artifacts',return_value=verified), \
                patch.object(reload_module,'verify_model_cache',return_value=cached), \
                patch.object(reload_module,'_generate',return_value={'response':'CPU controlled'}) as generate:
                result=reload_module.reload_and_generate('/tmp/test-output','/tmp/test-cache',prompt='合成提示',**options)
                self.assertEqual(result,{'response':'CPU controlled'})
                self.assertIs(generate.call_args.args[0],verified)
                self.assertIs(generate.call_args.args[1],cached)
                self.assertEqual(generate.call_args.kwargs['compare'],expected)

    def test_cli_compare_is_opt_in_and_preserves_json_result(self):
        module=module_at('e01_reload_cli','scripts/reload_adapter.py')
        with tempfile.TemporaryDirectory(prefix='e01-reload-cli-') as temp:
            root=Path(temp)
            paths=SimpleNamespace(data_dir=root/'data',cache_dir=root/'cache',hf_home=root/'hf')
            task='992aa53a-a246-45de-a8f1-4d4164d9b42e'
            for extra,expected in (([],False),(['--compare'],True)):
                result={'status':'reload_verified','response':'合成结果'}
                if expected:
                    result.update(base={'generated_text':'合成基础'},adapter={'generated_text':'合成微调'})
                stream=io.StringIO()
                with self.subTest(compare=expected), \
                    patch.object(sys,'argv',['reload_adapter.py','--task-id',task,'--prompt','合成提示','--max-new-tokens','192',*extra]), \
                    patch.object(module,'resolve_model_paths',return_value=paths), \
                    patch.object(module,'reload_and_generate',return_value=result) as call, \
                    patch.dict(os.environ,{},clear=False), redirect_stdout(stream):
                    self.assertEqual(module.main(),0)
                self.assertEqual(call.call_args.kwargs['compare'],expected)
                self.assertEqual(call.call_args.kwargs['max_new_tokens'],192)
                self.assertEqual(call.call_args.kwargs['expected_task_id'],UUID(task))
                self.assertEqual(json.loads(stream.getvalue()),result)

if __name__=='__main__':
    unittest.main(verbosity=2)
