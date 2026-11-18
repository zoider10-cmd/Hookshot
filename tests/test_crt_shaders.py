"""Game-free contracts for the pinned CRT imports, compute ports and SPIR-V headers.

Checks every imported byte against its pinned SHA-256, the complete adapted filter
math against the upstream sections, defaults/compute ABI, the area-box formula and
its rational reference cases, and the headers' source hashes/notices. No shader
compiler is required by default. --glslang also runs the generator's --check,
compiling all four shaders and comparing same-version SPIR-V. These are source and
compiler checks, not GPU execution or a claim of visual equivalence.

    python -I -B tests/test_crt_shaders.py [--glslang glslangValidator]
"""
import argparse
from fractions import Fraction
import hashlib
import re
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = ROOT / "third_party/crt_shaders"
SHADERS = ROOT / "gpu/vk/shaders"
COMMIT = "2345ee91602a7404d3a1a6a5df6108d7305fdad4"
PINNED = {
    "crt/shaders/crt-lottes.slang": "e382eec413c2acf5d03cce65d447347553032acf2e550826d0142a9c51d559ef",
    "crt/shaders/hyllian/crt-hyllian-fast.slang": "4b8dc17d092440d6e1edd31aaea41165bc491e82e112ddb974f1db2d450be11e",
    "crt/shaders/zfast_crt/zfast_crt_finemask.slang": "0214419beed4c08d991288e90f8a73700fd7da567a454ad2ffe725b3b6eea366",
    "crt/shaders/zfast_crt/zfast_crt_impl.inc": "e1006274577b85f18ed793856b46f92d5cd6f6207a98af398004644006907bf1",
}
NAMES = ("crt_lottes", "crt_hyllian", "crt_zfast", "crt_downsample")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def tokens(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"\s+", "", text)


def same(expected, actual, label):
    require(tokens(expected) == tokens(actual), label + ": differs from the pinned math/declared adapter changes")


def body(text, marker="void main()"):
    start = text.index("{", text.index(marker)) + 1
    end, depth = start, 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end - 1]


def defaults(upstream, adapter, exceptions=()):
    original = dict(re.findall(r'^#pragma parameter (\w+) "[^"]*" ([-0-9.]+)', upstream, re.M))
    fixed = dict(re.findall(r"^const float (\w+) = ([-0-9.]+);", adapter, re.M))
    expected = {key: value for key, value in original.items() if key not in exceptions}
    require(set(expected) == set(fixed), "fixed parameter names differ from the upstream defaults")
    for key, value in expected.items():
        require(Fraction(value) == Fraction(fixed[key]), f"{key}: not the upstream default {value}")


def check_imports():
    manifest = (IMPORTS / "SHA256SUMS").read_text(encoding="utf-8")
    expected = "".join(f"{digest}  {path}\n" for path, digest in PINNED.items())
    require(manifest == expected, "SHA256SUMS does not name exactly the four pinned originals")
    provenance = (IMPORTS / "PROVENANCE.md").read_text(encoding="utf-8")
    require(COMMIT in provenance and "libretro/slang-shaders" in provenance, "provenance lost its upstream commit")
    policy = runpy.run_path(str(ROOT / "scripts/check_third_party.py"))
    require(policy["recorded"](provenance) == policy["tree_hash"](str(ROOT), "crt_shaders"),
            "CRT import tree differs from its provenance under the repository's third-party rule")
    for text in ("Timothy Lottes", "PUBLIC DOMAIN", "Hyllian", "cgwg", "DariusG", "hunterk", "MIT",
                 "Greg Hogan", "SoltanGris42", "GPL-2.0-or-later", "Inigo Quilez", ".gitattributes"):
        require(text in provenance, f"provenance missing {text}")
    present = {p.relative_to(IMPORTS).as_posix() for p in IMPORTS.rglob("*") if p.is_file()}
    require(present == set(PINNED) | {"PROVENANCE.md", "SHA256SUMS", ".gitattributes"},
            "unexpected import or missing packaging file")
    attributes = (IMPORTS / ".gitattributes").read_text(encoding="utf-8")
    require("*.slang -text" in attributes and "*.inc -text" in attributes, "Git must preserve original bytes")
    source = {}
    for path, digest in PINNED.items():
        data = (IMPORTS / path).read_bytes()
        require(hashlib.sha256(data).hexdigest() == digest, f"{path}: changed upstream bytes (including line endings)")
        require(path in provenance and digest in provenance, f"{path}: missing provenance hash/path")
        source[path] = data.decode("utf-8").replace("\r\n", "\n")
    return source


