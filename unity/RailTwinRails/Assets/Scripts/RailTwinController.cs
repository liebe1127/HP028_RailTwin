using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

/// <summary>
/// 대시보드 JS가 SendMessage("RailTwin", "ApplyState", json)로 이상 구간을 넣는다.
/// JSON: {"x":45,"len":100,"n":20,"wheel":1,"l":[...],"r":[...]}  — x·len은 cm.
/// 레일은 second-prototype의 각파이프(25×25 mm, 60 cm)를 3개 이어 180 cm다.
/// wheel이 1이면 x는 구동바퀴 접점의 레일 위치다. 엔코더 0은 접점 58 cm, 122 cm를 구르면 180 cm.
/// 차체 앞면은 접점보다 2 cm 앞에 있다. len은 엔코더 좌표의 구간 길이고, 색은 58 cm를 더해 칠한다.
/// 보이는 대차는 second-prototype 하나다. 모델 +X 를 화면의 먼 쪽 레일에 두었고,
/// 그 레일에 left 색을 칠한다. 이 좌우 대응은 사진으로 아직 확인하지 않았다.
/// </summary>
public class RailTwinController : MonoBehaviour
{
    const int PipeCount = 3;
    const float PipeLength = 0.6f;
    const float PipeSection = 0.025f;
    const float JointGap = 0.015f;
    const float WheelStartCm = 58f;
    const float NosePastWheelM = 0.02f;

    public int segmentCount = 20;
    public float railLength = PipeCount * PipeLength;
    public float railGap = 0.386f;

    struct RailPiece
    {
        public MeshRenderer Renderer;
        public float AlongM;
    }

    Transform _marker;
    List<RailPiece> _left;
    List<RailPiece> _right;
    float _cartCenterX;
    float _cartWidth;
    bool _prototype;
    bool _orbit;
    Vector3 _orbitFocus;
    float _yaw;
    float _pitch;
    float _distance = 5.2f;
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

    void UsePipeSpec()
    {
        railLength = PipeCount * PipeLength;
    }

    public void ApplyState(string json)
    {
        if (string.IsNullOrEmpty(json))
        {
            return;
        }

        float x = ReadFloat(json, "x");
        bool wheelContact = ReadFloat(json, "wheel") > 0.5f;
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
        segmentCount = Mathf.Max(1, count);
        if (_left == null)
        {
            RebuildRails();
        }
        Paint(_left, left, lengthCm, wheelContact);
        Paint(_right, right, lengthCm, wheelContact);
        PlaceMarker(x, wheelContact);
    }

    void PlaceMarker(float xCm, bool wheelContact)
    {
        if (_marker == null)
        {
            return;
        }

        float start = -railLength * 0.5f;
        if (_prototype && wheelContact)
        {
            float along = Mathf.Clamp(xCm / 100f, 0f, railLength);
            float half = Mathf.Min(_cartWidth * 0.5f, railLength * 0.5f);
            float wheelAhead = Mathf.Max(0f, half - NosePastWheelM);
            float minCenter = half;
            float maxCenter = railLength - half + NosePastWheelM;
            float centerAlong = Mathf.Clamp(along - wheelAhead, minCenter, maxCenter);
            _marker.localPosition = new Vector3(start + centerAlong - _cartCenterX, 0f, 0f);
            return;
        }

        float alongPlain = Mathf.Clamp(xCm / 100f, 0f, railLength);
        if (_prototype)
        {
            float half = Mathf.Min(_cartWidth * 0.5f, railLength * 0.5f);
            float center = Mathf.Clamp(start + alongPlain, start + half, start + railLength - half);
            _marker.localPosition = new Vector3(center - _cartCenterX, 0f, 0f);
            return;
        }

        _marker.localPosition = new Vector3(start + alongPlain, PipeSection + 0.08f, 0f);
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
        UsePipeSpec();
        rails.localScale = Vector3.one;
        LayoutPipeRun(rails);
        _left = CollectPieces(rails, "RailLeft_");
        _right = CollectPieces(rails, "RailRight_");
        if (_left == null || _right == null)
        {
            return;
        }

        EnsureJoints(rails, AverageZ(_left), AverageZ(_right));
        Bounds cartBounds = WorldBounds(cart.gameObject);
        _cartCenterX = cartBounds.center.x - cart.position.x;
        _cartWidth = cartBounds.size.x;
        _prototype = true;
        EnsureLight();
        SetupCamera();
        CaptureOrbit(new Vector3(0f, 0.04f, 0f));
    }

    void LayoutPipeRun(Transform rails)
    {
        if (rails.Find("PipeRun") != null)
        {
            return;
        }

        var originals = new List<Transform>();
        foreach (Transform child in rails)
        {
            originals.Add(child);
        }
        if (originals.Count == 0)
        {
            return;
        }

        var run = new GameObject("PipeRun");
        run.transform.SetParent(rails, false);
        float origin = -railLength * 0.5f;
        float pipeScale = (PipeLength - JointGap) / PipeLength;
        for (int i = 0; i < PipeCount; i++)
        {
            var pipe = new GameObject("Pipe_" + i.ToString("00"));
            pipe.transform.SetParent(run.transform, false);
            pipe.transform.localPosition = new Vector3(origin + (i + 0.5f) * PipeLength, 0f, 0f);
            pipe.transform.localScale = new Vector3(pipeScale, 1f, 1f);
            bool keepOriginal = i == PipeCount - 1;
            foreach (Transform original in originals)
            {
                Transform piece;
                if (keepOriginal)
                {
                    piece = original;
                    piece.SetParent(pipe.transform, false);
                }
                else
                {
                    var copy = Instantiate(original.gameObject, pipe.transform);
                    copy.name = original.name;
                    piece = copy.transform;
                }
                piece.localPosition = Vector3.zero;
                piece.localRotation = Quaternion.identity;
                piece.localScale = Vector3.one;
            }
        }
    }

