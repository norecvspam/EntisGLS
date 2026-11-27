#!/usr/bin/env python3
"""ERISA-N (Nemesis) 압축 해제기 — NOA 엔트리(f2 = 0x80000010)용.

알고리즘 출처: GARbro (https://github.com/morkt/GARbro, MIT License)
  ArcFormats/Entis/ErisaNemesis.cs, EriReader.cs(ProbDecodeContext, ErisaProbModel), ArcNOA.cs
  Copyright (C) 2015-2018 morkt — MIT 라이선스 고지는 LICENSE-GARbro.txt 참고.
이 파일은 위 C# 구현을 Python으로 옮긴 것이다.
"""
M32 = 0xFFFFFFFF
ESC = -1
TOTAL_LIMIT = 0x2000
SYMBOL_SORT_MAX = 0x101
SUB_SORT_MAX = 0x80
SLOT_MAX = 0x800
SHIFT = (1, 3, 4, 5)
NEW_PROB_LIMIT = (0x01, 0x08, 0x10, 0x20)
NEM_BUF = 0x10000
NEM_MASK = 0xFFFF
NEM_IDX_MASK = 0xFF


class ProbModel:
    __slots__ = ('total', 'sorts', 'occ', 'sym', 'sub_occ', 'sub_sym')

    def __init__(self):
        self.total = 0
        self.sorts = 0
        self.occ = [0] * SYMBOL_SORT_MAX
        self.sym = [0] * SYMBOL_SORT_MAX
        self.sub_occ = [0] * SUB_SORT_MAX
        self.sub_sym = [0] * SUB_SORT_MAX

    def initialize(self):
        self.total = SYMBOL_SORT_MAX
        self.sorts = SYMBOL_SORT_MAX
        for i in range(0x100):
            self.occ[i] = 1
            self.sym[i] = i
        self.occ[0x100] = 1
        self.sym[0x100] = ESC
        for i in range(SUB_SORT_MAX):
            self.sub_occ[i] = 0
            self.sub_sym[i] = -1

    def half(self):
        t = 0
        for i in range(self.sorts):
            self.occ[i] = (self.occ[i] + 1) >> 1
            t += self.occ[i]
        self.total = t
        for i in range(SUB_SORT_MAX):
            self.sub_occ[i] >>= 1

    def increase(self, index):
        occured = self.occ[index] + 1
        self.occ[index] = occured
        symbol = self.sym[index]
        while True:
            index -= 1
            if index < 0:
                break
            if self.occ[index] >= occured:
                break
            self.occ[index + 1] = self.occ[index]
            self.sym[index + 1] = self.sym[index]
        index += 1
        self.occ[index] = occured
        self.sym[index] = symbol
        self.total += 1
        if self.total >= TOTAL_LIMIT:
            self.half()
        return index

    def add_symbol(self, symbol):
        index = self.sorts
        self.sorts += 1
        self.total += 1
        self.sym[index] = symbol
        self.occ[index] = 1
        return index


class InvalidStream(Exception):
    pass


