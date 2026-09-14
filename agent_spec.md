model: "datarobot/azure/gpt-4o-mini-2024-07-18"
system_prompt: |
  You are an expert P&C motor insurance claims processing assistant. You analyze FNOL (First Notice of Loss) reports, correlate evidence from multiple sources, and provide clear, auditable, and defensible claim routing recommendations.

  Your responsibilities:
  1. Retrieve and analyze FNOL records from the DataRobot dataset
  2. Score each claim using three predictive models: fraud detection, damage classification, and anomaly detection
  3. Apply deterministic rules (R0–R6) to determine routing decisions
  4. Generate natural language explanations of scoring outcomes and routing rationale
  5. Identify evidence gaps in submitted claims
  6. Provide recommended next actions for each claim

  CRITICAL: You never override the deterministic rules engine output. LLM explanations describe the outcome — they do not change it. All routing decisions are made by the rules engine only.

  Rules (evaluated in order, first match wins):
  - R0: fraud_score >= 70 AND red_flag_count >= 3 → "Recommend Decline Review"
  - R1: fraud_score >= 70 OR red_flag_count >= 2 → "Complex"
  - R2: gap_count > 0 → "More Info Needed"
  - R3: injury_flag OR repair_total_estimate >= 25000 → "Complex"
  - R4: fraud_score >= 50 OR anomaly_score >= 0.5 OR repair_total_estimate > 10000 OR liability not clear → "Standard"
  - R5: repair_total_estimate <= 10000 AND liability clear AND all docs present → "Fast Track"
  - R6: fallback → "Standard"

  Red flag conditions (each increments red_flag_count by 1):
  - fraud_score >= 60
  - anomaly_score >= 0.5
  - gap_count >= 3
  - prior_claims_count >= 2

tools:
  - function_name: load_fnol_records
    inputs: []
    out:
      - arg_name: records
        type: list
        object_schema: "List of FNOL claim records with all dataset fields"

  - function_name: score_fraud
    inputs:
      - arg_name: records
        type: list
        object_schema: "List of claim records to score for fraud"
    out:
      - arg_name: fraud_scores
        type: dict
        object_schema: "Map of claim_id to fraud probability (0-1)"

  - function_name: score_damage
    inputs:
      - arg_name: records
        type: list
        object_schema: "List of claim records to classify damage"
    out:
      - arg_name: damage_scores
        type: dict
        object_schema: "Map of claim_id to damage classification and confidence"

  - function_name: score_anomaly
    inputs:
      - arg_name: records
        type: list
        object_schema: "List of claim records to score for anomaly"
    out:
      - arg_name: anomaly_scores
        type: dict
        object_schema: "Map of claim_id to anomaly score (0-1)"

  - function_name: detect_evidence_gaps
    inputs:
      - arg_name: record
        type: dict
        object_schema: "Single FNOL claim record"
    out:
      - arg_name: gaps
        type: list
        object_schema: "List of evidence gap descriptions"

  - function_name: apply_rules_engine
    inputs:
      - arg_name: claim_id
        type: str
      - arg_name: fraud_score
        type: float
      - arg_name: anomaly_score
        type: float
      - arg_name: damage_class
        type: str
      - arg_name: repair_estimate
        type: float
      - arg_name: injury_flag
        type: bool
      - arg_name: gap_count
        type: int
      - arg_name: red_flag_count
        type: int
      - arg_name: liability_status
        type: str
    out:
      - arg_name: routing_decision
        type: str
      - arg_name: rule_fired
        type: str
      - arg_name: rule_trace
        type: list

  - function_name: generate_claim_rationale
    inputs:
      - arg_name: claim_data
        type: dict
        object_schema: "Full scored claim data including all scores, gaps, and routing"
    out:
      - arg_name: rationale
        type: str
      - arg_name: recommended_action
        type: str

examples:
  - "Load and process all FNOL claims"
  - "Score claim CLM-2024-001 for fraud and anomaly"
  - "What is the routing decision for claim CLM-2024-005?"
  - "Show all claims flagged as Complex or Recommend Decline Review"
  - "What evidence gaps are present in claim CLM-2024-010?"

frontend:
  type: "multi-page"
  pages:
    - "Claims Dashboard - Main table showing all FNOL claims with fraud score, anomaly score, routing decision, rule fired, gap count, and color-coded routing badge. Supports search by claim ID, insured ID, loss type. Sortable columns."
    - "Claim Detail - Expandable audit trail panel per claim showing rule trace (R0-R6 with pass/fail), evidence gaps, scores, LLM rationale, and recommended action."
  requirements: |
    - Dark theme professional UI, full-window layout
    - NO chat interface - dashboard only
    - Claims table columns: Claim ID, Insured ID, Date, Fraud Score, Anomaly Score, Routing Decision (color badge), Rule Fired, Gap Count
    - NO damage category or confidence columns in the table
    - Color badges: Recommend Decline Review=red, Complex=orange, More Info Needed=yellow, Standard=blue, Fast Track=green
    - Expandable per-claim audit trail with rule trace, gaps, rationale (break-words whitespace-normal CSS)
    - Search across claim ID, insured ID, loss type
    - Sortable columns
    - DataRobot dataset ID: 6a84e3f4bd4eb9abe94a66d4
    - Fraud deployment ID: 6a8734c14864b60d101e7db6
    - Damage classification deployment ID: 6a87421021f6a5e546f65279
    - Anomaly deployment ID: 6a8747e921f2ad7a801e7aff
