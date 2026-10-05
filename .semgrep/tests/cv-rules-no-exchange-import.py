"""Fixtures for cv-rules-no-exchange-import."""
import importlib

from candleviewer.exchange.base import Adapter  # ruleid: cv-rules-no-exchange-import
import candleviewer.exchange.bybit  # ruleid: cv-rules-no-exchange-import
from candleviewer import exchange  # ruleid: cv-rules-no-exchange-import
from ..exchange import bybit  # ruleid: cv-rules-no-exchange-import
from ...exchange.base import Adapter2  # ruleid: cv-rules-no-exchange-import
from .. import exchange as ex  # ruleid: cv-rules-no-exchange-import
from candleviewer.oms import submit  # ok: cv-rules-no-exchange-import
from ..oms import intents  # ok: cv-rules-no-exchange-import


def dyn() -> object:
    return importlib.import_module("candleviewer.exchange.bybit")  # ruleid: cv-rules-no-exchange-import
