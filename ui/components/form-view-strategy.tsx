"use client";

import { useI18n } from "@/hooks/useI18n";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "./ui/accordion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { NumberField, SliderField, asSettingsSection, type SettingsSection, type StrategySection } from "./form-view-fields";

const MEMORY_TYPES = ["user_profile", "environment_fact", "agent_architecture", "project_memory", "episodic_memory", "timeline_event", "decision", "feedback", "skill_candidate", "raw_event"];
const ACTIONS = ["mark_contradicted", "archive_and_merge_duplicate", "archive", "split", "promote"];
const RULE_PRECIOUS = ["user_profile", "environment_fact", "decision", "project_memory", "skill_candidate"];
const GOVERNANCE_PRECIOUS = ["user_profile", "decision", "project_memory"];

type FieldSpec = {
  key: string;
  label: string;
  hint?: string;
  fallback: number;
  min: number;
  max?: number;
  step?: number;
};

type StrategySettingsProps = {
  strategy: SettingsSection;
  onChange: (section: StrategySection, key: string, value: unknown) => void;
  onListToggle: (section: StrategySection, key: string, item: string, checked: boolean) => void;
};

export function StrategySettings({ strategy, onChange, onListToggle }: StrategySettingsProps) {
  const st = useI18n().messages.settings.strategy;
  const rule = asSettingsSection(strategy.rule_curator);
  const llm = asSettingsSection(strategy.llm_curator);
  const governance = asSettingsSection(strategy.governance);
  const extraction = asSettingsSection(strategy.extraction_strategy);
  const ruleGroups: Array<[string, string, FieldSpec[]]> = [
    ["decay", st.decayGroup, [
      slider("decay_step", st.decayStep, 0.05, 0.01, 0.5, 0.01, st.decayStepHint),
      number("decay_interval_days", st.decayIntervalDays, 30, 1, st.decayIntervalDaysHint),
      slider("decay_min_confidence", st.decayMinConfidence, 0.15, 0, 1, 0.01, st.decayMinConfidenceHint),
    ]],
    ["candidate", st.candidateGroup, [
      number("candidate_ttl_episodic_days", st.candidateTtlEpisodicDays, 7, 1),
      number("candidate_ttl_precious_days", st.candidateTtlPreciousDays, 30, 1),
      number("candidate_ttl_default_days", st.candidateTtlDefaultDays, 7, 1),
      number("never_accessed_candidate_days", st.neverAccessedCandidateDays, 14, 1),
    ]],
    ["lifecycle", st.lifecycleGroup, [
      number("stale_days_episodic", st.staleDaysEpisodic, 14, 1), number("archive_days_episodic", st.archiveDaysEpisodic, 30, 1),
      number("stale_days_default", st.staleDaysDefault, 365, 1), number("archive_days_default", st.archiveDaysDefault, 730, 1),
      number("contradicted_archive_days", st.contradictedArchiveDays, 90, 1),
    ]],
    ["promotion", st.promotionGroup, [
      slider("promote_importance_threshold", st.promoteImportanceThreshold, 0.75, 0, 1, 0.01), number("promote_injected_threshold", st.promoteInjectedThreshold, 3, 1),
      number("revival_window_days", st.revivalWindowDays, 7, 1), slider("revival_effectiveness_min", st.revivalEffectivenessMin, 0.5, 0, 1, 0.01),
      slider("revival_feedback_min", st.revivalFeedbackMin, 0, -5, 5, 0.1), slider("skill_promote_importance", st.skillPromoteImportance, 0.65, 0, 1, 0.01),
      slider("skill_promote_feedback_min", st.skillPromoteFeedbackMin, 0, -5, 5, 0.1),
    ]],
    ["stale", st.staleGroup, [
      slider("stale_importance_threshold", st.staleImportanceThreshold, 0.45, 0, 1, 0.01), slider("stale_feedback_threshold", st.staleFeedbackThreshold, -0.5, -5, 0, 0.1),
      slider("precious_stale_feedback", st.preciousStaleFeedback, -2, -10, 0, 0.1), slider("precious_stale_importance", st.preciousStaleImportance, 0.3, 0, 1, 0.01),
    ]],
  ];
  const llmFields = [
    slider("sim_threshold", st.simThreshold, 0.6, 0, 1, 0.01, st.simThresholdHint), number("batch_size", st.batchSize, 10, 1, st.batchSizeHint),
    number("importance_limit", st.importanceLimit, 1000, 1, st.importanceLimitHint), number("split_content_threshold", st.splitContentThreshold, 400, 50, st.splitContentThresholdHint),
    number("review_cooldown_seconds", st.reviewCooldownSeconds, 7200, 0, st.reviewCooldownSecondsHint), number("reviewed_ids_max_age_seconds", st.reviewedIdsMaxAgeSeconds, 86400, 0, st.reviewedIdsMaxAgeSecondsHint),
  ];
  const governanceFields = [
    slider("review_confidence_threshold", st.reviewConfidenceThreshold, 0.55, 0, 1, 0.01, st.reviewConfidenceThresholdHint),
    slider("high_importance_threshold", st.highImportanceThreshold, 0.85, 0, 1, 0.01, st.highImportanceThresholdHint),
    slider("auto_approve_confidence", st.autoApproveConfidence, 0.9, 0, 1, 0.01, st.autoApproveConfidenceHint),
    slider("auto_approve_low_risk_confidence", st.autoApproveLowRiskConfidence, 0.7, 0, 1, 0.01, st.autoApproveLowRiskConfidenceHint),
  ];
  const extractionGroups: Array<[string, string, FieldSpec[]]> = [
    ["quality", st.extractionQualityGroup, [slider("min_importance", st.minImportance, 0.3, 0, 1, 0.05, st.minImportanceHint), slider("default_confidence", st.defaultConfidence, 0.65, 0, 1, 0.05, st.defaultConfidenceHint), slider("default_importance", st.defaultImportance, 0.5, 0, 1, 0.05, st.defaultImportanceHint), slider("chinese_detection_ratio", st.chineseDetectionRatio, 0.15, 0.05, 0.5, 0.01, st.chineseDetectionRatioHint)]],
    ["dedup", st.dedupThresholdGroup, [slider("skip_threshold", st.skipThreshold, 0.92, 0.8, 0.99, 0.01, st.skipThresholdHint), slider("update_threshold", st.updateThreshold, 0.78, 0.6, 0.95, 0.01, st.updateThresholdHint), slider("link_threshold", st.linkThreshold, 0.55, 0.3, 0.8, 0.01, st.linkThresholdHint)]],
    ["context", st.contextSearchGroup, [number("context_sample_length", st.contextSampleLength, 200, 50, st.contextSampleLengthHint), number("context_memory_limit", st.contextMemoryLimit, 10, 1, st.contextMemoryLimitHint), number("dedup_search_limit", st.dedupSearchLimit, 5, 1, st.dedupSearchLimitHint), number("max_related_ids", st.maxRelatedIds, 10, 1, st.maxRelatedIdsHint)]],
  ];

  return <Card>
    <CardHeader><CardTitle>{st.title}</CardTitle><CardDescription>{st.description}</CardDescription></CardHeader>
    <CardContent><Tabs defaultValue="rule_curator" className="w-full">
      <TabsList className="grid w-full grid-cols-4"><TabsTrigger value="rule_curator">{st.ruleCurator}</TabsTrigger><TabsTrigger value="llm_curator">{st.llmCurator}</TabsTrigger><TabsTrigger value="governance">{st.governance}</TabsTrigger><TabsTrigger value="extraction_strategy">{st.extractionStrategy}</TabsTrigger></TabsList>
      <TabsContent value="rule_curator" className="mt-4"><Accordion type="multiple" defaultValue={["decay", "candidate"]} className="space-y-2">
        {ruleGroups.map(([key, label, fields]) => <FieldGroup key={key} itemKey={key} label={label} section="rule_curator" values={rule} fields={fields} onChange={onChange} />)}
        <AccordionItem value="precious"><AccordionTrigger className="text-sm">{st.preciousGroup}</AccordionTrigger><AccordionContent className="space-y-3 pt-2"><CheckList label={st.preciousTypes} items={MEMORY_TYPES} selected={(rule.precious_types as string[] | undefined) ?? RULE_PRECIOUS} onToggle={(item, checked) => onListToggle("rule_curator", "precious_types", item, checked)} /></AccordionContent></AccordionItem>
      </Accordion></TabsContent>
      <TabsContent value="llm_curator" className="mt-4 space-y-4"><Fields section="llm_curator" values={llm} fields={llmFields} onChange={onChange} /></TabsContent>
      <TabsContent value="governance" className="mt-4 space-y-4">
        <Fields section="governance" values={governance} fields={governanceFields} onChange={onChange} />
        <CheckList label={st.governancePreciousTypes} items={MEMORY_TYPES} selected={(governance.precious_types as string[] | undefined) ?? GOVERNANCE_PRECIOUS} onToggle={(item, checked) => onListToggle("governance", "precious_types", item, checked)} grid />
        <CheckList label={st.manualOnlyActions} items={ACTIONS} selected={(governance.manual_only_actions as string[] | undefined) ?? ["split"]} onToggle={(item, checked) => onListToggle("governance", "manual_only_actions", item, checked)} />
        <CheckList label={st.mergeActions} items={ACTIONS} selected={(governance.merge_actions as string[] | undefined) ?? ["archive_and_merge_duplicate"]} onToggle={(item, checked) => onListToggle("governance", "merge_actions", item, checked)} />
      </TabsContent>
      <TabsContent value="extraction_strategy" className="mt-4"><Accordion type="multiple" defaultValue={["quality", "dedup"]} className="space-y-2">
        {extractionGroups.map(([key, label, fields]) => <FieldGroup key={key} itemKey={key} label={label} section="extraction_strategy" values={extraction} fields={fields} onChange={onChange} />)}
        <AccordionItem value="defaults"><AccordionTrigger className="text-sm">{st.memoryDefaultsGroup}</AccordionTrigger><AccordionContent className="space-y-4 pt-2">
          <SelectField label={st.defaultMemoryType} hint={st.defaultMemoryTypeHint} value={(extraction.default_memory_type as string) ?? "episodic_memory"} options={MEMORY_TYPES} onChange={(value) => onChange("extraction_strategy", "default_memory_type", value)} />
          <SelectField label={st.defaultStatus} hint={st.defaultStatusHint} value={(extraction.default_status as string) ?? "candidate"} options={["candidate", "active"]} onChange={(value) => onChange("extraction_strategy", "default_status", value)} />
          <SelectField label={st.defaultDecayPolicy} hint={st.defaultDecayPolicyHint} value={(extraction.default_decay_policy as string) ?? "review"} options={["review", "standard", "slow", "never"]} onChange={(value) => onChange("extraction_strategy", "default_decay_policy", value)} />
          <NumberField label={st.titleMaxLength} hint={st.titleMaxLengthHint} value={(extraction.title_max_length as number) ?? 80} min={40} onChange={(value) => onChange("extraction_strategy", "title_max_length", value)} />
          <SelectField label={st.defaultScope} hint={st.defaultScopeHint} value={(extraction.default_scope as string) ?? "global"} options={["global", "session", "agent"]} onChange={(value) => onChange("extraction_strategy", "default_scope", value)} />
        </AccordionContent></AccordionItem>
      </Accordion></TabsContent>
    </Tabs></CardContent>
  </Card>;
}

