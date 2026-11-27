# EntisGLS 포팅 분석 노트

대상: ゾンビが溢れた世界で俺だけが襲われない 0화 (`zombie0.exe`, 2018-04-13 빌드)
작성 기준: 사용자가 제공한 파일(hexdump, srcxml, `system.noa` 추출본, `system.inf`, exe)과 GARbro 소스(MIT), Python 검증 결과.
신뢰도 표기: **[확정]** 데이터로 교차 검증됨 / **[추정]** 정황·기억 기반이라 검증 필요 / **[미확인]**

---

## 0. 정정 이력

- 2차 노트의 "스크립트 태그 이름이 exe 문자열에 없다"는 **틀렸다**. NUL 경계 정확 일치 검색으로 다시 보니 대부분의 태그/속성 이름이 exe의 UTF-16 문자열 풀에 있다 (5장). 따라서 "명령 로직이 `wm_*.noa`의 Sakura2 모듈에 있다"는 가설은 폐기하고, 명령 처리는 exe 네이티브/VM 쪽에 있다고 본다.
- `wm_*.noa`는 스크립트 모듈이 없는 UI 스킨 번들이다 (3.5, 3.6).

## 1. 전체 구조 요약

```
zombie0.exe  ── SakuraGL 런타임 + Sakura2 VM(JIT 포함), OpenGL, DirectSound 추정
  │   └ RCDATA IDR_COTOMI ── 부팅 설정 XML (ERISA-N 압축, 4장에서 해제 확인)
  ├ system.noa     ── alpha*.eri, *.tct, *.xml, *.mio, wm_*.noa(중첩, 압축)
  ├ bg/bgm/bs/ev/se/voice/ending/extra.noa  ── 게임 리소스
  └ script/*.srcxml (한글패치: 낱개) 또는 script.noa (1화~)
```

## 2. Entis 컨테이너 / NOA 포맷

### 2.1 공통 헤더 (64바이트) [확정]

| 오프셋 | 내용 |
|---|---|
| 0x00 | `"Entis" 1A 00 00` |
| 0x08 | u32 파일 종류 ID (NOA: `0x02000400`, ERI: `0x00030001`, TCT: `0xFFFFFFFF`) |
| 0x10 | 설명 문자열 (NOA `ERISA-Archive file`, ERI `Entis Rasterized Image`, MIO `Music Interleaved and Orthogonal transformed`, TCT `Tone curve filter file`) |
| 0x38 | u64 본문 길이 (= 파일 크기 − 64) |

### 2.2 NOA 디렉터리 [확정: 구조 / GARbro 소스와 데이터 교차 확인]

`0x40`부터 `"DirEntry"`, u64 디렉터리 길이, u32 엔트리 수, 이어서 엔트리 반복.

| 필드 | 크기 | 비고 |
|---|---|---|
| size | u64 | **원본(해제 후) 크기** |
| attr | u32 | `0x10` = 하위 디렉터리(블록 헤더 0x10 뒤에 `DirEntry`), `0x20`/`0x40` = 목록 종료. 일반 파일은 그 외(`ending.noa`는 `0x01000000`, `system.noa`는 `0`) |
| encryption | u32 | 저장 방식. 아래 표 |
| offset | u64 | `0x40` 기준 상대 오프셋 (`filedata` 블록 시작) |
| timestamp | 8B | 초, 분, 시, 요일, 일, 월, 연(u16) |
| extra_len | u32 | 이후 extra 바이트 수 (관측값은 항상 0) |
| name_len | u32 | NUL 포함 |
| name | name_len | 플랫 이름. cp932 가정 (GARbro는 구형 `EMSAC-Binary Archive`만 cp932 고정) |

데이터 블록: `"filedata"` + u64 **stored size** + 데이터. 다음 블록 오프셋 = 현재 + 16 + stored size.

`encryption` 값 (GARbro `EncType`):

| 값 | 의미 | 이 게임에서 관측 |
|---|---|---|
| `0x00000000` | Raw | `.mio` 3개, `keikoku03.eri` |
| `0x80000010` | ERISA 압축 (Nemesis) | 나머지 전부 |
| `0x40000000` | BSHF 암호화 (비밀번호) | 없음 |
| `0x20000000` | SimpleCrypt32 | 없음 |
| `0xC0000010` / `0xA0000010` | 압축+암호화 | 없음 |

