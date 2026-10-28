# ClipCut

Editor local de downloads e recortes de vídeos próprios ou autorizados. Interface em português com Next.js App Router, TypeScript, Tailwind e Lucide; API independente em FastAPI, yt-dlp e FFmpeg/FFprobe.

## Executar no Windows 11

Requisitos: Python 3.11+, Node.js 22+, FFmpeg e FFprobe no PATH. Reserve espaço para o vídeo intermediário e a saída; o limite padrão de 2 GB vale para o total temporário de cada tarefa.

Instale o FFmpeg no PowerShell:

```powershell
winget install --id Gyan.FFmpeg --exact
```

Abra um novo terminal para atualizar o PATH e confira `ffmpeg -version` e `ffprobe -version`. Também é possível configurar caminhos absolutos para os executáveis em `backend/.env`, usando barras `/`.

Terminal 1, na raiz do projeto:

```powershell
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
npm run dev
```

Abra http://localhost:3000. Use `localhost`, pois essa é a origem permitida por padrão no CORS. Documentação interativa da API: http://localhost:8000/docs.

No Linux/macOS, use `.venv/bin/python` e instale FFmpeg pelo gerenciador de pacotes do sistema. Node deve estar acessível ao backend: yt-dlp usa o runtime JavaScript para interpretar respostas públicas do YouTube.

## Uso

1. Cole um link HTTPS de vídeo do YouTube e carregue os metadados.
2. Escolha vídeo completo ou recorte. Ajuste as alças ou os campos `HH:MM:SS.mmm`.
3. Os botões de marcação usam o tempo do player; “Reproduzir seleção” começa no início e pausa no fim. A precisão da prévia depende do player e do navegador.
4. Escolha formato e qualidade, confirme que possui autorização e prepare o download.
5. Acompanhe a tarefa, cancele se necessário e clique em “Salvar arquivo” quando pronta.

O player oficial mantém seus controles e anúncios. Conteúdo que não permite incorporação ainda pode receber tempos manuais, desde que esteja disponível publicamente para processamento autorizado. Não há cookies, login, DRM ou contorno de restrições.

## API

| Método / rota | Uso |
| --- | --- |
| `GET /api/health` | Disponibilidade dos executáveis e limites |
| `POST /api/videos` | `{ "url": "https://www.youtube.com/watch?v=…" }`; retorna título, canal, duração, thumbnail e qualidades |
| `POST /api/tasks` | Cria tarefa e retorna `202`, ID e estado |
| `GET /api/tasks/{id}` | Estado, progresso, erro e nome final |
| `DELETE /api/tasks/{id}` | Cancela tarefa em fila ou execução e seus subprocessos |
| `GET /api/tasks/{id}/file` | Download em blocos de 256 KB |

Corpo de criação de tarefa:

```json
{"url":"https://www.youtube.com/watch?v=abcdefghijk","authorized":true,"mode":"clip","start":12.5,"end":32.75,"format":"mp4","quality":"720"}
```

Para vídeo completo, use `mode: "full"`, `start: 0`, `end: null`. Formatos: `mp4`, `webm`, `mp3`, `m4a`. Qualidades: `best`, `2160`, `1440`, `1080`, `720`, `480`, `360`. O servidor revalida a duração e a qualidade usando metadados atuais, mesmo que a interface tenha sido alterada.

Estados: `queued`, `obtaining`, `downloading`, `cutting`, `converting`, `completed`, `failed`, `cancelled`. A obtenção parcial e o corte podem acontecer no mesmo processo; a UI os identifica juntos durante o download. Progresso de download é estimado e pode ficar parado durante operações do FFmpeg; não é um relógio simulado.

## Processamento

O yt-dlp recebe `--download-sections` nos recortes, solicitando apenas o intervalo quando a origem/protocolo permite. `--force-keyframes-at-cuts` recodifica para cortes fora de keyframes. Não é possível garantir economia de banda em todos os protocolos do YouTube. A saída passa por conversão explícita: H.264/AAC para MP4, VP9/Opus para WebM, MP3 ou AAC para áudio. Não há aumento de resolução nem mudança explícita de FPS. MP4 inclui `faststart`; áudio e vídeo são mapeados do mesmo intermediário preservando os timestamps. FFprobe valida duração positiva e presença de áudio antes de liberar o arquivo.

