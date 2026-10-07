"""Generate small original models for manual Local Mesh smoke tests."""
from pathlib import Path
import json
import struct
import zlib

ROOT = Path(__file__).resolve().parents[2]
out = ROOT / ".logs/local-mesh-fixtures"
out.mkdir(parents=True, exist_ok=True)


def model(height=3):
    # Y-up pyramid, split into two material slots, without authored normals.
    vertices = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1), (0, height, 0)]
    indices = [0, 4, 1, 1, 4, 2, 2, 4, 3, 3, 4, 0, 0, 1, 2, 0, 2, 3]
    binary = b"".join(struct.pack("<3f", *v) for v in vertices) + struct.pack("<18H", *indices)
    document = {"asset": {"version": "2.0", "generator": "Prism local mesh test fixture"},
                "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
                "buffers": [{"byteLength": len(binary)}],
                "bufferViews": [{"buffer": 0, "byteLength": 60},
                                {"buffer": 0, "byteOffset": 60, "byteLength": 36}],
                "accessors": [{"bufferView": 0, "componentType": 5126, "count": 5, "type": "VEC3"},
                              {"bufferView": 1, "componentType": 5123, "count": 9, "type": "SCALAR"},
                              {"bufferView": 1, "byteOffset": 18, "componentType": 5123, "count": 9, "type": "SCALAR"}],
                "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [.04, .7, 1, 1], "metallicFactor": 0, "roughnessFactor": .55}, "doubleSided": True},
                              {"pbrMetallicRoughness": {"baseColorFactor": [1, .35, .02, 1], "metallicFactor": 0, "roughnessFactor": .55}}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0},
                                            {"attributes": {"POSITION": 0}, "indices": 2, "material": 1}]}]}
    return document, binary


def glb(document, binary):
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary)) + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + struct.pack("<II", len(binary), 0x004E4942) + binary


doc, data = model()
valid = glb(doc, data)
(out / "pyramid.glb").write_bytes(valid)
(out / "reload.glb").write_bytes(valid)
(out / "taller.glb").write_bytes(glb(*model(6)))
(out / "truncated.glb").write_bytes(valid[:len(valid) // 2])
doc["buffers"][0]["uri"] = "pyramid.bin"
(out / "pyramid.gltf").write_text(json.dumps(doc))
(out / "pyramid.bin").write_bytes(data)
doc["nodes"][0]["children"] = [0]
(out / "cycle.gltf").write_text(json.dumps(doc))


def dae(height=3, axis="Y_UP", meter=1):
    vertices = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1), (0, height, 0)]
    if axis == "Z_UP":
        vertices = [(x, -z, y) for x, y, z in vertices]
    positions = " ".join(str(c / meter) for point in vertices for c in point)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><created>2026-10-04T00:00:00Z</created><modified>2026-10-04T00:00:00Z</modified><unit meter="{meter}"/><up_axis>{axis}</up_axis></asset>
<library_images><image id="checker"><init_from>dae-colors.png</init_from></image></library_images>
<library_effects>
<effect id="cyan"><profile_COMMON><newparam sid="surface"><surface type="2D"><init_from>checker</init_from></surface></newparam><newparam sid="sampler"><sampler2D><source>surface</source></sampler2D></newparam><technique sid="common"><lambert><diffuse><texture texture="sampler" texcoord="UVMap"/></diffuse></lambert></technique></profile_COMMON></effect>
<effect id="orange"><profile_COMMON><technique sid="common"><lambert><diffuse><color>1 .35 .02 1</color></diffuse></lambert></technique></profile_COMMON></effect>
</library_effects>
<library_materials><material id="paint"><instance_effect url="#cyan"/></material><material id="trim"><instance_effect url="#orange"/></material></library_materials>
<library_geometries><geometry id="pyramid" name="pyramid"><mesh>
<source id="pos"><float_array id="pos-data" count="15">{positions}</float_array><technique_common><accessor source="#pos-data" count="5" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="uv"><float_array id="uv-data" count="10">0 0 1 0 1 1 0 1 .5 .5</float_array><technique_common><accessor source="#uv-data" count="5" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
<vertices id="verts"><input semantic="POSITION" source="#pos"/></vertices>
<triangles count="3" material="paint"><input semantic="VERTEX" source="#verts" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><p>0 0 4 4 1 1 1 1 4 4 2 2 2 2 4 4 3 3</p></triangles>
<triangles count="3" material="trim"><input semantic="VERTEX" source="#verts" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><p>3 3 4 4 0 0 0 0 1 1 2 2 0 0 2 2 3 3</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="scene"><node id="node"><translate>0 0 0</translate><instance_geometry url="#pyramid"><bind_material><technique_common><instance_material symbol="paint" target="#paint"/><instance_material symbol="trim" target="#trim"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#scene"/></scene></COLLADA>'''


def png_chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


# Original 2x2 orientation marker, red/green above blue/yellow.
png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
png += png_chunk(b"IDAT", zlib.compress(bytes([0, 255, 0, 0, 0, 255, 0, 0, 0, 0, 255, 255, 255, 0])))
png += png_chunk(b"IEND", b"")
(out / "dae-colors.png").write_bytes(png)
(out / "pyramid.dae").write_text(dae())
(out / "reload.dae").write_text(dae())
(out / "taller.dae").write_text(dae(6))
(out / "z-up-centimeters.dae").write_text(dae(axis="Z_UP", meter=.01))
(out / "broken.dae").write_text("<COLLADA><broken>")
print(out)
