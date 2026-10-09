import time
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class TranscriptTurn:
    turn_id: int
    channel: str           # "you", "participants", "room"
    speaker_label: str     # "[You]", "[Call Participants]", "[Room • Turn 1]"
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

@dataclass
class FollowUpItem:
    id: str
    task: str
    owner: str = "Unassigned"
    status: str = "pending"  # "pending", "done", "dismissed"
    created_at: float = field(default_factory=time.time)

class CopilotMemory:
    """Thread-safe context buffer managing transcript history, rolling summary, questions, and action items."""

    def __init__(self, max_history_seconds: float = 240.0):
        self.max_history_seconds = max_history_seconds
        self.lock = threading.Lock()
        
        # Chronological transcript turns
        self.turns: List[TranscriptTurn] = []
        
        # Structured Intelligence State
        self.rolling_summary: Dict[str, Any] = {
            "topic": "",
            "topics": [],
            "summary_bullets": [],
            "executive_summary": "",
            "key_decisions": []
        }
        self.suggested_questions: List[SuggestedQuestion] = []
        self.follow_up_suggestions: List[FollowUpItem] = []
        self.user_notes: List[str] = []
        
        # Backwards compatibility alias for tests/code checking live_notes
        self.live_notes: List[str] = self.user_notes

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
            if len(self.turns) > 120:
                cutoff = now - (self.max_history_seconds * 2.5)
                self.turns = [t for t in self.turns if t.timestamp >= cutoff]

        return turn

    def get_recent_transcript(self, seconds: float = 180.0) -> str:
        """Returns the formatted transcript of the last N seconds."""
        now = time.time()
        cutoff = now - seconds
        with self.lock:
            recent = [t for t in self.turns if t.timestamp >= cutoff]
            if not recent:
                recent = self.turns[-4:] if self.turns else []
            
            lines = [f"{t.speaker_label} ({t.formatted_time}): {t.text}" for t in recent]
            return "\n".join(lines)

    def get_all_transcript(self) -> str:
        """Returns the full chronological transcript of the session."""
        with self.lock:
            lines = [f"{t.speaker_label} ({t.formatted_time}): {t.text}" for t in self.turns]
            return "\n".join(lines)

    # --- Rolling Summary Mutators ---

    def set_rolling_summary(self, summary_data: Dict[str, Any]):
        """Updates rolling executive summary and key decisions with accumulating rolling topic and bullet updates."""
        with self.lock:
            if not isinstance(summary_data, dict):
                return
            topic = summary_data.get("topic", "").strip()
            exec_sum = summary_data.get("executive_summary", "").strip()
            incoming_bullets = summary_data.get("summary_bullets", [])
            incoming_topics = summary_data.get("topics", [])
            decisions = summary_data.get("key_decisions", [])
            
            if topic:
                self.rolling_summary["topic"] = topic

            # 1. Accumulate and update Topic Cards
            if isinstance(incoming_topics, list) and incoming_topics:
                current_topics = self.rolling_summary.setdefault("topics", [])
                for it in incoming_topics:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("title", "").strip()
                    if not title:
                        continue
                    summary = it.get("summary", "").strip()
                    status = it.get("status", "in_progress").strip()
                    key_points = [p.strip() for p in it.get("key_points", []) if isinstance(p, str) and p.strip()]

                    # Check if matching topic already exists
                    matched = None
                    title_norm = title.lower()
                    for existing in current_topics:
                        existing_norm = existing.get("title", "").lower()
                        if title_norm in existing_norm or existing_norm in title_norm:
                            matched = existing
                            break

                    if matched:
                        if summary:
                            matched["summary"] = summary
                        if status:
                            matched["status"] = status
                        if key_points:
                            existing_pts = set(matched.get("key_points", []))
                            for kp in key_points:
                                if kp not in existing_pts:
                                    matched.setdefault("key_points", []).append(kp)
                                    existing_pts.add(kp)
                    else:
                        current_topics.append({
                            "title": title,
                            "summary": summary,
                            "status": status,
                            "key_points": key_points
                        })

                if len(current_topics) > 12:
                    self.rolling_summary["topics"] = current_topics[-12:]

                if not topic and current_topics:
                    self.rolling_summary["topic"] = current_topics[-1]["title"]

            # 2. Ensure summary_bullets list exists
            current_bullets = self.rolling_summary.setdefault("summary_bullets", [])
            
            # Accumulate and roll forward synthesized bullet points
            if isinstance(incoming_bullets, list) and incoming_bullets:
                existing_norms = {b.strip().lower().rstrip(".") for b in current_bullets if isinstance(b, str)}
                for b in incoming_bullets:
                    if isinstance(b, str) and b.strip():
                        b_clean = b.strip()
                        norm = b_clean.lower().rstrip(".")
                        if norm not in existing_norms:
                            current_bullets.append(b_clean)
                            existing_norms.add(norm)
            elif exec_sum and not current_bullets:
                current_bullets.append(exec_sum)
            
            # Cap rolling bullet history
            if len(current_bullets) > 25:
                self.rolling_summary["summary_bullets"] = current_bullets[-25:]

            # Keep executive_summary string synchronized for backward compatibility
            if exec_sum:
                self.rolling_summary["executive_summary"] = exec_sum
            elif self.rolling_summary["summary_bullets"]:
                self.rolling_summary["executive_summary"] = " ".join(self.rolling_summary["summary_bullets"][-3:])
            
            if isinstance(decisions, list):
                clean_decisions = []
                for d in decisions:
                    if isinstance(d, str) and d.strip():
                        clean_decisions.append(d.strip())
                if clean_decisions:
                    # Accumulate unique decisions
                    existing_dec = set(self.rolling_summary.get("key_decisions", []))
                    for cd in clean_decisions:
                        if cd not in existing_dec:
                            self.rolling_summary.setdefault("key_decisions", []).append(cd)
                            existing_dec.add(cd)

    # --- Questions Mutators ---

    def set_suggested_questions(self, questions_data: List[Any]):
        """Accumulates suggested questions from agent while preventing duplicates and preserving user status."""
        with self.lock:
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
                    continue

                new_q = SuggestedQuestion(
                    id=f"q_{int(time.time())}_{len(self.suggested_questions)}_{i}",
                    question=q_text,
                    rationale=rationale,
                    status="pending"
                )
                self.suggested_questions.append(new_q)
                existing_map[norm_key] = len(self.suggested_questions) - 1

            # Cap total stored questions to prevent unbounded growth in very long calls
            if len(self.suggested_questions) > 100:
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
        """Marks a question as asked by the user."""
        with self.lock:
            for q in self.suggested_questions:
                if q.question.strip() == question_text.strip():
                    q.status = "asked"
                    break

    def mark_question_dismissed(self, question_text: str):
        """Dismisses a question from suggestions."""
        with self.lock:
            for q in self.suggested_questions:
                if q.question.strip() == question_text.strip():
                    q.status = "dismissed"
                    break

    # --- Follow-up Suggestions & Action Items Mutators ---

    def set_follow_up_suggestions(self, items_data: List[Any]):
        """Accumulates follow-up suggestions and action items while preventing duplicates."""
        with self.lock:
            existing_map = {}
            for idx, item in enumerate(self.follow_up_suggestions):
                norm_key = item.task.strip().lower().rstrip(".")
                existing_map[norm_key] = idx

            for i, it in enumerate(items_data):
                if isinstance(it, dict):
                    task_text = it.get("task", it.get("action", "")).strip()
                    owner = it.get("owner", "Unassigned").strip() or "Unassigned"
                elif isinstance(it, str):
                    task_text = it.strip()
                    owner = "Unassigned"
                else:
                    continue

                if not task_text:
                    continue

                norm_key = task_text.lower().rstrip(".")
                if norm_key in existing_map:
                    continue

                new_item = FollowUpItem(
                    id=f"f_{int(time.time())}_{len(self.follow_up_suggestions)}_{i}",
                    task=task_text,
                    owner=owner,
                    status="pending"
                )
                self.follow_up_suggestions.append(new_item)
                existing_map[norm_key] = len(self.follow_up_suggestions) - 1

            if len(self.follow_up_suggestions) > 100:
                pending = [f for f in self.follow_up_suggestions if f.status == "pending"]
                non_pending = [f for f in self.follow_up_suggestions if f.status != "pending"]
                self.follow_up_suggestions = pending + non_pending[-40:]

    def clear_follow_up_suggestions(self, status: Optional[str] = None):
        """Clears follow-ups, optionally filtering by status."""
        with self.lock:
            if status:
                self.follow_up_suggestions = [f for f in self.follow_up_suggestions if f.status != status]
            else:
                self.follow_up_suggestions.clear()

    def mark_followup_done(self, task_text: str):
        """Marks an action item as completed."""
        with self.lock:
            for f in self.follow_up_suggestions:
                if f.task.strip() == task_text.strip():
                    f.status = "done"
                    break

    def mark_followup_dismissed(self, task_text: str):
        """Dismisses an action item suggestion."""
        with self.lock:
            for f in self.follow_up_suggestions:
                if f.task.strip() == task_text.strip():
                    f.status = "dismissed"
                    break

    # --- Custom User Notes Mutators ---

    def add_user_note(self, note: str):
        """Appends a user-written custom note."""
        with self.lock:
            cleaned = note.strip()
            if cleaned:
                self.user_notes.append(cleaned)
                if self.user_notes is not self.live_notes:
                    self.live_notes.append(cleaned)

    def update_live_notes(self, notes: List[str]):
        """Legacy helper updating user notes."""
        with self.lock:
            self.user_notes = [n.strip() for n in notes if n.strip()]
            self.live_notes = self.user_notes

    # --- Markdown & Context Serialization ---

    def get_scratchpad_markdown(self) -> str:
        """Serializes current meeting intelligence to clean, structured Markdown.
        
        Checkboxes are strictly used for Action Items & Follow-ups.
        """
        with self.lock:
            md_lines = ["# 📝 Meeting Summary & Live Intelligence\n"]
            
            # 1. Topic & Executive Summary
            topic = self.rolling_summary.get("topic", "")
            topics_list = self.rolling_summary.get("topics", [])
            bullets = self.rolling_summary.get("summary_bullets", [])
            exec_sum = self.rolling_summary.get("executive_summary", "")
            if topic:
                md_lines.append(f"**Topic:** {topic}\n")
            
            md_lines.append("## 📌 Executive Summary")
            if topics_list:
                for top in topics_list:
                    status_badge = f" *({top.get('status', 'in_progress').replace('_', ' ').title()})*" if top.get('status') else ""
                    md_lines.append(f"### 🔹 {top.get('title', 'Discussion Topic')}{status_badge}")
                    if top.get("summary"):
                        md_lines.append(f"{top['summary']}\n")
                    for kp in top.get("key_points", []):
                        md_lines.append(f"- {kp}")
                    md_lines.append("")
            elif bullets:
                for b in bullets:
                    md_lines.append(f"- {b}")
                md_lines.append("")
            elif exec_sum:
                md_lines.append(f"{exec_sum}\n")
            else:
                md_lines.append("*Summary will synthesize as discussion progresses.*\n")

            # 2. Key Decisions
            decisions = self.rolling_summary.get("key_decisions", [])
            if decisions:
                md_lines.append("## 🎯 Key Decisions")
                for d in decisions:
                    md_lines.append(f"- {d}")
                md_lines.append("")

            # 3. Action Items & Follow-ups (Checkboxes strictly here)
            pending_acts = [f for f in self.follow_up_suggestions if f.status == "pending"]
            done_acts = [f for f in self.follow_up_suggestions if f.status == "done"]
            
            if pending_acts or done_acts:
                md_lines.append("## 📋 Action Items & Follow-ups")
                for item in done_acts:
                    owner_tag = f" (@{item.owner})" if item.owner and item.owner != "Unassigned" else ""
                    md_lines.append(f"- [x] {item.task}{owner_tag}")
                for item in pending_acts:
                    owner_tag = f" (@{item.owner})" if item.owner and item.owner != "Unassigned" else ""
                    md_lines.append(f"- [ ] {item.task}{owner_tag}")
                md_lines.append("")

            # 4. Asked Questions (for record)
            asked_q = [q for q in self.suggested_questions if q.status == "asked"]
            if asked_q:
                md_lines.append("## 💡 Questions Asked During Meeting")
                for q in asked_q:
                    md_lines.append(f"- {q.question}")
                md_lines.append("")

            # 5. User Custom Notes
            if self.user_notes:
                md_lines.append("## ✍️ Custom Notes")
                for note in self.user_notes:
                    md_lines.append(f"- {note}")
                md_lines.append("")

            return "\n".join(md_lines)

    def get_prompt_context(self) -> str:
        """Builds structured context block for the LLM agent."""
        recent_tx = self.get_recent_transcript(seconds=240.0)
        scratchpad_md = self.get_scratchpad_markdown()
        
        with self.lock:
            already_addressed_q = [
                q.question for q in self.suggested_questions if q.status in ("asked", "dismissed")
            ]
            already_addressed_f = [
                f.task for f in self.follow_up_suggestions if f.status in ("done", "dismissed")
            ]
        
        addressed_q_str = "\n".join(f"- {q}" for q in already_addressed_q) if already_addressed_q else "None."
        addressed_f_str = "\n".join(f"- {f}" for f in already_addressed_f) if already_addressed_f else "None."

        return f"""=== RECENT DIALOGUE TURNS (Note: '[You]' is the user; '[Call Participants]' are remote speakers) ===
{recent_tx or '[No speech recorded in active window]'}

=== PREVIOUSLY ASKED / DISMISSED QUESTIONS (DO NOT RE-SUGGEST) ===
{addressed_q_str}

=== PREVIOUSLY COMPLETED / DISMISSED ACTION ITEMS (DO NOT RE-SUGGEST) ===
{addressed_f_str}

=== CURRENT MEETING SUMMARY & CONTEXT ===
{scratchpad_md}
"""

    def clear(self):
        """Clears memory for a new session."""
        with self.lock:
            self.turns.clear()
            self.rolling_summary = {
                "topic": "",
                "topics": [],
                "summary_bullets": [],
                "executive_summary": "",
                "key_decisions": []
            }
            self.suggested_questions.clear()
            self.follow_up_suggestions.clear()
            self.user_notes.clear()
            self.live_notes.clear()
