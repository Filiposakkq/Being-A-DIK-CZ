"""Read-only access to Ren'Py archives (.rpa, versions 2 and 3).

An archive is a header line (`RPA-3.0 <index offset hex> <key hex>`), the file data, and at the offset a zlib compressed pickle
of {name: [(offset, length[, prefix])]}. The pickle comes from a file on disk, so it is read with an unpickler that refuses to
create any object: only plain numbers, strings, bytes, lists, tuples and dicts get through. Nothing here ever writes.
"""
import io
import pickle
import zlib

MAX_INDEX = 128 * 1024 * 1024        # the decompressed index of even a huge game is a few MB


class RpaError(Exception):
    pass


class _PlainUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"blocked {module}.{name}")


def read_index(path):
    """Returns (version, {name: (offset, length, prefix_bytes)}). Raises RpaError for anything that is not a usable archive."""
    try:
        with open(path, "rb") as f:
            head = f.readline(80).decode("latin-1").strip().split()
            if not head or head[0] not in ("RPA-3.0", "RPA-2.0"):
                raise RpaError("není archiv RPA 2 / 3")
            off = int(head[1], 16)
            key = int(head[2], 16) if head[0] == "RPA-3.0" else 0
            f.seek(off)
            comp = f.read()
        dec = zlib.decompressobj()
        raw = dec.decompress(comp, MAX_INDEX)
        if dec.unconsumed_tail:
            raise RpaError("index archivu je nezvykle velký")
        idx = _PlainUnpickler(io.BytesIO(raw), encoding="latin-1").load()
    except RpaError:
        raise
    except (OSError, ValueError, IndexError, zlib.error, pickle.UnpicklingError, EOFError, AttributeError, TypeError) as e:
        raise RpaError(f"archiv nejde přečíst: {e}") from e
    out = {}
    if not isinstance(idx, dict):
        raise RpaError("index archivu má neočekávaný tvar")
    for name, items in idx.items():
        try:
            e = items[0]
            offset, length = int(e[0]) ^ key, int(e[1]) ^ key
            prefix = e[2] if len(e) > 2 else b""
            if isinstance(prefix, str):
                prefix = prefix.encode("latin-1")
            if not isinstance(prefix, (bytes, bytearray)) or offset < 0 or length < 0:
                continue
            out[str(name).replace("\\", "/")] = (offset, length, bytes(prefix))
        except (IndexError, TypeError, ValueError):
            continue
    return head[0], out


def read_entry(path, entry, limit=64 * 1024 * 1024):
    """The bytes of one file of an archive (prefix + data), at most `limit` bytes."""
    offset, length, prefix = entry
    if length > limit:
        raise RpaError("soubor v archivu je příliš velký")
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(max(0, length - len(prefix)))
    except OSError as e:
        raise RpaError(f"archiv nejde přečíst: {e.strerror or e}") from e
    return prefix + data
