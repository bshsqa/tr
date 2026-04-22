import os
import re
import io
import json
import time
from google import genai
from google.genai import types
from PIL import Image


class Translator:
    def __init__(self, text_length: int, thinking_level: str):
        self.client = genai.Client(
            api_key=os.environ.get("GOOGLE_API_KEY"),
        )

        self.text_length = text_length
        self.glossary = ""
        self.honorifics = []
        self.memory = []

        self.safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",        threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="OFF"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",         threshold="OFF"),
        ]

        self.text_model = "gemini-3.1-flash-lite-preview"
        self.text_model_config = types.GenerateContentConfig(
            temperature=1,
            top_p=0.95,
            max_output_tokens=65535,
            safety_settings=self.safety_settings,
            response_mime_type="application/json",
            response_schema={"type": "OBJECT", "properties": {"translation": {"type": "STRING"}}},
            thinking_config=types.ThinkingConfig(
                thinking_level=thinking_level,
            ),
        )

    def set_glossary(self, glossary: dict):
        if not glossary:
            self.glossary = ""
            return

        lines = ["Glossary (YOU MUST use these exact Korean translations — never deviate):"]
        for src_term, tgt_term in glossary.items():
            lines.append(f"- {src_term} : {tgt_term}")
        self.glossary = "\n".join(lines)

    def set_honorifics(self, honorifics: list):
        self.honorifics = honorifics

    def _get_honorifics_prompt(self) -> str:
        if not self.honorifics:
            return ""
        lines = [
            "Honorific rules — each honorific form is complete and already includes the suffix.",
            "Do NOT append さん, 상, 씨, or any other suffix on top of the specified form:",
        ]
        for caller, target, honorific in self.honorifics:
            lines.append(f'- When {caller} refers to {target}, always use "{honorific}"')
        return "\n".join(lines)

    def _gen_content(self, contents: list, model: str, config: types.GenerateContentConfig) -> types.GenerateContentResponse:
        while True:
            try:
                return self.client.models.generate_content(
                    model=model,
                    config=config,
                    contents=contents,
                )
            except Exception as e:
                e_code = getattr(e, "code", None)
                if e_code == 429:
                    print("요청 한도를 초과했습니다. 5초 후 재시도합니다...")
                    time.sleep(5)
                    continue
                if e_code == 401:
                    raise Exception("인증에 실패했습니다. API 키를 확인하고 다시 시도해주세요.")
                if e_code == 403:
                    raise Exception("권한이 없습니다. API 키의 권한을 확인하고 다시 시도해주세요.")
                print(f"Error Code: {e_code}, 5초 후 재시도합니다...")
                time.sleep(5)

    def _gen_content_dict(self, contents: list, model: str, config: types.GenerateContentConfig) -> dict:
        while True:
            try:
                res = self._gen_content(model=model, config=config, contents=contents)
                return json.loads(res.text)
            except json.JSONDecodeError:
                pass

    def _add_memory(self, text: str):
        self.memory.append(text)
        while len("\n".join(self.memory)) > self.text_length * 2:
            self.memory.pop(0)

    def _get_memory(self) -> str:
        if not self.memory:
            return ""
        joined = "\n".join(self.memory)
        return f"Translation memory (use for consistency; do not translate this section):\n{joined}\n"

    def _count_japanese(self, text: str) -> int:
        return len(re.findall(r'[぀-ヿ一-鿿]', text))

    def _find_japanese_contexts(self, text: str) -> list[str]:
        contexts = []
        for m in re.finditer(r'[぀-ヿ一-鿿]+', text):
            start = max(0, m.start() - 15)
            end = min(len(text), m.end() + 15)
            contexts.append(text[start:end])
        return contexts

    def _build_translate_contents(self, text: str, tgt_lang: str, retry_hint: str) -> list:
        contents = [
            f"You are a professional Japanese-to-{tgt_lang} translator specializing in light novels.",
            self.glossary,
            self._get_honorifics_prompt(),
            self._get_memory(),
            "Follow ALL of these rules strictly:",
            "1. Translate every Japanese character (hiragana, katakana, kanji) to Korean. The output must contain zero Japanese characters.",
            "2. Use the EXACT Korean terms from the glossary for every listed term. Never substitute or omit glossary terms.",
            "3. Translate Japanese interjections and fillers (えっと→음..., ええ→에..., あの→저..., うん→응, ねえ→있잖아, etc.) into natural Korean equivalents.",
            "4. Translate all onomatopoeia and mimetic words (擬音語·擬態語) into appropriate Korean equivalents (e.g. パチパチ→짝짝, ドキドキ→두근두근, ボロボロ→너덜너덜).",
            "5. Infer each character's unique speech style from context and maintain it consistently throughout.",
            "6. Produce natural, fluent Korean that reads as if originally written in Korean — not a literal translation.",
            "7. Preserve all line breaks exactly as in the source.",
            "8. Keep symbols such as 「」 unchanged.",
        ]
        if retry_hint:
            contents.append(retry_hint)
        contents.append(f"Translate the following text to {tgt_lang}:\n{text}")
        return contents

    def translate_text(self, text: str, tgt_lang: str = "Korean") -> str:
        best_result = ""
        best_jp_count = float("inf")
        retry_hint = ""

        for attempt in range(3):
            contents = self._build_translate_contents(text, tgt_lang, retry_hint)
            res = self._gen_content_dict(
                model=self.text_model,
                config=self.text_model_config,
                contents=contents,
            )
            translation = res.get("translation", "")

            jp_contexts = self._find_japanese_contexts(translation)
            if not jp_contexts:
                self._add_memory(translation)
                return translation

            jp_count = self._count_japanese(translation)
            if jp_count < best_jp_count:
                best_jp_count = jp_count
                best_result = translation

            context_list = "\n".join(f"  - '...{ctx}...'" for ctx in jp_contexts[:5])
            retry_hint = (
                f"WARNING: The previous translation still contained Japanese characters in the output. "
                f"The following parts must be fully translated to Korean — do not leave any Japanese:\n"
                f"{context_list}"
            )

        self._add_memory(best_result)
        return best_result

    def translate_image(self, image: Image.Image, tgt_lang: str = "Korean") -> Image.Image:
        raise NotImplementedError("Image translation is not supported with the free API.")
