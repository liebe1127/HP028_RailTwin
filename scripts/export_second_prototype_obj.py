#!/usr/bin/env python3
"""second-prototype.glb 를 Unity가 읽는 OBJ로 나눈다.

레일은 주행 축(X)을 따라 두고, 대차 몸통은 레일 메시를 뺀 하나다.
모델 +X 가 실물 왼쪽인지는 사진으로 아직 확인하지 않았다.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLB = ROOT / "docs/hardware-digital-twin/model/second-prototype.glb"
OUT = ROOT / "unity/RailTwinRails/Assets/Resources/SecondPrototype"


def mat_mul(a, b):
    out = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = sum(a[i][k] * b[k][j] for k in range(4))
    return out


def mat_vec(m, x, y, z):
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
    )


def trs(translation, rotation, scale):
    tx, ty, tz = translation or (0.0, 0.0, 0.0)
    x, y, z, w = rotation or (0.0, 0.0, 0.0, 1.0)
    sx, sy, sz = scale or (1.0, 1.0, 1.0)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        [sx * (1 - 2 * (yy + zz)), sy * 2 * (xy - wz), sz * 2 * (xz + wy), tx],
        [sx * 2 * (xy + wz), sy * (1 - 2 * (xx + zz)), sz * 2 * (yz - wx), ty],
        [sx * 2 * (xz - wy), sy * 2 * (yz + wx), sz * (1 - 2 * (xx + yy)), tz],
        [0.0, 0.0, 0.0, 1.0],
    ]


IDENT = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
SEGMENT_COUNT = 20


def load_glb(path: Path):
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + json_len])
    bin_off = 20 + json_len
    blob_len = struct.unpack_from("<I", data, bin_off)[0]
    blob = data[bin_off + 8 : bin_off + 8 + blob_len]
    return doc, blob


def read_vec3(doc, blob, accessor_index):
    acc = doc["accessors"][accessor_index]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    count = acc["count"]
    stride = view.get("byteStride", 12)
    out = []
    for i in range(count):
        out.append(struct.unpack_from("<fff", blob, start + i * stride))
    return out


def read_indices(doc, blob, accessor_index):
    acc = doc["accessors"][accessor_index]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    count = acc["count"]
    return list(struct.unpack_from("<" + "H" * count, blob, start))


def main():
    doc, blob = load_glb(GLB)
    nodes = doc["nodes"]
    world = [None] * len(nodes)

    def walk(index, parent):
        node = nodes[index]
        local = trs(node.get("translation"), node.get("rotation"), node.get("scale"))
        world[index] = mat_mul(parent, local)
        for child in node.get("children", []):
            walk(child, world[index])

    for root in doc["scenes"][doc["scene"]]["nodes"]:
        walk(root, IDENT)

    # glTF Y-up 에서 주행 축은 Z. 전진(구동륜, Z 감소)이 화면 +X 가 되게 돌린다.
    # scene = (-modelZ, modelY, modelX)
    baked = []
    for index, node in enumerate(nodes):
        mesh_index = node.get("mesh")
        if mesh_index is None:
            continue
        mesh = doc["meshes"][mesh_index]
        for prim in mesh["primitives"]:
            positions = read_vec3(doc, blob, prim["attributes"]["POSITION"])
            indices = read_indices(doc, blob, prim["indices"])
            verts = []
            for px, py, pz in positions:
                wx, wy, wz = mat_vec(world[index], px, py, pz)
                verts.append((-wz, wy, wx))
            name = node.get("name") or mesh.get("name") or f"mesh{mesh_index}"
            is_rail = "Square hollow" in name
            baked.append(
                {
                    "name": name,
                    "material": prim.get("material", 0),
                    "verts": verts,
                    "indices": indices,
                    "rail": is_rail,
                }
            )

    rail_parts = [part for part in baked if part["rail"]]
    if len(rail_parts) != 2:
        raise SystemExit(f"레일 메시가 2개가 아닙니다: {len(rail_parts)}")
    rail_y = []
    rail_x = []
    for part in rail_parts:
        xs = [v[0] for v in part["verts"]]
        ys = [v[1] for v in part["verts"]]
        rail_x.append((min(xs) + max(xs)) * 0.5)
        rail_y.extend(ys)
    shift_x = sum(rail_x) / len(rail_x)
    shift_y = min(rail_y)
    for part in baked:
        part["verts"] = [(x - shift_x, y - shift_y, z) for x, y, z in part["verts"]]

    rail_segments = []
    for part in rail_parts:
        zs = [v[2] for v in part["verts"]]
        prefix = "RailLeft" if sum(zs) / len(zs) >= 0 else "RailRight"
        rail_segments.extend(split_rail(part, prefix))
    if len(rail_segments) != SEGMENT_COUNT * 2:
        raise SystemExit(f"레일 구간이 {SEGMENT_COUNT * 2}개가 아닙니다: {len(rail_segments)}")

    OUT.mkdir(parents=True, exist_ok=True)
    write_obj(OUT / "cart.obj", [part for part in baked if not part["rail"]], doc)
    segment_dir = OUT / "Segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    for part in rail_segments:
        write_obj(segment_dir / f"{part['name']}.obj", [part], doc)
    span = []
    for part in rail_parts:
        xs = [v[0] for v in part["verts"]]
        zs = [v[2] for v in part["verts"]]
        span.append((part["name"], min(xs), max(xs), sum(zs) / len(zs)))
    print("rail spans", span)
    cart = [part for part in baked if not part["rail"]]
    cxs = [v[0] for part in cart for v in part["verts"]]
    print("cart x", min(cxs), max(cxs), "parts", len(cart))


def clip_half(poly, limit, keep_greater):
    if not poly:
        return []
    out = []
    for i, cur in enumerate(poly):
        prev = poly[i - 1]
        prev_in = prev[0] >= limit if keep_greater else prev[0] <= limit
        cur_in = cur[0] >= limit if keep_greater else cur[0] <= limit
        if cur_in:
            if not prev_in:
                out.append(cross(prev, cur, limit))
            out.append(cur)
        elif prev_in:
            out.append(cross(prev, cur, limit))
    return out


def cross(a, b, x):
    dx = b[0] - a[0]
    t = 0.0 if abs(dx) < 1e-9 else (x - a[0]) / dx
    return (x, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def split_rail(part, prefix):
    verts = part["verts"]
    indices = part["indices"]
    xs = [v[0] for v in verts]
    min_x = min(xs)
    span = max(max(xs) - min_x, 1e-6)
    pieces = []
    for i in range(SEGMENT_COUNT):
        x0 = min_x + span * i / SEGMENT_COUNT
        x1 = min_x + span * (i + 1) / SEGMENT_COUNT
        out_verts = []
        out_idx = []
        for t in range(0, len(indices), 3):
            tri = [verts[indices[t]], verts[indices[t + 1]], verts[indices[t + 2]]]
            poly = clip_half(clip_half(tri, x0, True), x1, False)
            if len(poly) < 3:
                continue
            base = len(out_verts)
            out_verts.extend(poly)
            for k in range(1, len(poly) - 1):
                out_idx.extend((base, base + k, base + k + 1))
        if not out_verts:
            raise SystemExit(f"{prefix}_{i:02d} 구간에 삼각형이 없습니다")
        pieces.append(
            {
                "name": f"{prefix}_{i:02d}",
                "material": part["material"],
                "verts": out_verts,
                "indices": out_idx,
                "rail": True,
            }
        )
    return pieces


def write_obj(path: Path, parts, doc):
    materials = doc["materials"]
    lines = ["mtllib " + path.with_suffix(".mtl").name]
    mtl = []
    used = []
    vertex_base = 1
    for part in parts:
        mat = part["material"]
        mat_name = f"mat_{mat}"
        if mat not in used:
            used.append(mat)
            color = materials[mat].get("pbrMetallicRoughness", {}).get(
                "baseColorFactor", [0.7, 0.7, 0.7, 1]
            )
            mtl.append(f"newmtl {mat_name}")
            mtl.append(f"Kd {color[0]:.4f} {color[1]:.4f} {color[2]:.4f}")
            mtl.append("d 1")
        lines.append(f"o {sanitize(part['name'])}_{mat}")
        lines.append(f"usemtl {mat_name}")
        for x, y, z in part["verts"]:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        idx = part["indices"]
        for i in range(0, len(idx), 3):
            a = vertex_base + idx[i]
            b = vertex_base + idx[i + 1]
            c = vertex_base + idx[i + 2]
            lines.append(f"f {a} {b} {c}")
        vertex_base += len(part["verts"])
    path.write_text("\n".join(lines) + "\n")
    path.with_suffix(".mtl").write_text("\n".join(mtl) + "\n")
    print(path.name, "verts groups", len(parts))


def sanitize(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)[:40]


if __name__ == "__main__":
    main()
