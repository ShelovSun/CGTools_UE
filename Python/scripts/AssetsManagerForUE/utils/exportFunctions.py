# uncompyle6 version 3.7.4
# Python bytecode 3.7 (3394)
# Decompiled from: Python 3.8.6 (tags/v3.8.6:db45529, Sep 23 2020, 15:37:30) [MSC v.1927 32 bit (Intel)]
# Embedded file name: D:\OneMT\AssetsManagerUE4\UE4.26.1\utils\exportFunctions.py
# Compiled at: 2021-02-22 09:31:26
# Size of source mod 2**32: 2633 bytes
import unreal

class ExportFunctions(object):

    def __init__(self):
        pass

    def exportSingleFbxFile(self, fbx_path, foliageExport=False):
        actors = unreal.EditorLevelLibrary.get_all_level_actors()
        static_mesh_actors = unreal.EditorFilterLibrary.by_class(actors, unreal.StaticMeshActor)
        landscape_actors = unreal.EditorFilterLibrary.by_class(actors, unreal.Landscape)
        world = unreal.EditorLevelLibrary.get_editor_world()
        foliage_actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.InstancedFoliageActor)
        for i in landscape_actors:
            static_mesh_actors.append(i)

        if foliageExport:
            for j in foliage_actors:
                static_mesh_actors.append(j)

        actors_list = static_mesh_actors
        if len(actors_list) == 0:
            exit
        export_object = actors_list[0].get_world()
        unreal.EditorLevelLibrary.set_selected_level_actors(actors_list)
        fbx_export_task = self.buildExportTask(export_object, fbx_path, self.buildFbxExportOptions())
        self.executeExportTasks([fbx_export_task])

    def exportSeparateFbxFile(self):
        actors = unreal.EditorLevelLibrary.get_selected_level_actors()
        static_mesh_actors = unreal.EditorFilterLibrary.by_class(actors, unreal.StaticMeshActor)
        landscape_actors = unreal.EditorFilterLibrary.by_class(actors, unreal.Landscape)
        for i in landscape_actors:
            static_mesh_actors.append(i)

        actors_list = static_mesh_actors
        for actor in actors_list:
            export_object = actor.static_mesh_component.static_mesh
            fbx_path = 'D:/Works/20201126/%s.fbx' % actor.get_name()
            fbx_export_task = self.buildExportTask(export_object, fbx_path, self.buildFbxExportOptions())
            self.executeExportTasks([fbx_export_task])

    def executeExportTasks(self, tasks):
        unreal.Exporter.run_asset_export_tasks(tasks)

    def buildExportTask(self, export_object, destination_path, options=None):
        task = unreal.AssetExportTask()
        task.object = export_object
        task.selected = True
        task.filename = destination_path
        task.replace_identical = False
        task.prompt = False
        task.automated = True
        task.options = options
        return task

    def buildFbxExportOptions(self):
        options = unreal.FbxExportOption()
        options.vertex_color = False
        options.collision = False
        options.level_of_detail = False
        return options