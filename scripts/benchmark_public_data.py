"""Normal-only, handcrafted patch Gaussian baseline on verified VisA PCB1 images.

Independent offline experiment; scores are not calibrated confidence, and no labels enter prediction.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time

import cv2
import numpy as np
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json
from src.datasets import DatasetStore, digest


class PatchGaussian:
    """Fixed 320x240 Lab patch descriptors, diagonal normal statistics, no pretrained weights."""
    @staticmethod
    def features(frame):
        image = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32) / 255
        # A 16x16 patch has a 4x4 spatial grid of Lab means (48 dimensions).
        pooled = cv2.resize(lab, (80, 60), interpolation=cv2.INTER_AREA)
        return pooled.reshape(15,4,20,4,3).transpose(0,2,1,3,4).reshape(300,48)

    def fit(self, frames):
        features = np.stack([self.features(frame) for frame in frames])
        self.mean = features.mean(axis=0)
        self.scale = np.maximum(features.std(axis=0), 0.03)  # Fixed variance floor.

    def score(self, frame):
        distances = np.mean(((self.features(frame) - self.mean) / self.scale)**2, axis=1)
        return float(np.mean(np.sort(distances)[-3:]))  # Top 1% patches; fixed before test.


def auroc(labels, scores):
    labels = np.asarray(labels, dtype=bool)
    positive, negative = int(labels.sum()), int((~labels).sum())
    if not positive or not negative: return None
    ranks = rankdata(scores, method='average')
    return float((ranks[labels].sum() - positive*(positive+1)/2) / (positive*negative))


def run(source: Path, output: Path):
    if output.exists(): raise ValueError('Output exists; preserve prior measurements')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.public-benchmark-', dir=output.parent) as temporary:
        prepared = Path(temporary) / 'report'
        report, imported = _run(source, prepared)
        if output.exists(): raise ValueError('Output appeared during experiment; preserve existing evidence')
        prepared.rename(output)
    print(json.dumps({'metrics':report['metrics'],'dataset_id':imported['id'],'manifest':str((output/'manifest.json').resolve())},ensure_ascii=False))
    return report


def _run(source: Path, output: Path):
    metadata = json.loads((source / 'source.json').read_bytes())
    rows = metadata['files']
    def image(row):
        path = (source / row['image']).resolve()
        if not path.is_relative_to(source.resolve()): raise ValueError('Source path escapes dataset root')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row['sha256']: raise ValueError('Source image digest mismatch')
        frame = cv2.imdecode(np.frombuffer(content,np.uint8),cv2.IMREAD_COLOR)
        if frame is None: raise ValueError('Source image decode failed')
        return frame
    training = sorted([r for r in rows if r['split']=='train' and r['label']=='normal'], key=lambda r:r['image'])
    if len(training) < 30: raise ValueError('At least 30 verified normal training images required')
    fit_rows, calibration = training[:-20], training[-20:]
    evaluations = sorted([r for r in rows if r['split']=='test'], key=lambda r:r['image'])
    if not evaluations: raise ValueError('No evaluation images')
    start=time.perf_counter()
    detector=PatchGaussian()
    detector.fit([image(row) for row in fit_rows])
    fit_seconds=time.perf_counter()-start
    calibration_scores=[detector.score(image(row)) for row in calibration]
    threshold=float(np.quantile(calibration_scores,.95,method='higher'))
    predictions=[]
    for row in evaluations:
        frame=image(row)
        begin=time.perf_counter()
        score=detector.score(frame)
        predictions.append({'image':row['image'],'image_sha256':row['sha256'], 'score':score,
                            'is_ng':score>threshold,'elapsed_ms':(time.perf_counter()-begin)*1000})
    # Labels are attached only after all predictions and the threshold are fixed.
    labels={r['image']:r['label'] for r in evaluations}
    for prediction in predictions: prediction['label']=labels[prediction['image']]
    tp=sum(r['is_ng'] and r['label']=='anomaly' for r in predictions)
    tn=sum(not r['is_ng'] and r['label']=='normal' for r in predictions)
    fp=sum(r['is_ng'] and r['label']=='normal' for r in predictions)
    fn=sum(not r['is_ng'] and r['label']=='anomaly' for r in predictions)
    report={'dataset':'VisA PCB1 bounded subset', 'source_sha256':hashlib.sha256((source/'source.json').read_bytes()).hexdigest(),
            'method':'handcrafted spatial Lab patch diagonal Gaussian; normal-only fit',
            'method_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'parameters':{'resize':[320,240],'patch_size':16,'pooled_grid':[4,4],'variance_floor':.03,'top_patches':3},
            'fit_count':len(fit_rows),'calibration_count':len(calibration),'test_count':len(predictions),
            'fit_ids':[r['image'] for r in fit_rows],'calibration_ids':[r['image'] for r in calibration],
            'threshold':threshold,'threshold_policy':'95th percentile (higher) of held-out normal train calibration; fixed before test',
            'fit_seconds':fit_seconds,'platform':platform.platform(),'numpy':np.__version__,'opencv':cv2.__version__,
            'metrics':{'image_auroc':auroc([r['label']=='anomaly' for r in predictions],[r['score'] for r in predictions]),
                       'tp':tp,'tn':tn,'fp':fp,'fn':fn,'recall':tp/(tp+fn) if tp+fn else None,
                       'false_positive_rate':fp/(fp+tn) if fp+tn else None},
            'predictions':predictions,'limitations':['Not PatchCore/PaDiM or a production defect detector',
                'No segmentation metrics; masks not used','No test labels used for training, threshold or parameter tuning',
                'Bounded lexicographic subset, one category; not full benchmark or factory validation',
                'Scores are uncalibrated anomaly scores; not exported as decision confidence',
                'No Spark inference or fault-cause ground truth evaluation']}
    output.mkdir(parents=True)
    write_json(output/'benchmark.json',report)
    # Prepare exact same pixels for the existing workstation. Different files keep official partitions explicit.
    samples=[]
    chosen = fit_rows[:min(100,len(fit_rows))]+evaluations
    for index,row in enumerate(chosen):
        filename=f'images/{index:04d}.png'
        destination=output/filename;destination.parent.mkdir(exist_ok=True)
        if not cv2.imwrite(str(destination),cv2.resize(image(row),(640,480),interpolation=cv2.INTER_AREA)):
            raise OSError('Failed to save normalized public image')
        samples.append({'id':f'visa-pcb1-{index:04d}','batch':f'VisA pcb1 official {row["split"]}',
                        'path':filename,'split':'baseline' if row['split']=='train' else 'evaluation','origin':'real',
                        'conditions':{'dataset':'VisA','official_partition':row['split'],'original_file':row['image'],
                                      'source_revision':metadata['revision'],'license':'CC BY 4.0'},
                        'label':{'defect':'defect' if row['label']=='anomaly' else 'normal','cause':'unknown',
                                 'note':'Official image-level annotation; no fault-cause label'}})
    write_json(output/'manifest.json',{'schema_version':1,'name':'VisA PCB1 public subset',
               'description':'Official public images and annotations; train/test are partitions, not factory batch IDs', 'samples':samples})
    store=DatasetStore(output/'datasets')
    imported=store.import_manifest(output/'manifest.json')
    write_json(output/'import.json',imported)
    return report, imported


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'data/public-datasets/visa-pcb1')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/public-data-visa-pcb1')
    args=parser.parse_args();run(args.input,args.output)


if __name__=='__main__':main()
