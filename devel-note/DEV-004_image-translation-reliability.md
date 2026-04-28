# DEV-004: 이미지 번역 안정성 개선

## 배경

DEV-003에서 이미지 번역을 복원했으나, 텍스트 대비 간헐적 실패 빈도가 높다.
코드 분석 결과 LLM 특성 외에 코드 수준에서 수정 가능한 원인이 두 가지 확인됐다.

## 원인 분석

### 1. 이미지 응답 검증 없음 (주요 원인)

텍스트 번역(`translate_text`)은 `_gen_content_dict()`를 통해 5회 재시도 + JSON 검증을 하지만,
이미지 번역 2단계는 `_gen_content()`를 직접 호출하고 즉시 인덱스 접근한다.

```python
# 현재 코드
res = self._gen_content(model=self.image_model, ...)
img_data = res.parts[0].inline_data          # parts가 비거나 IMAGE 아닌 응답이면 IndexError / AttributeError
return Image.open(io.BytesIO(img_data.data)) # data가 None이면 TypeError
```

모델이 이미지 대신 텍스트로 응답하거나 safety filter에 걸려 빈 parts를 반환하면
예외가 발생하고 `_gen_content()`의 `while True`가 이를 잡아 무한 루프에 빠진다.

### 2. 텍스트 감지 실패 시 묵음 스킵

`_gen_content_dict()`가 5회 모두 실패하면 `{}`를 반환한다.
`res.get("is_text_present", False)`는 `False`가 되어 텍스트가 있는 이미지도 원본 그대로 반환된다.

### 3. 이미지 프롬프트 품질

현재 이미지 번역 프롬프트는 단순하다.
라이트노벨 삽화 특성(말풍선, 효과음, 세로 쓰기 레이아웃)을 고려한 지시가 없다.

## 수정 내용

### gemini_service.py

**`translate_image()` 재시도 및 응답 검증 추가**

- 최대 3회 재시도 루프
- 응답 유효성 검사: `parts` 비어있지 않은지, `inline_data`가 있는지, `data`가 None이 아닌지
- 텍스트 감지 실패(`{}` 반환) 시 경고 로그 후 원본 반환 (묵음 스킵 동일하나 명시적으로 처리)
- 모든 시도 실패 시 원본 이미지 반환 (번역 실패로 전체 중단되지 않도록)

**이미지 번역 프롬프트 개선**

라이트노벨 삽화 특성에 맞춘 지시 추가:
- 말풍선, 나레이션 박스 등 텍스트 요소를 모두 번역
- 원본 레이아웃, 글자 위치, 스타일 유지
- 효과음(의성어·의태어)은 한국어 동등 표현으로 번역
- 세로 텍스트는 적절한 방향으로 처리
- 용어집 반영 명시

## 변경 파일

- `modules/gemini_service.py` — `translate_image()` 재시도 로직, 응답 검증, 프롬프트 개선
