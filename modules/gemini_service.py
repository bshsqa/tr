# modules/gemini_service.py
import os
import io
import json
import time
from google import genai
from google.genai import types
from PIL import Image


class Translator:
    def __init__(self, text_length: int, thinking_level: str, vertexai: bool = True):
        self.client = self._get_client(vertexai)

        self.text_length = text_length

        self.glossary = ""
        self.memory = []

        self.safety_settings = [types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="OFF"
        ),types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="OFF"
        ),types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="OFF"
        ),types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="OFF"
        )]

        self.image_model = "gemini-3-pro-image-preview" # Nano Banana Pro
        self.image_model_config = types.GenerateContentConfig(
            temperature = 1,
            top_p = 0.95,
            max_output_tokens = 32768,
            response_modalities = ["IMAGE"],
            safety_settings = self.safety_settings,
            image_config=types.ImageConfig(
            #aspect_ratio="2:3",
            #image_size="1K",
            output_mime_type="image/png",
            ),
        )
        self.text_in_image_config = types.GenerateContentConfig(
            temperature = 1,
            top_p = 0.95,
            max_output_tokens = 65535,
            safety_settings = self.safety_settings,
            response_mime_type = "application/json",
            response_schema = {"type":"OBJECT","properties":{"is_text_present":{"type":"BOOLEAN"}}},
            thinking_config=types.ThinkingConfig(
            thinking_level="MINIMAL", # MINIMAL, LOW, MEDIUM, HIGH
            ),
        )

        self.text_model = "gemini-3-flash-preview"
        self.text_model_config = types.GenerateContentConfig(
            temperature = 1,
            top_p = 0.95,
            max_output_tokens = 65535,
            safety_settings = self.safety_settings,
            response_mime_type = "application/json",
            response_schema = {"type":"OBJECT","properties":{"translation":{"type":"STRING"}}},
            thinking_config=types.ThinkingConfig(
            thinking_level=thinking_level, # MINIMAL, LOW, MEDIUM, HIGH
            ),
        )
    
    def _get_client(self, vertexai: bool):
        return genai.Client(
            vertexai=vertexai,
            api_key=os.environ.get("GOOGLE_CLOUD_API_KEY") if vertexai else os.environ.get("GOOGLE_API_KEY"),
        )
    
    def set_glossary(self, glossary: dict):
        if not glossary:
            self.glossary = ""
            return
        
        self.glossary = "Use the following glossary for translation:\n"
        for src_term, tgt_term in glossary.items():
            self.glossary += f"- {src_term} : {tgt_term}\n"
    
    def _gen_content(self, contents: list, model: str, config: types.GenerateContentConfig) -> types.GenerateContentResponse:
        while True:
            try:
                res = self.client.models.generate_content(
                    model=model,
                    config=config,
                    contents=contents
                )
                return res
            except Exception as e:
                e_code = getattr(e, 'code', None)
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
                res = self._gen_content(
                    model=model,
                    config=config,
                    contents=contents
                )
                return json.loads(res.text)
            except json.JSONDecodeError:
                pass

    
    def translate_image(self, image: Image.Image, tgt_lang: str = "Korean") -> Image.Image:
        contents = [
            f"Is there any text present in this image? Respond with a JSON object with a boolean field 'is_text_present'.",
            image
        ]
        res = self._gen_content_dict(
            model=self.text_model,
            config=self.text_in_image_config,
            contents=contents
        )
        is_text_present = res.get("is_text_present", False)
        if not is_text_present:
            return image

        contents = [
            "You are a professional translator specialized in image translation.",
            self.glossary,
            self._get_memory(),
            f"Translate the content of this image to {tgt_lang}. Provide only the translated image without any additional text or explanations:\n",
            image,
        ]

        # new
        res = self._gen_content(
            model=self.image_model,
            config=self.image_model_config,
            contents=contents
        )

        img_data = res.parts[0].inline_data
        img = Image.open(io.BytesIO(img_data.data))
        return img
    
    def _add_memory(self, text: str):
        self.memory.append(text)
        while len("\n".join(self.memory)) > self.text_length * 2:
            self.memory.pop(0)
    
    def _get_memory(self) -> str:
        memory_prompt = "\n".join(self.memory)
        memory_prompt = f"Translation memory (use for consistency; do not translate this memory):\n{memory_prompt}\n" if memory_prompt else ""
        return memory_prompt

    def translate_text(self, text: str, tgt_lang: str = "Korean") -> str:
        contents = [
            "You are a professional translator.",
            self.glossary,
            self._get_memory(),
            "Keep symbols such as 「」 unchanged.",
            "Preserve line breaks in the output. You always include appropriate line breaks in the translation.",
            f"Translate the following text to {tgt_lang}:\n",
            text
        ]

        res = self._gen_content_dict(
            model=self.text_model,
            config=self.text_model_config,
            contents=contents
        )

        translation = res.get("translation", "")
        self._add_memory(translation)
        return translation


if __name__ == "__main__":
    translator = Translator()
    img = Image.open("./test.png")
    translated_img = translator.translate_image(img, tgt_lang="Korean")
    translated_img.show()
    translated_img.save("translated_test.png")
    #text = "Hello, how are you?"
    #translated_text = translator.translate_text(text, tgt_lang="Korean")
    #print("\n" + translated_text)