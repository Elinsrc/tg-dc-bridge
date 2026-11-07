# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Elinsrc

import asyncio
import shutil
import tempfile
from pathlib import Path

from loguru import logger

from bridge.constants import GIF_MAX_FPS, GIF_TIMEOUT


class GifConverter:
    OPAQUE = "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    TRANSPARENT = (
        "split[s0][s1];[s0]palettegen=reserve_transparent=1[p];"
        "[s1][p]paletteuse=alpha_threshold=128"
    )

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg:
            logger.warning("ffmpeg not found: Telegram GIFs and stickers will be sent without conversion")

    async def video_to_gif(self, data: bytes) -> bytes | None:
        if not self.ffmpeg:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.mp4", Path(tmp) / "out.gif"
            src.write_bytes(data)
            video_filter = f"{await self._fps_cap(src)}{self.OPAQUE}"
            return await self._encode(["-i", str(src), "-vf", video_filter, "-loop", "0"], dst)

    async def webm_to_gif(self, data: bytes) -> bytes | None:
        if not self.ffmpeg:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.webm", Path(tmp) / "out.gif"
            src.write_bytes(data)
            video_filter = f"{await self._fps_cap(src)}{self.TRANSPARENT}"
            return await self._encode(
                ["-c:v", "libvpx-vp9", "-i", str(src), "-vf", video_filter,
                 "-gifflags", "-offsetting", "-loop", "0"],
                dst,
            )

    async def tgs_to_gif(self, data: bytes) -> bytes | None:
        if not self.ffmpeg:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            src, dst = workdir / "in.tgs", workdir / "out.gif"
            src.write_bytes(data)
            fps = await asyncio.to_thread(self._render_tgs, src, workdir)
            if not fps:
                return None
            return await self._encode(
                ["-framerate", f"{fps:.3f}", "-i", str(workdir / "f%04d.png"), "-vf", self.TRANSPARENT,
                 "-gifflags", "-offsetting", "-loop", "0"],
                dst,
            )

    @staticmethod
    def _render_tgs(src: Path, workdir: Path) -> float | None:
        try:
            from rlottie_python import LottieAnimation
        except ImportError:
            logger.warning("rlottie-python is not installed: animated stickers will be sent as static images")
            return None
        try:
            anim = LottieAnimation.from_tgs(str(src))
            total = int(anim.lottie_animation_get_totalframe())
            source_fps = float(anim.lottie_animation_get_framerate()) or 30.0
            out_fps = min(source_fps, GIF_MAX_FPS)
            count = max(1, round(total * out_fps / source_fps))
            for n in range(count):
                frame = min(total - 1, int(n * source_fps / out_fps))
                anim.render_pillow_frame(frame_num=frame).save(workdir / f"f{n:04d}.png")
            return out_fps
        except Exception as e:
            logger.warning("TGS render failed: {!r}", e)
            return None

    async def _fps_cap(self, src: Path) -> str:
        if not self.ffprobe:
            return ""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate", "-of", "default=nw=1:nk=1", str(src),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), 15)
            num, den = out.decode().strip().split("/")
            fps = int(num) / int(den)
        except Exception:
            return ""
        return f"fps={GIF_MAX_FPS}," if fps > GIF_MAX_FPS else ""

    async def _encode(self, args: list[str], dst: Path) -> bytes | None:
        if not await self._run(*args, str(dst)) or not dst.exists():
            return None
        data = dst.read_bytes()
        if len(data) > self.max_bytes:
            logger.warning("GIF is {} bytes, too large for Discord, sending original", len(data))
            return None
        return data

    async def _run(self, *args: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            self.ffmpeg, "-v", "error", "-y", *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), GIF_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("GIF conversion timed out")
            return False
        if proc.returncode != 0:
            logger.warning("GIF conversion failed: {}", err.decode(errors="ignore").strip())
            return False
        return True
