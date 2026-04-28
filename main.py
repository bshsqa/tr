try:
    import os
    from pathlib import Path
    import questionary
    from rich.console import Console
    from rich.panel import Panel
    from rich.align import Align
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TextColumn,
        TimeElapsedColumn,
        ProgressColumn,
        Task
    )
    from rich.text import Text
    import time
    import json

    from modules.document import Docx
    from modules.gemini_service import Translator
    from modules.util import load_glossary, load_honorifics
except ImportError as e:
    missing_module = str(e).split("'")[1]
    print(f"오류: '{missing_module}' 모듈이 없습니다. 'pip install -r requirements.txt' 명령어로 필요한 모듈을 설치해주세요.")
    input("계속하려면 Enter 키를 누르세요...")
    exit(1)

# Constants
BASE_DIR = Path(__file__).resolve().parent
BOOKS_DIR = BASE_DIR / "books"
TEXT_LENGTH_LIMIT = 2048
CHECKPOINT_INTERVAL = 10

# Initialize Console
console = Console()

def print_center(message: str) -> None:
    console.print(Align.center(message))

QUESTIONARY_STYLE = questionary.Style([
    ('qmark', 'fg:#4f46e5 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#16a34a bold'),
    ('pointer', 'fg:#4f46e5 bold'),
    ('highlighted', 'fg:#4f46e5 bold'),
    ('selected', 'fg:#4f46e5'),
    ('separator', 'fg:#94a3b8'),
    ('instruction', 'fg:#64748b'),
    ('text', ''),
    ('disabled', 'fg:#94a3b8 italic')
])


class CumulativeETAColumn(ProgressColumn):
    _PLACEHOLDER = Text("/ --:-- (경과/예상)", style="bold red")

    @staticmethod
    def format_duration(seconds: float | int) -> str:
        total_seconds = max(0, int(seconds))
        minutes, secs = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _estimate_total_seconds(self, task: Task) -> float | None:
        if not task.total or not task.completed:
            return None

        elapsed = task.fields.get("elapsed_translation_seconds")
        chunks = task.completed
        if not elapsed or not chunks:
            return None

        return task.total * (elapsed / chunks)

    def render(self, task: Task) -> Text:
        total_estimated = self._estimate_total_seconds(task)
        if total_estimated is None:
            return self._PLACEHOLDER

        return Text(f"/ {self.format_duration(total_estimated)} (경과/예상)", style="bold red")


def wait_for_exit(message: str | None = None) -> None:
    if message:
        print_center(Panel(
            f"[bold green]{message}[/bold green]\n[dim]Enter 키를 누르면 종료합니다.[/dim]",
            title="✨ 완료",
            border_style="bright_cyan",
            expand=False
        ))
    else:
        print_center("종료하려면 Enter 키를 누르세요...")
    console.input(password=True)


def select_backend() -> str | None:
    selected = questionary.select(
        "사용할 AI 백엔드를 선택하세요:",
        choices=[
            "Gemini 무료 API  (빠름, 이미지 번역 미지원)",
            "Vertex AI        (이미지 번역 지원, 유료)",
        ],
        style=QUESTIONARY_STYLE,
    ).ask()
    if not selected:
        return None
    return "vertex" if "Vertex" in selected else "gemini"


def ensure_api_key(backend: str) -> bool:
    if backend == "vertex":
        env_var = "GOOGLE_CLOUD_API_KEY"
        label = "GOOGLE_CLOUD_API_KEY (Vertex AI)"
    else:
        env_var = "GOOGLE_API_KEY"
        label = "GOOGLE_API_KEY (Gemini)"

    api_key = os.environ.get(env_var, "").strip()
    if api_key:
        print_center("[green]✓ API key 확인됨[/green]")
        return True

    print_center(Panel(
        f"[bold]API Key 필요[/bold]\n{label}를 입력해주세요.",
        border_style="yellow",
        expand=False
    ))
    api_key = questionary.password(
        "API Key 입력:",
        style=QUESTIONARY_STYLE
    ).ask()

    if not api_key:
        print_center("[bold red]오류:[/bold red] API Key가 입력되지 않았습니다.")
        return False

    os.environ[env_var] = api_key.strip()
    print_center("[green]✓ API key 설정 완료[/green]")
    return True


def get_projects() -> list[Path]:
    if not BOOKS_DIR.exists():
        return []
    return sorted([d for d in BOOKS_DIR.iterdir() if d.is_dir()])


def select_project() -> Path | None:
    projects = get_projects()
    if not projects:
        print_center(f"[bold red]오류:[/bold red] '{BOOKS_DIR}' 폴더에 프로젝트가 없습니다.")
        return None

    selected = questionary.select(
        "번역할 작품을 선택하세요:",
        choices=[p.name for p in projects],
        style=QUESTIONARY_STYLE
    ).ask()

    if not selected:
        return None

    return BOOKS_DIR / selected


