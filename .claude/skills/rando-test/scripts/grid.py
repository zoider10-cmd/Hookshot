"""A grid of a headless run's pictures, to look at in one read.

    py -I grid.py <out.png> [--last 48] [--step 4] [--cols 4] [--crop x0,y0,x1,y1] [--zoom 1.0] [--shots DIR]

Takes the last --last pictures of DIR (default $WORK/shots, $WORK as in run_headless.sh), every --step-th, each cropped
(in the 960x540 picture's pixels) and scaled to fit a cell of 480x270 times --zoom. Needs Pillow.
"""
import argparse
import os
import sys

from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("--last", type=int, default=48)
    p.add_argument("--step", type=int, default=4)
    p.add_argument("--cols", type=int, default=4)
    p.add_argument("--crop")
    p.add_argument("--zoom", type=float, default=1.0)
    p.add_argument("--shots", default=os.path.join(os.environ.get("WORK") or os.path.join(os.environ.get("TEMP", "/tmp"), "rando-test"), "shots"))
    a = p.parse_args()
    names = sorted(n for n in os.listdir(a.shots) if n.endswith(".png"))
    if not names:
        sys.exit("no pictures in %s" % a.shots)
    pick = names[max(0, len(names) - a.last)::a.step]
    box = tuple(int(v) for v in a.crop.split(",")) if a.crop else None
    w, h = int(480 * a.zoom), int(270 * a.zoom)
    if box:
        h = int(w * (box[3] - box[1]) / (box[2] - box[0]))
    rows = (len(pick) + a.cols - 1) // a.cols
    out = Image.new("RGB", (w * a.cols, h * rows))
    for k, n in enumerate(pick):
        im = Image.open(os.path.join(a.shots, n))
        if box:
            im = im.crop(box)
        out.paste(im.resize((w, h)), ((k % a.cols) * w, (k // a.cols) * h))
    out.save(a.out)
    print("%s: %d pictures (%s to %s)" % (a.out, len(pick), pick[0], pick[-1]))


if __name__ == "__main__":
    main()
