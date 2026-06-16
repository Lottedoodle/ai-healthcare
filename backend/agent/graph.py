from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.types import Command
from langgraph.prebuilt import ToolNode, tools_condition

from pydantic import BaseModel, Field
from typing import Literal, TypedDict, Annotated
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import re

load_dotenv()


def _create_llm() -> ChatOpenAI:
    openrouter_key = (os.getenv("OPEN_ROUTER_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")
    model = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

    if openrouter_key:
        return ChatOpenAI(
            model=model if "/" in model else f"openai/{model}",
            openai_api_key=openrouter_key,
            openai_api_base=os.getenv("OPEN_ROUTER_BASE", "https://openrouter.ai/api/v1"),
        )

    if not openai_key:
        raise RuntimeError("Missing OPENAI_API_KEY or OPEN_ROUTER_KEY in .env")

    return ChatOpenAI(model=model, openai_api_key=openai_key)


llm = _create_llm()


class TriageAndValidation(BaseModel):
    """Classify intent and check required fields in one step."""

    intent: Literal[
        "medical_knowledge",
        "patient_data",
        "dose_calculation",
        "drug_interaction",
        "emergency",
    ]
    provided_fields: list[str] = Field(
        description="Fields already provided, e.g. ['patient_id', 'weight']"
    )
    missing_fields: list[str] = Field(
        description="Required fields not yet provided"
    )
    clarifying_question: str = Field(
        description="Question to ask if fields are missing, empty string if complete"
    )


class PlanStep(BaseModel):
    action: str = Field(description="Short name for this step")
    tool: Literal[
        "search_medical_knowledge",
        "get_patient_labs",
        "get_patient_vitals",
        "check_drug_interaction",
        "emergency_protocol",
        "summarize",
        "none",
    ] = Field(description="Tool to call, summarize for final LLM summary, none to skip")
    description: str = Field(description="What this step accomplishes")
    hn: str = Field(default="", description="Patient HN (6 digits) for lab/vitals tools")
    query: str = Field(default="", description="Query for search_medical_knowledge")
    drug_a: str = Field(default="", description="First drug for check_drug_interaction")
    drug_b: str = Field(default="", description="Second drug for check_drug_interaction")
    symptom: str = Field(default="", description="Symptom for emergency_protocol")


def plan_step_to_tool_args(step: dict) -> dict:
    """Build tool invoke args from structured PlanStep fields (no free-form dict)."""
    args: dict = {}
    if step.get("hn"):
        args["hn"] = step["hn"]
    if step.get("query"):
        args["query"] = step["query"]
    if step.get("drug_a"):
        args["drug_a"] = step["drug_a"]
    if step.get("drug_b"):
        args["drug_b"] = step["drug_b"]
    if step.get("symptom"):
        args["symptom"] = step["symptom"]
    return args


class ExecutionPlan(BaseModel):
    steps: list[PlanStep] = Field(description="Ordered list of steps to execute")
    summary: str = Field(description="One-line summary of the plan for the physician")


class ComplexityRoute(BaseModel):
    mode: Literal["fast", "react", "plan"] = Field(
        description="fast=direct answer/one tool; react=agent loop; plan=multi-step structured workflow"
    )
    reason: str = Field(description="One-line reason for this routing decision")


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_input: str
    conversation_summary: str
    recent_conversation: str
    intent: str
    provided_fields: list[str]
    clarifying_question: str
    next_step: str
    route_mode: str
    route_reason: str
    patient_hn: str
    weight_kg: float
    renal_cr: float
    current_step: int
    audit_log: list[str]
    execution_result: str
    plan: list[dict]
    plan_summary: str


def build_llm_user_context(state: AgentState) -> str:
    """Combine rolling summary, recent turns, and the current user message."""
    parts: list[str] = []
    summary = (state.get("conversation_summary") or "").strip()
    recent = (state.get("recent_conversation") or "").strip()
    user_input = state.get("user_input", "")

    if summary:
        parts.append(f"[สรุปการสนทนาก่อนหน้า]\n{summary}")
    if recent:
        parts.append(f"[ข้อความล่าสุด]\n{recent}")
    parts.append(f"[ข้อความปัจจุบัน]\n{user_input}")
    return "\n\n".join(parts)


triage_validator = llm.with_structured_output(TriageAndValidation, method="function_calling")
planner_llm = llm.with_structured_output(ExecutionPlan, method="function_calling")
complexity_llm = llm.with_structured_output(ComplexityRoute, method="function_calling")

SYSTEM_PROMPT = """
< Role >
You are a medical AI assistant acting as an Intent & Information Checker for physicians. You sit between the physician and a downstream agent. Your sole responsibility is to (1) identify the physician's intent, (2) verify that all required patient information is present, and (3) either forward the complete request to the agent or ask the physician for missing details.
</ Role >

< Background >
Physicians interact with this system to get clinical decision support, treatment recommendations, drug dosing guidance, differential diagnoses, and similar medical tasks. Before any request can be processed, it must carry a clear intent and a sufficient set of patient data. Incomplete requests waste time and risk unsafe outputs — your job is to be the quality gate.
</ Background >

< Instructions >
1. Identify the intent from the physician's message. Map it to one of the recognized intent categories (see Rules).
2. Check for required fields associated with that intent.
3. If all required fields are present → output a structured handoff object for the agent.
4. If any required fields are missing → do NOT forward. Instead, ask the physician a single, concise follow-up question listing only the missing fields.
5. Keep your tone professional, brief, and clinically appropriate. Never add medical opinions or recommendations yourself.
</ Instructions >

< Rules >
**R1 — Recognized intents, their meaning, and required fields:**
| Intent             | Meaning                                                  | Required Fields                                      |
|--------------------|----------------------------------------------------------|------------------------------------------------------|
| medical_knowledge  | General medical knowledge, disease info, drug info       | (none — proceed immediately)                         |
| patient_data       | Specific patient data (lab results, vitals, etc.)        | patient HN                                           |
| dose_calculation   | Calculate a specific patient's drug dose                 | patient HN, weight (kg), renal function (eGFR or Cr) |
| drug_interaction   | Drug-drug interaction checking                           | (none — proceed immediately)                         |
| emergency          | Emergency / critical situation                           | (none — proceed immediately)                         |

R2 — If the intent is ambiguous, ask the physician to clarify the intent before checking fields.
R3 — Never fabricate, assume, or infer missing patient data. Ask explicitly.
R4 — Ask for missing fields all at once in one message, not one field at a time.
R5 — When forwarding to the agent, output only the structured JSON block — no extra commentary.
R6 — Do not provide any clinical advice, diagnosis, or treatment yourself.
R7 — Use natural conversational Thai, like a doctor talking to a colleague. Be polite but friendly, not robotic.
R8 — A patient's first name or last name alone is NOT a valid patient HN. Only accept an actual 6-digit medical record ID.
R9 — If the physician's message is empty, vague, or does not clearly match any specific intent, default to "medical_knowledge". Do NOT guess "emergency" unless there is an explicit mention of a critical/emergency situation.
R10 — A valid patient HN must be exactly 6 digits (e.g., "123456").
</ Rules >
"""

PLANNER_PROMPT = """You are a medical task planner for physicians. Given a complex request, create an ordered execution plan.

Available tools and their argument fields:
- search_medical_knowledge: set query
- get_patient_labs: set hn (6-digit patient HN)
- get_patient_vitals: set hn
- check_drug_interaction: set drug_a, drug_b
- emergency_protocol: set symptom
- summarize: no extra fields (final synthesis step)
- none: no tool, placeholder step

Rules:
1. Keep plans to 3-6 steps.
2. Always end with a "summarize" step.
3. Use HN from context when calling patient tools.
4. Steps must be concrete and actionable.
5. Respond in the same language context as the user request.
"""

COMPLEXITY_PROMPT = """You route physician requests to the correct execution mode after intent triage.

Modes:
- fast: One direct answer OR a single tool call is enough. Examples: BMI formula, normal lab range, one drug-pair interaction, brief emergency steps for one symptom, simple definition.
- react: Moderate complexity — agent picks tools dynamically in a loop (typically 1-3 tool calls), single primary goal. Examples: fetch labs for one HN, get vitals and explain, one interaction check with summary.
- plan: High complexity — 3+ distinct sequential steps, synthesize across multiple sources, case workup, morning-round summary, problem list, compare guidelines, multiple actions for one HN.

Rules:
1. Judge by MEANING — users may write in Thai or English with varied phrasing (not fixed keywords).
2. dose_calculation that ONLY asks to compute a dose (HN + weight + renal given) → react, NOT plan (simple dose uses a fixed pipeline elsewhere).
3. dose_calculation PLUS workup, monitoring plan, multiple drugs, or multi-part case → plan.
4. When uncertain between react and plan → react.
5. When uncertain between fast and react → fast only if truly trivial.

Output mode and a concise reason (English or Thai)."""

# Soft signals — boost score only, not sole trigger
PLAN_SIGNAL_WORDS = (
    "workup", "morning round", "เปรียบเทียบ", "ครบทุก", "วิเคราะห์ครบ",
    "สรุป case", "problem list", "compare guideline", "หลายขั้น", "ครบให้",
    "ครบทุกมิติ", "to-do", "trend", "ไล่สาเหตุ", "present", "round",
    "monitoring plan", "problem list",
)

FAST_HINT_KEYWORDS = (
    "สูตร", "reference range", "คืออะไร", "definition", "bmi", "normal range",
)

FIELD_ALIASES = {
    "patient hn": "patient HN",
    "hn": "patient HN",
    "patient_id": "patient HN",
    "patient id": "patient HN",
    "weight": "weight",
    "weight (kg)": "weight",
    "น้ำหนัก": "weight",
    "น้ำหนัก (kg)": "weight",
    "renal function": "renal_function",
    "renal_function": "renal_function",
    "renal function (egfr or cr)": "renal_function",
    "cr": "renal_function",
    "creatinine": "renal_function",
    "egfr": "renal_function",
}

REQUIRED_BY_INTENT = {
    "patient_data": ["patient HN"],
    "dose_calculation": ["patient HN", "weight", "renal_function"],
}

FIELD_LABELS = {
    "patient HN": "HN (ตัวเลข 6 หลัก)",
    "weight": "น้ำหนัก (kg)",
    "renal_function": "ค่า Cr หรือ eGFR ล่าสุด",
}


def normalize_fields(fields: list[str]) -> list[str]:
    return list(set(FIELD_ALIASES.get(f.lower().strip(), f) for f in fields))


def build_clarifying_question(missing: list[str]) -> str:
    return (
        "ขอข้อมูลเพิ่มเติม: "
        + ", ".join(FIELD_LABELS.get(f, f) for f in missing)
        + " ด้วยครับ"
    )


def is_bare_numeric_answer(text: str) -> bool:
    return bool(re.match(r"^\d+(?:\.\d+)?$", text.strip()))


def extract_hn(text: str) -> str | None:
    m = re.search(r"\b\d{6}\b", text)
    return m.group(0) if m else None


def extract_cr(text: str) -> float | None:
    m = re.search(r"cr\s*[:=]?\s*(\d+(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1))
    # standalone decimal in renal range when no "kg" context
    if re.search(r"\bkg\b", text, re.I):
        return None
    bare = re.match(r"^(\d+(?:\.\d+)?)$", text.strip())
    if bare:
        val = float(bare.group(1))
        if 0.1 <= val <= 20 and val < 30:
            return val
    return None


def extract_weight(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", text, re.I)
    if m:
        return float(m.group(1))
    bare = re.match(r"^(\d+(?:\.\d+)?)$", text.strip())
    if bare:
        val = float(bare.group(1))
        # plausible adult weight in kg (integer answers like "75")
        if val == int(val) and 30 <= val <= 250:
            return val
    return None


def infer_followup_fields(
    user_input: str,
    previous_question: str,
    existing_fields: list[str],
    intent: str,
    state: AgentState,
) -> tuple[list[str], dict]:
    """Map bare follow-up answers (e.g. '75', '1.2') to clinical fields."""
    if not previous_question.strip():
        return list(existing_fields), {}

    text = user_input.strip()
    lower_q = previous_question.lower()
    fields = list(existing_fields)
    updates: dict = {}

    # carry forward values from prior turns
    if state.get("patient_hn") and "patient HN" not in fields:
        fields.append("patient HN")
    if state.get("weight_kg", 0) > 0 and "weight" not in fields:
        fields.append("weight")
    if state.get("renal_cr", 0) > 0 and "renal_function" not in fields:
        fields.append("renal_function")

    hn = extract_hn(text) or state.get("patient_hn")
    if hn and "patient HN" not in fields:
        fields.append("patient HN")
        updates["patient_hn"] = hn

    weight = extract_weight(text)
    if weight is None and state.get("weight_kg", 0) > 0:
        weight = state["weight_kg"]
    cr = extract_cr(text)
    if cr is None and state.get("renal_cr", 0) > 0:
        cr = state["renal_cr"]

    bare_match = re.match(r"^(\d+(?:\.\d+)?)$", text)
    if bare_match:
        val = float(bare_match.group(1))
        missing_weight = "weight" not in fields
        missing_renal = "renal_function" not in fields

        asks_weight = any(k in lower_q for k in ("น้ำหนัก", "weight", "kg", "กก"))
        asks_renal = any(k in lower_q for k in ("cr", "egfr", "ไต", "renal", "creatinine"))

        if missing_weight and missing_renal:
            # both still needed — disambiguate by value range
            if val == int(val) and 30 <= val <= 250:
                weight = val
            elif 0.1 <= val <= 20:
                cr = val
        elif missing_weight and not missing_renal:
            # only weight left — integer 20-250 is weight
            if val == int(val) and 20 <= val <= 250:
                weight = val
        elif missing_renal and not missing_weight:
            # only renal left — decimal 0.1-20 is Cr/eGFR
            if 0.1 <= val <= 20:
                cr = val
        elif missing_weight and (asks_weight or intent == "dose_calculation"):
            if val == int(val) and 20 <= val <= 250:
                weight = val
        elif missing_renal and (asks_renal or intent == "dose_calculation"):
            if 0.1 <= val <= 20:
                cr = val

    if weight and "weight" not in fields:
        fields.append("weight")
        updates["weight_kg"] = float(weight)
    if cr and "renal_function" not in fields:
        fields.append("renal_function")
        updates["renal_cr"] = float(cr)

    return fields, updates


def deterministic_triage_followup(state: AgentState) -> Command | None:
    """Handle multi-turn field collection without LLM — avoids mis-parsing bare numbers."""
    previous_question = state.get("clarifying_question", "")
    previous_intent = state.get("intent", "")
    user_input = state["user_input"]

    if not previous_question or previous_intent not in REQUIRED_BY_INTENT:
        return None

    existing = normalize_fields(state.get("provided_fields") or [])
    merged, value_updates = infer_followup_fields(
        user_input, previous_question, existing, previous_intent, state
    )
    merged = normalize_fields(merged)

    has_hn = re.search(r"\b\d{6}\b", user_input)
    if has_hn and "patient HN" not in merged:
        merged.append("patient HN")
        value_updates.setdefault("patient_hn", has_hn.group(0))

    required = REQUIRED_BY_INTENT[previous_intent]
    still_missing = [f for f in required if f not in merged]

    if still_missing:
        return Command(
            goto=END,
            update={
                "intent": previous_intent,
                "provided_fields": merged,
                "clarifying_question": build_clarifying_question(still_missing),
                "next_step": "ask_user",
                **value_updates,
            },
        )

    return Command(
        goto="route_after_triage",
        update={
            "intent": previous_intent,
            "provided_fields": merged,
            "clarifying_question": "",
            "next_step": "route",
            **value_updates,
        },
    )


def complexity_signal_score(text: str) -> int:
    """Heuristic score — higher means more likely to need plan mode."""
    lower = text.lower()
    score = 0

    if len(text) > 120:
        score += 1
    if len(text) > 220:
        score += 1
    if any(k in lower for k in PLAN_SIGNAL_WORDS):
        score += 2

    multi_verbs = len(re.findall(
        r"(และ|พร้อม|จากนั้น|แล้ว|compare|summarize|เปรียบ|สรุป|ตรวจ|ดึง|workup|analyze|ไล่|monitor)",
        lower,
        re.I,
    ))
    if multi_verbs >= 2:
        score += 2
    if multi_verbs >= 4:
        score += 1

    if extract_hn(text) and len(text.split()) > 12:
        score += 1
    if re.search(r"\d+[\.)]\s", text):
        score += 1

    return score


def is_clearly_fast(state: AgentState) -> bool:
    text = state["user_input"]
    lower = text.lower()
    intent = state["intent"]

    if extract_hn(text):
        return False

    # medical_knowledge ทุกคำถาม → ReAct + Knowledge Base (detect จาก intent ไม่ใช่ keyword)
    if intent == "medical_knowledge":
        return False

    if intent not in ("drug_interaction", "emergency"):
        return False

    if any(k in lower for k in FAST_HINT_KEYWORDS):
        return True

    if len(text) >= 120:
        return False

    if intent == "emergency":
        return True

    if intent == "drug_interaction":
        drug_markers = (" + ", " กับ ", " and ", " vs ", " interact")
        return sum(1 for m in drug_markers if m in lower) <= 1

    return False


def classify_with_llm(state: AgentState, signals: int) -> ComplexityRoute:
    try:
        return complexity_llm.invoke([
            SystemMessage(content=COMPLEXITY_PROMPT),
            HumanMessage(content=(
                f"Intent: {state['intent']}\n"
                f"Provided fields: {state.get('provided_fields', [])}\n"
                f"Complexity signal score (0-8, higher=more complex): {signals}\n"
                f"User message: {state['user_input']}"
            )),
        ])
    except Exception:
        return ComplexityRoute(mode="react", reason="LLM classifier failed — default to react")


def classify_complexity(state: AgentState) -> tuple[Literal["fast", "react", "pipeline", "plan"], str]:
    text = state["user_input"]
    intent = state["intent"]
    signals = complexity_signal_score(text)

    # patient_data ต้องเรียก tool (get_patient_labs/vitals) — ไม่ใช้ FAST ที่ตอบจาก LLM ตรงๆ
    if intent == "patient_data":
        return "react", "patient_data → ReAct with lab/vitals tools"

    # Rule: simple dose_calculation → fixed pipeline (unless clearly multi-part)
    if intent == "dose_calculation":
        if signals >= 4:
            route = classify_with_llm(state, signals)
            if route.mode == "plan":
                return "plan", route.reason
        return "pipeline", "dose_calculation with standard fields → fixed audit pipeline"

    # medical_knowledge (detect จาก triage intent) → ReAct + Knowledge Base เสมอ
    if intent == "medical_knowledge":
        return "react", "medical_knowledge → Knowledge Base search"

    # Rule: obvious fast cases — skip LLM
    if is_clearly_fast(state) and signals <= 1:
        return "fast", "short general question, no patient HN, no multi-step signals"

    # LLM decides fast / react / plan from meaning (not keywords)
    route = classify_with_llm(state, signals)
    mode = route.mode

    # Guard: LLM said fast but signals suggest complexity → upgrade to react
    if mode == "fast" and signals >= 2:
        return "react", f"LLM said fast but signal score={signals} → upgraded to react. {route.reason}"

    # Guard: LLM said plan but very low signals and simple patient_data → downgrade to react
    if mode == "plan" and signals <= 1 and intent == "patient_data" and len(text) < 80:
        return "react", f"Simple patient_data fetch → react instead of plan. {route.reason}"

    return mode, route.reason


@tool
def search_medical_knowledge(query: str) -> str:
    """ค้นหาความรู้ทางการแพทย์จาก AWS Bedrock Knowledge Base"""
    from backend.rag.knowledge_base import search_medical_knowledge as kb_search

    return kb_search(query)


@tool
def get_patient_labs(hn: str) -> str:
    """ดึงผล lab ของคนไข้จาก HN 6 หลัก"""
    from backend.data.labs import fetch_lab_results

    return fetch_lab_results(hn)


@tool
def get_patient_vitals(hn: str) -> str:
    """ดึง vital signs ของคนไข้จาก HN 6 หลัก"""
    return f"[mock] Vitals HN {hn}: BP 120/80, HR 78, Temp 37.0°C"


@tool
def check_drug_interaction(drug_a: str, drug_b: str) -> str:
    """ตรวจ drug-drug interaction ระหว่างยา 2 ตัว"""
    return f"[mock] {drug_a} + {drug_b}: moderate interaction — monitor QT interval"


@tool
def emergency_protocol(symptom: str) -> str:
    """ดึง emergency protocol ตามอาการ"""
    return f"[mock] Emergency protocol สำหรับ '{symptom}': ABC, stat labs, consult senior immediately"


AGENT_TOOLS = [
    search_medical_knowledge,
    get_patient_labs,
    get_patient_vitals,
    check_drug_interaction,
    emergency_protocol,
]
TOOL_BY_NAME = {t.name: t for t in AGENT_TOOLS}
llm_with_tools = llm.bind_tools(AGENT_TOOLS)

AGENT_SYSTEM_PROMPT = """คุณคือ Medical Agent สำหรับแพทย์ ตอบเป็นภาษาไทยที่ถูกต้อง ชัดเจน

Triage ระบุแล้วว่า:
- intent: {intent}
- fields ที่มี: {provided_fields}
- HN (ถ้ามี): {patient_hn}

เลือก tools ที่เหมาะสมตาม intent:
- medical_knowledge → search_medical_knowledge (เรียกก่อนตอบเสมอ)
- patient_data → get_patient_labs หรือ get_patient_vitals (ใช้ HN จาก context)
- drug_interaction → check_drug_interaction
- emergency → emergency_protocol (ตอบเร็ว กระชับ เน้น action)

ห้ามถามข้อมูลที่ triage ควรถามไปแล้ว
เมื่อได้ผลจาก tools แล้ว สรุปให้แพทย์อ่านง่าย

สำคัญ — ภาษาไทยในเอกสารยา (ฉลาก/SmPC):
- "สมมูลกับ" / "equivalent to" หมายถึง **ปริมาณสารออกฤทธิ์** ที่ salt form เท่ากับ (เช่น ไฮโดรคลอไรด์ 500 mg สมมูลกับ แวนโคมัยซิน 500 mg)
- **ไม่ใช่** การเปรียบเทียบยาทางเลือก (เช่น linezolid, daptomycin)
- ถ้ามีผลจาก Knowledge Base ให้ตอบจากเอกสารนั้นเป็นหลัก ห้ามแต่งยาทดแทนที่ไม่มีในเอกสาร

สำคัญ — คำถามเรื่องผลกระทบ / อันตรกิริยาระหว่างยา:
- ตอบจาก section **อันตรกิริยากับยาอื่น / adverse effects / toxicity** เท่านั้น
- **ห้าม**ตอบด้วยข้อบ่งใช้หรือประสิทธิภาพการใช้ร่วมกัน (เช่น endocarditis synergy) แทนผลข้างเคียง
- ถ้าเอกสารระบุพิษต่อไต/ototoxicity/interaction ให้ตอบประเด็นนั้นเป็นหลัก
- ถ้าไม่พบข้อมูล interaction ในเอกสาร ให้บอกชัดว่าไม่พบ ห้ามเดาจากความรู้ทั่วไป
"""

FAST_SYSTEM_PROMPT = """คุณคือผู้ช่วยแพทย์ ตอบสั้น กระชับ เป็นภาษาไทย
intent: {intent}
ตอบจากความรู้ทั่วไป ไม่ต้องถามข้อมูลเพิ่ม
"""

DOSE_PIPELINE_STEPS = [
    "verify_patient_identity",
    "fetch_renal_function",
    "calculate_dose",
    "generate_summary",
]


def _dose_verify(hn: str) -> str:
    return f"verified HN={hn}"


def _dose_fetch_renal(hn: str, cr: float) -> str:
    return f"renal: HN={hn}, Cr={cr}, eGFR_est=72"


def _dose_calculate(weight: float, cr: float) -> str:
    dose_mg = round(weight * 15 * (1.2 / cr), 1)
    return f"recommended loading dose: {dose_mg} mg IV"


def _run_tool_by_name(tool_name: str, tool_args: dict, state: AgentState) -> str:
    if tool_name in ("summarize", "none"):
        return ""

    tool_fn = TOOL_BY_NAME.get(tool_name)
    if not tool_fn:
        return f"[error] unknown tool: {tool_name}"

    args = dict(tool_args)
    if tool_name in ("get_patient_labs", "get_patient_vitals"):
        args.setdefault("hn", state.get("patient_hn") or extract_hn(state["user_input"]) or "")
    return tool_fn.invoke(args)


def _summarize_results(state: AgentState, step_results: list[str]) -> str:
    hn = state.get("patient_hn") or extract_hn(state["user_input"]) or "ไม่มี"
    context = "\n".join(step_results)
    response = llm.invoke([
        SystemMessage(content=(
            f"สรุปผลให้แพทย์เป็นภาษาไทย intent={state['intent']} HN={hn}\n"
            f"Plan: {state.get('plan_summary', '')}"
        )),
        HumanMessage(content=f"ผลจากแต่ละ step:\n{context}\n\nคำถามเดิม:\n{build_llm_user_context(state)}"),
    ])
    return response.content if isinstance(response.content, str) else str(response.content)


def triage_validator_node(state: AgentState) -> Command:
    """เรียก LLM เพื่อ classify intent + ตรวจสอบ fields ในครั้งเดียว"""
    user_input = state["user_input"]
    existing_fields = state.get("provided_fields") or []
    previous_intent = state.get("intent", "")
    previous_question = state.get("clarifying_question", "")

    if not user_input.strip():
        if previous_question:
            return Command(
                goto=END,
                update={
                    "intent": previous_intent,
                    "provided_fields": existing_fields,
                    "clarifying_question": previous_question,
                    "next_step": "ask_user",
                },
            )
        return Command(
            goto="route_after_triage",
            update={
                "intent": "medical_knowledge",
                "provided_fields": existing_fields,
                "clarifying_question": "",
                "next_step": "route",
            },
        )

    if not previous_question:
        existing_fields = []

    # multi-turn: use deterministic parser (skip LLM) for field follow-ups
    if previous_question and previous_intent in REQUIRED_BY_INTENT:
        followup_cmd = deterministic_triage_followup(state)
        if followup_cmd is not None:
            return followup_cmd

    context_parts = [build_llm_user_context(state)]
    if previous_question:
        context_parts.append(f"Previous question (being answered): {previous_question}")
    if existing_fields:
        context_parts.append(f"Already have: {', '.join(existing_fields)}")
    context = "\n\n".join(context_parts)

    result: TriageAndValidation = triage_validator.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=context),
    ])

    # keep intent stable across multi-turn field collection
    if previous_question and previous_intent:
        result.intent = previous_intent  # type: ignore[assignment]

    merged = list(set(existing_fields + result.provided_fields))
    merged = normalize_fields(merged)
    existing_fields = normalize_fields(existing_fields)

    if previous_question:
        inferred_fields, value_updates = infer_followup_fields(
            user_input, previous_question, merged, result.intent, state
        )
        merged = normalize_fields(inferred_fields)
    else:
        value_updates = {}

    required = REQUIRED_BY_INTENT.get(result.intent, [])
    still_missing = [f for f in required if f not in merged]

    has_hn = re.search(r"\b\d{6}\b", user_input)

    if has_hn and result.intent in ("patient_data", "dose_calculation"):
        if "patient HN" not in merged:
            merged.append("patient HN")
        if "patient HN" in still_missing:
            still_missing.remove("patient HN")

    hn_is_new_from_llm = (
        "patient HN" in result.provided_fields and "patient HN" not in existing_fields
    )
    if hn_is_new_from_llm and not has_hn and "patient HN" in merged:
        merged.remove("patient HN")
        if "patient HN" not in still_missing:
            still_missing.append("patient HN")

    result.missing_fields = [f for f in normalize_fields(result.missing_fields) if f not in merged]

    if still_missing:
        clarifying_question = build_clarifying_question(still_missing)
        return Command(
            goto=END,
            update={
                "intent": result.intent,
                "provided_fields": merged,
                "clarifying_question": clarifying_question,
                "next_step": "ask_user",
                **value_updates,
            },
        )

    if result.intent in ("medical_knowledge", "drug_interaction", "emergency"):
        pass  # no required fields

    return Command(
        goto="route_after_triage",
        update={
            "intent": result.intent,
            "provided_fields": merged,
            "clarifying_question": "",
            "next_step": "route",
            **value_updates,
        },
    )


