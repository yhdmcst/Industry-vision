"""Operator-facing failure categories; raw details remain available for maintenance."""

import errno
import socket
import subprocess

import httpx


class OperationCancelled(RuntimeError):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise OperationCancelled('操作已取消')


class ModelFault(RuntimeError):
    def __init__(self, code, message, remedy, detail=''):
        super().__init__(message)
        self.code, self.message, self.remedy, self.detail = code, message, remedy, detail


def describe_fault(exc):
    if isinstance(exc, ModelFault):
        code, message, remedy = exc.code, exc.message, exc.remedy
        detail = exc.detail
    elif isinstance(exc, OperationCancelled):
        code, message, remedy, detail = 'cancelled', '操作已取消', '可以重新开始；已完成的下载会保留。', ''
    elif isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE:
        code, message, remedy, detail = 'port_busy', '服务端口已被占用', '连接已有服务，或在维护设置中更换端口。', str(exc)
    elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        code, message, remedy, detail = 'disk_full', '磁盘空间不足', '清理其他文件后重试；现有模型和证据不会被自动删除。', str(exc)
    elif isinstance(exc, (httpx.TimeoutException, subprocess.TimeoutExpired, TimeoutError)):
        code, message, remedy, detail = 'timeout', '操作等待超时', '检查设备负载和网络后重试。', str(exc)
    elif isinstance(exc, (httpx.HTTPError, socket.gaierror)):
        code, message, remedy, detail = 'network', '连接或下载失败', '检查网络或服务是否运行，再重试。', str(exc)
    elif isinstance(exc, PermissionError):
        code, message, remedy, detail = 'permission', '文件访问权限不足', '检查模型和运行目录的读写权限。', str(exc)
    else:
        code, message, remedy, detail = 'operation_failed', '模型操作未完成', '查看维护详情中的原因，修复后重试。', str(exc)
    return {'code': code, 'message': message, 'remedy': remedy,
            'detail': detail[:2000], 'impact': '模型复核暂不可用；采集、规则观测和人工记录可继续使用。'}
