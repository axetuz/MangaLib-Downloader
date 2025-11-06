import asyncio
from pathlib import Path

from config import Config
from downloader import ChapterDownloader


async def main():
    # ========== КОНФИГУРАЦИЯ ==========
    cfg = Config(
        manga_slug="114307--kaoru-hana-wa-rinto-saku",
        chapter_range=(54, 56),  # (начальная глава, конечная глава)
        series_title_override="Kaoru Hana Wa Rin To Saku",
        
        # Параметры производительности
        max_concurrent_chapters=1,  # рекомендуется: 1-5
        max_concurrent_images=5,    # рекомендуется: 2-10
        request_delay=0.1,          # рекомендуется: 0.5-5
        
        # Дополнительные параметры
        output_dir=Path("downloads"),
        cleanup_temp=True,
        fallback_volume_range=(1, 15)
    )
    # ========== КОНФИГУРАЦИЯ ==========

    downloader = ChapterDownloader(cfg)
    await downloader.download_chapters(cfg.chapter_range)


if __name__ == "__main__":
    asyncio.run(main())