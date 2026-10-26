"""Analyse and repair .fantome custom skins against the installed game.

Since patch 16.21 the game splits skin data into shared bins named
'DATA/Characters/<Champ>/<Champ>_Multi_Skins_*.bin' that every skinN.bin has
to list as a linked file (the older 'DATA/<Champ>_Skins_*.bin' files are
gone). Mods built before that patch keep the old link list, so the data
living in the new shared bins is never loaded and the game aborts while
loading with 'FATAL ERROR. Missing data: 0x0'.

For every .bin inside a mod WAD this module:
  * removes linked files that exist neither in the mod nor in the game;
  * adds the links the game's own copy of that bin has now;
  * appends entries the game's copy has and the mod's copy lacks.
A champion root bin (data/characters/<c>/<c>.bin) that is missing entries
the game has is replaced by the game's current copy plus the entries only
the mod defines.
"""
import os
import re
import shutil
import tempfile
import zipfile

from .binfile import BIN_MAGICS, BinFile
from .gamepath import CHAMPIONS_SUBDIR
from .wad import Wad, WadError, path_hash

LINK_CHAR_RE = re.compile(r"^data/characters/([^/]+)/", re.I)


class GameData:
    """Index of the game's WAD files, looked up by file name."""

    def __init__(self, game_dir):
        self.game_dir = game_dir
        self.index = {}
        final = os.path.join(game_dir, "DATA", "FINAL")
        for root, _, files in os.walk(final):
            for f in files:
                if f.lower().endswith(".wad.client"):
                    self.index.setdefault(f.lower(), os.path.join(root, f))
        if not any(p.startswith(os.path.join(game_dir, CHAMPIONS_SUBDIR)) for p in self.index.values()):
            raise FileNotFoundError("pasta do jogo inválida: %s" % game_dir)
        self._cache = {}

    def wad(self, name):
        key = os.path.basename(name).lower()
        if key not in self._cache:
            p = self.index.get(key)
            self._cache[key] = Wad.from_file(p) if p else None
        return self._cache[key]

    def release(self):
        self._cache.clear()


class WadReport:
    def __init__(self, name):
        self.name = name
        self.game_found = False
        self.bins = 0
        self.bins_changed = 0
        self.links_added = 0
        self.links_removed = 0
        self.entries_added = 0
        self.roots_replaced = []
        self.error = None


class FantomeReport:
    def __init__(self, path):
        self.path = path
        self.wads = []
        self.output = None
        self.error = None

    @property
    def needs_fix(self):
        return any(w.bins_changed for w in self.wads)

    def summary_lines(self):
        lines = []
        if self.error:
            return ["  ERRO: %s" % self.error]
        for w in self.wads:
            if w.error:
                lines.append("  %s: ERRO: %s" % (w.name, w.error))
                continue
            if not w.game_found:
                lines.append("  %s: WAD não existe no jogo, ignorado" % w.name)
                continue
            lines.append("  %s: %d .bin, %d precisam de ajuste" % (w.name, w.bins, w.bins_changed))
            if w.bins_changed:
                lines.append("    links adicionados: %d | links quebrados removidos: %d | entradas adicionadas: %d"
                             % (w.links_added, w.links_removed, w.entries_added))
            for r in w.roots_replaced:
                lines.append("    bin principal desatualizado substituído pela versão atual: %s" % r)
        return lines


def _character_names(wad_name, bins):
    names = {wad_name.split(".")[0].lower()}
    for b in bins:
        for link in b.links:
            m = LINK_CHAR_RE.match(link)
            if m:
                names.add(m.group(1).lower())
    return names


