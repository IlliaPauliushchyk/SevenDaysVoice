"""Чтение слота 2 из .rpyc без записи и без запуска игры."""

from __future__ import annotations

import io
import pickle
import struct
import zlib
from pathlib import Path

RPYC2_HEADER = b"RENPY RPC2"


class Stub:
    def __new__(cls, *args, **kwargs):
        return object.__new__(cls)

    def __init__(self, *args, **kwargs):
        self._init_args = args

    def __setitem__(self, key, value):
        items = self.__dict__.setdefault("_items", {})
        items[key] = value

    def __getitem__(self, key):
        return self.__dict__.get("_items", {})[key]

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(_decode_tree(state))
            return
        if isinstance(state, tuple) and len(state) == 2:
            plain, slots = state
            if isinstance(plain, dict):
                self.__dict__.update(_decode_tree(plain))
            if isinstance(slots, dict):
                self.__dict__.update(_decode_tree(slots))
            return
        self._state = _decode_tree(state)


class PyExpr(str):
    def __new__(cls, value, filename=None, linenumber=None):
        text = _as_text(value)
        obj = str.__new__(cls, text)
        obj.filename = _as_text(filename) if filename is not None else None
        obj.linenumber = linenumber
        return obj


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _decode_tree(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {(_as_text(k) if isinstance(k, bytes) else k): _decode_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_tree(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_decode_tree(item) for item in value)
    return value


def _newobj(cls, *args):
    try:
        if issubclass(cls, str):
            return cls.__new__(cls, *args)
    except TypeError:
        pass
    try:
        return cls.__new__(cls, *args)
    except TypeError:
        return cls.__new__(cls)


_STUBS: dict[tuple[str, str], type] = {}


def _stub(module: str, name: str) -> type:
    key = (module, name)
    if key not in _STUBS:
        _STUBS[key] = type(name, (Stub,), {"__module__": module})
    return _STUBS[key]


class RevertableDict(dict):
    pass


class RevertableList(list):
    pass


class RevertableSet(set):
    def __setstate__(self, state):
        if isinstance(state, tuple):
            self.update(state[0].keys())
        else:
            self.update(state)


class RenpyUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if name == "NoneType":
            return type(None)
        if name in {"__newobj__", "newobj"}:
            return _newobj
        if module in {"copy_reg", "copyreg"}:
            return super().find_class("copyreg", name)
        if module in {"renpy.ast", "ast"} and name == "PyExpr":
            return PyExpr
        if module in {"__builtin__", "builtins"} and name in {"object", "str", "unicode", "int", "long", "list", "dict", "tuple", "set"}:
            mapping = {
                "object": object,
                "str": str,
                "unicode": str,
                "int": int,
                "long": int,
                "list": list,
                "dict": dict,
                "tuple": tuple,
                "set": set,
            }
            return mapping[name]
        if module.startswith("renpy") and name == "RevertableDict":
            return RevertableDict
        if module.startswith("renpy") and name == "RevertableList":
            return RevertableList
        if module.startswith("renpy") and name == "RevertableSet":
            return RevertableSet
        if module.startswith("renpy") or module == "store":
            return _stub(module, name)
        try:
            return super().find_class(module, name)
        except Exception:
            return _stub(module, name)


def read_slot(path: Path, slot: int) -> bytes | None:
    with path.open("rb") as handle:
        header = handle.read(1024)
        if not header.startswith(RPYC2_HEADER):
            if slot != 1:
                return None
            handle.seek(0)
            return zlib.decompress(handle.read())
        pos = len(RPYC2_HEADER)
        while pos + 12 <= len(header):
            header_slot, start, length = struct.unpack("III", header[pos : pos + 12])
            if header_slot == 0:
                return None
            if header_slot == slot:
                handle.seek(start)
                return zlib.decompress(handle.read(length))
            pos += 12
    return None


def load_ast(path: Path):
    """Возвращает (data, statements, slot). Предпочитает слот 2: там уже есть идентификаторы."""
    last_error = None
    for slot in (2, 1):
        blob = read_slot(path, slot)
        if not blob:
            continue
        for encoding in ("utf-8", "latin1"):
            try:
                data, statements = RenpyUnpickler(io.BytesIO(blob), encoding=encoding).load()
                return data, statements, slot
            except Exception as exc:  # noqa: BLE001 — другая кодировка или другой слот
                last_error = exc
    raise RuntimeError(f"Не удалось прочитать {path}: {last_error}")
