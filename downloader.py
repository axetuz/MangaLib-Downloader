import asyncio
import json
import time
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Tuple, List
from collections import defaultdict
from tqdm.asyncio import tqdm as async_tqdm

from config import Config
from colors import Colors
from models import ChapterInfo
from api_client import MangaAPIClient
from metadata import MetadataGenerator


class ChapterDownloader:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.metadata_gen = MetadataGenerator(cfg)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sanitize_filename(text: str) -> str:
        text = text.strip()
        text = re.sub(r'[\\/*?:"<>|]', '_', text)
        return text[:200]

    @staticmethod
    def build_image_url(path: str, host: str) -> str:
        if not path:
            raise ValueError("Empty image path")
        
        if path.startswith("//"):
            path = path[1:]
        
        if path.startswith("http"):
            return path
        
        if not path.startswith("/"):
            path = "/" + path
        
        return host + path

    @staticmethod
    def clean_chapter_name(name: str) -> str:
        name = re.sub(r'\s*\([^)]*\d[^)]*\)', '', name).strip()
        name = re.sub(r'\d+', '', name).strip()
        return name

    async def download_chapter(self, api: MangaAPIClient, chapter_num: int) -> Optional[Tuple[Path, ChapterInfo]]:
        tmp_dir = self.cfg.output_dir / f"_tmp_ch{chapter_num}_{int(time.time())}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            volume = await api.resolve_volume(self.cfg.manga_slug, chapter_num)
            
            chapter_json = await api.fetch_chapter_data(
                self.cfg.manga_slug, chapter_num, volume
            )
            data = chapter_json.get("data", {})

            if not isinstance(data, dict):
                raise ValueError("Invalid API response: 'data' is not a dictionary")

            pages = data.get("pages", [])
            if not pages:
                raise ValueError("No pages found")

            series_title = await self._get_series_title(api, data)

            chapter_name = self.clean_chapter_name(str(data.get("name") or "").strip())

            teams = [
                t.get("name", "") 
                for t in data.get("teams", []) 
                if isinstance(t, dict)
            ]

            print(f"\n{Colors.chapter(chapter_num)} | {Colors.title(series_title)}")
            print(f"  Volume: {volume} | Pages: {len(pages)} | Name: {chapter_name or 'N/A'}")

            urls = [
                self.build_image_url(
                    p.get("url") or p.get("image", ""), 
                    self.cfg.image_host
                )
                for p in pages
                if isinstance(p, dict)
            ]

            if not urls:
                raise ValueError("No valid image URLs found")

            await self._download_images(api, urls, tmp_dir, chapter_num)

            info = ChapterInfo(
                number=chapter_num,
                volume=volume,
                name=chapter_name,
                pages_count=len(urls),
                series_title=series_title,
                teams=teams,
                chapter_id=str(data.get("id", ""))
            )

            return tmp_dir, info

        except Exception as e:
            print(Colors.error(f"Chapter {chapter_num}: {e}"))
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

    async def _get_series_title(self, api: MangaAPIClient, chapter_data: dict) -> str:
        if self.cfg.series_title_override:
            return self.cfg.series_title_override

        meta = await api.fetch_series_info(self.cfg.manga_slug)
        raw_title = (meta.get("name") or meta.get("title") or 
                    chapter_data.get("manga_id") or "Unknown")
        return str(raw_title).strip()

    async def _download_images(self, api: MangaAPIClient, urls: List[str], 
                               tmp_dir: Path, chapter_num: int):
        sem = asyncio.Semaphore(self.cfg.max_concurrent_images)

        async def download_task(idx: int, url: str):
            async with sem:
                ext = Path(url).suffix or ".jpg"
                filename = f"{idx:03d}{ext}"
                await api.download_image(url, tmp_dir / filename)

        tasks = [download_task(i + 1, url) for i, url in enumerate(urls)]
        await async_tqdm.gather(
            *tasks, 
            desc=f"  Downloading Ch{chapter_num}", 
            unit="img"
        )

    def create_cbz(self, tmp_dir: Path, info: ChapterInfo, cbz_path: Path):
        final_series_title = info.series_title or self.cfg.manga_slug

        meta = {
            "series": final_series_title,
            "chapter_number": info.number,
            "volume": info.volume,
            "chapter_name": info.name,
            "chapter_id": info.chapter_id,
            "teams": info.teams,
            "pages": info.pages_count,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        comicinfo_xml = self.metadata_gen.create_chapter_comicinfo(info)

        with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("info.txt", json.dumps(meta, ensure_ascii=False, indent=2))
            zf.writestr("ComicInfo.xml", comicinfo_xml)
            
            for file in sorted(tmp_dir.iterdir()):
                if file.is_file():
                    zf.write(file, arcname=file.name)

    async def download_chapters(self, chapter_range: Tuple[int, int]) -> List[Path]:
        start, end = chapter_range
        chapters = list(range(start, end + 1))

        self._print_header(start, end, len(chapters))

        async with MangaAPIClient(self.cfg) as api:
            try:
                await api.fetch_chapters_list(self.cfg.manga_slug)
            except Exception:
                pass

            series_meta = await api.fetch_series_info(self.cfg.manga_slug)
            series_title = self._determine_series_title(series_meta)

            results = await self._download_all_chapters(api, chapters)

        successful, failed_count = self._process_results(chapters, results)

        if not successful:
            print(Colors.error("No chapters downloaded successfully"))
            return []

        zip_path = await self._create_series_archive(
            successful, series_title, series_meta, api
        )

        self._print_summary(len(successful), len(chapters), failed_count)

        return [zip_path] if zip_path else []

    def _print_header(self, start: int, end: int, total: int):
        print(f"\n{Colors.BOLD}╔══════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.BOLD}║         MangaLib Downloader v2.0         ║{Colors.RESET}")
        print(f"{Colors.BOLD}╚══════════════════════════════════════════╝{Colors.RESET}")
        
        series_info = self.cfg.series_title_override or f"{self.cfg.manga_slug} (from slug)"
        print(f"\n{Colors.info(f'Manga: {series_info}')}")
        print(f"{Colors.info(f'Chapters: {start}-{end} ({total} total)')}")
        print(f"{Colors.info(f'Concurrency: {self.cfg.max_concurrent_chapters} chapters, {self.cfg.max_concurrent_images} images')}\n")

    def _determine_series_title(self, series_meta: dict) -> str:
        return (self.cfg.series_title_override or 
                series_meta.get("name") or 
                series_meta.get("rus_name") or 
                series_meta.get("eng_name") or 
                self.cfg.manga_slug)

    async def _download_all_chapters(self, api: MangaAPIClient, chapters: List[int]) -> list:
        sem = asyncio.Semaphore(self.cfg.max_concurrent_chapters)

        async def download_with_limit(ch: int):
            async with sem:
                return await self.download_chapter(api, ch)

        return await asyncio.gather(
            *[download_with_limit(ch) for ch in chapters],
            return_exceptions=True
        )

    def _process_results(self, chapters: List[int], 
                        results: list) -> Tuple[list, int]:
        successful = []
        failed_count = 0
        
        for ch, result in zip(chapters, results):
            if isinstance(result, Exception):
                print(Colors.error(f"Chapter {ch}: {result}"))
                failed_count += 1
            elif result:
                successful.append(result)
        
        return successful, failed_count

    async def _create_series_archive(self, successful: list, series_title: str, series_meta: dict, api: MangaAPIClient) -> Path:
        volume_groups = defaultdict(list)
        for tmp_dir, info in successful:
            volume_groups[info.volume].append((tmp_dir, info))

        temp_series_dir = self.cfg.output_dir / f"_tmp_series_{int(time.time())}"
        temp_series_dir.mkdir(parents=True, exist_ok=True)

        sanitized_series = self.sanitize_filename(series_title)
        series_folder = temp_series_dir / sanitized_series
        series_folder.mkdir(exist_ok=True)

        await self._download_series_cover(series_meta, series_folder, api)

        self._create_series_metadata(series_folder, series_title, series_meta)

        self._process_volumes(volume_groups, series_folder, series_title, series_meta)

        zip_path = self._create_final_archive(temp_series_dir, sanitized_series)

        self._cleanup(successful, temp_series_dir)

        return zip_path

    async def _download_series_cover(self, series_meta: dict, series_folder: Path, api: MangaAPIClient):
        cover = series_meta.get("cover", {})
        cover_url = cover.get("default") if isinstance(cover, dict) else cover
        
        if not cover_url:
            return

        cover_names = [
            "Series Cover.jpg", "cover.jpg", "folder.jpg", 
            "poster.jpg", "thumbnail.jpg"
        ]
        
        for name in cover_names:
            try:
                await api.download_image(cover_url, series_folder / name)
            except Exception as e:
                print(Colors.warning(f"Failed to download cover '{name}': {e}"))

    def _create_series_metadata(self, series_folder: Path, series_title: str, series_meta: dict):
        
        series_xml = self.metadata_gen.create_series_comicinfo(
            series_title, series_meta
        )
        (series_folder / "ComicInfo.xml").write_bytes(series_xml)

        series_json = self.metadata_gen.create_series_json(
            series_title, series_meta
        )
        (series_folder / "series.json").write_text(series_json, encoding="utf-8")

    def _process_volumes(self, volume_groups: dict, series_folder: Path, series_title: str, series_meta: dict):
        for volume in sorted(volume_groups):
            chapter_list = sorted(volume_groups[volume], key=lambda x: x[1].number)
            
            vol_name = f"Volume {volume:02d}"
            sanitized_vol = self.sanitize_filename(vol_name)
            vol_folder = series_folder / sanitized_vol
            vol_folder.mkdir(exist_ok=True)

            vol_xml = self.metadata_gen.create_volume_comicinfo(
                volume, series_title, len(chapter_list), series_meta
            )
            (vol_folder / "ComicInfo.xml").write_bytes(vol_xml)

            for tmp_dir, info in chapter_list:
                chap_name = f"Chapter {info.number:03d}"
                sanitized_chap = self.sanitize_filename(chap_name)
                cbz_path = vol_folder / f"{sanitized_chap}.cbz"
                self.create_cbz(tmp_dir, info, cbz_path)

    def _create_final_archive(self, temp_series_dir: Path, sanitized_series: str) -> Path:
        zip_base = self.cfg.output_dir / sanitized_series
        shutil.make_archive(str(zip_base), 'zip', str(temp_series_dir))
        zip_path = zip_base.with_suffix('.zip')
        print(Colors.success(f"Saved archive: {zip_path.name}"))
        return zip_path

    def _cleanup(self, successful: list, temp_series_dir: Path):
        if not self.cfg.cleanup_temp:
            return

        for tmp_dir, _ in successful:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        
        if temp_series_dir.exists():
            shutil.rmtree(temp_series_dir, ignore_errors=True)

    def _print_summary(self, successful: int, total: int, failed: int):
        print(f"\n{Colors.BOLD}{'═' * 50}{Colors.RESET}")
        print(Colors.success(f"Completed: {successful}/{total} chapters"))
        if failed:
            print(Colors.info(f"Failed: {failed} chapters"))
        print(Colors.info(f"Output directory: {self.cfg.output_dir.absolute()}"))
        print(f"{Colors.BOLD}{'═' * 50}{Colors.RESET}\n")