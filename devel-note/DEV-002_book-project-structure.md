# DEV-002: 작품별 프로젝트 폴더 구조 및 파일 선택 UI

## 배경

기존에는 `glossary.csv`, `honorifics.csv`, `target/`, `output/` 폴더가 루트에 고정되어 있어 작품을 바꿀 때마다 파일을 직접 교체해야 했다. 작품별로 독립된 프로젝트 폴더를 두고, 앱 실행 시 작품과 파일을 선택하는 UI로 개선한다.

---

## 새 디렉토리 구조

```
tr/
├── books/
│   └── {작품명}/
│       ├── glossary.csv      ← 작품별 용어집
│       ├── honorifics.csv    ← 작품별 호칭 룰북
│       ├── source/           ← 번역할 원본 파일 (.docx)
│       │   └── .gitkeep
│       └── result/           ← 번역 결과 파일
│           └── .gitkeep
├── main.py
└── modules/
```

- `source/`, `result/` 내 실제 파일은 `.gitignore`로 추적 제외
- `.gitkeep`만 커밋하여 폴더 구조 유지

---

## 실행 흐름

```
앱 시작
  → books/ 하위 폴더 목록 표시
  → 작품 선택
  → 선택한 작품의 source/ 파일 목록 표시
  → 파일 선택
  → 추론 수준 선택
  → 번역 실행
  → result/에 저장
     (동명 파일 존재 시: [translated] 파일명 (1).docx 형식으로 인덱스 부여)
```

---

## 변경 사항

### 제거된 상수 및 함수

| 항목 | 내용 |
|------|------|
| `GLOSSARY_PATH`, `HONORIFICS_PATH` | 프로젝트 폴더 기반 동적 경로로 대체 |
| `TARGET_DIR`, `OUTPUT_DIR` | `source/`, `result/` 서브폴더로 대체 |
| `ensure_target_dir()` | 제거 |
| `ensure_output_dir()` | `get_output_path()` 내부에서 처리 |
| `get_first_target_file()` | `select_source_file()`로 대체 |
| `has_target_files()` | 제거 |

### 추가된 함수

| 함수 | 역할 |
|------|------|
| `get_projects()` | `books/` 하위 프로젝트 폴더 목록 반환 |
| `select_project()` | 작품 선택 UI |
| `select_source_file(project_dir)` | source/ 내 파일 선택 UI |
| `get_output_path(project_dir, source_file)` | result/ 경로 결정, 중복 시 인덱스 부여 |

### 중복 파일명 처리

```
result/[translated] vol1.docx  → 존재하면
result/[translated] vol1 (1).docx  → 존재하면
result/[translated] vol1 (2).docx  → ...
```

---

## .gitignore 추가 항목

```
books/*/source/*
!books/*/source/.gitkeep
books/*/result/*
!books/*/result/.gitkeep
```
