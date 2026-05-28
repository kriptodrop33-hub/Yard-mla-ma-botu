import hashlib
import logging
import time
from typing import Optional

import aiohttp

from config import Config

logger = logging.getLogger(__name__)

# ─── Basit Türkçe küfür listesi (Groq rate-limit yedeği) ───────────────────
_LOCAL_BANNED = {
    "orospu", "oç", "oğlum", "göt", "sik", "amk", "amına", "bok",
    "piç", "salak", "aptal", "gerizekalı", "mal", "yarrak", "sikim",
    "götveren", "kahpe", "ibne", "puşt", "gavat", "amcık", "taşak",
    "orospu çocuğu", "bok gibi", "s.k", "a.k", "o.ç",
}

# ─── Sonuç önbelleği: {hash: (bool, timestamp)} ────────────────────────────
_cache: dict[str, tuple[bool, float]] = {}
_CACHE_TTL = 3_600  # 1 saat


class GroqFilter:
    def __init__(self):
        self.api_key  = Config.GROQ_API_KEY
        self.models   = Config.GROQ_MODELS
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.enabled  = bool(self.api_key)

    # ── Yerel kontrol ──────────────────────────────────────────────────────
    def _local_check(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in _LOCAL_BANNED)

    # ── Ana kontrol ────────────────────────────────────────────────────────
    async def is_profanity(self, text: str) -> bool:
        if not text or len(text) < 2:
            return False

        # Hızlı yerel kontrol
        if self._local_check(text):
            return True

        if not self.enabled or len(text) < 5:
            return False

        # Önbellek
        key = hashlib.md5(text[:200].encode()).hexdigest()
        if key in _cache:
            result, ts = _cache[key]
            if time.time() - ts < _CACHE_TTL:
                return result

        # Groq API — model sırasını dene
        for model in self.models:
            try:
                result = await self._query_groq(text[:500], model)
                _cache[key] = (result, time.time())
                return result
            except RateLimitError:
                logger.warning(f"Groq rate-limit: {model}, sıradaki modele geçiliyor…")
                continue
            except Exception as e:
                logger.warning(f"Groq hata ({model}): {e}")
                continue

        # Tüm modeller başarısız → yerel liste yeterli
        return False

    # ── Groq isteği ────────────────────────────────────────────────────────
    async def _query_groq(self, text: str, model: str) -> bool:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 5,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Sen bir Türkçe içerik moderatörüsün. "
                        "Verilen mesajın küfür, ağır hakaret veya cinsel içerik barındırıp "
                        "barındırmadığını söyle. Yalnızca 'EVET' ya da 'HAYIR' yaz."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Bu mesaj uygunsuz mu?\n\n{text}",
                },
            ],
        }
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession() as session:
            async with session.post(self.base_url, headers=headers, json=payload, timeout=timeout) as resp:
                if resp.status == 429:
                    raise RateLimitError()
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()
                answer = data["choices"][0]["message"]["content"].strip().upper()
                return "EVET" in answer


class RateLimitError(Exception):
    pass
