import time
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class TranscriptTurn:
    turn_id: int
    channel: str           # "you", "participants", "room"
    speaker_label: str     # "[You]", "[Participants]", "[Turn 1]"
    text: str
    timestamp: float
    formatted_time: str

@dataclass
class SuggestedQuestion:
    id: str
    question: str
    rationale: str = ""
    status: str = "pending"  # "pending", "asked", "dismissed"
    created_at: float = field(default_factory=time.time)

class CopilotMemory:
    """Thread-safe context buffer managing transcript history and interactive scratchpad."""

    def __init__(self, max_history_seconds: float = 240.0):
        self.max_history_seconds = max_history_seconds
        self.lock = threading.Lock()
        
        # Chronological transcript turns
        self.turns: List[TranscriptTurn] = []
        
        # Interactive Scratchpad State
        self.suggested_questions: List[SuggestedQuestion] = []
        self.live_notes: List[str] = []
        self.action_items: List[Dict[str, Any]] = []

    def add_transcript(self, channel: str, text: str, timestamp: float, turn_id: int) -> TranscriptTurn:
        """Appends a new transcribed turn to memory."""
        time_str = time.strftime("%I:%M:%S %p", time.localtime(timestamp))
        
        if channel == "you":
            label = "[You]"
        elif channel == "participants":
            label = "[Call Participants]"
        elif channel == "room":
            label = f"[Room • Turn {turn_id}]"
        else:
            label = f"[{channel.capitalize()}]"

        turn = TranscriptTurn(
            turn_id=turn_id,
            channel=channel,
            speaker_label=label,
            text=text.strip(),
            timestamp=timestamp,
            formatted_time=time_str
        )

        with self.lock:
            self.turns.append(turn)
            # Prune turns older than max_history_seconds if history gets very long
            now = time.time()
            if len(self.turns) > 100:
                cutoff = now - (self.max_history_seconds * 2)
                self.turns = [t for t in self.turns if t.timestamp >= cutoff]

        return turn

    def get_recent_transcript(self, seconds: float = 180.0) -> str:
        """Returns the formatted transcript of the last N seconds."""
        now = time.time()
        cutoff = now - seconds
        with self.lock:
            recent = [t for t in self.turns if t.timestamp >= cutoff]
            if not recent:
                # If nothing in window, return the last 3 turns if available
                recent = self.turns[-3:] if self.turns else []
            
            lines = [f"{t.speaker_label} ({t.formatted_time}): {t.text}" for t in recent]
            return "\n".join(lines)

    def get_all_transcript(self) -> str:
        """Returns the full chronological transcript of the session."""
        with self.lock:
            lines = [f"{t.speaker_label} ({t.formatted_time}): {t.text}" for t in self.turns]
            return "\n".join(lines)

    # --- Scratchpad Mutators (Interactive) ---

    def set_suggested_questions(self, questions_data: List[Any]):
        """Accumulates suggested questions from agent while preventing duplicates and preserving user status."""
        with self.lock:
            # Map normalized existing question texts to their index in self.suggested_questions
            existing_map = {}
            for idx, q in enumerate(self.suggested_questions):
                norm_key = q.question.strip().lower().rstrip("?").rstrip(".")
                existing_map[norm_key] = idx

            for i, qd in enumerate(questions_data):
                if isinstance(qd, dict):
                    q_text = qd.get("question", "").strip()
                    rationale = qd.get("rationale", "")
                elif isinstance(qd, str):
                    q_text = qd.strip()
                    rationale = ""
                else:
                    continue

                if not q_text:
                    continue

                norm_key = q_text.lower().rstrip("?").rstrip(".")
                if norm_key in existing_map:
                    # Question already exists (pending, asked, or dismissed) - retain it
                    continue

                # New question: append with pending status
                new_q = SuggestedQuestion(
                    id=f"q_{int(time.time())}_{len(self.suggested_questions)}_{i}",
                    question=q_text,
                    rationale=rationale,
                    status="pending"
                )
                self.suggested_questions.append(new_q)
                existing_map[norm_key] = len(self.suggested_questions) - 1

            # Cap total stored questions to 100 to prevent unbounded memory in very long calls
            if len(self.suggested_questions) > 100:
                # Keep pending questions, prune oldest dismissed/asked
                pending = [q for q in self.suggested_questions if q.status == "pending"]
                non_pending = [q for q in self.suggested_questions if q.status != "pending"]
                self.suggested_questions = pending + non_pending[-40:]

    def clear_suggested_questions(self, status: Optional[str] = None):
        """Clears suggested questions, optionally filtering by status (e.g. 'pending')."""
        with self.lock:
            if status:
                self.suggested_questions = [q for q in self.suggested_questions if q.status != status]
            else:
                self.suggested_questions.clear()

    def mark_question_asked(self, question_text: str):
        """Marks a question as asked by the user, moving it into notes context."""
        with self.lock:
            for q in self.suggested_questions:
                if q.question.strip() == question_text.strip():
                    q.status = "asked"
                    break
            # Add to notes as resolved
            clean_q = question_text.strip()
            if not any(clean_q in note for note in self.live_notes):
                self.live_notes.append(f"[Asked] {clean_q}")

    def mark_question_dismissed(self, question_text: str):
        """Dismisses a question from suggestions."""
        with self.lock:
            for q in self.suggested_questions:
                if q.question.strip() == question_text.strip():
                    q.status = "dismissed"
                    break

    def update_live_notes(self, notes: List[str]):
        """Replaces or updates the running live notes."""
        with self.lock:
            self.live_notes = [n.strip() for n in notes if n.strip()]

    def add_user_note(self, note: str):
        """Appends a user-written custom note."""
        with self.lock:
            self.live_notes.append(note.strip())

    def get_scratchpad_markdown(self) -> str:
        """Serializes current scratchpad to clean Markdown."""
        with self.lock:
            md_lines = ["### 💡 Key Takeaways & Live Notes"]
            if self.live_notes:
                for note in self.live_notes:
                    md_lines.append(f"- {note}")
            else:
                md_lines.append("*No notes recorded yet.*")

            md_lines.append("\n### ❓ Addressed & Outstanding Questions")
            pending_q = [q for q in self.suggested_questions if q.status == "pending"]
            asked_q = [q for q in self.suggested_questions if q.status == "asked"]

            if asked_q:
                md_lines.append("**Asked / Clarified:**")
                for q in asked_q:
                    md_lines.append(f"- [x] {q.question}")

            if pending_q:
                md_lines.append("**Outstanding / Follow-up:**")
                for q in pending_q:
                    md_lines.append(f"- [ ] {q.question}")

            return "\n".join(md_lines)

    def get_prompt_context(self) -> str:
        """Builds structured context block for the LLM agent."""
        recent_tx = self.get_recent_transcript(seconds=180.0)
        scratchpad_md = self.get_scratchpad_markdown()
        
        return f"""=== RECENT CONVERSATION (Last 2-3 Minutes) ===
{recent_tx or '[No recent speech recorded]'}

=== CURRENT MEETING SCRATCHPAD & ADDRESSED POINTS ===
{scratchpad_md}
"""

    def clear(self):
        """Clears memory for a new session."""
        with self.lock:
            self.turns.clear()
            self.suggested_questions.clear()
            self.live_notes.clear()
            self.action_items.clear()
