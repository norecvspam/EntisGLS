#!/usr/bin/env python3
"""NOA 안의 모든 .mio 헤더(코덱 변형 분포)를 조사하고, 선택적으로 실제 디코딩까지 시험한다.

사용법: python scan_mio.py bgm.noa se.noa voice.noa system.noa [--decode] [--per-group N] [--wav OUTDIR]
  (기본) 헤더만 읽는다 — 수 초면 끝난다. 먼저 이것만 실행해 보세요.
  --decode      : 변형(그룹)마다 앞에서 N개(기본 3)만 실제로 디코딩해 성공/실패를 확인 (Python 디코더는 느리다: 3분짜리 BGM 한 곡에 수십 초)
  --per-group N : --decode 시 그룹당 디코드할 개수 (0 = 전부)
  --wav DIR     : 디코딩한 결과를 WAV로 저장 (--decode 필요)
진행 상황은 stderr 로 바로바로 출력된다 (멈춘 것처럼 보이면 마지막 줄의 파일이 원인).
"""
import collections, mmap, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noa, mio

TRANS = {0x03020000: 'Lossless_ERI', 0x5: 'LOT_ERI', 0x105: 'LOT_ERI_MSS'}
ARCH = {-1: 'Gamma', -4: 'Huffman', -16: 'Nemesis', 32: 'Arithmetic'}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    wav_dir = None
    if '--wav' in sys.argv:
        wav_dir = sys.argv[sys.argv.index('--wav') + 1]; args = [a for a in args if a != wav_dir]
        os.makedirs(wav_dir, exist_ok=True)
    do_decode = '--decode' in sys.argv
    per_group = int(sys.argv[sys.argv.index('--per-group') + 1]) if '--per-group' in sys.argv else 3
    args = [a for a in args if a != str(per_group) or '--per-group' not in sys.argv]
    groups = collections.OrderedDict()
    fails = []
    total = 0
    t0 = time.time()
    for path in args:
        print(f'[scan] {path}', file=sys.stderr, flush=True)
        with open(path, 'rb') as f:
            buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            for e in noa.read_dir(buf):
                if not e.name.lower().endswith('.mio'):
                    continue
                total += 1
                try:
                    data = noa.read_entry(buf, e)
                    info = mio.read_header(data)
                    key = (TRANS.get(info.transformation, hex(info.transformation)), ARCH.get(info.architecture, info.architecture),
                           f'{info.channels}ch', f'{info.rate}Hz', f'{info.bits}bit', f'subband={info.subband_degree}',
                           f'lapped={info.lapped}', hex(info.version))
                    g = groups.setdefault(key, {'n': 0, 'ex': [], 'arc': collections.Counter(), 'ok': 0, 'dur': 0.0, 'tried': 0})
                    g['n'] += 1; g['arc'][os.path.basename(path)] += 1
                    if len(g['ex']) < 3: g['ex'].append(e.name)
                    if do_decode and (per_group == 0 or g['tried'] < per_group):
                        g['tried'] += 1
                        print(f'  [decode] {e.name} ({info.channels}ch {info.rate}Hz) ...', file=sys.stderr, flush=True)
                        try:
                            _, pcm = mio.decode(data)
                            g['ok'] += 1
                            g['dur'] += len(pcm) / info.channels / info.rate
                            if wav_dir:
                                mio.write_wav(info, pcm, os.path.join(wav_dir, os.path.splitext(e.name)[0] + '.wav'))
                        except Exception as ex:
                            fails.append((e.name, type(ex).__name__, str(ex)[:80]))
                except Exception as ex:
                    fails.append((e.name, type(ex).__name__, str(ex)[:80]))
    print(f'총 MIO {total}개 / 변형 {len(groups)}종 / 실패 {len(fails)}개 / {time.time() - t0:.0f}s\n')
    for k, g in sorted(groups.items(), key=lambda kv: -kv[1]['n']):
        extra = f"  디코드 성공 {g['ok']}/{g['tried']} 시도 (총 {g['dur']:.0f}s 분량)" if do_decode else ''
        print(' | '.join(str(x) for x in k), f"→ {g['n']}{extra}")
        print('     아카이브:', dict(g['arc']), ' 예:', g['ex'])
    for x in fails[:30]:
        print('FAIL', x)


if __name__ == '__main__':
    main()
