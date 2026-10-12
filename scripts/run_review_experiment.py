"""Run a frozen independent-model study on an owned temporary service, then close it."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_review_methods import run, source_digests
from src.llm.deployment import ROOT as MODEL_ROOT, preflight, serving_environment, verify_weight
from src.llm.research_client import BASELINE, ResearchClient
from src.llm.runtime import OwnedRuntime
from src.review_study import load_suite, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=11436)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port == 11435:
        parser.error('Use an independent port 1024..65535; 11435 is reserved for the workstation')
    if args.output.exists(): raise ValueError('Output exists; preserve experiment evidence')
    suite = load_suite(read_json(args.suite))['suite']
    if suite['schema_version'] != 2 or suite['source_sha256'] != source_digests():
        raise ValueError('Expected a matching frozen independent-baseline suite')
    if suite['source'].get('single_use') and args.suite.with_name(args.suite.name+'.consumed.json').exists():
        raise ValueError('Held-out suite already consumed; preserve its original evidence')
    weight = MODEL_ROOT/'models'/BASELINE['file']
    if not verify_weight(weight, BASELINE): raise ValueError('Prepare and verify the pinned independent baseline first')
    args.output.mkdir(parents=True)
    runtime = OwnedRuntime(args.output/'runtime')
    def interrupt(*_): raise KeyboardInterrupt('Experiment interrupted')
    signal.signal(signal.SIGTERM, interrupt)
    try:
        runtime.start('4b', args.port)
        runtime.import_model('1.7b', preflight('1.7b', runtime.report['runtime_cli']), runtime.cancel)
        modelfile = args.output/'baseline.Modelfile'
        modelfile.write_text(f'FROM {json.dumps(str(weight))}\nPARAMETER num_ctx 4096\n', encoding='utf-8')
        with (args.output/'baseline-import.log').open('xb') as log:
            runtime.importer = subprocess.Popen([runtime.report['runtime_cli'], 'create', BASELINE['model_name'],
                                                 '-f', str(modelfile.resolve())], cwd=ROOT,
                                                env=serving_environment(args.port), stdout=log, stderr=subprocess.STDOUT)
            runtime.importer.wait(timeout=240)
        if runtime.importer.returncode: raise RuntimeError('Independent baseline import failed; inspect baseline-import.log')
        client = ResearchClient(BASELINE['model_name'], base_url=f'http://127.0.0.1:{args.port}')
        if not client.initialize(): raise RuntimeError(client.last_error)
        report = run(args.suite, args.output/'run', f'http://127.0.0.1:{args.port}')
        print(json.dumps({'study_id': report['study_id'], 'accepted': report['accepted'],
                          'summaries': [{k: s[k] for k in ('id', 'coverage', 'category_agreement', 'status')} for s in report['summaries']]}))
        return 0
    finally:
        runtime.close()


if __name__ == '__main__': raise SystemExit(main())
