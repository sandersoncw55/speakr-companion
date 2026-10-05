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
    
    Extracts rolling summaries, questions, commitments, and risks from local transcript turns
    without requiring any cloud API keys or external services.
    """

    ACTION_KEYWORDS = [
        "action item", "will do", "need to", "going to", "follow up", 
        "send", "review", "schedule", "assign", "check with", "make sure",
        "i'll", "we'll", "take care of", "look into", "set up", "deploy", "update"
    ]
    
    DECISION_KEYWORDS = [
        "agreed", "decided", "decision", "consensus", "confirmed", "approved", 
        "will proceed with", "going with", "settled on", "plan is"
    ]

    RISK_KEYWORDS = [
        "risk", "delay", "issue", "problem", "blocker", "blocked", "fail", 
        "failed", "bug", "crash", "uncertain", "not sure", "concern",
        "bottleneck", "timeout", "latency", "regression"
    ]

    def generate_periodic(self, turns: List[TranscriptTurn], live_notes: List[str]) -> Dict[str, Any]:
        """Synthesizes rolling summary, questions, and follow-ups from recent turns."""
        if not turns:
            return {
                "rolling_summary": {"topic": "", "executive_summary": "", "key_decisions": []},
                "suggested_questions": [],
                "follow_up_suggestions": [],
                "live_notes": [],
                "action_items": []
            }

        recent_turns = turns[-14:]
        
        extracted_questions = []
        follow_up_items = []
        key_decisions = []
        substantive_statements = []

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

                # Check for decisions
                if any(kw in s_lower for kw in self.DECISION_KEYWORDS):
                    if len(s_clean) > 15 and s_clean not in key_decisions:
                        key_decisions.append(s_clean)

                # Check for action items / follow-ups
                if any(kw in s_lower for kw in self.ACTION_KEYWORDS):
                    owner = "You" if "you" in speaker.lower() else "Unassigned"
                    # Try to parse owner if speaker is named or mentioned
                    if "i'll" in s_lower or "i will" in s_lower:
                        owner = speaker.replace("[", "").replace("]", "")
                    follow_up_items.append({
                        "task": s_clean,
                        "owner": owner
                    })

                # Collect substantive statements for narrative synthesis
                if len(s_clean) > 20 and not s_clean.endswith("?"):
                    substantive_statements.append((speaker, s_clean))

        # Formulate suggested questions
        suggested_questions = []
        
        # 1. Follow up on any unanswered question from dialogue
        for eq in extracted_questions[:2]:
            suggested_questions.append({
                "question": f"Follow up: {eq}",
                "rationale": "Clarify question raised in recent dialogue"
            })
            
        # 2. Contextual questions based on actions / commitments
        if follow_up_items and len(suggested_questions) < 3:
            first_act = follow_up_items[0]["task"]
            suggested_questions.append({
                "question": f"Regarding '{first_act[:55]}...', what is the validation criteria and cutover window?",
                "rationale": "Lock down commitment scope and acceptance criteria"
            })
            
        # 3. Technical Dependency / Blocker check
        if len(suggested_questions) < 3:
            suggested_questions.append({
                "question": "Are there any downstream service dependencies or database locks we need to account for?",
                "rationale": "Validate system blast radius and failure isolation"
            })
        if len(suggested_questions) < 3:
            suggested_questions.append({
                "question": "What is the rollback procedure if validation tests fail post-deployment?",
                "rationale": "Ensure failure recovery plan is confirmed"
            })

        # Synthesize rolling summary narrative
        topic = "Meeting Discussion"
        if substantive_statements:
            # Topic inference
            first_stmt = substantive_statements[0][1]
            topic_match = re.search(r'(?:about|on|regarding|for)\s+([A-Za-z0-9_\-\s]{4,30})', first_stmt, re.IGNORECASE)
            if topic_match:
                topic = topic_match.group(1).strip().capitalize()
            else:
                topic = first_stmt[:40].strip() + ("..." if len(first_stmt) > 40 else "")

            # Cohesive prose summary
            sentences_pool = [s[1] for s in substantive_statements[-4:]]
            exec_summary = " ".join(sentences_pool)
            if len(exec_summary) > 350:
                exec_summary = exec_summary[:347] + "..."
        else:
            exec_summary = "Discussion in progress. Awaiting speech turns for synthesis."

        return {
            "rolling_summary": {
                "topic": topic,
                "executive_summary": exec_summary,
                "key_decisions": key_decisions[:3]
            },
            "suggested_questions": suggested_questions[:3],
            "follow_up_suggestions": follow_up_items[:4],
            "live_notes": [f"{s[0]}: {s[1]}" for s in substantive_statements[-3:]],
            "action_items": [f"[{it['owner']}] {it['task']}" for it in follow_up_items[:4]]
        }

    def generate_quick_action(self, prompt_key_or_text: str, turns: List[TranscriptTurn]) -> str:
        """Processes quick action triggers offline."""
        if not turns:
            return "No transcript turns captured yet. Speak or play meeting audio to analyze."

        p_lower = prompt_key_or_text.lower()
        recent_turns = turns[-15:]

        if "catch" in p_lower or "summarize" in p_lower:
            lines = ["⏱️ **Recent Meeting Summary:**\n"]
            for t in recent_turns[-8:]:
                lines.append(f"• **{t.speaker_label}** ({t.formatted_time}): {t.text}")
            return "\n".join(lines)

        elif "ask" in p_lower or "what_to_ask" in p_lower:
            periodic = self.generate_periodic(turns, [])
            q_list = periodic.get("suggested_questions", [])
            lines = ["💡 **Suggested Questions for Right Now:**\n"]
            for i, q in enumerate(q_list, 1):
                if isinstance(q, dict):
                    q_text = q.get("question", "")
                    rat = q.get("rationale", "")
                    lines.append(f"{i}. **{q_text}**" + (f" *(Rationale: {rat})*" if rat else ""))
                else:
                    lines.append(f"{i}. {q}")
            return "\n".join(lines)

        elif "owner" in p_lower or "clarify_ownership" in p_lower or "action" in p_lower:
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
        self.llm_provider = "offline"  # "offline", "openrouter", "gemini", "ollama", "lm_studio"
        self.api_key = ""
        self.model_name = "openai/gpt-4o-mini"
        self.custom_endpoint: Optional[str] = None
        self.privacy_mode = False
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
                latest_turns = self.memory.turns
                if latest_turns and latest_turns[-1].turn_id > self.last_analyzed_turn_id:
                    self.last_analyzed_turn_id = latest_turns[-1].turn_id
                    threading.Thread(target=self._run_periodic_analysis, daemon=True).start()

    def _is_offline_mode(self) -> bool:
        """Determines if offline fallback should be used."""
        if self.llm_provider == "offline":
            return True
        if self.privacy_mode and self.llm_provider not in ("ollama", "lm_studio"):
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
                    self.memory.turns, self.memory.user_notes
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
                        self.memory.turns, self.memory.user_notes
                    )
            
            if response_json and isinstance(response_json, dict):
                # 1. Update Rolling Summary
                summary_data = response_json.get("rolling_summary", {})
                if summary_data and isinstance(summary_data, dict):
                    self.memory.set_rolling_summary(summary_data)

                # 2. Update Suggested Questions
                q_list = response_json.get("suggested_questions", [])
                if q_list:
                    self.memory.set_suggested_questions(q_list)
                
                # 3. Update Follow-up Suggestions / Action Items
                follow_ups = response_json.get("follow_up_suggestions", response_json.get("action_items", []))
                if follow_ups:
                    self.memory.set_follow_up_suggestions(follow_ups)

                # Emit structured results to UI
                self.on_results_callback({
                    "type": "periodic",
                    "rolling_summary": self.memory.rolling_summary,
                    "questions": self.memory.suggested_questions,
                    "follow_ups": self.memory.follow_up_suggestions,
                    "user_notes": self.memory.user_notes,
                    "notes": self.memory.user_notes,
                    "action_items": self.memory.follow_up_suggestions
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
        if prompt_key_or_text in DEFAULT_QUICK_PROMPTS:
            instruction = DEFAULT_QUICK_PROMPTS[prompt_key_or_text]["instruction"]
            title = DEFAULT_QUICK_PROMPTS[prompt_key_or_text]["title"]
        else:
            instruction = prompt_key_or_text
            title = "Custom Query"

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
            return self.offline_engine.generate_periodic(self.memory.turns, self.memory.user_notes)

        raw_text = self._call_llm_text(system_prompt, user_content, json_mode=require_json)
        if not raw_text:
            return None

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

        if self.llm_provider == "lm_studio":
            raw_url = (self.custom_endpoint or "http://localhost:1234/v1").strip().rstrip("/")
            if raw_url.endswith("/chat/completions"):
                endpoint = raw_url
            elif raw_url.endswith("/v1"):
                endpoint = f"{raw_url}/chat/completions"
            else:
                endpoint = f"{raw_url}/v1/chat/completions"

            headers = {
                "Content-Type": "application/json"
            }
            if self.api_key and self.api_key.strip():
                headers["Authorization"] = f"Bearer {self.api_key.strip()}"

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
            payload = {
                "model": self.model_name or "local-model",
                "messages": messages,
                "temperature": 0.3
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            with httpx.Client(timeout=30.0) as client:
                resp = client.post(endpoint, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                raise RuntimeError(f"LM Studio returned HTTP {resp.status_code}: {resp.text}")

        elif self.llm_provider == "ollama" or (self.privacy_mode and self.llm_provider not in ("openrouter", "gemini")):
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


def fetch_lm_studio_models(endpoint: str, api_key: str = "") -> List[str]:
    """Queries LM Studio / OpenAI-compatible endpoint for available model names."""
    clean_ep = endpoint.strip().rstrip("/")
    if not clean_ep:
        clean_ep = "http://localhost:1234/v1"
        
    if not clean_ep.endswith("/models"):
        if not clean_ep.endswith("/v1"):
            clean_ep = f"{clean_ep}/v1"
        models_url = f"{clean_ep}/models"
    else:
        models_url = clean_ep

    headers = {}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    with httpx.Client(timeout=4.0) as client:
        resp = client.get(models_url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            models_data = data.get("data", [])
            models = []
            for item in models_data:
                if isinstance(item, dict) and "id" in item:
                    models.append(item["id"])
                elif isinstance(item, str):
                    models.append(item)
            return sorted(models)
        raise RuntimeError(f"LM Studio returned HTTP {resp.status_code}: {resp.text}")
