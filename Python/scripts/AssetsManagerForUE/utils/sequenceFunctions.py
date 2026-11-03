#!/usr/bin/env python
# -*- coding: utf-8 -*-
# <sequenceFunctions> Created: 19/03/2021 by Sunxh<175702994@qq.com>
# log:

import unreal

def getOrAddPossessableInSequenceAsset(sequence_path='', actor=None):
    sequence_asset = unreal.LevelSequence.cast(unreal.load_asset(sequence_path))
    possessable = sequence_asset.add_possessable(object_to_possess=actor)
    return possessable


def addSkeletalAnimationTrackOnPossessable(animation_path='', possessable=None):
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


def getOrAddSpawnableInSequenceAsset(sequence_path='', actor=None):
    sequence_asset = unreal.LevelSequence.cast(unreal.load_asset(sequence_path))
    sequence_asset.set_playback_start(101)
    sequence_asset.set_view_range_start(3.36667)
    sequence_asset.set_work_range_start(3.36667)
    spawnable = sequence_asset.add_spawnable_from_instance(object_to_spawn=actor)
    return spawnable


def addSkeletalAnimationTrackOnSpawnable(animation_path='', spawnable=None):
    animation_asset = unreal.AnimSequence.cast(unreal.load_asset(animation_path))
    params = unreal.MovieSceneSkeletalAnimationParams()
    params.set_editor_property('Animation', animation_asset)
    animation_track = spawnable.add_track(track_type=unreal.MovieSceneSkeletalAnimationTrack)
    animation_section = animation_track.add_section()
    animation_section.set_editor_property('Params', params)
    animation_section.set_range(101, animation_asset.sequence_length * 30 + 101)


def addSkeletalAnimationTrack(sequence_path, animation_path):
    asset_obj = unreal.load_asset(animation_path)
    spawnable_in_sequence = getOrAddSpawnableInSequenceAsset(sequence_path, asset_obj)
    addSkeletalAnimationTrackOnSpawnable(animation_path, spawnable_in_sequence)


def addCamera(sequence_path, fbx_path):
    seq_asset_LevelSequence = unreal.LevelSequence.cast(unreal.load_asset(sequence_path))
    camera_name = fbx_path.rsplit('/', 1)[1].split('.')[0]
    createCamera(seq_asset_LevelSequence, fbx_path, fbxCamName=camera_name)


def addCamera_EXAMPLE():
    seq_asset_LevelSequence = unreal.LevelSequence.cast(unreal.load_asset('/Game/Project/MeiNvTaFang/Animations/S01.S01'))
    import_filename = 'Y:/Onemt/Marketing/BOE/Project/20201019_MeiNvTaFang/Ani/AniCamera/BOE_MeiNvTaFang_S01/Cam01_101_200.fbx'
    camera_name = import_filename.rsplit('/', 1)[1].split('.')[0]
    createCamera(seq_asset_LevelSequence, import_filename, fbxCamName=camera_name)


def createCamera(levelSequence, cameraPath, fbxCamName='GuanYJ_Camera'):
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
    cam = unreal.SequencerTools.import_fbx(world, levelSequence, [binding], import_setting, cameraPath)