import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from starlette.requests import Request
from starlette.responses import PlainTextResponse


def webhook(verified):
    source = Path(__file__).resolve().parents[1] / "src/webapp/routes/webhooks.py"
    function = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "intellectmoney_webhook")
    function.decorator_list = []
    for arg in function.args.args:
        arg.annotation = None
    function.args.defaults = []
    namespace = {"PlainTextResponse": PlainTextResponse,
                 "intellectmoney": SimpleNamespace(verify_webhook_hash=lambda payload: verified),
                 "get_cart_by_id": AsyncMock(return_value=None)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["intellectmoney_webhook"], namespace


def request(body):
    sent = False
    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/webhooks/intellectmoney",
                    "headers": [(b"content-type", b"application/x-www-form-urlencoded")]}, receive)


class WebhookFormTests(unittest.TestCase):
    def test_unsigned_form_is_rejected_without_touching_database(self):
        handler, ns = webhook(False)
        result = asyncio.run(handler(request(b"OrderId=123&PaymentId=test&Hash=invalid"), None))
        self.assertEqual(result.status_code, 400)
        ns["get_cart_by_id"].assert_not_awaited()

    def test_signed_unknown_order_does_not_create_payment(self):
        handler, ns = webhook(True)
        result = asyncio.run(handler(request(b"OrderId=999999999&PaymentId=test"), None))
        self.assertEqual(result.status_code, 404)
        ns["get_cart_by_id"].assert_awaited_once_with(None, 999999999)


if __name__ == "__main__":
    unittest.main()
