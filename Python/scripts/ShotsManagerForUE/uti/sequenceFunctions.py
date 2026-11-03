# uncompyle6 version 3.7.4
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.8.6 (tags/v3.8.6:db45529, Sep 23 2020, 15:37:30) [MSC v.1927 32 bit (Intel)]
# Embedded file name: E:\PyCharm\Unreal\utils\sequenceFunctions.py
# Compiled at: 2020-10-28 16:44:11
import unreal

def getOrAddPossessableInSequenceAsset(sequence_path='', actor=None):
    ''''''
    sequence_asset = unreal.LevelSequence.cast(unreal.load_asset(sequence_path))
    possessable = sequence_asset.add_possessable(object_to_possess=actor)
    return possessable


def addSkeletalAnimationTrackOnPossessable(animation_path='', possessable=None):
    ''''''
    animation_asset = unreal.AnimSequence.cast(unreal.load_asset(animation_path))
    params = unreal.MovieSceneSkeletalAnimationParams()
    params.set_editor_property('Animation', animation_asset)
    animation_track = possessable.add_track(track_type=unreal.MovieSceneSkeletalAnimationTrack)
    animation_section = animation_track.add_section()
    animation_section.set_editor_property('Params', params)
    animation_section.set_range_seconds(0, animation_asset.sequence_length)


def addSkeletalAnimationTrackOnActor_EXAMPLE():
    sequence_path = '/Game/Project/GuanYiJieTest/NewLevelSequence.NewLevelSequence'
    animation_path = '/Game/Project/GuanYiJieTest/Animations/S01/BaiPao_hi_rig__BaiPao_ROS_AST_Anim.BaiPao_hi_rig__BaiPao_ROS_AST_Anim'
    world = unreal.EditorLevelLibrary.get_editor_world()
    actor_in_world = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkeletalMeshActor)[0]
    possessable_in_sequence = getOrAddPossessableInSequenceAsset(sequence_path, actor_in_world)
    addSkeletalAnimationTrackOnPossessable(animation_path, possessable_in_sequence)


def addSkeletalAnimationTrack(sequence_path, animation_path):
    '''添加骨骼动画到动画序列里
    sequence_path = /Game/Projects/20211105_ChuBingZhanShi/Animations/C1
    animation_path = /Game/Projects/20211105_ChuBingZhanShi/Animations/C1/20211105_ChuBingZhanShi_C1_MonikaHi_hi_rig.20211105_ChuBingZhanShi_C1_MonikaHi_hi_rig
    '''
    asset_obj = unreal.load_asset(animation_path) #要产生到动画序列的animation_path下的actor
    spawnable_in_sequence,sequence_asset = getOrAddSpawnableInSequenceAsset(sequence_path, asset_obj)
    end_time = addSkeletalAnimationTrackOnSpawnable(animation_path, spawnable_in_sequence)
    sequence_asset.set_playback_end(end_time)

def getOrAddSpawnableInSequenceAsset(sequence_path='', actor=None):
    '''建立sequence_path，有设置actor就加载actor到序列，返回加载的actor名'''
    # sequence_asset = unreal.LevelSequence.cast(unreal.load_asset(sequence_path))
    sequence_asset = unreal.MovieSceneSequence.cast(unreal.load_asset(sequence_path))
    # print("==============================================",sequence_asset)
    sequence_asset.set_playback_start(101) # 序列起始帧
    sequence_asset.set_view_range_start(3.36667)
    sequence_asset.set_work_range_start(3.36667)
    spawnable = sequence_asset.add_spawnable_from_instance(object_to_spawn=actor)
    return spawnable,sequence_asset

def addSkeletalAnimationTrackOnSpawnable(animation_path='', spawnable=None):
    '''
    给seq添加轨道
    :param animation_path:
    :param spawnable: 新产生的actor
    :return:
    '''
    animation_asset = unreal.AnimSequence.cast(unreal.load_asset(animation_path))
    # print("animation_asset=========================",animation_asset.sequence_length)
    params = unreal.MovieSceneSkeletalAnimationParams()
    params.set_editor_property('Animation', animation_asset)
    animation_track = spawnable.add_track(track_type=unreal.MovieSceneSkeletalAnimationTrack)
    '''添加片段'''
    animation_section = animation_track.add_section()
    animation_section.set_editor_property('Params', params)
    end_time = animation_asset.sequence_length * 30 + 101
    animation_section.set_range(101, end_time) #设置动画片段长度为动画长
    '''添加轨道'''
    transform_track = spawnable.add_track(track_type=(unreal.MovieScene3DTransformTrack))
    transform_track.set_property_name_and_path('Transform', 'Transform')
    transform_track.set_editor_property('display_name', 'Transform')
    transform_section = transform_track.add_section()
    transform_section.set_start_frame_bounded(False)
    transform_section.set_end_frame_bounded(False)
    return end_time


