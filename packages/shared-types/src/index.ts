/**
 * API contracts shared by the web app. `api.ts` is generated from the FastAPI OpenAPI
 * schema (`npm run generate:types` at the repo root); never edit it by hand. CI fails if
 * it is out of date with the API.
 */

import type { components, paths } from "./api";

export type { components, paths };

type Schemas = components["schemas"];

export type LiveResponse = Schemas["LiveResponse"];
export type DependencyCheck = Schemas["DependencyCheck"];
export type ReadyResponse = Schemas["ReadyResponse"];
export type VersionResponse = Schemas["VersionResponse"];
export type CheckStatus = DependencyCheck["status"];

export type SessionOut = Schemas["SessionOut"];
export type UserOut = Schemas["UserOut"];
export type MembershipOut = Schemas["MembershipOut"];
export type OrganisationOut = Schemas["OrganisationOut"];
export type MemberOut = Schemas["MemberOut"];
export type InvitationOut = Schemas["InvitationOut"];
export type AuditEventOut = Schemas["AuditEventOut"];

export type ProjectOut = Schemas["ProjectOut"];
export type ProjectDetailOut = Schemas["ProjectDetailOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectStatus = Schemas["ProjectStatus"];
export type StatusEventOut = Schemas["StatusEventOut"];
export type TaskOut = Schemas["TaskOut"];
export type ReminderOut = Schemas["ReminderOut"];
export type SubmissionSummary = Schemas["SubmissionSummary"];
export type SubmissionOut = Schemas["SubmissionOut"];
export type QuestionnaireOut = Schemas["QuestionnaireOut"];
export type QuestionnaireSummary = Schemas["QuestionnaireSummary"];
export type SectionOut = Schemas["SectionOut"];
export type QuestionOut = Schemas["QuestionOut"];
export type OptionOut = Schemas["OptionOut"];
export type PrefillOut = Schemas["PrefillOut"];
export type PrefillSuggestion = Schemas["PrefillSuggestion"];
export type PropertyOut = Schemas["PropertyOut"];
export type VesselOut = Schemas["VesselOut"];
export type BusinessProfileOut = Schemas["BusinessOut"];

/** Error body returned by the API for every handled error. */
export interface ApiErrorBody {
  detail:
    | { code: string; message: string; fields?: Record<string, string> }
    | Array<{ msg: string; loc: (string | number)[] }>;
}

/** Regulatory confidence levels. Every regulatory outcome uses exactly one of these. */
export const CONFIDENCE_LEVELS = ["VERIFIED", "LIKELY", "REVIEW_REQUIRED", "UNKNOWN"] as const;
export type Confidence = (typeof CONFIDENCE_LEVELS)[number];

export const VERTICALS = ["PLANNING", "VESSEL", "BUSINESS", "GRANT", "SELL", "RENT"] as const;
export type Vertical = (typeof VERTICALS)[number];

export type RuleResult = Schemas["RuleResult"];
export type OutcomeType = Schemas["OutcomeType"];
export type AssessmentSummary = Schemas["AssessmentSummary"];
export type AssessmentOut = Schemas["AssessmentOut"];
export type FindingOut = Schemas["FindingOut"];
export type FindingSourceOut = Schemas["FindingSourceOut"];
export type RuleSetScopeOut = Schemas["RuleSetScopeOut"];
export type ApprovalRequirementOut = Schemas["ApprovalRequirementOut"];
export type ApprovalMapEntryOut = Schemas["ApprovalMapEntryOut"];
export type MarketplaceCategoryOut = Schemas["MarketplaceCategoryOut"];
export type EvidenceRequirementOut = Schemas["EvidenceRequirementOut"];
export type ReferralCategoryOut = Schemas["ReferralCategoryOut"];
export type Certainty = Schemas["Certainty"];

export type SourceOrganisationOut = Schemas["SourceOrganisationOut"];
export type SourceDocumentOut = Schemas["SourceDocumentOut"];
export type SnapshotSummary = Schemas["SnapshotSummary"];
export type SnapshotOut = Schemas["SnapshotOut"];
export type SnapshotCaptured = Schemas["SnapshotCaptured"];
export type SourceCheckOut = Schemas["SourceCheckOut"];
export type SourceReferenceOut = Schemas["SourceReferenceOut"];
export type ReviewEventOut = Schemas["ReviewEventOut"];

export type RuleSetOut = Schemas["RuleSetOut"];
export type RuleSummary = Schemas["RuleSummary"];
export type RuleOut = Schemas["RuleOut"];
export type RuleVersionOut = Schemas["RuleVersionOut"];
export type RuleVersionSummary = Schemas["RuleVersionSummary"];
export type RuleVersionContent = Schemas["RuleVersionContent"];
export type PublishChecksOut = Schemas["PublishChecksOut"];
export type EvaluateOut = Schemas["EvaluateOut"];

export type DocumentOut = Schemas["DocumentOut"];
export type ScanStatus = Schemas["ScanStatus"];
export type UploadLimitsOut = Schemas["UploadLimitsOut"];
export type EvidenceOut = Schemas["EvidenceOut"];
export type GeneratedDocumentOut = Schemas["GeneratedDocumentOut"];
export type OutputFormat = Schemas["OutputFormat"];
export type GenerationStatus = Schemas["GenerationStatus"];
export type Classification = Schemas["Classification"];
export type EvidenceStatus = Schemas["EvidenceStatus"];
export type ReviewStatus = Schemas["ReviewStatus"];

export type ProfessionalOut = Schemas["ProfessionalOut"];
export type ProfessionalPublicOut = Schemas["ProfessionalPublicOut"];
export type ProfessionalStatus = Schemas["ProfessionalStatus"];
export type CredentialOut = Schemas["CredentialOut"];
export type CredentialKind = Schemas["CredentialKind"];
export type Discipline = Schemas["Discipline"];
export type ReviewSummary = Schemas["ReviewSummary"];
export type ReviewOut = Schemas["ReviewOut"];
export type ReviewRequestStatus = Schemas["ReviewRequestStatus"];
export type CommentOut = Schemas["CommentOut"];
export type OverrideOut = Schemas["OverrideOut"];
export type DecisionOut = Schemas["DecisionOut"];
export type Decision = Schemas["Decision"];
export type AssessmentReviewOut = Schemas["AssessmentReviewOut"];
export type QueueItemOut = Schemas["QueueItemOut"];
export type ReviewerWorkspaceOut = Schemas["ReviewerWorkspaceOut"];
export type StaffReviewOut = Schemas["StaffReviewOut"];

export type ChecklistOut = Schemas["ChecklistOut"];
export type ChecklistItemOut = Schemas["ChecklistItemOut"];
export type ChecklistDefinitionOut = Schemas["ChecklistDefinitionOut"];
export type ItemStatus = Schemas["ItemStatus"];
export type CertificateOut = Schemas["CertificateOut"];
export type CertificateKind = Schemas["CertificateKind"];
export type SmsOut = Schemas["SmsOut"];
export type SmsSectionOut = Schemas["SmsSectionOut"];
export type SmsElementOut = Schemas["SmsElementOut"];

// GrantReady (Milestone 10)
export type GrantProgramOut = Schemas["GrantProgramOut"];
export type GrantRoundOut = Schemas["GrantRoundOut"];
export type GrantMatchOut = Schemas["GrantMatchOut"];
export type MatchCriterionOut = Schemas["MatchCriterionOut"];
export type MatchStatus = GrantMatchOut["status"];
export type RoundStatus = GrantRoundOut["state"];

export type AddressMatchOut = Schemas["AddressMatchOut"];
export type AddressSearchOut = Schemas["AddressSearchOut"];
export type ParcelOut = Schemas["ParcelOut"];
export type VesselLookupOut = Schemas["VesselLookupOut"];

// AI drafting (Milestone 12)
export type AIJobOut = Schemas["AIJobOut"];
export type AIStatusOut = Schemas["AIStatusOut"];
export type AIUsageOut = Schemas["AIUsageOut"];
export type AIUsageRowOut = Schemas["AIUsageRowOut"];
export type PromptVersionOut = Schemas["PromptVersionOut"];
export type AssessmentExplanation = Schemas["AssessmentExplanationV1"];
export type GrantDraft = Schemas["GrantDraftV1"];
export type CitedPoint = Schemas["CitedPoint"];
export type DraftSection = Schemas["DraftSection"];
// PropertyReady (Milestone 11)
export type SaleOut = Schemas["SaleOut"];
export type SaleStatus = Schemas["SaleStatus"];
export type DisclosureOut = Schemas["DisclosureOut"];
export type SaleDocumentOut = Schemas["SaleDocumentOut"];
export type VaultCategory = Schemas["VaultCategory"];
export type OfferOut = Schemas["OfferOut"];
export type OfferStatus = Schemas["OfferStatus"];
export type EnquiryOut = Schemas["EnquiryOut"];
export type RentalOut = Schemas["RentalOut"];
export type ApplicationOut = Schemas["ApplicationOut"];
export type TenancyOut = Schemas["TenancyOut"];
export type InspectionOut = Schemas["InspectionOut"];
export type InspectionDetailOut = Schemas["InspectionDetailOut"];
export type InspectionItemOut = Schemas["InspectionItemOut"];
export type ItemCondition = Schemas["ItemCondition"];
export type MaintenanceOut = Schemas["MaintenanceOut"];
export type NotificationOut = Schemas["NotificationOut"];
export type NotificationListOut = Schemas["NotificationListOut"];
export type CrossSellOut = Schemas["CrossSellOut"];

// Customer payments (Milestone 13)
export type BillingOut = Schemas["BillingOut"];
export type BillingStatusOut = Schemas["BillingStatusOut"];
export type CatalogueOut = Schemas["CatalogueOut"];
export type ProductOut = Schemas["ProductOut"];
export type PriceOut = Schemas["PriceOut"];
export type PriceInterval = Schemas["PriceInterval"];
export type FeatureLimitOut = Schemas["FeatureLimitOut"];
export type SubscriptionOut = Schemas["SubscriptionOut"];
export type AllowanceOut = Schemas["AllowanceOut"];
export type PaymentOut = Schemas["PaymentOut"];
export type InvoiceOut = Schemas["InvoiceOut"];
export type RedirectOut = Schemas["RedirectOut"];
export type CheckoutOut = Schemas["CheckoutOut"];
export type StripeEventOut = Schemas["StripeEventOut"];
export type ReviewPaymentOut = Schemas["ReviewPaymentOut"];

// Partner accounts (Milestone 14)
export type PartnerOut = Schemas["PartnerOut"];
export type StaffPartnerOut = Schemas["StaffPartnerOut"];
export type PartnerSummaryOut = Schemas["PartnerSummaryOut"];
export type PartnerStatus = Schemas["PartnerStatus"];
export type PartnerCategoryOut = Schemas["PartnerCategoryOut"];
export type PartnerCategoryStatus = Schemas["PartnerCategoryStatus"];
export type PartnerCredentialOut = Schemas["PartnerCredentialOut"];
export type PartnerCredentialKind = Schemas["PartnerCredentialKind"];
export type PartnerCredentialStatus = Schemas["PartnerCredentialStatus"];
export type PartnerServiceAreaOut = Schemas["PartnerServiceAreaOut"];
export type ServiceAreaKind = Schemas["ServiceAreaKind"];
export type AustralianState = Schemas["AustralianState"];
export type PartnerPlanOut = Schemas["PartnerPlanOut"];
export type PartnerPlanLimitOut = Schemas["PartnerPlanLimitOut"];
export type PartnerApplicationOut = Schemas["PartnerApplicationOut"];
export type PartnerMemberOut = Schemas["PartnerMemberOut"];
export type PartnerApplicationIn = Schemas["PartnerApplicationIn"];

// Lead engine (Milestone 15)
export type ReferralIn = Schemas["ReferralIn"];
export type ReferralOut = Schemas["ReferralOut"];
export type ReferralOptionsOut = Schemas["ReferralOptionsOut"];
export type ReferralCategoryOptionOut = Schemas["ReferralCategoryOptionOut"];
export type CustomerLeadOut = Schemas["CustomerLeadOut"];
export type ClaimedPartnerOut = Schemas["ClaimedPartnerOut"];
export type ReleasableField = Schemas["ReleasableField"];
export type Timing = Schemas["Timing"];
export type LeadStatus = Schemas["LeadStatus"];
export type LeadMatchStatus = Schemas["LeadMatchStatus"];
export type LeadPublicView = Schemas["LeadPublicView"];
export type LeadOfferOut = Schemas["LeadOfferOut"];
export type ClaimOut = Schemas["ClaimOut"];
export type FeeOut = Schemas["FeeOut"];
export type ScoreFactorOut = Schemas["ScoreFactorOut"];
export type LeadPreferencesOut = Schemas["LeadPreferencesOut"];
export type CreditsOut = Schemas["CreditsOut"];
export type CreditEntryOut = Schemas["CreditEntryOut"];
export type CreditKind = Schemas["CreditKind"];
export type CreditStaffOut = Schemas["CreditStaffOut"];
export type LeadPriceOut = Schemas["LeadPriceOut"];
export type StaffLeadOut = Schemas["StaffLeadOut"];
export type StaffMatchOut = Schemas["StaffMatchOut"];

export type FunnelOut = Schemas["FunnelOut"];
export type PartnerAnalyticsOut = Schemas["PartnerAnalyticsOut"];
export type BenchmarkOut = Schemas["BenchmarkOut"];
export type BenchmarksOut = Schemas["BenchmarksOut"];
export type MarketTotalsOut = Schemas["MarketTotalsOut"];
export type MarketPartnerOut = Schemas["MarketPartnerOut"];
export type MarketplaceAnalyticsOut = Schemas["MarketplaceAnalyticsOut"];

export type CheckState = Schemas["CheckState"];
export type CheckOut = Schemas["CheckOut"];
export type BackupRunOut = Schemas["BackupRunOut"];
export type OpsStatusOut = Schemas["OpsStatusOut"];
