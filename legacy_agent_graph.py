from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.types import Command 
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field
from typing import Literal, TypedDict, Annotated
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import re
import json


load_dotenv()
# print("Loaded OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY")) 


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


# ============================================================
# State Schema
# ============================================================
# class TriageState(TypedDict):
#     user_input: str
#     intent: str
#     provided_fields: list[str]
#     clarifying_question: str
#     next_step: str
#     plan: list[dict]          # แผนที่ planner สร้าง
#     plan_summary: str
#     current_step: int
#     execution_result: str     # ผลลัพธ์สุดท้าย
#     patient_hn: str   


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    user_input: str
    intent: str
    provided_fields: list[str]
    clarifying_question: str
    next_step: str
    patient_hn: str
    weight_kg: float
    renal_cr: float
    # dose pipeline only
    current_step: int
    audit_log: list[str]
    execution_result: str


# ============================================================
# LLM Setup
# ============================================================
# llm = init_chat_model("openai:gpt-4o-mini")
llm = ChatOpenAI(
    model="openai/gpt-4o",
    openai_api_key=os.getenv("OPEN_ROUTER_KEY"),
    openai_api_base="https://openrouter.ai/api/v1",
)


triage_validator = llm.with_structured_output(TriageAndValidation)

# SYSTEM_PROMPT = """คุณคือผู้ช่วยทางการแพทย์ ตอบเป็นภาษาไทยที่ถูกต้อง ชัดเจน

# วิเคราะห์ข้อความผู้ใช้และระบุ:
# 1. intent — เจตนาของผู้ใช้
# 2. provided_fields — ข้อมูลที่มีอยู่ในข้อความแล้ว
# 3. missing_fields — ข้อมูลที่จำเป็นต้องใช้แต่ยังไม่มี
# 4. clarifying_question — ถ้าขาดข้อมูลให้ถามอย่างสุภาพ, ถ้าครบแล้วให้เป็นข้อความว่าง

# แต่ละ intent ต้องการข้อมูลดังนี้:
# - medical_knowledge: ไม่ต้องการข้อมูลเพิ่มเติม
# - patient_data: ต้องการ patient_id (HN)
# - dose_calculation: ต้องการ patient_id, weight, renal_function
# - drug_interaction: ต้องการ patient_id
# - emergency: ไม่ต้องการข้อมูลเพิ่มเติม"""


# Triage prompt
SYSTEM_PROMPT = """
< Role >
You are a medical AI assistant acting as an Intent & Information Checker for physicians. You sit between the physician and a downstream Planner agent. Your sole responsibility is to (1) identify the physician's intent, (2) verify that all required patient information is present, and (3) either forward the complete request to the Planner or ask the physician for missing details.
</ Role >


< Background >
Physicians interact with this system to get clinical decision support, treatment recommendations, drug dosing guidance, differential diagnoses, and similar medical tasks. Before any request can be processed by the Planner, it must carry a clear intent and a sufficient set of patient data. Incomplete requests waste time and risk unsafe outputs — your job is to be the quality gate.
</ Background >


< Instructions >

Instructions

1.Identify the intent from the physician's message. Map it to one of the recognized intent categories (see Rules).
2.Check for required fields associated with that intent.
3.If all required fields are present → output a structured handoff object for the Planner (see output format below).
4.If any required fields are missing → do NOT forward to the Planner. Instead, ask the physician a single, concise follow-up question listing only the missing fields.
5.Keep your tone professional, brief, and clinically appropriate. Never add medical opinions or recommendations yourself.

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
R5 — When forwarding to the Planner, output only the structured JSON block — no extra commentary.
R6 — Do not provide any clinical advice, diagnosis, or treatment yourself.
R6 — Do not provide any clinical advice, diagnosis, or treatment yourself.
R7 — Use natural conversational Thai, like a doctor talking to a colleague. Be polite but friendly, not robotic.
R8 — A patient's first name or last name alone is NOT a valid patient HN / hospital number. Only accept an actual numeric or alphanumeric medical record ID as patient HN.
R9 — If the physician's message is empty, vague, or does not clearly match any specific intent, default to "medical_knowledge". Do NOT guess "emergency" unless there is an explicit mention of a critical/emergency situation.
R10 — A valid patient HN must be exactly 6 digits (e.g., "123456"). Do NOT accept names, short numbers, or anything that is not exactly 6 numeric digits as a patient HN. If the user provides something that looks like a name, a nickname, or a number that is not 6 digits, ask for the correct 6-digit HN.

</ Rules >


< Few shot examples >


User: Could you show me Yosvarit's lab results?
Assistant (internal): intent=patient_data, provided_fields=[], missing_fields=[patient HN]
clarifying_question: "ขอ HN ของคุณ Yosvarit ด้วยครับ"

User: HN 12345
Assistant (internal): intent=patient_data, provided_fields=[patient HN], missing_fields=[]
clarifying_question: ""  (empty — proceed to planner)

User: ขอสูตรคำนวณ BMI หน่อย
Assistant (internal): intent=medical_knowledge, provided_fields=[], missing_fields=[]
clarifying_question: ""  (empty — proceed to planner)

User: คำนวณ BMI ให้ HN 12345 หนัก 70 kg Cr 1.2
Assistant (internal): intent=dose_calculation, provided_fields=[patient HN, weight, renal function], missing_fields=[]
clarifying_question: ""  (empty — proceed to planner)

</ Few shot examples >
"""


