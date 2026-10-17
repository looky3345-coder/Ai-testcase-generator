# 로컬 LLM 설치 가이드 (집 데스크톱)

대상 PC: RAM 32GB, AMD Radeon RX 7800 XT (VRAM 16GB, RDNA3 / gfx1101), Windows

## 1. 모델 선택

| 용도 | 모델 (Q4 양자화) | 크기(대략) | 이 PC에서 |
|---|---|---|---|
| **1순위 (생성 A)** | **Ornith-1.5-9B** (2026-08 공개, 1.0의 후속) | 약 6GB | VRAM에 전부 올라감 → 빠름 |
| 듀얼 교차검증 (생성 B) | 다른 계열 7~14B (예: Qwen 계열) | 약 5~9GB | VRAM에 올라감. A와 번갈아 로드 (`--workers 1`) |
| 품질 업그레이드 (나중에) | Ornith 35B A3B 계열 | 약 21~27GB | VRAM 초과 → 일부를 RAM(32GB)으로 넘겨 실행. MoE(활성 3B)라 느리지만 쓸 만한 수준으로 예상 |

- 크기 수치는 서드파티 추정치이며 출처마다 차이가 있음. 실제 크기는 `ollama pull` 후 `ollama list`로 확인
- Ornith-1.5-9B: 9.4B 파라미터 dense 모델, 컨텍스트 최대 262K 토큰, MIT 라이선스, 가중치는 Hugging Face 공개.
  벤치마크(SWE-bench Verified 70.6 등)는 제조사 발표치이며 독립 검증은 아직 없음
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
4. 모델 받기 — `ollama list`는 **이미 받은 모델만** 보여준다. Ornith-1.5-9B는 Hugging Face GGUF로 받는 것이 확실하다
   (Ollama 공식 라이브러리 등록 여부는 미확인: https://ollama.com/search?q=ornith).
   ```powershell
   ollama pull hf.co/bartowski/Ornith-1.5-9B-GGUF:Q4_K_M     # 약 5.9GB
   ollama cp hf.co/bartowski/Ornith-1.5-9B-GGUF:Q4_K_M ornith15-9b   # 짧은 별칭 (선택)
   ollama list
   ```
   - `bartowski/...`는 커뮤니티 변환본(널리 쓰이는 업로더). 공식 원본은 `ornith-ai/Ornith-1.5-9B`
   - `hf.co/` 방식이 안 되면 Ollama를 최신 버전으로 업데이트
   - Ollama가 이미 설치되어 있었다면 3번(컨텍스트 길이) 설정 후 반드시 완전 종료 → 재실행

## 3. GPU 사용 확인

```powershell
ollama run ornith15-9b "안녕"     # 응답 확인 후 /bye
ollama ps                              # PROCESSOR 열이 "100% GPU"면 정상
```
- `100% CPU`로 나오면 GPU를 못 잡은 것 → 드라이버 업데이트, Ollama 재설치, docs.ollama.com/gpu 의 AMD 항목 확인
- 35B처럼 VRAM을 넘는 모델은 `40%/60% CPU/GPU`처럼 나뉘어 표시되는 게 정상

## 4. 첫 실호출

### 4-1. 이 PC에서 coverage.json 만들기 (필수)

`coverage.json`은 테스트 실행 결과물이라 보통 git에 없다. 새 PC에서 대상 프로젝트를 받았다면 반드시 다시 만든다.
복사해 왔더라도 대상 코드·테스트가 바뀌었으면 라인 번호가 어긋나므로 다시 만든다.

```powershell
cd "<대상 프로젝트>\backend"
python -m venv .venv                          # 이 PC에 .venv가 없을 때만
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest pytest-cov   # 처음 한 번
$env:GROQ_API_KEY = "dummy-key-for-coverage"  # PowerShell 창마다
python -m pytest tests/ --cov=app --cov-branch --cov-report=json:coverage.json
```
`Coverage JSON written to file coverage.json`이 나오면 성공 (일부 테스트 실패는 무관). 오류는 README "문제 해결" 참고

### 4-2. 테스트 케이스 생성

```powershell
cd <Ai-testcase-generator 폴더>
git pull
python -m testgen.cli `
  --coverage-json "<backend 폴더>" --source-root "<backend 폴더>" `
  --framework-hint "FastAPI + SQLAlchemy. tests/conftest.py의 DB 세션/TestClient 픽스처 사용" `
  --qualname analyze_work_hours `
  --models "local:ornith15-9b" --workers 1
```
- 결과: `output\test_cases.csv` (엑셀), 원본 응답: `output\responses\`
- 공유할 것: 콘솔 요약 줄, `test_cases.csv`, 소요 시간

### 4-3. 전체 실행을 나눠서 하기

함수 하나에 수십 초~1분이 걸리므로 107개를 한 번에 돌리지 말고 나눠 실행한다.
`--resume`을 붙이면 같은 프롬프트로 이미 성공한 함수는 다시 호출하지 않는다.

```powershell
# 1회차: 앞에서부터 20개
python.exe -m testgen.cli <경로 옵션들> --models "local:ornith15-9b-16k" --workers 1 --limit 20 --resume
# 2회차(다른 날): 40개까지 — 앞 20개는 재사용, 21~40번째만 새로 호출
python.exe -m testgen.cli <경로 옵션들> --models "local:ornith15-9b-16k" --workers 1 --limit 40 --resume
```
- `--file-contains services`처럼 폴더 단위로 나눠도 된다
- 프롬프트가 바뀐 함수(도구 업데이트, `--framework-hint` 변경 등)는 자동으로 다시 호출된다
- `test_cases.csv`에는 재사용한 결과까지 모두 들어간다

### 4-4. 테스트 코드 생성·실행 (3단계)

4-2 명령에 `--generate-code`를 붙인다. 같은 PowerShell 창에서 `$env:GROQ_API_KEY = "dummy-key-for-coverage"`를 먼저 설정.
대상 프로젝트 `.venv`에 `pytest-cov`가 있어야 한다 (4-1에서 설치함). 함수 1개당 LLM 호출이 케이스 1회 + 코드 1~3회로 늘어난다.

## 5. GPU 부담

- 부하 수준은 게임과 비슷하며, 이 도구는 생성 중에만 짧게(호출당 수 초~수십 초) 사용하고 쉬는 간헐적 부하다. 상시 고부하(채굴 등)와 다름
- 정상 온도 범위에서는 칩 수명에 미치는 영향은 무시할 수준이고, 과열 시 GPU가 스스로 클럭을 낮춰 보호한다. 기계적 소모는 팬 정도(게임과 동일)
- Ornith-1.5-9B(약 6GB)는 VRAM 16GB의 절반 이하만 사용
- 사용 후 약 5분간 모델이 VRAM에 남음(Ollama 기본 keep_alive) → 곧바로 게임할 때는 `ollama stop <모델명>`
- 온도 확인: 작업 관리자 → 성능 → GPU, 또는 AMD Adrenalin 오버레이. 게임할 때와 비슷하면 정상
- 더 줄이고 싶으면 Adrenalin → 성능 → 튜닝에서 전력 제한을 -10% 정도 (속도 약간 감소, 발열·소음 감소)
- 35B처럼 VRAM을 넘는 모델은 CPU/RAM 부하가 커지지만 고장 위험이 아니라 속도 저하 문제

## 6. 문제가 생기면

| 증상 | 원인/조치 |
|---|---|
| `연결 실패 ... ollama serve` | Ollama가 실행 중이 아님 → 시작 메뉴에서 Ollama 실행 |
| `HTTP 404 ... model not found` | `--models local:<태그>`의 태그가 `ollama list`와 다름 |
| `PARSE FAIL` + "답 본문은 비었고 사고 과정(reasoning)만 있음" | 추론형 모델이 thinking에 시간을 다 쓰고 답(content)을 비움 → `--local-thinking off`(기본값) 확인 |
| `[응답이 길이 한도로 잘림: finish_reason=length, 입력 + 출력 = N 토큰]` | N이 4096/8192 근처면 Ollama 컨텍스트 한도 → 아래 "컨텍스트 한도 늘리기" |
| `PARSE FAIL` (그 외) | 모델이 JSON 형식을 지키지 못함 → 응답 JSON의 `raw_output`, `raw_response` 공유 |
| `600초 타임아웃` | CPU로 돌고 있을 가능성 → `ollama ps` 확인 |

## 컨텍스트 한도 늘리기 (응답이 잘릴 때)

환경변수(`OLLAMA_CONTEXT_LENGTH`)는 Ollama 재시작이 필요하고 적용 여부가 잘 안 보인다.
**모델 자체에 한도를 넣은 별칭**을 만드는 방법이 더 확실하다.

```powershell
@"
FROM ornith15-9b
PARAMETER num_ctx 16384
"@ | Set-Content -Encoding ascii Modelfile.ornith16k
ollama create ornith15-9b-16k -f Modelfile.ornith16k
ollama show ornith15-9b-16k      # parameters에 num_ctx 16384 확인
```
이후 `--models "local:ornith15-9b-16k"`로 실행. 9B Q4 + 16K 컨텍스트는 VRAM 16GB 안에 들어갈 것으로 예상
(`ollama ps`에서 100% GPU인지 확인, CPU로 넘어가면 12288 등으로 낮춤).
