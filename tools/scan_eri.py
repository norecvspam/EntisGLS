#!/usr/bin/env python3
"""NOA 안의 모든 .eri 헤더를 훑어서 코덱 변형 분포를 요약한다 (디코딩은 하지 않음).

raw 엔트리는 앞 0x400바이트만 읽으므로 bg.noa(수백 MB)도 빠르다. 압축 엔트리는 해제가 필요해 느릴 수 있다.
사용법: python scan_eri.py bg.noa bs.noa ev.noa ending.noa extra.noa system.noa [--samples 3]
"""
import collections, mmap, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noa, eri

TRANS = {0x03020000: 'Lossless_ERI', 0x03010000: 'Lossless_EMI', 0x1: 'DCT', 0x5: 'LOT', 0x105: 'LOT_MSS'}
ARCH = {-1: 'Gamma', -4: 'Huffman', -16: 'Nemesis', 32: 'Arithmetic'}


def head_bytes(buf, e):
    stored = noa.stored_size(buf, e)
    if e.enc == noa.ENC_RAW:
        return bytes(buf[e.blk + 0x10:e.blk + 0x10 + min(stored, 0x400)])
    return noa.read_entry(buf, e)[:0x400]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    nsamp = 3
    if '--samples' in sys.argv:
        nsamp = int(sys.argv[sys.argv.index('--samples') + 1]); args = [a for a in args if a != str(nsamp)]
    groups = collections.OrderedDict()
    errors = collections.Counter()
    total = 0
    for path in args:
        with open(path, 'rb') as f:
            buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            for e in noa.read_dir(buf):
                if not e.name.lower().endswith('.eri'):
                    continue
                total += 1
                try:
                    h = head_bytes(buf, e)
                    info = eri.read_info(h)
                    ref = bool(info.description and 'reference-file' in info.description)
                    key = (TRANS.get(info.transformation, hex(info.transformation)), ARCH.get(info.architecture, info.architecture),
                           hex(info.format_type), info.bpp, 1 << info.blocking_degree if info.blocking_degree else 0,
                           'vflip' if info.vflip else 'bottom-up', hex(info.version), 'REFERENCE' if ref else '')
                    g = groups.setdefault(key, {'n': 0, 'ex': [], 'dims': collections.Counter(), 'arc': collections.Counter()})
                    g['n'] += 1
                    g['dims'][f'{info.width}x{info.height}'] += 1
                    g['arc'][os.path.basename(path)] += 1
                    if len(g['ex']) < nsamp:
                        g['ex'].append(e.name)
                except Exception as ex:
                    errors[(os.path.basename(path), type(ex).__name__ + ': ' + str(ex)[:60])] += 1
    print(f'총 ERI {total}개 / 변형 {len(groups)}종 / 오류 {sum(errors.values())}개\n')
    print('transformation | arch | format | bpp | block | 방향 | ver | ref  → 개수')
    for k, g in sorted(groups.items(), key=lambda kv: -kv[1]['n']):
        print(' | '.join(str(x) for x in k), f"→ {g['n']}")
        print('     크기:', dict(g['dims'].most_common(4)), ' 아카이브:', dict(g['arc']), ' 예:', g['ex'])
    for k, n in errors.items():
        print('ERROR', k, n)


if __name__ == '__main__':
    main()
