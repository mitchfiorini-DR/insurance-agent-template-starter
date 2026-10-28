import json
import logging
import math
import os
from typing import Any

import datarobot as dr
import httpx
import pandas as pd
import httpx_sse
from datarobot.models.dataset import Dataset
from datarobot_predict.deployment import predict
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

claims_router = APIRouter(tags=["Claims"])

DATASET_ID = "6a84e3f4bd4eb9abe94a66d4"
FRAUD_DEPLOYMENT_ID = "6a8734c14864b60d101e7db6"
ANOMALY_DEPLOYMENT_ID = "6a8747e921f2ad7a801e7aff"

# A claim is shown as fraud-flagged when the fraud model's probability is over 50%.
FRAUD_FLAG_THRESHOLD = 50.0

EXTRA_COLS = [
    "image_provided",
    "fnol_path",
    "police_report_path",
    "damage_photo_path",
    "medical_summary_path",
    "prior_claims_count",
]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in record.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            result[k] = None
        else:
            result[k] = v
    return result


def detect_evidence_gaps(record: dict[str, Any]) -> list[str]:
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

    repair_val = safe_float(repair_est, 0.0) if repair_est is not None else 0.0
    if repair_val >= 25000:
        if not record.get("police_report_path"):
            gaps.append("Missing police report (required for estimates >= $25,000)")
        if not record.get("damage_photo_path"):
            gaps.append("Missing damage photos (required for estimates >= $25,000)")

    if record.get("injury_flag"):
        if not record.get("medical_summary_path"):
            gaps.append("Missing medical summary (required for injury claims)")

    return gaps


def fraud_probability_column(df: pd.DataFrame) -> str:
    """Return the column holding the positive-class (fraud) probability.

    DataRobot binary deployments return one ``<target>_<class>_PREDICTION`` column per
    class (e.g. ``fraud_flag_True_PREDICTION``) plus a ``POSITIVE_CLASS`` column.
    """
    if "POSITIVE_CLASS" in df.columns and len(df):
        col = f"fraud_flag_{df['POSITIVE_CLASS'].iloc[0]}_PREDICTION"
        if col in df.columns:
            return col
    if "fraud_flag_True_PREDICTION" in df.columns:
        return "fraud_flag_True_PREDICTION"
    raise ValueError(f"No fraud probability column found in prediction output. Available columns: {list(df.columns)}")


def compute_red_flags(fraud_score: float, anomaly_score: float, gap_count: int, prior_claims_count: int = 0) -> int:
    count = 0
    if fraud_score >= 60:
        count += 1
    if anomaly_score >= 0.5:
        count += 1
    if gap_count >= 3:
        count += 1
    if prior_claims_count >= 2:
        count += 1
    return count


def apply_rules_engine(
    fraud_score: float,
    anomaly_score: float,
    repair_estimate: float,
    injury_flag: bool,
    gap_count: int,
    red_flag_count: int,
    liability_status: str,
) -> tuple[str, str, list[dict[str, Any]]]:
    rules: list[dict[str, Any]] = []

    liability_clear = liability_status.lower() in ("clear", "confirmed") if liability_status else False

    def check(rule: str, condition: bool, desc: str) -> None:
        rules.append({"rule": rule, "passed": condition, "description": desc})

    r0 = fraud_score >= 70 and red_flag_count >= 3
    check("R0", r0, f"fraud_score >= 70 ({fraud_score:.0f}) AND red_flags >= 3 ({red_flag_count})")

    r1 = fraud_score >= 70 or red_flag_count >= 2
    check("R1", r1, f"fraud_score >= 70 ({fraud_score:.0f}) OR red_flags >= 2 ({red_flag_count})")

    r2 = gap_count > 0
    check("R2", r2, f"evidence gaps > 0 (found {gap_count})")

    r3 = injury_flag or repair_estimate >= 25000
    check("R3", r3, f"injury_flag={injury_flag} OR repair_estimate >= $25,000 (${repair_estimate:,.0f})")

    r4a = fraud_score >= 50 or anomaly_score >= 0.5
    check("R4a", r4a, f"fraud >= 50 ({fraud_score:.0f}) OR anomaly >= 0.5 ({anomaly_score:.3f})")

    r4b = repair_estimate > 10000
    check("R4b", r4b, f"estimate > $10k (${repair_estimate:,.0f})")

    r4c = not liability_clear
    check("R4c", r4c, f"liability not clear ({liability_status})")

    r5 = repair_estimate <= 10000 and liability_clear and gap_count == 0
    check("R5", r5, "estimate <= $10k AND liability clear AND no gaps")

    if r0:
        return "Recommend Decline Review", "R0", rules
    if r1:
        return "Complex", "R1", rules
    if r2:
        return "More Info Needed", "R2", rules
    if r3:
        return "Complex", "R3", rules
    if r4a:
        return "Standard", "R4a", rules
    if r4b:
        return "Standard", "R4b", rules
    if r4c:
        return "Standard", "R4c", rules
    if r5:
        return "Fast Track", "R5", rules
    return "Standard", "R6", rules


