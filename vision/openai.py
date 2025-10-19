from openai import OpenAI

from .client import VisionClient

class OpenAIVisionClient(VisionClient):
    def __init__(self, api_key: str, model: str):
        self.model = model
        self.openai = OpenAI(api_key=api_key)

    def analyze(self, base64_image, prompt: str):
        return self.openai.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        },
                    ]
                }
            ],
            model=self.model
        ).choices[0].message.content