def route_after_triage(state: AgentState) -> Command:
    hn = extract_hn(state["user_input"]) or state.get("patient_hn") or ""
    weight = extract_weight(state["user_input"])
    if weight is None and state.get("weight_kg", 0) > 0:
        weight = state["weight_kg"]
    cr = extract_cr(state["user_input"])
    if cr is None and state.get("renal_cr", 0) > 0:
        cr = state["renal_cr"]

    base_update = {
        "patient_hn": hn,
        "weight_kg": weight or 0.0,
        "renal_cr": cr or 0.0,
    }

    mode, reason = classify_complexity({**state, **base_update})

    route_update = {**base_update, "route_reason": reason}

    if mode == "pipeline":
        return Command(
            goto="dose_pipeline_node",
            update={
                **route_update,
                "route_mode": "pipeline",
                "current_step": 0,
                "audit_log": [],
                "next_step": "execute",
            },
        )

    if mode == "plan":
        return Command(
            goto="planner_node",
            update={**route_update, "route_mode": "plan", "next_step": "plan"},
        )

    if mode == "fast":
        return Command(
            goto="fast_node",
            update={**route_update, "route_mode": "fast", "next_step": "fast"},
        )

    return Command(
        goto="prepare_agent_node",
        update={**route_update, "route_mode": "react", "next_step": "agent"},
    )


