"""Strict dispatch for original recipes and sealed PaDiM research deployments."""
import json
from pathlib import Path

from src.inspection.vision_model import validated_files, VisionModel, method_digest


def checked_asset(root):
    root = Path(root).expanduser().resolve()
    path = root / 'recipe.json'
    if path.stat().st_size > 128 * 1024: raise ValueError('视觉配方过大')
    method = json.loads(path.read_bytes()).get('method')
    if method == 'frozen-padim-v1':
        from src.inspection.release_deployment import validated_deployment
        return validated_deployment(root)
    return validated_files(root)


def asset_files(recipe):
    return ('recipe.json', *recipe['files']) if recipe['method'] == 'frozen-padim-v1' else ('recipe.json', 'weights.pth', 'statistics.npz', 'reference.png')


def asset_method_digest(method):
    if method == 'frozen-padim-v1':
        from src.inspection.release_deployment import deployment_digest
        return deployment_digest()
    return method_digest()


def load_asset(root, features=None):
    _, recipe = checked_asset(root)
    if recipe['method'] == 'frozen-padim-v1':
        from src.inspection.release_deployment import FrozenVisionModel
        return FrozenVisionModel(root, features)
    return VisionModel(root, features)