def generate_rationale(
    record: dict[str, Any],
    fraud_score: float,
    anomaly_score: float,
    routing: str,
    rule_fired: str,
    gaps: list[str],
    red_flag_count: int,
) -> tuple[str, str]:
    claim_id = record.get("claim_id", "Unknown")
    repair_est = safe_float(record.get("repair_total_estimate"), 0.0)

    rationale_parts = [f"Claim {claim_id} has been routed to '{routing}' (rule {rule_fired})."]

    if fraud_score > FRAUD_FLAG_THRESHOLD:
        rationale_parts.append("Fraud flag is True (fraud model probability over 50%); claim warrants elevated scrutiny.")

    if anomaly_score >= 0.5:
        rationale_parts.append(f"Anomaly detection score ({anomaly_score:.2f}) exceeds threshold, indicating irregular claim patterns.")

    if gaps:
        rationale_parts.append(f"Evidence gaps identified ({len(gaps)}): {'; '.join(gaps[:3])}.")

    if red_flag_count > 0:
        rationale_parts.append(f"{red_flag_count} red flag(s) detected across fraud, anomaly score, and evidence gaps.")

    if repair_est >= 25000:
        rationale_parts.append(f"High value claim (${repair_est:,.0f}) requires enhanced validation.")

    if record.get("injury_flag"):
        rationale_parts.append("Injury involvement requires medical evidence review.")

    rationale = " ".join(rationale_parts)

    actions_map = {
        "Recommend Decline Review": "Escalate to senior adjuster and SIU team. Compile fraud evidence dossier. Issue reservation of rights letter.",
        "Complex": "Assign to experienced adjuster. Schedule inspection within 48 hours. Validate all supporting documentation.",
        "More Info Needed": f"Contact insured to provide: {'; '.join(gaps[:2]) if gaps else 'missing documentation'}. Set 10-day follow-up deadline.",
        "Standard": "Assign to standard adjuster queue. Complete liability assessment and damage valuation within 5 business days.",
        "Fast Track": "Eligible for automated settlement pathway. Verify policy coverage and issue payment within 2 business days.",
    }

    recommended_action = actions_map.get(routing, "Route to standard adjuster queue for review.")
    return rationale, recommended_action


class ScoredClaim(BaseModel):
    claim_id: str
    policy_id: str | None
    insured_id: str | None
    loss_date: str | None
    loss_type: str | None
    fraud_score: float
    fraud_flag: bool
    anomaly_score: float
    damage_class: str | None
    routing_decision: str
    rule_fired: str
    gap_count: int
    red_flag_count: int
    gaps: list[str]
    rule_trace: list[dict[str, Any]]
    rationale: str
    recommended_action: str
    repair_total_estimate: float | None
    injury_flag: bool


