# uncompyle6 version 3.7.4
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.8.6 (tags/v3.8.6:db45529, Sep 23 2020, 15:37:30) [MSC v.1927 32 bit (Intel)]
# Embedded file name: E:\PyCharm\Unreal\utils\assetFunctions.py
# Compiled at: 2020-11-02 19:49:08
import unreal

static_mesh_fbx = 'Y:\\Onemt\\Marketing\\BOE\\Project\\20210416_GuanYiJieTest\\Ani\\AniFBX\\BOE_GuanYiJieTest_S01\\AiJiBuBing_hi_rig__AiJiBuBing_WOE_AST.fbx'
skeletal_mesh_fbx = 'Y:\\Onemt\\Marketing\\BOE\\Project\\20210416_GuanYiJieTest\\Ani\\AniFBX\\BOE_GuanYiJieTest_S01\\AiJiBuBing_hi_rig__AiJiBuBing_WOE_AST.fbx'
animation_mesh_fbx = 'D:/Works/20200928/AiJiBuBing_WOE_AST.fbx'
skeleton_path = '/Game/Content/Geometry/FBX/AiJiBuBing_Skeleton'
animations_folder = '/Game/Geometry/Animations'


class AssetFunctions(object):

    def __init__(self):
        pass

    def importMyAssets(self):
        static_mesh_task = self.buildImportTask(static_mesh_fbx, '/Game/StaticMeshs',
                                                self.buildStaticMeshImportOptions())
        skeletal_mesh_task = self.buildImportTask(skeletal_mesh_fbx, '/Game/SkeletalMeshs',
                                                  self.buildSkeletalMeshImportOptions())
        animation_mesh_task = self.buildImportTask(animation_mesh_fbx, '/Game/Animations',
                                                   self.buildAnimationImportOptions(skeleton_path))
        self.executeImportTasks([static_mesh_task, skeletal_mesh_task, animation_mesh_task])

    def executeImportTasks(self, tasks):
        """
        执行导入
        """
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
        for task in tasks:
            for path in task.get_editor_property('imported_object_paths'):
                print('Imported: %s' % path)

    def buildImportTask(self, filename, destination_path, options=None):
        """
        建立导入任务
        """
        task = unreal.AssetImportTask()
        task.set_editor_property('automated', True)
        task.set_editor_property('destination_name', '')
        task.set_editor_property('destination_path', destination_path)
        task.set_editor_property('filename', filename)
        task.set_editor_property('replace_existing', True)
        task.set_editor_property('save', False)
        task.set_editor_property('options', options)
        return task

    def buildStaticMeshImportOptions(self):
        """
        建立Static Mesh的options
        """
        options = unreal.FbxImportUI()
        options.set_editor_property('import_mesh', True)
        options.set_editor_property('import_textures', True)
        options.set_editor_property('import_materials', True)
        options.set_editor_property('import_as_skeletal', False)
        options.static_mesh_import_data.set_editor_property('import_translation', unreal.Vector(0.0, 0.0, 0.0))
        options.static_mesh_import_data.set_editor_property('import_rotation', unreal.Rotator(0.0, 0.0, 0.0))
        options.static_mesh_import_data.set_editor_property('import_uniform_scale', 1.0)
        options.static_mesh_import_data.set_editor_property('combine_meshes', True)
        options.static_mesh_import_data.set_editor_property('generate_lightmap_u_vs', True)
        options.static_mesh_import_data.set_editor_property('auto_generate_collision', True)
        return options

    def buildSkeletalMeshImportOptions(self):
        """
        Skeletal Mesh 的options
        """
        options = unreal.FbxImportUI()
        options.set_editor_property('import_mesh', True)
        options.set_editor_property('import_textures', True)
        options.set_editor_property('import_materials', True)
        options.set_editor_property('import_as_skeletal', True)
        options.skeletal_mesh_import_data.set_editor_property('import_translation', unreal.Vector(0.0, 0.0, 0.0))
        options.skeletal_mesh_import_data.set_editor_property('import_rotation', unreal.Rotator(0.0, 0.0, 0.0))
        options.skeletal_mesh_import_data.set_editor_property('import_uniform_scale', 1.0)
        options.skeletal_mesh_import_data.set_editor_property('import_morph_targets', True)
        options.skeletal_mesh_import_data.set_editor_property('update_skeleton_reference_pose', False)
        return options

    def buildAnimationImportOptions(self, skeleton_path):
        """
        Animation 的options
        """
        options = unreal.FbxImportUI()
        options.set_editor_property('import_as_skeletal', True)
        options.skeletal_mesh_import_data.set_editor_property('vertex_color_import_option',
                                                              unreal.VertexColorImportOption.REPLACE)
        options.skeletal_mesh_import_data.set_editor_property('import_morph_targets', True)
        options.skeletal_mesh_import_data.set_editor_property('use_t0_as_ref_pose', True)
        options.skeletal_mesh_import_data.set_editor_property('preserve_smoothing_groups', True)
        options.skeletal_mesh_import_data.set_editor_property('import_meshes_in_bone_hierarchy', True)
        options.skeletal_mesh_import_data.set_editor_property('update_skeleton_reference_pose', False)
        options.skeletal_mesh_import_data.set_editor_property('morph_threshold_position', 0.015)
        options.skeletal_mesh_import_data.set_editor_property('threshold_position', 2e-05)
        options.skeletal_mesh_import_data.set_editor_property('threshold_tangent_normal', 2e-05)
        options.skeletal_mesh_import_data.set_editor_property('threshold_uv', 0.000977)
        options.skeletal_mesh_import_data.set_editor_property('transform_vertex_to_absolute', True)
        options.skeletal_mesh_import_data.set_editor_property('import_translation', unreal.Vector(0.0, 0.0, 0.0))
        options.skeletal_mesh_import_data.set_editor_property('import_rotation', unreal.Rotator(0.0, 0.0, 0.0))
        options.skeletal_mesh_import_data.set_editor_property('import_uniform_scale', 1.0)
        options.set_editor_property('import_mesh', False)
        options.set_editor_property('import_animations', True)
        options.skeleton = unreal.load_asset(skeleton_path)
        options.set_editor_property('import_textures', False)
        options.set_editor_property('import_materials', False)
        options.set_editor_property('create_physics_asset', False)
        options.anim_sequence_import_data.set_editor_property('import_translation', unreal.Vector(0.0, 0.0, 0.0))
        options.anim_sequence_import_data.set_editor_property('import_rotation', unreal.Rotator(0.0, 0.0, 0.0))
        options.anim_sequence_import_data.set_editor_property('import_uniform_scale', 1.0)
        options.anim_sequence_import_data.set_editor_property('animation_length',
                                                              unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME)
        options.anim_sequence_import_data.set_editor_property('import_meshes_in_bone_hierarchy', True)
        options.anim_sequence_import_data.set_editor_property('use_default_sample_rate', False)
        options.anim_sequence_import_data.set_editor_property('import_custom_attribute', True)
        options.anim_sequence_import_data.set_editor_property('delete_existing_custom_attribute_curves', False)
        options.anim_sequence_import_data.set_editor_property('import_bone_tracks', True)
        options.anim_sequence_import_data.set_editor_property('remove_redundant_keys', True)
        options.anim_sequence_import_data.set_editor_property('delete_existing_morph_target_curves', False)
        options.anim_sequence_import_data.set_editor_property('do_not_import_curve_with_zero', True)
        options.anim_sequence_import_data.set_editor_property('preserve_local_transform', False)
        return options

    def get_selected_assets(self):
        utility_base = unreal.GlobalEditorUtilityBase.get_default_object()
        return utility_base.get_selected_assets()

    def createGenericAsset(self, asset_path='', unique_name=True, asset_class=None, asset_factory=None):
        if unique_name:
            asset_path, asset_name = unreal.AssetToolsHelpers.get_asset_tools().create_unique_asset_name(
                base_package_name=asset_path, suffix='')
        if not unreal.EditorAssetLibrary.does_asset_exist(asset_path=asset_path):
            path = asset_path.rsplit('/', 1)[0]
            name = asset_path.rsplit('/', 1)[1]
            return unreal.AssetToolsHelpers.get_asset_tools().create_asset(asset_name=name, package_path=path,
                                                                           asset_class=asset_class,
                                                                           factory=asset_factory)
        return unreal.load_asset(asset_path)

    def createGenericAsset_EXAMPLE(self):
        base_path = '/Game/GenericAssets/'
        generic_assets = [
            [
                base_path + 'sequence', unreal.LevelSequence, unreal.LevelSequenceFactoryNew()],
            [
                base_path + 'material', unreal.Material, unreal.MaterialFactoryNew()],
            [
                base_path + 'world', unreal.World, unreal.WorldFactory()],
            [
                base_path + 'particle_system', unreal.ParticleSystem, unreal.ParticleSystemFactoryNew()],
            [
                base_path + 'paper_flipbook', unreal.PaperFlipbook, unreal.PaperFlipbookFactory()],
            [
                base_path + 'data_table', unreal.DataTable, unreal.DataTableFactory()]]
        for asset in generic_assets:
            print(self.createGenericAsset(asset[0], True, asset[1], asset[2]))
