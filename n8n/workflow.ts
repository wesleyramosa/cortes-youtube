import { workflow, node, trigger, sticky, newCredential, expr } from '@n8n/workflow-sdk';

const agendamento = trigger({
  type: 'n8n-nodes-base.scheduleTrigger',
  version: 1.2,
  config: {
    name: 'Todo dia 09h',
    parameters: { rule: { interval: [{ field: 'cronExpression', expression: '0 9 * * *' }] } }
  },
  output: [{}]
});

const config = node({
  type: 'n8n-nodes-base.set',
  version: 3.4,
  config: {
    name: 'Configuração',
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'c1', name: 'temas', value: expr('{{ ["finanças pessoais", "empreendedorismo", "marketing digital"] }}'), type: 'array' },
          { id: 'c2', name: 'github_repo', value: 'wesleyramosa/cortes-youtube', type: 'string' },
          { id: 'c3', name: 'num_cortes', value: '1', type: 'string' },
          { id: 'c4', name: 'publicar', value: 'sim', type: 'string' },
          { id: 'c5', name: 'privacidade', value: 'private', type: 'string' },
          { id: 'c6', name: 'callback_url', value: 'https://wdoisaagencia.app.n8n.cloud/webhook/cortes-retorno', type: 'string' },
          { id: 'c7', name: 'dias_busca', value: 90, type: 'number' }
        ]
      }
    }
  },
  output: [{ temas: ['finanças pessoais'], github_repo: 'wesleyramosa/cortes-youtube', num_cortes: '1', publicar: 'sim', privacidade: 'private', callback_url: 'https://x/webhook/cortes-retorno', dias_busca: 90 }]
});

const separarTemas = node({
  type: 'n8n-nodes-base.splitOut',
  version: 1,
  config: {
    name: 'Um item por tema',
    parameters: { fieldToSplitOut: 'temas', include: 'allOtherFields', options: { destinationFieldName: 'tema' } }
  },
  output: [{ tema: 'finanças pessoais', github_repo: 'wesleyramosa/cortes-youtube', num_cortes: '1', publicar: 'sim', privacidade: 'private', callback_url: 'https://x/webhook/cortes-retorno', dias_busca: 90 }]
});

const buscarYoutube = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.2,
  config: {
    name: 'Buscar vídeos no YouTube',
    parameters: {
      method: 'GET',
      url: 'https://www.googleapis.com/youtube/v3/search',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpQueryAuth',
      sendQuery: true,
      queryParameters: {
        parameters: [
          { name: 'part', value: 'snippet' },
          { name: 'type', value: 'video' },
          { name: 'q', value: expr('{{ $json.tema }}') },
          { name: 'videoLicense', value: 'creativeCommon' },
          { name: 'videoDuration', value: 'medium' },
          { name: 'order', value: 'viewCount' },
          { name: 'relevanceLanguage', value: 'pt' },
          { name: 'regionCode', value: 'BR' },
          { name: 'maxResults', value: '10' },
          { name: 'publishedAfter', value: expr('{{ $now.minus($json.dias_busca, "days").toUTC().toISO({ suppressMilliseconds: true }) }}') }
        ]
      },
      options: {}
    },
    credentials: { httpQueryAuth: newCredential('YouTube API Key') }
  },
  output: [{ items: [{ id: { videoId: 'abc123def45' }, snippet: { title: 'Vídeo', channelTitle: 'Canal' } }] }]
});

const separarVideos = node({
  type: 'n8n-nodes-base.splitOut',
  version: 1,
  config: { name: 'Um item por vídeo', parameters: { fieldToSplitOut: 'items', include: 'noOtherFields' } },
  output: [{ id: { videoId: 'abc123def45' }, snippet: { title: 'Vídeo', channelTitle: 'Canal' } }]
});

