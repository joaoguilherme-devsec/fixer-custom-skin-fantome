"""Locate the League of Legends 'Game' folder."""
import configparser
import os
import re

CHAMPIONS_SUBDIR = os.path.join("DATA", "FINAL", "Champions")
DEFAULT_GAME_DIR = r"C:\Riot Games\League of Legends\Game"
RIOT_SETTINGS = (r"C:\ProgramData\Riot Games\Metadata\league_of_legends.live"
                 r"\league_of_legends.live.product_settings.yaml")


def normalize(path):
    """Accept either '<...>/League of Legends' or '<...>/League of Legends/Game'.

    Returns the Game folder, or None when it is not a valid install.
    """
    if not path:
        return None
    path = os.path.normpath(path.strip().strip('"'))
    for cand in (path, os.path.join(path, "Game")):
        if os.path.isdir(os.path.join(cand, CHAMPIONS_SUBDIR)):
            return cand
    return None


def _from_rose():
    ini = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Rose", "config.ini")
    if not os.path.isfile(ini):
        return None
    cp = configparser.ConfigParser()
    try:
        cp.read(ini, encoding="utf-8")
        return cp.get("General", "leaguepath", fallback=None)
    except configparser.Error:
        return None


def _from_riot_client():
    try:
        with open(RIOT_SETTINGS, encoding="utf-8") as f:
            m = re.search(r'product_install_full_path:\s*"?([^"\r\n]+)', f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def detect():
    for cand in (_from_rose(), _from_riot_client(), DEFAULT_GAME_DIR):
        found = normalize(cand)
        if found:
            return found
    return None