def addCamera(sequence_path, fbx_path):
    '''添加相机'''
    seq_asset_LevelSequence = unreal.LevelSequence.cast(unreal.load_asset(sequence_path))
    camera_name = fbx_path.rsplit('/', 1)[1].split('.')[0]
    createSpawnableCamera(seq_asset_LevelSequence, fbx_path, fbxCamName=camera_name)


def addCamera_EXAMPLE():
    seq_asset_LevelSequence = unreal.LevelSequence.cast(unreal.load_asset('/Game/Project/MeiNvTaFang/Animations/S01.S01'))
    import_filename = 'Y:/Onemt/Marketing/BOE/Project/20201019_MeiNvTaFang/Ani/AniCamera/BOE_MeiNvTaFang_S01/Cam01_101_200.fbx'
    camera_name = import_filename.rsplit('/', 1)[1].split('.')[0]
    createPossessableCamera(seq_asset_LevelSequence, import_filename, fbxCamName=camera_name)


def createPossessableCamera(levelSequence, cameraPath, fbxCamName='Sun_Camera'):
    '''创建可控制相机'''
    cine_camera = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector())
    cine_camera.set_actor_label(fbxCamName)
    binding = levelSequence.add_possessable(cine_camera)
    options = cine_camera.get_cine_camera_component()
    possessable = levelSequence.add_possessable(options)
    focus_distance_track = possessable.add_track(track_type=unreal.MovieSceneFloatTrack)
    focal_length_track = possessable.add_track(track_type=unreal.MovieSceneFloatTrack)
    aperture_track = possessable.add_track(track_type=unreal.MovieSceneFloatTrack)
    aperture_track.set_property_name_and_path('Current Aperture', 'CurrentAperture')
    focus_distance_track.set_property_name_and_path('Manual Focus Distance (Focus Settings)', 'FocusSettings.ManualFocusDistance')
    focal_length_track.set_property_name_and_path('Current Focal Length', 'CurrentFocalLength')
    focus_distance_track.add_section()
    focal_length_track.add_section()
    aperture_track.add_section()
    camera_id = unreal.MovieSceneObjectBindingID()
    camera_id.set_editor_property('guid', binding.get_id())
    camera_cut_track = levelSequence.add_master_track(unreal.MovieSceneCameraCutTrack)
    camera_section = camera_cut_track.add_section()
    camera_section.set_range(101, 300)
    camera_section.set_camera_binding_id(camera_id)
    import_setting = unreal.MovieSceneUserImportFBXSettings()
    import_setting.set_editor_property('create_cameras', False)
    import_setting.set_editor_property('force_front_x_axis', False)
    import_setting.set_editor_property('match_by_name_only', True)
    import_setting.set_editor_property('reduce_keys', False)
    import_setting.set_editor_property('reduce_keys_tolerance', 0.001)
    world = unreal.EditorLevelLibrary.get_editor_world()
    cam = unreal.SequencerTools.import_fbx(world, levelSequence, [binding], import_setting, cameraPath)  # UE4.26
    # cam = unreal.SequencerTools.import_level_sequence_fbx(world, levelSequence, [binding], import_setting, cameraPath) #UE4.27


