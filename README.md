# EntisGLS (zombie 0~3화) 모바일 포팅 작업 저장소

개인 학습/사용 목적의 분석·프로토타입 저장소입니다. **게임 리소스(NOA, ERI, MIO 등)는 포함하지 않습니다.**

- `docs/analysis-notes.md` — 분석 노트 (확정/추정/미확인 구분)
- `docs/updates/` — 차수별 보충 노트 (최신: `05-mio-decoder.md`)
- `docs/exe-string-pool.txt` — exe의 스크립트 명령/속성/설정 키 문자열 목록
- `tools/erisa_nemesis.py` — NOA 압축(ERISA-N) 해제기 (GARbro, MIT 기반)
- `tools/noa.py` — NOA 리스트/추출 도구 (`list`/`extract`, `-r` 중첩 재귀)
- `tools/eri.py` — ERI 이미지 디코더 → PNG (무손실+감마 코드 경로)
- `tools/scan_eri.py` — NOA 안 ERI 헤더 변형 분포 조사
- `tools/mio.py` — MIO 오디오 디코더 → WAV (LOT_ERI, 모노/스테레오)
- `tools/scan_mio.py` — NOA 안 MIO 변형 분포 조사 / 일괄 디코드 시험
- `tools/walk_noa.py` — 헤더만 보는 간이 워커 (v2)
- `tools/LICENSE-GARbro.txt` — GARbro MIT 라이선스 고지

사용 예
```
python tools/noa.py list system.noa -r
python tools/noa.py extract system.noa OUT -r
python tools/eri.py OUT/keikoku01.eri keikoku01.png
python tools/scan_eri.py bg.noa bs.noa ev.noa ending.noa extra.noa
python tools/mio.py voice01.mio out.wav
python tools/scan_mio.py bgm.noa se.noa voice.noa --decode
```