def check_abi(adapter, name):
    code = tokens(adapter)
    require(code.startswith("#version450"), f"{name}: not GLSL 450")
    require("layout(local_size_x=8,local_size_y=8)in;" in code, f"{name}: dispatch is not 8x8")
    sampler = "src" if name == "crt_downsample" else "Source"
    require(f"layout(binding=0)uniformsampler2D{sampler};" in code, f"{name}: missing combined source sampler")
    require("layout(binding=1,rgba8)uniformwriteonlyimage2Ddst;" in code, f"{name}: destination must be write-only RGBA8")
    require(len(re.findall(r"layout\(binding=", code)) == 2, f"{name}: unexpected descriptor")
    require("constivec2pixel=ivec2(gl_GlobalInvocationID.xy);" in code, f"{name}: missing output-pixel coordinates")
    require(not re.search(r"\btexture\s*\(", adapter), f"{name}: compute samples must use explicit LOD 0")
    if name == "crt_downsample":
        require("push_constant" not in code, "downsample must not have push constants")
    else:
        require("layout(push_constant)uniformP{vec4SourceSize;vec4OutputSize;uintstyle;}pc;" in code,
                f"{name}: expected exactly the 36-byte SourceSize/OutputSize/style push ABI")
        require("if(any(greaterThanEqual(pixel,imageSize(dst))))return;" in code, f"{name}: missing dispatch bounds")
        require("vec2vTexCoord=(vec2(pixel)+vec2(0.5))*pc.OutputSize.zw;" in code, f"{name}: missing pixel-centre UVs")


def check_lottes(upstream, adapter):
    notice = upstream[upstream.index("// PUBLIC DOMAIN"):upstream.index("#pragma stage fragment")]
    require(notice in adapter, "Lottes dedication/attribution changed")
    defaults(upstream, adapter, ("warpX", "warpY", "shadowMask"))
    for macro in ("#define warpX (pc.style == 1u ? 0.0 : 0.031)",
                  "#define warpY (pc.style == 1u ? 0.0 : 0.041)",
                  "#define shadowMask (pc.style == 1u ? 2.0 : 1.0)"):
        require(macro in adapter, "Lottes style 1 must be flat grille and style 2 the original curved TV mask")
    require("#define DO_BLOOM 1" in adapter, "Lottes bloom disabled")
    require(not re.search(r"^\s*#define SIMPLE_LINEAR_GAMMA", adapter, re.M), "Lottes default gamma changed")
    original_fragment = upstream[upstream.index("#pragma stage fragment"):]
    expected = original_fragment[original_fragment.index("//Uncomment"):original_fragment.index("void main()")]
    expected = expected.replace("params.", "").replace("global.", "pc.")
    expected = expected.replace("texture(Source,pos.xy)", "textureLod(Source,pos.xy,0.0)")
    actual = adapter[adapter.index("//Uncomment"):adapter.index("void main()")]
    same(expected, actual, "Lottes transfer/filter/beam/bloom/warp/mask functions")
    expected = body(original_fragment).replace("params.", "").replace("global.", "pc.")
    expected = re.sub(r"#ifdef GL_ES.*?#endif", "", expected, flags=re.S)
    expected = expected.replace("FragColor = vec4(ToSrgb(outColor.rgb), 1.0);",
                                "imageStore(dst, pixel, vec4(ToSrgb(outColor.rgb), 1.0));")
    actual = body(adapter)
    same(expected, actual[actual.index("vec2 pos = Warp"):], "Lottes composition")


