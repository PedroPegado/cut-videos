"""Real FFmpeg conversion, with a generated source instead of remote media."""
import asyncio
import json
import shutil
import pytest
from app.config import settings
from app.models import TaskRequest
from app.service import Manager
import app.service as service


@pytest.mark.parametrize('output_format', ['mp4', 'webm', 'mp3', 'm4a'])
def test_real_conversion(output_format, monkeypatch, tmp_path):
    if not shutil.which(settings.ffmpeg_path) or not shutil.which(settings.ffprobe_path):
        pytest.skip('FFmpeg/FFprobe unavailable')
    async def scenario():
        monkeypatch.setattr(settings, 'temp_dir', tmp_path)
        original = service.command
        async def metadata(url):
            return {'title': 'Synthetic test', 'duration': 2, 'qualities': ['360']}
        async def download(args, folder=None, callback=None, limit=16_000_000):
            if '--progress-template' in args:
                return await original([settings.ffmpeg_path, '-nostdin', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=24', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-t', '2', '-c:v', 'libx264', '-c:a', 'aac', str(folder/'source.mkv')], folder)
            return await original(args, folder, callback, limit)
        monkeypatch.setattr(service, 'metadata', metadata)
        monkeypatch.setattr(service, 'command', download)
        job=Manager().create(TaskRequest(url='https://youtu.be/abcdefghijk', authorized=True, mode='full', format=output_format))
        await job.worker
        assert job.status == 'completed', job.error
        info=json.loads(await original([settings.ffprobe_path,'-v','error','-show_streams','-show_format','-of','json',str(job.file)]))
        assert abs(float(info['format']['duration'])-2) < .15
        assert any(s['codec_type']=='audio' for s in info['streams'])
        if output_format in ('mp4','webm'):
            stream=next(s for s in info['streams'] if s['codec_type']=='video')
            assert stream['width']==320 and stream['height']==180
            assert stream['r_frame_rate']=='24/1'
    asyncio.run(scenario())
