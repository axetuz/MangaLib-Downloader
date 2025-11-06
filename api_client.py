import asyncio
import aiohttp
from pathlib import Path
from typing import Optional, Dict, Any

from config import Config
from colors import Colors


class MangaAPIClient:

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._session: Optional[aiohttp.ClientSession] = None
        self._chapters_map: Dict[str, Dict[float, int]] = {}
        self._series_cache: Dict[str, Dict[str, Any]] = {}
        self._headers = {
            "User-Agent": "Mozilla/5.0 (iPad; CPU OS 18_6_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/142.0.7444.46 Mobile/15E148 Safari/604.1",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9"
        }

    async def __aenter__(self):
        conn = aiohttp.TCPConnector(limit=self.cfg.max_concurrent_images * 2)
        self._session = aiohttp.ClientSession(connector=conn, headers=self._headers)
        await self._warm_up_session()
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    async def _warm_up_session(self):
        try:
            async with self._session.get(self.cfg.referer, timeout=6):
                pass
        except Exception:
            pass

    async def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None, 
                       retries: int = 5) -> Dict[str, Any]:
        for attempt in range(retries):
            try:
                async with self._session.get(url, params=params, timeout=30) as resp:
                    if resp.status == 429:
                        wait = self._calculate_retry_delay(resp.headers, attempt)
                        print(Colors.warning(
                            f"Rate limit (429). Retry in {wait:.2f}s... "
                            f"(Attempt {attempt + 1}/{retries})"
                        ))
                        await asyncio.sleep(wait)
                        continue

                    resp.raise_for_status()
                    data = await resp.json()
                    await asyncio.sleep(self.cfg.request_delay)
                    return data

            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    wait = self._calculate_retry_delay({}, attempt)
                    print(Colors.warning(
                        f"Rate limit (429) via exception. Retry in {wait:.2f}s... "
                        f"(Attempt {attempt + 1}/{retries})"
                    ))
                    await asyncio.sleep(wait)
                    continue
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))

            except Exception as e:
                if attempt == retries - 1:
                    print(Colors.error(f"Request failed after {retries} attempts: {e}"))
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))

        raise RuntimeError("Retries exhausted")

    @staticmethod
    def _calculate_retry_delay(headers: Dict[str, str], attempt: int) -> float:
        retry_after = headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return float(retry_after) + 1.0
        return min(2 ** attempt, 60) + 0.1 * attempt

    @staticmethod
    def _parse_float(value: str) -> Optional[float]:
        try:
            return float(value)
        except ValueError:
            try:
                return float(value.replace(",", "."))
            except ValueError:
                return None

    async def fetch_chapters_list(self, slug: str) -> Dict[float, int]:
        if slug in self._chapters_map:
            return self._chapters_map[slug]

        url = f"{self.cfg.api_base}/{slug}/chapters"
        mapping: Dict[float, int] = {}

        try:
            data = await self._get_json(url, retries=4)
            items = data.get("data", []) if isinstance(data, dict) else []

            for item in items:
                chapter_num = item.get("number")
                volume_num = item.get("volume")
                
                if chapter_num is None or volume_num is None:
                    continue

                chapter_float = self._parse_float(str(chapter_num))
                try:
                    volume_int = int(volume_num)
                except (ValueError, TypeError):
                    continue

                if chapter_float is not None:
                    mapping[chapter_float] = volume_int
        except Exception:
            mapping = {}

        self._chapters_map[slug] = mapping
        return mapping

    async def fetch_series_info(self, slug: str) -> Dict[str, Any]:
        if slug in self._series_cache:
            return self._series_cache[slug]

        url = f"{self.cfg.api_base}/{slug}"
        fields = [
            "background", "eng_name", "otherNames", "summary", "releaseDate", 
            "type_id", "caution", "views", "close_view", "rate_avg", "rate", 
            "genres", "tags", "teams", "user", "franchise", "authors", "publisher", 
            "userRating", "moderated", "metadata", "metadata.count", 
            "metadata.close_comments", "manga_status_id", "chap_count", 
            "status_id", "artists", "format"
        ]
        params = {f"fields[]": field for field in fields}
        
        try:
            data = await self._get_json(url, params=params, retries=3)
            result = data.get("data", {}) if isinstance(data, dict) else {}
        except Exception:
            result = {}

        self._series_cache[slug] = result
        return result

    async def fetch_chapter_data(self, slug: str, chapter_num: int, 
                                 volume: int) -> Dict[str, Any]:
        url = f"{self.cfg.api_base}/{slug}/chapter"
        return await self._get_json(
            url,
            params={"number": chapter_num, "volume": volume},
            retries=4
        )

    async def resolve_volume(self, slug: str, chapter_num: int) -> int:
        if self.cfg.volume_override is not None:
            return self.cfg.volume_override

        chapters_map = await self.fetch_chapters_list(slug)
        target_chapter = float(chapter_num)

        if chapters_map and target_chapter in chapters_map:
            return chapters_map[target_chapter]

        series_info = await self.fetch_series_info(slug)
        detected_volume = self._search_volume_in_metadata(series_info, target_chapter)
        
        if detected_volume is not None:
            try:
                await self.fetch_chapter_data(slug, chapter_num, detected_volume)
                return detected_volume
            except Exception:
                pass

        return await self._bruteforce_volume(slug, chapter_num)

    def _search_volume_in_metadata(self, metadata: Dict[str, Any], 
                                   target_chapter: float) -> Optional[int]:
        def search(obj) -> Optional[int]:
            if isinstance(obj, dict):
                num = obj.get("number") or obj.get("chapter_number")
                vol = obj.get("volume")
                
                if num is not None and vol is not None:
                    chapter_float = self._parse_float(str(num))
                    if chapter_float == target_chapter:
                        try:
                            return int(vol)
                        except (ValueError, TypeError):
                            pass
                
                for value in obj.values():
                    result = search(value)
                    if result is not None:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = search(item)
                    if result is not None:
                        return result
            return None

        return search(metadata)

    async def _bruteforce_volume(self, slug: str, chapter_num: int) -> int:
        start, end = self.cfg.fallback_volume_range
        
        for volume in range(start, end + 1):
            try:
                await asyncio.sleep(0.12)
                await self.fetch_chapter_data(slug, chapter_num, volume)
                return volume
            except Exception:
                continue

        raise ValueError(f"Could not determine volume for chapter {chapter_num}")

    async def download_image(self, url: str, dest: Path, retries: int = 10):
        headers = {
            **self._headers,
            "Referer": self.cfg.referer,
            "Origin": self.cfg.referer.rstrip("/")
        }

        for attempt in range(retries):
            try:
                async with self._session.get(url, headers=headers, timeout=60) as resp:
                    if resp.status == 429:
                        wait = self._calculate_retry_delay(resp.headers, attempt)
                        print(Colors.warning(
                            f"Rate limit (429) for image. Retry in {wait:.2f}s... "
                            f"(Attempt {attempt + 1}/{retries})"
                        ))
                        await asyncio.sleep(wait)
                        continue

                    if resp.status == 403 and attempt < retries - 1:
                        print(Colors.warning(
                            f"403 Forbidden. Warming up and retrying... "
                            f"(Attempt {attempt + 1}/{retries})"
                        ))
                        await self._warm_up_session()
                        await asyncio.sleep(0.3 * (attempt + 1))
                        continue

                    resp.raise_for_status()
                    data = await resp.read()
                    
                    if not data:
                        raise RuntimeError("Empty response")

                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    await asyncio.sleep(self.cfg.request_delay)
                    return

            except Exception as e:
                if attempt == retries - 1:
                    print(Colors.error(f"Image download failed after {retries} attempts: {e}"))
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))