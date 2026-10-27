import json
import time
import re
import threading
import httpx
from typing import Optional, Callable, Dict, Any, List
from core.copilot.memory import CopilotMemory, TranscriptTurn
from core.copilot.corpus import DynamicDomainCorpus
from core.copilot.prompts import (
    get_periodic_prompt,
    DEFAULT_QUICK_PROMPTS,
    BASE_SYSTEM_PROMPT
)

class OfflineExtractiveEngine:
    """Zero-dependency, 100% offline heuristic intelligence engine.
    
    Extracts rolling topic summaries, technical questions, commitments, and risks from local transcript turns
    without requiring any cloud API keys or external services, filtering conversational noise and chatter.
    """

    ACTION_KEYWORDS = [
        "action item", "will do", "need to", "going to", "follow up", 
        "send", "review", "schedule", "assign", "check with", "make sure",
        "i'll", "we'll", "take care of", "look into", "set up", "deploy", "update",
        "implement", "verify", "patch", "migrate", "benchmark", "document", "reproduce"
    ]

    TECHNICAL_ACTION_VERBS = [
        "deploy", "test", "benchmark", "configure", "review", "investigate", "fix",
        "patch", "document", "schedule", "implement", "provision", "verify", "reproduce",
        "refactor", "monitor", "migrate", "validate", "open", "create", "reach out",
        "sync", "assign", "check", "email", "update", "pull", "merge", "commit", "build"
    ]
    
    DECISION_KEYWORDS = [
        "agreed", "decided", "decision", "consensus", "confirmed", "approved", 
        "will proceed with", "going with", "settled on", "plan is", "concluded"
    ]

    RISK_KEYWORDS = [
        "risk", "delay", "issue", "problem", "blocker", "blocked", "fail", 
        "failed", "bug", "crash", "uncertain", "not sure", "concern",
        "bottleneck", "timeout", "latency", "regression", "lock contention"
    ]

    # Conversational filler and non-work chatter patterns to ignore
    CHATTER_PATTERNS = [
        r'\b(?:i mean|you know|dude|man|bro|honestly|actually)\b',
        r'\b(?:drink|beer|liters?|boot|whisper|milwaukee|conference|party|vacation)\b',
        r'\b(?:next video|youtube|subscribe|podcast|recorded)\b',
        r'\b(?:good morning|good afternoon|have a good|see ya|bye now|see you)\b',
        r'\b(?:can you hear me|can you see my screen|you are on mute|unmute)\b',
        r'\b(?:thank you for walking through|thanks for having me|great to see you)\b',
        r'\b(?:stories about it|good conference|was not looking forward to|looking forward to going)\b',
        r'\b(?:i pray|whispered in .* ear|poison|oh,? my god)\b',
        r'\b(?:sounds really cool|could never do that here|back of their hand)\b',
        r'\b(?:look at all the apps|sometimes you don\'t even know who the app owner is)\b',
        r'\b(?:sorry, that was a little more than|drink a few)\b',
        r'\b(?:i brought us some people that are happy with it)\b'
    ]

    TECHNICAL_DOMAINS = [
        ("Storage & VDI Infrastructure", [
            "vdi", "virtual desktop", "thin provisioning", "vmotion", "datastore",
            "san storage", "storage cluster", "storage array", "storage volume", "snapshot rollback"
        ]),
        ("Database & Data Architecture", [
            "database", "postgres", "postgresql", "mysql", "mongodb", "schema migration",
            "table index", "replica lag", "database replication", "query execution", "sql migration"
        ]),
        ("Deployment & Release Lifecycle", [
            "canary deployment", "production rollback", "cutover window", "ci/cd pipeline",
            "staging deployment", "release build", "blue-green deployment", "zero-downtime"
        ]),
        ("API & Microservice Architecture", [
            "rest api", "graphql", "microservice", "grpc", "api gateway", "ingress controller",
            "circuit breaker", "api endpoint", "service mesh"
        ]),
        ("Event Streaming & Messaging", [
            "apache kafka", "kafka broker", "rabbitmq", "message broker", "consumer lag",
            "partition offset", "message queue", "event stream"
        ]),
        ("Caching & State Management", [
            "redis cache", "memcached", "cache invalidation", "cache eviction", "ttl expiration"
        ]),
        ("Performance & Reliability Diagnostics", [
            "p99 latency", "memory leak", "cpu spike", "thread exhaustion", "connection pool",
            "profiling trace", "bottleneck analysis", "telemetry counter"
        ]),
        ("Network & Infrastructure Security", [
            "firewall rule", "vlan subnet", "dns resolution", "ssl certificate", "tls handshake",
            "zero trust", "network security", "bastion host"
        ]),
        ("Enterprise Endpoint & Packaging", [
            "intune", "autopilot", "application packaging", "repackaging", "psadt", "sccm",
            "win32 app", "zscaler", "endpoint manager", "logon logger"
        ]),
        ("Identity, Access & Policy Management", [
            "rbac permissions", "azure entra", "entra id", "group policy", "gpo policy",
            "active directory", "access control list", "token auth"
        ]),
        ("Product Strategy & Roadmap", [
            "product roadmap", "sprint planning", "milestone", "user story", "backlog grooming",
            "feature scope", "product launch", "mvp release", "release train"
        ]),
        ("UI/UX & Frontend Development", [
            "user interface", "frontend architecture", "design system", "wireframe", "figma mockup",
            "responsive design", "component library", "user experience"
        ]),
        ("Finance, Budget & Procurement", [
            "budget allocation", "vendor contract", "procurement", "licensing agreement",
            "pricing tier", "cost estimation", "capex opex", "contract renewal"
        ]),
        ("Operations & Incident Response", [
            "incident postmortem", "root cause analysis", "outage remediation", "pagerduty alert",
            "runbook execution", "sev1 incident", "service degradation"
        ]),
        ("Team Sync & People Operations", [
            "headcount planning", "hiring pipeline", "candidate interview", "performance review",
            "1-on-1 sync", "team retrospective", "onboarding workflow"
        ])
    ]

    COMMON_STOP_ACRONYMS = {
        "THE", "AND", "FOR", "YOU", "ARE", "NOT", "CAN", "BUT", "ALL", 
        "NEW", "NOW", "SEE", "YES", "GET", "LET", "PUT", "OUT", "ONE", 
        "TWO", "HOW", "WHO", "WHY", "OUR", "ANY", "HAS", "HAD", "HAVE"
    }

    @classmethod
    def extract_dynamic_entities(cls, text: str) -> List[str]:
        """Dynamically extracts technical acronyms, PascalCase systems, and key technical phrases."""
        entities = []
        # 1. Technical acronyms (2-6 chars): e.g. RBAC, GPO, MSI, PSADT, SCCM, Intune, API, SAN, VDI, W365
        acronyms = re.findall(r'\b[A-Z0-9]{2,6}\b', text)
        for ac in acronyms:
            if ac not in cls.COMMON_STOP_ACRONYMS and not ac.isdigit():
                if ac not in entities:
                    entities.append(ac)
        
        # 2. PascalCase / CamelCase identifiers: e.g. AutoPilot, PowerShell, LogonLogger, PostgreSQL, ServiceBus
        pascal_cases = re.findall(r'\b[A-Z][a-z]+(?:[A-Z0-9][a-z0-9]*)+\b', text)
        for pc in pascal_cases:
            if pc not in entities:
                entities.append(pc)

        # 3. Capitalized multi-word noun clusters: e.g. "Group Policy", "Home Office", "Microsoft Graph", "Branch Office"
        multi_words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text)
        for mw in multi_words:
            if mw not in entities and not any(mw.lower().startswith(s) for s in ["good morning", "thank you", "look at", "have a", "sometimes you"]):
                entities.append(mw)

        # 4. Technical and organizational collocations (multi-word phrases)
        colloc_pattern = r'\b(?:registry|policy|package|packaging|endpoint|cluster|deployment|pipeline|permission|token|driver|migration|database|infrastructure|network|firewall|server|service|container|volume|workflow|build|script|architecture|dependency|latency|failover|firmware|schema|table|queue|broker|cache|gateway|ingress|autopilot|intune|zscaler|rbac|gpo|win32|psadt|sprint|roadmap|milestone|feature|budget|licensing|contract|vendor|design|incident|outage|postmortem|onboarding|performance)\b\s+[a-zA-Z0-9_\-]+'
        collocs = re.findall(colloc_pattern, text, re.IGNORECASE)
        for c in collocs:
            c_clean = c.strip().title()
            if len(c_clean) > 4 and c_clean not in entities:
                entities.append(c_clean)

        return entities

    @classmethod
    def _is_casual_noise(cls, text: str) -> bool:
        """Determines if a statement is casual chatter, greeting, joke, or conversational filler."""
        t_lower = text.lower().strip()
        if len(t_lower) < 12:
            return True
        for pattern in cls.CHATTER_PATTERNS:
            if re.search(pattern, t_lower):
                return True
        # Check starting casual idioms
        casual_starts = (
            "i like it, but", "i'm just saying", "sorry,", "look at all",
            "sometimes you", "it was a good", "surprisingly,", "we'll see you",
            "we'll tell mike", "oh, my god", "thank you for", "i pray",
            "casey was the one", "casey did help", "i'll get you", "dude,", "man,"
        )
        if any(t_lower.startswith(cs) for cs in casual_starts):
            return True
        return False

    @classmethod
    def _is_valid_technical_action(cls, sentence: str) -> bool:
        """Validates that a sentence represents an authentic work deliverable, not casual chatter."""
        s_lower = sentence.lower()
        if cls._is_casual_noise(s_lower):
            return False
        # Must contain at least one valid technical action verb
        has_action_verb = any(v in s_lower for v in cls.TECHNICAL_ACTION_VERBS)
        # Exclude casual 'going to' phrases without work verbs
        if "going to" in s_lower and not any(v in s_lower for v in ["deploy", "test", "review", "schedule", "implement", "update", "fix", "verify", "sign", "assign", "create"]):
            return False
        return has_action_verb

    def generate_periodic(self, turns: List[TranscriptTurn], live_notes: List[str], custom_summary_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Synthesizes structured topic summary cards, technical questions, and deliverables from turns."""
        if not turns:
            return {
                "rolling_summary": {"topic": "", "topics": [], "executive_summary": "", "key_decisions": [], "summary_bullets": []},
                "suggested_questions": [],
                "follow_up_suggestions": [],
                "live_notes": [],
                "action_items": []
            }

        recent_turns = turns[-16:]
        
        extracted_questions = []
        follow_up_items = []
        key_decisions = []
        substantive_statements = []

        def _clean_stmt(stmt_text: str) -> str:
            t = stmt_text.strip()
            t = re.sub(r'^(?:so|well|yeah|okay|ok|hey|uh|um|look|actually|honestly|i mean|you know)\s*,\s*', '', t, flags=re.IGNORECASE)
            t = re.sub(r'^(?:i think|we think|i believe|we believe|my thought is that|our plan is to)\s+', '', t, flags=re.IGNORECASE)
            t = re.sub(r'^(?:let\'s|we should|we need to)\s+', '', t, flags=re.IGNORECASE)
            t = t.strip()
            return (t[0].upper() + t[1:]) if t else ""

        for turn in recent_turns:
            text = turn.text.strip()
            speaker = turn.speaker_label
            sentences = re.split(r'(?<=[.?!])\s+', text)
            
            for s in sentences:
                s_clean = s.strip()
                if not s_clean:
                    continue
                s_lower = s_clean.lower()

                # Filter out casual conversational noise immediately
                if self._is_casual_noise(s_clean):
                    continue
                
                # Check for questions asked in conversation
                if s_clean.endswith("?") or any(s_lower.startswith(w) for w in ["who ", "what ", "where ", "when ", "why ", "how ", "can we ", "should we ", "could you "]):
                    if len(s_clean) > 12 and s_clean not in extracted_questions:
                        extracted_questions.append(s_clean)

                # Check for decisions
                if any(kw in s_lower for kw in self.DECISION_KEYWORDS):
                    clean_d = _clean_stmt(s_clean)
                    if len(clean_d) > 15 and clean_d not in key_decisions:
                        key_decisions.append(clean_d)

                # Check for action items / follow-ups with strict action verb validation
                if any(kw in s_lower for kw in self.ACTION_KEYWORDS) and self._is_valid_technical_action(s_clean):
                    owner = "You" if "you" in speaker.lower() else "Unassigned"
                    if "i'll" in s_lower or "i will" in s_lower or "i was going to" in s_lower:
                        owner = speaker.replace("[", "").replace("]", "")
                    follow_up_items.append({
                        "task": _clean_stmt(s_clean),
                        "owner": owner
                    })

                # Collect substantive statements for narrative synthesis
                if len(s_clean) > 18 and not s_clean.endswith("?"):
                    substantive_statements.append((speaker, _clean_stmt(s_clean)))

        # Collect statements with dynamic entities
        stmt_entities = []
        all_detected_entities = []
        for speaker, stmt in substantive_statements:
            ents = self.extract_dynamic_entities(stmt)
            stmt_entities.append((speaker, stmt, ents))
            for e in ents:
                if e not in all_detected_entities:
                    all_detected_entities.append(e)

        # Formulate suggested questions dynamically from extracted technical entities and deliverables
        suggested_questions = []

        # 1. Probe top extracted technical entities from recent dialogue
        for ent in all_detected_entities[:3]:
            if len(suggested_questions) < 3:
                suggested_questions.append({
                    "question": f"Regarding {ent}, what are the specific edge cases, dependency constraints, or validation criteria?",
                    "rationale": f"Verify architectural boundaries and failure modes for {ent}"
                })

        # 2. Contextual probing on commitments / deliverables
        if follow_up_items and len(suggested_questions) < 3:
            first_act = follow_up_items[0]["task"]
            suggested_questions.append({
                "question": f"Regarding '{first_act[:50]}...', what is the validation criteria and rollback cutover threshold?",
                "rationale": "Lock down technical acceptance criteria and safety margin"
            })

        # 3. Follow up on any unanswered technical question from dialogue
        for eq in extracted_questions[:2]:
            if len(suggested_questions) < 3:
                suggested_questions.append({
                    "question": f"Follow up: {_clean_stmt(eq)}",
                    "rationale": "Clarify technical inquiry raised in recent dialogue"
                })

        # 4. Fallback technical probing question if needed
        if len(suggested_questions) < 3:
            suggested_questions.append({
                "question": "What is the automated rollback trigger and telemetry signal if staging validation fails?",
                "rationale": "Ensure regression recovery plan is verified"
            })

        # Dynamically cluster substantive statements by shared entity overlap (No Hardcoded Domain Buckets!)
        clustered_topics: List[Dict[str, Any]] = []
        used_indices = set()

        for i, (spk_i, stmt_i, ents_i) in enumerate(stmt_entities):
            if i in used_indices:
                continue
            used_indices.add(i)
            cluster_stmts = [stmt_i]
            cluster_ents = set(ents_i)

            for j, (spk_j, stmt_j, ents_j) in enumerate(stmt_entities):
                if j in used_indices:
                    continue
                shared = cluster_ents.intersection(set(ents_j))
                if shared or (not cluster_ents and not ents_j):
                    used_indices.add(j)
                    cluster_stmts.append(stmt_j)
                    cluster_ents.update(ents_j)

            # Derive topic title dynamically
            title = None
            combined_cluster_text = " ".join([s.lower() for s in cluster_stmts])

            # 1. Primary: Dynamic entities extracted directly from dialogue
            if cluster_ents:
                # Prioritize multi-word phrases and high-signal terms
                top_ents = sorted(list(cluster_ents), key=lambda e: (len(e.split()) > 1, len(e)), reverse=True)[:2]
                title = " & ".join(top_ents)

            # 2. Secondary fallback: Check structured domain taxonomy with whole-word regex
            if not title:
                for dom_name, dom_kws in self.TECHNICAL_DOMAINS:
                    if any(re.search(rf"\b{re.escape(k)}\b", combined_cluster_text, re.IGNORECASE) for k in dom_kws):
                        title = dom_name
                        break

            # 3. Tertiary fallback: Clean subject from first statement
            if not title:
                first_s = cluster_stmts[0].rstrip(".")
                first_clean = re.sub(r'^(?:we|they|the team|i|you)\s+(?:discussed|reviewed|evaluated|tested|confirmed|noted|agreed that|looked at)\s+', '', first_s, flags=re.IGNORECASE)
                first_clean = first_clean[0].upper() + first_clean[1:] if first_clean else first_s
                title = first_clean[:55] + ("..." if len(first_clean) > 55 else "")

            # Synthesize cohesive narrative sentences
            title_display = title if any(c.isupper() for c in title) else title.title()
            if len(cluster_stmts) == 1:
                stmt_clean = cluster_stmts[0].rstrip(".")
                if stmt_clean.lower().startswith("we ") or stmt_clean.lower().startswith("the team "):
                    summary_text = f"{stmt_clean} in relation to {title_display}."
                else:
                    summary_text = f"The team reviewed {title_display}, noting that {stmt_clean.lower() if not stmt_clean.startswith('I ') else stmt_clean}."
            else:
                s1 = cluster_stmts[0].rstrip(".")
                s2 = cluster_stmts[1].rstrip(".")
                summary_text = f"Discussion focused on {title_display}: {s1}. Furthermore, {s2}."

            clustered_topics.append({
                "title": title,
                "summary": summary_text,
                "status": "in_progress",
                "key_points": cluster_stmts[:3]
            })

        structured_topics = clustered_topics[:4]

        # Synthesize rolling summary bullet points (Objective Technical Takeaways, NEVER raw conversational quotes)
        summary_bullets = []
        for dec in key_decisions[:2]:
            summary_bullets.append(f"Confirmed: {dec}")

        for act in follow_up_items[:2]:
            owner_str = f" (@{act['owner']})" if act["owner"] != "Unassigned" else ""
            summary_bullets.append(f"Planned action: {act['task']}{owner_str}")

        for top in structured_topics:
            if len(summary_bullets) < 5 and top["summary"]:
                summary_bullets.append(f"{top['title']}: {top['summary'][:120]}...")

        if not summary_bullets:
            summary_bullets = ["Meeting discussion active; synthesizing ongoing technical exchange."]

        # Primary topic title
        topic = structured_topics[0]["title"] if structured_topics else "Technical Discussion"

        exec_summary = " ".join([t["summary"] for t in structured_topics[:2]]) if structured_topics else " ".join(summary_bullets[:3])
        if len(exec_summary) > 350:
            exec_summary = exec_summary[:347] + "..."

        return {
            "rolling_summary": {
                "topic": topic,
                "topics": structured_topics,
                "summary_bullets": summary_bullets[:5],
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
        self.custom_summary_instruction: Optional[str] = None

        # State tracking
        self.last_analyzed_turn_id = 0
        self.is_running = False
        self.is_analyzing = False
        self.last_analysis_status = "idle"  # "idle", "analyzing", "online", "offline", "offline_fallback", "error"
        self.last_analysis_time = 0.0
        self.last_latency_ms = 0.0
        self.last_error_message = ""
        self.timer_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def configure(
        self,
        provider: str = "openrouter",
        api_key: str = "",
        model_name: str = "openai/gpt-4o-mini",
        custom_endpoint: Optional[str] = None,
        privacy_mode: bool = False,
        active_tag: Optional[str] = None,
        custom_summary_instruction: Optional[str] = None
    ):
        """Updates agent LLM parameters and privacy state."""
        with self.lock:
            self.llm_provider = provider
            self.api_key = api_key
            self.model_name = model_name
            self.custom_endpoint = custom_endpoint
            self.privacy_mode = privacy_mode
            self.active_tag = active_tag
            self.custom_summary_instruction = custom_summary_instruction
            self.last_analysis_status = "offline" if provider == "offline" else "idle"

    def get_engine_info(self) -> Dict[str, Any]:
        """Returns current reasoning engine metadata and live health status."""
        with self.lock:
            return {
                "provider": self.llm_provider,
                "model": self.model_name,
                "endpoint": self.custom_endpoint or "",
                "privacy_mode": self.privacy_mode,
                "status": self.last_analysis_status,
                "last_analysis_time": self.last_analysis_time,
                "latency_ms": self.last_latency_ms,
                "error_message": self.last_error_message
            }

    def check_health(self) -> Dict[str, Any]:
        """Performs a lightweight connectivity check to verify reasoning engine availability."""
        with self.lock:
            provider = self.llm_provider
            endpoint = self.custom_endpoint
            api_key = self.api_key
            model_name = self.model_name

        start_time = time.time()

        if provider == "offline":
            return {
                "ok": True,
                "status": "offline",
                "provider": "offline",
                "model": "extractive-heuristics",
                "endpoint": "local",
                "latency_ms": 0.0,
                "message": "Offline extractive engine active (zero external dependencies)."
            }

        if provider == "lm_studio":
            target_url = (endpoint or "http://localhost:1234/v1").strip().rstrip("/")
            if not target_url.endswith("/models"):
                if not target_url.endswith("/v1"):
                    target_url = f"{target_url}/v1"
                models_url = f"{target_url}/models"
            else:
                models_url = target_url

            headers = {}
            if api_key and api_key.strip():
                headers["Authorization"] = f"Bearer {api_key.strip()}"

            try:
                with httpx.Client(timeout=3.0) as client:
                    resp = client.get(models_url, headers=headers)
                    latency = round((time.time() - start_time) * 1000, 1)
                    if resp.status_code == 200:
                        data = resp.json()
                        models_data = data.get("data", [])
                        model_ids = [m["id"] if isinstance(m, dict) else str(m) for m in models_data]
                        return {
                            "ok": True,
                            "status": "online",
                            "provider": "lm_studio",
                            "model": model_name or "Default",
                            "endpoint": target_url,
                            "latency_ms": latency,
                            "models_count": len(model_ids),
                            "message": f"Connected to LM Studio ({latency} ms). Models loaded: {len(model_ids)}"
                        }
                    return {
                        "ok": False,
                        "status": "error",
                        "provider": "lm_studio",
                        "model": model_name,
                        "endpoint": target_url,
                        "latency_ms": latency,
                        "message": f"LM Studio responded with HTTP {resp.status_code}: {resp.text[:100]}"
                    }
            except Exception as ex:
                latency = round((time.time() - start_time) * 1000, 1)
                return {
                    "ok": False,
                    "status": "error",
                    "provider": "lm_studio",
                    "model": model_name,
                    "endpoint": target_url,
                    "latency_ms": latency,
                    "message": f"Cannot connect to LM Studio at {target_url}: {ex}"
                }

        elif provider == "ollama":
            target_url = (endpoint or "http://localhost:11434").strip().rstrip("/")
            tags_url = f"{target_url}/api/tags" if not target_url.endswith("/tags") else target_url
            try:
                with httpx.Client(timeout=3.0) as client:
                    resp = client.get(tags_url)
                    latency = round((time.time() - start_time) * 1000, 1)
                    if resp.status_code == 200:
                        return {
                            "ok": True,
                            "status": "online",
                            "provider": "ollama",
                            "model": model_name or "llama3.2",
                            "endpoint": target_url,
                            "latency_ms": latency,
                            "message": f"Connected to Ollama ({latency} ms)."
                        }
                    return {
                        "ok": False,
                        "status": "error",
                        "provider": "ollama",
                        "model": model_name,
                        "endpoint": target_url,
                        "latency_ms": latency,
                        "message": f"Ollama HTTP {resp.status_code}: {resp.text[:100]}"
                    }
            except Exception as ex:
                latency = round((time.time() - start_time) * 1000, 1)
                return {
                    "ok": False,
                    "status": "error",
                    "provider": "ollama",
                    "model": model_name,
                    "endpoint": target_url,
                    "latency_ms": latency,
                    "message": f"Cannot connect to Ollama at {target_url}: {ex}"
                }

        elif provider == "openrouter":
            if not api_key:
                return {
                    "ok": False,
                    "status": "unconfigured",
                    "provider": "openrouter",
                    "model": model_name,
                    "endpoint": "https://openrouter.ai/api/v1",
                    "latency_ms": 0.0,
                    "message": "OpenRouter API Key is missing. Configure in Preferences."
                }
            try:
                with httpx.Client(timeout=3.5) as client:
                    resp = client.get(
                        "https://openrouter.ai/api/v1/auth/key",
                        headers={"Authorization": f"Bearer {api_key.strip()}"}
                    )
                    latency = round((time.time() - start_time) * 1000, 1)
                    if resp.status_code == 200:
                        return {
                            "ok": True,
                            "status": "online",
                            "provider": "openrouter",
                            "model": model_name,
                            "endpoint": "https://openrouter.ai/api/v1",
                            "latency_ms": latency,
                            "message": f"OpenRouter verified ({latency} ms). Model: {model_name}"
                        }
                    return {
                        "ok": False,
                        "status": "error",
                        "provider": "openrouter",
                        "model": model_name,
                        "endpoint": "https://openrouter.ai/api/v1",
                        "latency_ms": latency,
                        "message": f"OpenRouter auth rejected (HTTP {resp.status_code})"
                    }
            except Exception as ex:
                return {
                    "ok": False,
                    "status": "error",
                    "provider": "openrouter",
                    "model": model_name,
                    "endpoint": "https://openrouter.ai/api/v1",
                    "latency_ms": 0.0,
                    "message": f"OpenRouter request error: {ex}"
                }

        elif provider == "gemini":
            if not api_key:
                return {
                    "ok": False,
                    "status": "unconfigured",
                    "provider": "gemini",
                    "model": model_name,
                    "endpoint": "https://generativelanguage.googleapis.com",
                    "latency_ms": 0.0,
                    "message": "Gemini API Key is missing. Configure in Preferences."
                }
            try:
                with httpx.Client(timeout=3.5) as client:
                    resp = client.get(
                        f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key.strip()}"
                    )
                    latency = round((time.time() - start_time) * 1000, 1)
                    if resp.status_code == 200:
                        return {
                            "ok": True,
                            "status": "online",
                            "provider": "gemini",
                            "model": model_name,
                            "endpoint": "https://generativelanguage.googleapis.com",
                            "latency_ms": latency,
                            "message": f"Gemini API verified ({latency} ms). Model: {model_name}"
                        }
                    return {
                        "ok": False,
                        "status": "error",
                        "provider": "gemini",
                        "model": model_name,
                        "endpoint": "https://generativelanguage.googleapis.com",
                        "latency_ms": latency,
                        "message": f"Gemini API error HTTP {resp.status_code}"
                    }
            except Exception as ex:
                return {
                    "ok": False,
                    "status": "error",
                    "provider": "gemini",
                    "model": model_name,
                    "endpoint": "https://generativelanguage.googleapis.com",
                    "latency_ms": 0.0,
                    "message": f"Gemini request error: {ex}"
                }

        return {
            "ok": False,
            "status": "unknown",
            "provider": provider,
            "model": model_name,
            "endpoint": endpoint or "",
            "latency_ms": 0.0,
            "message": f"Unknown provider: {provider}"
        }

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
        """Timer loop firing background analysis on cadence with fast-start warmup."""
        last_check_time = time.time()
        while self.is_running:
            time.sleep(1.0)
            now = time.time()
            # Fast-start warmup cadence: check every 10-12s when no topics exist yet
            has_topics = bool(self.memory.rolling_summary.get("topics"))
            effective_cadence = self.cadence_seconds
            if not has_topics and len(self.memory.turns) >= 3:
                effective_cadence = min(12.0, max(8.0, self.cadence_seconds / 3.0))

            if now - last_check_time >= effective_cadence:
                last_check_time = now
                latest_turns = self.memory.turns
                if latest_turns and latest_turns[-1].turn_id > self.last_analyzed_turn_id:
                    self.last_analyzed_turn_id = latest_turns[-1].turn_id
                    threading.Thread(target=self._run_periodic_analysis, daemon=True).start()

    def trigger_immediate_periodic_analysis(self) -> None:
        """Manually triggers rolling summary synthesis immediately in a background thread."""
        if not self.is_analyzing and self.memory.turns:
            self.last_analyzed_turn_id = self.memory.turns[-1].turn_id
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
        self.last_analysis_status = "analyzing"
        start_t = time.time()
        try:
            if self._is_offline_mode():
                response_json = self.offline_engine.generate_periodic(
                    self.memory.turns, self.memory.user_notes, self.custom_summary_instruction
                )
                self.last_analysis_status = "offline"
                self.last_latency_ms = round((time.time() - start_t) * 1000, 1)
                self.last_analysis_time = time.time()
                self.last_error_message = ""
            else:
                try:
                    prompt_context = self.memory.get_prompt_context()
                    system_prompt = get_periodic_prompt(
                        tag_name=self.active_tag,
                        custom_summary_instruction=self.custom_summary_instruction
                    )
                    response_json = self._call_llm(
                        system_prompt=system_prompt,
                        user_content=prompt_context,
                        require_json=True
                    )
                    self.last_analysis_status = "online"
                    self.last_latency_ms = round((time.time() - start_t) * 1000, 1)
                    self.last_analysis_time = time.time()
                    self.last_error_message = ""
                except Exception as ex:
                    print(f"[CopilotAgent] Online analysis failed ({ex}), falling back to offline engine.")
                    self.last_analysis_status = "offline_fallback"
                    self.last_latency_ms = round((time.time() - start_t) * 1000, 1)
                    self.last_analysis_time = time.time()
                    self.last_error_message = str(ex)
                    response_json = self.offline_engine.generate_periodic(
                        self.memory.turns, self.memory.user_notes, self.custom_summary_instruction
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
                    "action_items": self.memory.follow_up_suggestions,
                    "engine_info": self.get_engine_info()
                })
        except Exception as e:
            self.last_analysis_status = "error"
            self.last_error_message = str(e)
            print(f"[CopilotAgent] Error in periodic analysis: {e}")
        finally:
            self.is_analyzing = False

    def run_quick_prompt(self, prompt_key_or_text: str, custom_instruction: Optional[str] = None):
        """Immediately executes an on-demand prompt in background."""
        threading.Thread(
            target=self._execute_quick_prompt,
            args=(prompt_key_or_text, custom_instruction),
            daemon=True
        ).start()

    def _execute_quick_prompt(self, prompt_key_or_text: str, custom_instruction: Optional[str] = None):
        """Worker executing quick-action prompt."""
        if custom_instruction and custom_instruction.strip():
            instruction = custom_instruction.strip()
            title = DEFAULT_QUICK_PROMPTS.get(prompt_key_or_text, {}).get("title", prompt_key_or_text)
        elif prompt_key_or_text in DEFAULT_QUICK_PROMPTS:
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
            return self.offline_engine.generate_periodic(self.memory.turns, self.memory.user_notes, self.custom_summary_instruction)

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
        except json.JSONDecodeError:
            # Fallback: extract first matching JSON object {...}
            match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            print(f"[CopilotAgent] JSON parse error. Raw text:\n{raw_text}")
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
                
                # If LM Studio rejected response_format json_object (e.g. requires json_schema or text), retry without response_format
                if json_mode and resp.status_code == 400 and "response_format" in resp.text:
                    payload.pop("response_format", None)
                    retry_resp = client.post(endpoint, headers=headers, json=payload)
                    if retry_resp.status_code == 200:
                        data = retry_resp.json()
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
