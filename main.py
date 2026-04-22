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

    from modules.document import Docx
    from modules.gemini_service import Translator
    from modules.util import load_glossary
except ImportError as e:
    missing_module = str(e).split("'")[1]
    print(f"오류: '{missing_module}' 모듈이 없습니다. 'pip install -r requirements.txt' 명령어로 필요한 모듈을 설치해주세요.")
    input("계속하려면 Enter 키를 누르세요...")
    exit(1)

# Constants
BASE_DIR = Path(__file__).resolve().parent
GLOSSARY_PATH = BASE_DIR / "glossary.csv"
TARGET_DIR = BASE_DIR / "target"
OUTPUT_DIR = BASE_DIR / "output"
TEXT_LENGTH_LIMIT = 2048

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


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_target_dir() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)


def get_first_target_file() -> Path | None:
    ensure_target_dir()

    target_files = sorted(TARGET_DIR.iterdir())
    if not target_files:
        print_center(f"[bold red]오류:[/bold red] '{TARGET_DIR}' 폴더에 파일이 없습니다.")
        return None

    return target_files[0]


def has_target_files() -> bool:
    return TARGET_DIR.exists() and any(TARGET_DIR.iterdir())

def ensure_api_key() -> bool:
    """Ensure GOOGLE_CLOUD_API_KEY exists; prompt if missing."""
    api_key = os.environ.get("GOOGLE_CLOUD_API_KEY", "").strip()
    if api_key:
        print_center("[green]✓ API key 확인됨[/green]")
        return True

    print_center(Panel(
        "[bold]API Key 필요[/bold]\nGOOGLE_CLOUD_API_KEY를 입력해주세요.",
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

    os.environ["GOOGLE_CLOUD_API_KEY"] = api_key.strip()
    print_center("[green]✓ API key 설정 완료[/green]")
    return True

def calculate_total_paragraphs(docx: Docx, include_ad_images: bool) -> int:
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


def translate(translate_images: bool, translate_ad_images: bool, thinking_level: str) -> None:
    """Translate the first DOCX file in the target directory."""
    target_file = get_first_target_file()
    if not target_file:
        return

    ensure_output_dir()

    with console.status("[bold green]번역기 초기화 중...", spinner="dots"):
        translator = Translator(text_length=TEXT_LENGTH_LIMIT, thinking_level=thinking_level)
        print_center("[green]✓ 번역기 초기화 완료[/green]")

    with console.status("[bold green]용어집 불러오는 중...", spinner="dots"):
        glossary = load_glossary(str(GLOSSARY_PATH))
        translator.set_glossary(glossary)
        print_center(f"[green]✓ 용어집 로드 완료 ({len(glossary)}개 용어)[/green]")

    with console.status(f"[bold green]문서 불러오는 중: {target_file.name}...", spinner="dots"):
        docx = Docx()
        docx.load_from_path(str(target_file), max_len=TEXT_LENGTH_LIMIT)
        print_center(f"[green]✓ 문서 로드 완료 ({len(docx.doc)} 청크)[/green]")

    include_ad_images = translate_images and translate_ad_images
    total_paragraphs = calculate_total_paragraphs(docx, include_ad_images)

    print_center(Panel(
        f"[bold]번역 시작[/bold]\n파일: {target_file.name}\n총 청크 수: {total_paragraphs}",
        border_style="blue",
        expand=False
    ))

    def advance_task(task_id: int, elapsed_seconds: float | None = None) -> None:
        task = progress.tasks[task_id]
        elapsed_increment = elapsed_seconds or 0
        progress.update(
            task_id,
            advance=1,
            elapsed_translation_seconds=task.fields.get("elapsed_translation_seconds", 0) + elapsed_increment,
            translated_chunks=task.fields.get("translated_chunks", 0) + 1
        )

    # Processing Loop with Progress Bar
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

        task_id = progress.add_task("[cyan]번역 중...", total=total_paragraphs)

        for idx in range(total_paragraphs):
            paragraph = docx.doc[idx]
            tgt_object = "이미지" if paragraph.image else "텍스트"
            progress.update(
                task_id,
                description=f"[cyan]{tgt_object} 번역 중 {idx + 1}/{total_paragraphs}..."
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

    # Save Document
    output_filename = f"[translated] {target_file.name}"
    output_path = OUTPUT_DIR / output_filename

    with console.status("[bold green]문서 저장 중...", spinner="dots"):
        docx.save_to_path(str(output_path))

    print_center(Panel(
        f"[bold green]번역 완료![/bold green]\n저장 위치: {output_path}",
        border_style="green",
        expand=False
    ))
    wait_for_exit("번역이 끝났습니다.")


def main() -> None:
    """Entry point for the CLI UI."""
    console.clear()
    print_center(Panel("[bold cyan]Docx 번역기 v0.1[/bold cyan]", expand=False, border_style="cyan"))

    ensure_target_dir()

    if not ensure_api_key():
        print_center("종료하려면 Enter 키를 누르세요...")
        console.input(password=True)
        return

    # Initial check
    if not has_target_files():
        print_center(
            f"[bold red]오류:[/bold red] '{TARGET_DIR}' 폴더에 번역할 파일이 없습니다.\n"
            "파일을 추가한 후 다시 시도해주세요."
        )
        wait_for_exit()
        return

    # User Selection
    print_center("[bold]설정 확인[/bold]")

    thinking_level_sel = questionary.select(
        "모델의 추론 수준을 선택하세요.\n추론 수준이 높을수록 더 정교한 번역이 가능하지만, 처리 시간이 길어질 수 있습니다.\n최소 수준 추론도 충분히 정교한 번역을 제공합니다:",
        choices=["최소", "낮음", "보통", "높음"],
        default="최소",
        style=QUESTIONARY_STYLE
    ).ask()

    if not thinking_level_sel:
        return  # User cancelled
    
    thinking_level = {"최소": "MINIMAL", "낮음": "LOW", "보통": "MEDIUM", "높음": "HIGH"}[thinking_level_sel]

    action = questionary.select(
        "이미지 번역 옵션을 선택하세요:",
        choices=[
            "✅ 네, 이미지 번역도 할게요 (느림)",
            "❌ 아니요, 텍스트만 번역할게요 (빠름)"
        ],
        style=QUESTIONARY_STYLE
    ).ask()

    if not action:
        return  # User cancelled

    translate_images = "✅" in action
    translate_ad_images = False

    if translate_images:
        ad_action = questionary.select(
            "이미지 번역 시, 뒤에 나오는 광고 페이지 이미지도 번역할까요?",
            choices=[
                "❌ 아니요, 광고 이미지는 건너뛸게요 (추천)",
                "✅ 네, 광고 이미지도 번역할게요"
            ],
            default="❌ 아니요, 광고 이미지는 건너뛸게요 (추천)",
            style=QUESTIONARY_STYLE
        ).ask()

        if not ad_action:
            return  # User cancelled

        translate_ad_images = "✅" in ad_action
    
    option_text = "이미지 번역 켜기" if translate_images else "텍스트만 번역"
    if translate_images:
        option_text += " / 광고 이미지 포함" if translate_ad_images else " / 광고 이미지 제외"
    print_center(f"[dim]선택된 옵션: {option_text} / 추론 수준: {thinking_level_sel}[/dim]")
    console.print()

    # Start Translation
    translate(translate_images, translate_ad_images, thinking_level)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        console.print_exception()
        wait_for_exit("오류가 발생하여 프로그램을 종료합니다.")