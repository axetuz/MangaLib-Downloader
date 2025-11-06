from dataclasses import dataclass
from typing import Optional, List


@dataclass
class ChapterInfo:
    number: int
    volume: int
    name: str
    pages_count: int
    series_title: Optional[str]
    teams: List[str]
    chapter_id: Optional[str] = None