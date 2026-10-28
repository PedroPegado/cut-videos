import asyncio
import json
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import psutil
from .config import settings
from .models import TaskRequest


def kill_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass


async def command(args, folder=None, callback=None, limit=16_000_000):
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, limit=20_000_000)
    output = []
    size = 0
    async def read():
        nonlocal size
        while line := await process.stdout.readline():
            text = line.decode('utf-8', errors='replace')
            size += len(line)
            if size > limit:
                raise RuntimeError('A saída do processo excedeu o limite.')
            output.append(text)
            if callback:
                callback(text)
        await process.wait()
    reader = asyncio.create_task(read())
    try:
        async with asyncio.timeout(settings.task_timeout):
            while not reader.done():
                await asyncio.wait({reader}, timeout=.25)
                if folder and sum(p.stat().st_size for p in folder.glob('**/*') if p.is_file()) > settings.max_bytes:
                    raise RuntimeError('O arquivo excedeu o limite de armazenamento.')
            await reader
        if process.returncode:
            raise RuntimeError('Não foi possível processar o vídeo. Ele pode estar indisponível, restrito ou a rede pode ter falhado.')
        return ''.join(output)
    finally:
        if process.returncode is None:
            kill_tree(process.pid)
            await process.wait()
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


def ytdlp():
    return [sys.executable, '-m', 'app.extractor', '--ignore-config', '--no-playlist', '--no-warnings', '--proxy', '',
            '--socket-timeout', '20', '--retries', '2', '--extractor-retries', '2',
            '--no-check-formats', '--no-cache-dir', '--js-runtimes', 'node']


metadata_slots = asyncio.Semaphore(2)


async def metadata(url):
    if metadata_slots.locked():
        raise RuntimeError('Muitas consultas em andamento. Tente novamente em instantes.')
    async with metadata_slots:
        async with asyncio.timeout(60):
            info = json.loads(await command(ytdlp() + ['--skip-download', '--dump-single-json', '--', url]))
    duration = info.get('duration')
    if info.get('is_live') or not duration or duration > settings.max_duration:
        raise RuntimeError('Vídeo ao vivo ou com duração fora do limite permitido.')
    if info.get('availability') not in (None, 'public', 'unlisted') or info.get('has_drm'):
        raise RuntimeError('Este conteúdo possui restrições de acesso.')
    formats = [f for f in info.get('formats', []) if not f.get('has_drm')]
    height = max((f.get('height') or 0 for f in formats), default=0)
    return {'id': info['id'], 'title': info.get('title', 'Vídeo'), 'channel': info.get('channel', ''),
            'duration': duration, 'thumbnail': f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg",
            'qualities': [str(h) for h in (2160, 1440, 1080, 720, 480, 360) if h <= height]}


@dataclass
class Job:
    id: str
    request: TaskRequest
    status: str = 'queued'
    progress: float = 0
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    file: Path | None = None
    worker: asyncio.Task | None = None
    readers: int = 0

    def public(self):
        return {'id': self.id, 'status': self.status, 'progress': self.progress, 'error': self.error,
                'filename': self.file.name if self.file else None}


