# 로컬 LLM 설치 가이드 (집 데스크톱)

대상 PC: RAM 32GB, AMD Radeon RX 7800 XT (VRAM 16GB, RDNA3 / gfx1101), Windows

## 1. 모델 선택

| 용도 | 모델 (Q4 양자화) | 크기(대략) | 이 PC에서 |
|---|---|---|---|
| **1순위 (생성 A)** | Ornith 1.0 9B | 약 6GB | VRAM에 전부 올라감 → 빠름 |
| 듀얼 교차검증 (생성 B) | 다른 계열 7~14B (예: Qwen 계열) | 약 5~9GB | VRAM에 올라감. A와 번갈아 로드 (`--workers 1`) |
| 품질 업그레이드 (나중에) | Ornith 1.0 35B A3B | 약 21~27GB | VRAM 초과 → 일부를 RAM(32GB)으로 넘겨 실행. MoE(활성 3B)라 느리지만 쓸 만한 수준으로 예상 |

- 크기 수치는 서드파티 추정치이며 출처마다 차이가 있음. 실제 크기는 `ollama pull` 후 `ollama list`로 확인
- 처음에는 **9B 하나로 `--qualname analyze_work_hours` 1건**만 돌려 품질·속도를 본 뒤 확장

## 2. 설치

1. AMD 그래픽 드라이버(Adrenalin) 최신 버전으로 업데이트
2. Ollama Windows 설치 (https://ollama.com/download) — AMD GPU 가속(ROCm/HIP)이 포함되어 있음.
   RX 7800 XT는 Ollama 문서의 Windows 지원 목록에 있음 (최신 목록은 https://docs.ollama.com/gpu 에서 재확인)
3. **컨텍스트 길이 늘리기 (중요)**: Ollama 기본 컨텍스트가 작으면 긴 함수 프롬프트가 잘린다.
   OpenAI 호환 API는 요청마다 컨텍스트 길이를 지정할 수 없으므로 서버 환경변수로 설정한다.
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH", "8192", "User")
   ```
   설정 후 Ollama를 완전히 종료(트레이 아이콘 → Quit)했다가 다시 실행
4. 모델 받기 — 태그 이름은 https://ollama.com/library 에서 "ornith" 검색으로 확인.
   라이브러리에 없으면 Hugging Face의 GGUF를 직접 받을 수 있다: `ollama pull hf.co/<저장소>:Q4_K_M`
   ```powershell
   ollama pull <ornith 9B 태그>
   ollama list
   ```

## 3. GPU 사용 확인

```powershell
ollama run <ornith 9B 태그> "안녕"     # 응답 확인 후 /bye
ollama ps                              # PROCESSOR 열이 "100% GPU"면 정상
```
- `100% CPU`로 나오면 GPU를 못 잡은 것 → 드라이버 업데이트, Ollama 재설치, docs.ollama.com/gpu 의 AMD 항목 확인
- 35B처럼 VRAM을 넘는 모델은 `40%/60% CPU/GPU`처럼 나뉘어 표시되는 게 정상

## 4. 첫 실호출

```powershell
cd <Ai-testcase-generator 폴더>
git pull
python -m testgen.cli `
  --coverage-json "<backend 폴더>" --source-root "<backend 폴더>" `
  --framework-hint "FastAPI + SQLAlchemy. tests/conftest.py의 DB 세션/TestClient 픽스처 사용" `
  --qualname analyze_work_hours `
  --models "local:<ornith 9B 태그>" --workers 1
```
- 결과: `output\test_cases.csv` (엑셀), 원본 응답: `output\responses\`
- 공유할 것: 콘솔 요약 줄, `test_cases.csv`, 소요 시간

## 5. 문제가 생기면

| 증상 | 원인/조치 |
|---|---|
| `연결 실패 ... ollama serve` | Ollama가 실행 중이 아님 → 시작 메뉴에서 Ollama 실행 |
| `HTTP 404 ... model not found` | `--models local:<태그>`의 태그가 `ollama list`와 다름 |
| `PARSE FAIL` 다수 | 모델이 JSON 형식을 지키지 못함 → 원본 응답 JSON의 `raw_output` 공유 |
| `600초 타임아웃` | CPU로 돌고 있을 가능성 → `ollama ps` 확인 |
