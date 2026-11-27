"""
Dashboard de Indicadores Econômicos — App Flask
Lê os indicadores do Postgres da Aiven (tabela bcb_series). Quando o cache
de uma série fica velho, o próprio app busca dados novos na API do BCB
(ver refresh_stale_series). Cada acesso fica registrado na tabela visits.

Variáveis de ambiente esperadas (ver .env.example):
  AIVEN_DB_URL   -> string de conexão fornecida pela Aiven
  PORT           -> porta HTTP (default 8080)
  CACHE_HOURS    -> horas antes de buscar dados novos na API (default 6)
"""

import os
import time
import datetime
from flask import Flask, render_template, jsonify
import requests

import bcb_client as bcb

app = Flask(__name__)

CACHE_HOURS = int(os.environ.get("CACHE_HOURS", 6))
TZ = os.environ.get("TZ_DISPLAY", "America/Sao_Paulo")
START_TIME = time.time()

# Garante que as tabelas existam assim que o módulo é carregado — necessário
# porque em produção o app roda via gunicorn (`gunicorn app:app`), que nunca
# executa o bloco `if __name__ == "__main__":` lá embaixo.
bcb.init_db()


def log_visit(path: str):
    with bcb.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO visits (path) VALUES (%s);", (path,))
        conn.commit()


def is_cache_stale(series_code: int) -> bool:
    with bcb.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(fetched_at) AS last_fetch FROM bcb_series WHERE series_code = %s;",
                (series_code,),
            )
            row = cur.fetchone()
    if not row or not row["last_fetch"]:
        return True
    age = datetime.datetime.now(datetime.timezone.utc) - row["last_fetch"]
    return age > datetime.timedelta(hours=CACHE_HOURS)


def refresh_stale_series():
    """Só busca na API do BCB as séries com cache vencido."""
    for code in bcb.SERIES:
        if is_cache_stale(code):
            try:
                points = bcb.fetch_series_from_bcb(code)
                bcb.upsert_series(code, points)
            except (requests.RequestException, ValueError) as exc:  # noqa: BLE001
                app.logger.warning("Falha ao atualizar série %s: %s", code, exc)


def get_series_data(series_code: int):
    with bcb.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ref_date, value
                FROM bcb_series
                WHERE series_code = %s
                ORDER BY ref_date DESC
                LIMIT %s;
                """,
                (series_code, bcb.POINTS_PER_SERIES),
            )
            # DESC pega os mais recentes (ASC pegava os 30 mais antigos da
            # tabela, que só cresce); inverte pra exibir em ordem cronológica.
            return cur.fetchall()[::-1]


def get_dashboard_data():
    refresh_stale_series()

    indicators = []
    for code, meta in bcb.SERIES.items():
        rows = get_series_data(code)
        latest = rows[-1] if rows else None
        previous = rows[-2] if len(rows) > 1 else None
        delta = None
        if latest and previous:
            delta = round(float(latest["value"]) - float(previous["value"]), meta["casas"])

        indicators.append(
            {
                "code": code,
                "name": meta["name"],
                "unit": meta["unit"],
                "latest_value": round(float(latest["value"]), meta["casas"]) if latest else None,
                "latest_date": latest["ref_date"].strftime("%d/%m/%Y") if latest else None,
                "delta": delta,
                "labels": [r["ref_date"].strftime("%d/%m") for r in rows],
                "values": [round(float(r["value"]), meta["casas"]) for r in rows],
            }
        )

    with bcb.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM visits;")
            total_visits = cur.fetchone()["total"]
            cur.execute(
                """
                SELECT to_char(m, 'HH24:MI') AS minute, total
                FROM (
                    SELECT date_trunc('minute', created_at AT TIME ZONE %s) AS m,
                           COUNT(*) AS total
                    FROM visits
                    WHERE created_at > now() - interval '30 minutes'
                    GROUP BY m
                ) t
                ORDER BY m;
                """,
                (TZ,),
            )
            per_minute = cur.fetchall()
            cur.execute(
                """
                SELECT path, to_char(created_at AT TIME ZONE %s, 'DD/MM HH24:MI:SS') AS at
                FROM visits
                ORDER BY id DESC
                LIMIT 10;
                """,
                (TZ,),
            )
            recent_visits = cur.fetchall()

    return {
        "indicators": indicators,
        "total_visits": total_visits,
        "visits_per_minute": {
            "labels": [r["minute"] for r in per_minute],
            "values": [r["total"] for r in per_minute],
        },
        "recent_visits": recent_visits,
        "uptime_seconds": int(time.time() - START_TIME),
        "server_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cache_hours": CACHE_HOURS,
    }


@app.route("/")
def dashboard():
    log_visit("/")
    data = get_dashboard_data()
    return render_template("dashboard.html", data=data)


@app.route("/api/indicators")
def api_indicators():
    log_visit("/api/indicators")
    return jsonify(get_dashboard_data())


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Força a atualização de todas as séries via cache batch, ignorando a
    idade do cache. Útil como fallback quando não se está usando Kafka."""
    for code in bcb.SERIES:
        try:
            points = bcb.fetch_series_from_bcb(code)
            bcb.upsert_series(code, points)
        except (requests.RequestException, ValueError) as exc:  # noqa: BLE001
            return jsonify({"status": "error", "series": code, "detail": str(exc)}), 502
    return jsonify({"status": "ok", "refreshed": list(bcb.SERIES.keys())})


@app.route("/healthz")
def healthz():
    """Usado pelo pipeline de CI/CD e pelo health check do Render.

    `commit` vem do RENDER_GIT_COMMIT (o Render preenche sozinho): o CI usa
    pra saber se a versão nova já está no ar, e não a anterior."""
    try:
        with bcb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return jsonify({"status": "ok", "commit": os.environ.get("RENDER_GIT_COMMIT")}), 200
    except Exception:  # noqa: BLE001
        # Detalhe só no log: a mensagem do psycopg2 expõe host/usuário do banco.
        app.logger.exception("healthz: falha ao consultar o banco")
        return jsonify({"status": "error"}), 503


if __name__ == "__main__":
    refresh_stale_series()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
