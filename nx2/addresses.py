"""The addresses Hookshot's tools send to, from nx2/addresses.ini: kept out of the code, to edit in one place.

    address("perf_reports")   -> "https://data-services.magicbean.dev/telemetry/perf", or "" when it isn't set
"""
import configparser
import os

ADDRESSES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addresses.ini")


def address(key, path=ADDRESSES):
    """A service's address; "" when it isn't there. A BOM (utf-8-sig) is fine, and a file that doesn't parse turns the
    uses off: it never stops the builders"""
    ini = configparser.ConfigParser(interpolation=None)
    try:
        ini.read(path, encoding="utf-8-sig")
        return ini.get("addresses", key, fallback="").strip()
    except (configparser.Error, UnicodeDecodeError):
        return ""
