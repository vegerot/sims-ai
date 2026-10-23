"""Build BanterLab.ts4script and BanterLabUI.package, then deploy to Mods/BanterLab."""

import importlib.util
import py_compile
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

DEFAULT_DEPLOY_DIR = Path(r'C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\BanterLab')
DEFAULT_UI_PACKAGE = Path(r'C:\Program Files\EA Games\The Sims 4\Data\Client\UI.package')


def _encode_u30(val):
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _patch_gfx_doabc(chunk, replacements):
    nbits = chunk[8] >> 3
    tpos = 8 + (5 + nbits * 4 + 7) // 8 + 4
    while tpos < len(chunk):
        tc = struct.unpack_from('<H', chunk, tpos)[0]
        tt, tl = tc >> 6, tc & 0x3F
        if tl == 0x3F:
            len_pos = tpos + 2
            tl = struct.unpack_from('<I', chunk, len_pos)[0]
            data_start = tpos + 6
        else:
            len_pos = None
            data_start = tpos + 2
        data_end = data_start + tl
        if tt == 82:
            tag_data = chunk[data_start:data_end]
            for old_bytes, new_bytes in replacements:
                count = tag_data.count(old_bytes)
                assert count == 1, f'Expected 1 occurrence of ABC pattern, found {count}'
                tag_data = tag_data.replace(old_bytes, new_bytes, 1)
            new_tl = len(tag_data)
            assert len_pos is not None
            new_chunk = (
                chunk[:4]
                + struct.pack('<I', len(chunk) + (new_tl - tl))
                + chunk[8:len_pos]
                + struct.pack('<I', new_tl)
                + tag_data
                + chunk[data_end:]
            )
            assert len(new_chunk) == struct.unpack_from('<I', new_chunk, 4)[0]
            return new_chunk
        tpos = data_end
    raise RuntimeError('DoABC tag not found in GFX stream')


def _write_dbpf_package(output_path, resources):
    """Write a DBPF v2.1 package with ZLIB-compressed resources: [(type, group, instance, raw_bytes)]."""
    body_chunks = []
    index_entries = []
    current_offset = 96
    for rtype, rgroup, rinst, raw_bytes in resources:
        comp_bytes = zlib.compress(raw_bytes, 6)
        inst_hi = (rinst >> 32) & 0xFFFFFFFF
        inst_lo = rinst & 0xFFFFFFFF
        index_entries.append(struct.pack(
            '<IIIIIIIHH',
            rtype,
            rgroup,
            inst_hi,
            inst_lo,
            current_offset,
            len(comp_bytes) | 0x80000000,
            len(raw_bytes),
            0x5A42,
            1,
        ))
        body_chunks.append(comp_bytes)
        current_offset += len(comp_bytes)

    index_blob = struct.pack('<I', 0) + b''.join(index_entries)
    header = bytearray(96)
    header[0:4] = b'DBPF'
    struct.pack_into('<I', header, 4, 2)
    struct.pack_into('<I', header, 8, 1)
    struct.pack_into('<I', header, 36, len(resources))
    struct.pack_into('<I', header, 44, len(index_blob))
    struct.pack_into('<I', header, 60, 3)
    struct.pack_into('<I', header, 64, current_offset)
    struct.pack_into('<I', header, 80, 0xFFFF)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(header) + b''.join(body_chunks) + index_blob)


