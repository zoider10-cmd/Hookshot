"""scripts/hardware_report.py's classify and os_of on the answers players write in the issue forms, no forge.

The Steam Deck is the priority hardware, and the reach a fix is scored by (docs/workflow.md) comes from these counts: a Deck must
count as "AMD APU / handheld" however it is written (its Vulkan name "AMD Custom GPU 0932 (RADV VANGOGH)", "Steamdeck"), and an
everyday word in an issue's title ("finally", "really") must not make another card one.

    python -I -B tests/test_hardware_report.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hardware_report  # noqa: E402

CLASSES = [
    # (the GPU field + " " + the title, as main() passes them; vendor and class wanted)
    ("AMD Custom GPU 0932 (RADV VANGOGH) Stutter in Hyrule Field", ("AMD", "AMD APU / handheld")),
    ("AMD Custom GPU 0405 (RADV VANGOGH) Crash at the title", ("AMD", "AMD APU / handheld")),
    ("Steamdeck Steamdeck locked at 6fps in anything but cutscenes", ("AMD", "AMD APU / handheld")),
    ("Steam Deck OLED black screen", ("AMD", "AMD APU / handheld")),
    ("ROG Ally X Device lost in Kokiri", ("AMD", "AMD APU / handheld")),
    ("AMD Radeon RX 7900 XTX Shadows flicker", ("AMD", "RX 7000")),
    ("Intel Arc A770 The game finally crashes at the castle", ("Intel", "Intel")),
    ("Intel UHD 770 Really slow loading", ("Intel", "Intel")),
    ("Intel Arc B580 Audio totally gone after a while", ("Intel", "Intel")),
]
OSES = [
    ("Steamdeck OLED, 16 GB", "Linux / SteamOS"),
    ("Ryzen 7 5800X, 32 GB, Windows 11", "Windows"),
    ("SteamOS 3.7, Steam Deck LCD", "Linux / SteamOS"),
]


def main():
    bad = []
    for text, want in CLASSES:
        got = hardware_report.classify(text)
        print("%s %-60s -> %s" % ("ok  " if got == want else "FAIL", text, got))
        if got != want:
            bad.append(text)
    for text, want in OSES:
        got = hardware_report.os_of(text)
        print("%s %-60s -> %s" % ("ok  " if got == want else "FAIL", text, got))
        if got != want:
            bad.append(text)
    if bad:
        raise SystemExit("hardware_report.py misreads %d answer(s): %s" % (len(bad), "; ".join(bad)))


if __name__ == "__main__":
    main()