def check_hyllian(upstream, adapter):
    notice = upstream[upstream.index("/*"):upstream.index("*/") + 2]
    require(notice in adapter, "Hyllian full MIT notice/credits changed")
    defaults(upstream, adapter)
    for macro in ("#define SourceSize pc.SourceSize", "#define TextureSize SourceSize.xy",
                  "#define COMPAT_TEXTURE(tex, coord) textureLod(tex, coord, 0.0)"):
        require(macro in adapter, "Hyllian source sampling contract changed")
    for name in ("GAMMA_IN", "GAMMA_OUT"):
        original = re.search(r"^#define " + name + r"[^\n]*", upstream, re.M).group(0)
        require(original in adapter, f"Hyllian {name} changed")
    for expression in ("vec2 tex_size = vec2(TextureSize.x, TextureSize.y);", "vec2 ps = 1.0/tex_size;",
                       "vTexCoord.xy += ps * vec2(-0.49999, 0.0);"):
        require(tokens(expression) in tokens(body(adapter)), "Hyllian lost its vertex ps/coordinate offset")
    require("TexCoord.xy + ps * vec2(-0.49999, 0.0)" in upstream, "pinned Hyllian vertex formula changed")
    expected = body(upstream[upstream.index("#pragma stage fragment"):])
    expected = expected.replace("vec2 dy = vec2(0.0, ps.y);", "")
    expected = expected.replace("color = GAMMA_IN(color);", "color = max(color, vec3(0.0)); color = GAMMA_IN(color);")
    expected = expected.replace("global.OutputSize", "pc.OutputSize")
    expected = expected.replace("FragColor = vec4(color.r, color.g, color.b, 1.0);",
                                "imageStore(dst, pixel, vec4(color.r, color.g, color.b, 1.0));")
    actual = body(adapter)
    same(expected, actual[actual.index("vec2 dx ="):], "Hyllian cubic/gamma/scanline/dotmask math")


def check_zfast(wrapper, upstream, adapter):
    notice = upstream[:upstream.index("*/") + 2]
    require(notice in adapter, "zfast full GPL notice/credits changed")
    defaults(upstream, adapter)
    require('#include "zfast_crt_impl.inc"' in wrapper, "zfast wrapper no longer includes the pinned implementation")
    for source in (wrapper, adapter):
        require(re.search(r"^#define FINEMASK$", source, re.M), "zfast must select FINEMASK")
    for expression in ("float maskFade = 0.3333*MASK_FADE;", "vec2 invDims = 1.0/pc.SourceSize.xy;"):
        require(tokens(expression) in tokens(body(adapter)), "zfast lost its vertex maskFade/invDims")
    require("maskFade = 0.3333*MASK_FADE;" in upstream and "invDims = 1.0/params.SourceSize.xy;" in upstream,
            "pinned zfast vertex formulas changed")
    expected = body(upstream[upstream.index("#pragma stage fragment"):])
    expected = re.sub(r"#if defined\(BLACK_OUT_BORDER\).*?#endif", "", expected, flags=re.S)
    expected = expected.replace("params.", "pc.").replace("texture(Source, p)", "textureLod(Source, p, 0.0)")
    expected = expected.replace("FragColor.rgb =", "vec3 outColor =")
    expected += "\nimageStore(dst, pixel, vec4(outColor, 1.0));"
    actual = body(adapter)
    same(expected, actual[actual.index("vec2 p ="):], "zfast scaling/finemask/scanline/fade math and opaque alpha")


# The whole box body is pinned here so the reference below describes the shader's
# actual footprint, loop bounds, texelFetch weights and normalization, not a bilinear stand-in.
BOX_BODY = """
    const ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 targetSize = imageSize(dst);
    if (any(greaterThanEqual(pixel, targetSize))) return;
    const ivec2 sourceSize = textureSize(src, 0);
    const vec2 scale = vec2(sourceSize) / vec2(targetSize);
    const vec2 firstEdge = vec2(pixel) * scale;
    const vec2 lastEdge = min(vec2(pixel + ivec2(1)) * scale, vec2(sourceSize));
    const ivec2 first = ivec2(floor(firstEdge));
    const ivec2 end = min(ivec2(ceil(lastEdge)), sourceSize);
    vec3 sum = vec3(0.0);
    for (int y = first.y; y < end.y; ++y) {
        const float wy = max(0.0, min(lastEdge.y, float(y + 1)) - max(firstEdge.y, float(y)));
        for (int x = first.x; x < end.x; ++x) {
            const float wx = max(0.0, min(lastEdge.x, float(x + 1)) - max(firstEdge.x, float(x)));
            sum += texelFetch(src, ivec2(x, y), 0).rgb * (wx * wy);
        }
    }
    const vec2 extent = lastEdge - firstEdge;
    imageStore(dst, pixel, vec4(sum / (extent.x * extent.y), 1.0));
"""