- `system.noa` 39개 엔트리 전부에서 `enc == 0x80000010 ↔ stored < size` [확정].
- 압축 엔트리는 **마지막 4바이트를 제외**한 `stored − 4`바이트를 해제기에 넣고, 출력 길이는 디렉터리의 `size`로 제한한다 (GARbro `ArcNOA.OpenEntry`) [확정: `black.eri` 검증].
- 패커는 파일별로 "압축해서 줄면 압축, 아니면 raw"를 고른 것으로 보인다 [추정].
- 암호화 NOA의 비밀번호는 exe의 `IDR_COTOMI` XML에서 `<archive path= key=>`로 찾을 수 있는데(GARbro 방식), 이 게임의 `IDR_COTOMI`에는 `key`가 하나도 없다 [확정]. 다만 `system.noa` 외 다른 NOA의 `encryption` 값은 아직 확인하지 못했다 [미확인].

### 2.3 중첩 NOA [확정]

`system.noa` 안의 `wm_extra/title/window/xscenario.noa`는 모두 `0x80000010`(압축)이다. 해제하면 다시 `Entis` 헤더로 시작하는 NOA가 나오므로 재귀 처리한다 (`tools/noa.py -r`).

## 3. 리소스 포맷

### 3.1 ERI [확정: 관측값 / 추정: 필드 이름]

`Entis Rasterized Image`. 청크 `Header`(0xE4) → `FileHdr`(0x14) → `ImageInf`(0x44) → …
`ImageInf` 필드 순서(스펙 기억 기반): version=`0x00020100`, transformation=`0x03020000`, architecture=`0xFFFFFFFF`, format type, width, height, bpp.

| 파일 | format type | 크기 | bpp |
|---|---|---|---|
| `alpha00~13.eri` | `0x2` | 1280×720 | 8 (그레이, 전환 마스크로 추정) |
| `black/white/red.eri` | `0x1` | 1280×720 | 32 |
| `keikoku01~04.eri`, `taiken_keikoku.eri` | `0x1` | 1280×720 (`keikoku03`은 height −720) | 24 |
| `light.eri` | `0x04000001` | 800×−600 | 32 (RGBA) |
| `blur_effect_bk.eri` | `0x04000001` | 4011×720 | 32 (RGBA) |

- 높이가 음수면 top-down 배치로 보인다 [추정]. **기준 해상도는 1280×720** [확정] (`IDR_COTOMI`의 `<display width=1280 height=720>`와도 일치).
- 디코더 참조 구현: GARbro `ArcFormats/Entis/EriReader.cs`(2844줄), `ImageERI.cs`, `ErisaMatrix.cs` (MIT). 아직 포팅 전.

### 3.2 TCT (톤 커브 필터) [확정]

`Tone curve filter file`. 청크: `blue`(256) `green`(256) `red`(256) `alpha`(256) `curve`(가변) `info`(4, 일부만).
채널별 256엔트리 룩업 테이블이므로 `scrnfilter src="sepia"`는 **채널별 LUT 적용**으로 구현하면 된다 [추정: scrnfilter ↔ .tct 대응].
파일: `gray`, `light`, `sepia`, `yoru`, `yoru2`, `yu`. `curve`/`info`는 편집기용 메타데이터일 가능성이 높다 [추정].

### 3.3 MIO [확정: 헤더만]

`Music Interleaved and Orthogonal transformed`. `Header`(0x5C) → `FileHdr`(0x14) → `SoundInf`(0x28)…
`test_sample_se/sysse/voice.mio`는 설정 화면의 음량 테스트용으로 보인다 [추정]. 디코더 참조 구현: GARbro `MioDecoder.cs`(968줄), `AudioMIO.cs`. 아직 포팅 전.

### 3.4 XML [확정]

- `configuration.xml`: 캐릭터 3종 — `深月 id=mit voices=mitu`, `牧浦 id=mak voices=maku`, `その他`. `voices` 접두어가 스크립트의 `voices="mitu01100"` 파일명 접두어와 일치. 메시지/테두리 색 정의.
- `input.xml`: 키보드/마우스 → 가상 조이스틱 버튼(`button:0/1/2`), 커맨드(`ID_FULLSCREEN`, `ID_CONFIG`, `ID_SAVE`, `ID_LOAD`, `ID_PLAY_VOICE`, `ID_CHANGE_AUTO_MODE`, `ID_MSG_CLOSE`, `ID_LOG`, `ID_CHANGE_SKIP_MODE`) 매핑. F1~F8(0x70~0x77) = CONFIG, SAVE, LOAD, PLAY_VOICE, AUTO, MSG_CLOSE, LOG, SKIP. → 모바일 입력은 이 가상 패드 계층에 터치를 매핑하는 설계가 자연스럽다.

### 3.5 `wm_*.noa` (중첩 NOA) — 파일 목록 [확정]

