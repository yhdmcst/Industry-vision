import numpy as np
import pytest

from src.acceptance import evaluate, wilson
from src.inspection.methods import DensePatchMemory, PatchMemory, ShrinkagePaDiM, load_patch_memory, normal_roi, score_map


def rows():
    return [{'sample_id': f'{label}-{i}', 'label': label, 'status': 'ok',
             'is_ng': label == 'defect', 'anomaly_score': 2. if label == 'defect' else 0., 'group': 'a'}
            for label in ('normal', 'defect') for i in range(50)]


def test_acceptance_counts_unavailable_defects_and_blocks_development_claims():
    predictions = rows()
    assert evaluate(predictions)['status'] == 'passed'
    assert not evaluate(predictions)['accepted']
    assert evaluate(predictions, evidence='independent_final')['accepted']
    for row in predictions[-10:]: row.update(status='error', is_ng=None, anomaly_score=None)
    gate = evaluate(predictions, evidence='independent_final')
    assert gate['overall']['recall_all_defects'] == .8
    assert gate['overall']['unavailable']['defect'] == 10
    assert gate['status'] == 'failed' and not gate['accepted']


def test_small_groups_and_duplicate_views_never_increase_evidence():
    predictions = rows()
    predictions[-49:][0]['group'] = 'small'
    assert evaluate(predictions, groups=('small',))['status'] == 'insufficient_evidence'
    assert not evaluate(predictions, evidence='controlled_transform')['accepted']
    with pytest.raises(ValueError, match='Repeated'): evaluate(predictions+predictions[:1])
    predictions[0]['anomaly_score'] = float('nan')
    with pytest.raises(ValueError, match='finite'): evaluate(predictions)
    assert wilson(0,0) is None
    assert wilson(50,50)[0] < 1


def test_patch_memory_matches_normal_patches_and_roi_rejects_empty_normal_reference():
    embeddings = np.random.default_rng(0).normal(size=(10,14,14,3)).astype(np.float32)
    model = PatchMemory(); model.fit(embeddings)
    assert model.predict(embeddings[0])[0] < 1e-6
    assert model.predict(embeddings[0]+100)[0] > 100
    mask = np.zeros((224,224), bool); mask[100:120,100:120] = True
    heat = np.ones((224,224)); heat[0,0] = 10
    assert score_map(heat,mask) == 1 and score_map(heat) == 10
    with pytest.raises(ValueError, match='ROI'): normal_roi([np.zeros((480,640,3),np.uint8)])


def test_shrinkage_stabilizes_underdetermined_correlated_features_and_roundtrips(tmp_path):
    from src.inspection.padim import PaDiM
    rng = np.random.default_rng(4)
    signal = rng.normal(size=(12, 2, 2, 1)).astype(np.float32)
    features = np.repeat(signal, 30, axis=-1)+rng.normal(0, .001, (12, 2, 2, 30))
    raw = PaDiM(); raw.fit(features)
    model = ShrinkagePaDiM(); model.fit(features)
    assert np.linalg.cond(model.precision).max() < np.linalg.cond(raw.precision).min()
    shifted = features[0]+2
    assert model.predict(shifted)[0] > model.predict(model.mean)[0]
    path = tmp_path/'statistics.npz'; model.save(path)
    assert PaDiM.load(path).predict(shifted)[0] == pytest.approx(model.predict(shifted)[0])
    with pytest.raises(ValueError): model.fit(features[:9])
    features[0, 0, 0, 0] = np.nan
    with pytest.raises(ValueError): model.fit(features)


def test_dense_memory_uses_normal_scale_bounded_bank_and_validated_archive(tmp_path):
    features = np.random.default_rng(1).normal(size=(10, 8, 8, 3)).astype(np.float32)
    model = DensePatchMemory(); model.fit(features)
    assert model.bank.shape == (4096, 3)
    score = model.predict(features[0]+100)[0]
    assert score > model.predict(features[0])[0]
    path = tmp_path/'dense.npz'; model.save(path)
    assert load_patch_memory(path, dense=True).predict(features[0]+100)[0] == pytest.approx(score)
    with pytest.raises(ValueError, match='fields'): load_patch_memory(path)
    np.savez_compressed(path, bank=model.bank, center=model.center, scale=np.zeros(3))
    with pytest.raises(ValueError, match='scale'): load_patch_memory(path, dense=True)
