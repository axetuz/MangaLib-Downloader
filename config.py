from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass
class Config:
    manga_slug: str
    chapter_range: Tuple[int, int]
    series_title_override: Optional[str] = None
    volume_override: Optional[int] = None
    output_dir: Path = Path("downloads")
    max_concurrent_chapters: int = 3
    max_concurrent_images: int = 8
    request_delay: float = 0.03
    fallback_volume_range: Tuple[int, int] = (1, 15)
    cleanup_temp: bool = True
    api_base: str = "https://api.cdnlibs.org/api/manga"
    image_host: str = "https://img3.mixlib.me"
    referer: str = "https://mangalib.me/"