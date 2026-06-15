"""Compile a .po file to a .mo file without requiring GNU gettext."""
import struct


def _unescape(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


def compile_po_to_mo(po_path: str, mo_path: str) -> None:
    messages: dict[bytes, bytes] = {}
    current_id: list[str] = []
    current_str: list[str] = []
    in_id = False
    in_str = False

    def _commit():
        if current_id is not None:
            key = _unescape("".join(current_id)).encode("utf-8")
            val = _unescape("".join(current_str)).encode("utf-8")
            messages[key] = val

    with open(po_path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if line.startswith("#") or not line.strip():
                continue
            if line.startswith("msgid "):
                _commit()
                current_id = []
                current_str = []
                in_id = True
                in_str = False
                inner = line[7:-1]  # strip leading: msgid " and trailing "
                current_id.append(inner)
            elif line.startswith("msgstr "):
                in_id = False
                in_str = True
                inner = line[8:-1]
                current_str.append(inner)
            elif line.startswith('"'):
                inner = line[1:-1]
                if in_id:
                    current_id.append(inner)
                elif in_str:
                    current_str.append(inner)
        _commit()

    # Sort: empty key (header) must come first, then sorted ids
    empty = messages.pop(b"", b"")
    # Rebuild header with charset so gettext knows to use UTF-8
    if b"Content-Type" not in empty:
        empty = b"Content-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\nLanguage: sw\n"
    messages[b""] = empty

    keys = sorted(messages.keys())
    n = len(keys)

    # Compute offsets
    # Header: magic(4) revision(4) n(4) off_ids(4) off_strs(4) hash_size(4) hash_off(4) = 28 bytes
    id_index_start = 28
    str_index_start = 28 + 8 * n
    strings_start = 28 + 16 * n  # where actual string bytes begin

    id_offsets = []
    str_offsets = []
    id_bytes = b""
    str_bytes = b""

    id_pos = strings_start
    for k in keys:
        id_offsets.append((len(k), id_pos))
        id_bytes += k + b"\x00"
        id_pos += len(k) + 1

    str_pos = strings_start + len(id_bytes)
    for k in keys:
        v = messages[k]
        str_offsets.append((len(v), str_pos))
        str_bytes += v + b"\x00"
        str_pos += len(v) + 1

    MAGIC = 0x950412DE
    with open(mo_path, "wb") as f:
        f.write(struct.pack("<IIIIIII", MAGIC, 0, n, id_index_start, str_index_start, 0, 0))
        for length, offset in id_offsets:
            f.write(struct.pack("<II", length, offset))
        for length, offset in str_offsets:
            f.write(struct.pack("<II", length, offset))
        f.write(id_bytes)
        f.write(str_bytes)

    print(f"Compiled {n - 1} messages (+ header) -> {mo_path}")


if __name__ == "__main__":
    compile_po_to_mo(
        "locale/sw/LC_MESSAGES/django.po",
        "locale/sw/LC_MESSAGES/django.mo",
    )
