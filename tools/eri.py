#!/usr/bin/env python3
"""ERI(Entis Rasterized Image) 디코더 — 무손실(Lossless_ERI) + 런렁스 감마 코드(RunlengthGamma) 경로.

알고리즘 출처: GARbro (https://github.com/morkt/GARbro, MIT License)
  ArcFormats/Entis/ImageERI.cs, EriReader.cs  (원본: E R I S A - L i b r a r y,
  Copyright (C) 2002-2004 Leshade Entis, Entis-soft; C# port by morkt)
MIT 라이선스 고지는 LICENSE-GARbro.txt 참고. 이 파일은 위 C# 구현을 Python/numpy로 옮긴 것이다.

지원: transformation 0x03020000(Lossless), architecture -1(RunlengthGamma) / -4(RunlengthHuffman, ERI v0x20200),
      RGB/RGBA/Gray, 8/24/32bpp, 'reference-file' 차분 이미지(resolver 콜백 필요)
미지원(예외 발생): Nemesis/Arithmetic 아키텍처, 손실(DCT/LOT) 변환
"""
import struct
import numpy as np
import mio          # ERINA Huffman (MIO 와 공용)

CV_LOSSLESS_ERI = 0x03020000
ARCH_GAMMA, ARCH_HUFFMAN, ARCH_NEMESIS, ARCH_ARITH = -1, -4, -16, 32
T_RGB, T_GRAY, T_RGBA = 0x1, 0x2, 0x04000001


class EriError(Exception):
    pass


class _Huff(mio.HuffmanContext):
    """ERI 용 HuffmanDecodeContext: 생성 직후 flags=0 (PrepareToDecodeERINACode 전에 연산코드를 읽을 때 사용)"""

    def __init__(self):
        super().__init__()
        self.flags = 0

    def code(self, tree):
        return self._code(tree, False)


def parse_tags(desc):
    """GARbro ParseTagInfo: '#tag' 줄 다음에 오는 값 줄들을 모아 {tag: value} 로 반환"""
    tags = {}
    if not desc:
        return tags
    desc = desc.replace('\0', '')
    if desc[0] != '#':
        tags['comment'] = desc
        return tags
    lines = desc.splitlines()
    i = 0
    import re
    while i < len(lines):
        m = re.match(r'^\s*#\s*(\S+)', lines[i])
        if not m:
            break
        tag = m.group(1)
        val = []
        i += 1
        while i < len(lines):
            ln = lines[i]
            if ln.startswith('#'):
                if len(ln) < 2 or ln[1] != '#':
                    break
                ln = ln[1:]
            val.append(ln)
            i += 1
        tags[tag] = '\n'.join(val)
    return tags


class EriInfo:
    pass


def read_info(data):
    """ERI 헤더 파싱. 반환: EriInfo (stream_pos 는 'ImageFrm' 섹션 헤더 이후의 데이터 시작 오프셋)"""
    if data[:8] != b'Entis\x1a\x00\x00':
        raise EriError('not an Entis file')
    fid = struct.unpack_from('<I', data, 8)[0]
    if fid not in (0x03000100, 0x02000100):
        raise EriError('not an ERI (id=0x%08X)' % fid)
    desc0 = data[0x10:0x38].split(b'\0')[0]
    if not desc0.startswith((b'Entis Rasterized Image', b'Moving Entis Image', b'EMSAC-Image')):   # GARbro AsciiEqual = 접두어 비교
        raise EriError('bad description')
    sid, slen = data[0x40:0x48], struct.unpack_from('<Q', data, 0x48)[0]
    if sid != b'Header  ' or slen <= 0:
        raise EriError('Header section not found')
    info = EriInfo()
    info.description = None
    pos = 0x50
    header_size = int(slen)
    stream_pos = 0x50 + header_size
    got = False
    while header_size > 0x10:
        sid = data[pos:pos + 8]; (ln,) = struct.unpack_from('<Q', data, pos + 8); pos += 16
        header_size -= 0x10
        if ln <= 0 or ln > header_size:
            break
        if sid == b'ImageInf':
            (ver, trans, arch, fmt, w, h, bpp, clip, samp) = struct.unpack_from('<iIiIiiiii', data, pos)
            qb, ab = struct.unpack_from('<QQ', data, pos + 36)
            bd, lap, ft, fd = struct.unpack_from('<iiii', data, pos + 52)
            if ver not in (0x00020100, 0x00020200):
                raise EriError('bad ImageInf version')
            info.version, info.transformation, info.architecture, info.format_type = ver, trans, arch, fmt
            info.width, info.height, info.vflip = abs(w), abs(h), h < 0
            info.bpp, info.clipped, info.sampling = bpp, clip, samp
            info.blocking_degree = bd
            got = True
        elif sid == b'descript':
            raw = data[pos:pos + ln]
            try:
                info.description = (raw[2:].decode('utf-16le') if raw[:2] == b'\xff\xfe' else raw.decode('utf-8', 'replace'))
            except Exception:
                pass
        pos += ln
        header_size -= ln
    if not got:
        raise EriError('ImageInf not found')
    # 'ImageFrm' 섹션까지 이동 (GARbro ReadImageData)
    pos = stream_pos
    info.palette = None
    while True:
        if pos + 16 > len(data):
            raise EriError('ImageFrm not found')
        sid = data[pos:pos + 8]; (ln,) = struct.unpack_from('<Q', data, pos + 8); pos += 16
        if sid == b'Stream  ':
            continue
        if sid == b'ImageFrm':
            break
        if sid == b'Palette ' and info.bpp <= 8 and ln <= 0x400:
            info.palette = data[pos:pos + ln]
        pos += ln
    info.stream_pos = pos
    return info


