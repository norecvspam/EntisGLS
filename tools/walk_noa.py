#!/usr/bin/env python3
"""NOA(ERISA-Archive) 디렉터리 워커 v2.

v1 대비 변경점
- 디렉터리의 size(원본 크기)와 데이터 블록 헤더의 stored size(저장 크기)를 둘 다 출력
- stored != size 이면 압축 엔트리(C)로 표시하고, 중첩 NOA도 압축 상태면 재귀하지 않고 건너뜀
- 플래그 두 개(f1, f2)와 데이터 처음 16바이트를 같이 출력 (압축/암호화 판별용 샘플)

사용법: python walk_noa.py system.noa [--peek 32]
(압축 해제까지 필요하면 noa.py 를 사용)
"""
import mmap, struct, sys

def read_dir(buf, base=0):
    assert bytes(buf[base:base+5]) == b'Entis', 'not an Entis container'
    d = base + 0x40
    assert bytes(buf[d:d+8]) == b'DirEntry', 'DirEntry not found'
    (count,) = struct.unpack_from('<I', buf, d + 16)
    pos, out = d + 20, []
    for _ in range(count):
        size, f1, f2, off = struct.unpack_from('<QIIQ', buf, pos); pos += 24
        sec, mi, hr, dow, day, mon, yr = struct.unpack_from('<6BH', buf, pos); pos += 8
        z, nlen = struct.unpack_from('<II', buf, pos); pos += 8
        name = bytes(buf[pos:pos+nlen]).rstrip(b'\0').decode('cp932'); pos += nlen
        blk = d + off
        assert bytes(buf[blk:blk+8]) == b'filedata', f'bad block header for {name}'
        (stored,) = struct.unpack_from('<Q', buf, blk + 8)
        out.append(dict(name=name, size=size, stored=stored, blk=blk, data=blk + 16,
                        f1=f1, f2=f2, z=z, ts=f'{yr:04d}-{mon:02d}-{day:02d} {hr:02d}:{mi:02d}:{sec:02d}'))
    return out

def walk(buf, base=0, depth=0, peek=16):
    for e in read_dir(buf, base):
        packed = e['stored'] != e['size']
        mark = 'C' if packed else '-'
        head = bytes(buf[e['data']:e['data'] + peek]).hex(' ')
        print('  ' * depth + f"[{mark}] {e['name']}  size={e['size']} stored={e['stored']} "
              f"f1=0x{e['f1']:08X} f2=0x{e['f2']:08X} z={e['z']} data@0x{e['data']:X}  {head}")
        if e['name'].lower().endswith('.noa'):
            if packed:
                print('  ' * (depth + 1) + '(압축된 중첩 NOA: noa.py -r 로 해제 후 재귀)')
            else:
                walk(buf, e['data'], depth + 1, peek)

if __name__ == '__main__':
    peek = 16
    if '--peek' in sys.argv:
        peek = int(sys.argv[sys.argv.index('--peek') + 1])
    with open(sys.argv[1], 'rb') as f:
        walk(mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ), peek=peek)
