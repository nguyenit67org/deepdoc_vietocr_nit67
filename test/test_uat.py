"""Deployment safety tests using fake inference, no downloads or GPU."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from module.cancellation import check_cancelled, cancellation_scope, ProcessingCancelled
from server.uat import create_app, run_inference


def prediction():
    keys = ("type title code documentDate officeSender recipients signer priority_level "
            "security_level first_recipients signer_title province receiverDate").split()
    fields = {key: {"value": "0_BÌNH THƯỜNG" if key in ("priority_level", "security_level") else "",
                    "type": "string"} for key in keys}
    return {"information": [fields], "processing_time": 0.1}


class FakePipeline:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.paths = []
        self.block = False

    def process_pdf(self, path, source_filename=None):
        self.paths.append(path)
        assert Path(path).exists()
        self.entered.set()
        while self.block and not self.release.wait(0.01):
            check_cancelled()
        check_cancelled()
        return prediction()


class UatApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"VOCR_API_KEY": "test-key"})
        self.env.start()
        self.pipeline = FakePipeline()
        self.client = TestClient(create_app(lambda: self.pipeline))
        self.client.__enter__()

    def tearDown(self):
        self.pipeline.release.set()
        self.client.__exit__(None, None, None)
        self.env.stop()

    def upload(self, **kwargs):
        return self.client.post("/api/v1/ocr/pdf", headers={"Authorization": "Bearer test-key"},
                                files={"file": ("sample.pdf", b"%PDF-fake", "application/pdf")}, **kwargs)

    def test_health_and_hidden_routes(self):
        self.assertEqual(self.client.get("/health").json(),
                         {"status": "ready", "model_loaded": True, "busy": False})
        for path in ("/docs", "/debug/ocr/pdf", "/api/v1/ocr/pdfs", "/pipeline_outputs/test"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_auth_before_processing(self):
        response = self.client.post("/api/v1/ocr/pdf", content=b"unused")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.pipeline.entered.is_set())

    def test_placeholder_key_rejected_at_startup(self):
        with patch.dict(os.environ, {"VOCR_API_KEY": "REPLACE_WITH_RANDOM_TOKEN"}):
            with self.assertRaisesRegex(RuntimeError, "Replace the example"):
                with TestClient(create_app(lambda: self.pipeline)):
                    pass

    def test_success_cleanup_and_reuse(self):
        for _ in range(2):
            response = self.upload()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()["information"][0]), 13)
        self.assertEqual(len(self.pipeline.paths), 2)
        self.assertTrue(all(not Path(path).exists() for path in self.pipeline.paths))

    def test_one_inference_and_health_while_busy(self):
        self.pipeline.block = True
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.upload)
            try:
                self.assertTrue(self.pipeline.entered.wait(5))
                self.assertTrue(self.client.get("/health").json()["busy"])
                second = self.upload()
                self.assertEqual(second.status_code, 503)
                self.assertIn("Retry-After", second.headers)
                self.assertEqual(len(self.pipeline.paths), 1)
            finally:
                self.pipeline.release.set()
            self.assertEqual(first.result(5).status_code, 200)

    def test_upload_deadline_does_not_limit_inference(self):
        self.pipeline.block = True
        with patch("server.uat.UPLOAD_TOTAL_SECONDS", 0.1):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(self.upload)
                try:
                    self.assertTrue(self.pipeline.entered.wait(5))
                    time.sleep(0.35)
                finally:
                    self.pipeline.release.set()
                self.assertEqual(first.result(5).status_code, 200)

    def test_body_limit_and_slot_released(self):
        with patch("server.uat.MAX_BODY_BYTES", 4):
            self.assertEqual(self.upload().status_code, 413)
        self.assertFalse(self.client.get("/health").json()["busy"])
        self.assertEqual(self.upload().status_code, 200)

    def test_invalid_file_and_failure_cleanup(self):
        response = self.client.post("/api/v1/ocr/pdf", headers={"Authorization": "Bearer test-key"},
                                    files={"file": ("bad.txt", b"abc")})
        self.assertEqual(response.status_code, 400)
        from pdf2image.exceptions import PDFPageCountError
        with patch.object(self.pipeline, "process_pdf", side_effect=PDFPageCountError("bad PDF")):
            self.assertEqual(self.upload().status_code, 422)
        self.assertFalse(self.client.get("/health").json()["busy"])

    def test_chunked_body_limit_without_content_length(self):
        headers = {"Authorization": "Bearer test-key",
                   "Content-Type": "multipart/form-data; boundary=x"}
        with patch("server.uat.MAX_BODY_BYTES", 4):
            response = self.client.post("/api/v1/ocr/pdf", headers=headers,
                                        content=iter([b"--x\r\n", b"oversized"]))
        self.assertEqual(response.status_code, 413)
        self.assertFalse(self.client.get("/health").json()["busy"])

    def test_malformed_multipart_is_not_server_error(self):
        response = self.client.post("/api/v1/ocr/pdf", headers={"Authorization": "Bearer test-key",
                                    "Content-Type": "multipart/form-data"}, content=b"invalid")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.client.get("/health").json()["busy"])


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_cancels_without_reloading(self):
        pipeline = FakePipeline()
        pipeline.block = True
        class Request:
            app = SimpleNamespace(state=SimpleNamespace(pipeline=pipeline))
            async def is_disconnected(self):
                return pipeline.entered.is_set()
        with tempfile.NamedTemporaryFile() as source:
            with self.assertRaises(ProcessingCancelled):
                await asyncio.wait_for(run_inference(Request(), source.name, "sample.pdf", threading.Event()), 5)
        self.assertEqual(len(pipeline.paths), 1)

    async def test_request_cancellation_waits_for_native_call(self):
        entered, finish, exited = threading.Event(), threading.Event(), threading.Event()
        def native(*args, **kwargs):
            entered.set()
            finish.wait(5)
            exited.set()
            check_cancelled()
        class Request:
            app = SimpleNamespace(state=SimpleNamespace(pipeline=SimpleNamespace(process_pdf=native)))
            async def is_disconnected(self):
                return False
        task = asyncio.create_task(run_inference(Request(), "unused", "sample.pdf", threading.Event()))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(exited.is_set())


class PersistenceTests(unittest.TestCase):
    def test_no_output_directory_when_disabled(self):
        from PIL import Image
        from module.pipeline import DocumentPipeline, PipelineConfig
        from module.layout.base import LayoutLabelSchema
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist"
            config = PipelineConfig.from_conf({"output": {"persist": False, "dir": str(output)}})
            schema = LayoutLabelSchema(*(frozenset() for _ in range(4)))
            pipeline = DocumentPipeline(SimpleNamespace(label_schema=schema), None, None, config)
            image = Image.new("RGB", (100, 100))
            with patch("module.pipeline.document_pipeline.load_pdf_page_count", return_value=1), \
                 patch("module.pipeline.document_pipeline.load_pdf_page_window", return_value=[image]), \
                 patch.object(pipeline, "_process_pages_batch", return_value=([[]], [(0, 0)], [image])):
                result = pipeline.process_pdf("not-copied.pdf")
            self.assertEqual(len(result["information"][0]), 13)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