def select_source_file(project_dir: Path) -> Path | None:
    source_dir = project_dir / "source"
    if not source_dir.exists():
        print_center(f"[bold red]오류:[/bold red] '{source_dir}' 폴더가 없습니다.")
        return None

    files = sorted([f for f in source_dir.iterdir() if f.is_file() and f.name != ".gitkeep"])
    if not files:
        print_center(f"[bold red]오류:[/bold red] '{source_dir}' 폴더에 파일이 없습니다.")
        return None

    selected = questionary.select(
        "번역할 파일을 선택하세요:",
        choices=[f.name for f in files],
        style=QUESTIONARY_STYLE
    ).ask()

    if not selected:
        return None

    return source_dir / selected


def get_checkpoint_path(project_dir: Path, source_file: Path) -> Path:
    result_dir = project_dir / "result"
    result_dir.mkdir(parents=True, exist_ok=True)
    return result_dir / f"[checkpoint] {source_file.stem}.json"


def load_checkpoint(path: Path, source_name: str, total: int) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("source_file") == source_name and data.get("total") == total:
            return data
    except Exception:
        pass
    return None


def save_checkpoint(path: Path, source_name: str, total: int, completed: int, texts: list, memory: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "source_file": source_name,
            "total": total,
            "completed": completed,
            "texts": texts,
            "memory": memory,
        }, f, ensure_ascii=False, indent=2)


def get_output_path(project_dir: Path, source_file: Path) -> Path:
    result_dir = project_dir / "result"
    result_dir.mkdir(parents=True, exist_ok=True)

    stem = source_file.stem
    suffix = source_file.suffix

    output_path = result_dir / f"[translated] {stem}{suffix}"
    if not output_path.exists():
        return output_path

    idx = 1
    while True:
        output_path = result_dir / f"[translated] {stem} ({idx}){suffix}"
        if not output_path.exists():
            return output_path
        idx += 1


def calculate_total_paragraphs(docx: Docx, include_ad_images: bool = False) -> int:
    if include_ad_images:
        return len(docx.doc)

    ad_range = 1
    if docx.doc:
        cur = docx.doc[-1]
        while len(cur.text.strip()) == 0 and ad_range < len(docx.doc):
            ad_range += 1
            cur = docx.doc[-ad_range]
        ad_range -= 1
    return len(docx.doc) - ad_range


def translate(project_dir: Path, source_file: Path, thinking_level: str, vertexai: bool = False, translate_images: bool = False, translate_ad_images: bool = False) -> None:
    with console.status("[bold green]번역기 초기화 중...", spinner="dots"):
        translator = Translator(text_length=TEXT_LENGTH_LIMIT, thinking_level=thinking_level, vertexai=vertexai)
        print_center("[green]✓ 번역기 초기화 완료[/green]")

    with console.status("[bold green]용어집 불러오는 중...", spinner="dots"):
        glossary = load_glossary(str(project_dir / "glossary.csv"))
        translator.set_glossary(glossary)
        print_center(f"[green]✓ 용어집 로드 완료 ({len(glossary)}개 용어)[/green]")

    with console.status("[bold green]호칭 룰북 불러오는 중...", spinner="dots"):
        honorifics = load_honorifics(str(project_dir / "honorifics.csv"))
        translator.set_honorifics(honorifics)
        print_center(f"[green]✓ 호칭 룰북 로드 완료 ({len(honorifics)}개 규칙)[/green]")

    with console.status(f"[bold green]문서 불러오는 중: {source_file.name}...", spinner="dots"):
        docx = Docx()
        docx.load_from_path(str(source_file), max_len=TEXT_LENGTH_LIMIT)
        print_center(f"[green]✓ 문서 로드 완료 ({len(docx.doc)} 청크)[/green]")

    total_paragraphs = calculate_total_paragraphs(docx, include_ad_images=translate_images and translate_ad_images)

    # Checkpoint
    checkpoint_path = get_checkpoint_path(project_dir, source_file)
    checkpoint = load_checkpoint(checkpoint_path, source_file.name, total_paragraphs)

    resume_from = 0
    saved_texts = [None] * len(docx.doc)

    if checkpoint:
        completed = checkpoint.get("completed", 0)
        resume = questionary.confirm(
            f"이전 번역 진행 상황이 있습니다 ({completed}/{total_paragraphs}). 이어서 번역하시겠습니까?",
            default=True,
            style=QUESTIONARY_STYLE
        ).ask()

        if resume is None:
            return

        if resume:
            resume_from = completed
            saved_texts = checkpoint.get("texts", saved_texts)
            translator.set_memory(checkpoint.get("memory", []))
            for i, text in enumerate(saved_texts):
                if text is not None and i < len(docx.doc):
                    docx.doc[i].text = text
            print_center(f"[green]✓ {completed}/{total_paragraphs} 청크부터 이어서 번역합니다.[/green]")
        else:
            checkpoint_path.unlink(missing_ok=True)

    panel_title = "번역 재개" if resume_from > 0 else "번역 시작"
    panel_body = f"[bold]{panel_title}[/bold]\n파일: {source_file.name}\n총 청크 수: {total_paragraphs}"
    if resume_from > 0:
        panel_body += f"\n재개 위치: {resume_from} / {total_paragraphs}"
    print_center(Panel(panel_body, border_style="blue", expand=False))

    def advance_task(task_id: int, elapsed_seconds: float | None = None) -> None:
        task = progress.tasks[task_id]
        elapsed_increment = elapsed_seconds or 0
        progress.update(
            task_id,
            advance=1,
            elapsed_translation_seconds=task.fields.get("elapsed_translation_seconds", 0) + elapsed_increment,
            translated_chunks=task.fields.get("translated_chunks", 0) + 1
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        CumulativeETAColumn(),
        console=console,
        transient=False,
    ) as progress:

        task_id = progress.add_task("[cyan]번역 중...", total=total_paragraphs, completed=resume_from)

        for idx in range(resume_from, total_paragraphs):
            paragraph = docx.doc[idx]
            tgt_object = "이미지" if paragraph.image else "텍스트"
            progress.update(
                task_id,
                description=f"[cyan]{tgt_object} 처리 중 {idx + 1}/{total_paragraphs}..."
            )

            if paragraph.image:
                if not translate_images:
                    advance_task(task_id)
                    continue
                start_time = time.perf_counter()
                paragraph.image = translator.translate_image(paragraph.image)
                advance_task(task_id, time.perf_counter() - start_time)
                continue

            if len(paragraph.text.strip()) == 0:
                advance_task(task_id)
                continue

            start_time = time.perf_counter()
            paragraph.text = translator.translate_text(paragraph.text)
            advance_task(task_id, time.perf_counter() - start_time)

            saved_texts[idx] = paragraph.text
            if (idx + 1) % CHECKPOINT_INTERVAL == 0:
                save_checkpoint(checkpoint_path, source_file.name, total_paragraphs, idx + 1, saved_texts, translator.get_memory())

    checkpoint_path.unlink(missing_ok=True)

    output_path = get_output_path(project_dir, source_file)

    with console.status("[bold green]문서 저장 중...", spinner="dots"):
        docx.save_to_path(str(output_path))

    print_center(Panel(
        f"[bold green]번역 완료![/bold green]\n저장 위치: {output_path}",
        border_style="green",
        expand=False
    ))
    wait_for_exit("번역이 끝났습니다.")


