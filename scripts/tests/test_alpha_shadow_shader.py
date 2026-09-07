"""Syntax-check shared alpha shader permutations with glslangValidator on PATH.

Run: python scripts/tests/test_alpha_shadow_shader.py
This validates GLSL permutations, not driver linking, visuals, or performance.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    validator = shutil.which("glslangValidator")
    if validator is None:
        raise SystemExit("glslangValidator must be on PATH")
    root = Path(__file__).resolve().parents[2]
    source = (root / "indra/newview/app_settings/shaders/class2/deferred/alphaF.glsl").read_text()
    variants = {
        "indexed": ["USE_INDEXED_TEX", "USE_VERTEX_COLOR", "HAS_ALPHA_MASK"],
        "skinned": ["USE_INDEXED_TEX", "USE_VERTEX_COLOR", "HAS_ALPHA_MASK", "HAS_SKIN"],
        "avatar": ["USE_DIFFUSE_TEX", "IS_AVATAR_SKIN"],
        "impostor": ["USE_INDEXED_TEX", "USE_VERTEX_COLOR", "FOR_IMPOSTOR"],
        "hud": ["USE_INDEXED_TEX", "USE_VERTEX_COLOR", "IS_HUD"],
    }
    checks = 0
    with tempfile.TemporaryDirectory(prefix="boxxy-alpha-shader-") as directory:
        shader = Path(directory) / "alpha.frag"
        for name, defines in variants.items():
            for shadows in (False, True):
                for exact_oit in (False, True) if name in ("indexed", "skinned") else (False,):
                    flags = defines + (["HAS_SUN_SHADOW"] if shadows else [])
                    flags += ["EXACT_OIT"] if exact_oit else []
                    preamble = "#version 430 core\nvec4 diffuseLookup(vec2 uv);\n"
                    preamble += "".join(f"#define {flag} 1\n" for flag in flags)
                    shader.write_text(preamble + source)
                    result = subprocess.run([validator, "-S", "frag", str(shader)],
                                            capture_output=True, text=True)
                    if result.returncode:
                        raise SystemExit(f"{name}: {flags}\n{result.stdout}{result.stderr}")
                    checks += 1
    print(f"Passed {checks} alpha shader syntax checks")


if __name__ == "__main__":
    main()
