from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API = "https://api.github.com"
USER_AGENT = "AcademicGitHubRepositoryMiner/1.0"
DEFAULT_DB = "data/miner.db"
DEFAULT_OUT = "output"
TEST_FILE_RE = re.compile(
    r"(^|/)(tests?|specs?)(/|$)|(^|/)(test_|spec_)[^/]+\.(py|js|jsx|ts|tsx|java|rb|go)$|"
    r"\.(test|spec)\.(js|jsx|ts|tsx)$|(^|/)[^/]*(test|spec)[^/]*\.(java|cs|go|rb)$",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubMiner:
    def __init__(self, token: str | None = None, timeout: int = 30, pause: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        })
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.timeout = timeout
        self.pause = pause


    def get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any] | None:
        for attempt in range(5):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout
                )

                # Repositório sem árvore disponível ou conflito na consulta
                if response.status_code == 409:
                    print(
                        f"[aviso] HTTP 409; ignorando recurso: {url}",
                        file=sys.stderr
                    )
                    return None

                # Recurso inexistente
                if response.status_code == 404:
                    return None

                # Limite da API ou acesso bloqueado
                if response.status_code in (403, 429):
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    reset = response.headers.get("X-RateLimit-Reset")
                    retry_after = response.headers.get("Retry-After")

                    if retry_after:
                        wait = max(1, int(retry_after))
                    elif remaining == "0" and reset:
                        wait = max(1, int(reset) - int(time.time()) + 2)
                    else:
                        # Se não for possível identificar o limite,
                        # não insistir indefinidamente.
                        print(
                            f"[erro] HTTP {response.status_code}; "
                            "verifique autenticação e limite da API.",
                            file=sys.stderr
                        )
                        return None

                    if attempt == 4:
                        print(
                            f"[erro] Limite da API persiste após "
                            f"{attempt + 1} tentativas: {url}",
                            file=sys.stderr
                        )
                        return None

                    print(
                        f"[limite/API] HTTP {response.status_code}; "
                        f"aguardando {wait}s",
                        file=sys.stderr
                    )
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response.json()

            except (requests.RequestException, ValueError) as exc:
                if attempt == 4:
                    print(f"[erro] {url}: {exc}", file=sys.stderr)
                    return None

                time.sleep(min(30, 2 ** attempt))

        return None

    def search_repositories(self, query: str, max_results: int = 100) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        page = 1
        while len(found) < max_results:
            per_page = min(100, max_results - len(found))
            data = self.get(f"{API}/search/repositories", {
                "q": query, "sort": "updated", "order": "desc",
                "per_page": per_page, "page": page,
            })
            if not isinstance(data, dict):
                break
            items = data.get("items", [])
            if not items:
                break
            found.extend(items)
            if len(items) < per_page or len(found) >= data.get("total_count", 0):
                break
            page += 1
            time.sleep(self.pause)
            # GitHub Search API returns at most 1,000 results per query.
            if page > 10:
                break
        return found[:max_results]

    def get_readme(self, full_name: str) -> tuple[str, str]:
        data = self.get(f"{API}/repos/{full_name}/readme")
        if not isinstance(data, dict):
            return "", ""
        download_url = data.get("download_url") or ""
        # Prefer the raw download URL for text; API metadata still identifies the README.
        if download_url:
            try:
                response = self.session.get(download_url, timeout=self.timeout)
                if response.ok:
                    return response.text[:500_000], data.get("path", "")
            except requests.RequestException:
                pass
        return "", data.get("path", "")

    def get_languages(self, full_name: str) -> dict[str, int]:
        data = self.get(f"{API}/repos/{full_name}/languages")
        return data if isinstance(data, dict) else {}

    def get_tree(self, full_name: str, branch: str | None) -> tuple[list[str], bool]:
        if not branch:
            return [], False
        data = self.get(f"{API}/repos/{full_name}/git/trees/{branch}", {"recursive": "1"})
        if not isinstance(data, dict):
            return [], False
        tree = data.get("tree", [])
        paths = [item.get("path", "") for item in tree if item.get("type") == "blob" and item.get("path")]
        return paths, bool(data.get("truncated", False))


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS repositories (
                                                             repo_id INTEGER PRIMARY KEY,
                                                             full_name TEXT NOT NULL UNIQUE,
                                                             html_url TEXT,
                                                             description TEXT,
                                                             owner TEXT,
                                                             created_at TEXT,
                                                             updated_at TEXT,
                                                             pushed_at TEXT,
                                                             archived INTEGER,
                                                             fork INTEGER,
                                                             stars INTEGER,
                                                             forks INTEGER,
                                                             open_issues INTEGER,
                                                             default_branch TEXT,
                                                             license_name TEXT,
                                                             topics_json TEXT,
                                                             languages_json TEXT,
                                                             readme_path TEXT,
                                                             readme_text TEXT,
                                                             file_paths_json TEXT,
                                                             test_file_count INTEGER,
                                                             has_test_files INTEGER,
                                                             tree_truncated INTEGER,
                                                             matched_queries TEXT,
                                                             collected_at TEXT NOT NULL,
                                                             api_payload_json TEXT
                 )
                 """)
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS search_runs (
                                                            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                            query TEXT NOT NULL,
                                                            started_at TEXT NOT NULL,
                                                            finished_at TEXT,
                                                            result_count INTEGER DEFAULT 0,
                                                            filters_json TEXT,
                                                            notes TEXT
                 )
                 """)
    conn.commit()
    return conn