원본 크기: `wm_extra` 3,962,619 / `wm_title` 1,878,748 / `wm_window` 5,513,650 / `wm_xscenario` 3,170,595. 합계 271개 파일, 13.83MB.
내용은 **`.eri`(UI 이미지, `ID_*`), `.mio`(효과음, `SE_*`), `system.inf`(스킨 XML) 뿐**이다.

| 모듈 | 용도 |
|---|---|
| `wm_title` | 타이틀 화면 (시작/로드/설정/CG모드/엔드롤/종료) |
| `wm_window` | 메시지창, 로그, 세이브/로드(10페이지×슬롯), 설정 3탭(화면/사운드/시스템), 캐릭터별 보이스, 스킵 범위, 우클릭 동작, 확인 팝업 |
| `wm_extra` | CG 갤러리(3페이지+썸네일), 음악 감상(16곡), 씬 회상 |
| `wm_xscenario` | 시나리오 선택(12개, 3페이지) |

각 모듈이 `SE_BUTTON_*`, `SE_OPEN_MENU`, `SE_SAVED`, `SE_SILENT`를 중복 포함한다(자기완결 스킨 번들).

### 3.6 `system.inf` = 선언형 스킨 XML [확정]

4개 파일(3.8KB / 10KB / 26.6KB / 90.8KB, 인코딩 선언 Shift_JIS, 내용은 ASCII)을 전부 파싱했다. **스크립트/코드는 없고** 순수 UI 정의다.

- 루트 `<skin>` → `<resource>`(`<sound id src>`, `<image id src>`) → `<declare_style>`(`<style id type>`) → `<page id width height x y>`/`<window id bg x y>` 아래 위젯.
- 위젯: `button`(199, `x y width height style tab_stop group pushed_se`), `static_text`(11), `scroll_bar`(9, `<bar range>`), 이미지(`<image id x y rsrc>`), `<command>`/`<basic_flag hit_transparency>`/`<status_notification parameter>`.
- 스타일 타입: `button`(arrange `button`/`radio`/`check`), `static_text`, `scroll_bar`(`horz`/`vert`). 버튼 상태는 스프라이트 시트 `RECT(x,y,w,h)` 참조: `normal` / `focus` / `pushed` / `disabled` / `active_pushed` / `pushed_focus`, 클릭 판정은 `mask`.
- 텍스트 스타일: `font`(size/face/bold/italic), `text`(color/transparency), `shadow`, `border`.
- 즉 모바일 UI는 **스킨 로더(약 25종 요소) 하나**로 4개 화면을 모두 재현할 수 있다. 터치 UI로의 재배치(큰 버튼, 안전영역)는 이 위에서 한다.

## 4. exe 부팅 설정 `IDR_COTOMI` [확정: 해제 성공]

`RCDATA IDR_COTOMI`(400B)를 ERISA-N 해제기로 풀면 1188바이트 Shift_JIS XML이 나온다.

```xml
<script src="script.csx">
  <save_dir path="$(CURRENT)\savedata"/>
  <save_dir version="6" platform="2" path="$(APPDATA)\seacoxx\zombie0"/>
  <icon id="IDI_MAIN" src="$(CURRENT)\system\main.ico"/>
  <archive path="$(CURRENT)\bg.noa"/> ... bs, bgm, se, ev, evm, system, extra, movie, ending, script, voice2, voice
  <file path="$(CURRENT)"/>  ... bs, bg, ev, bgm, se, system, movie, voice, script
  <display caption="ゾンビのあふれた世界で俺だけが襲われない０" width="1280" height="720"/>
</script>
```

- **VFS 마운트 목록**이 여기 있다: 아카이브 13개(없는 것은 건너뜀. 0화에는 `script.noa`/`voice2.noa`/`evm.noa`/`movie.noa`가 없음) + 낱개 파일 검색 디렉터리 10개. 낱개/아카이브 간 우선순위는 **[미확인]** (Process Monitor로 확인 필요).
- `script.csx`: 메인 스크립트 모듈 이름으로 보이나 0화 폴더에는 없다. 1화의 `script.noa` 안에 있는지 확인 필요 [미확인].
- 세이브 위치: 게임 폴더 `savedata`, 또는 `%APPDATA%\seacoxx\zombie0` → 모바일에서는 앱 전용 디렉터리로 대체.
- `archive`에 `key` 속성이 없으므로 이 게임은 NOA 암호화 비밀번호를 쓰지 않는다 [확정].

## 5. srcxml 스크립트와 exe 문자열 풀

### 5.1 srcxml

