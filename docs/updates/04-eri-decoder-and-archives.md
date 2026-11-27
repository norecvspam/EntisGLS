# 업데이트 4 — ERI 디코더, 전체 NOA 목록, 1화 script.noa

(analysis-notes.md의 보충. 신뢰도 표기는 동일: [확정]/[추정]/[미확인])

## 1. system.noa 전체 추출 검증 [확정]

`tools/noa.py extract system.noa OUT -r` 실행 결과 (사용자 로그):
- 최상위 39개 + 중첩 4개(wm_*.noa) 내부 271개 = 파일 306개, **오류/건너뜀 0건**.
- 중첩 271개의 원본 크기 합계 = 14,504,498B (`wm_filelist.txt` 합계와 정확히 일치).
- 중첩 엔트리는 전부 `enc=0`(raw): 압축은 `wm_*.noa` 바깥 층에서만 한 번 적용된다.
- 주의: 검증은 크기 일치까지다. 바이트 내용 일치는 `black.eri`(원본 대조)와 IDR_COTOMI(정상 XML), ERI 이미지 24장(육안)으로 확인했다. 전체 해시 대조는 GARbro 추출본과 비교하면 된다 [미확인].

## 2. 0화 NOA 8개 목록 [확정]

`tools/noa.py list` 결과 (모두 `enc=0` = **무압축·무암호화**):

| 아카이브 | 파일 수 | 용량 | 확장자 |
|---|---|---|---|
| bg.noa | 389 | 364.2MB | eri (배경) |
| bs.noa | 2176 | 107.7MB | eri (캐릭터 스프라이트) |
| ev.noa | 326 | 295.6MB | eri (이벤트 CG) |
| bgm.noa | 16 | 29.8MB | mio |
| se.noa | 221 | 20.5MB | mio |
| voice.noa | 606 | 29.8MB | mio |
| extra.noa | 28 | 0.9MB | eri |
| ending.noa | 20 | 0.5MB | eri |

- `attr` 값은 `0x01000000`(ev.noa만 `0`)이며 디렉터리/종료 표식(0x10/0x20/0x40)이 아니라 일반 파일이다.
- 이름은 확장자를 뺀 **플랫 네임스페이스**이고, system.noa 포함 총 4062개 이름이 **아카이브 간 중복 0건**이다 → VFS는 `이름 → (아카이브, 확장자)` 단일 해시맵으로 충분하다.
- `通常シーン2（深月） ヘアゴム.srcxml`이 참조하는 리소스 64개(bg/char/se/bgm/scrnfilter/voices)가 이 인덱스로 **전부 해석된다**. 예: `bg75a`→bg.noa, `l_mit_bade`→bs.noa, `se004`→se.noa, `bgm04`→bgm.noa, `sepia`→system.noa(tct), `mitu01100`→voice.noa.

## 3. 1화 `script.noa` [확정: GARbro 화면 / 미확인: 내부]

GARbro 캡처 기준 내용물 3개:

| 파일 | 크기 | 비고 |
|---|---|---|
| `script.csx` | 1,413,119 | **컴파일된 스크립트 모듈**로 보임. 0화 폴더에는 없음 |
| `start.xml` | 382 | `<xscript>` 형식. 개발 경로 `...\script\start.txt`, `<call target="ゾンビのあふれた世界で"/>` |
| `ゾンビのあふれた世界で.xml` | 984,138 | 1화 시나리오 본문(추정). 파일명은 사용자가 Hex로 확인 |

- 1화는 시나리오가 `.xml`(0화 한글패치는 `.srcxml`)이고, 진입점이 `start.xml` → 시나리오 이름 호출이다. VFS의 스크립트 이름 해석은 확장자 후보(`.srcxml`, `.xml`)를 모두 시도해야 한다.
- `script.csx`의 정체: (a) srcxml의 컴파일 캐시, (b) 게임 로직이 담긴 모듈 중 하나. 0화는 csx 없이 낱개 srcxml로 동작하므로 (a)일 가능성이 높지만 확정 불가. 파일을 직접 봐야 한다.
- GARbro에서 마지막 파일명이 깨진 것은 이름 바이트의 인코딩이 GARbro 설정과 달라서로 보인다. 저장 인코딩은 [미확인] → `script.noa` 실물로 확인 필요. (`noa.py`는 `--encoding` 옵션을 제공하며 기본 cp932.)

## 4. ERI 디코더 [확정: 검증됨]

`tools/eri.py` — GARbro `ImageERI.cs`/`EriReader.cs`(MIT)를 Python/numpy로 옮김 (원본은 Leshade Entis의 ERISA-Library).

- 지원: Lossless_ERI(`0x03020000`) + RunlengthGamma(`-1`), 8/24/32bpp, RGB/RGBA/Gray, 블록 8/16/32, 부분 블록, 상하 방향.
- 미지원(명시적 예외): Huffman/Nemesis/Arithmetic 아키텍처, 손실(DCT/LOT), `reference-file` 차분 이미지.
- 검증: system.noa 추출 ERI **24장 전부 성공**(0.2~2.2초/장). `black/white/red`는 단색 정확(BGR 0,0,0 / 255,255,255 / 0,0,255), `keikoku01`(심의 마크)·`keikoku04`(ATTENTION 화면, 노이즈 질감)는 육안으로 정확. 방향(아래→위 / vflip)·채널 순서(B,G,R,A) 확인.
- 이미지 포맷 규칙: 높이가 양수면 스트림이 **아래에서 위로**, 음수면 위에서 아래로 저장. 데이터는 `ImageFrm` 섹션 헤더 직후부터 시작. 압축 스트림은 블록(8/16/32)별로 [연산코드 4비트 | 감마 코드 런렁스] 구조.
- `alpha00~13.eri`는 8비트 그레이 **전환 마스크**이고, `alpha01`은 가로 블라인드 와이프 형태다 → 스크립트의 `alpha="N"`은 이 마스크 번호로 보는 것이 맞다 [추정 → 근거 강화]. 어느 번호가 어느 `alphaNN`인지(0 기반/1 기반)는 PC 관찰로 확인 필요.
- `keikoku*`/`taiken_keikoku`는 연령 등급·주의 문구 화면으로, 게임 시작 시 표시되는 것으로 보인다 [추정].

## 5. 다음 단계

- [ ] `tools/scan_eri.py`를 0화 NOA 전부에 실행해 **ERI 변형 분포**(아키텍처/손실 여부/reference-file) 확정 → 추가 디코더 경로 필요 여부 판단
- [ ] 1화 `script.noa` 실물 분석 (`script.csx` 구조, 파일명 인코딩)
- [ ] MIO 디코더 포팅 (`MioDecoder.cs`)
- [ ] srcxml 파서/VM 설계 시작, 스킨 로더 설계
