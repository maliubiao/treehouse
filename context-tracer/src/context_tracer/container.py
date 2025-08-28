"""
Persistent, Encrypted Data Container for Trace Events.

This module provides a robust system for storing trace data captured by the tracer.
It features:
- Asynchronous writing to avoid blocking the traced application.
- Efficient binary serialization using MessagePack.
- Strong AES-GCM encryption for data confidentiality and integrity.
- A FileManager to handle source code paths and dynamic code snippets.
"""

import json
import queue
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import IO, Any, Dict, List, NamedTuple, Optional, Tuple, Union

try:
    import msgpack
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
except ImportError:
    print(
        "Error: 'msgpack' and 'pycryptodome' are required for the data container. "
        "Please run 'pip install msgpack pycryptodome'",
        file=sys.stderr,
    )
    sys.exit(1)

# Constants for the container file format
MAGIC_NUMBER = b"CTXTRACE"
FORMAT_VERSION = 4  # V4: FileManager stored at end of file with pointer in header
HEADER_RESERVED_BYTES = 256  # Reserved space for future header extensions

# V3 Format indices for event data lists
CALL_FUNC_INDEX = 0
CALL_ARGS_INDEX = 1

RETURN_FUNC_INDEX = 0
RETURN_VALUE_INDEX = 1
RETURN_VARS_INDEX = 2

LINE_CONTENT_INDEX = 0
LINE_RAW_INDEX = 1
LINE_VARS_INDEX = 2

EXCEPTION_FUNC_INDEX = 0
EXCEPTION_TYPE_INDEX = 1
EXCEPTION_VALUE_INDEX = 2

C_CALL_FUNC_INDEX = 0
C_CALL_ARG0_INDEX = 1

C_RETURN_FUNC_INDEX = 0
C_RAISE_FUNC_INDEX = 0


class EventType(Enum):
    """Enumeration of trace event types."""

    CALL = 1
    RETURN = 2
    LINE = 3
    EXCEPTION = 4
    C_CALL = 5
    C_RETURN = 6
    C_RAISE = 7


class TraceEvent(NamedTuple):
    """A structured representation of a single trace event."""

    event_type: int  # Corresponds to EventType enum
    timestamp: float
    thread_id: int
    frame_id: int
    file_id: int
    lineno: int
    data: List[Any]  # V3 format uses list-based data


class FileManager:
    """
    Manages the mapping between file paths and unique integer IDs.
    Also handles the storage of dynamically executed code snippets.

    Note: Source file content is now handled by SourceManager for better separation of concerns.
    """

    def __init__(self) -> None:
        self._file_to_id: Dict[str, int] = {}
        self._id_to_file: Dict[int, str] = {}
        self._dynamic_code: Dict[int, str] = {}
        self._next_id = 0

    def get_id(self, path: str, content: Optional[str] = None) -> int:
        """
        Get a unique ID for a file path or dynamic code snippet.

        If content is provided, it's treated as dynamic code and stored internally.
        """
        if path in self._file_to_id:
            return self._file_to_id[path]

        file_id = self._next_id
        self._file_to_id[path] = file_id
        self._id_to_file[file_id] = path
        if content:
            self._dynamic_code[file_id] = content
        self._next_id += 1
        return file_id

    def get_path(self, file_id: int) -> Optional[str]:
        """Retrieve the file path associated with an ID."""
        return self._id_to_file.get(file_id)

    def get_source_lines(self, file_id: int) -> Optional[List[str]]:
        """
        Get the source code for a file ID, split into lines.
        Only handles dynamic code snippets. For regular file source content, use SourceManager.
        """
        if file_id in self._dynamic_code:
            return self._dynamic_code[file_id].splitlines()

        # For regular files, use SourceManager or read directly from disk
        path_str = self.get_path(file_id)
        if path_str:
            try:
                return Path(path_str).read_text(encoding="utf-8").splitlines()
            except (IOError, OSError):
                return None
        return None

    def serialize(self) -> bytes:
        """Serialize the FileManager state to bytes."""
        state = {
            "file_to_id": self._file_to_id,
            "id_to_file": self._id_to_file,
            "dynamic_code": self._dynamic_code,
            "next_id": self._next_id,
        }
        return json.dumps(state).encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> "FileManager":
        """Deserialize bytes to create a FileManager instance."""
        state = json.loads(data.decode("utf-8"))
        instance = cls()
        instance._file_to_id = state["file_to_id"]
        # JSON keys must be strings, so convert IDs back to integers
        instance._id_to_file = {int(k): v for k, v in state["id_to_file"].items()}
        instance._dynamic_code = {int(k): v for k, v in state["dynamic_code"].items()}
        instance._next_id = state["next_id"]
        return instance


