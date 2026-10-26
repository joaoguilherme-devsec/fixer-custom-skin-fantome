"""Minimal PROP/PTCH property-bin container.

Entries are kept as opaque byte blobs, so the file round-trips exactly no
matter which property kinds the current game version uses.
"""
import struct

BIN_MAGICS = (b"PROP", b"PTCH")


class BinFile:
    def __init__(self, b):
        self.ptch_header = None
        o = 0
        if b[:4] == b"PTCH":
            self.ptch_header = b[4:12]
            o = 12
        if b[o:o + 4] != b"PROP":
            raise ValueError("não é um .bin (PROP)")
        o += 4
        self.version = struct.unpack_from("<I", b, o)[0]
        o += 4
        self.links = []
        if self.version >= 2:
            n = struct.unpack_from("<I", b, o)[0]
            o += 4
            for _ in range(n):
                ln = struct.unpack_from("<H", b, o)[0]
                self.links.append(b[o + 2:o + 2 + ln].decode("utf-8"))
                o += 2 + ln
        count = struct.unpack_from("<I", b, o)[0]
        o += 4
        types = struct.unpack_from("<%dI" % count, b, o)
        o += 4 * count
        self.entries = []  # (class_hash, path_hash, blob starting with path_hash)
        for t in types:
            ln = struct.unpack_from("<I", b, o)[0]
            blob = b[o + 4:o + 4 + ln]
            self.entries.append((t, struct.unpack_from("<I", blob, 0)[0], blob))
            o += 4 + ln
        self.tail = b[o:]  # PTCH patch section, if any

    def dump(self):
        out = bytearray()
        if self.ptch_header is not None:
            out += b"PTCH" + self.ptch_header
        out += b"PROP" + struct.pack("<I", self.version)
        if self.version >= 2:
            out += struct.pack("<I", len(self.links))
            for link in self.links:
                e = link.encode("utf-8")
                out += struct.pack("<H", len(e)) + e
        out += struct.pack("<I", len(self.entries))
        out += struct.pack("<%dI" % len(self.entries), *[t for t, _, _ in self.entries])
        for _, _, blob in self.entries:
            out += struct.pack("<I", len(blob)) + blob
        out += self.tail
        return bytes(out)