    void EnsureJoints(Transform rails, float zLeft, float zRight)
    {
        Transform run = rails.Find("PipeRun");
        if (run == null || run.Find("PipeJoint_00") != null)
        {
            return;
        }

        float origin = -railLength * 0.5f;
        float y = PipeSection * 0.5f;
        int index = 0;
        for (int joint = 1; joint < PipeCount; joint++)
        {
            float x = origin + joint * PipeLength;
            MakeJoint(run, x, y, zLeft, index++);
            MakeJoint(run, x, y, zRight, index++);
        }
    }

    static void MakeJoint(Transform parent, float x, float y, float z, int index)
    {
        var band = GameObject.CreatePrimitive(PrimitiveType.Cube);
        band.name = "PipeJoint_" + index.ToString("00");
        band.transform.SetParent(parent, false);
        band.transform.localScale = new Vector3(0.028f, 0.042f, 0.042f);
        band.transform.localPosition = new Vector3(x, y, z);
        var collider = band.GetComponent<Collider>();
        if (collider != null)
        {
            DestroyImmediate(collider);
        }
        Tint(band.GetComponent<MeshRenderer>(), new Color(0.86f, 0.88f, 0.90f));
    }

    List<RailPiece> CollectPieces(Transform rails, string prefix)
    {
        var found = new List<RailPiece>();
        var seen = new HashSet<MeshRenderer>();
        foreach (Transform child in rails.GetComponentsInChildren<Transform>(true))
        {
            if (!child.name.StartsWith(prefix))
            {
                continue;
            }
            MeshRenderer renderer = child.GetComponent<MeshRenderer>();
            if (renderer == null)
            {
                renderer = child.GetComponentInChildren<MeshRenderer>(true);
            }
            if (renderer == null || !seen.Add(renderer))
            {
                continue;
            }
            Vector3 local = transform.InverseTransformPoint(renderer.bounds.center);
            found.Add(new RailPiece
            {
                Renderer = renderer,
                AlongM = local.x + railLength * 0.5f,
            });
        }
        found.Sort((a, b) => a.AlongM.CompareTo(b.AlongM));
        return found.Count > 0 ? found : null;
    }

    static float AverageZ(List<RailPiece> pieces)
    {
        float sum = 0f;
        int count = 0;
        foreach (RailPiece piece in pieces)
        {
            if (piece.Renderer == null)
            {
                continue;
            }
            sum += piece.Renderer.bounds.center.z;
            count++;
        }
        return count > 0 ? sum / count : 0f;
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
        UsePipeSpec();
        _prototype = false;
        _left = MakePipeRail("RailLeft", -railGap * 0.5f);
        _right = MakePipeRail("RailRight", railGap * 0.5f);
        var marker = GameObject.CreatePrimitive(PrimitiveType.Cube);
        marker.name = "GantryMarker";
        marker.transform.SetParent(transform, false);
        marker.transform.localScale = new Vector3(0.05f, 0.16f, railGap + 0.12f);
        Tint(marker.GetComponent<MeshRenderer>(), new Color(0.9f, 0.92f, 0.95f));
        _marker = marker.transform;
        EnsureLight();
        SetupCamera();
        CaptureOrbit(new Vector3(0f, 0.04f, 0f));
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
        _distance = Mathf.Clamp(_distance * factor, 0.8f, 12f);
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

    List<RailPiece> MakePipeRail(string name, float z)
    {
        var root = new GameObject(name);
        root.transform.SetParent(transform, false);
        var pieces = new List<RailPiece>();
        const int slicesPerPipe = 4;
        float slice = PipeLength / slicesPerPipe;
        float origin = -railLength * 0.5f;
        float y = PipeSection * 0.5f;
        for (int i = 0; i < PipeCount; i++)
        {
            for (int s = 0; s < slicesPerPipe; s++)
            {
                float along = i * PipeLength + (s + 0.5f) * slice;
                var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
                cube.name = name + "_" + i.ToString("00") + "_" + s.ToString("00");
                cube.transform.SetParent(root.transform, false);
                cube.transform.localScale = new Vector3(slice - JointGap / slicesPerPipe, PipeSection, PipeSection);
                cube.transform.localPosition = new Vector3(origin + along, y, z);
                var renderer = cube.GetComponent<MeshRenderer>();
                Tint(renderer, RiskColor(0f));
                pieces.Add(new RailPiece { Renderer = renderer, AlongM = along });
            }
            if (i < PipeCount - 1)
            {
                MakeJoint(root.transform, origin + (i + 1) * PipeLength, y, z, i);
            }
        }
        return pieces;
    }

    static void Paint(List<RailPiece> rails, float[] values, float lengthCm, bool wheelContact)
    {
        if (rails == null)
        {
            return;
        }

        int count = values != null ? values.Length : 0;
        float segCm = (count > 0 && lengthCm > 0f) ? lengthCm / count : 0f;
        foreach (RailPiece piece in rails)
        {
            float cm = piece.AlongM * 100f;
            if (wheelContact)
            {
                cm -= WheelStartCm;
            }
            float v = 0f;
            if (count > 0 && segCm > 0f && cm >= 0f && cm < lengthCm)
            {
                int idx = Mathf.Clamp(Mathf.FloorToInt(cm / segCm), 0, count - 1);
                v = Mathf.Clamp01(values[idx]);
            }
            Tint(piece.Renderer, RiskColor(v));
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
        cam.farClipPlane = 40f;
        cam.transform.position = new Vector3(0f, 0.85f, -3.2f);
        cam.transform.LookAt(new Vector3(0f, 0.04f, 0f));
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