def matches_filters(repo: dict[str, Any], languages: dict[str, int], paths: list[str],
                    min_stars: int, active_since: str | None, require_tests: bool,
                    allowed_languages: set[str] | None) -> bool:
    if int(repo.get("stargazers_count") or 0) < min_stars:
        return False
    updated = parse_date(repo.get("pushed_at") or repo.get("updated_at"))
    since = parse_date(active_since)
    if since and (not updated):
        return False

    if since and updated:
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)

        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        if updated < since:
            return False

    if allowed_languages and not (set(languages) & allowed_languages):
        return False
    has_tests = any(TEST_FILE_RE.search(path) for path in paths)
    if require_tests and not has_tests:
        return False
    return True


def upsert_repo(conn: sqlite3.Connection, repo: dict[str, Any], query: str,
                languages: dict[str, int], readme_path: str, readme_text: str,
                paths: list[str], truncated: bool) -> None:
    full_name = repo.get("full_name", "")
    previous = conn.execute("SELECT matched_queries FROM repositories WHERE full_name=?", (full_name,)).fetchone()
    queries = set(previous["matched_queries"].split(" || ")) if previous and previous["matched_queries"] else set()
    queries.add(query)
    license_obj = repo.get("license") or {}
    owner_obj = repo.get("owner") or {}
    test_count = sum(1 for path in paths if TEST_FILE_RE.search(path))
    fields = (
        repo.get("id"), full_name, repo.get("html_url"), repo.get("description"),
        owner_obj.get("login"), repo.get("created_at"), repo.get("updated_at"),
        repo.get("pushed_at"), int(bool(repo.get("archived"))), int(bool(repo.get("fork"))),
        repo.get("stargazers_count", 0), repo.get("forks_count", 0),
        repo.get("open_issues_count", 0), repo.get("default_branch"),
        license_obj.get("spdx_id") or license_obj.get("name"),
        json.dumps(repo.get("topics", []), ensure_ascii=False),
        json.dumps(languages, ensure_ascii=False), readme_path, readme_text,
        json.dumps(paths, ensure_ascii=False), test_count, int(test_count > 0),
        int(truncated), " || ".join(sorted(queries)), utc_now(),
        json.dumps(repo, ensure_ascii=False),
    )
    conn.execute("""
                 INSERT INTO repositories (
                     repo_id, full_name, html_url, description, owner, created_at, updated_at,
                     pushed_at, archived, fork, stars, forks, open_issues, default_branch,
                     license_name, topics_json, languages_json, readme_path, readme_text,
                     file_paths_json, test_file_count, has_test_files, tree_truncated,
                     matched_queries, collected_at, api_payload_json
                 ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(full_name) DO UPDATE SET
                     repo_id=excluded.repo_id, html_url=excluded.html_url,
                                                   description=excluded.description, owner=excluded.owner,
                                                   created_at=excluded.created_at, updated_at=excluded.updated_at,
                                                   pushed_at=excluded.pushed_at, archived=excluded.archived, fork=excluded.fork,
                                                   stars=excluded.stars, forks=excluded.forks, open_issues=excluded.open_issues,
                                                   default_branch=excluded.default_branch, license_name=excluded.license_name,
                                                   topics_json=excluded.topics_json, languages_json=excluded.languages_json,
                                                   readme_path=excluded.readme_path, readme_text=excluded.readme_text,
                                                   file_paths_json=excluded.file_paths_json, test_file_count=excluded.test_file_count,
                                                   has_test_files=excluded.has_test_files, tree_truncated=excluded.tree_truncated,
                                                   matched_queries=excluded.matched_queries, collected_at=excluded.collected_at,
                                                   api_payload_json=excluded.api_payload_json
                 """, fields)
    conn.commit()