class Bits:
    """ERISADecodeContext 의 비트 읽기. 전체 스트림을 0/1 바이트열로 펼쳐 둔다 (4바이트 단위 0 패딩)."""

    def __init__(self, data):
        pad = (-len(data)) % 4
        arr = np.frombuffer(bytes(data) + b'\0' * pad, dtype=np.uint8)
        self.b = np.unpackbits(arr).tobytes()
        self.n = len(self.b)
        self.p = 0
        self.flg_zero = 0
        self.length = 0

    def nbits(self, n):
        code = 0
        b, p, e = self.b, self.p, self.n
        while n and p < e:
            code = (code << 1) | b[p]; p += 1; n -= 1
        self.p = p
        return code

    def abit(self):
        if self.p >= self.n:
            return 1
        v = -self.b[self.p]            # 1 비트 → -1, 0 비트 → 0 (C# 산술 시프트 결과)
        self.p += 1
        return v

    def init_gamma(self):
        self.flg_zero = self.abit()
        self.length = 0

    def gamma(self):
        b, p, e = self.b, self.p, self.n
        if p >= e:
            return 0
        if b[p] == 0:
            self.p = p + 1
            return 1
        p += 1
        if p >= e:
            self.p = p
            return 0
        code, base = 0, 2
        while True:
            if p >= e:
                self.p = p; return 0
            x = b[p]; p += 1
            code = (code << 1) | x
            if p >= e:
                self.p = p; return 0
            y = b[p]; p += 1
            if y == 0:
                self.p = p
                return code + base
            base <<= 1

    def decode_gamma_bytes(self, out, count):
        """RLEDecodeContext.DecodeGammaCodeBytes. out: int16/int 리스트(길이>=count). 반환: 디코드한 개수"""
        dst = 0
        decoded = 0
        if self.length == 0:
            self.length = self.gamma()
            if self.length == 0:
                return decoded
        while True:
            rep = min(self.length, count)
            self.length -= rep
            count -= rep
            if self.flg_zero == 0:
                decoded += rep
                for _ in range(rep):
                    out[dst] = 0; dst += 1
            else:
                for _ in range(rep):
                    sign = self.abit()
                    code = self.gamma()
                    if code == 0:
                        return decoded
                    decoded += 1
                    v = (code ^ sign) - sign
                    out[dst] = ((v + 128) & 0xFF) - 128; dst += 1
            if count == 0:
                if self.length == 0:
                    self.flg_zero = ~self.flg_zero
                return decoded
            self.flg_zero = ~self.flg_zero
            self.length = self.gamma()
            if self.length == 0:
                return decoded


def _arrange_tables(bs, ch):
    A = bs * bs
    S = A * ch
    t = [None] * 4
    t[0] = np.arange(S)
    t1 = []
    l = 0
    for i in range(ch):
        for j in range(bs):
            m = l + j
            for k in range(bs):
                t1.append(m); m += bs
        l += A
    t[1] = np.array(t1)
    t2 = []
    for i in range(A):
        k = i
        for j in range(ch):
            t2.append(k); k += A
    t[2] = np.array(t2)
    t3 = []
    for i in range(bs):
        l = i
        for j in range(bs):
            m = l; l += bs
            for k in range(ch):
                t3.append(m); m += A
    t[3] = np.array(t3)
    return t