def fast_node(state: AgentState) -> Command:
    intent = state["intent"]
    user_context = build_llm_user_context(state)

    if intent == "drug_interaction":
        llm_one_tool = llm.bind_tools([check_drug_interaction])
        response = llm_one_tool.invoke([
            SystemMessage(content="Extract two drug names and call check_drug_interaction once."),
            HumanMessage(content=user_context),
        ])
        if response.tool_calls:
            tc = response.tool_calls[0]
            tool_result = check_drug_interaction.invoke(tc["args"])
            text = llm.invoke([
                HumanMessage(content=f"สรุปเป็นภาษาไทยสำหรับแพทย์:\n{tool_result}\nคำถาม: {user_context}"),
            ]).content
        else:
            text = response.content if isinstance(response.content, str) else str(response.content)

    elif intent == "emergency":
        llm_one_tool = llm.bind_tools([emergency_protocol])
        response = llm_one_tool.invoke([
            SystemMessage(content="Call emergency_protocol once with the main symptom."),
            HumanMessage(content=user_context),
        ])
        if response.tool_calls:
            tc = response.tool_calls[0]
            tool_result = emergency_protocol.invoke(tc["args"])
            text = llm.invoke([
                HumanMessage(content=f"สรุป action list ภาษาไทย:\n{tool_result}\nคำถาม: {user_context}"),
            ]).content
        else:
            text = response.content if isinstance(response.content, str) else str(response.content)

    else:
        text = llm.invoke([
            SystemMessage(content=FAST_SYSTEM_PROMPT.format(intent=intent)),
            HumanMessage(content=user_context),
        ]).content

    text = text if isinstance(text, str) else str(text)
    return Command(
        goto=END,
        update={
            "execution_result": text,
            "clarifying_question": text,
            "next_step": "done",
        },
    )


