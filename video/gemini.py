import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from .client import VideoClient

class GeminiVideoClient(VideoClient):
    def __init__(self, api_key: str, model: str, images_path: Path):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.images_path = images_path

    def generate_video(self, prompt: str, image_path: Optional[str] = None) -> str:
        self.images_path.mkdir(parents=True, exist_ok=True)

        image = types.Image.from_file(location=str(image_path)) if image_path else None

        operation = self.client.models.generate_videos(
            model=self.model,
            prompt=prompt,
            image=image,
        )

        while not operation.done:
            time.sleep(10)
            operation = self.client.operations.get(operation)

        generated_video = operation.response.generated_videos[0]

        self.client.files.download(file=generated_video.video)

        output_file_path = self.images_path / f"{int(time.time())}.mp4"
        generated_video.video.save(str(output_file_path))

        return str(output_file_path)