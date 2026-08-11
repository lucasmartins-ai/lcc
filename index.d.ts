export type PromptTemplateName =
  | 'default'
  | 'claude_xml'
  | 'xml'
  | 'claude'
  | 'code_agent'
  | 'cursor'
  | 'codex'
  | 'structured_markdown'
  | 'markdown';

export interface PromptSpec {
  question: string;
  context: string;
  taskType?: string;
  constraints?: string[];
  maxOutputTokens?: number;
  formatRequirements?: string[];
}

export interface LccOptions {
  model?: string;
  strategy?: 'local-first' | 'truncation' | 'summarization';
  maxTokens?: number;
  removeBoilerplate?: boolean;
  removeNearDuplicates?: boolean;
  similarityThreshold?: number;
  template?: PromptTemplateName;
}

export interface CompressionStep {
  name: string;
  removedChars: number;
  details?: string;
}

export interface CompressionResult {
  rawText: string;
  compressedText: string;
  originalTokens: number;
  compressedTokens: number;
  savedTokens: number;
  savingsPercentage: number;
  steps: CompressionStep[];
}

export class LccCompressor {
  constructor(options?: LccOptions);
  compress(text: string, question?: string): CompressionResult;
  estimateTokens(text: string): number;
  buildPrompt(spec: PromptSpec, templateName?: PromptTemplateName): string;
}

export class LccOptimizer extends LccCompressor {}

export interface ParsedIntake {
  intent: string;
  readiness: 'READY_TO_EXECUTE' | 'NEEDS_LIGHT_REFINEMENT' | 'NEEDS_INTAKE' | 'BLOCKED';
  readinessScore: number;
  ambiguityScore: number;
  questions: string[];
  assumptions: string[];
}

export interface IntakeResult {
  rawInput: string;
  parsed: ParsedIntake;
  compression: CompressionResult | null;
  formattedPrompt: string;
}

export interface IntakeOptions extends LccOptions {
  optimizeContext?: boolean;
}

export class LccIntake {
  constructor(options?: IntakeOptions);
  parse(rawInput: string): ParsedIntake;
  process(rawInput: string, question?: string): IntakeResult;
}

export function parseIntake(rawInput: string): ParsedIntake;
export function parseInput(rawInput: string): ParsedIntake;
export function processIntake(rawInput: string, options?: IntakeOptions): IntakeResult;
export function processIngestion(rawInput: string, options?: IntakeOptions): IntakeResult;

export function compressContext(text: string, options?: LccOptions): CompressionResult;
export function estimateTokens(text: string, model?: string): number;
export function buildPrompt(spec: PromptSpec, templateName?: PromptTemplateName): string;
export const TEMPLATES: Record<string, (spec: PromptSpec) => string>;