- 모든 태그에 `@l="줄번호"` 속성이 있어 **표준 XML 파서가 거부**한다(속성명에 `@`). 자체 파서 또는 `@l` → 다른 이름 치환이 필요 [확정].
- 태그 약 32종. `wait_chgmv` 495 = `bg` 293 + `ev` 202 → **변환기가 bg/ev 앞에 자동 삽입** [확정].
- `msg`는 NVL 방식: 줄이 쌓이고 `page_feed="true"` 뒤 `page fade=300`으로 페이지 비움, `add="true"`는 이어붙임 [추정].
- `begin_trans`~`end_trans`는 일괄 전환 [추정]. `alpha="1~5"` ↔ `alpha01~05.eri` 전환 마스크 [추정].

| 분류 | 태그 |
|---|---|
| 흐름 | label goto call return end_scene ending description select menu |
| 텍스트 | msg page |
| 화면 | bg ev char clear begin_trans end_trans wait_chgmv wait |
| 연출 | shake flash scrnfilter warp lfd |
| 오디오 | bgm stopbgm se stopse waitse (+ msg의 voices) |

### 5.2 exe의 UTF-16 문자열 풀 [확정]

`.rdata`의 file offset `0x2cf600~0x2d2a00`에 318개 문자열이 있고(`docs/exe-string-pool.txt`), 스크립트 태그 대부분이 포함된다 (`xscript`/`select`/`menu`/`bgm`/`fadeout`은 정확 일치로는 안 잡힘 — 다른 문자열의 일부로 합쳐졌을 수 있음).

- **명령/속성 어휘**: `label goto call end_scene begin_replay end_replay debug @l .srcxml expr ev layer move layer_set layer_option layer_anime ref_layer sync begin_trans end_trans over_scroll_trans flash shake layer_shake scrnfilter tonefilter set_filter clear_filter fade_filter warp movie endmovie chgmovie bgmovie wait_chgmv bgm se bgv stopbgm stopse stopbgv waitse msg lfd msgshow msgclear voice start_timer sync_timer begin_keyskip end_keyskip reset_skip page_feed char_id frame_id auto_hide ...`
- **`m_*` 함수 이름**: `m_end_trans m_wait_layer m_wait_multi_layers m_wait_end_movie m_wait_fade_movie m_wait_chgmovie m_flip_screen m_wait_fade_msg m_wait_fadeout_msg m_wait_clicked m_wait_time m_msgframe ...` — VM에 바인딩된 네이티브 메서드 이름으로 보인다 [추정].
- **효과 프리셋**: `WaveHighlight RippleLoop RippleOnce RippleOnceRandom RippleInterval RippleRandom Shimmer`(= `warp preset`), 전환 `cross_fade white black dark raster_scroll wave_circle`, `sine cosine`(shake type), `shading_off shading_light`.
- **3D/무비 어휘**(`init3d_scene load3d_config fade3d camera3d_set_pos stage3d_load char3d_*`, `.mei .mdfx .psfx .mpsxml`)가 있으나 이 게임 스크립트는 쓰지 않는다 → 포팅 범위에서 제외 가능 [추정].
- **설정 키**(config 화면용): `full_screen window_stretch system_effect game_effect skip_effect_mode auto_focus_cursor right_click_func space_key_func inactive_sound show_music_title show_icon_help show_cutin_effect h_scene_se mask_msg_box msg_speed auto_speed frame_transparency disable_skip skip_only_read_msg quick_read_msg keep_auto_after_sel cancel_auto_by_click stop_voice_by_click down_bgm_vol_on_voice msg_effect_type msg_font_face volume mute voice_volume voice_mask system_voice` …
- **세이브/상태 키**: `yread_log past_label watched_cg shared_variable fEnding fGalleryMode fExtraScenario flagAnyCleared suspended.sav .sav`.
- UI 파일명: `wm_window.noa`, `ww_system.noa`, `main.srcxml`, `ID_MSGBOX_*`, `ID_SKIP_TO_NEXT_PAGE`, `ID_TITLE`, `ID_CONFIG` 등.
- 설정 경로 `script\opengl\program_cache`, `script\opengl\program_ver`가 있어 **OpenGL 셰이더 프로그램 캐시**를 쓰는 경로가 있을 수 있다 [추정]. 정적 import는 고정 파이프라인(glMatrixMode, glDrawElements, glBlendFunc …)이다.
- 문자열 `fxscript`, `f.@r=0`, `expr`로 보아 **srcxml을 스크립트 코드로 변환/컴파일하는 단계**가 exe에 있는 것으로 보인다 (`@l`/`wait_chgmv` 자동 삽입과 맞음) [추정].

## 6. zombie0.exe 분석 [확정: 정적 분석]

