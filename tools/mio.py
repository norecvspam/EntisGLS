#!/usr/bin/env python3
"""MIO(Music Interleaved and Orthogonal transformed) 디코더 — LOT_ERI(손실) 경로, 모노/스테레오.

알고리즘 출처: GARbro (https://github.com/morkt/GARbro, MIT License)
  ArcFormats/Entis/AudioMIO.cs, MioDecoder.cs, ErisaMatrix.cs, EriReader.cs(HuffmanTree 등)
  (원본: ERISA-Library, Copyright (C) 2002-2004 Leshade Entis; C# port by morkt)
MIT 라이선스 고지는 LICENSE-GARbro.txt 참고. Python/numpy 이식. 내부 연산은 float64(원본은 float32)라
정수 반올림 단계에서 ±1 LSB 차이가 날 수 있다.

지원: transformation 0x5(LOT_ERI), architecture 비-Nemesis(GARbro와 같이 ERINA Huffman으로 디코드), 16bit, ch 1/2
미지원(예외): Lossless_ERI PCM 경로 일부, LOT_ERI_MSS(0x105) 스테레오, Nemesis 아키텍처
"""
import struct, wave, math
import numpy as np

CODE_FLAG = -0x80000000
H_ESCAPE = 0x7FFFFFFF
H_NULL = 0x8000
H_MAX = 0x4000
H_ROOT = 0x200
LOW31 = 0x7FFFFFFF
MIO_LEAD_BLOCK = 0x01


class MioError(Exception):
    pass


# ---------------------------------------------------------------- bit reader / gamma
class Bits:
    def __init__(self, data):
        pad = (-len(data)) % 4
        self.b = np.unpackbits(np.frombuffer(bytes(data) + b'\0' * pad, dtype=np.uint8)).tobytes()
        self.n = len(self.b)
        self.p = 0

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
        v = -self.b[self.p]
        self.p += 1
        return v

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


# ---------------------------------------------------------------- ERINA adaptive Huffman
class HNode:
    __slots__ = ('w', 'p', 'c')

    def __init__(self):
        self.w = 0; self.p = 0; self.c = 0

    def copy_from(self, o):
        self.w = o.w; self.p = o.p; self.c = o.c