def decode(data, resolver=None, _depth=0):
    """ERI 파일 바이트 → (info, ndarray[H, W, C] uint8, 채널 순서 B,G,R(,A) 또는 Gray)

    resolver(name) -> bytes : 'reference-file' 차분 이미지가 참조하는 ERI 를 돌려주는 콜백 (같은 아카이브/폴더 기준)
    """
    info = read_info(data)
    if info.transformation != CV_LOSSLESS_ERI:
        raise EriError('unsupported transformation 0x%08X (lossy ERI)' % info.transformation)
    if info.architecture not in (ARCH_GAMMA, ARCH_HUFFMAN):
        raise NotImplementedError('architecture %d not implemented (Gamma/Huffman only)' % info.architecture)
    if info.blocking_degree == 0:
        raise EriError('bad blocking degree')
    arch = info.architecture
    if arch == ARCH_HUFFMAN and info.version != 0x00020200:
        raise NotImplementedError('Huffman ERI with ImageInf version 0x%X' % info.version)
    ref_name = ''
    tags = parse_tags(info.description)
    if 'reference-file' in tags:
        ref_name = tags['reference-file'].strip()
    ftype = info.format_type & 0xFFFF
    if ftype == 1:
        ch = 1 if info.bpp <= 8 else (3 if not (info.format_type & 0x04000000) else 4)
    elif ftype == 2:
        ch = 1
    else:
        raise EriError('unsupported format type 0x%X' % info.format_type)
    W, H, bpp = info.width, info.height, info.bpp
    bs = 1 << info.blocking_degree
    A = bs * bs
    S = A * ch
    wb = (W + bs - 1) >> info.blocking_degree
    hb = (H + bs - 1) >> info.blocking_degree
    tabs = _arrange_tables(bs, ch)

    br = Bits(data[info.stream_pos:])
    ver = br.nbits(8); fop = br.nbits(8); fenc = br.nbits(8); nbc = br.nbits(8)
    if fop != 0 or (fenc & 0xFE) != 0:
        raise EriError('bad stream header')
    if ver == 1:
        if nbc != 0: raise EriError('bad stream header')
    elif ver == 8:
        if nbc != 8: raise EriError('bad stream header')
    elif ver == 16:
        if nbc != 8 or fenc != 0: raise EriError('bad stream header')
    else:
        raise NotImplementedError('ERI stream version %d' % ver)
    if bpp not in (8, 24, 32):
        raise NotImplementedError('bpp %d' % bpp)

    ctx = optree = None
    if arch == ARCH_HUFFMAN:
        ctx = _Huff()
        ctx.attach(br)
        optree = mio.HTree()
    ops = None
    if (fenc & 1) and ch >= 3:
        if arch == ARCH_GAMMA:
            ops = [br.nbits(4) | 0xC0 for _ in range(wb * hb)]
        else:
            ops = [ctx.code(optree) & 0xFF for _ in range(wb * hb)]
    if br.abit() != 0:
        raise EriError('bad stream (first bit)')
    if arch == ARCH_GAMMA:
        if fenc & 1:
            br.init_gamma()
    else:
        ctx.prepare()

    out = np.zeros((H, W, ch), dtype=np.uint8)
    linebuf = np.zeros(ch * wb * bs, dtype=np.int8)
    arr = [0] * S
    nlines = bs * ch
    opi = 0
    left_h = H
    for py in range(hb):
        colbuf = np.zeros(nlines, dtype=np.int8)
        dh = min(bs, left_h)
        left_w = W
        lb = 0
        for px in range(wb):
            dw = min(bs, left_w)
            if ch >= 3:
                if fenc & 1:
                    op = ops[opi]; opi += 1
                elif arch == ARCH_HUFFMAN:
                    op = ctx.code(optree) & 0xFF
                else:
                    op = br.nbits(4) | 0xC0
                    br.init_gamma()
            else:
                op = 0xC0 if ftype == 2 else 0
                if not (fenc & 1) and arch == ARCH_GAMMA:
                    br.init_gamma()
            got = br.decode_gamma_bytes(arr, S) if arch == ARCH_GAMMA else ctx.decode_bytes(arr, S)
            if got < S:
                raise EriError('truncated stream at block (%d,%d)' % (px, py))
            a = np.array(arr, dtype=np.int8)
            cop, arr_code, diff = op & 0x0F, (op >> 4) & 3, (op >> 6) & 3
            if arr_code == 0:
                dec = a.copy()
                if op == 0:
                    pass_diff = False
                else:
                    pass_diff = True
            else:
                dec = np.empty(S, dtype=np.int8)
                dec[tabs[arr_code]] = a
                pass_diff = True
            if pass_diff:
                p = dec.reshape(ch, A)
                # 색 연산 (int8 래핑 덧셈)
                if cop == 0b0101: p[1] += p[0]
                elif cop == 0b0110: p[2] += p[0]
                elif cop == 0b0111: p[1] += p[0]; p[2] += p[0]
                elif cop == 0b1001: p[0] += p[1]
                elif cop == 0b1010: p[2] += p[1]
                elif cop == 0b1011: p[0] += p[1]; p[2] += p[1]
                elif cop == 0b1101: p[0] += p[2]
                elif cop == 0b1110: p[1] += p[2]
                elif cop == 0b1111: p[0] += p[2]; p[1] += p[2]
                rows = dec.reshape(nlines, bs)
                if diff & 1:
                    cs = np.cumsum(rows.astype(np.int16), axis=1) + colbuf.astype(np.int16)[:, None]
                    rows = (cs & 0xFF).astype(np.uint8).view(np.int8)
                    colbuf = rows[:, -1].copy()
                else:
                    colbuf = rows[:, -1].copy()
                # 세로 차분: 채널별로 [직전 줄 버퍼 + 누적합]
                dec = np.empty((ch, bs, bs), dtype=np.int8)
                rows3 = rows.reshape(ch, bs, bs)
                for k in range(ch):
                    seg = linebuf[lb + k * bs: lb + (k + 1) * bs].astype(np.int16)
                    cs = np.cumsum(rows3[k].astype(np.int16), axis=0) + seg[None, :]
                    res = (cs & 0xFF).astype(np.uint8).view(np.int8)
                    dec[k] = res
                    linebuf[lb + k * bs: lb + (k + 1) * bs] = res[-1]
                dec = dec.reshape(S)
            lb += nlines
            blk = dec.reshape(ch, bs, bs).view(np.uint8)
            # 복원: (ch, y, x) → (y, x, ch). 스트림 행 순서는 vflip 이 아니면 아래→위
            y0 = py * bs
            piece = np.transpose(blk[:, :dh, :dw], (1, 2, 0))
            x0 = px * bs
            if info.vflip:
                out[y0:y0 + dh, x0:x0 + dw, :] = piece
            else:
                ys = H - 1 - y0
                out[ys - dh + 1:ys + 1, x0:x0 + dw, :] = piece[::-1]
            left_w -= bs
        left_h -= bs
    if ref_name:
        if ch < 3:
            raise EriError('reference-file on a non-color image')
        if resolver is None:
            raise NotImplementedError('image needs reference file %r (pass resolver=)' % ref_name)
        if _depth > 8:
            raise EriError('reference chain too deep')
        rdata = resolver(ref_name)
        if rdata is None:
            raise FileNotFoundError('referenced image not found: %s' % ref_name)
        rinfo, rimg = decode(rdata, resolver, _depth + 1)
        h = min(out.shape[0], rimg.shape[0]); w = min(out.shape[1], rimg.shape[1])
        out[:h, :w, :3] += rimg[:h, :w, :3]                      # uint8 래핑 덧셈 (원본: byte 덧셈)
        if out.shape[2] == 4 and rimg.shape[2] == 4:
            out[:h, :w, 3] += rimg[:h, :w, 3]
        info.reference = ref_name
    return info, out