def _fix_bin(mod_bin, game_bin, resolves, root_path, rep):
    """Mutate mod_bin; return True if anything changed."""
    changed = False
    dead = [l for l in mod_bin.links if not resolves(l)]
    links = [l for l in mod_bin.links if resolves(l)]
    added = []
    if game_bin:
        have = {l.lower() for l in links}
        added = [l for l in game_bin.links if l.lower() not in have]
        links = added + links
    if dead or added:
        mod_bin.links = links
        rep.links_added += len(added)
        rep.links_removed += len(dead)
        changed = True

    if game_bin:
        mod_hashes = {e[1] for e in mod_bin.entries}
        game_only = [e for e in game_bin.entries if e[1] not in mod_hashes]
        if game_only and root_path:
            game_hashes = {e[1] for e in game_bin.entries}
            mod_only = [e for e in mod_bin.entries if e[1] not in game_hashes]
            extra_links = [l for l in mod_bin.links if l.lower() not in {g.lower() for g in game_bin.links}]
            mod_bin.entries = list(game_bin.entries) + mod_only
            mod_bin.links = list(game_bin.links) + extra_links
            rep.roots_replaced.append(root_path)
            changed = True
        elif game_only:
            mod_bin.entries = mod_bin.entries + game_only
            rep.entries_added += len(game_only)
            changed = True
    return changed


def _process_wad(name, data, game, rep):
    w = Wad(data)
    gw = game.wad(name)
    rep.game_found = gw is not None
    if gw is None:
        return None

    bins = {}
    for h, e in w.entries.items():
        if e.size >= 8 and w.read(h, limit=4) in BIN_MAGICS:
            bins[h] = BinFile(w.read(h))
    rep.bins = len(bins)

    roots = {path_hash("data/characters/%s/%s.bin" % (c, c)): "data/characters/%s/%s.bin" % (c, c)
             for c in _character_names(name, bins.values())}
    resolves = lambda link: path_hash(link) in w.entries or path_hash(link) in gw.entries

    replaced = {}
    for h, mb in bins.items():
        gb = BinFile(gw.read(h)) if h in gw.entries and gw.read(h, limit=4) in BIN_MAGICS else None
        if _fix_bin(mb, gb, resolves, roots.get(h), rep):
            replaced[h] = mb.dump()
    rep.bins_changed = len(replaced)
    return w.rebuild(replaced) if replaced else None


def process(path, game, output=None, log=lambda msg: None):
    """Analyse `path`; when `output` is given, write the repaired mod there.

    Returns a FantomeReport. The source file is never modified.
    """
    rep = FantomeReport(path)
    try:
        zin = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        rep.error = "não foi possível abrir o arquivo (%s)" % e
        return rep

    new_wads = {}
    with zin:
        try:
            names = zin.namelist()
            for n in names:
                if not n.lower().endswith(".wad.client"):
                    continue
                wr = WadReport(n)
                rep.wads.append(wr)
                log("  analisando %s..." % n)
                try:
                    new = _process_wad(os.path.basename(n), zin.read(n), game, wr)
                    if new is not None:
                        new_wads[n] = new
                except (WadError, ValueError, zipfile.BadZipFile) as e:
                    wr.error = str(e)
            if not rep.wads:
                rep.error = "nenhum WAD encontrado (o arquivo não parece ser um .fantome)"
                return rep

            if output and new_wads:
                os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
                fd, tmp = tempfile.mkstemp(suffix=".fantome", dir=os.path.dirname(os.path.abspath(output)))
                os.close(fd)
                try:
                    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                        for info in zin.infolist():
                            if info.filename in new_wads:
                                zout.writestr(info.filename, new_wads[info.filename], compress_type=zipfile.ZIP_STORED)
                            elif not info.is_dir():
                                zout.writestr(info.filename, zin.read(info.filename))
                    os.replace(tmp, output)
                    rep.output = output
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
        except zipfile.BadZipFile as e:
            rep.error = "arquivo corrompido (%s)" % e
        finally:
            game.release()
    return rep


def fix_in_place(path, game, log=lambda msg: None):
    """Repair `path` itself, keeping the original as '<path>.bak'."""
    fd, tmp = tempfile.mkstemp(suffix=".fantome", dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    os.remove(tmp)
    rep = process(path, game, output=tmp, log=log)
    if rep.output:
        backup = path + ".bak"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        os.replace(tmp, path)
        rep.output = path
    return rep
