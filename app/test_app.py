"""Testes da app contra um Postgres de verdade (no CI sobe um container).

Rodar local:
    AIVEN_DB_URL=postgres://postgres:postgres@localhost:5432/postgres \
    DB_SSLMODE=disable python -m unittest -v test_app

A API do BCB é trocada por um mock: o teste não depende de rede externa.
"""
import datetime
import unittest
from unittest import mock

import bcb_client as bcb
import app as webapp

START = datetime.date(2026, 1, 1)
# 40 pontos por série: mais que POINTS_PER_SERIES (30), pra pegar o bug do
# ORDER BY ASC que mostrava os pontos mais antigos.
POINTS = [{"ref_date": START + datetime.timedelta(days=i), "value": 5 + i / 100} for i in range(40)]


class DashboardTest(unittest.TestCase):
    def setUp(self):
        with bcb.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE bcb_series, visits;")
            conn.commit()
        for code in bcb.SERIES:
            bcb.upsert_series(code, POINTS)
        # cache recém-gravado: se a app tentar ir na API, o teste quebra
        patcher = mock.patch.object(bcb, "fetch_series_from_bcb", side_effect=AssertionError)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = webapp.app.test_client()

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    def test_indicadores_usam_pontos_mais_recentes(self):
        data = self.client.get("/api/indicators").get_json()
        self.assertEqual(len(data["indicators"]), len(bcb.SERIES))
        for ind in data["indicators"]:
            self.assertEqual(len(ind["values"]), bcb.POINTS_PER_SERIES)
            self.assertEqual(ind["latest_date"], "09/02/2026")  # 01/01 + 39 dias

    def test_acessos_sao_registrados(self):
        self.client.get("/")
        data = self.client.get("/api/indicators").get_json()
        self.assertEqual(data["total_visits"], 2)
        self.assertEqual(sum(data["visits_per_minute"]["values"]), 2)
        self.assertEqual(data["recent_visits"][0]["path"], "/api/indicators")

    def test_pagina_renderiza(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Últimos acessos", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