def axis_weights(source, target, pixel):
    first_edge = Fraction(pixel * source, target)
    last_edge = Fraction((pixel + 1) * source, target)
    first = first_edge.numerator // first_edge.denominator
    end = min(-(-last_edge.numerator // last_edge.denominator), source)
    return [(i, max(Fraction(0), min(last_edge, i + 1) - max(first_edge, i)) / (last_edge - first_edge))
            for i in range(first, end)]


def box_reference(source, width, height):
    return [[sum(source[sy][sx] * wx * wy
                 for sy, wy in axis_weights(len(source), height, y)
                 for sx, wx in axis_weights(len(source[0]), width, x))
             for x in range(width)] for y in range(height)]


def check_box(adapter):
    same(BOX_BODY, body(adapter), "area box footprint/weights/normalization")
    require(not re.search(r"\btextureLod\s*\(", adapter), "box filter must use source texels, not bilinear guesses")
    for source in range(1, 10):
        for target in range(1, 13):
            for pixel in range(target):
                weights = axis_weights(source, target, pixel)
                require(all(0 <= i < source and w > 0 for i, w in weights), "box taps outside the source")
                require(sum(w for _, w in weights) == 1, "box weights do not preserve constant colour")
    require(box_reference([[0, 1, 0]], 2, 1) == [[Fraction(1, 3), Fraction(1, 3)]], "noninteger reduction")
    require(box_reference([[0, 1]], 3, 2) == [[0, Fraction(1, 2), 1]] * 2, "source smaller than virtual raster")
    require(box_reference([[0, 0, 0], [0, 1, 0], [0, 0, 0]], 2, 2) == [[Fraction(1, 9)] * 2] * 2,
            "two-dimensional overlap weights")
    require(box_reference([[0, 1, 0], [1, 0, 1]], 1, 3) == [[Fraction(1, 3)], [Fraction(1, 2)], [Fraction(2, 3)]],
            "one shrinking axis and one growing axis")
    require(box_reference([[1]], 5, 7) == [[1] * 5] * 7, "single-texel source")


def check_headers():
    generator = runpy.run_path(str(ROOT / "scripts/crt_shaders.py"))
    require(generator["SHADERS"] == NAMES, "generator shader set changed")
    require(generator["TARGET_ENV"] == "vulkan1.2", "generator target environment changed")
    for name in NAMES:
        comp = SHADERS / (name + ".comp")
        header = comp.with_name(name + "_comp_spv.h")
        body_text = generator["checked_header"](comp, name)
        first = header.read_text(encoding="utf-8").splitlines()[0]
        digest = hashlib.sha256(comp.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        require(first.startswith(f"// {comp.name} sha256 {digest} "), f"{name}: first-line source hash mismatch")
        require(f"-V --target-env vulkan1.2 --vn {name.upper()}_COMP_SPV" in first, f"{name}: generation command changed")
        require(len(generator["words"](body_text, name)) > 20, f"{name}: not a complete SPIR-V module")
        require(generator["generator"](body_text), f"{name}: missing glslang version")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glslang", help="also compile and compare the checked-in SPIR-V through --check")
    args = parser.parse_args()
    source = check_imports()
    ports = {name: (SHADERS / (name + ".comp")).read_text(encoding="utf-8") for name in NAMES}
    for name, adapter in ports.items():
        check_abi(adapter, name)
    check_lottes(source["crt/shaders/crt-lottes.slang"], ports["crt_lottes"])
    check_hyllian(source["crt/shaders/hyllian/crt-hyllian-fast.slang"], ports["crt_hyllian"])
    check_zfast(source["crt/shaders/zfast_crt/zfast_crt_finemask.slang"],
                source["crt/shaders/zfast_crt/zfast_crt_impl.inc"], ports["crt_zfast"])
    check_box(ports["crt_downsample"])
    check_headers()
    print("PASS: four byte-identical CRT imports, provenance, defaults, complete filter math, compute ABI and area-box contracts")
    print("PASS: four checked-in CRT headers name their sources and retain their notices")
    if args.glslang:
        subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/crt_shaders.py"), "--check",
                        "--glslang", args.glslang], check=True)
    else:
        print("CRT compilation not checked (pass --glslang to recompile and compare)")


if __name__ == "__main__":
    main()
