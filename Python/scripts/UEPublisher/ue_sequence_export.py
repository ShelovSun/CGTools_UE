import unreal


def get_current_sequence():
    # 获取当前选中的 Level Sequence
    assets = unreal.EditorUtilityLibrary.get_selected_assets()
    for asset in assets:
        if isinstance(asset, unreal.LevelSequence):
            return asset
    unreal.log_warning("没有选中 Level Sequence")
    return None


def get_bound_actors(sequence):
    # 获取 Level Sequence 绑定的所有 Actor
    bindings = sequence.get_bindings()
    selected_actors = []
    for binding in bindings:
        # 你可以使用 binding.get_name() 进行过滤
        for bound_object in sequence.find_bound_objects(binding, unreal.EditorLevelLibrary.get_editor_world()):
            if isinstance(bound_object, unreal.Actor):
                selected_actors.append(bound_object)
    return selected_actors


def bake_and_export(sequence, actors):
    # 获取时间范围
    EXPORT_DIR = "D:/AAA"
    frame_rate = sequence.get_display_rate()
    start_frame = sequence.get_playback_range()[0]
    end_frame = sequence.get_playback_range()[1]

    start_time = unreal.SequencerScriptingRangeHandles.get_lower_bound_value(start_frame)
    end_time = unreal.SequencerScriptingRangeHandles.get_upper_bound_value(end_frame)

    # 转换为帧数
    start_frame_num = unreal.convert_frame_time_to_seconds(start_time, frame_rate) * frame_rate.numerator
    end_frame_num = unreal.convert_frame_time_to_seconds(end_time, frame_rate) * frame_rate.numerator

    # 配置 bake 设置
    bake_settings = unreal.MovieSceneBakeSettings()
    bake_settings.reduce_keys = False
    bake_settings.keep_current_transform = True
    bake_settings.remove_transform_tracks = False
    bake_settings.call_post_edit_change = True
    bake_settings.recreate_actor = False

    for actor in actors:
        unreal.log(f"Baking Actor: {actor.get_name()}")

        # bake transform
        unreal.SequencerTools.bake_transform_for_actor(
            sequence=sequence,
            actor=actor,
            bake_settings=bake_settings,
            start_frame=int(start_frame_num),
            end_frame=int(end_frame_num),
            frame_rate=frame_rate
        )

        # 导出 FBX
        export_path = f"{EXPORT_DIR}/{actor.get_name()}.fbx"

        export_options = unreal.FbxExportOption()
        export_options.ascii = False
        export_options.level_of_detail = False
        export_options.vertex_color = True
        export_options.map_skeletal_motion_to_root = False
        export_options.export_local_time = False
        export_options.export_preview_mesh = True
        export_options.force_front_x_axis = False
        export_options.export_transforms = True
        export_options.export_animation = True
        export_options.level = None
        export_options.bake_space = unreal.FbxExportBakeSpace.DEFAULT
        export_options.automated = True

        success = unreal.Exporter.run_asset_export_task(
            unreal.AssetExportTask(
                object=actor,
                filename=export_path,
                automated=True,
                options=export_options,
                prompt=False
            )
        )
        if success:
            unreal.log(f"导出成功: {export_path}")
        else:
            unreal.log_warning(f"导出失败: {export_path}")


def bake_anim(sequence):
    frame_rate = sequence.get_display_rate()
    start_frame = sequence.get_playback_range().get_start_frame()
    end_frame = sequence.get_playback_range().get_end_frame()

    # start_time = unreal.SequencerScriptingRangeHandles.get_lower_bound_value(start_frame)
    # end_time = unreal.SequencerScriptingRangeHandles.get_upper_bound_value(end_frame)

    # 转换为帧数
    # start_frame_num = unreal.convert_frame_time_to_seconds(start_time, frame_rate) * frame_rate.numerator
    # end_frame_num = unreal.convert_frame_time_to_seconds(end_time, frame_rate) * frame_rate.numerator
    settings = unreal.BakingAnimationKeySettings(start_frame=unreal.FrameNumber(start_frame),
                                                 end_frame=unreal.FrameNumber(end_frame),
                                                 baking_key_settings=unreal.BakingKeySettings.ALL_FRAMES)
    unreal.bake_transform_with_settings(object_bindings=sequence.get_bindings(),
                                        settings=settings)


def do_it():
    sequence = get_current_sequence()
    if not sequence:
        unreal.log_warning("没有找到Sequence ")
        return

    bake_anim(sequence)

    # actors = get_bound_actors(sequence)
    # if not actors:
    #     unreal.log_warning("没有找到绑定的 Actor")
    #     return
    #
    # bake_and_export(sequence, actors)