# ============================================================
# Single Node — ทำทั้ง triage + validation
# ============================================================

def triage_validator_node(state: TriageState) -> Command:
    """เรียก LLM เพื่อ classify intent + ตรวจสอบ fields ในครั้งเดียว"""
    user_input = state["user_input"]
    existing_fields = state.get("provided_fields") or []
    previous_intent = state.get("intent", "")
    previous_question = state.get("clarifying_question", "")

    # ✅ ถ้า user ไม่ได้พิมพ์อะไร:
    if not user_input.strip():
        if previous_question:
            return Command(
                goto=END,
                update={
                    "intent": previous_intent,
                    "provided_fields": existing_fields,
                    "clarifying_question": previous_question,
                    "next_step": "ask_user",
                }
            )
        return Command(
            goto="planner_node",
            update={
                "intent": "medical_knowledge",
                "provided_fields": existing_fields,
                "clarifying_question": "",
                "next_step": "planner",
            }
        )

    # 🧹 ไม่มีคำถามค้าง → เป็น request ใหม่ → ล้างข้อมูลคนไข้เก่า
    if not previous_question:
        existing_fields = []

    # สร้าง context แบบมีประวัติ
    context_parts = [f"User message: {user_input}"]
    if previous_question:
        context_parts.append(f"Previous question (being answered): {previous_question}")
    if existing_fields:
        context_parts.append(f"Already have: {', '.join(existing_fields)}")
    context = "\n\n".join(context_parts)

    # ===== เรียก LLM (ทำครั้งเดียว) =====
    result: TriageAndValidation = triage_validator.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=context),
    ])

    # merge provided_fields เดิม + อันใหม่จาก LLM
    merged = list(set(existing_fields + result.provided_fields))

    FIELD_ALIASES = {
        "patient hn": "patient HN",
        "hn": "patient HN",
        "patient_id": "patient HN",
        "patient id": "patient HN",
        "weight": "weight",
        "weight (kg)": "weight",
        "น้ำหนัก": "weight",
        "renal function": "renal_function",
        "renal_function": "renal_function",
        "cr": "renal_function",
        "creatinine": "renal_function",
        "egfr": "renal_function",
    }
    merged = list(set(FIELD_ALIASES.get(f.lower(), f) for f in merged))
    existing_fields = list(set(FIELD_ALIASES.get(f.lower(), f) for f in existing_fields))

    # 🛡️ SAFETY NET: ตรวจซ้ำด้วยกฎ deterministic
    REQUIRED_BY_INTENT = {
        "patient_data": ["patient HN"],
        "dose_calculation": ["patient HN", "weight", "renal_function"],
    }
    required = REQUIRED_BY_INTENT.get(result.intent, [])
    still_missing = [f for f in required if f not in merged]

    # 🔢 HN ต้องเป็นตัวเลข 6 หลัก
    has_hn = re.search(r'\b\d{6}\b', user_input)

    if has_hn and result.intent in ("patient_data", "dose_calculation"):
        if "patient HN" not in merged:
            merged.append("patient HN")
        if "patient HN" in still_missing:
            still_missing.remove("patient HN")

    hn_is_new_from_llm = "patient HN" in result.provided_fields and "patient HN" not in existing_fields
    if hn_is_new_from_llm and not has_hn and "patient HN" in merged:
        merged.remove("patient HN")
        if "patient HN" not in still_missing:
            still_missing.append("patient HN")

    result.missing_fields = [f for f in result.missing_fields if f not in merged]

    if still_missing:
        result.missing_fields = list(set(result.missing_fields + still_missing))
        if not result.clarifying_question:
            labels = {"patient HN": "HN (ตัวเลข 6 หลัก)", "weight": "น้ำหนัก (kg)", "renal_function": "ค่า Cr ล่าสุด"}
            result.clarifying_question = "ขอข้อมูลเพิ่มเติม: " + ", ".join(labels.get(f, f) for f in still_missing) + " ด้วยครับ"

    if result.intent in ("medical_knowledge", "drug_interaction", "emergency"):
        result.missing_fields = []

    if result.missing_fields:
        return Command(
            goto=END,
            update={
                "intent": result.intent,
                "provided_fields": merged,
                "clarifying_question": result.clarifying_question,
                "next_step": "ask_user",
            }
        )

    return Command(
        goto="planner_node",
        update={
            "intent": result.intent,
            "provided_fields": merged,
            "clarifying_question": "",
            "next_step": "planner",
        }
    )


