#!/usr/bin/env python3
"""NOA(ERISA-Archive) 리스트/추출 도구.

- 디렉터리 포맷, 플래그 의미(EncType)는 GARbro ArcNOA.cs(MIT)와 실제 데이터 대조로 확인
- 압축(ERISA-N, f2 = 0x80000010)은 erisa_nemesis.py 로 해제하고, 중첩 NOA는 재귀 처리
- 암호화(0x40000000 BSHF 등)는 미구현: 만나면 경고만 출력하고 건너뜀

사용법
  python noa.py list    system.noa [-r]          # -r: 중첩 NOA까지 풀어서 재귀 목록
  python noa.py extract system.noa OUTDIR [-r]   # 파일 추출 (-r: 중첩 NOA를 폴더로 펼침)
  python noa.py extract bs.noa OUT --only 'kdu_aaa*' --only 'kdu_aab*'   # 이름 패턴(fnmatch, 대소문자 무시)에 맞는 것만
"""
import argparse, fnmatch, mmap, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import erisa_nemesis

ENC_RAW, ENC_ERISA = 0x00000000, 0x80000010
ENC_NAMES = {0x40000000: 'BSHF', 0x20000000: 'SimpleCrypt32', 0xC0000010: 'ERISA+BSHF', 0xA0000010: 'ERISA+Crypt32'}


class Entry:
    __slots__ = ('name', 'size', 'attr', 'enc', 'blk', 'ts', 'extra')


AUTO_ENCODINGS = ('utf-8', 'cp932', 'cp949')


def read_dir(buf, base=0, encoding='auto', cur=''):
    """buf[base:] 가 'Entis' 헤더로 시작하는 NOA 라고 가정하고 디렉터리를 파싱한다.
    encoding='auto' : utf-8 → cp932 → cp949 순으로 '모든 이름이 엄격하게 디코드되는' 첫 인코딩을 쓴다
    (한글패치 도구가 시스템 코드페이지(cp949)로 이름을 저장한 아카이브가 있음: 1화 script.noa)."""
    if bytes(buf[base:base + 5]) != b'Entis':
        raise ValueError('not an Entis container')
    if encoding != 'auto':
        return _parse_dir(buf, base, base + 0x40, encoding, cur)
    last = None
    for enc in AUTO_ENCODINGS:
        try:
            return _parse_dir(buf, base, base + 0x40, enc, cur)
        except UnicodeDecodeError as ex:
            last = ex
    raise last


def _parse_dir(buf, base, d, encoding, cur):
    if bytes(buf[d:d + 8]) != b'DirEntry':
        raise ValueError('DirEntry not found @0x%X' % d)
    (count,) = struct.unpack_from('<I', buf, d + 16)
    pos, out = d + 20, []
    for _ in range(count):
        size, attr, enc, off = struct.unpack_from('<QIIQ', buf, pos); pos += 24
        sec, mi, hr, dow, day, mon, yr = struct.unpack_from('<6BH', buf, pos); pos += 8
        (extra_len,) = struct.unpack_from('<I', buf, pos); pos += 4
        extra = bytes(buf[pos:pos + extra_len]) if (extra_len and not (attr & 0x70)) else b''
        pos += extra_len
        (nlen,) = struct.unpack_from('<I', buf, pos); pos += 4
        name = bytes(buf[pos:pos + nlen]).rstrip(b'\0').decode(encoding); pos += nlen
        e = Entry()
        e.name = cur + name; e.size = size; e.attr = attr; e.enc = enc
        e.blk = d + off          # filedata 블록 시작 (d = 'DirEntry' 위치 = 0x40 기준)
        e.ts = f'{yr:04d}-{mon:02d}-{day:02d} {hr:02d}:{mi:02d}:{sec:02d}'; e.extra = extra
        if attr == 0x10:                      # 하위 디렉터리: 블록 헤더(0x10) 뒤에 DirEntry
            out += _parse_dir(buf, base, e.blk + 0x10, encoding, e.name + '/')
        elif attr in (0x20, 0x40):
            break
        else:
            out.append(e)
    return out


def stored_size(buf, e):
    if bytes(buf[e.blk:e.blk + 8]) != b'filedata':
        raise ValueError('bad block header for ' + e.name)
    return struct.unpack_from('<Q', buf, e.blk + 8)[0]


def read_entry(buf, e):
    """엔트리 내용을 bytes 로 반환 (raw / ERISA 만 지원)."""
    stored = stored_size(buf, e)
    data = bytes(buf[e.blk + 0x10:e.blk + 0x10 + stored])
    if stored <= 4:
        return b''
    if e.enc == ENC_RAW:
        return data
    if e.enc == ENC_ERISA:
        out = erisa_nemesis.decompress(data, e.size)
        if len(out) != e.size:
            raise ValueError(f'{e.name}: 해제 크기 불일치 {len(out)} != {e.size}')
        return out
    raise NotImplementedError(f'{e.name}: 암호화 방식 {ENC_NAMES.get(e.enc, hex(e.enc))} 미구현')


def _match(name, only):
    if not only:
        return True
    base = name.rsplit('/', 1)[-1].lower()
    return any(fnmatch.fnmatch(base, pat.lower()) for pat in only)


def walk(buf, recursive, depth=0, prefix='', on_file=None, encoding='auto', only=None):
    for e in read_dir(buf, 0, encoding):
        stored = stored_size(buf, e)
        mode = {ENC_RAW: '-', ENC_ERISA: 'C'}.get(e.enc, '?')
        line = '  ' * depth + f'[{mode}] {e.name}  size={e.size} stored={stored} enc=0x{e.enc:08X} attr=0x{e.attr:X}'
        is_nested = recursive and e.name.lower().endswith('.noa')
        wanted = _match(e.name, only)
        if wanted or is_nested:
            print(line)
        if on_file and wanted:
            on_file(prefix + e.name, e, buf)
        if recursive and e.name.lower().endswith('.noa'):
            try:
                inner = read_entry(buf, e)
            except Exception as ex:
                print('  ' * (depth + 1) + f'(재귀 실패: {ex})'); continue
            walk(memoryview(inner), True, depth + 1, prefix + e.name + '/', on_file, encoding, only)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['list', 'extract'])
    ap.add_argument('archive'); ap.add_argument('outdir', nargs='?')
    ap.add_argument('-r', '--recursive', action='store_true')
    ap.add_argument('--only', action='append', help='이름 패턴(fnmatch)에 맞는 파일만 처리 (여러 번 지정 가능)')
    ap.add_argument('--encoding', default='auto', help="이름 인코딩 (기본 auto: utf-8/cp932/cp949 자동 판별)")
    a = ap.parse_args()
    with open(a.archive, 'rb') as f:
        buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        def extract(path, e, b):
            if a.recursive and e.name.lower().endswith('.noa'):
                return                        # 중첩 NOA 는 펼치기만 함
            dst = os.path.join(a.outdir, *path.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                with open(dst, 'wb') as o:
                    o.write(read_entry(b, e))
            except Exception as ex:
                print('   !! 건너뜀:', ex)
        walk(buf, a.recursive, on_file=extract if a.cmd == 'extract' else None, encoding=a.encoding, only=a.only)


if __name__ == '__main__':
    main()
