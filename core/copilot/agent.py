import json
import time
import threading
import httpx
from typing import Optional, Callable, Dict, Any, List
from core.copilot.memory import CopilotMemory
from core.copilot.prompts import (
    get_periodic_prompt,
    DEFAULT_QUICK_PROMPTS,
    BASE_SYSTEM_PROMPT
)

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
        
        # Configuration
        self.llm_provider = "openrouter"  # "openrouter", "gemini", "ollama"
        self.api_key = ""
        self.model_name = "openai/gpt-4o-mini"
        self.custom_endpoint: Optional[str] = None
        self.privacy_mode = False  # If True, enforces local Ollama or blocks outbound
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

    def _run_periodic_analysis(self):
        """Executes periodic background evaluation."""
        if self.is_analyzing:
            return
        self.is_analyzing = True
        try:
            prompt_context = self.memory.get_prompt_context()
            system_prompt = get_periodic_prompt(self.active_tag)
            
            response_json = self._call_llm(
                system_prompt=system_prompt,
                user_content=prompt_context,
                require_json=True
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
        # Resolve prompt instruction
        if prompt_key_or_text in DEFAULT_QUICK_PROMPTS:
            instruction = DEFAULT_QUICK_PROMPTS[prompt_key_or_text]["instruction"]
            title = DEFAULT_QUICK_PROMPTS[prompt_key_or_text]["title"]
        else:
            instruction = prompt_key_or_text
            title = "Custom Query"

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
            self.on_results_callback({
                "type": "quick_action",
                "title": title,
                "text": f"Error executing prompt: {e}"
            })

    def _call_llm(self, system_prompt: str, user_content: str, require_json: bool = True) -> Optional[Dict[str, Any]]:
        """Invokes configured LLM and parses JSON output."""
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