def planner_node(state: AgentState) -> Command:
    hn = state.get("patient_hn") or extract_hn(state["user_input"]) or "ไม่มี"
    plan: ExecutionPlan = planner_llm.invoke([
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=(
            f"Intent: {state['intent']}\n"
            f"User request:\n{build_llm_user_context(state)}\n"
            f"Patient HN: {hn}\n"
            f"Available fields: {state.get('provided_fields', [])}\n"
            f"Weight kg: {state.get('weight_kg')}\n"
            f"Cr: {state.get('renal_cr')}"
        )),
    ])
    return Command(
        goto="plan_executor_node",
        update={
            "plan": [step.model_dump() for step in plan.steps],
            "plan_summary": plan.summary,
            "current_step": 0,
            "audit_log": [],
            "next_step": "execute",
        },
    )


def plan_executor_node(state: AgentState) -> Command:
    steps = state.get("plan") or []
    step_idx = state.get("current_step", 0)
    audit = list(state.get("audit_log") or [])

    if step_idx >= len(steps):
        all_results = [line.split(": ", 1)[-1] for line in audit if ": " in line]
        final = _summarize_results(state, all_results)
        return Command(
            goto=END,
            update={
                "execution_result": final,
                "clarifying_question": final,
                "next_step": "done",
            },
        )

    step = steps[step_idx]
    tool_name = step.get("tool", "none")

    if tool_name == "summarize":
        prior = [line.split(": ", 1)[-1] for line in audit if ": " in line]
        result = _summarize_results(state, prior)
    elif tool_name == "none":
        result = step.get("description", "skipped")
    else:
        result = _run_tool_by_name(tool_name, plan_step_to_tool_args(step), state)

    audit.append(f"[plan {step_idx + 1}/{len(steps)}] {step.get('action', tool_name)}: {result}")

    if step_idx + 1 < len(steps):
        return Command(
            goto="plan_executor_node",
            update={"current_step": step_idx + 1, "audit_log": audit},
        )

    if tool_name != "summarize":
        all_results = [line.split(": ", 1)[-1] for line in audit if ": " in line]
        final = _summarize_results(state, all_results)
    else:
        final = result

    return Command(
        goto=END,
        update={
            "execution_result": final,
            "clarifying_question": final,
            "audit_log": audit,
            "next_step": "done",
        },
    )


