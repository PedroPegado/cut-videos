import asyncio
import shutil
from contextlib import asynccontextmanager
from urllib.parse import quote
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from .config import settings
from .models import VideoRequest, TaskRequest
from .service import manager, metadata


@asynccontextmanager
async def lifespan(app):
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    # No jobs survive a restart; only remove directories created by this service.
    for directory in settings.temp_dir.iterdir():
        if directory.is_dir() and len(directory.name) == 32 and all(c in '0123456789abcdef' for c in directory.name):
            shutil.rmtree(directory, ignore_errors=True)
    async def sweep():
        while True:
            await asyncio.sleep(30)
            manager.cleanup()
    cleaner = asyncio.create_task(sweep())
    yield
    cleaner.cancel()
    workers = [j.worker for j in manager.jobs.values() if j.worker]
    for worker in workers:
        worker.cancel()
    await asyncio.gather(cleaner, *workers, return_exceptions=True)


app = FastAPI(title='ClipCut API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])


@app.get('/api/health')
async def health():
    return {'ok': bool(shutil.which(settings.ffmpeg_path) and shutil.which(settings.ffprobe_path)),
            'max_duration': settings.max_duration, 'retention_seconds': settings.retention_seconds}


@app.post('/api/videos')
async def video(request: VideoRequest):
    try:
        return await metadata(request.url)
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(422, str(exc) or 'Tempo limite ao consultar o vídeo.')


@app.post('/api/tasks', status_code=202)
async def create(request: TaskRequest):
    if not shutil.which(settings.ffmpeg_path) or not shutil.which(settings.ffprobe_path):
        raise HTTPException(503, 'Instale FFmpeg e FFprobe antes de iniciar um download.')
    try:
        return manager.create(request).public()
    except RuntimeError as exc:
        raise HTTPException(429, str(exc))


def get_job(task_id):
    job = manager.jobs.get(task_id)
    if not job:
        raise HTTPException(404, 'Tarefa expirada ou não encontrada.')
    return job


@app.get('/api/tasks/{task_id}')
async def status(task_id: str):
    return get_job(task_id).public()


@app.delete('/api/tasks/{task_id}')
async def cancel(task_id: str):
    job = get_job(task_id)
    manager.cancel(job)
    return job.public()


@app.get('/api/tasks/{task_id}/file')
async def download(task_id: str):
    job = get_job(task_id)
    if job.status != 'completed' or not job.file or not job.file.exists():
        raise HTTPException(409, 'Arquivo ainda não disponível.')
    async def chunks():
        job.readers += 1
        try:
            with job.file.open('rb') as file:
                while chunk := await asyncio.to_thread(file.read, 256 * 1024):
                    yield chunk
        finally:
            job.readers -= 1
    return StreamingResponse(chunks(), media_type='application/octet-stream', headers={
        'Content-Disposition': f"attachment; filename*=UTF-8''{quote(job.file.name)}",
        'Content-Length': str(job.file.stat().st_size)})
