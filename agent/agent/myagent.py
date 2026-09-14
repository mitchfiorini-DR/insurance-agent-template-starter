import math
import os
from typing import Any

import datarobot as dr
import litellm
from datarobot.models.dataset import Dataset
from datarobot_genai.core.agents import make_system_prompt
from datarobot_genai.langgraph.agent import datarobot_agent_class_from_langgraph
from datarobot_predict.deployment import predict
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool, tool
from langgraph.graph import END, START, MessagesState, StateGraph

litellm.modify_params = True

DATASET_ID = "6a84e3f4bd4eb9abe94a66d4"
FRAUD_DEPLOYMENT_ID = "6a8734c14864b60d101e7db6"
DAMAGE_DEPLOYMENT_ID = "6a87421021f6a5e546f65279"
ANOMALY_DEPLOYMENT_ID = "6a8747e921f2ad7a801e7aff"

EXTRA_COLS = [
    "base_repair_component",
    "driver_age",
    "repair_estimate_path",
    "total_estimate",
    "vehicle_current_value",
    "image_provided",
    "fnol_path",
    "police_report_path",
    "damage_photo_path",
    "medical_summary_path",
    "prior_claims_count",
]

prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert P&C motor insurance claims processing assistant. "
            "You analyze FNOL records, score claims using predictive models, and provide "
            "clear, auditable, and defensible claim routing recommendations.",
        ),
        (
            "user",
            "{user_input}",
        ),
    ]
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _sanitize(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in record.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            result[k] = None
        else:
            result[k] = v
    return result


def _init_dr() -> None:
    dr.Client(
        token=os.environ.get("DATAROBOT_API_TOKEN"),
        endpoint=os.environ.get(
            "DATAROBOT_ENDPOINT", "https://app.datarobot.com/api/v2"
        ),
    )


def _detect_gaps(record: dict[str, Any]) -> list[str]:
    """Detect evidence gaps in a claim record."""
    gaps: list[str] = []

    for field in ["claim_id", "policy_id", "insured_id", "loss_date"]:
        if not record.get(field):
            gaps.append(f"Missing required field: {field}")

    if not record.get("loss_description_code"):
        gaps.append("Missing loss description code")

    repair_est = record.get("repair_total_estimate")
    if repair_est is None:
        gaps.append("Missing repair total estimate")

    if not record.get("image_provided"):
        gaps.append("No image provided")

    if not record.get("fnol_path"):
        gaps.append("Missing FNOL document")

    repair_val = _safe_float(repair_est, 0.0) if repair_est is not None else 0.0
    if repair_val >= 25000:
        if not record.get("police_report_path"):
            gaps.append("Missing police report (required for estimates >= $25,000)")
        if not record.get("damage_photo_path"):
            gaps.append("Missing damage photos (required for estimates >= $25,000)")

    if record.get("injury_flag"):
        if not record.get("medical_summary_path"):
            gaps.append("Missing medical summary (required for injury claims)")

    return gaps


def _apply_rules(
    fraud_score: float,
    anomaly_score: float,
    repair_estimate: float,
    injury_flag: bool,
    gap_count: int,
    red_flag_count: int,
    liability_clear: bool,
) -> tuple[str, str]:
    """Apply R0–R6 rules engine. Returns (routing_decision, rule_fired)."""
    if fraud_score >= 70 and red_flag_count >= 3:
        return "Recommend Decline Review", "R0"
    if fraud_score >= 70 or red_flag_count >= 2:
        return "Complex", "R1"
    if gap_count > 0:
        return "More Info Needed", "R2"
    if injury_flag or repair_estimate >= 25000:
        return "Complex", "R3"
    if fraud_score >= 50 or anomaly_score >= 0.5:
        return "Standard", "R4a"
    if repair_estimate > 10000:
        return "Standard", "R4b"
    if not liability_clear:
        return "Standard", "R4c"
    if repair_estimate <= 10000 and liability_clear and gap_count == 0:
        return "Fast Track", "R5"
    return "Standard", "R6"


@tool
def load_fnol_records() -> str:
    """Load all FNOL claim records from the DataRobot dataset."""
    _init_dr()
    dataset = Dataset.get(DATASET_ID)
    df = dataset.get_as_dataframe()
    records = [_sanitize(r) for r in df.to_dict(orient="records")]
    count = len(records)
    sample = records[:3] if records else []
    return f"Loaded {count} FNOL records. Sample claim IDs: {[r.get('claim_id') for r in sample]}"


@tool
def score_all_claims() -> str:
    """Score all FNOL claims with fraud and anomaly models. Returns summary statistics."""
    _init_dr()
    dataset = Dataset.get(DATASET_ID)
    df = dataset.get_as_dataframe()
    records = [_sanitize(r) for r in df.to_dict(orient="records")]
    for rec in records:
        for col in EXTRA_COLS:
            if col not in rec:
                rec[col] = None

    fraud_high = 0
    anomaly_high = 0
    total = len(records)

    try:
        fraud_dep = dr.Deployment.get(FRAUD_DEPLOYMENT_ID)
        fr = predict(fraud_dep, records)
        if hasattr(fr, "dataframe"):
            fr_df = fr.dataframe
            for i in range(len(records)):
                pv = fr_df.iloc[i].get("FRAUD_FLAG_1_PREDICTION", 0.0)
                if _safe_float(pv, 0.0) >= 0.7:
                    fraud_high += 1
    except Exception as e:
        return f"Scoring incomplete — fraud model error: {e}"

    try:
        anomaly_dep = dr.Deployment.get(ANOMALY_DEPLOYMENT_ID)
        an = predict(anomaly_dep, records)
        if hasattr(an, "dataframe"):
            an_df = an.dataframe
            cols = [
                c
                for c in an_df.columns
                if "anomaly" in c.lower() or "prediction" in c.lower()
            ]
            if cols:
                for i in range(len(records)):
                    pv = an_df.iloc[i].get(cols[0], 0.0)
                    if _safe_float(pv, 0.0) >= 0.5:
                        anomaly_high += 1
    except Exception as e:
        return f"Scoring incomplete — anomaly model error: {e}"

    return (
        f"Scored {total} claims. High fraud risk (>=70%): {fraud_high}. "
        f"Anomaly flagged (>=0.5): {anomaly_high}."
    )


@tool
def analyze_claim(claim_id: str) -> str:
    """Fully analyze a specific claim by ID using all three predictive models (fraud, anomaly, damage),
    detect evidence gaps, compute red flags, and apply the deterministic routing rules engine (R0-R6).
    Returns a complete structured assessment the agent can use to produce rationale and recommendations."""
    _init_dr()
    dataset = Dataset.get(DATASET_ID)
    df = dataset.get_as_dataframe()
    records = [_sanitize(r) for r in df.to_dict(orient="records")]

    record = next((r for r in records if str(r.get("claim_id")) == claim_id), None)
    if not record:
        return f"Claim {claim_id} not found in dataset."

    for col in EXTRA_COLS:
        if col not in record:
            record[col] = None

    # --- Fraud model ---
    fraud_s = 0.0
    fraud_source = "default"
    try:
        fraud_dep = dr.Deployment.get(FRAUD_DEPLOYMENT_ID)
        fr = predict(fraud_dep, [record])
        if hasattr(fr, "dataframe"):
            pv = fr.dataframe.iloc[0].get("FRAUD_FLAG_1_PREDICTION", None)
            if pv is not None:
                fraud_s = _safe_float(pv, 0.0) * 100
                fraud_source = "fraud model"
        elif hasattr(fr, "predictions"):
            pvs = fr.predictions[0].get("predictionValues", [])
            for pv in pvs:
                if str(pv.get("label", "")) == "1":
                    fraud_s = _safe_float(pv.get("value", 0.0), 0.0) * 100
                    fraud_source = "fraud model"
                    break
    except Exception as e:
        fraud_s = _safe_float(record.get("fraud_flag", 0), 0.0) * 100
        fraud_source = f"fallback field (model error: {e})"

    # --- Anomaly model ---
    anomaly_s = 0.0
    anomaly_source = "default"
    try:
        anomaly_dep = dr.Deployment.get(ANOMALY_DEPLOYMENT_ID)
        an = predict(anomaly_dep, [record])
        if hasattr(an, "dataframe"):
            cols = [c for c in an.dataframe.columns if "anomaly" in c.lower() or "prediction" in c.lower()]
            if cols:
                anomaly_s = _safe_float(an.dataframe.iloc[0].get(cols[0], 0.0), 0.0)
                anomaly_source = f"anomaly model (column: {cols[0]})"
        elif hasattr(an, "predictions"):
            pvs = an.predictions[0].get("predictionValues", [])
            for pv in pvs:
                if str(pv.get("label", "")).lower() in ("1", "true", "anomaly"):
                    anomaly_s = _safe_float(pv.get("value", 0.0), 0.0)
                    anomaly_source = "anomaly model"
                    break
    except Exception as e:
        anomaly_source = f"unavailable (error: {e})"

    # --- Damage model ---
    damage_c = str(record.get("damage_classification") or "unknown")
    damage_source = "dataset field"
    try:
        damage_dep = dr.Deployment.get(DAMAGE_DEPLOYMENT_ID)
        dm = predict(damage_dep, [record])
        classes = ["minor", "moderate", "severe", "total_loss", "unknown"]
        if hasattr(dm, "dataframe"):
            dm_df = dm.dataframe
            pred_col = [c for c in dm_df.columns if "prediction" in c.lower() and "PREDICTION" in c]
            if pred_col:
                damage_c = str(dm_df.iloc[0].get(pred_col[0], "unknown"))
                damage_source = "damage model"
            else:
                class_cols = {c: c.split("_")[-2].lower() for c in dm_df.columns if any(cls in c.lower() for cls in classes)}
                best_class, best_val = "unknown", -1.0
                for col, cls in class_cols.items():
                    v = _safe_float(dm_df.iloc[0].get(col, 0.0), 0.0)
                    if v > best_val:
                        best_val, best_class = v, cls
                damage_c = best_class
                damage_source = "damage model (argmax)"
        elif hasattr(dm, "predictions"):
            pvs = dm.predictions[0].get("predictionValues", [])
            best_class, best_val = "unknown", -1.0
            for pv in pvs:
                v = _safe_float(pv.get("value", 0), 0.0)
                if v > best_val:
                    best_val, best_class = v, str(pv.get("label", "unknown"))
            damage_c = best_class
            damage_source = "damage model"
    except Exception as e:
        damage_source = f"dataset fallback (model error: {e})"

    # --- Evidence gaps ---
    gaps = _detect_gaps(record)
    gap_count = len(gaps)

    # --- Red flags ---
    prior_claims = int(_safe_float(record.get("prior_claims_count"), 0.0))
    red_flags = 0
    if fraud_s >= 60:
        red_flags += 1
    if anomaly_s >= 0.5:
        red_flags += 1
    if gap_count >= 3:
        red_flags += 1
    if prior_claims >= 2:
        red_flags += 1

    # --- Liability ---
    loss_type = str(record.get("loss_type") or "").lower()
    liability_determinable = damage_c.lower() not in ("unknown", "")
    liability_clear = liability_determinable and loss_type != "liability"

    # --- Rules engine ---
    repair_est = _safe_float(record.get("repair_total_estimate"), 0.0)
    injury = bool(record.get("injury_flag", False))
    routing, rule_fired = _apply_rules(fraud_s, anomaly_s, repair_est, injury, gap_count, red_flags, liability_clear)

    gaps_str = "; ".join(gaps) if gaps else "none"
    return (
        f"CLAIM ANALYSIS: {claim_id}\n"
        f"\nSCORES (from predictive models):"
        f"\n  Fraud score: {fraud_s:.1f}% [source: {fraud_source}]"
        f"\n  Anomaly score: {anomaly_s:.3f} [source: {anomaly_source}]"
        f"\n  Damage classification: {damage_c} [source: {damage_source}]"
        f"\n\nCLAIM DATA:"
        f"\n  Repair estimate: ${repair_est:,.0f}"
        f"\n  Injury flag: {injury}"
        f"\n  Loss type: {record.get('loss_type') or 'unknown'}"
        f"\n  Loss date: {record.get('loss_date') or 'unknown'}"
        f"\n  Prior claims count: {prior_claims}"
        f"\n\nEVIDENCE GAPS ({gap_count}): {gaps_str}"
        f"\n\nRED FLAGS: {red_flags}/4"
        f"\n  - Fraud >= 60%: {fraud_s >= 60}"
        f"\n  - Anomaly >= 0.5: {anomaly_s >= 0.5}"
        f"\n  - Gaps >= 3: {gap_count >= 3}"
        f"\n  - Prior claims >= 2: {prior_claims >= 2}"
        f"\n\nLIABILITY: {'clear' if liability_clear else 'unclear'}"
        f"\n\nROUTING DECISION: {routing} (rule {rule_fired})"
        + (
            f"\n  R4a — fraud>=50% OR anomaly>=0.5: fraud={fraud_s:.1f}%, anomaly={anomaly_s:.3f}"
            if rule_fired == "R4a" else
            f"\n  R4b — estimate>$10k: ${repair_est:,.0f}"
            if rule_fired == "R4b" else
            f"\n  R4c — liability not clear: {('unclear' if not liability_clear else 'clear')}"
            if rule_fired == "R4c" else ""
        )
    )


def graph_factory(
    llm: BaseChatModel, tools: list[BaseTool], verbose: bool = False
) -> StateGraph:
    all_tools = [load_fnol_records, score_all_claims, analyze_claim, *tools]

    claims_agent = create_agent(
        llm,
        tools=all_tools,
        system_prompt=make_system_prompt(
            "You are an expert P&C motor insurance claims processing assistant.\n\n"
            "Your role is to:\n"
            "1. Load and analyze FNOL (First Notice of Loss) records from the DataRobot dataset\n"
            "2. Score claims using three predictive models: fraud detection, damage classification, anomaly\n"
            "3. Apply deterministic rules (R0-R6) to determine routing — rules are fixed, you explain them\n"
            "4. Generate clear, natural language explanations of scoring outcomes\n"
            "5. Identify evidence gaps and recommend next actions\n\n"
            "CRITICAL RULES:\n"
            "- You NEVER override the deterministic rules engine. You explain outcomes, not change them.\n"
            "- All routing decisions come from the rules engine only.\n"
            "- Explanations must be clear, professional, and defensible for regulatory review.\n"
            "- Cite specific scores and rules when explaining decisions.\n\n"
            "Rule Summary (first match wins):\n"
            "R0: fraud>=70% AND red_flags>=3 → Recommend Decline Review\n"
            "R1: fraud>=70% OR red_flags>=2 → Complex\n"
            "R2: gaps>0 → More Info Needed\n"
            "R3: injury OR estimate>=$25k → Complex\n"
            "R4a: fraud>=50% OR anomaly>=0.5 → Standard\n"
            "R4b: estimate>$10k → Standard\n"
            "R4c: liability not clear → Standard\n"
            "R5: estimate<=$10k AND liability clear AND no gaps → Fast Track\n"
            "R6: fallback → Standard",
        ),
        name="claims_agent",
        debug=verbose,
    )

    wf = StateGraph(MessagesState)
    wf.add_node("claims_agent_node", claims_agent)
    wf.add_edge(START, "claims_agent_node")
    wf.add_edge("claims_agent_node", END)
    return wf


MyAgent = datarobot_agent_class_from_langgraph(graph_factory, prompt_template)
