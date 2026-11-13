"""Keep the native import cause when UE's Python wrapper reports a generic error."""
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import traceback


def _log_marker(engine):
    try:
        directory = Path(engine.Paths.convert_relative_path_to_full(engine.Paths.project_log_dir()))
        logs = [p for p in directory.glob('*.log') if 'backup' not in p.name.lower()
                and not p.name.lower().startswith('cef')]
        path = max(logs, key=lambda p: p.stat().st_mtime_ns)
        return path, path.stat().st_size
    except Exception:
        return None


def _log_delta(marker):
    if marker is None:
        return ''
    path, offset = marker
    try:
        size = path.stat().st_size
        with path.open('rb') as stream:
            stream.seek(max(offset if size >= offset else 0, size - 1024 * 1024))
            return stream.read().decode('utf-8', errors='replace')
    except OSError:
        return ''


def _reason(details, original):
    bones = re.findall(r'(?:无法检索轨道的骨骼索引[:：]|Unable to retrieve bone index for track[:\s]+)\s*([^\r\n]+)', details)
    bones = list(dict.fromkeys(bone.strip().strip("'\"") for bone in bones))
    if bones:
        names = '、'.join(bones[:8]) + (u'等 {0} 根'.format(len(bones)) if len(bones) > 8 else '')
        return u'部分动画轨道无法映射到目标骨架，骨骼：{0}。\n请检查对应部位的动画效果；如需保留这些轨道，请使用匹配骨架的动画版本或重新导出。'.format(names)
    if "GLView::_advanceFrame" in details:
        return u'导入期间触发动作预览回调异常：GLView::_advanceFrame。'
    if 'returned NULL without setting an exception' in str(original):
        errors = list(dict.fromkeys(line.strip() for line in details.splitlines()
                      if ('Error:' in line or '错误' in line) and 'returned NULL' not in line))
        if errors:
            return '\n'.join(errors[:6])
        return u'UE 导入接口异常退出，未返回具体原因；请查看诊断记录和 UE 输出日志。\n{0}'.format(original)
    return str(original)


@contextmanager
def capture(source, skeleton, destination, engine):
    marker = _log_marker(engine)
    try:
        yield
    except Exception as exc:
        trace = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log = _log_delta(marker)
        reason = _reason(trace + '\n' + log, exc)
        message = record(source, skeleton, destination, reason, trace, log, marker)
        raise RuntimeError(message) from exc


def record(source, skeleton, destination, reason, trace='', log='', marker=None, outcome=None):
    """Record warning/unsaved evidence as well as exceptions that produced no output."""
    try:
        root = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir())
        folder = root/'CGTools/AssetsManagerForUE/diagnostics'
        folder.mkdir(parents=True, exist_ok=True)
        report = folder/('action-import-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        report.write_text(json.dumps(dict(source=source, skeleton=skeleton, destination=destination,
            reason=reason, traceback=trace, log_file=str(marker[0]) if marker else '',
            log=log, outcome=outcome), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        return reason + u'\n诊断记录：{0}'.format(report)
    except OSError:
        return reason