class DataContainerWriter:
    """
    Handles the writing of trace events to an encrypted, serialized file.

    This class uses a dedicated thread to perform I/O operations, minimizing
    impact on the main application's performance.
    """

    def __init__(self, file_path: Union[str, Path], key: bytes, file_manager: FileManager, source_manager=None):
        self._file_path = Path(file_path)
        self._key = key
        self._file_manager = file_manager
        self._source_manager = source_manager  # SourceManager for source content
        self._queue: queue.Queue[Optional[TraceEvent]] = queue.Queue(maxsize=10000)
        self._writer_thread: Optional[threading.Thread] = None
        self._running = False
        self._file: Optional[IO[bytes]] = None

    def _encrypt(self, plaintext: bytes) -> bytes:
        """Encrypts a plaintext bytestring using AES-GCM."""
        cipher = AES.new(self._key, AES.MODE_GCM)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext)
        # Prepend nonce and tag for decryption
        return cipher.nonce + tag + ciphertext

    def open(self) -> None:
        """Opens the container file and starts the writer thread."""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._file_path, "wb")
        self._write_header()

        self._running = True
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def _write_header(self) -> None:
        """Writes the container file header with FileManager pointer placeholder."""
        if not self._file:
            return
        # Write magic number and version
        self._file.write(MAGIC_NUMBER)
        self._file.write(FORMAT_VERSION.to_bytes(2, "big"))

        # Write placeholder for FileManager position (8 bytes for 64-bit offset)
        self._file.write(b"\0\0\0\0\0\0\0\0")  # FileManager position placeholder

        # Write reserved bytes for future use
        self._file.write(b"\0" * HEADER_RESERVED_BYTES)

    def add_event(self, event: TraceEvent) -> None:
        """Adds a trace event to the writing queue."""
        if not self._running:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # In a real-world scenario, you might log this or have a strategy
            # to handle a full queue (e.g., dropping events).
            pass

    def _writer_loop(self) -> None:
        """The main loop for the writer thread."""
        while self._running or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.1)
                if event is None:  # Sentinel value to stop
                    break
                self._write_event(event)
            except queue.Empty:
                continue
        self._flush()

    def _write_event(self, event: TraceEvent) -> None:
        """Serializes, encrypts, and writes a single event to the file."""
        if not self._file:
            return
        try:
            # V3 format: full list-based serialization using NamedTuple attributes
            event_list = [
                event.event_type,
                event.timestamp,
                event.thread_id,
                event.frame_id,
                event.file_id,
                event.lineno,
                event.data,  # Now expects a list, not a dict
            ]
            packed_event = msgpack.packb(event_list, use_bin_type=True)
            encrypted_event = self._encrypt(packed_event)

            # Write record length prefix and the encrypted record
            self._file.write(len(encrypted_event).to_bytes(4, "big"))
            self._file.write(encrypted_event)
        except (IOError, OSError) as e:
            print(f"Error writing to trace container: {e}", file=sys.stderr)
            self._running = False  # Stop on I/O error

    def _flush(self) -> None:
        """Flushes the file buffer to disk."""
        if self._file:
            self._file.flush()

    def close(self) -> None:
        """Stops the writer thread and closes the file."""
        if not self._running:
            return
        self._running = False
        # Add sentinel to unblock the writer thread if it's waiting
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass  # The thread will eventually stop on its own

        if self._writer_thread:
            self._writer_thread.join(timeout=2)
        if self._file:
            # Write the FileManager to the end of the file before closing
            self._write_file_manager()
            self._file.close()
            self._file = None

    def _write_file_manager(self) -> None:
        """Writes the FileManager and SourceManager to the end of the file and updates header pointer."""
        if not self._file:
            return

        # Save current position
        current_pos = self._file.tell()

        # Move to end of file to write metadata
        self._file.seek(0, 2)  # Seek to end
        metadata_pos = self._file.tell()

        # Create combined metadata
        metadata = {
            "file_manager": self._file_manager.serialize().decode("utf-8"),
            "source_manager": self._source_manager.serialize().decode("utf-8") if self._source_manager else "",
        }
        metadata_bytes = json.dumps(metadata).encode("utf-8")
        encrypted_metadata = self._encrypt(metadata_bytes)

        # Write metadata
        self._file.write(len(encrypted_metadata).to_bytes(4, "big"))
        self._file.write(encrypted_metadata)

        # Update header with metadata position
        self._file.seek(len(MAGIC_NUMBER) + 2)  # Skip magic and version
        self._file.write(metadata_pos.to_bytes(8, "big"))

        # Restore position
        self._file.seek(current_pos)


