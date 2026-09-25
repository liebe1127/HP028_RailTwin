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
        PlacePrototype(root.transform);
        EditorSceneManager.SaveScene(scene, ScenePath);
        var list = new EditorBuildSettingsScene[]
        {
            new EditorBuildSettingsScene(ScenePath, true),
        };
        EditorBuildSettings.scenes = list;
    }

    static void PlacePrototype(Transform railTwin)
    {
        var cart = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Resources/SecondPrototype/cart.obj");
        string[] segmentGuids = AssetDatabase.FindAssets(
            "t:GameObject",
            new[] { "Assets/Resources/SecondPrototype/Segments" });
        if (cart == null || segmentGuids.Length == 0)
        {
            Debug.LogError("second-prototype OBJ를 불러오지 못했습니다.");
            return;
        }

        var host = new GameObject("Prototype");
        host.transform.SetParent(railTwin, false);
        var cartGo = Object.Instantiate(cart, host.transform);
        cartGo.name = "Cart";
        var railGo = new GameObject("RailSource");
        railGo.transform.SetParent(host.transform, false);
        foreach (string guid in segmentGuids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var segment = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (segment == null)
            {
                continue;
            }
            var piece = Object.Instantiate(segment, railGo.transform);
            piece.name = Path.GetFileNameWithoutExtension(path);
        }
        Debug.Log("second-prototype segments " + railGo.transform.childCount);
    }
}
