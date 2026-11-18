"""A texel buffer view is only made of a format the device supports as a (uniform or storage) texel buffer
(gpu/vk/vk_texture.cpp texel_buffer_view); where it does not, no view or, without nullDescriptor, a dummy one. Longshot #1244
via HeyListen 00e8805b; the check reads the source (tests/test_texel_buffer_ownership.py runs the branch). No GPU or game.

python -I -B tests/test_texel_buffer_format_support.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    src = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    at = src.index("VkBufferView texel_buffer_view(const nvn_tex* t, const nvn_view* v, bool storage) {")
    body = src[at:at + 4500]
    for need in ("format_props(f).bufferFeatures", "VK_FORMAT_FEATURE_STORAGE_TEXEL_BUFFER_BIT",
                 "VK_FORMAT_FEATURE_UNIFORM_TEXEL_BUFFER_BIT", "dev.null_descriptor ? VK_NULL_HANDLE : dummy_texel_view(f)"):
        if need not in body:
            raise SystemExit("texel_buffer_view lacks: " + need)
    if body.index("bufferFeatures") > body.index("gpu_buffer("):
        raise SystemExit("the support check must come before the buffer is looked up and the view made")
    d = src[src.index("VkBufferView dummy_texel_view(VkFormat f) {"):]
    if "VK_FORMAT_R32_SFLOAT, VK_FORMAT_R32_UINT, VK_FORMAT_R32_SINT" not in d[:1500]:
        raise SystemExit("the dummy view does not cover float, uint and sint")
    print("texel buffer views of unsupported formats are skipped")


if __name__ == "__main__":
    main()
