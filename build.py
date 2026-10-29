"""Build BanterLab.ts4script and BanterLabUI.package, deploy, or uninstall (--uninstall / --reset-data)."""

import argparse
import ctypes
import importlib.util
import json
import os
import py_compile
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

DEFAULT_TS4_DIR = Path(r'C:\Program Files\EA Games\The Sims 4')
DEFAULT_TS4_USER_DIR = Path(r'C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4')
DEFAULT_DEPLOY_DIR = DEFAULT_TS4_USER_DIR / 'Mods' / 'BanterLab'
DEFAULT_UI_PACKAGE = DEFAULT_TS4_DIR / 'Data' / 'Client' / 'UI.package'
DEFAULT_GAME_INI = DEFAULT_TS4_DIR / 'Game' / 'Bin' / 'Default.ini'


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


def _decode_u30(buf, pos):
    val = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7


def _skip_u30(buf, pos, count=1):
    for _ in range(count):
        _, pos = _decode_u30(buf, pos)
    return pos


def _patch_notifications_abc(tag):
    """Symbolically patch NotificationsMain.ShowNextMessage in DoABC to honor notification.timeout_duration > 0."""
    p = tag.index(0, 4) + 5  # DoABC flags (4B) + null-terminated name + minor/major version (4B)
    for _ in range(2):
        cnt, p = _decode_u30(tag, p)
        p = _skip_u30(tag, p, max(0, cnt - 1))
    dbl_cnt, p = _decode_u30(tag, p)
    p += max(0, dbl_cnt - 1) * 8
    str_cnt, p = _decode_u30(tag, p)
    strings = ['']
    for _ in range(max(0, str_cnt - 1)):
        slen, p = _decode_u30(tag, p)
        strings.append(tag[p:p + slen].decode('utf-8', errors='replace'))
        p += slen
    ns_cnt, p = _decode_u30(tag, p)
    namespaces = [(0, '')]
    for _ in range(max(0, ns_cnt - 1)):
        kind = tag[p]
        ni, p = _decode_u30(tag, p + 1)
        namespaces.append((kind, strings[ni]))
    nsset_cnt, p = _decode_u30(tag, p)
    for _ in range(max(0, nsset_cnt - 1)):
        cnt, p = _decode_u30(tag, p)
        p = _skip_u30(tag, p, cnt)
    mn_cnt, p = _decode_u30(tag, p)
    mn_names = ['']
    td_mn = timer_mn = None
    for idx in range(1, mn_cnt):
        k = tag[p]
        p += 1
        if k in (0x07, 0x0D):
            ns, p = _decode_u30(tag, p)
            nm, p = _decode_u30(tag, p)
            sname = strings[nm]
            mn_names.append(sname)
            if k == 0x07 and namespaces[ns] == (0x16, '') and sname == 'timeout_duration':
                td_mn = idx
            elif k == 0x07 and namespaces[ns] == (0x16, 'flash.utils') and sname == 'Timer':
                timer_mn = idx
        elif k in (0x0F, 0x10):
            nm, p = _decode_u30(tag, p)
            mn_names.append(strings[nm])
        elif k in (0x11, 0x12):
            mn_names.append('')
        elif k in (0x09, 0x0E):
            nm, p = _decode_u30(tag, p)
            p = _skip_u30(tag, p)
            mn_names.append(strings[nm])
        elif k in (0x1B, 0x1C):
            p = _skip_u30(tag, p)
            mn_names.append('')
        elif k == 0x1D:
            p = _skip_u30(tag, p)
            cnt, p = _decode_u30(tag, p)
            p = _skip_u30(tag, p, cnt)
            mn_names.append('')
        else:
            raise ValueError('Unknown ABC multiname kind {:#x}'.format(k))
    assert td_mn is not None and timer_mn is not None, (td_mn, timer_mn)

    meth_cnt, p = _decode_u30(tag, p)
    for _ in range(meth_cnt):
        pcnt, p = _decode_u30(tag, p)
        p = _skip_u30(tag, p, pcnt + 2)
        mf = tag[p]
        p += 1
        if mf & 0x08:
            oc, p = _decode_u30(tag, p)
            for _ in range(oc):
                p = _skip_u30(tag, p) + 1
        if mf & 0x80:
            p = _skip_u30(tag, p, pcnt)
    meta_cnt, p = _decode_u30(tag, p)
    for _ in range(meta_cnt):
        p = _skip_u30(tag, p)
        ic, p = _decode_u30(tag, p)
        p = _skip_u30(tag, p, ic * 2)

    def read_traits(pos):
        tc, pos = _decode_u30(tag, pos)
        out = []
        for _ in range(tc):
            tn, pos = _decode_u30(tag, pos)
            kb = tag[pos]
            pos += 1
            tk, ta = kb & 0x0F, kb >> 4
            mid = None
            if tk in (0, 6):
                pos = _skip_u30(tag, pos, 2)
                vi, pos = _decode_u30(tag, pos)
                if vi:
                    pos += 1
            elif tk in (1, 2, 3, 5):
                pos = _skip_u30(tag, pos)
                mid, pos = _decode_u30(tag, pos)
            elif tk == 4:
                pos = _skip_u30(tag, pos, 2)
            if ta & 0x04:
                mc, pos = _decode_u30(tag, pos)
                pos = _skip_u30(tag, pos, mc)
            out.append((mn_names[tn], tk, mid))
        return out, pos

    inst_cnt, p = _decode_u30(tag, p)
    target_mid = None
    for _ in range(inst_cnt):
        iname, p = _decode_u30(tag, p)
        p = _skip_u30(tag, p)
        ifl = tag[p]
        p = _skip_u30(tag, p + 1) if (ifl & 0x08) else (p + 1)
        ic, p = _decode_u30(tag, p)
        p = _skip_u30(tag, p, ic + 1)
        trs, p = read_traits(p)
        if mn_names[iname] == 'NotificationsMain':
            for tname, tk, mid in trs:
                if tname == 'ShowNextMessage' and tk == 1:
                    target_mid = mid
    assert target_mid is not None, 'NotificationsMain.ShowNextMessage not found'
    for _ in range(inst_cnt):
        _, p = read_traits(_skip_u30(tag, p))
    scr_cnt, p = _decode_u30(tag, p)
    for _ in range(scr_cnt):
        _, p = read_traits(_skip_u30(tag, p))

    op_0 = {
        0x02, 0x20, 0x21, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x30, 0x47, 0x48,
        0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x82, 0x85, 0x87,
        0x90, 0x91, 0x93, 0x95, 0x96, 0x97,
        0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xAB,
        0xAC, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3, 0xB4,
        0xC0, 0xC1, 0xC4, 0xC5, 0xC6, 0xC7,
        0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,
    }
    op_u30_1 = {
        0x25, 0x2C, 0x2D, 0x2E, 0x2F, 0x40, 0x41, 0x42, 0x55, 0x56, 0x58,
        0x5D, 0x5E, 0x60, 0x61, 0x62, 0x63, 0x66, 0x68, 0x80, 0x86,
        0x92, 0x94, 0xC2, 0xC3, 0xF0, 0xF1,
    }
    op_u30_2 = {0x45, 0x46, 0x4A, 0x4C, 0x4E, 0x4F}

    body_cnt, p = _decode_u30(tag, p)
    for _ in range(body_cnt):
        mid, p = _decode_u30(tag, p)
        clen_pos = _skip_u30(tag, p, 4)
        clen, p = _decode_u30(tag, clen_pos)
        cend_pos = p + clen
        code = tag[p:cend_pos]
        ecnt, p = _decode_u30(tag, cend_pos)
        p = _skip_u30(tag, p, ecnt * 5)
        _, p = read_traits(p)
        if mid == target_mid:
            assert ecnt == 0, 'Unexpected exception blocks in ShowNextMessage'
            timer_u30 = _encode_u30(timer_mn)
            anchor = b'\x75\xd7\xd0\x5d' + timer_u30 + b'\xd3\x4a' + timer_u30 + b'\x01'
            assert code.count(anchor) == 1, 'Expected 1 Timer(_loc3_) anchor in ShowNextMessage'
            ins_pos = code.index(anchor) + 2
            td_u30 = _encode_u30(td_mn)
            set_body = b'\xd1\x66' + td_u30 + b'\x75\xd7'
            injected = (
                b'\xd1\x66'
                + td_u30
                + b'\x24\x00\x0e'
                + len(set_body).to_bytes(3, 'little', signed=True)
                + set_body
            )
            patched_pre = bytearray(code[:ins_pos])
            cp = 0
            while cp < ins_pos:
                op = patched_pre[cp]
                cp += 1
                if op in op_0:
                    pass
                elif op == 0x24:
                    cp += 1
                elif 0x0C <= op <= 0x19:
                    rel = int.from_bytes(patched_pre[cp:cp + 3], 'little', signed=True)
                    if (cp + 3 + rel) >= ins_pos:
                        patched_pre[cp:cp + 3] = (rel + len(injected)).to_bytes(3, 'little', signed=True)
                    cp += 3
                elif op in op_u30_1:
                    cp = _skip_u30(patched_pre, cp)
                elif op in op_u30_2:
                    cp = _skip_u30(patched_pre, cp, 2)
                else:
                    raise ValueError('Unhandled AVM2 opcode {:#x} at {}'.format(op, cp - 1))
            new_code = bytes(patched_pre) + injected + code[ins_pos:]
            return tag[:clen_pos] + _encode_u30(len(new_code)) + new_code + tag[cend_pos:]
    raise RuntimeError('ShowNextMessage method body not found')


