"""Check that a submission cut into parts (RX_VK_CHUNK, vk_replay.cpp maybe_split) can end a part only right before a plain
draw (no game/GPU required): maybe_split asks for the end (part_end_wanted) and replay() makes it (split_part) before a
NOP_DRAW, NOP_DRAW_IDX or NOP_DRAW_INDIRECT that will be recorded, so no cut leaves a part beginning with a mesh draw or a dispatch. On an
Intel Arc B580 a command buffer that began with mesh draws drew the plain draws after them as exploded triangles (white
shards while moving). RX_VK_SPLIT_BEFORE_DRAW=0 ends a part after its 120th draw or dispatch, as before.

python -I -B tests/test_split_before_draw.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def order(where, text, needles):
    at = -1
    for needle in needles:
        nxt = text.find(needle, at + 1)
        if nxt < 0:
            raise SystemExit(where + " no longer has, in this order: " + needle)
        at = nxt


def main():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")

    # the switch: on by default on Intel, RX_VK_SPLIT_BEFORE_DRAW either way elsewhere
    on = block(replay, "bool part_ends_before_draw() {")
    need("part_ends_before_draw", on, ['getenv("RX_VK_SPLIT_BEFORE_DRAW")', "!env_value_off(e)", "dev.props.vendorID == 0x8086"])

    # maybe_split only asks; the old behaviour (the end at once) is what the switch's off does
    ask = block(replay, "void maybe_split(VkCommandBuffer& cmd) {")
    order("maybe_split", ask, ["++part_work < every", "if (part_ends_before_draw())", "part_end_wanted = true;", "return;",
                               "split_part(cmd);"])
    if "submit_recording" in ask:
        raise SystemExit("maybe_split submits a part itself again: the end belongs to split_part")

    # the end itself: the request is taken back first, and the part is ended and begun as before
    cut = block(replay, "void split_part(VkCommandBuffer& cmd) {")
    order("split_part", cut, ["part_end_wanted = false;", "if (split_off || !rec_cur || rec_parts + 1 >= kMaxParts || dump_on()) return;",
                              "end_pass(cmd);", "memory_end_submission(cmd, rec_cur->part);",
                              "submit_recording(*rec_cur, false);", "begin_recording(rec_cur_value);", "part_work = 0;",
                              "rec_parts++;"])

    # replay(): before the switch on the op, for the three plain draws only, and only one that will be recorded
    loop = block(replay, "void replay(VkCommandBuffer& cmd, NvnState& s, const uint8_t* p, const uint8_t* end")
    order("replay", loop, ["if (!dry && !worker && part_end_wanted &&", "h.op == NOP_DRAW || h.op == NOP_DRAW_IDX || h.op == NOP_DRAW_INDIRECT",
                           "s.render_enabled && !s.raster_discard)", "split_part(cmd);", "switch (h.op) {"])
    head = loop[: loop.index("switch (h.op) {")]
    for op in ("NOP_DRAW_MESH", "NOP_DISPATCH"):
        if op in head[head.index("part_end_wanted") :]:
            raise SystemExit("replay() ends a part before a " + op + ": a part would begin with it")

    # a submission starts with no end asked for (both places a submission's first recording is begun)
    if replay.count("rec_parts = 0, part_work = 0, part_end_wanted = false;") != 2:
        raise SystemExit("a submission's start no longer takes back the part's end asked for in the one before")

    need("docs/development.md", docs, ["`RX_VK_SPLIT_BEFORE_DRAW=0` or `1`"])
    print("ok: a part ends right before a plain draw (RX_VK_SPLIT_BEFORE_DRAW), never before a mesh draw or a dispatch")


if __name__ == "__main__":
    main()
