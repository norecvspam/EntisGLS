# 업데이트 5 — MIO(오디오) 디코더

(신뢰도 표기: [확정]/[추정]/[미확인])

## 1. MIO 포맷 [확정: 헤더·구조 / GARbro 소스와 샘플 3개 대조]

`Music Interleaved and Orthogonal transformed`. Entis 공통 헤더(0x40) 뒤에:

- `Header` 섹션 → `FileHdr` → `SoundInf`(40바이트): version, transformation, architecture, channels, rate, blocksets, subband_degree, total_samples, lapped_degree, bits
- `Stream` 섹션 → `SoundStm` 청크 반복. 청크 앞 8바이트: version(u8), flags(u8), reserved(u16), sample_count(u32). `flags & 1` = 선두 블록(Huffman 트리 초기화).

system.noa의 샘플 3개 헤더 (전부 동일 계열):

| 파일 | 채널 | 샘플레이트 | subband | 길이 |
|---|---|---|---|---|
| test_sample_se | 1 | 22050 | 9 (512) | 5.3s |
| test_sample_sysse | 1 | 22050 | 9 | 1.7s |
| test_sample_voice | 1 | 44100 | 10 (1024) | 8.8s |

공통: version `0x20300`, transformation `0x5`(LOT_ERI), architecture `-1`, 16bit, lapped 1.

## 2. 코덱 구조 [확정]

**LOT(Lapped Orthogonal Transform) 기반 손실 코덱 + 적응형 Huffman**.

1. 청크 헤더: 서브밴드마다 division code(2bit), weight code(32bit), coefficient(16bit)
2. 계수 스트림: **ERINA Huffman**(1차 문맥, 제로 런렁스 포함)으로 바이트 열 디코딩 후 상/하위 바이트를 합쳐 16bit 양자화 계수로 복원 (`architecture = -1`이어도 GARbro는 Huffman 경로를 쓴다)
3. 역양자화: 7구간 선형 보간 가중치 테이블 + `sqrt(2/n) * coefficient`
4. 역변환: OddGivens 역행렬 → IPLOT → ILOT(이전 블록과 오버랩) → IDCT → 반올림/클램프 → int16
5. 상태가 청크 사이에 이어진다: Huffman 트리와 오버랩 버퍼(`last_dct`)는 선두 블록이 아닌 한 유지

## 3. 구현과 검증 [확정]

`tools/mio.py` (GARbro MIT 기반, Python/numpy):
- IDCT는 원본 재귀 알고리즘을 단위 행렬에 적용해 **IDCT 행렬을 한 번 만든 뒤 행렬곱**으로 계산 (선형 변환이라 동등). 열 직교성 확인(비대각 오차 1e-12 수준).
- 샘플 3개 전부 디코드 성공: 샘플 수가 헤더의 `total_samples`와 일치(116,992 / 38,400 / 386,496).
- 파형·스펙트로그램 검증: `voice`는 말소리 하모닉스와 디지털 무음 구간, `se`는 두 번 두드린 음의 깨끗한 배음 구조, `sysse`는 광대역 감쇠음. 클리핑 없음, **블록 경계에서의 불연속(클릭) 없음** (경계 1차 차분 ≈ 전체 평균) → 오버랩 처리 정상.
- 한계: 내부 연산이 float64라 원본(float32) 대비 반올림에서 ±1 LSB 차이가 날 수 있다. 바이트 단위 대조는 아직 안 했다 [미확인] → GARbro로 같은 파일을 WAV로 내보내 비교하면 확인 가능.
- 미지원(예외 발생): `LOT_ERI_MSS`(0x105, 스테레오 mid/side), Nemesis 아키텍처, Lossless PCM 경로. 0화 `bgm.noa`가 스테레오인지/어느 변형인지는 **[미확인]** → `tools/scan_mio.py`로 확인.
- 속도: 8.8초 음성 약 0.9초 (Python). C++ 이식 시 BGM 스트리밍 디코드도 충분.

## 4. 다음 단계

- [ ] `python tools/scan_mio.py bgm.noa se.noa voice.noa --decode` 실행해 변형 분포와 디코드 성공률 확인 (스테레오/MSS 여부)
- [ ] 필요하면 `LOT_ERI_MSS` 경로 포팅 (`MioDecoder.cs`의 `*_MSS` 함수들)
- [ ] (선택) GARbro로 내보낸 WAV와 비교해 비트 일치율 확인
- [ ] 이후: srcxml 파서/VM, 스킨 로더, PC(SDL3) 프로토타입 설계
