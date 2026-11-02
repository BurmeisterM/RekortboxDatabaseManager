"""Recycle-only Windows file operations, with no permanent deletion fallback."""

from pathlib import Path
import sys


def _hresult_failed(value: int | None) -> bool:
    # HRESULT success codes can be positive. Test the severity bit for both
    # signed and unsigned values; pywin32 also returns None for void methods.
    return value is not None and bool(value & 0x80000000)


def recycle_file(path: Path) -> None:
    if sys.platform != "win32":
        raise OSError("Der Windows-Papierkorb steht auf diesem System nicht zur Verfügung.")
    # Import only when used. Missing COM support leaves the music file intact.
    import pythoncom
    from winerror import E_ABORT
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from send2trash.win.IFileOperationProgressSink import FileOperationProgressSink

    class RecycleOnlySink(FileOperationProgressSink):
        recycled = False
        error = None
        delete_result = None
        blocked = False

        def PreDeleteItem(self, flags, item):
            if not flags & shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:
                self.blocked = True
                # Returning a failing HRESULT is insufficient with some pywin32
                # dispatch paths. Raising COMException actively cancels the item.
                raise COMException(desc="Die Datei kann nicht in den Papierkorb verschoben werden.",
                                   scode=E_ABORT)
            return 0

        def PostDeleteItem(self, flags, item, hr_delete, newly_created):
            self.delete_result = hr_delete
            if _hresult_failed(hr_delete):
                self.error = hr_delete
            elif newly_created is not None:
                # Windows can report e.g. COPYENGINE_S_DONT_PROCESS_CHILDREN
                # (0x00270008) for a successful recycle. Keep the receipt if
                # another informational callback follows for the same item.
                self.recycled = True
            return 0

    pythoncom.CoInitialize()
    try:
        operation = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None,
                                              pythoncom.CLSCTX_ALL, shell.IID_IFileOperation)
        operation.SetOperationFlags(shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI |
                                    shellcon.FOF_SILENT | shellcon.FOFX_EARLYFAILURE |
                                    0x20000000 | 0x00080000)  # undo record + recycle on delete
        sink = RecycleOnlySink()
        wrapped = pythoncom.WrapObject(sink, shell.IID_IFileOperationProgressSink)
        item = shell.SHCreateItemFromParsingName(str(path.resolve()), None, shell.IID_IShellItem)
        operation.DeleteItem(item, wrapped)
        result = operation.PerformOperations()
        aborted = operation.GetAnyOperationsAborted()
        if _hresult_failed(result) or aborted or sink.error is not None or not sink.recycled:
            if sink.blocked:
                reason = "Windows bietet für diese Datei keinen Papierkorb an; der Vorgang wurde abgebrochen."
            elif sink.error is not None or _hresult_failed(result):
                code = sink.error if sink.error is not None else result
                reason = f"Windows meldet einen Papierkorb-Fehler (HRESULT 0x{code & 0xFFFFFFFF:08X})."
            elif aborted:
                reason = "Windows hat den Papierkorb-Vorgang abgebrochen."
            else:
                code = sink.delete_result
                status = f" (HRESULT 0x{code & 0xFFFFFFFF:08X})" if code is not None else ""
                reason = f"Windows hat die Verschiebung in den Papierkorb nicht bestätigt{status}."
            raise OSError(reason)
    finally:
        pythoncom.CoUninitialize()
