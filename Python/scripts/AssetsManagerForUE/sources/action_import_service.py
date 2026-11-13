"""Validate this import task's actual outputs, then save even after native warnings."""
import traceback
from . import action_import_diagnostics as diagnostics


def import_animation(source, skeleton, destination, engine, factory):
    task = factory.buildImportTask(source, destination, factory.buildAnimationImportOptions(skeleton))
    marker = diagnostics._log_marker(engine)
    native_error = None
    try:
        factory.executeImportTasks([task])
    except Exception as exc:
        # Interchange may finish and populate the task before its Python wrapper
        # raises. An exception alone cannot say whether the animation was made.
        native_error = exc
    trace = ''.join(traceback.format_exception(type(native_error), native_error, native_error.__traceback__)) if native_error else ''
    log = diagnostics._log_delta(marker)
    warning = diagnostics._reason(trace + '\n' + log, native_error) if native_error else ''

    objects = {obj.get_path_name(): obj for obj in task.get_objects() if obj is not None}
    for path in task.get_editor_property('imported_object_paths'):
        if path not in objects:
            obj = engine.load_asset(path)
            if obj is not None:
                objects[path] = obj
    outputs = []
    unsaved = []
    for path, obj in objects.items():
        kind = obj.get_class().get_name()
        if kind == 'SkeletalMesh':
            engine.EditorAssetLibrary.delete_asset(path)
            continue
        if kind != 'AnimSequence':
            continue
        actual_skeleton = obj.get_editor_property('skeleton')
        if actual_skeleton is None or actual_skeleton.get_path_name().split('.')[0] != skeleton.split('.')[0]:
            raise RuntimeError(u'动画已生成，但目标骨架校验失败：{0}\n要求骨架：{1}'.format(path, skeleton))
        keys = engine.AnimationLibrary.get_num_keys(obj)
        if keys < 1:
            raise RuntimeError(u'动画已生成，但没有有效关键帧：{0}'.format(path))
        entry = dict(path=path, skeleton=actual_skeleton.get_path_name(), keys=keys, saved=False)
        outputs.append(entry)
        try:
            engine.AnimationLibrary.set_is_root_motion_lock_forced(obj, True)
            if not engine.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False):
                raise RuntimeError(u'保存动作失败：{0}'.format(path))
            entry['saved'] = True
        except Exception as exc:
            unsaved.append(u'{0}\n{1}'.format(path, exc))
    if not outputs:
        # Never claim success just because an older same-name asset exists.
        # Only current-task objects/paths count as proof of this operation.
        if native_error is not None:
            raise RuntimeError(u'本次导入任务未返回动画输出，无法确认导入成功。\n{0}'.format(warning)) from native_error
        raise RuntimeError(u'导入动作未生成动画序列：{0}'.format(source))
    state = 'unsaved' if unsaved else ('warning' if warning else 'succeeded')
    if unsaved:
        message = u'动画已生成/更新，但未保存成功：\n' + '\n'.join(unsaved)
        if warning:
            message += '\n' + warning
    elif warning:
        message = u'已导入并保存（有警告）：\n' + warning
    else:
        message = u'已导入并保存：{0}'.format(source)
    outcome = dict(state=state, message=message, outputs=outputs)
    if state != 'succeeded':
        outcome['message'] = diagnostics.record(source, skeleton, destination, message, trace, log, marker, dict(outcome))
    return outcome
