from typing import Optional, Protocol

class VideoClient(Protocol):
    def generate_video(self, prompt: str, image_path: Optional[str] = None) -> str: ...