function slider(key: string, label: string, fallback: number, min: number, max: number, step: number, hint?: string): FieldSpec { return { key, label, hint, fallback, min, max, step }; }
function number(key: string, label: string, fallback: number, min: number, hint?: string): FieldSpec { return { key, label, hint, fallback, min }; }

function Fields({ section, values, fields, onChange }: { section: StrategySection; values: SettingsSection; fields: FieldSpec[]; onChange: StrategySettingsProps["onChange"] }) {
  return <>{fields.map((field) => field.max === undefined
    ? <NumberField key={field.key} label={field.label} hint={field.hint} value={(values[field.key] as number) ?? field.fallback} min={field.min} onChange={(value) => onChange(section, field.key, value)} />
    : <SliderField key={field.key} label={field.label} hint={field.hint} value={(values[field.key] as number) ?? field.fallback} min={field.min} max={field.max} step={field.step ?? 1} onChange={(value) => onChange(section, field.key, value)} />
  )}</>;
}

function FieldGroup({ itemKey, label, ...props }: { itemKey: string; label: string; section: StrategySection; values: SettingsSection; fields: FieldSpec[]; onChange: StrategySettingsProps["onChange"] }) {
  return <AccordionItem value={itemKey}><AccordionTrigger className="text-sm">{label}</AccordionTrigger><AccordionContent className="space-y-4 pt-2"><Fields {...props} /></AccordionContent></AccordionItem>;
}

function CheckList({ label, items, selected, onToggle, grid = false }: { label: string; items: string[]; selected: string[]; onToggle: (item: string, checked: boolean) => void; grid?: boolean }) {
  return <div className="space-y-2"><Label className="text-xs text-muted-foreground">{label}</Label><div className={grid ? "grid grid-cols-2 gap-2" : "flex flex-wrap gap-2"}>{items.map((item) => <label key={item} className="flex items-center gap-2 text-sm"><Checkbox checked={selected.includes(item)} onCheckedChange={(checked) => onToggle(item, checked === true)} />{item}</label>)}</div></div>;
}

function SelectField({ label, hint, value, options, onChange }: { label: string; hint: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <div className="space-y-2"><Label className="text-sm">{label}</Label><Select value={value} onValueChange={onChange}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{options.map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectContent></Select><p className="text-xs text-muted-foreground">{hint}</p></div>;
}