def planner_node(state: TriageState) -> Command:
    plan = llm.invoke([
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=f"""
Intent: {state['intent']}
User request: {state['user_input']}
Available fields: {state['provided_fields']}
"""),
    ])
    return Command(
        goto="executor_node",
        update={
            "plan": plan.steps,
            "plan_summary": plan.summary,
            "current_step": 0,
            "next_step": "execute",
        },
    )






# ============================================================
# Routing
# ============================================================
# def should_ask_or_continue(state: TriageState) -> Literal["planner_node", "__end__"]:
#     if state.get("next_step") == "ask_user":
#         return "__end__"
#     return "planner_node"



# ============================================================
# Build Graph
# ============================================================
def build_graph() -> StateGraph:
    workflow = StateGraph(TriageState)
    workflow.add_node("triage_validator_node", triage_validator_node)
    workflow.add_node("planner_node", planner_node)
    workflow.set_entry_point("triage_validator_node")
    # ไม่ต้องมี conditional_edges หรือ add_edge — Command จัดการ routing เอง
    return workflow.compile()






# ============================================================
# Interactive Chat Loop (like ChatGPT / Claude / Gemini)
# ============================================================
print("=" * 60)
print("🩺 Medical Triage Assistant — พิมพ์ข้อความของคุณ (พิมพ์ 'exit' เพื่อออก)")
print("=" * 60)

app = build_graph()

state = {
    "user_input": "",
    "intent": "",
    "provided_fields": [],
    "clarifying_question": "",
    "next_step": "",
}

while True:
    user_input = input("\nคุณ: ")
    if user_input.lower() in ("exit", "quit", "ออก"):
        print("👋 ลาก่อน!")
        break
    
    # เอาไว้ เช็คว่า graph เป็นยังไง
    app.get_graph().draw_mermaid_png(output_file_path="workflow_graph.png")

    state["user_input"] = user_input

    result = app.invoke(state)

    print(f"\n🤖 Assistant:", end=" ")
    if result.get("next_step") == "ask_user":
        print(f"[{result['intent']}] {result['clarifying_question']}")
    else:
        print(f"[{result['intent']}] ✅ ข้อมูลครบแล้ว! ดำเนินการต่อ...")

    if result.get("next_step") == "done":
        # 🧹 Request จบแล้ว → ล้าง state ให้สดใหม่ ไม่ให้ข้อมูลเก่าหลุดไป request หน้า
        state = {
            "user_input": "",
            "intent": "",
            "provided_fields": [],
            "clarifying_question": "",
            "next_step": "",
        }
    else:
        state = result