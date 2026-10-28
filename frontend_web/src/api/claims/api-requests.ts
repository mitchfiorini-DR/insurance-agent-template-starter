import apiClient from '@/api/apiClient';

export interface RuleTrace {
  rule: string;
  passed: boolean;
  description: string;
}

export interface ScoredClaim {
  claim_id: string;
  policy_id: string | null;
  insured_id: string | null;
  loss_date: string | null;
  loss_type: string | null;
  fraud_score: number;
  /** True when the fraud model probability is over 50%. */
  fraud_flag: boolean;
  anomaly_score: number;
  damage_class: string | null;
  routing_decision: string;
  rule_fired: string;
  gap_count: number;
  red_flag_count: number;
  gaps: string[];
  rule_trace: RuleTrace[];
  rationale: string;
  recommended_action: string;
  repair_total_estimate: number | null;
  injury_flag: boolean;
}

export async function fetchClaims(): Promise<ScoredClaim[]> {
  const response = await apiClient.get<ScoredClaim[]>('/v1/claims');
  return response.data;
}

export interface EmailTemplate {
  subject: string;
  body: string;
}

export interface NextStep {
  text: string;
  requires_outreach: boolean;
  email_template: EmailTemplate | null;
}

export interface RecommendationResponse {
  claim_id: string;
  rationale: string;
  recommendation: string;
  next_steps: NextStep[];
}

export async function fetchRecommendation(claimId: string): Promise<RecommendationResponse> {
  const response = await apiClient.post<RecommendationResponse>(`/v1/claims/${claimId}/recommend`);
  return response.data;
}
