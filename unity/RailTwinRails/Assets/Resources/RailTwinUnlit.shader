Shader "RailTwin/UnlitColor"
{
    Properties
    {
        _Color ("Color", Color) = (0.23, 0.51, 0.96, 1)
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        Pass
        {
            Lighting Off
            ZWrite On
            Cull Back
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            fixed4 _Color;
            float4 vert(float4 vertex : POSITION) : SV_POSITION
            {
                return UnityObjectToClipPos(vertex);
            }
            fixed4 frag() : SV_Target
            {
                return _Color;
            }
            ENDCG
        }
    }
    Fallback "Legacy Shaders/VertexLit"
}