class HTree:
    def __init__(self):
        self.t = [HNode() for _ in range(0x201)]
        self.sym = [H_NULL] * 0x100
        self.escape = H_NULL
        self.ptr = H_ROOT
        r = self.t[H_ROOT]
        r.w = 0; r.p = H_NULL; r.c = H_NULL

    def increase(self, e):
        self.t[e].w = (self.t[e].w + 1) & 0xFFFF
        self.normalize(e)
        if self.t[H_ROOT].w >= H_MAX:
            self.half_rebuild()

    def recount(self, parent):
        ch = self.t[parent].c
        self.t[parent].w = (self.t[ch].w + self.t[ch + 1].w) & 0xFFFF

    def normalize(self, e):
        t = self.t
        while e < H_ROOT:
            sw = e + 1
            w = t[e].w
            while sw < H_ROOT:
                if t[sw].w >= w:
                    break
                sw += 1
            sw -= 1
            if e == sw:
                e = t[e].p
                self.recount(e)
                continue
            if (t[e].c & CODE_FLAG) == 0:
                ch = t[e].c
                t[ch].p = sw; t[ch + 1].p = sw
            else:
                code = t[e].c & LOW31
                if code != H_ESCAPE: self.sym[code & 0xFF] = sw
                else: self.escape = sw
            if (t[sw].c & CODE_FLAG) == 0:
                ch = t[sw].c
                t[ch].p = e; t[ch + 1].p = e
            else:
                code = t[sw].c & LOW31
                if code != H_ESCAPE: self.sym[code & 0xFF] = e
                else: self.escape = e
            node = t[sw]
            e_par = t[e].p
            s_par = t[sw].p
            t[sw] = t[e]
            t[e] = node
            t[sw].p = s_par
            t[e].p = e_par
            self.recount(s_par)
            e = s_par

    def add_new(self, code):
        t = self.t
        if self.ptr > 0:
            self.ptr -= 2
            i = self.ptr
            new = t[i]
            new.w = 1
            new.c = CODE_FLAG | code
            self.sym[code & 0xFF] = i
            root = t[H_ROOT]
            if root.c != H_NULL:
                parent = t[i + 2]
                child = t[i + 1]
                child.copy_from(parent)
                if (child.c & CODE_FLAG) != 0:
                    cc = child.c & LOW31
                    if cc != H_ESCAPE: self.sym[cc & 0xFF] = i + 1
                    else: self.escape = i + 1
                parent.w = (new.w + child.w) & 0xFFFF
                parent.p = child.p
                parent.c = i
                new.p = child.p = i + 2
                self.normalize(i + 2)
            else:
                new.p = H_ROOT
                self.escape = i + 1
                esc = t[self.escape]
                esc.w = 1
                esc.p = H_ROOT
                esc.c = CODE_FLAG | H_ESCAPE
                root.w = 2
                root.c = i
        else:
            i = self.ptr
            ent = t[i]
            if ent.c == (CODE_FLAG | H_ESCAPE):
                ent = t[i + 1]
            ent.c = CODE_FLAG | code

    def half_rebuild(self):
        t = self.t
        nxt = H_ROOT
        i = H_ROOT - 1
        while i >= self.ptr:
            if (t[i].c & CODE_FLAG) != 0:
                t[i].w = ((t[i].w + 1) >> 1) & 0xFFFF
                t[nxt].copy_from(t[i]); nxt -= 1
            i -= 1
        nxt += 1
        i = self.ptr
        while True:
            t[i].copy_from(t[nxt])
            t[i + 1].copy_from(t[nxt + 1])
            nxt += 2
            c1, c2 = t[i], t[i + 1]
            if (c1.c & CODE_FLAG) == 0:
                ch = c1.c
                t[ch].p = i; t[ch + 1].p = i
            else:
                code = c1.c & LOW31
                if code == H_ESCAPE: self.escape = i
                else: self.sym[code & 0xFF] = i
            if (c2.c & CODE_FLAG) == 0:
                ch = c2.c
                t[ch].p = i + 1; t[ch + 1].p = i + 1
            else:
                code = c2.c & LOW31
                if code == H_ESCAPE: self.escape = i + 1
                else: self.sym[code & 0xFF] = i + 1
            weight = (c1.w + c2.w) & 0xFFFF
            if nxt <= H_ROOT:
                j = nxt
                while True:
                    if weight <= t[j].w:
                        t[j - 1].w = weight
                        t[j - 1].c = i
                        break
                    t[j - 1].copy_from(t[j])
                    j += 1
                    if j > H_ROOT:
                        t[H_ROOT].w = weight
                        t[H_ROOT].c = i
                        break
                nxt -= 1
            else:
                t[H_ROOT].w = weight
                t[H_ROOT].p = H_NULL
                t[H_ROOT].c = i
                c1.p = H_ROOT
                c2.p = H_ROOT
                break
            i += 2