def _patch_gfx_doabc(chunk, tag_patcher):
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
            tag_data = tag_patcher(chunk[data_start:data_end])
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
        index_entries.append(struct.pack(
            '<IIIIIIIHH',
            rtype,
            rgroup,
            (rinst >> 32) & 0xFFFFFFFF,
            rinst & 0xFFFFFFFF,
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
    tmp_path = output_path.with_name('{}.{}.tmp'.format(output_path.name, os.getpid()))
    tmp_path.write_bytes(bytes(header) + b''.join(body_chunks) + index_blob)
    os.replace(str(tmp_path), str(output_path))


def build_ui_package(output_pkg, ui_pkg=DEFAULT_UI_PACKAGE):
    if not ui_pkg.exists():
        print(f'Skipping UI package build ({ui_pkg} not found)')
        return None
    data = ui_pkg.read_bytes()
    assert data[:4] == b'DBPF', 'Expected DBPF header in UI.package'
    index_count = struct.unpack_from('<I', data, 36)[0]
    pos = struct.unpack_from('<I', data, 64)[0] or struct.unpack_from('<I', data, 40)[0]
    flags = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    consts = {}
    for bit in (1, 2, 4, 8):
        if flags & bit:
            consts[bit] = struct.unpack_from('<I', data, pos)[0]
            pos += 4

    notif_inst = 0x47928BF88A95BD53
    for _ in range(index_count):
        vals = []
        for bit in (1, 2, 4, 8):
            if bit in consts:
                vals.append(consts[bit])
            else:
                vals.append(struct.unpack_from('<I', data, pos)[0])
                pos += 4
        rtype, rgroup, inst_hi, inst_lo = vals
        offset, size_raw, mem_size, comp_type = struct.unpack_from('<IIIH', data, pos)
        pos += 16
        inst = (inst_hi << 32) | inst_lo
        if inst == notif_inst:
            size = size_raw & 0x7FFFFFFF
            chunk = data[offset:offset + size]
            if comp_type and size != mem_size:
                chunk = zlib.decompress(chunk)
            patched_notif = _patch_gfx_doabc(chunk, _patch_notifications_abc)
            _write_dbpf_package(output_pkg, [(rtype, rgroup, inst, patched_notif)])
            print(f'Built {output_pkg} ({output_pkg.stat().st_size} bytes)')
            return output_pkg
    raise RuntimeError('Notifications.gfx resource missing from UI.package')


def _ensure_mods_enabled(user_dir=DEFAULT_TS4_USER_DIR, game_ini=DEFAULT_GAME_INI):
    """Sync GameVersion.txt to Default.ini and ensure script mods stay enabled across EA patches."""
    if game_ini.exists() and user_dir.exists():
        m = re.search(r'(?m)^gameversion\s*=\s*(\S+)', game_ini.read_text(encoding='utf-8', errors='replace'))
        if m:
            ver = m.group(1).encode('ascii')
            expected_gv = struct.pack('<I', len(ver)) + ver
            gv_path = user_dir / 'GameVersion.txt'
            if not gv_path.exists() or gv_path.read_bytes() != expected_gv:
                gv_path.write_bytes(expected_gv)
                print(f'Synced {gv_path} to {m.group(1)}')
    opt_path = user_dir / 'Options.ini'
    if opt_path.exists():
        raw = opt_path.read_bytes()
        updated = re.sub(rb'(?m)^modsdisabled\s*=\s*\d+', b'modsdisabled = 0', raw)
        updated = re.sub(rb'(?m)^scriptmodsenabled\s*=\s*\d+', b'scriptmodsenabled = 1', updated)
        if updated != raw:
            opt_path.write_bytes(updated)
            print(f'Enabled script mods in {opt_path}')


def uninstall_mod():
    if DEFAULT_DEPLOY_DIR.exists():
        for child in list(DEFAULT_DEPLOY_DIR.rglob('*')):
            if child.is_file():
                os.chmod(str(child), stat.S_IWRITE)
                child.unlink()
        if os.name == 'nt':
            # Clear OneDrive read-only/system directory flags before rmdir
            ctypes.windll.kernel32.SetFileAttributesW(str(DEFAULT_DEPLOY_DIR), 0x10)
        try:
            DEFAULT_DEPLOY_DIR.rmdir()
        except PermissionError:
            tmp = Path(tempfile.mkdtemp(prefix='banter-uninstall-'))
            shutil.move(str(DEFAULT_DEPLOY_DIR), str(tmp / 'BanterLab'))
        print(f'Uninstalled {DEFAULT_DEPLOY_DIR}')
    else:
        print(f'Already uninstalled ({DEFAULT_DEPLOY_DIR} absent)')
    thumb_cache = DEFAULT_TS4_USER_DIR / 'localthumbcache.package'
    if thumb_cache.exists():
        thumb_cache.unlink()
        print(f'Removed {thumb_cache}')
    for log_path in (
        DEFAULT_TS4_USER_DIR / 'Mods' / 'Basemental Drugs' / 'Basemental Drugs Log.log',
        DEFAULT_TS4_USER_DIR / 'WickedWhimsInfoLog.log',
    ):
        if log_path.exists():
            txt = log_path.read_text(encoding='utf-8', errors='replace')
            if 'BanterLab' in txt:
                kept = [ln for ln in txt.splitlines() if 'BanterLab' not in ln]
                log_path.write_text('\n'.join(kept) + '\n', encoding='utf-8')
                print(f'Scrubbed BanterLab entry from {log_path}')


def reset_runtime_data(root):
    data_dir = root / '.local' / 'data'
    tts_dir = root / '.local' / 'tts'
    for name in ('events.jsonl', 'memories.json', 'reply.json', 'companion.stdout.log', 'companion.stderr.log'):
        p = data_dir / name
        if p.exists():
            p.unlink()
            print(f'Removed {p}')
    cost_path = data_dir / 'cost_summary.json'
    if cost_path.exists():
        cost = json.loads(cost_path.read_text(encoding='utf-8-sig'))
        cost['session_usd'] = 0.0
        cost['session_exchanges'] = 0
        cost_path.write_text(json.dumps(cost, indent=2) + '\n', encoding='utf-8')
    if tts_dir.exists():
        removed_wavs = 0
        for wav in tts_dir.glob('*.wav'):
            wav.unlink()
            removed_wavs += 1
        if removed_wavs:
            print(f'Removed {removed_wavs} cached WAV files from {tts_dir}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true', help='Remove Mods/BanterLab and localthumbcache.package')
    parser.add_argument('--reset-data', action='store_true', help='Clear .local/data logs/memories and .local/tts WAVs')
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    if args.reset_data:
        reset_runtime_data(root)
    if args.uninstall:
        uninstall_mod()
        return
    if args.reset_data and sys.version_info[:2] != (3, 7):
        return

    if sys.version_info[:2] != (3, 7):
        raise SystemExit('The installed game requires Python 3.7 bytecode (.local/python37/python.exe).')

    source = root / 'src'
    init_text = (source / 'banter_lab' / '__init__.py').read_text(encoding='utf-8')
    proj_m = re.search(r"^_PROJECT_ROOT = r'([^']+)'", init_text, flags=re.M)
    py_m = re.search(r"^_PYTHON = r'([^']+)'", init_text, flags=re.M)
    # Invariant: embedded paths must resolve to this checkout and a real Python 3.15 binary.
    assert proj_m and Path(proj_m.group(1)).resolve() == root.resolve(), f'_PROJECT_ROOT mismatch: {proj_m}'
    assert py_m and Path(py_m.group(1)).is_file(), f'_PYTHON missing on disk: {py_m}'
    output = root / 'dist' / 'BanterLab.ts4script'
    ui_pkg_output = root / 'dist' / 'BanterLabUI.package'
    output.parent.mkdir(exist_ok=True)
    tmp_script = output.with_name(f'{output.name}.{os.getpid()}.tmp')
    with tempfile.TemporaryDirectory() as temporary, zipfile.ZipFile(str(tmp_script), 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*.py')):
            relative = path.relative_to(source).with_suffix('.pyc')
            compiled = Path(temporary) / relative
            compiled.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(path), cfile=str(compiled),
                               dfile=relative.as_posix(), doraise=True)
            assert compiled.read_bytes()[:4] == importlib.util.MAGIC_NUMBER
            archive.write(str(compiled), relative.as_posix())
    os.replace(str(tmp_script), str(output))
    print(f'Built {output}')
    with zipfile.ZipFile(str(output)) as archive:
        assert archive.testzip() is None
        print('Modules: {}'.format(', '.join(archive.namelist())))

    built_ui = build_ui_package(ui_pkg_output)

    if DEFAULT_DEPLOY_DIR.parent.exists():
        DEFAULT_DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
        # companion.py and prompt.txt run from this repository; the game starts them from here.
        assets = [output] + ([built_ui] if built_ui is not None else [])
        for asset in assets:
            dest = DEFAULT_DEPLOY_DIR / asset.name
            tmp_dest = dest.with_name(f'{dest.name}.{os.getpid()}.tmp')
            try:
                raw_asset = asset.read_bytes()
                if dest.exists() and dest.read_bytes() == raw_asset:
                    print(f'Up to date {dest}')
                    continue
                tmp_dest.write_bytes(raw_asset)
                os.replace(str(tmp_dest), str(dest))
                print(f'Deployed {dest}')
            except PermissionError:
                if tmp_dest.exists():
                    tmp_dest.unlink()
                print(f'Skipped locked {dest} (close The Sims 4 to replace .package)')
        _ensure_mods_enabled()


if __name__ == '__main__':
    main()
