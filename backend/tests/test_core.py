import asyncio
import time
import pytest
from pydantic import ValidationError
from app.models import canonical_url, parse_timestamp, TaskRequest
from app.service import Manager, Job, command
from app.config import settings

URL = 'https://www.youtube.com/watch?v=abcdefghijk'

@pytest.mark.parametrize('url', [URL, 'https://youtu.be/abcdefghijk?t=5', 'https://youtube.com/shorts/abcdefghijk'])
def test_url(url):
    assert canonical_url(url) == URL

@pytest.mark.parametrize('url', ['http://youtube.com/watch?v=abcdefghijk','https://youtube.com.evil.org/watch?v=abcdefghijk','https://127.0.0.1/video','https://youtube.com@evil.com/watch?v=abcdefghijk','https://youtube.com:88/watch?v=abcdefghijk','https://youtube.com/playlist?list=test','file:///etc/passwd'])
def test_reject_url(url):
    with pytest.raises(ValueError): canonical_url(url)

def test_timestamp():
    assert parse_timestamp('01:02:03.125') == 3723.125
    for value in ('00:60:00','00:00:60','-1:00:00','abc'):
        with pytest.raises(ValueError): parse_timestamp(value)

@pytest.mark.parametrize('start,end', [(5,5),(6,4),(-1,5),(0,None),(float('nan'),5)])
def test_interval(start,end):
    with pytest.raises(ValidationError): TaskRequest(url=URL,authorized=True,start=start,end=end)

def test_authorization():
    with pytest.raises(ValidationError): TaskRequest(url=URL,authorized=False,end=10)

def test_cancel_and_limit(monkeypatch,tmp_path):
    async def scenario():
        manager=Manager()
        async def pending(job): await asyncio.sleep(100)
        monkeypatch.setattr(manager,'run',pending)
        monkeypatch.setattr(settings,'max_tasks',1)
        monkeypatch.setattr(settings,'temp_dir',tmp_path)
        job=manager.create(TaskRequest(url=URL,authorized=True,end=10))
        with pytest.raises(RuntimeError): manager.create(job.request)
        manager.cancel(job)
        await asyncio.gather(job.worker,return_exceptions=True)
        assert job.status=='cancelled'
        job.finished=time.time()-settings.retention_seconds-1
        manager.cleanup()
        assert not manager.jobs
    asyncio.run(scenario())

def test_completion_and_validation(monkeypatch,tmp_path):
    import app.service as service
    async def scenario():
        monkeypatch.setattr(settings,'temp_dir',tmp_path)
        async def meta(url): return {'title':'Test / video','duration':30,'qualities':['720']}
        async def fake(args,folder=None,callback=None,limit=None):
            if '--progress-template' in args:
                (folder/'source.mkv').write_bytes(b'source')
            elif '-progress' in args:
                from pathlib import Path
                Path(args[-1]).write_bytes(b'output')
            else: return '{"format":{"duration":"10"},"streams":[{"codec_type":"audio"}]}'
            return ''
        monkeypatch.setattr(service,'metadata',meta)
        monkeypatch.setattr(service,'command',fake)
        manager=Manager()
        job=manager.create(TaskRequest(url=URL,authorized=True,end=10))
        await job.worker
        assert job.status=='completed' and job.file.exists()
        assert not list(job.file.parent.glob('source.*'))
        bad=manager.create(TaskRequest(url=URL,authorized=True,end=40))
        await bad.worker
        assert bad.status=='failed'
        assert not (tmp_path/bad.id).exists()
    asyncio.run(scenario())

def test_process_timeout(monkeypatch):
    import sys
    monkeypatch.setattr(settings,'task_timeout',1)
    with pytest.raises(TimeoutError):
        asyncio.run(command([sys.executable,'-c','import time; time.sleep(30)']))