def build_ui_package(output_pkg, ui_pkg=DEFAULT_UI_PACKAGE):
    if not ui_pkg.exists():
        print(f'Skipping UI package build ({ui_pkg} not found)')
        return None
    data = ui_pkg.read_bytes()
    index_count = struct.unpack_from('<I', data, 36)[0]
    index_offset = struct.unpack_from('<I', data, 64)[0] or struct.unpack_from('<I', data, 40)[0]
    pos = index_offset
    flags = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    const_type = struct.unpack_from('<I', data, pos)[0] if (flags & 1) else None
    if flags & 1:
        pos += 4
    const_group = struct.unpack_from('<I', data, pos)[0] if (flags & 2) else None
    if flags & 2:
        pos += 4
    const_inst_hi = struct.unpack_from('<I', data, pos)[0] if (flags & 4) else None
    if flags & 4:
        pos += 4
    const_inst_lo = struct.unpack_from('<I', data, pos)[0] if (flags & 8) else None
    if flags & 8:
        pos += 4

    notif_inst = 0x47928BF88A95BD53
    raw_resources = {}
    for _ in range(index_count):
        rtype = const_type if (flags & 1) else struct.unpack_from('<I', data, pos)[0]
        if not (flags & 1):
            pos += 4
        rgroup = const_group if (flags & 2) else struct.unpack_from('<I', data, pos)[0]
        if not (flags & 2):
            pos += 4
        inst_hi = const_inst_hi if (flags & 4) else struct.unpack_from('<I', data, pos)[0]
        if not (flags & 4):
            pos += 4
        inst_lo = const_inst_lo if (flags & 8) else struct.unpack_from('<I', data, pos)[0]
        if not (flags & 8):
            pos += 4
        offset, size_raw, mem_size, comp_type = struct.unpack_from('<IIIH', data, pos)
        pos += 16
        inst = (inst_hi << 32) | inst_lo
        if inst == notif_inst:
            size = size_raw & 0x7FFFFFFF
            chunk = data[offset:offset + size]
            if comp_type and size != mem_size:
                chunk = zlib.decompress(chunk)
            raw_resources[inst] = (rtype, rgroup, inst, chunk)

    # Patch Notifications.gfx (ShowNextMessage honors notification.timeout_duration in ms when > 0)
    old_6609 = bytes.fromhex(
        'd0 30 20 80 1f d5 20 85 d6 28 d7 20 80 0e 63 04 d0 66 da 2d 66 80 26 24 00 0e b3 00 00 '
        'd0 66 da 2d 24 00 46 90 26 01 60 1f 87 80 1f d5 d1 66 df 0f 46 c8 03 00 85 d6 60 90 99 01 '
        '60 e2 01 66 e8 8f 01 d2 66 80 26 d0 66 d9 2d 66 dc 0f a2 46 fc 1c 02 75 d7 d0 5d e7 05 d3 '
        '4a e7 05 01 68 db 2d d0 66 db 2d 60 6b 66 c9 9f 01 d0 66 ee 2d 27 24 00 27 4f db 14 05 d0 '
        '4f e8 2d 00 d0 d1 66 af 27 60 1f 66 a4 97 01 ab 68 e0 2d d0 d0 66 e0 2d 76 2a 11 06 00 00 '
        '29 d0 66 df 2d 76 2a 11 06 00 00 29 d0 66 dd 2d 76 68 de 2d 2c 84 08 d1 2c 82 b3 01 d0 66 '
        'de 2d 2c 84 b3 01 27 55 03 80 0e 63 04 60 37 2c 86 b3 01 62 04 4f 96 03 02 10 05 00 00 d0 '
        '27 68 dd 2d 47'
    )
    new_6609 = (
        old_6609[:25]
        + bytes.fromhex('0e c3 00 00')
        + old_6609[29:84]
        + bytes.fromhex('d1 66 e3 0f 24 00 0e 06 00 00 d1 66 e3 0f 75 d7')
        + old_6609[84:]
    )
    n_type, n_group, n_inst, n_chunk = raw_resources[notif_inst]
    patched_notif = _patch_gfx_doabc(
        n_chunk,
        [(_encode_u30(len(old_6609)) + old_6609, _encode_u30(len(new_6609)) + new_6609)],
    )

    _write_dbpf_package(output_pkg, [(n_type, n_group, n_inst, patched_notif)])
    print(f'Built {output_pkg} ({output_pkg.stat().st_size} bytes)')
    return output_pkg


def main():
    if sys.version_info[:2] != (3, 7):
        raise SystemExit('The installed game requires Python 3.7 bytecode.')

    root = Path(__file__).resolve().parent
    source = root / 'src'
    output = root / 'dist' / 'BanterLab.ts4script'
    ui_pkg_output = root / 'dist' / 'BanterLabUI.package'
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, zipfile.ZipFile(str(output), 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*.py')):
            relative = path.relative_to(source).with_suffix('.pyc')
            compiled = Path(temporary) / relative
            compiled.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(path), cfile=str(compiled),
                               dfile=relative.as_posix(), doraise=True)
            assert compiled.read_bytes()[:4] == importlib.util.MAGIC_NUMBER
            archive.write(str(compiled), relative.as_posix())
    print(f'Built {output}')
    with zipfile.ZipFile(str(output)) as archive:
        assert archive.testzip() is None
        print('Modules: {}'.format(', '.join(archive.namelist())))

    built_ui = build_ui_package(ui_pkg_output)

    if DEFAULT_DEPLOY_DIR.parent.exists():
        DEFAULT_DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
        # companion.py and prompt.txt run from this repository; the game starts them from here.
        assets = [output]
        if built_ui is not None:
            assets.append(built_ui)
        for asset in assets:
            dest = DEFAULT_DEPLOY_DIR / asset.name
            try:
                if dest.exists() and dest.read_bytes() == asset.read_bytes():
                    print(f'Up to date {dest}')
                    continue
                shutil.copy2(str(asset), str(dest))
                print(f'Deployed {dest}')
            except PermissionError:
                print(f'Skipped locked {dest} (close The Sims 4 to replace .package)')


if __name__ == '__main__':
    main()