const normalizar = node({
  type: 'n8n-nodes-base.set',
  version: 3.4,
  config: {
    name: 'Dados do vídeo',
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'n1', name: 'video_id', value: expr('{{ $json.id.videoId }}'), type: 'string' },
          { id: 'n2', name: 'titulo', value: expr('{{ $json.snippet.title }}'), type: 'string' },
          { id: 'n3', name: 'canal', value: expr('{{ $json.snippet.channelTitle }}'), type: 'string' },
          { id: 'n4', name: 'tema', value: expr('{{ $("Um item por tema").item.json.tema }}'), type: 'string' }
        ]
      }
    }
  },
  output: [{ video_id: 'abc123def45', titulo: 'Vídeo', canal: 'Canal', tema: 'finanças pessoais' }]
});

const naoProcessados = node({
  type: 'n8n-nodes-base.dataTable',
  version: 1.1,
  config: {
    name: 'Ainda não cortado',
    parameters: {
      resource: 'row',
      operation: 'rowNotExists',
      dataTableId: { __rl: true, mode: 'id', value: '6n0wefww6ZTxkNqR', cachedResultName: 'cortes_youtube' },
      matchType: 'anyCondition',
      filters: { conditions: [{ keyName: 'video_id', condition: 'eq', keyValue: expr('{{ $json.video_id }}') }] }
    }
  },
  output: [{ video_id: 'abc123def45', titulo: 'Vídeo', canal: 'Canal', tema: 'finanças pessoais' }]
});

const umPorTema = node({
  type: 'n8n-nodes-base.removeDuplicates',
  version: 2,
  config: {
    name: 'Mais visto por tema',
    parameters: { operation: 'removeDuplicateInputItems', compare: 'selectedFields', fieldsToCompare: 'tema', options: {} }
  },
  output: [{ video_id: 'abc123def45', titulo: 'Vídeo', canal: 'Canal', tema: 'finanças pessoais' }]
});

const registrar = node({
  type: 'n8n-nodes-base.dataTable',
  version: 1.1,
  config: {
    name: 'Registrar disparo',
    parameters: {
      resource: 'row',
      operation: 'insert',
      dataTableId: { __rl: true, mode: 'id', value: '6n0wefww6ZTxkNqR', cachedResultName: 'cortes_youtube' },
      columns: {
        mappingMode: 'defineBelow',
        value: {
          video_id: expr('{{ $json.video_id }}'),
          tema: expr('{{ $json.tema }}'),
          titulo: expr('{{ $json.titulo }}'),
          canal: expr('{{ $json.canal }}'),
          status: 'disparado',
          atualizado_em: expr('{{ $now.toISO() }}')
        },
        schema: [
          { id: 'video_id', displayName: 'video_id', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'tema', displayName: 'tema', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'titulo', displayName: 'titulo', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'canal', displayName: 'canal', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'status', displayName: 'status', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'atualizado_em', displayName: 'atualizado_em', required: false, defaultMatch: false, display: true, type: 'dateTime', canBeUsedToMatch: true }
        ]
      },
      options: {}
    }
  },
  output: [{ id: 1, createdAt: '2026-10-01T09:00:00Z', updatedAt: '2026-10-01T09:00:00Z' }]
});

const dispararGithub = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.2,
  config: {
    name: 'Disparar corte no GitHub',
    parameters: {
      method: 'POST',
      url: expr('https://api.github.com/repos/{{ $("Configuração").first().json.github_repo }}/dispatches'),
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      sendHeaders: true,
      headerParameters: {
        parameters: [
          { name: 'Accept', value: 'application/vnd.github+json' },
          { name: 'X-GitHub-Api-Version', value: '2022-11-28' }
        ]
      },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify({ event_type: "corte", client_payload: { video_id: $("Mais visto por tema").item.json.video_id, tema: $("Mais visto por tema").item.json.tema, num_cortes: $("Configuração").first().json.num_cortes, publicar: $("Configuração").first().json.publicar, privacidade: $("Configuração").first().json.privacidade, callback_url: $("Configuração").first().json.callback_url } }) }}'),
      options: {}
    },
    credentials: { httpHeaderAuth: newCredential('GitHub Token (cortes)') }
  },
  output: [{}]
});

