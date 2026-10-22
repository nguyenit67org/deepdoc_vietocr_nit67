"""HTTP security tests with no OCR/model imports, GPU use or real credentials."""

import os
import importlib.util
import tempfile
import unittest
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import APIRouter, FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from server.schemas import VBHCInformation
from server.security import configure_http_routes, load_api_key


TEST_KEY = "local-test-key-not-a-real-secret"


class APISecurityTests(unittest.TestCase):
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "index.html").write_text("local debug UI", encoding="utf-8")
        (self.root / "page.png").write_bytes(b"preview")
        self.pipeline_calls = 0

    def app(self, debug=False):
        @asynccontextmanager
        async def lifespan(app):
            app.state.api_key = load_api_key()
            yield

        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
        router = APIRouter(prefix="/api/v1/ocr")

        @router.post("/pdf")
        async def pdf(file: UploadFile = File(...)):
            self.pipeline_calls += 1
            fields = {
                name: {"value": "", "type": "string"}
                for name in VBHCInformation.model_fields
            }
            for name in ("priority_level", "security_level"):
                fields[name]["value"] = "0_BÌNH THƯỜNG"
            return {"information": [fields], "processing_time": 0.0}

        @router.get("/schema")
        async def schema():
            return {"schema": []}

        configure_http_routes(
            app, router, pdf, debug_enabled=debug,
            output_dir=self.root, static_dir=self.root,
        )
        return app

    def client(self, debug=False, host="127.0.0.1", base_url="http://127.0.0.1:8000"):
        self.contexts.enter_context(patch.dict(os.environ, {"VOCR_API_KEY": TEST_KEY}))
        return self.contexts.enter_context(TestClient(self.app(debug), base_url=base_url, client=(host, 50000)))

    def upload(self, client, path="/api/v1/ocr/pdf", headers=None):
        return client.post(path, files={"file": ("sample.pdf", b"fake-pdf", "application/pdf")}, headers=headers or {})

    def test_missing_or_empty_key_prevents_startup(self):
        for values in ({}, {"VOCR_API_KEY": ""}, {"VOCR_API_KEY": "   "}, {"VOCR_API_KEY": "bad key"}, {"VOCR_API_KEY": "bad\nkey"}, {"VOCR_API_KEY": "khóa"}):
            with self.subTest(values=bool(values)), patch.dict(os.environ, values, clear=True):
                with self.assertRaisesRegex(RuntimeError, "VOCR_API_KEY"):
                    with TestClient(self.app()):
                        pass

    def test_public_api_always_requires_bearer_even_in_debug(self):
        for debug in (False, True):
            client = self.client(debug)
            for header in (None, "Bearer wrong", "Basic abc", "Bearer", "Bearer " + TEST_KEY + "-wrong"):
                with self.subTest(debug=debug, header_present=header is not None):
                    response = self.upload(client, headers={"Authorization": header} if header else None)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
                    self.assertNotIn(TEST_KEY, response.text)
            self.assertEqual(self.pipeline_calls, 0)

    def test_valid_key_and_schema_route(self):
        client = self.client()
        headers = {"Authorization": "Bearer " + TEST_KEY}
        response = self.upload(client, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["information"][0]), 13)
        self.assertEqual(client.get("/api/v1/ocr/schema").status_code, 401)
        self.assertEqual(client.get("/api/v1/ocr/schema", headers=headers).status_code, 200)

    def test_uninitialized_auth_fails_closed(self):
        client = self.client()
        client.app.state.api_key = None
        response = self.upload(client, headers={"Authorization": "Bearer " + TEST_KEY})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.pipeline_calls, 0)

    def test_lowercase_bearer_and_non_ascii_bad_key(self):
        client = self.client()
        self.assertEqual(self.upload(client, headers={"Authorization": "bearer " + TEST_KEY}).status_code, 200)
        # Raw bytes exercise untrusted non-ASCII input without logging a secret.
        response = self.upload(client, headers={b"Authorization": b"Bearer \xc3\xa9"})
        self.assertEqual(response.status_code, 401)

    def test_debug_off_has_no_ui_outputs_debug_or_docs(self):
        client = self.client()
        for path in ("/", "/index.html", "/pipeline_outputs/page.png", "/docs", "/redoc", "/openapi.json", "/health", "/debug/config"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)
        self.assertEqual(self.upload(client, "/debug/ocr/pdf").status_code, 404)

    def test_local_debug_without_key_never_returns_key(self):
        client = self.client(debug=True)
        response = self.upload(client, "/debug/ocr/pdf", headers={"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for path in ("/", "/pipeline_outputs/page.png"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertNotIn(TEST_KEY, response.text)
        self.assertEqual(client.get("/debug/config").status_code, 404)
        self.assertEqual(self.pipeline_calls, 1)

    def test_remote_debug_is_rejected_for_ui_outputs_and_post(self):
        client = self.client(debug=True, host="192.0.2.1")
        for path in ("/", "/pipeline_outputs/page.png"):
            self.assertEqual(client.get(path).status_code, 403)
        self.assertEqual(self.upload(client, "/debug/ocr/pdf").status_code, 403)
        self.assertEqual(self.pipeline_calls, 0)

    def test_loopback_with_foreign_host_is_rejected(self):
        client = self.client(debug=True, base_url="http://attacker.example")
        self.assertEqual(client.get("/").status_code, 403)
        self.assertEqual(self.upload(client, "/debug/ocr/pdf").status_code, 403)

    def test_cross_origin_and_forwarding_headers_are_rejected(self):
        client = self.client(debug=True)
        cases = (
            {"Origin": "https://attacker.example"}, {"Origin": "null"},
            {"Origin": "http://localhost:8000"}, {"Origin": "http://127.0.0.1:9000"},
            {"Origin": "http://[broken"}, {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"}, {"Forwarded": "for=127.0.0.1"},
            {"X-Forwarded-For": "127.0.0.1"}, {"X-Forwarded-Host": "localhost"},
            {"X-Real-IP": "127.0.0.1"}, {"Via": "proxy"},
        )
        for headers in cases:
            with self.subTest(headers=headers):
                self.assertEqual(self.upload(client, "/debug/ocr/pdf", headers=headers).status_code, 403)
                self.assertEqual(client.get("/pipeline_outputs/page.png", headers=headers).status_code, 403)
        self.assertEqual(self.pipeline_calls, 0)

    def test_ipv6_loopback_supported(self):
        client = self.client(debug=True, host="::1", base_url="http://localhost:8000")
        self.assertEqual(self.upload(client, "/debug/ocr/pdf").status_code, 200)

    def test_static_ui_uses_only_local_debug_endpoint(self):
        html = (Path(__file__).parents[1] / "server/static/index.html").read_text()
        self.assertIn("fetch('/debug/ocr/pdf'", html)
        self.assertNotIn("VOCR_API_KEY", html)
        self.assertNotIn("localStorage", html)

    def test_docker_build_excludes_root_and_nested_env_files(self):
        patterns = (Path(__file__).parents[1] / ".dockerignore").read_text().splitlines()
        for pattern in (".env*", "*.env", "**/.env*", "**/*.env"):
            self.assertIn(pattern, patterns)

    def test_actual_main_wiring_and_key_validation_before_model_loading(self):
        # Execute the real HTTP entrypoint, replacing only model/config imports.
        # This also proves tests do not start a service or instantiate OCR models.
        import server

        pipeline = ModuleType("module.pipeline")
        pipeline.load_pipeline_conf = lambda: {"extract": {"enabled": False}}
        pipeline.PipelineConfig = SimpleNamespace(from_conf=lambda _: SimpleNamespace(
            output_dir=str(self.root), debug_enabled=False,
        ))
        pipeline.build_pipeline = Mock(return_value=object())
        extract = ModuleType("module.extract")
        extract.get_extract_backend = Mock()
        routes = ModuleType("server.routes")
        routes.router = APIRouter(prefix="/api/v1/ocr")

        @routes.router.get("/probe")
        async def probe():
            return {"ok": True}

        async def pdf(file: UploadFile = File(...)):
            return {}

        routes.ocr_pdf = pdf
        spec = importlib.util.spec_from_file_location(
            "server._test_main", Path(__file__).parents[1] / "server/main.py",
        )
        entrypoint = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"module.pipeline": pipeline, "module.extract": extract, "server.routes": routes}), patch.object(server, "routes", routes, create=True):
            spec.loader.exec_module(entrypoint)

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "VOCR_API_KEY"):
                with TestClient(entrypoint.app):
                    pass
        pipeline.build_pipeline.assert_not_called()
        with patch.dict(os.environ, {"VOCR_API_KEY": TEST_KEY}):
            with TestClient(entrypoint.app) as client:
                self.assertEqual(client.get("/api/v1/ocr/probe").status_code, 401)
                self.assertEqual(client.get("/api/v1/ocr/probe", headers={"Authorization": "Bearer " + TEST_KEY}).status_code, 200)
                for path in ("/", "/health", "/docs", "/openapi.json", "/pipeline_outputs/page.png"):
                    self.assertEqual(client.get(path).status_code, 404)
        pipeline.build_pipeline.assert_called_once()
        extract.get_extract_backend.assert_not_called()

    def test_actual_pdf_route_reused_for_local_debug_and_auth_api(self):
        # Import real route handlers with model modules stubbed out, then verify
        # both URLs share validation/response behavior without running inference.
        pipeline_module = ModuleType("module.pipeline")
        pipeline_module.DocumentPipeline = type("DocumentPipeline", (), {})
        pipeline_module.load_pipeline_conf = lambda: {}
        extract_module = ModuleType("module.extract")
        extract_module.ExtractBackend = type("ExtractBackend", (), {})
        extract_module.get_default_schema = lambda _: {}
        spec = importlib.util.spec_from_file_location(
            "server._test_routes", Path(__file__).parents[1] / "server/routes.py",
        )
        real_routes = importlib.util.module_from_spec(spec)
        # deps.py is isolated too, so this test does not leave model stubs cached
        # in the normal server dependency module used by other test suites.
        dep_spec = importlib.util.spec_from_file_location(
            "server.deps", Path(__file__).parents[1] / "server/deps.py",
        )
        deps = importlib.util.module_from_spec(dep_spec)
        with patch.dict("sys.modules", {"module.pipeline": pipeline_module, "module.extract": extract_module, "server.deps": deps}):
            dep_spec.loader.exec_module(deps)
            spec.loader.exec_module(real_routes)
        for name in ("_release_memory", "_log_rss", "_log_torch_tensor_stats", "_log_memory_hogs", "_log_duplicate_functions"):
            setattr(real_routes, name, Mock())

        fields = {name: {"value": "", "type": "string"} for name in VBHCInformation.model_fields}
        for name in ("priority_level", "security_level"):
            fields[name]["value"] = "0_BÌNH THƯỜNG"
        pipeline = SimpleNamespace(process_pdf=Mock(return_value={"information": [fields], "processing_time": 0.01}))
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.state.api_key = TEST_KEY
        app.state.pipeline = pipeline
        configure_http_routes(app, real_routes.router, real_routes.ocr_pdf, debug_enabled=True, output_dir=self.root, static_dir=self.root)
        with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
            self.assertEqual(self.upload(client).status_code, 401)
            pipeline.process_pdf.assert_not_called()
            for url, headers in (("/debug/ocr/pdf", {}), ("/api/v1/ocr/pdf", {"Authorization": "Bearer " + TEST_KEY})):
                response = self.upload(client, url, headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()["information"][0]), 13)
                self.assertNotIn("debug", response.json())
                self.assertEqual(client.post(url, headers=headers, files={"file": ("bad.txt", b"text")}).status_code, 400)
                self.assertEqual(client.post(url, headers=headers, files={"file": ("empty.pdf", b"")}).status_code, 400)
                self.assertEqual(client.post(url, headers=headers).status_code, 422)
            self.assertEqual(pipeline.process_pdf.call_count, 2)
            headers = {"Authorization": "Bearer " + TEST_KEY}
            pipeline.process_pdf.side_effect = real_routes.PDFSyntaxError("invalid test PDF")
            response = self.upload(client, headers=headers)
            self.assertEqual(response.status_code, 422)
            self.assertTrue(response.json()["detail"].startswith("Unable to read PDF:"))
            pipeline.process_pdf.side_effect = RuntimeError("internal test failure")
            with patch.object(real_routes.logger, "exception"):
                response = self.upload(client, headers=headers)
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.json(), {"detail": "Internal processing error"})
            app.state.pipeline = None
            self.assertEqual(self.upload(client, headers=headers).status_code, 503)


if __name__ == "__main__":
    unittest.main()
