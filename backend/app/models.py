import re
from urllib.parse import urlsplit, parse_qs
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


def canonical_url(value: str) -> str:
    u = urlsplit(value.strip())
    if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443):
        raise ValueError('Use um link HTTPS válido do YouTube.')
    host = u.hostname
    parts = u.path.strip('/').split('/')
    if host == 'youtu.be' and len(parts) == 1:
        video = parts[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        if u.path == '/watch':
            video = parse_qs(u.query).get('v', [''])[0]
        elif len(parts) == 2 and parts[0] in ('shorts', 'embed', 'live'):
            video = parts[1]
        else:
            raise ValueError('Link de vídeo não reconhecido.')
    else:
        raise ValueError('Somente links do YouTube são aceitos.')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{11}', video):
        raise ValueError('Identificador do vídeo inválido.')
    return f'https://www.youtube.com/watch?v={video}'


def parse_timestamp(value: str) -> float:
    if not re.fullmatch(r'\d{2,}:\d{2}:\d{2}(?:\.\d{1,3})?', value):
        raise ValueError('Use HH:MM:SS ou HH:MM:SS.mmm.')
    h, m, s = value.split(':')
    if int(m) >= 60 or float(s) >= 60:
        raise ValueError('Timestamp inválido.')
    return int(h) * 3600 + int(m) * 60 + float(s)


class VideoRequest(BaseModel):
    url: str = Field(max_length=2048)
    _url = field_validator('url')(canonical_url)


class TaskRequest(VideoRequest):
    authorized: Literal[True]
    mode: Literal['full', 'clip'] = 'clip'
    start: float = Field(0, ge=0, allow_inf_nan=False)
    end: float | None = Field(None, gt=0, allow_inf_nan=False)
    format: Literal['mp4', 'webm', 'mp3', 'm4a'] = 'mp4'
    quality: Literal['best', '2160', '1440', '1080', '720', '480', '360'] = 'best'

    @model_validator(mode='after')
    def interval(self):
        if self.mode == 'clip' and (self.end is None or self.end <= self.start):
            raise ValueError('O fim deve ser maior que o início.')
        return self
