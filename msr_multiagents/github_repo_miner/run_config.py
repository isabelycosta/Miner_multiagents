from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def main():
    config = load_config()
    queries = config.get("queries", [])
    if not queries or not any(str(q).strip() for q in queries):
        raise ValueError("Preencha pelo menos uma consulta no campo 'queries' do config.json.")

    filters = config.get("filters", {})
    collection = config.get("collection", {})
    output = config.get("output", {})

    command = [
        sys.executable, str(ROOT / "miner.py"),
        "--max-per-query", str(filters.get("max_per_query", 100)),
        "--min-stars", str(filters.get("min_stars", 0)),
        "--db", str(ROOT / output.get("database", "data/miner.db")),
        "--out", str(ROOT / output.get("directory", "output")),
        "--pause", str(collection.get("pause_seconds", 1.0)),
    ]

    active_since = filters.get("active_since")
    if active_since:
        command += ["--active-since", str(active_since)]

    for language in filters.get("languages", []):
        if str(language).strip():
            command += ["--language", str(language).strip()]

    for query in queries:
        if str(query).strip():
            command += ["--query", str(query).strip()]

    if filters.get("require_tests", False):
        command.append("--require-tests")
    if filters.get("include_forks", False):
        command.append("--include-forks")
    if filters.get("include_archived", False):
        command.append("--include-archived")
    if collection.get("download_source", False):
        command += ["--download-source", "--source-dir",
                    str(ROOT / collection.get("source_dir", "sources"))]

    env = os.environ.copy()
    token = env.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("AVISO: GITHUB_TOKEN não configurado. A API poderá ter limites menores.\n")

    print("Configuração carregada:", CONFIG_PATH.name)
    print("Consultas:", len([q for q in queries if str(q).strip()]))
    print("Iniciando coleta...\n")
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode != 0:
        print("\nA coleta terminou com erro. Confira as mensagens acima.")
        return result.returncode
    print("\nColeta finalizada.")
    print("Resultados:", ROOT / output.get("directory", "output"))
    print("Banco:", ROOT / output.get("database", "data/miner.db"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Erro na configuração: {exc}")
        raise SystemExit(1)
