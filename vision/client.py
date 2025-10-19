from typing import Protocol

class VisionClient(Protocol):
    def analyze(self, base64_image, prompt: str) -> str: ...