class DataContainerReader:
    """Reads and deciphers a trace data container file."""

    def __init__(self, file_path: Union[str, Path], key: bytes):
        self._file_path = Path(file_path)
        self._key = key
        self._file: Optional[IO[bytes]] = None
        self.file_manager: Optional[FileManager] = None
        self.source_manager = None  # SourceManager for source content
        self._format_version: int = 1
        self._metadata_position: int = 0  # For V4+ format (previously _file_manager_position)

    def _decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypts a bytestring using AES-GCM."""
        nonce = ciphertext[:16]
        tag = ciphertext[16:32]
        encrypted_data = ciphertext[32:]
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(encrypted_data, tag)

    def open(self) -> None:
        """Opens the file and reads the header."""
        self._file = open(self._file_path, "rb")

        # Verify magic number and version
        magic = self._file.read(len(MAGIC_NUMBER))
        if magic != MAGIC_NUMBER:
            raise ValueError("Not a valid context tracer file.")
        version = int.from_bytes(self._file.read(2), "big")
        if version > FORMAT_VERSION:
            raise ValueError(
                f"Unsupported format version: {version}. This tool supports up to version {FORMAT_VERSION}."
            )
        self._format_version = version

        if version >= 4:
            # V4+ format: Metadata (FileManager + SourceManager) stored at end with pointer in header
            self._metadata_position = int.from_bytes(self._file.read(8), "big")

            # Skip reserved bytes
            self._file.read(HEADER_RESERVED_BYTES)

            # Read metadata from end of file
            if self._metadata_position > 0:
                current_pos = self._file.tell()
                self._file.seek(self._metadata_position)

                metadata_len = int.from_bytes(self._file.read(4), "big")
                encrypted_metadata = self._file.read(metadata_len)
                metadata_bytes = self._decrypt(encrypted_metadata)
                metadata = json.loads(metadata_bytes.decode("utf-8"))

                # Deserialize FileManager
                fm_data = metadata.get("file_manager", "")
                if fm_data:
                    self.file_manager = FileManager.deserialize(fm_data.encode("utf-8"))
                else:
                    self.file_manager = FileManager()

                # Deserialize SourceManager if available
                sm_data = metadata.get("source_manager", "")
                if sm_data:
                    from .source_manager import SourceManager

                    self.source_manager = SourceManager.deserialize(sm_data.encode("utf-8"))

                # Restore position
                self._file.seek(current_pos)
            else:
                # No metadata (empty container)
                self.file_manager = FileManager()
                self.source_manager = None

    def __iter__(self) -> "DataContainerReader":
        if self._file is None:
            raise RuntimeError("Container must be opened before iteration.")
        return self

    def __next__(self) -> TraceEvent:
        """Reads, decrypts, and returns the next event in the file."""
        if not self._file:
            raise StopIteration

        # For V4 format, check if we've reached the metadata section
        if self._format_version >= 4 and self._metadata_position > 0:
            current_pos = self._file.tell()
            # If we're at the metadata position (end of events), stop iteration
            if current_pos >= self._metadata_position:
                raise StopIteration

        len_bytes = self._file.read(4)
        if not len_bytes:
            raise StopIteration

        record_len = int.from_bytes(len_bytes, "big")
        encrypted_record = self._file.read(record_len)
        if len(encrypted_record) < record_len:
            raise IOError("Incomplete record found at end of file.")

        decrypted_record = self._decrypt(encrypted_record)
        raw_event = msgpack.unpackb(decrypted_record, raw=False)

        # V3 and V4 format: convert list back to NamedTuple for API compatibility
        if self._format_version in (3, 4):
            event = TraceEvent(
                event_type=raw_event[0],
                timestamp=raw_event[1],
                thread_id=raw_event[2],
                frame_id=raw_event[3],
                file_id=raw_event[4],
                lineno=raw_event[5],
                data=raw_event[6],  # This is now a list from V3/V4 format
            )
            return event

        # Unsupported version
        raise TypeError(f"Unsupported format version: {self._format_version}")

    def close(self) -> None:
        """Closes the container file."""
        if self._file:
            self._file.close()
            self._file = None
