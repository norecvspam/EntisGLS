# 업데이트 6 — script.csx 정체, EntisGLS4 SDK 소스, ERI 변형 분포, MIO 대조

(신뢰도 표기: [확정]/[추정]/[미확인])

## 1. script.noa (1화) 실물 분석 [확정]

- `noa.py`로 추출 성공 (3개, 크기 검증 통과). 저장 크기: csx 1,413,119B → 162,844B, 시나리오 XML 984,138B → 212,228B (ERISA-N 압축).
- **파일명 인코딩**: 3번째 이름의 바이트가 **cp949**로만 엄격 디코드된다 (`ゾンビのあふれた世界で.xml`). 한글패치 도구가 시스템 코드페이지로 저장한 것으로 보인다. → `noa.py`는 이제 `--encoding auto`(기본): utf-8 → cp932 → cp949 순으로 **모든 이름이 엄격하게 디코드되는 첫 인코딩**을 쓴다. (원본 일본판은 cp932일 것으로 추정 [미확인].)
- `start.xml`: `<call target="ゾンビのあふれた世界で"/>` 한 줄. 진입점이 `start` → 시나리오 이름 호출이다.
- 시나리오 XML(701K자, 12,421줄)은 **한글패치본**(한글 122,870자). 태그: msg 6522, page 1023, se 685, char 659, bg 567, ev 481, stopse 223, clear 157, begin_trans/end_trans 129, … + 0화에 없던 `layer`(9), `begin_replay`/`end_replay`(7), `msgshow`(2), `movie`(1), `ending`(1).
- **`wait_chgmv`가 이 XML에는 없다.** 0화 `.srcxml`에는 있었으므로, 0화 한글패치 쪽이 후처리 결과(srcxml)를 배포한 것이고 1화 XML은 후처리 전 원문이다 → "xml → (wait_chgmv 자동 삽입) → srcxml" 변환 단계가 존재한다 [추정].

## 2. `script.csx` = 게임 프레임워크 전체가 컴파일된 모듈 [확정: 구조 / 추정: 해석]

- 포맷: Entis 컮테이너, 설명 문자열 `Cotopha Image file`. 섹션: `header`, `image`(343KB, 코드), `classinf`(907KB), `function`, `initnfnc`, `funcinfo`, `symblinf`, `global`, `data`, `conststr`(91KB), `linkinf`, `impnativ`(네이티브 임포트 표) …
- **시나리오 텍스트는 들어 있지 않다** (한글 문장을 UTF-16으로 검색해도 없음). 태그 이름도 없다.
- 들어 있는 것: 클래스/함수 식별자 4293개. 게임 레벨 클래스 목록 → **`UITitle`, `UIConfig`, `UISave`, `UIExtraMode`, `UIGalleryMode`, `UIReplayMode`, `UICharacterSelect`, `UIScenarioSelect`, `SystemMenu`, `SystemMenuItems`, `SelectMenu`, `NVMessageWindow`, `NVMessageLogData`, `NVMessagePageLog`, `XScriptFile`, `XScriptFileManager`, `GenericLayerSet`, `TransitionParam`, `VoiceManager`, `Config`, `GraphicsConfiguration`, `MovieSprite`, `MessageSprite`, `MeshWarpBuffer`, `ToneFilter`, `InputFilter`** 등.
- 즉 **1화 이후의 UI/메시지창/시나리오 재생 로직은 Sakura2(Cotopha) 스크립트로 작성되어 csx로 컴파일**되어 있고, exe의 SakuraGL 네이티브 클래스(`Sprite`, `ResourceManager`, `File`, `Window`, `InputFilter`, `ToneFilter`, …)를 호출한다.
- 0화 폴더에는 csx가 없다. 0화에서 같은 기능을 어디서 제공하는지는 **[미확인]** (exe 내장 네이티브 구현 가능성: exe 문자열 풀에 명령 어휘/`m_*` 이름이 있음).

## 3. EntisGLS4 SDK 소스가 공개되어 있다 [확정: 존재 / 미확인: 라이선스 세부]

`SegaraRai/EntisGLS4Build`(비공식 빌드 저장소) README와 포함 헤더로 확인:
- 공식 사이트(entis.jp/gls)에서 **EntisGLS ver.4s.05 (gls4s.05.2015.04.18.zip)** 를 받아 쓰는 구조이고, 저장소는 패치·프로젝트 파일만 가진다. SDK 자체의 라이선스는 `https://www.entis.jp/gls/license.txt`가 적용된다고 명시되어 있다.
- 헤더(`include_wo`) 구성: `sakura`(기반 라이브러리), `rosetta`, `glscs`(**Sakura2 VM**: `glscs_sakura2_vm.h`, `env_vm`, `module`, `assembler`, **JIT: x86/SSE2/ARM**, 네이티브 객체 `obj_file/image/font/window/render/audio_player/…`), `sakuragl`(OpenGL 창/컨텍스트/렌더, 2D/3D, ERISA 연동), `sakuraglx`(스프라이트, UI, 표준 앱).
- 즉 exe 안의 `SakuraGL::*`, `ECSSakura2::*`, `SGL*` 클래스들이 **SDK 소스로 존재**한다. ARM JIT 헤더가 있다는 점은 모바일 이식의 단서다.
- **라이선스 원문은 확인하지 못했다** (이 환경에서 entis.jp에 접근 불가, 검색으로도 원문이 나오지 않음). 개인 사용 목적의 포팅/수정이 허용되는지는 `license.txt`를 직접 읽어 확인해야 한다 [미확인]. 소스를 이 저장소에 올리지 말 것.

