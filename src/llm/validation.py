"""Real generation gate for deployment, separate from production quality evaluation."""
import hashlib
import time
import uuid
from .spark_client import SparkXClient
from .response_parser import ResponseParser
from .faults import check_cancel

PROBE_PROMPT = """这是部署推理自检，不是实际工位诊断。只返回要求的 JSON。
没有当前图像、基线、检测记录或质量指标，证据不足，不能推定现场正常或异常。
说明信息不足，提出人工收集基线与当前指标的步骤，不作停线或放行建议。
requires_human_review 必须为 true，drift_type 为 unknown。
"""


def validate_model(name, endpoint, cancel=None, policy=None):
    check_cancel(cancel)
    client = SparkXClient(name, base_url=endpoint, policy=policy)
    if not client.initialize(): raise RuntimeError(client.last_error)
    raw = client.generate(PROBE_PROMPT, max_tokens=1024, temperature=.2, thinking=False)
    ResponseParser.parse_drift_analysis(raw)
    check_cancel(cancel)
    return {'id':uuid.uuid4().hex, 'name':name, 'endpoint':endpoint, 'created':time.time(),
            'policy':dict(client.policy), 'details':dict(client.details), 'inference':dict(client.last_metrics),
            'probe_sha256':hashlib.sha256(PROBE_PROMPT.encode()).hexdigest(),
            'scope':'官方模型身份、真实生成与结构化响应；不证明诊断正确率', 'status':'passed'}