- SHA-256 `656c2921f339d05251433276f66837dbf13b3ad1142aa4e3e455724b05db437a`, PE32, GUI 서브시스템, 섹션 `.text .rdata .data .rsrc .reloc` (패킹 없음).
- Import: `OPENGL32` + `GLU32`, `WINMM`(waveIn/joy/time만), `MSACM32`, `IMM32`, `WS2_32`, `WININET`, `IPHLPAPI`. DirectSound/D3D는 import에 없음 → 오디오는 `SGLDirectSoundPlayer` 동적 로드 추정 [추정].
- RTTI: `EntisGLS4 - Sakura2VM`, `SSystem::Sakura2VM`, `ECSSakura2::*`(ExecutableModule/NativeCompiler 등), `SakuraGL::*`(Image/Font/Sprite/SkinManager/AudioPlayer …), `ERISA::SGLArchiveFile`, `SGL*DecodeContext`(ERISA/ERISA-N/Huffman/Gamma/Decrypt32/DecryptRSA96).
- exe 리소스: ICON 4개, MANIFEST, `RCDATA IDR_COTOMI` 뿐 [확정]. 큰 임베드 바이트코드 블롭은 없다 (엔트로피 7.6 이상 구간은 16KB 하나뿐). `0x2eb2f8`의 `Entis` 시그니처는 .rdata 테이블 오탐.

## 7. ERISA-N 해제기 [확정: 검증됨]

`tools/erisa_nemesis.py` — GARbro(MIT)의 `ErisaNemesis.cs` + `ProbDecodeContext`/`ErisaProbModel`을 Python으로 옮긴 것 (`tools/LICENSE-GARbro.txt` 고지 포함).

- 구조: 32비트 코드 레지스터 + 16비트 augend의 적응형 산술 코더, 4차 문맥 모델(`m_nShiftCount={1,3,4,5}`), 이스케이프 시 베이스 모델 폴백, 이스케이프 이스케이프 시 64KB 링버퍼 기반 **phrase/run-length 복사**(Nemesis).
- 검증 1: `system.noa`의 `black.eri` 저장 바이트 388B → 36348B가 **추출본과 바이트 단위로 일치**.
- 검증 2: exe `IDR_COTOMI` 400B → 1188B 정상 XML.
- 검증 3: 합성 중첩 NOA(압축 엔트리 포함)를 `tools/noa.py extract -r`로 추출해 일치 확인.
- 아직 실제 `system.noa` 전체(39개 엔트리, 중첩 4개)로는 검증하지 않았다 [미확인].

## 8. 구현 전략 (갱신)

| | A: srcxml 호환 노벨 엔진 재구현 | B: EntisGLS4 런타임 이식 (Sakura2VM + SakuraGL) |
|---|---|---|
| 내용 | 명령(bg/msg/…)과 스킨 UI를 네이티브로 직접 구현 | exe가 쓰는 런타임을 Android/SDL3로 이식 |
| 근거 | 명령 어휘와 UI 정의가 데이터(srcxml, skin XML, exe 문자열 풀)로 전부 드러남. 스킨 로더 + 명령 약 32종 | 게임별 `m_*` 네이티브 메서드는 exe 안에 있어 SDK 소스만으로는 부족할 가능성이 높음 |
| 판단 | **채택 방향** | SDK 소스 공개 범위/라이선스 [미확인]. 필요성 낮음 |

## 9. 다음 단계 체크리스트

- [x] `walk_noa.py v2` 실행 → 플래그 확정 (2.2)
- [x] ERISA-N 해제기 이식·검증 (7장)
- [x] `wm_*.noa` 목록과 `system.inf` 4개 분석 → 선언형 스킨 (3.5, 3.6)
- [x] exe `IDR_COTOMI` 해제 → 부팅 설정/VFS 마운트 목록 (4장)
- [ ] `tools/noa.py extract -r system.noa`를 실제 파일로 실행해 39개 + 중첩 271개 전부 해제 검증
- [ ] 0화의 다른 NOA(bg, bgm, bs, ev, se, voice, extra, ending) `list` 결과로 `encryption` 값 분포 확인
- [ ] 1화 `script.noa` 내용(특히 `script.csx` 유무) 확인
- [ ] 낱개 파일 vs 아카이브 우선순위 확인 (Process Monitor)
- [ ] ERI 디코더 포팅(PC 프로토타입, 1280×720 알파 마스크 → PNG) — `EriReader.cs` 참조
- [ ] MIO 디코더 포팅 — `MioDecoder.cs` 참조
- [ ] srcxml 파서/VM, 스킨 로더 설계
