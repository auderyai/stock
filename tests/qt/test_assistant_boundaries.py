from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date
import unittest

from krx_research.qt.services.assistant_service import ReadOnlyDatabaseTool
from krx_research.qt.services.assistant_service import AssistantService
from krx_research.qt.services.assistant_workspace import OneOffWorkspace, ReusableCodeLibrary


class AssistantBoundaryTests(unittest.TestCase):
    def test_assistant_parses_text_and_citations_without_persisting_api_state(self):
        class Response:
            ok = True

            @staticmethod
            def json():
                return {"output": [{"type": "message", "content": [{
                    "type": "output_text", "text": "검증 결과",
                    "annotations": [{
                        "type": "url_citation", "title": "공식 자료",
                        "url": "https://example.test/source",
                    }],
                }]}]}

        class Session:
            @staticmethod
            def post(*_args, **kwargs):
                assert kwargs["json"]["store"] is False
                return Response()

        service = AssistantService(None, session=Session())
        service._api_key = "test-key"
        reply = service.ask("확인")
        self.assertEqual(reply.text, "검증 결과")
        self.assertEqual(reply.citations, (("공식 자료", "https://example.test/source"),))

    def test_read_only_sql_rejects_mutation_and_escape(self):
        statements = (
            "DELETE FROM prices",
            "WITH gone AS (DELETE FROM prices RETURNING *) SELECT * FROM gone",
            "SELECT pg_read_file('/tmp/x')",
            "SELECT 1; SELECT 2",
            "SELECT 1 -- hidden",
        )
        for sql in statements:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                ReadOnlyDatabaseTool(None).query(sql)

    def test_assistant_rejects_reversed_period_before_provider_call(self):
        service = AssistantService(None, provider="codex", codex_backend=object())
        with self.assertRaisesRegex(ValueError, "시작일.*종료일"):
            service.ask("조회", period=(date(2026, 10, 8), date(2026, 9, 23)))

    def test_one_off_workspace_executes_json_calculation(self):
        with TemporaryDirectory() as directory:
            workspace = OneOffWorkspace(Path(directory))
            result = workspace.execute(
                "result = {'total': sum(row['value'] for row in input_data)}",
                [{"value": 2}, {"value": 3}],
            )
        self.assertEqual(result, {"total": 5})

    def test_one_off_execution_is_auditable_and_reusable_only_after_registration(self):
        with TemporaryDirectory() as directory:
            workspace = OneOffWorkspace(Path(directory))
            execution = workspace.execute_record("result = input_data['value'] * 2", {"value": 3})
            self.assertEqual(workspace.list_runs()[0]["status"], "completed")
            self.assertEqual(workspace.load_code(execution.run_id).strip(), "result = input_data['value'] * 2")
            library = ReusableCodeLibrary(workspace)
            registered = library.register(execution.run_id, "두 배 계산", "검증된 계산", code="result = input_data['value'] * 3")
            reused = library.execute(registered["library_id"], {"value": 4})
            self.assertEqual(reused.result, 12)
            self.assertEqual(library.list()[0]["use_count"], 1)
            self.assertEqual(library.list()[0]["version_count"], 1)
            second = library.register(execution.run_id, "두 배 계산", "수정 버전", code="result = input_data['value'] * 4")
            self.assertEqual(second["version_count"], 2)
            self.assertEqual(library.execute(second["library_id"], {"value": 4}).result, 16)
            code_path = library.root / second["library_id"] / f"{second['active_version']}.py"
            code_path.write_text("result = 999\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "무결성"):
                library.execute(second["library_id"], {})

    def test_reusable_library_rejects_path_escape_and_unsafe_modification(self):
        with TemporaryDirectory() as directory:
            workspace = OneOffWorkspace(Path(directory)); library = ReusableCodeLibrary(workspace)
            execution = workspace.execute_record("result = 1", {})
            with self.assertRaises(ValueError):
                library.register(execution.run_id, "위험", "", code="import os\nresult = 1")
            with self.assertRaises(ValueError):
                library.execute("../outside", {})

    def test_only_completed_runs_are_promotable_and_frequent_code_is_recommended(self):
        with TemporaryDirectory() as directory:
            service = AssistantService(None, Path(directory), provider="codex", codex_backend=object())
            for _ in range(3): service._workspace.execute("result = 1", {})
            self.assertTrue(all(row["promotion_recommended"] for row in service.one_off_runs()))
            with self.assertRaises(RuntimeError): service._workspace.execute("result = 1 / 0", {})
            failed = next(row for row in service.one_off_runs() if row["status"] == "failed")
            self.assertEqual(failed["status"], "failed")
            with self.assertRaisesRegex(ValueError, "완료된"):
                service.register_reusable(failed["run_id"], "실패 코드", "", service.one_off_code(failed["run_id"]))

    def test_one_off_workspace_rejects_host_access(self):
        statements = (
            "import os\nresult = 1",
            "result = open('x').read()",
            "result = (1).__class__",
        )
        with TemporaryDirectory() as directory:
            workspace = OneOffWorkspace(Path(directory))
            for code in statements:
                with self.subTest(code=code), self.assertRaises(ValueError):
                    workspace.execute(code, {})

    def test_tool_failure_is_returned_to_model_for_retry(self):
        responses = iter((
            {"output": [{"type": "function_call", "name": "query_database",
                         "arguments": '{"sql":"SELECT missing"}', "call_id": "call-1"}]},
            {"output": [{"type": "message", "content": [
                {"type": "output_text", "text": "조회식을 수정했습니다.", "annotations": []}
            ]}]},
        ))

        class Response:
            ok = True
            def __init__(self): self._body = next(responses)
            def json(self): return self._body

        class Session:
            calls = []
            @classmethod
            def post(cls, *_args, **kwargs):
                cls.calls.append(kwargs["json"]["input"]); return Response()

        service = AssistantService(None, session=Session())
        service._api_key = "test-key"
        service._database.query = lambda _sql, **_kwargs: (_ for _ in ()).throw(RuntimeError("없는 열"))
        reply = service.ask("조회")
        output = Session.calls[-1][-1]
        self.assertEqual(reply.text, "조회식을 수정했습니다.")
        self.assertIn('"ok": false', output["output"])
        self.assertIn("없는 열", output["output"])

    def test_openai_error_extracts_json_message_instead_of_closing_brace(self):
        class Response:
            status_code = 400
            @staticmethod
            def json(): return {"error": {"message": "지원하지 않는 도구입니다.", "code": "bad_tool"}}

        message = AssistantService._api_error(Response())
        self.assertIn("지원하지 않는 도구", message)
        self.assertNotEqual(message, "}")

    def test_openai_credit_exhaustion_explains_separate_api_billing(self):
        class Response:
            status_code = 429
            @staticmethod
            def json(): return {"error": {"code": "credit_balance_exhausted"}}

        message = AssistantService._api_error(Response())
        self.assertIn("API 크레딧이 소진", message)
        self.assertIn("ChatGPT/Codex 구독 사용량과 API 크레딧은 별도", message)

    def test_codex_subscription_backend_uses_controlled_tools(self):
        class Backend:
            calls = 0
            def step(self, _prompt):
                self.calls += 1
                return ({"action": "query_database", "arguments": '{"sql":"SELECT 1 AS value"}',
                         "answer": "", "citations": []} if self.calls == 1 else
                        {"action": "finish", "arguments": "{}", "answer": "완료", "citations": []})

        backend = Backend()
        service = AssistantService(None, provider="codex", codex_backend=backend)
        service._database.query = lambda _sql, **_kwargs: __import__("pandas").DataFrame([{"value": 1}])
        reply = service.ask("확인")
        self.assertEqual(reply.text, "완료")
        self.assertEqual(reply.frame.iloc[0]["value"], 1)
        self.assertEqual(backend.calls, 2)

    def test_codex_database_tool_does_not_impose_screen_period_on_analysis_sql(self):
        class Backend:
            calls = 0
            def step(self, _prompt):
                self.calls += 1
                return ({"action": "query_database", "arguments": '{"sql":"SELECT 1 AS value"}',
                         "answer": "", "citations": []} if self.calls == 1 else
                        {"action": "finish", "arguments": "{}", "answer": "완료", "citations": []})

        service = AssistantService(None, provider="codex", codex_backend=Backend())
        received = []
        service._database.query = lambda sql, **kwargs: (
            received.append((sql, kwargs)) or __import__("pandas").DataFrame([{"value": 1}])
        )
        period = (date(2026, 9, 23), date(2026, 10, 8))
        service.ask("확인", period=period)
        self.assertEqual(received, [("SELECT 1 AS value", {})])

    def test_one_off_database_analysis_uses_screen_codes_and_records_run(self):
        with TemporaryDirectory() as directory:
            service = AssistantService(None, Path(directory), provider="codex", codex_backend=object())
            service._screen_cache = __import__("pandas").DataFrame([{"stock_code": "5930"}])
            queries = []
            service._database.query = lambda sql, **kwargs: (
                queries.append((sql, kwargs)) or
                __import__("pandas").DataFrame([{"stock_code": "005930", "close": 10}])
            )
            output = service._call_tool(
                "run_one_off_query_python",
                '{"sql":"SELECT * FROM prices WHERE stock_code IN ({{screen_codes}})",'
                '"code":"result = [{\'stock_code\': row[\'stock_code\']} for row in input_data]"}',
            )
            self.assertIn("'005930'", queries[0][0])
            self.assertEqual(queries[0][1], {"limit": 50_000})
            self.assertEqual(output["input_row_count"], 1)
            self.assertEqual(len(service.one_off_runs()), 1)

    def test_numbered_screen_uses_existing_runner_and_reuses_cached_result(self):
        service = AssistantService(None, provider="codex", codex_backend=object())
        calls = []
        service.bind_numbered_screen_runner(
            lambda number, period, limit: (
                calls.append((number, period, limit)) or
                (f"{number}. 시험 항목", [{"stock_code": "005930", "stock_name": "삼성전자"}])
            )
        )
        service.set_screen_rank_limit(100)
        period = (date(2026, 9, 23), date(2026, 10, 8))
        first = service._call_tool("run_numbered_screen", '{"number":12}', period)
        cached = service._call_tool("get_last_screen_result", "{}", period)
        self.assertEqual(calls, [(12, period, 100)])
        self.assertEqual(first, cached)
        self.assertEqual(service._last_frame.iloc[0]["stock_code"], "005930")

    def test_numbered_screen_rejects_missing_runner_or_period(self):
        service = AssistantService(None, provider="codex", codex_backend=object())
        with self.assertRaisesRegex(ValueError, "시작일과 종료일"):
            service._call_tool("run_numbered_screen", '{"number":1}')
        with self.assertRaisesRegex(RuntimeError, "연결되지"):
            service._call_tool(
                "run_numbered_screen", '{"number":1}',
                (date(2026, 10, 8), date(2026, 10, 8)),
            )


if __name__ == "__main__":
    unittest.main()
