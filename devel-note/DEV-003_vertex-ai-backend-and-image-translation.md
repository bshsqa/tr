# DEV-003: Vertex AI 백엔드 선택 및 이미지 번역 복원

## 1. tr은 makein 대비 어떻게 개선됐나

### 배경

`makein`은 Vertex AI를 사용하는 초기 프로토타입이고, `tr`은 이를 기반으로 실용성과 번역 품질을 높인 개선 버전이다.

### 구조 개선

| 항목 | makein | tr |
|------|--------|-----|
| 폴더 구조 | 단일 작품 (`target/`, `output/`) | 다중 작품 (`books/{작품명}/source`, `result/`) |
| 파일 선택 | `target/` 첫 번째 파일 자동 선택 | 작품 → 파일 순서로 사용자가 직접 선택 |
| 용어집 위치 | 루트 `glossary.csv` 고정 | 작품 폴더별 `glossary.csv` |

### 번역 품질 개선

**호칭 룰북 추가 (`honorifics.csv`)**
- makein에는 없었던 기능
- 캐릭터 간 호칭을 CSV로 명시 (caller, target, honorific)
- 프롬프트에 자동 주입하여 호칭 일관성 보장
- "さん, 상, 씨 등을 중복으로 붙이지 말 것" 방어 로직 포함

**프롬프트 엔지니어링 고도화**
- makein: 기본 3줄 규칙 (용어집, 기호 유지, 줄바꿈 유지)
- tr: 8가지 명시 규칙
  1. 일본어 문자 완전 제거 (히라가나·가타카나·한자 0개)
  2. 용어집 정확한 사용 강제
  3. 간투어 한국화 (えっと→음..., ええ→에... 등 예시 포함)
  4. 의성어·의태어 한국화 (パチパチ→짝짝 등 예시 포함)
  5. 캐릭터 말투 일관성 유지
  6. 자연스러운 한국어 (직역 금지)
  7. 줄바꿈 보존
  8. 기호 유지 (「」등)

**일본어 잔존 재시도 메커니즘**
- makein: 단발 요청, 재시도 없음
- tr: 번역 결과에 일본어가 남아있으면 최대 3회 재시도
  - 잔존 일본어 위치를 컨텍스트로 추출해 다음 요청에 `WARNING` 힌트 주입
  - 최적 결과(일본어 가장 적은 것)를 최종 반환

### 작업 안정성 개선

**체크포인트 시스템**
- makein: 없음 (중단 시 처음부터 재시작)
- tr: 10 청크마다 진행 상황 JSON 저장 (`[checkpoint] {파일명}.json`)
  - 저장 내용: 완료 청크 수, 번역된 텍스트 목록, 번역 메모리
  - 재실행 시 이어서 번역할지 묻고 체크포인트 복원

### API 변경 (makein → tr)

| 항목 | makein | tr |
|------|--------|-----|
| API | Vertex AI | Gemini 무료 API |
| 환경변수 | `GOOGLE_CLOUD_API_KEY` | `GOOGLE_API_KEY` |
| 텍스트 모델 | `gemini-3-flash-preview` | `gemini-3.1-flash-lite-preview` |
| 이미지 번역 | `gemini-3-pro-image-preview` (구현됨) | `NotImplementedError` |

Vertex AI → 무료 API 전환은 비용 절감 목적이었으나, 이미지 번역이 함께 빠졌다.

---

## 2. Vertex AI / Gemini 백엔드 선택 기능 추가 계획

### 목표

실행 시 Vertex AI와 Gemini 무료 API 중 하나를 선택할 수 있게 한다.  
환경변수가 있으면 자동으로 사용하고, 없으면 실행 중에 입력받는다.

### 환경변수

| 백엔드 | 환경변수 |
|--------|---------|
| Gemini 무료 API | `GOOGLE_API_KEY` |
| Vertex AI | `GOOGLE_CLOUD_API_KEY` |

### UI 흐름 변경 (`main.py`)

현재 `ensure_api_key()`는 `GOOGLE_API_KEY`만 확인한다.  
이를 다음 순서로 변경한다.

1. **백엔드 선택 UI** (앱 시작 직후)
   ```
   사용할 AI 백엔드를 선택하세요:
   ▶ Gemini 무료 API (빠름, 이미지 번역 미지원)
     Vertex AI       (이미지 번역 지원, 유료)
   ```

2. **API 키 확인 및 입력 (`ensure_api_key(backend)`))**
   - Gemini: `GOOGLE_API_KEY` 없으면 입력 요청
   - Vertex AI: `GOOGLE_CLOUD_API_KEY` 없으면 입력 요청

### `Translator` 클래스 변경 (`gemini_service.py`)

makein의 `Translator.__init__`은 이미 `vertexai: bool` 파라미터를 지원하고 있다.  
tr의 `Translator`는 이 파라미터가 없다. 추가할 내용:

