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

Cleanup (on by default, best effort). The loader (cslol mkoverlay, used by
Rose) writes every mod entry into *every* game WAD that holds the same file,
so a mod that ships a whole extracted WAD can force it to rewrite hundreds of
WADs; Rose gives up after 120 s and the skin is not applied. Dropped:
  * entries byte-identical to the game's copy in the mod's own WAD and in
    every other game WAD holding them (files only borrowed from other WADs
    are kept: those WADs are not loaded unless that champion is in the game).
    This never changes what the game loads;
  * item recommendation files (assets/recommendations/items/*.rec): shop
    data present in every champion WAD and never part of a skin. A mod's
    copy is a stale snapshot; without it the game shows its current one;
  * the WAD's own .subchunktoc when no mod entry uses sub-chunks: installed,
    it would replace the game's table for its own chunked entries.
Entries present in more than one WAD of the same mod are never dropped (which
copy wins would then depend on the loader), and identical/lite removal is
skipped if any game WAD could not be indexed.

Lite mode (opt-in) additionally drops the mod's changes to files the game
also keeps in other WADs (maps, other champions). Those force the loader to
rewrite multi-GB map WADs; dropping them keeps only the champion's own WADs,
at the cost of whatever those shared files changed (e.g. a custom model for
a summoned unit that the map WAD also carries).
"""
import os
import re
import shutil
import struct
import tempfile
import zipfile

from .binfile import BIN_MAGICS, BinFile
from .gamepath import CHAMPIONS_SUBDIR
from .wad import HEADER_SIZE_V3, TOC_ENTRY, TYPE_ZSTD_CHUNKED, Wad, path_hash, subchunktoc_hash

LINK_CHAR_RE = re.compile(r"^data/characters/([^/]+)/", re.I)

REC_HASHES = frozenset(
    [path_hash("assets/recommendations/items/item_metadata.rec")]
    + [path_hash("assets/recommendations/items/champion_%d_items.rec" % i) for i in range(1, 1000)])

TOUCHED_WADS_WARNING = 20


def _toc_hashes_from(f):
    head = f.read(HEADER_SIZE_V3 + 4)
    if len(head) < HEADER_SIZE_V3 + 4 or head[:2] != b"RW" or head[2] != 3:
        return ()
    (n,) = struct.unpack_from("<I", head, HEADER_SIZE_V3)
    toc = f.read(n * TOC_ENTRY.size)
    return [struct.unpack_from("<Q", toc, i * TOC_ENTRY.size)[0] for i in range(len(toc) // TOC_ENTRY.size)]


def _toc_hashes(path):
    with open(path, "rb") as f:
        return _toc_hashes_from(f)


class GameData:
    """The game's WAD files: lookup by file name and by contained path hash."""

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
        self._holders = None
        self.unindexed = []  # game WADs that could not be read while indexing
        self._open = {}

    def path_of(self, name):
        return self.index.get(os.path.basename(name).lower())

    def relpath(self, path):
        return os.path.relpath(path, self.game_dir).replace("\\", "/")

    def wad(self, name):
        p = self.path_of(name)
        return self.wad_at(p) if p else None

    def wad_at(self, path):
        if path not in self._open:
            w = Wad.open(path)
            w.load_subchunk_toc(subchunktoc_hash(self.relpath(path)))
            self._open[path] = w
        return self._open[path]

    def holders(self, h):
        """Paths of every game WAD that contains path hash `h`."""
        if self._holders is None:
            self._holders = {}
            for p in self.index.values():
                try:
                    hashes = _toc_hashes(p)
                except (OSError, struct.error):
                    self.unindexed.append(p)
                    continue
                for x in hashes:
                    self._holders.setdefault(x, []).append(p)
        return self._holders.get(h, ())

    def touched_wads(self, mod_wad_name, hashes):
        """Game WADs the loader has to rewrite for a mod WAD holding `hashes`."""
        own = self.path_of(mod_wad_name)
        out = {own} if own and hashes else set()
        for h in hashes:
            out.update(self.holders(h))
        return out

    def release(self):
        for w in self._open.values():
            w.close()
        self._open.clear()


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
        self.removed_identical = 0
        self.removed_identical_bytes = 0
        self.removed_rec = 0
        self.removed_subchunktoc = False
        self.removed_shared = []
        self.touched_before = 0
        self.touched_after = 0
        self.notes = []
        self.error = None

    @property
    def removed(self):
        return (self.removed_identical + self.removed_rec + int(self.removed_subchunktoc)
                + len(self.removed_shared))

    @property
    def changed(self):
        return bool(self.bins_changed or self.removed)


class FantomeReport:
    def __init__(self, path):
        self.path = path
        self.wads = []
        self.output = None
        self.error = None

    @property
    def needs_fix(self):
        return any(w.changed for w in self.wads)

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
            if w.removed:
                parts = []
                if w.removed_identical:
                    parts.append("%d idênticos ao jogo (%.1f MB)" % (w.removed_identical, w.removed_identical_bytes / 1e6))
                if w.removed_rec:
                    parts.append("%d de recomendação de itens" % w.removed_rec)
                if w.removed_subchunktoc:
                    parts.append("subchunktoc")
                if parts:
                    lines.append("    arquivos desnecessários removidos: %s" % ", ".join(parts))
                if w.removed_shared:
                    lines.append("    modo leve: %d alterações em arquivos compartilhados descartadas (WADs: %s)"
                                 % (len(w.removed_shared), ", ".join(sorted({x for _, ws in w.removed_shared for x in ws}))))
            if w.touched_before != w.touched_after:
                lines.append("    WADs do jogo que o loader regrava: %d -> %d" % (w.touched_before, w.touched_after))
            if w.touched_after > TOUCHED_WADS_WARNING:
                lines.append("    ATENÇÃO: o mod altera %d WADs do jogo; o Rose pode estourar o tempo de injeção"
                             % w.touched_after)
            lines.extend("    " + n for n in w.notes)
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


def _unneeded_entries(w, name, gw, game, replaced, multi, rep):
    """Entries the cleanup drops (see the module docstring)."""
    own = game.path_of(name)
    rec = {h for h in w.entries if h in REC_HASHES and h not in multi}
    subtoc = subchunktoc_hash(game.relpath(own))
    sub = set()
    if subtoc in w.entries and subtoc not in multi:
        if any(e.kind == TYPE_ZSTD_CHUNKED for e in w.entries.values()):
            rep.notes.append("aviso: o mod usa entradas em sub-blocos; o subchunktoc dele foi mantido")
        else:
            sub = {subtoc}
    identical = set()
    game.holders(0)  # build the index so `unindexed` is known before deciding
    if game.unindexed:
        rep.notes.append("aviso: %d WAD(s) do jogo não puderam ser lidos; arquivos idênticos foram mantidos"
                         % len(game.unindexed))
    else:
        for h in w.entries:
            if h in replaced or h in rec or h in sub or h in multi or h not in gw.entries:
                continue
            if not w.same_content(h, gw):
                continue
            if all(p == own or w.same_content(h, game.wad_at(p)) for p in game.holders(h)):
                identical.add(h)
    rep.removed_rec = len(rec)
    rep.removed_subchunktoc = bool(sub)
    rep.removed_identical = len(identical)
    rep.removed_identical_bytes = sum(w.entries[h].size for h in identical)
    return rec | sub | identical


def _family(path):
    """'Zed' for Zed.wad.client and Zed.pt_BR.wad.client."""
    return os.path.basename(path).split(".")[0].lower()


def _shared_entries(w, name, game, keep_candidates, multi, rep):
    """Lite mode: entries the game also holds in WADs outside the mod's own family."""
    fam = _family(name)
    shared = set()
    if game.unindexed:
        rep.notes.append("aviso: modo leve desativado porque alguns WADs do jogo não puderam ser lidos")
        return shared
    for h in keep_candidates:
        if h in multi:
            continue
        others = sorted({os.path.basename(p) for p in game.holders(h) if _family(p) != fam})
        if others:
            shared.add(h)
            rep.removed_shared.append((h, others))
    return shared


def _is_bin(w, h):
    try:
        return w.entries[h].size >= 8 and w.read(h, limit=4) in BIN_MAGICS
    except Exception:  # undecodable entry: not something we can fix, leave it alone
        return False


def _process_wad(name, data, game, rep, cleanup=True, lite=False, multi=frozenset()):
    w = Wad(data)
    gw = game.wad(name)
    rep.game_found = gw is not None
    if gw is None:
        return None
    w.load_subchunk_toc(subchunktoc_hash(game.relpath(game.path_of(name))))

    bins = {h: BinFile(w.read(h)) for h in w.entries if _is_bin(w, h)}
    rep.bins = len(bins)

    roots = {path_hash("data/characters/%s/%s.bin" % (c, c)): "data/characters/%s/%s.bin" % (c, c)
             for c in _character_names(name, bins.values())}
    resolves = lambda link: path_hash(link) in w.entries or path_hash(link) in gw.entries

    replaced = {}
    for h, mb in bins.items():
        gb = BinFile(gw.read(h)) if h in gw.entries and _is_bin(gw, h) else None
        if _fix_bin(mb, gb, resolves, roots.get(h), rep):
            replaced[h] = mb.dump()
    rep.bins_changed = len(replaced)

    # Cleanup is best effort: a failure here must never cost the .bin fixes above.
    removed = set()
    try:
        if cleanup:
            removed = _unneeded_entries(w, name, gw, game, replaced, multi, rep)
        if lite:
            removed |= _shared_entries(w, name, game, [h for h in w.entries if h not in removed], multi, rep)
        rep.touched_before = len(game.touched_wads(name, w.entries))
        rep.touched_after = len(game.touched_wads(name, [h for h in w.entries if h not in removed]))
    except Exception as e:
        removed = set()
        rep.removed_identical = rep.removed_identical_bytes = rep.removed_rec = 0
        rep.removed_subchunktoc = False
        rep.removed_shared = []
        rep.touched_before = rep.touched_after = 0
        rep.notes.append("aviso: limpeza ignorada neste WAD (%s: %s)" % (type(e).__name__, e))
    return w.rebuild(replaced, removed) if replaced or removed else None


def _shared_mod_hashes(zin, wad_names):
    """Path hashes that appear in more than one WAD of the same mod."""
    seen, multi = set(), set()
    for n in wad_names:
        try:
            with zin.open(n) as f:
                hashes = set(_toc_hashes_from(f))
        except Exception:
            continue
        multi |= seen & hashes
        seen |= hashes
    return multi


def process(path, game, output=None, log=lambda msg: None, cleanup=True, lite=False):
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
            wad_names = [n for n in zin.namelist() if n.lower().endswith(".wad.client")]
            multi = _shared_mod_hashes(zin, wad_names) if len(wad_names) > 1 else frozenset()
            for n in wad_names:
                wr = WadReport(n)
                rep.wads.append(wr)
                log("  analisando %s..." % n)
                try:
                    new = _process_wad(os.path.basename(n), zin.read(n), game, wr, cleanup, lite, multi)
                    if new is not None:
                        new_wads[n] = new
                except Exception as e:  # one broken WAD must not stop the rest of the batch
                    wr.error = "%s: %s" % (type(e).__name__, e)
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


def fix_in_place(path, game, log=lambda msg: None, cleanup=True, lite=False):
    """Repair `path` itself, keeping the original as '<path>.bak'."""
    fd, tmp = tempfile.mkstemp(suffix=".fantome", dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    os.remove(tmp)
    rep = process(path, game, output=tmp, log=log, cleanup=cleanup, lite=lite)
    if rep.output:
        backup = path + ".bak"
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        os.replace(tmp, path)
        rep.output = path
    return rep
