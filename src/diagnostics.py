"""Shared terminal/page diagnostics; no images, notes, prompts or environment dump."""
from importlib.metadata import version, PackageNotFoundError
import platform
import sys
import time

from src.llm.deployment import runtime_plan


def environment_diagnostics():
    packages = {}
    for name in ('numpy', 'scipy', 'opencv-python-headless', 'torch', 'torchvision', 'fastapi', 'uvicorn'):
        try: packages[name] = {'installed': True, 'version': version(name)}
        except PackageNotFoundError: packages[name] = {'installed': False, 'version': None}
    return {'system': platform.system(), 'architecture': platform.machine(), 'python': sys.version.split()[0],
            'interpreter': sys.executable, 'packages': packages, 'runtime_plan': runtime_plan(),
            'visual_dependencies': {'available': all(packages[name]['installed'] for name in ('torch', 'torchvision')),
                'command': f'"{sys.executable}" -m pip install -r requirements-vision.txt',
                'guidance': '先安装可选视觉依赖，再重新加载模型。封存研发配方还要求各包版本与配方一致；此检查仅确认安装记录，真实加载才能确认可用。'}}


def workstation_diagnostics(station=None):
    result = {'format': 'spark-workstation-diagnostics-v1', 'created': time.time(), 'environment': environment_diagnostics(),
              'scope': '部署与维护状态；不包含图像、人工记录、复核提示词或环境变量'}
    if station is None:
        result.update(online=False, guidance='终端离线检查；运行状态未知，启动工作台后使用 --endpoint 获取同页面诊断')
    else:
        with station.lock:
            runtime = station.monitor.vision.state() if station.monitor.vision else {'status': 'disabled'}
            result.update(online=True, visual_runtime=runtime, maintenance_busy=station.maintenance_busy)
        result.update(review_model=station.models.diagnostics(), visual_assets=station.vision_catalog.snapshot(),
                      storage=station.monitor.store.storage_info())
    return result