O corte pode fazer duas recodificações (precisão do recorte e compatibilidade final). Essa escolha simplifica a primeira versão, mas custa CPU. Resoluções inferiores podem ser produzidas escolhendo a melhor fonte disponível abaixo do teto; nunca se promete que a fonte tenha exatamente aquela altura.

## Configuração e limites

Veja `backend/.env.example` e `frontend/.env.example`. Padrões: 2 tarefas simultâneas, 30 tarefas retidas, vídeos até 2 horas, 2 GB temporários por tarefa, timeout de 30 minutos e retenção de 1 hora após o fim. Consultas de metadados têm concorrência 2 e timeout de 60 segundos. A limpeza roda a cada 30 segundos; arquivos em streaming ficam protegidos durante a leitura. Falhas e cancelamentos removem intermediários imediatamente. Reiniciar a API elimina as pastas de tarefas antigas e seus IDs.

Use **um único worker Uvicorn**: a fila e os estados ficam em memória. Não é uma fila distribuída nem persistente. Não recarregue a página durante uma tarefa se quiser manter seus controles na interface; o ID continua consultável pela API até expirar.

## Segurança

Somente URLs HTTPS com host e formato de vídeo explicitamente permitidos são aceitas; a entrada é reconstruída em uma URL canônica e parâmetros extras são descartados. Subprocessos usam listas de argumentos, nunca shell. Configurações externas do yt-dlp e proxies são desativados. O subprocesso Python recusa conexões para endereços privados, loopback e link-local, inclusive em redirects. FFmpeg trabalha com URLs extraídas do YouTube pelo yt-dlp e arquivos gerados pelo serviço, nunca com uma URL arbitrária fornecida pelo cliente.

A proteção Python não intercepta sockets abertos pelo executável FFmpeg. Para um serviço público, **é necessário bloquear redes privadas/link-local no egress do container/host**, inclusive IPv6 e endpoints de metadados da nuvem. CORS não é autenticação. Esta versão foi desenhada para localhost; antes de expor publicamente, adicione autenticação, rate limiting, TLS, quotas por usuário e isolamento de rede. IDs aleatórios não substituem autorização multiusuário. Não exponha a porta local diretamente à internet.

## Testes e build

```powershell
cd backend
.venv/Scripts/python -m pytest -q
cd ../frontend
npm run build
```

Os testes cobrem URLs permitidas/proibidas, timestamps, intervalos, consentimento, limites de tarefas, cancelamento, limpeza, timeout de subprocessos, conclusão e rejeição de trechos fora da duração. O processamento remoto é simulado nos testes de gerenciamento para não depender da disponibilidade do YouTube.

## Docker e deploy futuro

```powershell
docker compose up --build
```

O Compose publica apenas em loopback e limita CPU/memória do backend. Imagens incluem as dependências de execução e rodam como usuário sem privilégios. Para outro host, ajuste `NEXT_PUBLIC_API_URL` **no build** do frontend e `CORS_ORIGINS` do backend. Acrescente proxy HTTPS e as proteções descritas acima. Para múltiplas réplicas, substitua o gerenciador em memória por fila persistente, estado compartilhado e armazenamento com expiração; mantenha a API de tarefas.

## Referências

- [YouTube IFrame Player API](https://developers.google.com/youtube/iframe_api_reference)
- [Opções oficiais do yt-dlp](https://github.com/yt-dlp/yt-dlp#usage-and-options)
- [Next.js App Router](https://nextjs.org/docs/app)

Falhas de rede, mudanças do YouTube, exigência de login ou bloqueios da origem podem impedir o processamento. Atualize yt-dlp quando necessário. O sistema retorna erro e não tenta contornar esses bloqueios.

## Verificação desta entrega

- 24 testes automatizados passaram, incluindo conversões reais nos quatro formatos com fonte sintética.
- Build de produção do Next.js concluído.
- Recorte remoto real de 10,250 a 12,750 segundos concluído via API; download por streaming retornou HTTP 200.
- FFprobe confirmou MP4 H.264/AAC, 640×360, 30 FPS e duração de 2,500 segundos. O início do vídeo ficou a um frame do áudio (33 ms), dentro da granularidade da fonte selecionada.
- Material usado apenas no teste: Big Buck Bunny, © 2008 Blender Foundation / www.bigbuckbunny.org, CC BY 3.0. Referência: https://wiki.creativecommons.org/wiki/Big_Buck_Bunny. O recorte temporário segue a mesma expiração dos demais downloads.
- Docker fornecido, mas não executado nesta validação.
