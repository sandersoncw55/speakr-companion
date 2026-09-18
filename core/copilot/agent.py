import json
import time
import re
import threading
import httpx
from typing import Optional, Callable, Dict, Any, List
from core.copilot.memory import CopilotMemory, TranscriptTurn
from core.copilot.prompts import (
    get_periodic_prompt,
    DEFAULT_QUICK_PROMPTS,
    BASE_SYSTEM_PROMPT
)

class OfflineExtractiveEngine:
    """Zero-dependency, 100% offline heuristic intelligence engine.
    
    Extracts questions, commitments, risks, and summaries from local transcript turns
    without requiring any cloud API keys or external services.
    """

    ACTION_KEYWORDS = [
        "action item", "will do", "need to", "going to", "follow up", 
        "send", "review", "schedule", "assign", "check with", "make sure",
        "i'll", "we'll", "take care of", "look into", "set up"
    ]
    
    RISK_KEYWORDS = [
        "risk", "delay", "issue", "problem", "blocker", "blocked", "fail", 
        "failed", "bug", "crash", "uncertain", "not sure", "concern",
        "bottleneck", "timeout", "latency", "regression"
    ]

    def generate_periodic(self, turns: List[TranscriptTurn], live_notes: List[str]) -> Dict[str, Any]:
        """Synthesizes questions, live notes, and action items from recent turns."""
        if not turns:
            return {"suggested_questions": [], "live_notes": [], "action_items": []}

        # Analyze the most recent window of turns (last ~10 turns)
        recent_turns = turns[-12:]
        
        extracted_questions = []
        action_items = []
        key_statements = []

        for turn in recent_turns:
            text = turn.text.strip()
            speaker = turn.speaker_label
            sentences = re.split(r'(?<=[.?!])\s+', text)
            
            for s in sentences:
                s_clean = s.strip()
                if not s_clean:
                    continue
                s_lower = s_clean.lower()
                
                # Check for questions asked in conversation
                if s_clean.endswith("?") or any(s_lower.startswith(w) for w in ["who ", "what ", "where ", "when ", "why ", "how ", "can we ", "should we ", "could you "]):
                    if len(s_clean) > 10 and s_clean not in extracted_questions:
                        extracted_questions.append(s_clean)

                # Check for action items
                if any(kw in s_lower for kw in self.ACTION_KEYWORDS):
                    action_fmt = f"[{speaker}] {s_clean}"
                    if action_fmt not in action_items:
                        action_items.append(action_fmt)

                # Collect substantive statements for notes
                if len(s_clean) > 25 and not s_clean.endswith("?"):
                    key_statements.append((speaker, s_clean))

        # Formulate suggested questions
        suggested_questions = []
        
        # 1. Follow up on any unanswered question from dialogue
        for eq in extracted_questions[:2]:
            suggested_questions.append(f"Follow up: {eq}")
            
        # 2. Contextual questions based on actions / commitments
        if action_items and len(suggested_questions) < 3:
            suggested_questions.append("What is the expected timeline and priority for these action items?")
            
        # 3. Ownership / Blocker check
        if len(suggested_questions) < 3:
            suggested_questions.append("Who is the primary owner for the next milestone?")
        if len(suggested_questions) < 3:
            suggested_questions.append("Are there any technical dependencies or blockers?")

        # Formulate live notes from key statements
        notes = []
        for speaker, stmt in key_statements[-4:]:
            # Format as concise note
            note_str = f"[{speaker}] {stmt}"
            if note_str not in notes and note_str not in live_notes:
                notes.append(note_str)

        return {
            "suggested_questions": suggested_questions[:3],
            "live_notes": notes[:3],
            "action_items": action_items[:4]
        }

    def generate_quick_action(self, prompt_key_or_text: str, turns: List[TranscriptTurn]) -> str:
        """Processes quick action triggers offline."""
        if not turns:
            return "No transcript turns captured yet. Speak or play meeting audio to analyze."

        p_lower = prompt_key_or_text.lower()
        recent_turns = turns[-15:]

        if "catch" in p_lower or "summarize" in p_lower:
            # Catch up / summarize last 2 mins
            lines = ["⏱️ **Recent Meeting Summary:**\n"]
            for t in recent_turns[-8:]:
                lines.append(f"• **{t.speaker_label}** ({t.formatted_time}): {t.text}")
            return "\n".join(lines)

        elif "ask" in p_lower or "what_to_ask" in p_lower:
            # What to ask right now
            periodic = self.generate_periodic(turns, [])
            q_list = periodic.get("suggested_questions", [])
            lines = ["💡 **Suggested Questions for Right Now:**\n"]
            for i, q in enumerate(q_list, 1):
                lines.append(f"{i}. {q}")
            return "\n".join(lines)

        elif "owner" in p_lower or "clarify_ownership" in p_lower:
            # Clarify ownership
            actions = []
            for t in recent_turns:
                for kw in self.ACTION_KEYWORDS:
                    if kw in t.text.lower():
                        actions.append(f"• **{t.speaker_label}**: \"{t.text}\"")
                        break
            if actions:
                return "🎯 **Action & Ownership Points:**\n\n" + "\n".join(actions[-5:]) + "\n\n*Recommendation: Confirm assigned owners and due dates for above points.*"
            else:
                return "🎯 **Ownership Check:** No explicit task assignments detected in recent turns. Consider asking: *'Who has the action item to drive this forward?'*"

        elif "risk" in p_lower or "spot_risks" in p_lower:
            # Spot risks
            risks = []
            for t in recent_turns:
                for kw in self.RISK_KEYWORDS:
                    if kw in t.text.lower():
                        risks.append(f"• **{t.speaker_label}**: \"{t.text}\" (flag: *{kw}*)")
                        break
            if risks:
                return "🚩 **Potential Risks & Roadblocks Flagged:**\n\n" + "\n".join(risks[-5:])
            else:
                return "🚩 **Risk Assessment:** No immediate risks or blockers flagged in recent dialogue turns."

        else:
            # Custom write-in query: keyword search across turns
            query_words = [w for w in re.findall(r'\w+', p_lower) if len(w) > 2]
            matched = []
            for t in turns:
                t_lower = t.text.lower()
                if any(qw in t_lower for qw in query_words):
                    matched.append(f"• **{t.speaker_label}** ({t.formatted_time}): {t.text}")

            if matched:
                return f"🔍 **Mentions relevant to '{prompt_key_or_text}':**\n\n" + "\n".join(matched[-6:])
            else:
                # Fallback to recent context
                lines = [f"🔍 No exact keyword match for '{prompt_key_or_text}'. Recent context:\n"]
                for t in recent_turns[-4:]:
                    lines.append(f"• **{t.speaker_label}**: {t.text}")
                return "\n".join(lines)


