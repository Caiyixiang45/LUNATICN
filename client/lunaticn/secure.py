"""Windows DPAPI 凭据加密：密码仅当前 Windows 用户可解，不落明文。"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
from ctypes import wintypes


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _protect(data: bytes) -> bytes:
    out = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(_blob(data)), None, None, None, None, 0,
            ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _unprotect(data: bytes) -> bytes:
    out = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(_blob(data)), None, None, None, None, 0,
            ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def save_password(plain: str) -> str:
    """加密并返回 base64 串（存 settings 的 saved_password_enc）。"""
    return base64.b64encode(_protect(plain.encode("utf-8"))).decode("ascii")


def load_password(enc: str) -> str:
    """解密；失败返回 ""（换机器/凭据损坏时不炸启动）。"""
    if not enc:
        return ""
    try:
        return _unprotect(base64.b64decode(enc.encode("ascii"))).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""