def to_png(info, img, path):
    from PIL import Image
    if img.shape[2] == 1:
        Image.fromarray(img[:, :, 0], 'L').save(path)
    elif img.shape[2] == 3:
        Image.fromarray(img[:, :, ::-1], 'RGB').save(path)
    else:
        rgba = img[:, :, [2, 1, 0, 3]]
        Image.fromarray(np.ascontiguousarray(rgba), 'RGBA').save(path)


def dir_resolver(directory):
    """같은 폴더에서 (대소문자 무시) 참조 파일을 찾는 resolver. 확장자가 없으면 .eri 를 붙여 본다."""
    import os
    names = {n.lower(): n for n in os.listdir(directory)}

    def resolve(name):
        for cand in (name, name + '.eri'):
            n = names.get(cand.lower())
            if n:
                return open(os.path.join(directory, n), 'rb').read()
        return None
    return resolve


if __name__ == '__main__':
    import sys, time, os
    src, dst = sys.argv[1], sys.argv[2]
    ref_dir = sys.argv[sys.argv.index('--ref-dir') + 1] if '--ref-dir' in sys.argv else os.path.dirname(os.path.abspath(src))
    t = time.time()
    info, img = decode(open(src, 'rb').read(), dir_resolver(ref_dir))
    to_png(info, img, dst)
    print(f'{src}: {info.width}x{info.height} bpp={info.bpp} block={1 << info.blocking_degree} -> {dst} ({time.time() - t:.1f}s)')
