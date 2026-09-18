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

    def set_suggested_questions(self, questions_data: List[Dict[str, str]]):
        """Updates suggested questions from agent while preserving user status."""
        with self.lock:
            existing_statuses = {q.question.lower().strip(): q.status for q in self.suggested_questions}
            
            new_questions: List[SuggestedQuestion] = []
            for i, qd in enumerate(questions_data):
                q_text = qd.get("question", "").strip()
                if not q_text:
                    continue
                # If user previously asked or dismissed this question, maintain status
                prev_status = existing_statuses.get(q_text.lower().strip(), "pending")
                new_questions.append(SuggestedQuestion(
                    id=f"q_{int(time.time())}_{i}",
                    question=q_text,
                    rationale=qd.get("rationale", ""),
                    status=prev_status
                ))
            
            self.suggested_questions = new_questions

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
