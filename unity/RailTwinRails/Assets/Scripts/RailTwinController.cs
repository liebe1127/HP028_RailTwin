using UnityEngine;

/// <summary>
/// 대시보드 JS가 SendMessage("RailTwin", "ApplyState", json)로 이상 구간을 넣는다.
/// JSON: {"x":45,"len":100,"n":20,"l":[...],"r":[...]}  — x·len은 cm. 레일만, 크레인 메시 없음.
/// </summary>
public class RailTwinController : MonoBehaviour
{
    public int segmentCount = 20;
    public float railLength = 1.0f;
    public float railGap = 0.28f;

    Transform _marker;
    MeshRenderer[] _left;
    MeshRenderer[] _right;
    static Material _sharedUnlit;

    void Awake()
    {
        SetupCamera();
    }

    void Start()
    {
        // ApplyState가 Start보다 먼저 오면 이미 만들어 둔 막대를 다시 만들지 않는다.
        if (_left == null)
        {
            BuildRails();
        }
    }

    public void ApplyState(string json)
    {
        if (string.IsNullOrEmpty(json))
        {
            return;
        }

        float x = ReadFloat(json, "x");
        float lengthCm = ReadFloat(json, "len");
        if (lengthCm <= 0f)
        {
            lengthCm = 100f;
        }
        float[] left = ReadArray(json, "l");
        float[] right = ReadArray(json, "r");
        int count = Mathf.RoundToInt(ReadFloat(json, "n"));
        if (count <= 0)
        {
            count = left.Length > 0 ? left.Length : segmentCount;
        }
        if (_left == null || count != segmentCount)
        {
            segmentCount = Mathf.Max(1, count);
            RebuildRails();
        }
        Paint(_left, left);
        Paint(_right, right);
        if (_marker != null)
        {
            float t = Mathf.Clamp01(x / lengthCm);
            _marker.localPosition = new Vector3((t - 0.5f) * railLength, 0.08f, 0f);
        }
    }

    void RebuildRails()
    {
        BuildRails();
    }

    void DestroyNamed(string name)
    {
        Transform child = transform.Find(name);
        while (child != null)
        {
            DestroyImmediate(child.gameObject);
            child = transform.Find(name);
        }
    }

    void BuildRails()
    {
        DestroyNamed("RailLeft");
        DestroyNamed("RailRight");
        DestroyNamed("GantryMarker");
        _left = MakeRail("RailLeft", -railGap * 0.5f);
        _right = MakeRail("RailRight", railGap * 0.5f);
        var marker = GameObject.CreatePrimitive(PrimitiveType.Cube);
        marker.name = "GantryMarker";
        marker.transform.SetParent(transform, false);
        marker.transform.localScale = new Vector3(0.05f, 0.16f, railGap + 0.12f);
        Tint(marker.GetComponent<MeshRenderer>(), new Color(0.9f, 0.92f, 0.95f));
        _marker = marker.transform;
        EnsureLight();
        SetupCamera();
    }

    MeshRenderer[] MakeRail(string name, float z)
    {
        var root = new GameObject(name);
        root.transform.SetParent(transform, false);
        var renderers = new MeshRenderer[segmentCount];
        float seg = railLength / segmentCount;
        for (int i = 0; i < segmentCount; i++)
        {
            var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cube.name = name + "_" + i;
            cube.transform.SetParent(root.transform, false);
            cube.transform.localScale = new Vector3(seg * 0.88f, 0.045f, 0.09f);
            float x = -railLength * 0.5f + (i + 0.5f) * seg;
            cube.transform.localPosition = new Vector3(x, 0f, z);
            var renderer = cube.GetComponent<MeshRenderer>();
            Tint(renderer, RiskColor(0f));
            renderers[i] = renderer;
        }
        return renderers;
    }

    static void Paint(MeshRenderer[] rails, float[] values)
    {
        if (rails == null)
        {
            return;
        }

        for (int i = 0; i < rails.Length; i++)
        {
            float v = (values != null && i < values.Length) ? Mathf.Clamp01(values[i]) : 0f;
            Tint(rails[i], RiskColor(v));
        }
    }

    static Color RiskColor(float r)
    {
        if (r < 0.3f)
        {
            return new Color(0.13f, 0.77f, 0.37f);
        }
        if (r < 0.8f)
        {
            return new Color(0.92f, 0.70f, 0.03f);
        }
        return new Color(0.94f, 0.27f, 0.27f);
    }

    static void SetupCamera()
    {
        RenderSettings.skybox = null;
        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(0.55f, 0.58f, 0.62f);
        Camera cam = Camera.main;
        if (cam == null)
        {
            cam = FindAnyObjectByType<Camera>();
        }
        if (cam == null)
        {
            return;
        }

        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.02f, 0.04f, 0.08f);
        cam.fieldOfView = 40f;
        cam.nearClipPlane = 0.05f;
        cam.farClipPlane = 20f;
        cam.transform.position = new Vector3(0f, 0.62f, -1.05f);
        cam.transform.LookAt(new Vector3(0f, 0f, 0f));
    }

    static void EnsureLight()
    {
        Light existing = FindAnyObjectByType<Light>();
        if (existing != null)
        {
            existing.intensity = Mathf.Max(existing.intensity, 1.2f);
            return;
        }

        var lightGo = new GameObject("FillLight");
        var light = lightGo.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.35f;
        light.color = Color.white;
        lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
    }

    static void Tint(MeshRenderer renderer, Color color)
    {
        if (renderer == null)
        {
            return;
        }

        if (renderer.sharedMaterial == null || renderer.sharedMaterial.shader == null
            || renderer.sharedMaterial.shader.name != "RailTwin/UnlitColor")
        {
            renderer.sharedMaterial = UnlitMaterial();
        }
        renderer.material.SetColor("_Color", color);
        renderer.material.color = color;
    }

    static Material UnlitMaterial()
    {
        if (_sharedUnlit != null)
        {
            return new Material(_sharedUnlit);
        }

        var shader = Shader.Find("RailTwin/UnlitColor");
        if (shader == null)
        {
            shader = Shader.Find("Unlit/Color");
        }
        if (shader == null)
        {
            shader = Shader.Find("Legacy Shaders/Diffuse");
        }
        if (shader == null)
        {
            shader = Shader.Find("Sprites/Default");
        }
        _sharedUnlit = shader != null ? new Material(shader) : new Material(Shader.Find("Hidden/InternalErrorShader"));
        return new Material(_sharedUnlit);
    }

    static float ReadFloat(string json, string key)
    {
        string token = "\"" + key + "\":";
        int i = json.IndexOf(token);
        if (i < 0)
        {
            return 0f;
        }
        i += token.Length;
        int j = i;
        while (j < json.Length && "0123456789+-.eE".IndexOf(json[j]) >= 0)
        {
            j++;
        }
        float value;
        return float.TryParse(json.Substring(i, j - i), out value) ? value : 0f;
    }

    static float[] ReadArray(string json, string key)
    {
        string token = "\"" + key + "\":[";
        int i = json.IndexOf(token);
        if (i < 0)
        {
            return new float[0];
        }
        i += token.Length;
        int end = json.IndexOf(']', i);
        if (end < 0)
        {
            return new float[0];
        }
        string body = json.Substring(i, end - i);
        if (string.IsNullOrWhiteSpace(body))
        {
            return new float[0];
        }
        string[] parts = body.Split(',');
        var values = new float[parts.Length];
        for (int p = 0; p < parts.Length; p++)
        {
            float v;
            values[p] = float.TryParse(parts[p].Trim(), out v) ? v : 0f;
        }
        return values;
    }
}