@claims_router.get("/claims", response_model=list[ScoredClaim])
async def get_claims() -> list[ScoredClaim]:
    try:
        dr.Client(
            token=os.environ.get("DATAROBOT_API_TOKEN"),
            endpoint=os.environ.get("DATAROBOT_ENDPOINT", "https://app.datarobot.com/api/v2"),
        )

        dataset = Dataset.get(DATASET_ID)
        df = dataset.get_as_dataframe()

        raw_records = df.to_dict(orient="records")
        records = [sanitize_record(r) for r in raw_records]

        for rec in records:
            for col in EXTRA_COLS:
                if col not in rec:
                    rec[col] = None

        fraud_scores: dict[str, float] = {}
        anomaly_scores: dict[str, float] = {}
        damage_classes: dict[str, str] = {}

        records_df = pd.DataFrame(records)

        try:
            fraud_dep = dr.Deployment.get(FRAUD_DEPLOYMENT_ID)
            fraud_result = predict(fraud_dep, records_df)
            fr_df = fraud_result.dataframe
            fraud_col = fraud_probability_column(fr_df)
            for i, row in enumerate(records):
                cid = str(row.get("claim_id", i))
                pv = fr_df.iloc[i].get(fraud_col, None)
                fraud_scores[cid] = safe_float(pv, 0.0) * 100
        except Exception as e:
            logger.error(f"Fraud scoring failed: {e}", exc_info=True)
            for rec in records:
                fraud_scores[str(rec.get("claim_id", ""))] = safe_float(rec.get("fraud_flag", 0), 0.0) * 100

        try:
            anomaly_dep = dr.Deployment.get(ANOMALY_DEPLOYMENT_ID)
            anomaly_result = predict(anomaly_dep, records_df)
            an_df = anomaly_result.dataframe
            logger.info(f"Anomaly model returned columns: {list(an_df.columns)}")
            anomaly_cols = [c for c in an_df.columns if "anomaly" in c.lower() or "prediction" in c.lower()]
            if not anomaly_cols:
                raise ValueError(f"No anomaly score column found in prediction output. Available columns: {list(an_df.columns)}")
            anomaly_col = anomaly_cols[0]
            logger.info(f"Using anomaly column: {anomaly_col!r}")
            for i, row in enumerate(records):
                cid = str(row.get("claim_id", i))
                pv = an_df.iloc[i].get(anomaly_col, 0.0)
                anomaly_scores[cid] = safe_float(pv, 0.0)
        except Exception as e:
            logger.error(f"Anomaly scoring failed: {e}", exc_info=True)
            for rec in records:
                anomaly_scores[str(rec.get("claim_id", ""))] = 0.0

        # Damage class comes from the dataset's damage_classification column (no predictive model).
        for rec in records:
            damage_classes[str(rec.get("claim_id", ""))] = str(rec.get("damage_classification") or "unknown")

        scored: list[ScoredClaim] = []
        for rec in records:
            cid = str(rec.get("claim_id", ""))
            fraud_s = fraud_scores.get(cid, 0.0)
            anomaly_s = anomaly_scores.get(cid, 0.0)
            damage_c = damage_classes.get(cid, "unknown")
            repair_est = safe_float(rec.get("repair_total_estimate"), 0.0)
            injury = bool(rec.get("injury_flag", False))
            damage_c_for_liability = damage_classes.get(cid, "unknown") or "unknown"
            loss_type_str = str(rec.get("loss_type") or "").lower()
            liability_determinable = damage_c_for_liability.lower() not in ("unknown", "")
            third_party_liability = loss_type_str == "liability"
            liability = "clear" if (liability_determinable and not third_party_liability) else "unclear"

            gaps = detect_evidence_gaps(rec)
            gap_count = len(gaps)
            prior_claims = int(safe_float(rec.get("prior_claims_count"), 0.0))
            red_flags = compute_red_flags(fraud_s, anomaly_s, gap_count, prior_claims)

            routing, rule, rule_trace = apply_rules_engine(
                fraud_score=fraud_s,
                anomaly_score=anomaly_s,
                repair_estimate=repair_est,
                injury_flag=injury,
                gap_count=gap_count,
                red_flag_count=red_flags,
                liability_status=liability,
            )

            rationale, action = generate_rationale(rec, fraud_s, anomaly_s, routing, rule, gaps, red_flags)

            raw_est = rec.get("repair_total_estimate")
            est_val: float | None = None
            if raw_est is not None:
                est_val = safe_float(raw_est, 0.0)

            loss_date = rec.get("loss_date")
            loss_date_str: str | None = str(loss_date) if loss_date is not None else None

            scored.append(
                ScoredClaim(
                    claim_id=cid,
                    policy_id=str(rec.get("policy_id") or "") or None,
                    insured_id=str(rec.get("insured_id") or "") or None,
                    loss_date=loss_date_str,
                    loss_type=str(rec.get("loss_type") or "") or None,
                    fraud_score=round(fraud_s, 1),
                    fraud_flag=fraud_s > FRAUD_FLAG_THRESHOLD,
                    anomaly_score=round(anomaly_s, 3),
                    damage_class=damage_c,
                    routing_decision=routing,
                    rule_fired=rule,
                    gap_count=gap_count,
                    red_flag_count=red_flags,
                    gaps=gaps,
                    rule_trace=rule_trace,
                    rationale=rationale,
                    recommended_action=action,
                    repair_total_estimate=est_val,
                    injury_flag=injury,
                )
            )

        return scored

    except Exception as e:
        logger.error(f"Claims processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class EmailTemplate(BaseModel):
    subject: str
    body: str


class NextStep(BaseModel):
    text: str
    requires_outreach: bool
    email_template: EmailTemplate | None = None


class RecommendationResponse(BaseModel):
    claim_id: str
    rationale: str
    recommendation: str
    next_steps: list[NextStep] = []


@claims_router.post("/claims/{claim_id}/recommend", response_model=RecommendationResponse)
async def get_claim_recommendation(claim_id: str, request: Request) -> RecommendationResponse:
    """Ask the agent to use its analyze_claim tool and return a rationale and recommendation."""
    deps = request.app.state.deps
    config = deps.config

    prompt = (
        f"Use the analyze_claim tool to fully assess claim {claim_id} — this will call the two "
        f"predictive models (fraud, anomaly), read the recorded damage classification, detect evidence gaps, "
        f"and apply the rules engine.\n\n"
        f"When referring to fraud, describe it ONLY as a fraud flag: 'Fraud flag: True' if the fraud score is "
        f"over 50%, otherwise 'Fraud flag: False'. Never state the fraud percentage itself, in any section "
        f"or email.\n\n"
        f"Once you have the tool results, respond with exactly this structure:\n\n"
        f"RATIONALE: <one paragraph explaining the routing decision, citing the specific model scores, "
        f"which rule fired and why, and any evidence gaps or red flags>\n\n"
        f"RECOMMENDATION: <one paragraph summary of the recommended handling approach for this specific claim, "
        f"referencing the scores and routing outcome — do not repeat the routing decision label itself>\n\n"
        f"NEXT_STEPS:\n"
        f"For each step use this exact format on consecutive lines:\n"
        f"- STEP: <action text — be specific to this claim's scores, gaps, and routing decision>\n"
        f"  OUTREACH: YES or NO  (YES only if this step requires contacting the insured, a third party, SIU, a repair shop, a medical provider, or any external party to request information or action)\n"
        f"  EMAIL_SUBJECT: <short email subject line — only include this line when OUTREACH is YES>\n"
        f"  EMAIL_BODY: <full email body in plain text, pre-populated with claim-specific details including claim ID {claim_id}, relevant scores, and exactly what is being requested — only include this line when OUTREACH is YES>\n\n"
        f"Include as many steps as needed to fully complete the FNOL process. Each step must follow the format above exactly."
    )

    import uuid as _uuid
    thread_id = str(_uuid.uuid4())
    run_id = str(_uuid.uuid4())

    body = {
        "threadId": thread_id,
        "runId": run_id,
        "state": {},
        "messages": [{"id": str(_uuid.uuid4()), "role": "user", "content": prompt}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    agent_url = f"{config.agent_endpoint}/generate/stream"
    headers = {
        "Authorization": f"Bearer {config.datarobot_api_token}",
        "Content-Type": "application/json",
    }

    text_parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with httpx_sse.aconnect_sse(
                client, "POST", agent_url, headers=headers, content=json.dumps(body)
            ) as event_source:
                if event_source.response.status_code >= 400:
                    error_body = await event_source.response.aread()
                    raise HTTPException(
                        status_code=502,
                        detail=f"Agent returned {event_source.response.status_code}: {error_body.decode()}",
                    )
                async for sse in event_source.aiter_sse():
                    if not sse.data:
                        continue
                    raw = json.loads(sse.data)
                    for event in raw.get("events", []) or []:
                        if event.get("type") == "TEXT_MESSAGE_CONTENT":
                            text_parts.append(event.get("delta", ""))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent recommendation failed for claim {claim_id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Agent unavailable: {e}")

    full_text = "".join(text_parts).strip()
    if not full_text:
        raise HTTPException(status_code=502, detail="Agent returned an empty response")

    # ── Section split ────────────────────────────────────────────────────────
    rationale = ""
    recommendation = ""
    next_steps: list[NextStep] = []

    has_rationale = "RATIONALE:" in full_text
    has_recommendation = "RECOMMENDATION:" in full_text
    has_next_steps = "NEXT_STEPS:" in full_text

    if has_rationale and has_recommendation:
        after_rationale = full_text.split("RATIONALE:", 1)[1]
        rationale = after_rationale.split("RECOMMENDATION:", 1)[0].strip()
        after_recommendation = after_rationale.split("RECOMMENDATION:", 1)[1]
        if has_next_steps:
            recommendation = after_recommendation.split("NEXT_STEPS:", 1)[0].strip()
            steps_block = after_recommendation.split("NEXT_STEPS:", 1)[1].strip()
            next_steps = _parse_next_steps(steps_block)
        else:
            recommendation = after_recommendation.strip()
    else:
        recommendation = full_text

    return RecommendationResponse(
        claim_id=claim_id,
        rationale=rationale,
        recommendation=recommendation,
        next_steps=next_steps,
    )


def _parse_next_steps(block: str) -> list[NextStep]:
    """Parse the structured NEXT_STEPS block into NextStep objects.

    Expected format per step:
      - STEP: <action text>
        OUTREACH: YES | NO
        EMAIL_SUBJECT: <subject>   (only when OUTREACH: YES)
        EMAIL_BODY: <body>         (only when OUTREACH: YES)
    """
    steps: list[NextStep] = []
    # Split on lines that start a new step ("- STEP:" or "* STEP:" or numbered)
    import re
    # Collect raw step chunks by splitting on step-starter lines
    raw_chunks: list[str] = []
    current: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        is_step_start = (
            re.match(r'^[-*]\s+STEP:', stripped)
            or re.match(r'^\d+\.\s+STEP:', stripped)
        )
        if is_step_start:
            if current:
                raw_chunks.append("\n".join(current))
            current = [stripped]
        elif current:
            current.append(stripped)
    if current:
        raw_chunks.append("\n".join(current))

    for chunk in raw_chunks:
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]

        step_text = ""
        outreach = False
        email_subject = ""
        email_body_lines: list[str] = []
        in_email_body = False

        for line in lines:
            if re.match(r'^[-*\d.]*\s*STEP:', line):
                step_text = re.sub(r'^[-*\d.]*\s*STEP:\s*', '', line).strip()
                in_email_body = False
            elif line.startswith("OUTREACH:"):
                val = line.split(":", 1)[1].strip().upper()
                outreach = val == "YES"
                in_email_body = False
            elif line.startswith("EMAIL_SUBJECT:"):
                email_subject = line.split(":", 1)[1].strip()
                in_email_body = False
            elif line.startswith("EMAIL_BODY:"):
                email_body_lines = [line.split(":", 1)[1].strip()]
                in_email_body = True
            elif in_email_body:
                email_body_lines.append(line)

        if not step_text:
            continue

        email_template: EmailTemplate | None = None
        if outreach and email_subject:
            email_template = EmailTemplate(
                subject=email_subject,
                body="\n".join(email_body_lines).strip(),
            )

        steps.append(NextStep(
            text=step_text,
            requires_outreach=outreach,
            email_template=email_template,
        ))

    return steps