def prepare_agent_node(state: AgentState) -> Command:
    hn = state.get("patient_hn") or extract_hn(state["user_input"]) or "ไม่มี"
    system = AGENT_SYSTEM_PROMPT.format(
        intent=state["intent"],
        provided_fields=state.get("provided_fields", []),
        patient_hn=hn,
    )
    user_context = build_llm_user_context(state)

    messages: list = [SystemMessage(content=system)]

    # medical_knowledge: ค้น KB ก่อนเสมอ (ไม่พึ่ง LLM ว่าจะเรียก tool เองหรือไม่)
    if state["intent"] == "medical_knowledge":
        kb_query = state["user_input"].strip() or user_context
        kb_result = search_medical_knowledge.invoke({"query": kb_query})
        messages.append(
            SystemMessage(
                content=(
                    "ผลจาก Knowledge Base (ใช้เป็นแหล่งอ้างอิงหลัก):\n"
                    f"{kb_result}\n\n"
                    "ตอบจากเอกสารข้างต้นเป็นหลัก หากไม่พบข้อมูล ให้บอกว่าไม่พบใน knowledge base"
                )
            )
        )

    messages.append(HumanMessage(content=user_context))

    return Command(
        goto="agent_node",
        update={"messages": messages},
    )


def agent_node(state: AgentState) -> dict:
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def finalize_agent_node(state: AgentState) -> Command:
    last = state["messages"][-1]
    text = last.content if isinstance(last.content, str) else str(last.content)
    return Command(
        goto=END,
        update={
            "execution_result": text,
            "clarifying_question": text,
            "next_step": "done",
        },
    )


