import os
import re
import glob
import threading
from pathlib import Path
from typing import Dict, List, Set, Optional, Any

class DynamicDomainCorpus:
    """Mines historical meeting notes, transcripts, and tags to build a personalized technical lexicon."""

    _instance: Optional["DynamicDomainCorpus"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._lexicon: Dict[str, int] = {}
        self._historical_topics: List[str] = []
        self._synced_tags: Set[str] = set()
        self._scanned = False
        self._rw_lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "DynamicDomainCorpus":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def scan_historical_notes(self, recordings_dir: Path, extra_tags: Optional[List[str]] = None) -> None:
        """Asynchronously scans local markdown meeting notes and server tags to extract domain terms."""
        def _bg_scan():
            with self._rw_lock:
                if extra_tags:
                    for t in extra_tags:
                        t_clean = t.strip().lower()
                        if t_clean:
                            self._synced_tags.add(t_clean)
                            self._lexicon[t_clean] = self._lexicon.get(t_clean, 0) + 10

                if not recordings_dir or not recordings_dir.exists():
                    self._scanned = True
                    return

                try:
                    md_files = list(recordings_dir.glob("*.md"))
                    for md_file in md_files:
                        try:
                            with open(md_file, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            self._extract_terms_from_markdown(content)
                        except Exception:
                            continue
                except Exception as e:
                    print(f"[Corpus] Error scanning notes: {e}")

                self._scanned = True

        threading.Thread(target=_bg_scan, daemon=True).start()

    def _extract_terms_from_markdown(self, content: str) -> None:
        """Extracts topics, acronyms, and technical phrases from markdown meeting notes."""
        lines = content.splitlines()
        for line in lines:
            line_str = line.strip()
            # Extract topics and agendas
            if line_str.startswith("CURRENT AGENDA:") or line_str.startswith("### ") or line_str.startswith("🔹 "):
                cleaned = re.sub(r'^(?:CURRENT AGENDA:|###|🔹|\*|-)\s*', '', line_str).strip()
                cleaned = re.sub(r'\s*\((?:In Progress|Completed|Discussion)\)', '', cleaned, flags=re.IGNORECASE).strip()
                if cleaned and len(cleaned) > 3 and cleaned not in self._historical_topics:
                    self._historical_topics.append(cleaned)
                    # Index words in the topic
                    for word in re.findall(r'\b[a-zA-Z0-9_\-\.]{3,}\b', cleaned):
                        w_low = word.lower()
                        self._lexicon[w_low] = self._lexicon.get(w_low, 0) + 5

            # Extract acronyms (e.g. RBAC, GPO, MSI, SCCM, Intune)
            acronyms = re.findall(r'\b[A-Z0-9]{2,6}\b', line_str)
            for ac in acronyms:
                ac_low = ac.lower()
                self._lexicon[ac_low] = self._lexicon.get(ac_low, 0) + 2

    def get_domain_score(self, term: str) -> int:
        """Returns the frequency score of a term in the historical domain lexicon."""
        with self._rw_lock:
            return self._lexicon.get(term.lower().strip(), 0)

    def is_known_domain_term(self, term: str) -> bool:
        """Checks if a term appears in historical tags, notes, or topics."""
        with self._rw_lock:
            t = term.lower().strip()
            return t in self._lexicon or t in self._synced_tags

    def get_frequent_topics(self, limit: int = 10) -> List[str]:
        """Returns the most recent or frequent topic headings mined from past notes."""
        with self._rw_lock:
            return self._historical_topics[-limit:]