class CopilotAgent:
    """Intelligent reasoning engine running periodic analysis and instant quick prompts."""

    def __init__(
        self,
        memory: CopilotMemory,
        on_results_callback: Callable[[Dict[str, Any]], None],
        cadence_seconds: float = 35.0
    ):
        self.memory = memory
        self.on_results_callback = on_results_callback
        self.cadence_seconds = cadence_seconds
        self.offline_engine = OfflineExtractiveEngine()
        
        # Configuration
        self.llm_provider = "offline"  # "offline", "openrouter", "gemini", "ollama"
        self.api_key = ""
        self.model_name = "openai/gpt-4o-mini"
        self.custom_endpoint: Optional[str] = None
        self.privacy_mode = False  # If True, enforces local Ollama or offline fallback
        self.active_tag: Optional[str] = None

        # State tracking
        self.last_analyzed_turn_id = 0
        self.is_running = False
        self.is_analyzing = False
        self.timer_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def configure(
        self,
        provider: str = "openrouter",
        api_key: str = "",
        model_name: str = "openai/gpt-4o-mini",
        custom_endpoint: Optional[str] = None,
        privacy_mode: bool = False,
        active_tag: Optional[str] = None
    ):
        """Updates agent LLM parameters and privacy state."""
        with self.lock:
            self.llm_provider = provider
            self.api_key = api_key
            self.model_name = model_name
            self.custom_endpoint = custom_endpoint
            self.privacy_mode = privacy_mode
            self.active_tag = active_tag

    def start(self):
        """Starts periodic analysis background loop."""
        if self.is_running:
            return
        self.is_running = True
        self.timer_thread = threading.Thread(target=self._periodic_loop, daemon=True)
        self.timer_thread.start()
        print("[CopilotAgent] Periodic analysis agent started.")

    def stop(self):
        """Stops agent background loop."""
        self.is_running = False

    def _periodic_loop(self):
        """Timer loop firing background analysis on cadence."""
        last_check_time = time.time()
        while self.is_running:
            time.sleep(1.0)
            now = time.time()
            if now - last_check_time >= self.cadence_seconds:
                last_check_time = now
                # Check if there are new turns
                latest_turns = self.memory.turns
                if latest_turns and latest_turns[-1].turn_id > self.last_analyzed_turn_id:
                    self.last_analyzed_turn_id = latest_turns[-1].turn_id
                    threading.Thread(target=self._run_periodic_analysis, daemon=True).start()

    def _is_offline_mode(self) -> bool:
        """Determines if offline fallback should be used."""
        if self.llm_provider == "offline":
            return True
        if self.privacy_mode and self.llm_provider != "ollama":
            return True
        if self.llm_provider in ("openrouter", "gemini") and not self.api_key:
            return True
        return False

    def _run_periodic_analysis(self):
        """Executes periodic background evaluation."""
        if self.is_analyzing:
            return
        self.is_analyzing = True
        try:
            if self._is_offline_mode():
                response_json = self.offline_engine.generate_periodic(
                    self.memory.turns, self.memory.live_notes
                )
            else:
                try:
                    prompt_context = self.memory.get_prompt_context()
                    system_prompt = get_periodic_prompt(self.active_tag)
                    response_json = self._call_llm(
                        system_prompt=system_prompt,
                        user_content=prompt_context,
                        require_json=True
                    )
                except Exception as ex:
                    print(f"[CopilotAgent] Online analysis failed ({ex}), falling back to offline engine.")
                    response_json = self.offline_engine.generate_periodic(
                        self.memory.turns, self.memory.live_notes
                    )
            
            if response_json and isinstance(response_json, dict):
                # Update memory
                q_list = response_json.get("suggested_questions", [])
                if q_list:
                    self.memory.set_suggested_questions(q_list)
                
                notes_list = response_json.get("live_notes", [])
                if notes_list:
                    current_notes = list(self.memory.live_notes)
                    for n in notes_list:
                        if n not in current_notes:
                            current_notes.append(n)
                    self.memory.update_live_notes(current_notes)

                # Emit to UI
                self.on_results_callback({
                    "type": "periodic",
                    "questions": self.memory.suggested_questions,
                    "notes": self.memory.live_notes,
                    "action_items": response_json.get("action_items", [])
                })
        except Exception as e:
            print(f"[CopilotAgent] Error in periodic analysis: {e}")
        finally:
            self.is_analyzing = False

    def run_quick_prompt(self, prompt_key_or_text: str):
        """Immediately executes an on-demand prompt in background."""
        threading.Thread(
            target=self._execute_quick_prompt,
            args=(prompt_key_or_text,),
            daemon=True
        ).start()

    def _execute_quick_prompt(self, prompt_key_or_text: str):
        """Worker executing quick-action prompt."""
        # Resolve prompt instruction & title
        if prompt_key_or_text in DEFAULT_QUICK_PROMPTS:
            instruction = DEFAULT_QUICK_PROMPTS[prompt_key_or_text]["instruction"]
            title = DEFAULT_QUICK_PROMPTS[prompt_key_or_text]["title"]
        else:
            instruction = prompt_key_or_text
            title = "Custom Query"

        # Check offline mode
        if self._is_offline_mode():
            response_text = self.offline_engine.generate_quick_action(
                prompt_key_or_text, self.memory.turns
            )
            self.on_results_callback({
                "type": "quick_action",
                "title": title,
                "text": response_text
            })
            return

        prompt_context = self.memory.get_prompt_context()
        user_content = f"{prompt_context}\n\n=== USER REQUEST ===\n{instruction}"

        try:
            response_text = self._call_llm_text(
                system_prompt=BASE_SYSTEM_PROMPT,
                user_content=user_content
            )

            self.on_results_callback({
                "type": "quick_action",
                "title": title,
                "text": response_text
            })
        except Exception as e:
            print(f"[CopilotAgent] Online query error ({e}). Falling back to offline extraction.")
            offline_text = self.offline_engine.generate_quick_action(
                prompt_key_or_text, self.memory.turns
            )
            self.on_results_callback({
                "type": "quick_action",
                "title": title,
                "text": f"{offline_text}\n\n*(Note: Cloud LLM unavailable: {e})*"
            })

    def _call_llm(self, system_prompt: str, user_content: str, require_json: bool = True) -> Optional[Dict[str, Any]]:
        """Invokes configured LLM and parses JSON output."""
        if self._is_offline_mode():
            return self.offline_engine.generate_periodic(self.memory.turns, self.memory.live_notes)

        raw_text = self._call_llm_text(system_prompt, user_content, json_mode=require_json)
        if not raw_text:
            return None

        # Clean JSON markdown fences if present
        clean_text = raw_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()

        try:
            return json.loads(clean_text)
        except json.JSONDecodeError as e:
            print(f"[CopilotAgent] JSON parse error: {e}. Raw text:\n{raw_text}")
            return None

    def _call_llm_text(self, system_prompt: str, user_content: str, json_mode: bool = False) -> str:
        """Low-level HTTP dispatcher for LLMs."""
        if self.llm_provider == "offline":
            return self.offline_engine.generate_quick_action(user_content, self.memory.turns)

        if self.privacy_mode or self.llm_provider == "ollama":
            # Local Ollama
            endpoint = self.custom_endpoint or "http://localhost:11434/api/generate"
            payload = {
                "model": self.model_name or "llama3.2",
                "prompt": f"<|system|>\n{system_prompt}\n<|user|>\n{user_content}\n<|assistant|>",
                "stream": False
            }
            if json_mode:
                payload["format"] = "json"
            
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    return resp.json().get("response", "")
                raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text}")

        elif self.llm_provider == "openrouter":
            if not self.api_key:
                raise RuntimeError("OpenRouter API key is not configured.")
            
            endpoint = self.custom_endpoint or "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key.strip()}",
                "HTTP-Referer": "https://github.com/sandersoncw55/speakr-companion",
                "X-Title": "Speakr Companion Copilot"
            }
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
            payload = {
                "model": self.model_name or "openai/gpt-4o-mini",
                "messages": messages,
                "temperature": 0.3
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            with httpx.Client(timeout=15.0) as client:
                resp = client.post(endpoint, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                raise RuntimeError(f"OpenRouter returned HTTP {resp.status_code}: {resp.text}")

        elif self.llm_provider == "gemini":
            if not self.api_key:
                raise RuntimeError("Gemini API key is not configured.")
            
            model = self.model_name or "gemini-2.0-flash"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key.strip()}"
            
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": f"{system_prompt}\n\n{user_content}"}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.3
                }
            }
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                    return ""
                raise RuntimeError(f"Gemini API returned HTTP {resp.status_code}: {resp.text}")

        else:
            raise ValueError(f"Unknown LLM provider: {self.llm_provider}")