def dose_pipeline_node(state: AgentState) -> Command:
    step_idx = state.get("current_step", 0)
    hn = state.get("patient_hn") or extract_hn(state["user_input"]) or ""
    weight = state.get("weight_kg") or extract_weight(state["user_input"]) or 0.0
    cr = state.get("renal_cr") or extract_cr(state["user_input"]) or 0.0
    audit = list(state.get("audit_log") or [])

    step_name = DOSE_PIPELINE_STEPS[step_idx]

    if step_name == "verify_patient_identity":
        result = _dose_verify(hn)
    elif step_name == "fetch_renal_function":
        result = _dose_fetch_renal(hn, cr)
    elif step_name == "calculate_dose":
        result = _dose_calculate(weight, cr)
    else:
        result = (
            f"สรุป dose calculation\n"
            f"HN: {hn}, น้ำหนัก: {weight} kg, Cr: {cr}\n"
            f"ผล: {_dose_calculate(weight, cr)}"
        )

    audit.append(f"[pipeline {step_idx + 1}/{len(DOSE_PIPELINE_STEPS)}] {step_name}: {result}")

    if step_idx + 1 < len(DOSE_PIPELINE_STEPS):
        return Command(
            goto="dose_pipeline_node",
            update={
                "current_step": step_idx + 1,
                "audit_log": audit,
                "patient_hn": hn,
                "weight_kg": weight,
                "renal_cr": cr,
            },
        )

    return Command(
        goto=END,
        update={
            "execution_result": result,
            "clarifying_question": result,
            "audit_log": audit,
            "next_step": "done",
        },
    )