const retorno = trigger({
  type: 'n8n-nodes-base.webhook',
  version: 2.1,
  config: {
    name: 'Retorno do GitHub',
    parameters: { httpMethod: 'POST', path: 'cortes-retorno', authentication: 'headerAuth', responseMode: 'onReceived', options: {} },
    credentials: { httpHeaderAuth: newCredential('Token retorno cortes') }
  },
  output: [{ body: { status: 'ok', video_id: 'abc123def45', run_url: 'https://github.com/x/y/actions/runs/1', cortes: [{ youtube_url: 'https://youtube.com/shorts/xyz', titulo_final: 'Título #shorts' }] } }]
});

const atualizar = node({
  type: 'n8n-nodes-base.dataTable',
  version: 1.1,
  config: {
    name: 'Atualizar status',
    parameters: {
      resource: 'row',
      operation: 'update',
      dataTableId: { __rl: true, mode: 'id', value: '6n0wefww6ZTxkNqR', cachedResultName: 'cortes_youtube' },
      matchType: 'anyCondition',
      filters: { conditions: [{ keyName: 'video_id', condition: 'eq', keyValue: expr('{{ $json.body.video_id }}') }] },
      columns: {
        mappingMode: 'defineBelow',
        value: {
          status: expr('{{ $json.body.status === "ok" ? (($json.body.cortes || []).some(c => c.youtube_url) ? "publicado" : "cortado") : "erro" }}'),
          youtube_urls: expr('{{ ($json.body.cortes || []).map(c => c.youtube_url || c.arquivo).join("\\n") }}'),
          run_url: expr('{{ $json.body.run_url }}'),
          atualizado_em: expr('{{ $now.toISO() }}')
        },
        schema: [
          { id: 'status', displayName: 'status', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'youtube_urls', displayName: 'youtube_urls', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'run_url', displayName: 'run_url', required: false, defaultMatch: false, display: true, type: 'string', canBeUsedToMatch: true },
          { id: 'atualizado_em', displayName: 'atualizado_em', required: false, defaultMatch: false, display: true, type: 'dateTime', canBeUsedToMatch: true }
        ]
      },
      options: {}
    }
  },
  output: [{ id: 1 }]
});

const notaSetup = sticky(
  '## Configurar antes de ativar\n' +
  '1. **YouTube API Key** (Query Auth): name `key`, value = chave da YouTube Data API v3.\n' +
  '2. **GitHub Token (cortes)** (Header Auth): name `Authorization`, value `Bearer <fine-grained token>` com Contents: read/write só no repo.\n' +
  '3. **Token retorno cortes** (Header Auth): name `x-token`, value = mesmo valor do secret `CALLBACK_TOKEN` no GitHub.\n' +
  '4. Edite temas/repo/publicar em **Configuração**.\n\n' +
  'Busca só vídeos **Creative Commons** (evita strike). Uploads saem **privados** até a auditoria da API do YouTube.',
  [agendamento, config],
  { color: 4 }
);

export default workflow('cortes-youtube', '[18] Cortes YouTube — GitHub Actions')
  .add(agendamento)
  .to(config)
  .to(separarTemas)
  .to(buscarYoutube)
  .to(separarVideos)
  .to(normalizar)
  .to(naoProcessados)
  .to(umPorTema)
  .to(registrar)
  .to(dispararGithub)
  .add(retorno)
  .to(atualizar)
  .add(notaSetup)
  .group('Busca no YouTube', [separarTemas, buscarYoutube, separarVideos, normalizar], { description: 'Busca vídeos Creative Commons por tema, mais vistos nos últimos N dias' })
  .group('Disparo', [naoProcessados, umPorTema, registrar, dispararGithub], { description: 'Ignora vídeos já cortados, pega 1 por tema, registra e dispara o GitHub Actions' });
