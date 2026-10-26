"""Read and rewrite League of Legends WAD v3 archives (.wad.client)."""
import gzip
import struct

import xxhash
import zstandard

HEADER_SIZE_V3 = 4 + 256 + 8  # magic+version, ECDSA signature, checksum
TOC_ENTRY = struct.Struct("<QIIIBBHQ")
SUBCHUNK = struct.Struct("<IIQ")  # compressed size, uncompressed size, checksum
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

TYPE_RAW, TYPE_GZIP, TYPE_SATELLITE, TYPE_ZSTD, TYPE_ZSTD_CHUNKED = range(5)


def path_hash(path):
    return xxhash.xxh64_intdigest(path.lower().encode("utf-8"))


def subchunktoc_hash(wad_relpath):
    """Hash of the sub-chunk table of 'DATA/FINAL/Champions/Zed.wad.client'."""
    rel = wad_relpath.replace("\\", "/")
    return path_hash(rel[:-len("client")] + "subchunktoc")


class WadError(Exception):
    pass


class Entry:
    __slots__ = ("hash", "offset", "comp_size", "size", "type", "dup", "subchunk", "checksum")

    def __init__(self, h, offset, comp_size, size, type_, dup, subchunk, checksum):
        self.hash, self.offset, self.comp_size, self.size = h, offset, comp_size, size
        self.type, self.dup, self.subchunk, self.checksum = type_, dup, subchunk, checksum

    @property
    def kind(self):
        return self.type & 0x0F

    def first_subchunk(self, minor):
        # WAD 3.4 widened the index to 24 bits using the old "duplicate" byte.
        return self.subchunk | (self.dup << 16) if minor >= 4 else self.subchunk


class Wad:
    def __init__(self, data, fileobj=None):
        """`data` holds the whole WAD, or (with `fileobj`) just header + TOC."""
        if data[:2] != b"RW":
            raise WadError("não é um arquivo WAD")
        self.data = data
        self._file = fileobj
        self.subchunk_toc = None  # bytes of the WAD's .subchunktoc, for kind-4 entries
        self.major, self.minor = data[2], data[3]
        if self.major != 3:
            raise WadError("WAD versão %d.%d não suportado (só v3)" % (self.major, self.minor))
        (count,) = struct.unpack_from("<I", data, HEADER_SIZE_V3)
        off = HEADER_SIZE_V3 + 4
        self.entries = {}
        for _ in range(count):
            e = Entry(*TOC_ENTRY.unpack_from(data, off))
            off += TOC_ENTRY.size
            self.entries[e.hash] = e

    @classmethod
    def from_file(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    @classmethod
    def open(cls, path):
        """Read only header + TOC; entry data is read from disk on demand."""
        f = open(path, "rb")
        try:
            head = f.read(HEADER_SIZE_V3 + 4)
            if len(head) < HEADER_SIZE_V3 + 4 or head[:2] != b"RW" or head[2] != 3:
                raise WadError("WAD inválido ou não suportado: %s" % path)
            (count,) = struct.unpack_from("<I", head, HEADER_SIZE_V3)
            return cls(head + f.read(count * TOC_ENTRY.size), fileobj=f)
        except Exception:
            f.close()
            raise

    def close(self):
        if self._file:
            self._file.close()
            self._file = None

    def _raw(self, e):
        if self._file:
            self._file.seek(e.offset)
            return self._file.read(e.comp_size)
        return self.data[e.offset:e.offset + e.comp_size]

    def load_subchunk_toc(self, h):
        if h in self.entries:
            self.subchunk_toc = self.read(h)

    def same_content(self, h, other, oh=None):
        """True if entry `h` here and entry `oh` (default `h`) in `other` hold the same bytes.

        Anything that cannot be decoded counts as different (the caller keeps it).
        """
        a, b = self.entries[h], other.entries[h if oh is None else oh]
        if a.size != b.size:
            return False
        if a.kind == b.kind and a.comp_size == b.comp_size and self._raw(a) == other._raw(b):
            return True
        try:
            return self.read(a.hash) == other.read(b.hash)
        except Exception:
            return False

    def _read_chunked(self, e, raw, want):
        count = e.type >> 4
        first = e.first_subchunk(self.minor)
        toc = self.subchunk_toc
        if toc is not None and count and (first + count) * SUBCHUNK.size <= len(toc):
            out = bytearray()
            pos = 0
            for i in range(first, first + count):
                cs, us, _ = SUBCHUNK.unpack_from(toc, i * SUBCHUNK.size)
                part = raw[pos:pos + cs]
                pos += cs
                out += part if cs == us else zstandard.ZstdDecompressor().decompress(part, max_output_size=us)
                if len(out) >= want:
                    break
            return bytes(out[:want])
        # No table: uncompressed leading chunk(s) up to the first zstd frame, then frames.
        start = raw.find(ZSTD_MAGIC)
        if start < 0:
            return raw[:want]
        out = bytearray(raw[:start])
        with zstandard.ZstdDecompressor().stream_reader(raw[start:], read_across_frames=True) as r:
            while len(out) < want:
                chunk = r.read(want - len(out))
                if not chunk:
                    break
                out += chunk
        return bytes(out[:want])

    def read(self, h, limit=None):
        """Decompressed contents of entry `h` (only the first `limit` bytes if given)."""
        e = self.entries[h]
        raw = self._raw(e)
        if e.kind == TYPE_RAW:
            return raw[:limit] if limit else raw
        if e.kind == TYPE_GZIP:
            data = gzip.decompress(raw)
            return data[:limit] if limit else data
        if e.kind == TYPE_ZSTD_CHUNKED:
            return self._read_chunked(e, raw, limit or e.size)
        if e.kind == TYPE_ZSTD:
            dctx = zstandard.ZstdDecompressor()
            if not limit:
                return dctx.decompress(raw, max_output_size=e.size)
            want = limit
            out = bytearray()
            with dctx.stream_reader(raw, read_across_frames=True) as r:
                while len(out) < want:
                    chunk = r.read(want - len(out))
                    if not chunk:
                        break
                    out += chunk
            return bytes(out)
        raise WadError("tipo de entrada %d não suportado" % e.kind)

    def rebuild(self, replaced, removed=()):
        """Return a new WAD with entries in `replaced` ({hash: bytes}) swapped in
        and entries in `removed` dropped.

        Every other entry is copied byte-for-byte (compression, sub-chunks and
        checksum untouched).
        """
        cctx = zstandard.ZstdCompressor(level=3)
        items = []
        for h in sorted(self.entries):
            e = self.entries[h]
            if h in removed:
                continue
            if h in replaced:
                data = replaced[h]
                comp = cctx.compress(data)
                items.append((h, comp, len(data), TYPE_ZSTD, 0, 0, xxhash.xxh3_64_intdigest(comp)))
            else:
                # Keep the 'dup' byte: in WAD 3.4 it is the high byte of the sub-chunk index.
                items.append((h, self._raw(e), e.size, e.type, e.dup, e.subchunk, e.checksum))
        out = bytearray(self.data[:HEADER_SIZE_V3])
        out += struct.pack("<I", len(items))
        toc_at = len(out)
        out += bytes(TOC_ENTRY.size * len(items))
        for i, (h, blob, size, type_, dup, sub, chk) in enumerate(items):
            TOC_ENTRY.pack_into(out, toc_at + TOC_ENTRY.size * i, h, len(out), len(blob), size, type_, dup, sub, chk)
            out += blob
        return bytes(out)