class HuffmanContext:
    """HuffmanDecodeContext (ERINA, order-1). 비트 읽기는 Bits 객체를 attach 해서 쓴다."""

    def __init__(self):
        self.bits = None
        self.trees = None
        self.last = None
        self.length = 0
        self.flags = 1

    def attach(self, bits):
        self.bits = bits

    def prepare(self, flags=1):
        self.flags = flags
        self.length = 0
        if flags == 0:
            t0 = HTree(); tl = HTree()
            self.trees = [t0] + [t0] * 0xFF + [tl]
        else:
            self.trees = [HTree() for _ in range(0x101)]
        self.last = self.trees[0]

    def _code(self, tree, length_mode):
        bits = self.bits
        if tree.escape != H_NULL:
            entry = H_ROOT
            child = tree.t[H_ROOT].c
            b, n = bits.b, bits.n
            while True:
                if bits.p >= n:
                    return H_ESCAPE
                entry = child + b[bits.p]; bits.p += 1
                child = tree.t[entry].c
                if (child & CODE_FLAG) != 0:
                    break
            if self.flags != 0 or tree.t[H_ROOT].w < H_MAX - 1:
                tree.increase(entry)
            code = child & LOW31
            if code != H_ESCAPE:
                return code
        if length_mode:
            code = bits.gamma()
            if code == -1:
                return H_ESCAPE
        else:
            code = bits.nbits(8)
        tree.add_new(code)
        return code

    def decode_bytes(self, out, count):
        """DecodeErinaCodeBytes: out(list)에 부호 있는 바이트를 채우고 디코드한 개수를 반환"""
        tree = self.last
        i = 0
        if self.length > 0:
            ln = min(self.length, count)
            self.length -= ln
            while ln:
                out[i] = 0; i += 1; ln -= 1
        while i < count:
            sym = self._code(tree, False)
            if sym == H_ESCAPE:
                break
            out[i] = ((sym + 128) & 0xFF) - 128; i += 1
            if sym == 0:
                ln = self._code(self.trees[0x100], True)
                if ln == H_ESCAPE:
                    break
                ln -= 1
                if ln != 0:
                    self.length = ln
                    if i + ln > count:
                        ln = count - i
                    self.length -= ln
                    while ln > 0:
                        out[i] = 0; i += 1; ln -= 1
            tree = self.trees[sym & 0xFF]
        self.last = tree
        return i


# ---------------------------------------------------------------- LOT / DCT math
MIN_DCT_DEGREE, MAX_DCT_DEGREE = 2, 12
COS_PI4 = math.cos(math.pi / 4)
R2COS_PI4 = 2 * COS_PI4
_DCT_OF_K = {}


def _init_k():
    for i in range(1, MAX_DCT_DEGREE):
        n = 1 << i
        nr = math.pi / (4.0 * n)
        dr = nr + nr
        _DCT_OF_K[i] = np.array([math.cos(nr + dr * j) for j in range(n)])


_init_k()
K2 = _DCT_OF_K[1]


def _f32(x):
    return float(np.float32(x))


def create_revolve_parameter(deg):
    n = 1 << deg
    lc = 1
    m = n // 2
    while m >= 8:
        lc += 1; m //= 8
    rev = [[0.0, 0.0] for _ in range(lc * 8)]
    k = math.pi / (n * 2)
    nxt = 0
    step = 2
    while True:
        for i in range(7):
            ws = 1.0; a = 0.0
            for j in range(i):
                a += step
                ws = ws * rev[nxt + j][0] + rev[nxt + j][1] * math.cos(a * k)
            r = math.atan2(ws, math.cos((a + step) * k))
            rev[nxt + i][0] = _f32(math.sin(r))
            rev[nxt + i][1] = _f32(math.cos(r))
        nxt += 7
        step *= 8
        if not (step < n):
            break
    return rev