def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("triage_validator_node", triage_validator_node)
    workflow.add_node("route_after_triage", route_after_triage)
    workflow.add_node("fast_node", fast_node)
    workflow.add_node("planner_node", planner_node)
    workflow.add_node("plan_executor_node", plan_executor_node)
    workflow.add_node("prepare_agent_node", prepare_agent_node)
    workflow.add_node("agent_node", agent_node)
    workflow.add_node("tools_node", ToolNode(AGENT_TOOLS))
    workflow.add_node("finalize_agent_node", finalize_agent_node)
    workflow.add_node("dose_pipeline_node", dose_pipeline_node)

    workflow.add_edge(START, "triage_validator_node")
    workflow.add_conditional_edges(
        "agent_node",
        tools_condition,
        {"tools": "tools_node", END: "finalize_agent_node"},
    )
    workflow.add_edge("tools_node", "agent_node")

    return workflow.compile()


def fresh_state() -> AgentState:
    return {
        "messages": [],
        "user_input": "",
        "conversation_summary": "",
        "recent_conversation": "",
        "intent": "",
        "provided_fields": [],
        "clarifying_question": "",
        "next_step": "",
        "route_mode": "",
        "route_reason": "",
        "patient_hn": "",
        "weight_kg": 0.0,
        "renal_cr": 0.0,
        "current_step": 0,
        "audit_log": [],
        "execution_result": "",
        "plan": [],
        "plan_summary": "",
    }


MODE_LABELS = {
    "fast": "FAST",
    "react": "ReAct",
    "pipeline": "Pipeline",
    "plan": "Plan+Execute",
}


def format_agent_result(result: AgentState) -> dict:
    """Convert graph state to API-friendly response."""
    mode = MODE_LABELS.get(result.get("route_mode", ""), "")
    if result.get("next_step") == "ask_user":
        content = result.get("clarifying_question", "")
    else:
        content = result.get("clarifying_question") or result.get("execution_result", "")

    return {
        "content": content,
        "intent": result.get("intent", ""),
        "route_mode": result.get("route_mode", ""),
        "route_mode_label": mode,
        "route_reason": result.get("route_reason", ""),
        "plan_summary": result.get("plan_summary", ""),
        "audit_log": result.get("audit_log") or [],
        "next_step": result.get("next_step", ""),
        "awaiting_user": result.get("next_step") == "ask_user",
        "done": result.get("next_step") == "done",
    }


def next_agent_state(result: AgentState) -> AgentState:
    if result.get("next_step") == "done":
        return fresh_state()
    return result