class Manager:
    def __init__(self):
        self.jobs = {}
        self.slots = asyncio.Semaphore(settings.max_concurrent)

    def create(self, request):
        if len(self.jobs) >= settings.max_tasks:
            raise RuntimeError('Limite de tarefas atingido. Aguarde a limpeza automática.')
        job = Job(uuid.uuid4().hex, request)
        self.jobs[job.id] = job
        job.worker = asyncio.create_task(self.run(job))
        return job

    def cancel(self, job):
        if job.status not in ('completed', 'failed', 'cancelled'):
            job.status = 'cancelled'
            job.finished = time.time()
            job.worker.cancel()

    async def run(self, job):
        folder = settings.temp_dir / job.id
        try:
            async with self.slots, asyncio.timeout(settings.task_timeout):
                folder.mkdir(parents=True, exist_ok=True)
                job.status = 'obtaining'
                r = job.request
                info = await metadata(r.url)
                if r.mode == 'clip' and (r.end > info['duration'] or r.start >= info['duration']):
                    raise RuntimeError('O intervalo ultrapassa a duração do vídeo.')
                if r.quality != 'best' and r.quality not in info['qualities']:
                    raise RuntimeError('Qualidade indisponível para este vídeo.')
                height = '' if r.quality == 'best' else f'[height<={r.quality}]'
                fmt = 'bestaudio/best' if r.format in ('mp3', 'm4a') else f'bestvideo{height}+bestaudio/best{height}'
                args = ytdlp() + ['--newline', '--progress', '--progress-template', 'download:PROGRESS:%(progress._percent_str)s',
                    '--max-filesize', str(settings.max_bytes), '--ffmpeg-location', settings.ffmpeg_path,
                    '-f', fmt, '--merge-output-format', 'mkv', '-o', str(folder / 'source.%(ext)s')]
                if r.mode == 'clip':
                    args += ['--download-sections', f'*{r.start}-{r.end}', '--force-keyframes-at-cuts']
                def progress(line):
                    if 'PROGRESS:' in line:
                        match = re.search(r'PROGRESS:\s*([\d.]+)%', line)
                        if match:
                            job.progress = max(job.progress, min(65, float(match[1]) * .65))
                    if '[VideoConvertor]' in line:
                        job.status = 'cutting'
                job.status = 'downloading'
                await command(args + ['--', r.url], folder, progress)
                sources = [p for p in folder.glob('source.*') if p.suffix not in ('.part', '.ytdl')]
                if len(sources) != 1:
                    raise RuntimeError('O download não gerou um arquivo válido.')
                job.status = 'converting'
                job.progress = 68
                name = re.sub(r'[^\w .-]', '', info['title'], flags=re.UNICODE).strip(' .')[:100] or 'video'
                target = folder / f'ClipCut-{name}.{r.format}'
                codecs = {'mp4': ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart'],
                          'webm': ['-c:v', 'libvpx-vp9', '-deadline', 'good', '-cpu-used', '4', '-crf', '32', '-b:v', '0', '-c:a', 'libopus'],
                          'mp3': ['-vn', '-c:a', 'libmp3lame', '-q:a', '2'], 'm4a': ['-vn', '-c:a', 'aac', '-b:a', '192k']}[r.format]
                duration = r.end - r.start if r.mode == 'clip' else info['duration']
                def conversion(line):
                    if line.startswith('out_time_us='):
                        try:
                            job.progress = min(97, 68 + float(line.split('=')[1]) / 1e6 / duration * 29)
                        except ValueError:
                            pass
                await command([settings.ffmpeg_path, '-nostdin', '-y', '-i', str(sources[0]),
                    '-map', '0:a:0'] + ([] if r.format in ('mp3', 'm4a') else ['-map', '0:v:0', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2']) +
                    codecs + ['-t', str(duration), '-progress', 'pipe:1', '-nostats', str(target)], folder, conversion)
                probe = json.loads(await command([settings.ffprobe_path, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(target)]))
                if float(probe['format'].get('duration', 0)) <= 0 or not any(s['codec_type'] == 'audio' for s in probe['streams']):
                    raise RuntimeError('O arquivo final não passou na verificação de áudio e duração.')
                sources[0].unlink()
                job.file, job.status, job.progress = target, 'completed', 100
        except asyncio.CancelledError:
            job.status = 'cancelled'
        except TimeoutError:
            job.status, job.error = 'failed', 'Tempo limite excedido. Tente um trecho menor.'
        except Exception as exc:
            job.status, job.error = 'failed', str(exc) if isinstance(exc, RuntimeError) else 'Falha no processamento. Verifique FFmpeg e a conexão.'
        finally:
            job.finished = time.time()
            if job.status != 'completed':
                shutil.rmtree(folder, ignore_errors=True)

    def cleanup(self):
        for key, job in list(self.jobs.items()):
            if job.finished and not job.readers and time.time() - job.finished > settings.retention_seconds:
                shutil.rmtree(settings.temp_dir / key, ignore_errors=True)
                del self.jobs[key]


manager = Manager()