def odd_givens_inverse(buf, src, rev, deg):
    n = 1 << deg
    index = 1
    step = 2
    lc = (n // 2) // 8
    ridx = 0
    while True:
        ridx += 7
        index += step * 7
        step *= 8
        if lc <= 8:
            break
        lc //= 8
    k = index + step * (lc - 2)
    for j in range(lc - 2, -1, -1):
        s, c = rev[ridx + j]
        r1 = buf[src + k]; r2 = buf[src + k + step]
        buf[src + k] = r1 * c + r2 * s
        buf[src + k + step] = r2 * c - r1 * s
        k -= step
    while lc <= (n // 2) // 8:
        ridx -= 7
        step //= 8
        index -= step * 7
        for i in range(lc):
            k = i * (step * 8) + index + step * 6
            for j in range(6, -1, -1):
                s, c = rev[ridx + j]
                r1 = buf[src + k]; r2 = buf[src + k + step]
                buf[src + k] = r1 * c + r2 * s
                buf[src + k + step] = r2 * c - r1 * s
                k -= step
        lc *= 8


def fast_iplot(buf, src, deg):
    n = 1 << deg
    a = buf[src:src + n:2].copy()
    b = buf[src + 1:src + n:2].copy()
    buf[src:src + n:2] = 0.5 * (a + b)
    buf[src + 1:src + n:2] = 0.5 * (a - b)


def fast_ilot(dst, src1, s1, src2, s2, deg):
    n = 1 << deg
    r1 = src1[s1:s1 + n:2]
    r2 = src2[s2 + 1:s2 + n:2]
    dst[0:n:2] = r1 + r2
    dst[1:n:2] = r1 - r2


# FastDCT / FastIDCT: 원본 재귀 구조를 그대로 옮기되, 각 "원소"를 배치 벡터(열)로 취급해
# 단위 행렬을 넣으면 IDCT 행렬 M_d 를 얻는다. (선형 변환이므로 이후에는 M_d @ x 로 계산)
def _fast_dct(dst, d, interval, src, s, work, w, deg):
    if deg == MIN_DCT_DEGREE:
        r0 = src[s] + src[s + 3]
        r2 = src[s] - src[s + 3]
        r1 = src[s + 1] + src[s + 2]
        r3 = src[s + 1] - src[s + 2]
        dst[d] = 0.5 * (r0 + r1)
        dst[d + interval * 2] = COS_PI4 * (r0 - r1)
        r2 = K2[0] * r2
        r3 = K2[1] * r3
        r0 = r2 + r3
        r1 = R2COS_PI4 * (r2 - r3)
        r1 = r1 - r0
        dst[d + interval] = r0
        dst[d + interval * 3] = r1
    else:
        n = 1 << deg
        half = n >> 1
        for i in range(half):
            a = src[s + i]; b = src[s + n - i - 1]
            work[w + i] = a + b
            work[w + i + half] = a - b
        dstep = interval << 1
        _fast_dct(dst, d, dstep, work, w, src, s, deg - 1)
        k = _DCT_OF_K[deg - 1]
        s2 = w + half
        d2 = d + interval
        for i in range(half):
            work[s2 + i] = work[s2 + i] * k[i]
        _fast_dct(dst, d2, dstep, work, s2, work, w, deg - 1)
        p = d2
        for i in range(half):
            dst[p] = dst[p] + dst[p]
            p += dstep
        p = d2
        for i in range(1, half):
            dst[p + dstep] = dst[p + dstep] - dst[p]
            p += dstep


def _fast_idct(dst, d, src, s, interval, work, deg):
    if deg == MIN_DCT_DEGREE:
        a0 = src[s]
        a1 = COS_PI4 * src[s + interval * 2]
        b0 = a0 + a1
        b1 = a0 - a1
        a0 = K2[0] * src[s + interval]
        a1 = K2[1] * src[s + interval * 3]
        b2 = a0 + a1
        b3 = R2COS_PI4 * (a0 - a1)
        b3 = b3 - b2
        dst[d] = b0 + b2
        dst[d + 3] = b0 - b2
        dst[d + 1] = b1 + b3
        dst[d + 2] = b1 - b3
    else:
        n = 1 << deg
        half = n >> 1
        sstep = interval << 1
        _fast_idct(dst, d, src, s, sstep, work, deg - 1)
        k = _DCT_OF_K[deg - 1]
        odd = d + half
        nxt = s + interval
        for i in range(half):
            work[i] = src[nxt] * k[i]
            nxt += sstep
        _fast_dct(dst, odd, 1, work, 0, work, half, deg - 1)
        for i in range(half):
            dst[odd + i] = dst[odd + i] + dst[odd + i]
        for i in range(1, half):
            dst[odd + i] = dst[odd + i] - dst[odd + i - 1]
        quad = half >> 1
        for i in range(quad):
            a = dst[d + i]; b = dst[half + i]
            c = dst[half - 1 - i]; e = dst[d + n - 1 - i]
            r0 = a + b
            r3 = a - b
            r1 = c + e
            r2 = c - e
            dst[d + i] = r0
            dst[half - 1 - i] = r1
            dst[half + i] = r2
            dst[d + n - 1 - i] = r3


_IDCT_MAT = {}


def idct_matrix(deg):
    m = _IDCT_MAT.get(deg)
    if m is None:
        n = 1 << deg
        src = np.eye(n)                       # src[i] = i번째 단위벡터 (배치 열)
        dst = np.zeros((n, n))
        work = np.zeros((n, n))
        _fast_idct(dst, 0, src, 0, 1, work, deg)
        m = dst                               # dst[:, j] = IDCT(e_j) → out = M @ x
        _IDCT_MAT[deg] = m
    return m


# ---------------------------------------------------------------- MIO decoder
FREQ_WIDTH = (-6, -6, -5, -4, -3, -2, -1)


class SoundInfo:
    pass


def read_header(data):
    if data[:8] != b'Entis\x1a\x00\x00':
        raise MioError('not an Entis file')
    if struct.unpack_from('<I', data, 8)[0] != 0x03000100 or not data[0x10:0x28].startswith(b'Music Interleaved'):
        raise MioError('not a MIO')
    sid = data[0x40:0x48]
    (hl,) = struct.unpack_from('<Q', data, 0x48)
    if sid != b'Header  ':
        raise MioError('Header section missing')
    info = None
    pos = 0x50
    hs = int(hl)
    stream_pos = 0x50 + hs
    while hs > 0x10:
        sid = data[pos:pos + 8]; (ln,) = struct.unpack_from('<Q', data, pos + 8); pos += 16
        hs -= 0x10
        if ln <= 0 or ln > hs:
            break
        if sid == b'SoundInf':
            f = struct.unpack_from('<iIiiIIiIII', data, pos)
            info = SoundInfo()
            (info.version, info.transformation, info.architecture, info.channels, info.rate,
             info.blocksets, info.subband_degree, info.total_samples, info.lapped, info.bits) = f
            break
        pos += ln; hs -= ln
    if info is None:
        raise MioError('SoundInf not found')
    # 'Stream  ' 섹션 이후 'SoundStm' 청크들
    pos = stream_pos
    while True:
        if pos + 16 > len(data):
            raise MioError('Stream section missing')
        sid = data[pos:pos + 8]; (ln,) = struct.unpack_from('<Q', data, pos + 8); pos += 16
        if sid == b'Stream  ':
            break
        pos += ln
    chunks = []
    while pos + 16 <= len(data):
        sid = data[pos:pos + 8]; (ln,) = struct.unpack_from('<Q', data, pos + 8); pos += 16
        if sid != b'SoundStm':
            pos += ln; continue
        ver, flags, _, nsamp = struct.unpack_from('<BBHI', data, pos)
        chunks.append((ver, flags, nsamp, data[pos + 8:pos + ln]))
        pos += ln
    info.chunks = chunks
    return info


class Decoder:
    def __init__(self, info):
        self.info = info
        if info.channels not in (1, 2):
            raise MioError('bad channel count')
        if info.transformation == 0x105:
            raise NotImplementedError('LOT_ERI_MSS (stereo mid/side) not implemented')
        if info.transformation != 0x5:
            raise NotImplementedError('transformation 0x%X not implemented' % info.transformation)
        if info.architecture == -16:
            raise NotImplementedError('Nemesis architecture not implemented')
        if info.bits != 16 or not (8 <= info.subband_degree <= MAX_DCT_DEGREE) or info.lapped != 1:
            raise MioError('unsupported parameters')
        self.ch = info.channels
        self.deg = info.subband_degree
        self.huff = HuffmanContext()
        width = 1 << self.deg
        self.last_dct = np.zeros(self.ch * width * info.lapped)
        self.set_degree(self.deg)

    def set_degree(self, d):
        self.cur_deg = d
        self.n = 1 << d
        self.rev = create_revolve_parameter(d)
        self.fp = []
        j = 0
        for i in range(7):
            w = 1 << (d + FREQ_WIDTH[i])
            self.fp.append(j + w // 2)
            j += w

    def iquantize(self, qsrc, weight, coef):
        n = self.n
        scale = math.sqrt(2.0 / n)
        rc = scale * coef
        r = [1.0 / math.pow(2.0, (((weight >> (i * 5)) & 0x1F) - 15) * 0.5) for i in range(6)] + [1.0]
        fp = self.fp
        tab = np.empty(n)
        tab[:fp[0]] = r[0]
        i = fp[0]
        for j in range(1, 7):
            a = r[j - 1]
            k = (r[j] - a) / (fp[j] - fp[j - 1])
            idx = np.arange(i, fp[j])
            tab[i:fp[j]] = k * (idx - fp[j - 1]) + a
            i = fp[j]
        tab[i:n] = r[6]
        odd = (((weight >> 30) & 3) + 2) / 2.0
        tab[15::16] *= odd
        tab[n - 1] = float(coef)
        tab = 1.0 / tab
        return rc * tab * qsrc

    def _round(self, x, nsamp, out, dst_idx):
        v = np.where(x[:nsamp] >= 0, np.floor(x[:nsamp] + 0.5), np.ceil(x[:nsamp] - 0.5))
        v = np.clip(v, -0x8000, 0x7FFF).astype(np.int16)
        out[dst_idx:dst_idx + nsamp * self.ch:self.ch] = v

    def decode_chunk(self, ver, flags, nsamp, payload):
        info = self.info
        ch = self.ch
        W = 1 << self.deg
        ns = (nsamp + W - 1) & ~(W - 1)
        nsub = ns >> self.deg
        nall = ns * ch
        nallsub = nsub * ch
        bits = Bits(payload)
        self.huff.attach(bits)
        if bits.abit() != 0:
            raise MioError('bad chunk (first bit)')
        div = []
        wcode = []
        coef = []
        last_div = [-1] * ch
        for i in range(nsub):
            for j in range(ch):
                dc = bits.nbits(2)
                div.append(dc)
                if dc != last_div[j]:
                    if i != 0:
                        wcode.append(_s32(bits.nbits(32))); coef.append(bits.nbits(16))
                    last_div[j] = dc
                for k in range(1 << dc):
                    wcode.append(_s32(bits.nbits(32))); coef.append(bits.nbits(16))
        if nsub > 0:
            for i in range(ch):
                wcode.append(_s32(bits.nbits(32))); coef.append(bits.nbits(16))
        if bits.abit() != 0:
            raise MioError('bad chunk (second bit)')
        if flags & MIO_LEAD_BLOCK:
            self.huff.prepare()
        buf3 = [0] * (nall * 2)
        if self.huff.decode_bytes(buf3, nall * 2) < nall * 2:
            raise MioError('truncated chunk data')
        b3 = np.array(buf3, dtype=np.int64)
        hi = b3[:nall]
        lo = b3[nall:nall * 2]
        # buf2[i + j*W] = (lo & 0xFF) | ((hi ^ (lo >> 8)) << 8)   (i: 계수 인덱스, j: 블록 인덱스)
        val = (lo & 0xFF) | ((hi ^ (lo >> 8)) << 8)
        buf2 = np.zeros(nall, dtype=np.int64)
        buf2.reshape(nallsub, W)[:, :] = val.reshape(W, nallsub).T
        out = np.zeros(nsamp * ch, dtype=np.int16)

        self._nd = 0; self._nw = 0; self._nc = 0; self._ns = 0
        self._div, self._wcode, self._coef, self._buf2 = div, wcode, coef, buf2
        last_div = [-1] * ch
        rest = [nsamp] * ch
        dst = list(range(ch))
        cur = -1
        for i in range(nsub):
            for j in range(ch):
                dc = div[self._nd]; self._nd += 1
                cnt = 1 << dc
                self._lb = W * info.lapped * j
                lead = False
                if last_div[j] != dc:
                    if i != 0:
                        if cur != last_div[j]:
                            self.set_degree(self.deg - last_div[j]); cur = last_div[j]
                        n = min(rest[j], self.n)
                        self._post(out, dst[j], n)
                        rest[j] -= n; dst[j] += n * ch
                    last_div[j] = dc
                    lead = True
                if cur != dc:
                    self.set_degree(self.deg - dc); cur = dc
                for k in range(cnt):
                    if lead:
                        self._lead(); lead = False
                    else:
                        n = min(rest[j], self.n)
                        self._internal(out, dst[j], n)
                        rest[j] -= n; dst[j] += n * ch
        if nsub > 0:
            for i in range(ch):
                self._lb = W * info.lapped * i
                if cur != last_div[i]:
                    self.set_degree(self.deg - last_div[i]); cur = last_div[i]
                n = min(rest[i], self.n)
                self._post(out, dst[i], n)
                rest[i] -= n; dst[i] += n * ch
        return out

    # --- 블록 단위 (GARbro DecodeInternalBlock / DecodeLeadBlock / DecodePostBlock)
    def _take(self):
        w = self._wcode[self._nw]; c = self._coef[self._nc]
        self._nw += 1; self._nc += 1
        return w, c

    def _internal(self, out, dst_idx, nsamp):
        w, c = self._take()
        n = self.n
        mat = self.iquantize(self._buf2[self._ns:self._ns + n], w, c)
        self._ns += n
        odd_givens_inverse(mat, 0, self.rev, self.cur_deg)
        fast_iplot(mat, 0, self.cur_deg)
        work = np.empty(n)
        fast_ilot(work, self.last_dct, self._lb, mat, 0, self.cur_deg)
        self.last_dct[self._lb:self._lb + n] = mat[:n]
        mat = work
        x = idct_matrix(self.cur_deg) @ mat
        if nsamp:
            self._round(x, nsamp, out, dst_idx)

    def _half_buffer(self):
        n = self.n
        half = n // 2
        b1 = np.zeros(n, dtype=np.int64)
        b1[1::2] = self._buf2[self._ns:self._ns + half]
        self._ns += half
        return b1

    def _lead(self):
        w, c = self._take()
        n = self.n
        b1 = self._half_buffer()
        v = self.iquantize(b1, w, c)
        odd_givens_inverse(v, 0, self.rev, self.cur_deg)
        v[0:n:2] = v[1:n:2]
        fast_iplot(v, 0, self.cur_deg)
        self.last_dct[self._lb:self._lb + n] = v

    def _post(self, out, dst_idx, nsamp):
        w, c = self._take()
        n = self.n
        b1 = self._half_buffer()
        mat = self.iquantize(b1, w, c)
        odd_givens_inverse(mat, 0, self.rev, self.cur_deg)
        mat[0:n:2] = -mat[1:n:2]
        fast_iplot(mat, 0, self.cur_deg)
        work = np.empty(n)
        fast_ilot(work, self.last_dct, self._lb, mat, 0, self.cur_deg)
        x = idct_matrix(self.cur_deg) @ work
        if nsamp:
            self._round(x, nsamp, out, dst_idx)


def _s32(v):
    return v - (1 << 32) if v >= (1 << 31) else v


def decode(data):
    """MIO 파일 바이트 → (SoundInfo, int16 ndarray [샘플*채널] 인터리브)"""
    info = read_header(data)
    dec = Decoder(info)
    parts = []
    for ver, flags, nsamp, payload in info.chunks:
        parts.append(dec.decode_chunk(ver, flags, nsamp, payload))
    pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
    return info, pcm


def write_wav(info, pcm, path):
    with wave.open(path, 'wb') as w:
        w.setnchannels(info.channels)
        w.setsampwidth(2)
        w.setframerate(info.rate)
        w.writeframes(pcm.astype('<i2').tobytes())


if __name__ == '__main__':
    import sys, time
    t = time.time()
    info, pcm = decode(open(sys.argv[1], 'rb').read())
    write_wav(info, pcm, sys.argv[2])
    print(f'{sys.argv[1]}: {info.channels}ch {info.rate}Hz {len(pcm) // info.channels} samples '
          f'({len(pcm) / info.channels / info.rate:.2f}s) -> {sys.argv[2]} ({time.time() - t:.1f}s)')
