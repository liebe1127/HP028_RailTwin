using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

/// <summary>
/// 대시보드 JS가 SendMessage("RailTwin", "ApplyState", json)로 이상 구간을 넣는다.
/// JSON: {"x":45,"len":100,"n":20,"l":[...],"r":[...]}  — x·len은 cm.
/// 보이는 대차는 second-prototype 하나다. 모델 +X 를 화면의 먼 쪽 레일에 두었고,
/// 그 레일에 left 색을 칠한다. 이 좌우 대응은 사진으로 아직 확인하지 않았다.
/// </summary>
public class RailTwinController : MonoBehaviour
{
    public int segmentCount = 20;
    public float railLength = 1.0f;
    public float railGap = 0.28f;

    Transform _marker;
    MeshRenderer[] _left;
    MeshRenderer[] _right;
    float _cartCenterX;
    float _cartWidth;
    bool _prototype;
    bool _orbit;
    Vector3 _orbitFocus;
    float _yaw;
    float _pitch;
    float _distance = 1.4f;
    static Material _sharedUnlit;

    void Awake()
    {
        SetupCamera();
    }

    void Start()
    {
        // ApplyState가 Start보다 먼저 오면 이미 만들어 둔 막대를 다시 만들지 않는다.
        Transform existing = transform.Find("Prototype");
        if (existing != null)
        {
            AdoptPrototype(existing);
        }
        else if (_left == null && !BuildPrototype())
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
            if (_prototype)
            {
                float half = _cartWidth * 0.5f;
                float span = railLength * 0.5f;
                float center = Mathf.Lerp(-span + half, span - half, t);
                _marker.localPosition = new Vector3(center - _cartCenterX, 0f, 0f);
            }
            else
            {
                _marker.localPosition = new Vector3((t - 0.5f) * railLength, 0.08f, 0f);
            }
        }
    }

    void AdoptPrototype(Transform root)
    {
        DestroyNamed("GantryMarker");
        DestroyNamed("RailLeft");
        DestroyNamed("RailRight");
        Transform cart = root.Find("Cart");
        Transform rails = root.Find("RailSource");
        if (cart == null || rails == null)
        {
            return;
        }

        FlattenToUnlit(cart.gameObject);
        _marker = cart;
        _left = CollectRail(rails, "RailLeft_");
        _right = CollectRail(rails, "RailRight_");
        if (_left == null || _right == null)
        {
            return;
        }

        rails.localScale = Vector3.one;
        float minX = float.PositiveInfinity;
        float maxX = float.NegativeInfinity;
        foreach (MeshRenderer renderer in _left)
        {
            MeshFilter filter = renderer.GetComponent<MeshFilter>();
            if (filter == null || filter.sharedMesh == null)
            {
                continue;
            }
            Vector3 a = renderer.transform.TransformPoint(filter.sharedMesh.bounds.min);
            Vector3 b = renderer.transform.TransformPoint(filter.sharedMesh.bounds.max);
            minX = Mathf.Min(minX, Mathf.Min(a.x, b.x));
            maxX = Mathf.Max(maxX, Mathf.Max(a.x, b.x));
        }
        float meshLength = Mathf.Max(0.05f, maxX - minX);
        rails.localScale = new Vector3(railLength / meshLength, 1f, 1f);

        Bounds cartBounds = WorldBounds(cart.gameObject);
        _cartCenterX = cartBounds.center.x - cart.position.x;
        _cartWidth = cartBounds.size.x;
        _prototype = true;
        EnsureLight();
        SetupCamera();
        Camera cam = Camera.main;
        if (cam != null)
        {
            cam.transform.position = new Vector3(0f, 0.38f, -1.35f);
            cam.transform.LookAt(new Vector3(0f, 0.06f, 0f));
            CaptureOrbit(new Vector3(0f, 0.06f, 0f));
        }
    }

    static MeshRenderer[] CollectRail(Transform rails, string prefix)
    {
        var named = new List<Transform>();
        foreach (Transform child in rails)
        {
            if (child.name.StartsWith(prefix))
            {
                named.Add(child);
            }
        }
        named.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
        var found = new List<MeshRenderer>();
        foreach (Transform child in named)
        {
            MeshRenderer renderer = child.GetComponentInChildren<MeshRenderer>(true);
            if (renderer != null)
            {
                found.Add(renderer);
            }
        }
        return found.Count > 0 ? found.ToArray() : null;
    }

    bool BuildPrototype()
    {
        var cartPrefab = Resources.Load<GameObject>("SecondPrototype/cart");
        var segments = Resources.LoadAll<GameObject>("SecondPrototype/Segments");
        if (cartPrefab == null || segments == null || segments.Length == 0)
        {
            return false;
        }

        DestroyNamed("Prototype");
        var root = new GameObject("Prototype");
        root.transform.SetParent(transform, false);
        var cart = Instantiate(cartPrefab, root.transform);
        cart.name = "Cart";
        var rails = new GameObject("RailSource");
        rails.transform.SetParent(root.transform, false);
        foreach (GameObject segment in segments)
        {
            var piece = Instantiate(segment, rails.transform);
            piece.name = segment.name;
        }
        AdoptPrototype(root.transform);
        if (!_prototype)
        {
            DestroyImmediate(root);
            _marker = null;
            return false;
        }
        return true;
    }

    static void FlattenToUnlit(GameObject root)
    {
        foreach (MeshRenderer renderer in root.GetComponentsInChildren<MeshRenderer>())
        {
            Color color = renderer.sharedMaterial != null ? renderer.sharedMaterial.color : new Color(0.75f, 0.75f, 0.78f);
            Tint(renderer, color);
        }
    }

    static Bounds WorldBounds(GameObject root)
    {
        Bounds bounds = new Bounds(root.transform.position, Vector3.zero);
        bool started = false;
        foreach (Renderer renderer in root.GetComponentsInChildren<Renderer>())
        {
            if (!started)
            {
                bounds = renderer.bounds;
                started = true;
            }
            else
            {
                bounds.Encapsulate(renderer.bounds);
            }
        }
        return bounds;
    }

    void RebuildRails()
    {
        Transform existing = transform.Find("Prototype");
        if (existing != null)
        {
            if (!_prototype || _left == null)
            {
                AdoptPrototype(existing);
            }
            return;
        }
        if (!BuildPrototype())
        {
            BuildRails();
        }
    }

    void DestroyNamed(string name)
    {
        DestroyChild(transform, name);
    }

    static void DestroyChild(Transform parent, string name)
    {
        if (parent == null)
        {
            return;
        }
        Transform child = parent.Find(name);
        while (child != null)
        {
            DestroyImmediate(child.gameObject);
            child = parent.Find(name);
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
        CaptureOrbit(Vector3.zero);
    }

    public void OrbitDrag(string csv)
    {
        if (!_orbit || string.IsNullOrEmpty(csv))
        {
            return;
        }
        int comma = csv.IndexOf(',');
        if (comma <= 0)
        {
            return;
        }
        float dx;
        float dy;
        if (!float.TryParse(csv.Substring(0, comma), NumberStyles.Float, CultureInfo.InvariantCulture, out dx))
        {
            return;
        }
        if (!float.TryParse(csv.Substring(comma + 1), NumberStyles.Float, CultureInfo.InvariantCulture, out dy))
        {
            return;
        }
        _yaw += dx * 0.22f;
        _pitch = Mathf.Clamp(_pitch - dy * 0.16f, 6f, 80f);
        ApplyOrbit();
    }

    public void OrbitZoom(string raw)
    {
        if (!_orbit)
        {
            return;
        }
        float factor;
        if (!float.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out factor))
        {
            return;
        }
        _distance = Mathf.Clamp(_distance * factor, 0.4f, 4.5f);
        ApplyOrbit();
    }

    void CaptureOrbit(Vector3 focus)
    {
        Camera cam = Camera.main;
        if (cam == null)
        {
            return;
        }
        _orbitFocus = focus;
        Vector3 offset = cam.transform.position - focus;
        _distance = Mathf.Max(0.4f, offset.magnitude);
        float flat = Mathf.Sqrt(offset.x * offset.x + offset.z * offset.z);
        _pitch = Mathf.Atan2(offset.y, flat) * Mathf.Rad2Deg;
        _yaw = Mathf.Atan2(offset.x, offset.z) * Mathf.Rad2Deg;
        _orbit = true;
    }

    void ApplyOrbit()
    {
        Camera cam = Camera.main;
        if (cam == null)
        {
            return;
        }
        float yawRad = _yaw * Mathf.Deg2Rad;
        float pitchRad = _pitch * Mathf.Deg2Rad;
        float horizontal = _distance * Mathf.Cos(pitchRad);
        Vector3 offset = new Vector3(
            horizontal * Mathf.Sin(yawRad),
            _distance * Mathf.Sin(pitchRad),
            horizontal * Mathf.Cos(yawRad));
        cam.transform.position = _orbitFocus + offset;
        cam.transform.LookAt(_orbitFocus);
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