## 4. 구현 전략 재평가

| | A: 게임 프레임워크 재구현 | B: SDK 런타임 이식 + `script.csx` 그대로 실행 |
|---|---|---|
| 근거 | 명령 어휘/스킨 XML/클래스 목록이 모두 드러나 있어 기능 목록은 명확 | SDK 소스(VM, SakuraGL, ERISA)가 존재. csx가 UI·시나리오 재생을 전부 담당 |
| 장점 | 모바일 UI 최적화 자유. VM 불필요 | 1~3화 동작이 원본과 동일. 다른 EntisGLS4 게임도 같은 런처 가능 |
| 단점 | UI 시스템 전체를 직접 구현, 동작은 PC 관찰에 의존 | Windows 전용 부분(창, DirectSound, DirectShow, GDI+, WinINet 등)을 SDL3/GLES/Android로 교체해야 함. 규모 큼 |
| 선결 | — | **SDK 라이선스 확인**, SDK 입수(사용자가 공식 사이트에서 다운로드) |

0화는 csx가 없으므로 A 방식(또는 exe 내장 로직 분석)이 필요하고, 1~3화는 B가 자연스럽다. **0화 동작의 출처 확인과 SDK 라이선스 확인이 다음 결정의 열쇠**다.

## 5. ERI 변형 분포 (scan_eri 결과, 2939개) [확정]

| 아키텍처 | 버전 | 형식 | 개수 | 위치 |
|---|---|---|---|---|
| **Huffman + reference-file** | 0x20200 | RGBA 32bpp, 블록 8 | **2086** | bs.noa (캐릭터 스프라이트) |
| **Huffman** | 0x20200 | RGB 24bpp | 578 | bg.noa 388, ev.noa 190 (1280×720) |
| Gamma | 0x20100 | RGB 24bpp | 154 | ev 125, ending 1, extra 28 (192×108 썸네일 포함) |
| Gamma | 0x20100 | RGBA 32bpp | 90 | bs.noa |
| Gamma | 0x20100 | RGB 32bpp | 19 | ending.noa |
| Huffman | 0x20200 | RGBA 32bpp | 12 | bg 1, ev 11 (1280×720, 1266×720) |

- 전부 `Lossless_ERI`, 블록 8, 아래→위. **손실(DCT) 변형은 없다.**
- → **Huffman 경로와 reference-file이 필수**다 (2098개 = 71%). 이번 업데이트에서 `tools/eri.py`에 추가했다.
- 구현: MIO와 공용인 ERINA Huffman 컨텍스트 재사용. Huffman ERI(v0x20200)는 연산코드용 별도 트리(`HTree`)를 쓰고, 계수는 order-1 Huffman으로 디코드. reference-file은 description의 `#reference-file` 태그가 가리키는 ERI를 먼저 디코드해 **바이트 단위로 더한다**(알파 포함).
- 회귀 검증: Gamma 경로는 시스템 ERI 24장에서 이전 구현과 **24/24 동일**. **Huffman/reference 경로는 실제 샘플로 아직 검증하지 못했다** [미확인] → 샘플 필요.

## 6. MIO — GARbro WAV와의 대조 [확정]

`system.noa` 안 MIO 3개(`test_sample_*`)를 GARbro가 내보낸 WAV와 샘플 단위 비교:

| 파일 | 길이/채널/레이트 | 불일치 샘플 | 최대 차이 |
|---|---|---|---|
| test_sample_se | 일치 | 599 / 116,992 (0.51%) | 1 |
| test_sample_sysse | 일치 | 152 / 38,400 (0.40%) | 1 |
| test_sample_voice | 일치 | 2,845 / 386,496 (0.74%) | 1 |

→ 99.3% 이상이 비트 단위로 동일하고 나머지는 ±1 LSB (내부 float64 vs 원본 float32 반올림). 체계적 오류 없음.
- `wm_extra`의 SE 8개 중 **3개가 스테레오 44.1kHz**(`SE_BUTTON_CFG_FOCUS`, `SE_BUTTON_FOCUS`, `SE_SILENT`) → 스테레오 경로는 실제 MIO 파일이 있어야 검증 가능.
- `scan_mio.py`가 출력 없이 멈춘 원인은 전부 디코딩하려던 것(Python이라 느림)으로 추정. 진행 표시와 `--per-group`(기본 3) 제한을 추가했다.

## 7. 다음 단계

- [ ] **SDK 라이선스 확인** (사용자): `https://www.entis.jp/gls/license.txt` 내용 공유
- [ ] 샘플 업로드로 Huffman/reference ERI 검증: `bg01a.eri`, `BG101a.eri`(RGBA Huffman), `kdu_aaaa.eri` + 참조 파일, (가능하면 GARbro가 내보낸 PNG)
- [ ] 스테레오 MIO 3개(`SE_BUTTON_CFG_FOCUS/FOCUS/SE_SILENT.mio`)로 스테레오 경로 검증
- [ ] 0화에서 csx 없이 동작하는 근거 조사 (exe 분석 또는 원본 0화 구성 확인)
- [ ] `scan_mio.py bgm.noa se.noa voice.noa`(헤더만) 결과