```python
class Translator:
    def __init__(self, text_length: int, thinking_level: str, vertexai: bool = False):
        if vertexai:
            self.client = genai.Client(
                vertexai=True,
                api_key=os.environ.get("GOOGLE_CLOUD_API_KEY"),
            )
            self.text_model = "gemini-3-flash-preview"
        else:
            self.client = genai.Client(
                api_key=os.environ.get("GOOGLE_API_KEY"),
            )
            self.text_model = "gemini-3.1-flash-lite-preview"
        
        self.vertexai = vertexai
        # ... 나머지 초기화
```

`translate()` 함수 시그니처도 `vertexai: bool` 파라미터 추가.

### 텍스트 모델 선택 고려사항

Vertex AI 백엔드를 선택한다고 해서 반드시 더 좋은 텍스트 번역이 보장되지는 않는다.  
tr에서 고도화된 프롬프트 엔지니어링과 재시도 로직은 백엔드 무관하게 유지한다.  
단, Vertex AI용 텍스트 모델명은 `gemini-3-flash-preview`를 기본으로 사용한다.

---

## 3. 이미지 번역 복원 계획 (Vertex AI 전용)

### 현황

tr의 `translate_image()`는 현재:
```python
def translate_image(self, image: Image.Image, tgt_lang: str = "Korean") -> Image.Image:
    raise NotImplementedError("Image translation is not supported with the free API.")
```

makein에는 완전히 구현되어 있다 (`gemini-3-pro-image-preview` 사용).

### 복원할 코드

makein의 이미지 번역 파이프라인을 그대로 가져온다.

**이미지 관련 모델 및 설정 추가 (`gemini_service.py`)**

```python
# Vertex AI 전용 — __init__에서 vertexai=True일 때만 초기화
if vertexai:
    self.image_model = "gemini-3-pro-image-preview"
    self.image_model_config = types.GenerateContentConfig(
        temperature=1,
        top_p=0.95,
        max_output_tokens=32768,
        response_modalities=["IMAGE"],
        safety_settings=self.safety_settings,
        image_config=types.ImageConfig(output_mime_type="image/png"),
    )
    self.text_in_image_config = types.GenerateContentConfig(
        max_output_tokens=65535,
        safety_settings=self.safety_settings,
        response_mime_type="application/json",
        response_schema={"type": "OBJECT", "properties": {"is_text_present": {"type": "BOOLEAN"}}},
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
    )
```

**`translate_image()` 복원**

```python
def translate_image(self, image: Image.Image, tgt_lang: str = "Korean") -> Image.Image:
    if not self.vertexai:
        raise NotImplementedError("Image translation is not supported with the free API.")
    
    # 1단계: 텍스트 존재 여부 확인
    res = self._gen_content_dict(
        model=self.text_model,
        config=self.text_in_image_config,
        contents=["Is there any text present in this image? Respond with JSON {'is_text_present': bool}.", image],
    )
    if not res.get("is_text_present", False):
        return image  # 텍스트 없으면 원본 반환
    
    # 2단계: 이미지 번역
    contents = [
        "You are a professional translator specialized in image translation.",
        self.glossary,
        self._get_memory(),
        f"Translate the content of this image to {tgt_lang}. Provide only the translated image.",
        image,
    ]
    res = self._gen_content(model=self.image_model, config=self.image_model_config, contents=contents)
    img_data = res.parts[0].inline_data
    return Image.open(io.BytesIO(img_data.data))
```

### UI 변경 (`main.py`)

이미지 번역 UI는 **Vertex AI 백엔드 선택 시에만** 표시한다.

```
[Vertex AI 선택 시에만]
이미지 번역 옵션을 선택하세요:
▶ ❌ 아니요, 텍스트만 번역할게요 (빠름)
  ✅ 네, 이미지 번역도 할게요 (느림)

[이미지 번역 선택 시]
광고 이미지도 번역할까요?
▶ ❌ 아니요, 광고 이미지는 건너뛸게요 (추천)
  ✅ 네, 광고 이미지도 번역할게요
```

`calculate_total_paragraphs()`에 `include_ad_images` 파라미터 복원 (makein 참고).

`translate()` 함수에서 이미지 청크 처리 로직 변경:

```python
if paragraph.image:
    if not translate_images:
        advance_task(task_id)
        continue
    # Vertex AI 이미지 번역 실행
    start_time = time.perf_counter()
    paragraph.image = translator.translate_image(paragraph.image)
    advance_task(task_id, time.perf_counter() - start_time)
    continue
```

현재 tr은 이미지 청크를 무조건 skip한다. 이 부분을 위와 같이 조건부로 변경한다.

---

## 변경 파일 요약

| 파일 | 변경 내용 |
|------|---------|
| `main.py` | 백엔드 선택 UI 추가, `ensure_api_key(backend)` 수정, 이미지 번역 UI 추가 (Vertex AI 시), `translate()` 파라미터 추가 |
| `modules/gemini_service.py` | `Translator.__init__`에 `vertexai` 파라미터 추가, 이미지 모델 초기화, `translate_image()` 복원 |

`modules/document.py`, `modules/util.py`는 변경 없음.