def createSpawnableCamera(levelSequence, cameraPath, fbxCamName='Sun_Camera'):
    '''
    创建可生成相机
    :param levelSequence:
    :param cameraPath: Y:/MCCProject/GOM/Projects/20211105_ChuBingZhanShi/ANI/AniCamera/C1/Cam01_101_250.fbx
    :param fbxCamName:
    :return:
    '''
    cine_camera = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector()) # 在关卡里建立相机
    # print(<Object '/Game/StarterContent/Maps/Minimal_Default.Minimal_Default:PersistentLevel.CineCameraActor_35' (0x0000020B2C42B580) Class 'CineCameraActor'>)
    cine_camera.set_actor_label(fbxCamName) #相机改名
    cine_camera_component = cine_camera.get_cine_camera_component()


    camera_filmback_settings = unreal.CameraFilmbackSettings(sensor_width=35.999928, sensor_height=23.999952) #, sensor_aspect_ratio=1)
    cine_camera_component.set_editor_property('filmback', camera_filmback_settings) #设置关卡相机参数

    camera_focus_settings = unreal.CameraFocusSettings(focus_method=unreal.CameraFocusMethod.DO_NOT_OVERRIDE)
    cine_camera_component.set_editor_property('focus_settings', camera_focus_settings) #设置关卡相机参数

    binding = levelSequence.add_spawnable_from_instance(cine_camera) #在动画序列里建立可生成相机cine_camera
    camera_component_binding = levelSequence.add_possessable(cine_camera_component)  #在动画序列里建立可控制相机cine_camera
    camera_component_binding.set_parent(binding) #可控制相机父给可生成相机

    focus_distance_track = camera_component_binding.add_track(track_type=unreal.MovieSceneFloatTrack) #改camera_component_binding
    focus_distance_track.set_property_name_and_path('ManualFocusDistance', 'FocusSettings.ManualFocusDistance')
    focus_distance_track.set_editor_property('display_name', 'Manual Focus Distance (Focus Settings)')
    focus_distance_section = focus_distance_track.add_section()
    focus_distance_section.set_start_frame_bounded(False)
    focus_distance_section.set_end_frame_bounded(False)
    for channel in focus_distance_section.find_channels_by_type(unreal.MovieSceneScriptingFloatChannel):
        channel.set_default(1000000.0)

    focal_length_track = camera_component_binding.add_track(track_type=unreal.MovieSceneFloatTrack) #改camera_component_binding
    focal_length_track.set_property_name_and_path('CurrentFocalLength', 'CurrentFocalLength')
    focal_length_track.set_editor_property('display_name', 'Current Focal Length')
    focal_length_section = focal_length_track.add_section()
    focal_length_section.set_start_frame_bounded(False)
    focal_length_section.set_end_frame_bounded(False)
    for channel in focal_length_section.find_channels_by_type(unreal.MovieSceneScriptingFloatChannel):
        channel.set_default(35.0)

    aperture_track = camera_component_binding.add_track(track_type=unreal.MovieSceneFloatTrack) #改camera_component_binding
    aperture_track.set_property_name_and_path('CurrentAperture', 'CurrentAperture')
    aperture_track.set_editor_property('display_name', 'Current Aperture')
    aperture_section = aperture_track.add_section()
    aperture_section.set_start_frame_bounded(False)
    aperture_section.set_end_frame_bounded(False)
    for channel in aperture_section.find_channels_by_type(unreal.MovieSceneScriptingFloatChannel):
        channel.set_default(22)

    # camera_id = unreal.MovieSceneObjectBindingID()
    # camera_id.set_editor_property('guid', binding.get_id())
    # camera_cut_track = levelSequence.add_master_track(unreal.MovieSceneCameraCutTrack)
    # camera_section = camera_cut_track.add_section()
    # camera_section.set_range(101, 300)
    # camera_section.set_camera_binding_id(camera_id)
    '''导入相机FBX'''
    import_setting = unreal.MovieSceneUserImportFBXSettings()
    import_setting.set_editor_property('create_cameras', False)
    import_setting.set_editor_property('force_front_x_axis', False)
    import_setting.set_editor_property('match_by_name_only', False) # 发现True会导致Filmback修改
    import_setting.set_editor_property('reduce_keys', False)
    import_setting.set_editor_property('reduce_keys_tolerance', 0.001)
    world = unreal.EditorLevelLibrary.get_editor_world()
    unreal.SequencerTools.import_fbx(world, levelSequence, [binding], import_setting, cameraPath) # UE4.26
    # unreal.SequencerTools.import_level_sequence_fbx(world, levelSequence, [binding], import_setting, cameraPath) # UE4.27
    '''删除关卡里建立的相机'''
    unreal.EditorLevelLibrary().destroy_actor(cine_camera)
    '''删除序列中可控制且没有轨道的物体（Cam01_101_250）'''
    all_bindings = levelSequence.get_possessables()
    for i in all_bindings:
        if i.get_tracks() == []:
            i.remove()
    '''删除大纲中可生成且没有序列的物体(4.26才会有)'''