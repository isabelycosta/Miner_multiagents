# Minerador de repositórios GitHub

Ferramenta em Python para localizar repositórios públicos por consulta, coletar metadados, README e árvore de arquivos, identificar indícios de testes e exportar os dados para CSV, Excel e SQLite.

## Arquitetura

1. **Busca** — GitHub Search API (`/search/repositories`) para cada consulta.
2. **Coleta** — metadados, linguagens, README e árvore de arquivos.
3. **Filtros** — linguagem, atividade (`pushed_at`), estrelas e indícios de arquivos de teste; forks e arquivados são excluídos por padrão.
4. **Código-fonte opcional** — clone superficial (`git clone --depth 1`) dos repositórios que passaram pelos filtros.
5. **Persistência** — SQLite com tabelas `repositories` e `search_runs`.
5. **Exportação** — `output/repositorios.csv`, `output/repositorios.xlsx` e `output/readmes.csv`.

## Requisitos

Python 3.10 ou superior recomendado.

```bash
python -m venv .venv
```

Windows:
```bat
.venv\Scripts\activate
```

macOS/Linux:
```bash
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

## Autenticação

Configure `GITHUB_TOKEN` como variável de ambiente. Um token reduzido, sem permissões adicionais para repositórios públicos, costuma ser suficiente para consultas públicas. Não compartilhe nem versione o token.

Windows CMD:
```bat
set GITHUB_TOKEN=SEU_TOKEN
```

Windows PowerShell:
```powershell
$env:GITHUB_TOKEN="SEU_TOKEN"
```

macOS/Linux:
```bash
export GITHUB_TOKEN="SEU_TOKEN"
```

## Exemplos

Buscar repositórios relacionados a agentes inteligentes:
```bash
python miner.py --query '"intelligent agents" in:name,description,readme' --max-per-query 100
```

Várias consultas, mantendo os resultados deduplicados:
```bash
python miner.py ^
  --query '"intelligent agents" in:name,description,readme' ^
  --query '"agent-based testing" in:name,description,readme' ^
  --max-per-query 100
```

Somente projetos Python atualizados desde 2024:
```bash
python miner.py --query 'testing agents in:name,description,readme' --language Python --active-since 2024-01-01
```

Exigir indícios de arquivos de teste:
```bash
python miner.py --query 'software testing in:name,description,readme' --require-tests
```

Baixar também o código-fonte dos repositórios aprovados (requer Git instalado):
```bash
python miner.py --query 'software testing in:name,description,readme' --require-tests --download-source --source-dir sources
```

A consulta aceita a sintaxe da GitHub Search API. `--max-per-query` limita os candidatos coletados por consulta (1 a 1000); o endpoint de busca limita os resultados disponíveis por consulta a 1000.

## Interpretação dos filtros

- `--language Python`: filtra pelas linguagens detectadas pelo GitHub; com múltiplas linguagens, mantém repositórios que usam pelo menos uma delas.
- `--active-since 2024-01-01`: exige `pushed_at` igual ou posterior à data.
- `--require-tests`: heurística baseada em nomes/caminhos como `tests/`, `test_*.py`, `*.test.js`. Não prova que os testes executam ou passam.
- `--min-stars 5`: estrelas mínimas.
- `--include-forks` e `--include-archived`: incluem forks e/ou projetos arquivados.

## Limitações importantes para pesquisa acadêmica

- Por padrão, o minerador coleta metadados, README e árvore de arquivos. Use `--download-source` para clonar o código dos repositórios aprovados; isso requer Git instalado e espaço em disco. Os clones são superficiais (`--depth 1`), sem o histórico completo.
- README é limitado a 500.000 caracteres por repositório.
- Árvores de arquivos muito grandes podem ser truncadas pela API. O campo `tree_truncated` sinaliza isso.
- A presença de arquivos com nomes típicos de teste é apenas um indicador aproximado.
- A busca do GitHub não é uma base bibliográfica completa nem garante recall de todos os projetos pertinentes.
- O GitHub aplica limites de requisição. A execução faz pausas e tenta novamente após erros de limite, mas grandes coletas devem ser divididas em lotes.
- A saída do banco acumula repositórios entre execuções. Os CSVs/Excel são exportados a partir do banco inteiro, não apenas da última consulta.

## Boas práticas de reprodutibilidade

Para cada execução, registre:
- data e hora da coleta;
- consultas exatas;
- critérios de inclusão/exclusão;
- versão do script;
- eventuais falhas e limites de API;
- protocolo de triagem manual.

As consultas e filtros ficam registrados na tabela `search_runs`. A tabela `repositories` guarda os dados e a data da coleta.



## Executar por arquivo de configuração (sem preencher comandos)

Edite `config.json` com as consultas e filtros desejados. Depois, dê duplo clique em `Executar_coleta.bat` no Windows. O script lê a configuração e inicia a coleta.

Exemplo de consulta:
```json
{
  "queries": [
    "\"intelligent agents\" in:name,description,readme",
    "\"agent-based testing\" in:name,description,readme"
  ],
  "filters": {
    "max_per_query": 100,
    "min_stars": 0,
    "active_since": "2024-01-01",
    "languages": ["Python"],
    "require_tests": true,
    "include_forks": false,
    "include_archived": false
  },
  "collection": {
    "download_source": false,
    "source_dir": "sources",
    "pause_seconds": 1.0
  },
  "output": {
    "database": "data/miner.db",
    "directory": "output",
    "csv": true,
    "excel": true,
    "readme_csv": true
  }
}
```

Cada item de `queries` é uma consulta da GitHub Search API, não apenas uma palavra isolada. Você pode usar qualificadores como `language:Python`, `stars:>=10`, `pushed:>=2024-01-01` ou `in:name,description,readme`.

O token é lido da variável de ambiente `GITHUB_TOKEN`; ele não deve ser salvo no arquivo de configuração.
