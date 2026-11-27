# EntisGLS (zombie 0~3화) 모바일 포팅 작업 저장소

개인 학습/사용 목적의 분석·프로토타입 저장소입니다. **게임 리소스(NOA, ERI, MIO 등)는 포함하지 않습니다.**

- `docs/analysis-notes.md` — 분석 노트 (확정/추정/미확인 구분)
- `docs/exe-string-pool.txt` — exe의 스크립트 명령/속성/설정 키 문자열 목록
- `tools/erisa_nemesis.py` — NOA 압축(ERISA-N) 해제기 (GARbro, MIT 기반)
- `tools/noa.py` — NOA 리스트/추출 도구 (`list`/`extract`, `-r` 중첩 재귀)
- `tools/walk_noa.py` — 헤더만 보는 간이 워커 (v2)
- `tools/LICENSE-GARbro.txt` — GARbro MIT 라이선스 고지

사용 예: `python tools/noa.py list system.noa -r`