def main() -> None:
    console.clear()
    print_center(Panel("[bold cyan]Docx 번역기 v0.2[/bold cyan]", expand=False, border_style="cyan"))

    backend = select_backend()
    if not backend:
        return

    vertexai = backend == "vertex"
    print_center(f"[green]✓ 백엔드: [bold]{'Vertex AI' if vertexai else 'Gemini 무료 API'}[/bold][/green]")

    if not ensure_api_key(backend):
        wait_for_exit()
        return

    project_dir = select_project()
    if not project_dir:
        return

    print_center(f"[green]✓ 작품 선택: [bold]{project_dir.name}[/bold][/green]")

    source_file = select_source_file(project_dir)
    if not source_file:
        return

    print_center(f"[green]✓ 파일 선택: [bold]{source_file.name}[/bold][/green]")
    console.print()

    thinking_level_sel = questionary.select(
        "모델의 추론 수준을 선택하세요.\n추론 수준이 높을수록 더 정교한 번역이 가능하지만, 처리 시간이 길어질 수 있습니다.\n최소 수준 추론도 충분히 정교한 번역을 제공합니다:",
        choices=["최소", "낮음", "보통", "높음"],
        default="최소",
        style=QUESTIONARY_STYLE
    ).ask()

    if not thinking_level_sel:
        return

    thinking_level = {"최소": "MINIMAL", "낮음": "LOW", "보통": "MEDIUM", "높음": "HIGH"}[thinking_level_sel]

    translate_images = False
    translate_ad_images = False

    if vertexai:
        img_action = questionary.select(
            "이미지 번역 옵션을 선택하세요:",
            choices=[
                "❌ 아니요, 텍스트만 번역할게요 (빠름)",
                "✅ 네, 이미지 번역도 할게요 (느림)",
            ],
            style=QUESTIONARY_STYLE,
        ).ask()
        if not img_action:
            return
        translate_images = "✅" in img_action

        if translate_images:
            ad_action = questionary.select(
                "광고 페이지 이미지도 번역할까요?",
                choices=[
                    "❌ 아니요, 광고 이미지는 건너뛸게요 (추천)",
                    "✅ 네, 광고 이미지도 번역할게요",
                ],
                default="❌ 아니요, 광고 이미지는 건너뛸게요 (추천)",
                style=QUESTIONARY_STYLE,
            ).ask()
            if not ad_action:
                return
            translate_ad_images = "✅" in ad_action

    summary = f"{project_dir.name} / {source_file.name} / 추론 수준 {thinking_level_sel}"
    if vertexai:
        summary += " / 이미지 번역 " + ("켜기" if translate_images else "끄기")
    print_center(f"[dim]선택: {summary}[/dim]")
    console.print()

    translate(project_dir, source_file, thinking_level, vertexai=vertexai, translate_images=translate_images, translate_ad_images=translate_ad_images)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        console.print_exception()
        wait_for_exit("오류가 발생하여 프로그램을 종료합니다.")
