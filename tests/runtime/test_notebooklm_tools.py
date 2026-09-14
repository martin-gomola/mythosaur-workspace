from services.mcp_server.plugins.workspace import notebooklm


def test_tool_command_prefers_wrapper_when_no_override(monkeypatch, tmp_path):
    wrapper_path = tmp_path / "notebooklm_cli.py"
    wrapper_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    monkeypatch.delenv("MW_NOTEBOOKLM_BIN", raising=False)
    monkeypatch.setattr(notebooklm, "WRAPPER_PATH", wrapper_path)

    command = notebooklm._tool_command("login", "--check", "--profile", "demo")

    assert command[0] == notebooklm.sys.executable
    assert command[1] == str(wrapper_path)
    assert command[2:] == ["login", "--check", "--profile", "demo"]


def test_tool_command_respects_explicit_bin_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MW_NOTEBOOKLM_BIN", "/custom/bin/nlm")
    monkeypatch.setattr(notebooklm, "WRAPPER_PATH", tmp_path / "missing-wrapper.py")

    command = notebooklm._tool_command("notebook", "list")

    assert command == ["/custom/bin/nlm", "notebook", "list"]


def test_binary_exists_checks_wrapper_files(monkeypatch, tmp_path):
    wrapper_path = tmp_path / "notebooklm_cli.py"
    wrapper_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    python_path = tmp_path / "python"
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.delenv("MW_NOTEBOOKLM_BIN", raising=False)
    monkeypatch.setattr(notebooklm, "WRAPPER_PATH", wrapper_path)
    monkeypatch.setattr(notebooklm.sys, "executable", str(python_path))

    assert notebooklm._binary_exists() is True


def test_binary_exists_uses_shutil_for_named_binary(monkeypatch, tmp_path):
    monkeypatch.delenv("MW_NOTEBOOKLM_BIN", raising=False)
    monkeypatch.setattr(notebooklm, "WRAPPER_PATH", tmp_path / "missing-wrapper.py")
    monkeypatch.setattr(notebooklm.shutil, "which", lambda name: "/usr/bin/nlm" if name == "nlm" else None)

    assert notebooklm._binary_exists() is True


def test_command_env_maps_mt_ssl_cert_file(monkeypatch):
    monkeypatch.setenv("MW_SSL_CERT_FILE", "/secrets/macos-ca-bundle.pem")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)

    env = notebooklm._command_env()

    assert env["SSL_CERT_FILE"] == "/secrets/macos-ca-bundle.pem"
    assert env["REQUESTS_CA_BUNDLE"] == "/secrets/macos-ca-bundle.pem"
    assert env["CURL_CA_BUNDLE"] == "/secrets/macos-ca-bundle.pem"
