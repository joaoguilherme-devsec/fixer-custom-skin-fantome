"""Read and rewrite League of Legends WAD v3 archives (.wad.client)."""
import gzip
import struct

import xxhash
import zstandard

HEADER_SIZE_V3 = 4 + 256 + 8  # magic+version, ECDSA signature, checksum
TOC_ENTRY = struct.Struct("<QIIIBBHQ")

TYPE_RAW, TYPE_GZIP, TYPE_SATELLITE, TYPE_ZSTD, TYPE_ZSTD_CHUNKED = range(5)


def path_hash(path):
    return xxhash.xxh64_intdigest(path.lower().encode("utf-8"))


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


class Wad:
    def __init__(self, data):
        if data[:2] != b"RW":
            raise WadError("não é um arquivo WAD")
        self.data = data
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

    def _raw(self, e):
        return self.data[e.offset:e.offset + e.comp_size]

    def read(self, h, limit=None):
        """Decompressed contents of entry `h` (only the first `limit` bytes if given)."""
        e = self.entries[h]
        raw = self._raw(e)
        if e.kind == TYPE_RAW:
            return raw[:limit] if limit else raw
        if e.kind == TYPE_GZIP:
            data = gzip.decompress(raw)
            return data[:limit] if limit else data
        if e.kind in (TYPE_ZSTD, TYPE_ZSTD_CHUNKED):
            dctx = zstandard.ZstdDecompressor()
            if e.kind == TYPE_ZSTD and not limit:
                return dctx.decompress(raw, max_output_size=e.size)
            with dctx.stream_reader(raw, read_across_frames=True) as r:
                return r.read(limit or e.size)
        raise WadError("tipo de entrada %d não suportado" % e.kind)

    def rebuild(self, replaced):
        """Return a new WAD with entries in `replaced` ({hash: bytes}) swapped in.

        Every other entry is copied byte-for-byte (compression, sub-chunks and
        checksum untouched).
        """
        cctx = zstandard.ZstdCompressor(level=3)
        items = []
        for h in sorted(self.entries):
            e = self.entries[h]
            if h in replaced:
                data = replaced[h]
                comp = cctx.compress(data)
                items.append((h, comp, len(data), TYPE_ZSTD, 0, xxhash.xxh3_64_intdigest(comp)))
            else:
                items.append((h, self._raw(e), e.size, e.type, e.subchunk, e.checksum))
        out = bytearray(self.data[:HEADER_SIZE_V3])
        out += struct.pack("<I", len(items))
        toc_at = len(out)
        out += bytes(TOC_ENTRY.size * len(items))
        for i, (h, blob, size, type_, sub, chk) in enumerate(items):
            TOC_ENTRY.pack_into(out, toc_at + TOC_ENTRY.size * i, h, len(out), len(blob), size, type_, 0, sub, chk)
            out += blob
        return bytes(out)
