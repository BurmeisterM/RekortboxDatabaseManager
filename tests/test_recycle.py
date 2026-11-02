import sys
import os

import pytest

from rekordbox_manager.recycle import recycle_file


@pytest.mark.skipif(sys.platform != "win32", reason="Windows COM integration")
@pytest.mark.parametrize("can_recycle", [True, False])
def test_shell_cannot_fall_back_to_permanent_deletion(tmp_path, monkeypatch, can_recycle):
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from winerror import E_ABORT

    file = tmp_path / "synthetic.mp3"
    file.write_bytes(b"test")
    state = {}

    class Operation:
        def SetOperationFlags(self, flags):
            state["flags"] = flags

        def DeleteItem(self, item, sink):
            state["sink"] = sink

        def PerformOperations(self):
            sink = state["sink"]
            flags = shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE if can_recycle else 0
            sink.PreDeleteItem(flags, None)
            sink.PostDeleteItem(flags, None, 0, object())
            return 0

        def GetAnyOperationsAborted(self):
            return False

    monkeypatch.setattr(pythoncom, "CoCreateInstance", lambda *args: Operation())
    monkeypatch.setattr(pythoncom, "WrapObject", lambda sink, *args: sink)
    monkeypatch.setattr(shell, "SHCreateItemFromParsingName", lambda *args: object())
    if can_recycle:
        recycle_file(file)
    else:
        with pytest.raises(COMException) as exc:
            recycle_file(file)
        assert exc.value.scode == E_ABORT
    assert state["flags"] & 0x00080000
    # A synthetic shell is used; the actual test file was never touched.
    assert file.is_file()


@pytest.fixture
def shell_operation(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows COM integration")
    import pythoncom
    from win32com.shell import shell, shellcon
    file = tmp_path / "synthetic.mp3"
    file.write_bytes(b"test")
    state = {"delete_results": [(0, object())], "result": None, "aborted": False}

    class Operation:
        def SetOperationFlags(self, flags):
            state["flags"] = flags

        def DeleteItem(self, item, sink):
            state["sink"] = sink

        def PerformOperations(self):
            sink = state["sink"]
            flags = shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE
            sink.PreDeleteItem(flags, None)
            for result, receipt in state["delete_results"]:
                sink.PostDeleteItem(flags, None, result, receipt)
            return state["result"]

        def GetAnyOperationsAborted(self):
            return state["aborted"]

    monkeypatch.setattr(pythoncom, "CoCreateInstance", lambda *args: Operation())
    monkeypatch.setattr(pythoncom, "WrapObject", lambda sink, *args: sink)
    monkeypatch.setattr(shell, "SHCreateItemFromParsingName", lambda *args: object())
    return file, state


@pytest.mark.parametrize("success_code", [0, 0x00270008])
@pytest.mark.parametrize("operation_result", [None, 0, 0x00270008])
def test_successful_shell_status_is_not_an_error(shell_operation, success_code, operation_result):
    file, state = shell_operation
    state.update(delete_results=[(success_code, object())], result=operation_result)
    recycle_file(file)
    assert state["sink"].recycled
    assert state["sink"].error is None


def test_informational_callback_does_not_erase_recycle_confirmation(shell_operation):
    file, state = shell_operation
    state["delete_results"] = [(0, object()), (0x00270008, None)]
    recycle_file(file)


@pytest.mark.parametrize("code", [-2147024891, 0x80070005])
def test_failed_item_includes_windows_hresult(shell_operation, code):
    file, state = shell_operation
    state["delete_results"] = [(code, None)]
    with pytest.raises(OSError, match="0x80070005"):
        recycle_file(file)


def test_success_without_recycle_receipt_is_not_accepted(shell_operation):
    file, state = shell_operation
    state["delete_results"] = [(0x00270008, None)]
    with pytest.raises(OSError, match="nicht bestätigt.*0x00270008"):
        recycle_file(file)


def test_aborted_operation_is_reported(shell_operation):
    file, state = shell_operation
    state["aborted"] = True
    with pytest.raises(OSError, match="abgebrochen"):
        recycle_file(file)


@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("RBM_TEST_WINDOWS_RECYCLE") != "1",
                    reason="Opt-in integration test requiring the real Windows Recycle Bin")
def test_real_windows_recycle_from_worker_thread(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    file = tmp_path / "Papierkorb-Test (künstliche Datei).mp3"
    file.write_bytes(b"Synthetic test file; contains no user music.")
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(recycle_file, file).result(timeout=20)
    assert not file.exists()