def export_data(conn: sqlite3.Connection, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [dict(row) for row in conn.execute("SELECT * FROM repositories ORDER BY stars DESC")]
    if not rows:
        print("Nenhum repositório no banco; exportação vazia.")
        return
    # Human-readable fields alongside the original JSON columns.
    export_rows = []
    for row in rows:
        row["topics"] = ", ".join(json.loads(row.pop("topics_json") or "[]"))
        row["languages"] = ", ".join(json.loads(row.pop("languages_json") or "{}").keys())
        row["file_paths"] = "\n".join(json.loads(row.pop("file_paths_json") or "[]"))
        row.pop("api_payload_json", None)
        export_rows.append(row)
    csv_path = out_dir / "repositorios.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(export_rows[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(export_rows)
    try:
        import pandas as pd
        pd.DataFrame(export_rows).to_excel(out_dir / "repositorios.xlsx", index=False)
        print(f"Excel: {out_dir / 'repositorios.xlsx'}")
    except ImportError:
        print("Excel não gerado: instale pandas e openpyxl (pip install pandas openpyxl).")
    # Separate table makes README text easier to review than one very wide sheet.
    readme_rows = [{
        "full_name": r["full_name"], "url": r["html_url"],
        "readme_path": r["readme_path"], "readme_text": r["readme_text"]
    } for r in export_rows]
    with (out_dir / "readmes.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(readme_rows[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(readme_rows)
    print(f"CSV: {csv_path}")
    print(f"README CSV: {out_dir / 'readmes.csv'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Minerador acadêmico de repositórios GitHub.")
    parser.add_argument("--query", action="append", required=True,
                        help='Consulta GitHub Search. Pode repetir: --query "agent testing"')
    parser.add_argument("--max-per-query", type=int, default=100,
                        help="Máximo de repositórios por consulta (máximo prático: 1000).")
    parser.add_argument("--min-stars", type=int, default=0)
    parser.add_argument("--active-since", help="Data ISO, ex.: 2024-01-01; considera pushed_at.")
    parser.add_argument("--language", action="append",
                        help="Filtra por linguagem detectada; pode repetir, ex.: --language Python")
    parser.add_argument("--require-tests", action="store_true",
                        help="Mantém apenas repositórios com caminhos de arquivos que parecem testes.")
    parser.add_argument("--include-forks", action="store_true")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--download-source", action="store_true",
                        help="Clona em modo shallow os repositórios aprovados pelos filtros.")
    parser.add_argument("--source-dir", default="sources",
                        help="Diretório para os clones (usado com --download-source).")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--pause", type=float, default=1.0)
    args = parser.parse_args()

    if args.max_per_query < 1 or args.max_per_query > 1000:
        parser.error("--max-per-query deve estar entre 1 e 1000.")

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("[aviso] GITHUB_TOKEN não definido. A API sem autenticação tem limites menores.", file=sys.stderr)

    miner = GitHubMiner(token=token, pause=max(0, args.pause))
    conn = init_db(Path(args.db))
    languages_filter = {x.casefold() for x in args.language} if args.language else None
    filters = {
        "min_stars": args.min_stars, "active_since": args.active_since,
        "language": args.language, "require_tests": args.require_tests,
        "include_forks": args.include_forks, "include_archived": args.include_archived,
    }

    for query in args.query:
        started = utc_now()
        cur = conn.execute(
            "INSERT INTO search_runs(query, started_at, filters_json) VALUES(?,?,?)",
            (query, started, json.dumps(filters, ensure_ascii=False)),
        )
        run_id = cur.lastrowid
        conn.commit()
        candidates = miner.search_repositories(query, args.max_per_query)
        accepted = 0
        print(f"\nConsulta: {query} | candidatos: {len(candidates)}")

        for index, repo in enumerate(candidates, 1):
            if repo.get("fork") and not args.include_forks:
                continue
            if repo.get("archived") and not args.include_archived:
                continue
            full_name = repo.get("full_name")
            if not full_name:
                continue

            # Fetch files and README only for candidates; this uses additional API requests.
            readme_text, readme_path = miner.get_readme(full_name)
            languages = miner.get_languages(full_name)
            paths, truncated = miner.get_tree(full_name, repo.get("default_branch"))

            if not matches_filters(repo, languages, paths, args.min_stars,
                                   args.active_since, args.require_tests, languages_filter):
                continue

            upsert_repo(conn, repo, query, languages, readme_path, readme_text, paths, truncated)
            if args.download_source:
                source_root = Path(args.source_dir)
                source_root.mkdir(parents=True, exist_ok=True)
                target = source_root / full_name.replace("/", "__")
                if not target.exists():
                    try:
                        result = subprocess.run(
                            ["git", "clone", "--depth", "1", repo.get("html_url", ""), str(target)],
                            capture_output=True, text=True, timeout=300
                        )
                        if result.returncode != 0:
                            print(f"[aviso] clone falhou para {full_name}: {result.stderr.strip()}", file=sys.stderr)
                        else:
                            print(f"  código clonado: {target}")
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        print(f"[aviso] não foi possível clonar {full_name}: {exc}", file=sys.stderr)
            accepted += 1
            if index % 10 == 0:
                print(f"  processados {index}/{len(candidates)}; aceitos nesta consulta: {accepted}")
            time.sleep(max(0, args.pause))

        conn.execute(
            "UPDATE search_runs SET finished_at=?, result_count=? WHERE run_id=?",
            (utc_now(), accepted, run_id),
        )
        conn.commit()
        print(f"Aceitos após filtros: {accepted}")

    export_data(conn, Path(args.out))
    print(f"Banco SQLite: {args.db}")
    print("Coleta concluída. Registre a consulta, data e critérios usados no protocolo da pesquisa.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

