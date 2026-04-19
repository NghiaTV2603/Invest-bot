"""V2 memory layer.

5-layer persistent memory + FTS5 cross-session search. See PLAN_V2.md §4.

Public API — the rest of the codebase must go through this module, never
touch ~/.vnstock-bot/memory/*.md or events_fts directly.
"""

from __future__ import annotations

from vnstock_bot.memory.compression import compress_context
from vnstock_bot.memory.events import (
    get_timeline,
    record_event,
)
from vnstock_bot.memory.patterns import extract_and_persist as extract_patterns
from vnstock_bot.memory.files import (
    delete_memory_file,
    list_memory_files,
    read_memory_file,
    write_memory_file,
)
from vnstock_bot.memory.recall import (
    MemoryHit,
    recall_similar_decision,
    search_memory,
)
from vnstock_bot.memory.types import (
    Event,
    EventKind,
    MemoryFile,
    MemoryLayer,
    Pattern,
    Summary,
    SummaryScope,
)

__all__ = [
    # Events (L1)
    "record_event",
    "get_timeline",
    "Event",
    "EventKind",
    # Files (L2 user_prefs / L4 project / L4 reference)
    "read_memory_file",
    "write_memory_file",
    "list_memory_files",
    "delete_memory_file",
    "MemoryFile",
    "MemoryLayer",
    # Summaries (L3) / Patterns (L4 observed)
    "Summary",
    "SummaryScope",
    "Pattern",
    # Search / recall
    "search_memory",
    "recall_similar_decision",
    "MemoryHit",
    # Compression
    "compress_context",
    # Patterns (L4 writer)
    "extract_patterns",
]