class Decoder:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.ibuf = 0
        self.icount = 0
        # prob decode context
        self.phrase_len = ProbModel()
        self.phrase_idx = ProbModel()
        self.run_len = ProbModel()
        # nemesis state
        self.base = ProbModel()
        self.base.initialize()
        self.slots = [ProbModel() for _ in range(SLOT_MAX)]
        self.work_used = 0
        self.last = [0, 0, 0, 0]
        self.ilast = 0
        self.phrase_len.initialize()
        self.phrase_idx.initialize()
        self.run_len.initialize()
        self.code = self.get_nbits(32)
        self.augend = 0xFFFF
        self.postbits = 0
        self.nbuf = bytearray(NEM_BUF)
        self.nidx = 0
        self.nleft = 0
        self.nnext = 0
        self.lk_first = [0] * 256
        self.lk_index = [[0] * 256 for _ in range(256)]
        self.eof = False

    # --- bit reader ---
    def prefetch(self):
        if self.icount == 0:
            if self.pos >= len(self.data):
                return False
            chunk = self.data[self.pos:self.pos + 4]
            self.pos += 4
            if len(chunk) < 4:
                chunk = chunk + b'\0' * (4 - len(chunk))
            self.ibuf = int.from_bytes(chunk, 'big')
            self.icount = 32
        return True

    def get_bit(self):
        if not self.prefetch():
            return 1                      # EOF 표식
        v = -1 if (self.ibuf >> 31) & 1 else 0   # C#의 산술 시프트 결과(-1/0)를 재현
        self.icount -= 1
        self.ibuf = (self.ibuf << 1) & M32
        return v

    def get_nbits(self, n):
        code = 0
        while n:
            if not self.prefetch():
                break
            c = min(n, self.icount)
            code = ((code << c) | (self.ibuf >> (32 - c))) & M32
            n -= c
            self.icount -= c
            self.ibuf = (self.ibuf << c) & M32
        return code

    # --- arithmetic decoder ---
    def decode_index(self, m):
        acc = ((self.code * m.total) & M32) // self.augend
        if acc >= TOTAL_LIMIT:
            return -1
        wacc = acc & 0xFFFF
        wfs = 0
        i = 0
        while True:
            occ = m.occ[i]
            if wacc < occ:
                break
            wacc -= occ
            wfs += occ
            i += 1
            if i >= m.sorts:
                return -1
        self.code = (self.code - (self.augend * wfs + m.total - 1) // m.total) & M32
        self.augend = self.augend * occ // m.total
        while (self.augend & 0x8000) == 0:
            bit = self.get_bit()
            if bit == 1:
                self.postbits += 1
                if self.postbits >= 256:
                    return -1
                bit = 0
            self.code = ((self.code << 1) | (bit & 1)) & M32
            self.augend = (self.augend << 1) & M32
        self.code &= 0xFFFF
        return i

    def decode_code(self, m):
        i = self.decode_index(m)
        sym = ESC
        if i >= 0:
            sym = m.sym[i]
            m.increase(i)
        return sym

    # --- nemesis ---
    def _push(self, b):
        self.last[self.ilast] = b
        self.ilast = (self.ilast + 1) & 3
        self.lk_index[b][self.lk_first[b]] = self.nidx
        self.lk_first[b] = (self.lk_first[b] + 1) & NEM_IDX_MASK
        self.nbuf[self.nidx] = b
        self.nidx = (self.nidx + 1) & NEM_MASK

    def decode(self, count):
        out = bytearray()
        if self.eof:
            return bytes(out)
        base = self.base
        while len(out) < count:
            if self.nleft > 0:
                n = min(self.nleft, count - len(out))
                last_b = self.nbuf[(self.nidx - 1) & NEM_MASK]
                for _ in range(n):
                    b = last_b
                    if self.nnext >= 0:
                        b = self.nbuf[self.nnext]
                        self.nnext = (self.nnext + 1) & NEM_MASK
                    self._push(b)
                    last_b = b
                    out.append(b)
                self.nleft -= n
                continue

            model = base
            deg = 0
            while deg < 4:
                il = self.last[(self.ilast + 3 - deg) & 3] >> SHIFT[deg]
                s = model.sub_sym[il]
                if s < 0:
                    break
                if s >= self.work_used:
                    raise InvalidStream('Invalid Nemesis encoding sequence')
                model = self.slots[s]
                deg += 1
            isym = self.decode_index(model)
            if isym < 0:
                return bytes(out)
            nsym = model.sym[isym]
            model.increase(isym)

            nemesis = False
            if nsym == ESC:
                if model is not base:
                    isym = self.decode_index(base)
                    if isym < 0:
                        return bytes(out)
                    nsym = base.sym[isym]
                    base.increase(isym)
                    if nsym != ESC:
                        model.add_symbol(nsym)
                    else:
                        nemesis = True
                else:
                    nemesis = True
            if nemesis:
                pidx = self.decode_code(self.phrase_idx)
                if pidx == ESC:
                    self.eof = True
                    return bytes(out)
                if pidx == 0:
                    length = self.decode_code(self.run_len)
                else:
                    length = self.decode_code(self.phrase_len)
                if length == ESC:
                    return bytes(out)
                last_b = self.nbuf[(self.nidx - 1) & NEM_MASK]
                self.nleft = length
                if pidx == 0:
                    self.nnext = -1
                else:
                    self.nnext = self.lk_index[last_b][(self.lk_first[last_b] - pidx) & NEM_IDX_MASK]
                    if self.nbuf[self.nnext] != last_b:
                        raise InvalidStream('Invalid Nemesis encoding sequence')
                    self.nnext = (self.nnext + 1) & NEM_MASK
                continue

            b = nsym & 0xFF
            self._push(b)
            out.append(b)

            if self.work_used < SLOT_MAX and deg < 4:
                isymbol = b >> SHIFT[deg]
                if isymbol >= SUB_SORT_MAX:
                    raise InvalidStream('Invalid Nemesis encoding sequence')
                model.sub_occ[isymbol] += 1
                if model.sub_occ[isymbol] >= NEW_PROB_LIMIT[deg]:
                    parent = model
                    pm = base
                    i = 0
                    while i <= deg:
                        isymbol = self.last[(self.ilast + 3 - i) & 3] >> SHIFT[i]
                        s = pm.sub_sym[isymbol]
                        if s < 0:
                            break
                        if s >= self.work_used:
                            raise InvalidStream('Invalid Nemesis encoding sequence')
                        pm = self.slots[s]
                        i += 1
                    if i <= deg and pm.sub_sym[isymbol] < 0:
                        new = self.slots[self.work_used]
                        pm.sub_sym[isymbol] = self.work_used
                        self.work_used += 1
                        new.total = 0
                        j = 0
                        for k in range(parent.sorts):
                            wocc = (parent.occ[k] >> 4) & 0xFFFF
                            if wocc > 0 and parent.sym[k] != ESC:
                                new.total += wocc
                                new.occ[j] = wocc
                                new.sym[j] = parent.sym[k]
                                j += 1
                        new.total += 1
                        new.occ[j] = 1
                        new.sym[j] = ESC
                        j += 1
                        new.sorts = j
                        for k in range(SUB_SORT_MAX):
                            new.sub_occ[k] = 0
                            new.sub_sym[k] = -1
        return bytes(out)


def decompress(stream, out_len=None):
    """stream: 'filedata' 헤더 뒤의 저장 바이트 전체. out_len: 디렉터리의 원본 크기.
    NOA 엔트리는 GARbro와 같이 마지막 4바이트를 제외하고 해제한다."""
    if out_len is not None:
        stream = stream[:-4]
    d = Decoder(stream)
    return d.decode(out_len if out_len is not None else 1 << 30)


if __name__ == '__main__':
    import sys
    data = open(sys.argv[1], 'rb').read()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else None
    sys.stdout.buffer.write(decompress(data, n))
