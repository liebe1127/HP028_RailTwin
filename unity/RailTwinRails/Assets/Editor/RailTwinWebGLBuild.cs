using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using System.IO;

public static class RailTwinWebGLBuild
{
    const string ScenePath = "Assets/Scenes/RailTwin.unity";

    public static void Build()
    {
        Directory.CreateDirectory("Assets/Scenes");
        EditorUserBuildSettings.SwitchActiveBuildTarget(
            BuildTargetGroup.WebGL,
            BuildTarget.WebGL
        );
        EnsureScene();
        PlayerSettings.productName = "RailTwinRails";
        PlayerSettings.companyName = "RailTwin";
        PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;
        PlayerSettings.WebGL.exceptionSupport = WebGLExceptionSupport.None;
        PlayerSettings.WebGL.template = "APPLICATION:Default";
        var options = new BuildPlayerOptions
        {
            scenes = new[] { ScenePath },
            locationPathName = "Build/WebGL",
            target = BuildTarget.WebGL,
            options = BuildOptions.None,
        };
        var report = BuildPipeline.BuildPlayer(options);
        if (report.summary.result != BuildResult.Succeeded)
        {
            Debug.LogError("WebGL build failed: " + report.summary.result);
            EditorApplication.Exit(1);
            return;
        }
        EditorApplication.Exit(0);
    }

    static void EnsureScene()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        RenderSettings.skybox = null;
        var cam = Camera.main;
        if (cam != null)
        {
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0.02f, 0.04f, 0.08f);
            cam.fieldOfView = 40f;
            cam.transform.position = new Vector3(0f, 0.62f, -1.05f);
            cam.transform.LookAt(Vector3.zero);
        }
        var root = new GameObject("RailTwin");
        root.AddComponent<RailTwinController>();
        EditorSceneManager.SaveScene(scene, ScenePath);
        var list = new EditorBuildSettingsScene[]
        {
            new EditorBuildSettingsScene(ScenePath, true),
        };
        EditorBuildSettings.scenes = list;
    }
}
