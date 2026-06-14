"""Subtitle translation worker using DeepSeek (OpenAI-compatible API).

`_call_api` is the raw HTTP call.  `_default_translate` wraps it with retry
and is injectable so tests never make real network requests.
`do_translate` holds all DB logic and is called by the ARQ task and the sync
fallback in the API.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pysrt
from sqlmodel import Session, select

from app.core.db import engine
from app.core.safe_fs import atomic_write
from app.models import (
    ExternalSubtitle,
    Job,
    JobStatus,
    LanguageSource,
    Movie,
    SubSource,
)
from app.scanner.naming import canonical_sub_path

log = logging.getLogger(__name__)

BATCH_SIZE = 25
# Represents a newline within one subtitle block during round-trip through the LLM.
_NL = "⏎"  # ⏎
_ENVELOPE_RE = re.compile(r"^\[\[(\d+)\]\]\s?(.*)")


def _parse_numbered_response(text: str, n: int) -> list[str]:
    """Extract [[N]]-prefixed lines from an LLM response.

    Ignores prose/commentary lines that lack the [[N]] prefix.
    Raises RuntimeError when >10 % of indices are missing.
    Returns list of length n; missing indices become empty strings.
    """
    result: dict[int, str] = {}
    for line in text.splitlines():
        m = _ENVELOPE_RE.match(line)
        if m:
            idx = int(m.group(1))
            if 1 <= idx <= n:
                result[idx] = m.group(2)

    missing = n - len(result)
    threshold = max(1, n // 10)
    if missing > threshold:
        raise RuntimeError(
            f"[[N]] response missing {missing}/{n} indices; response: {text[:300]!r}"
        )
    return [result.get(i, "") for i in range(1, n + 1)]


def _call_api(
    lines: list[str],
    target_lang: str,
    source_lang_hint: str | None,
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> list[str]:
    """Send one batch of subtitle lines to the LLM and return translated lines."""
    import httpx  # noqa: PLC0415

    encoded = [t.replace("\n", _NL) for t in lines]
    n = len(encoded)
    block = "\n".join(f"[[{i}]] {line}" for i, line in enumerate(encoded, 1))

    source_desc = f"from {source_lang_hint} " if source_lang_hint else ""
    system_msg = (
        "You are a professional subtitle translator. "
        "Translate subtitle lines accurately and naturally. "
        f"The character {_NL!r} represents an in-block line break — preserve it. "
        "IMPORTANT: prefix every output line with [[N]] using the same number as the input line."
    )
    user_msg = (
        f"Translate the following {n} subtitle lines {source_desc}to {target_lang}. "
        f"Return exactly {n} lines, each prefixed with [[N]] matching the input number. "
        f"Preserve any {_NL!r} characters. Do not add commentary.\n\n"
        + block
    )

    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.3,
            },
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]

    parsed = _parse_numbered_response(text, n)
    return [t.replace(_NL, "\n") for t in parsed]


def _default_translate(
    lines: list[str],
    target_lang: str,
    source_lang_hint: str | None,
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> list[str]:
    """Translate lines with retry (3 attempts, exponential back-off)."""
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(3):
        try:
            return _call_api(lines, target_lang, source_lang_hint,
                             api_key=api_key, base_url=base_url, model=model)
        except Exception as exc:
            last_exc = exc
            log.warning("translate attempt %d failed: %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last_exc


def _read_srt(path: Path) -> pysrt.SubRipFile:
    content = path.read_text(encoding="utf-8", errors="replace")
    return pysrt.from_string(content)


def _translate_batch(
    batch: list[str],
    fn: Callable,
    target_lang: str,
    source_lang: str | None,
    api_key: str,
    base_url: str,
    model: str,
) -> list[str]:
    """Call fn on batch; on failure halve once and retry each half."""
    try:
        return fn(batch, target_lang, source_lang,
                  api_key=api_key, base_url=base_url, model=model)
    except Exception as exc:
        if len(batch) <= 1:
            raise
        log.warning("batch of %d failed (%s) — halving and retrying", len(batch), exc)
        mid = len(batch) // 2
        left = fn(batch[:mid], target_lang, source_lang,
                  api_key=api_key, base_url=base_url, model=model)
        right = fn(batch[mid:], target_lang, source_lang,
                   api_key=api_key, base_url=base_url, model=model)
        return left + right


def do_translate(
    job_id: int,
    *,
    session: Session,
    translate_fn: Callable | None = None,
) -> dict:
    """Core translation logic — called by ARQ worker and sync fallback."""
    job = session.get(Job, job_id)
    if not job:
        raise RuntimeError(f"Job {job_id} not found")

    job.status = JobStatus.running
    job.started_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()

    try:
        params = job.params or {}
        sub_id: int = params["sub_id"]
        target_lang: str = params["target_language"]
        source_lang: str | None = params.get("source_language")

        sub = session.get(ExternalSubtitle, sub_id)
        if not sub:
            raise RuntimeError(f"ExternalSubtitle {sub_id} not found")

        movie = session.get(Movie, sub.movie_id)
        if not movie:
            raise RuntimeError(f"Movie {sub.movie_id} not found")

        src_path = Path(sub.path)
        if not src_path.exists():
            raise RuntimeError(f"Source subtitle file not found: {src_path}")

        from app.core.config import settings  # noqa: PLC0415

        # Only enforce key when using the real API (injected fn provides its own auth).
        if translate_fn is None and not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")

        fn = translate_fn or _default_translate

        srt_subs = _read_srt(src_path)
        texts = [item.text for item in srt_subs]
        total = len(texts)

        if total == 0:
            raise RuntimeError("Source subtitle file is empty")

        translated: list[str] = []
        batches = [texts[i : i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

        for batch_idx, batch in enumerate(batches):
            translated_batch = _translate_batch(
                batch,
                fn,
                target_lang,
                source_lang or sub.language,
                api_key=settings.deepseek_api_key,
                base_url=settings.openai_base_url,
                model=settings.translate_model,
            )
            translated.extend(translated_batch)
            pct = min(99, int((batch_idx + 1) / len(batches) * 100))
            job.progress = pct
            job.log += f"[batch {batch_idx + 1}/{len(batches)}] {len(translated)}/{total} lines\n"
            session.add(job)
            session.commit()

        # Write translated SRT.
        for item, new_text in zip(srt_subs, translated, strict=True):
            item.text = new_text
        # pysrt.SubRipFile is a list — str() gives repr. Build SRT manually.
        srt_content = "\n".join(str(item) for item in srt_subs)

        out_path = Path(
            canonical_sub_path(
                movie.folder_path,
                movie.title,
                movie.year,
                target_lang,
                forced=sub.forced,
                sdh=sub.sdh,
                custom_tag="ai",
                ext="srt",
            )
        )
        atomic_write(out_path, srt_content.encode("utf-8"), replace=True)

        # Replace stale translated sub for the same target language (if any).
        existing = session.exec(
            select(ExternalSubtitle)
            .where(ExternalSubtitle.movie_id == movie.id)
            .where(ExternalSubtitle.source == SubSource.translated)
            .where(ExternalSubtitle.language == target_lang)
        ).first()
        if existing:
            session.delete(existing)
            session.flush()

        new_sub = ExternalSubtitle(
            movie_id=movie.id,
            path=str(out_path),
            real_path=str(out_path),
            is_symlink=False,
            filename=out_path.name,
            rel_dir="",
            language=target_lang,
            language_source=LanguageSource.manual,
            format="srt",
            forced=sub.forced,
            sdh=sub.sdh,
            custom_tag="ai",
            source=SubSource.translated,
            parent_sub_id=sub_id,
            created_at=datetime.now(timezone.utc),
        )
        session.add(new_sub)

        job.status = JobStatus.done
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        job.log += f"Translated {total} lines → {out_path.name}\n"
        session.add(job)
        session.commit()
        session.refresh(new_sub)
        return {"sub_id": new_sub.id, "path": str(out_path), "language": target_lang}

    except Exception as exc:
        log.exception("do_translate failed for job %s", job_id)
        job.status = JobStatus.failed
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        raise


async def run_translate(ctx: dict, job_id: int) -> dict:  # noqa: ARG001
    with Session(engine) as session:
        return do_translate(job_id, session=session)
