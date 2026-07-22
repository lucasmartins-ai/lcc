export interface LccOptions {
  model?: string;
  strategy?: 'local-first' | 'truncation' | 'summarization';
  maxTokens?: number;
  removeBoilerplate?: boolean;
  removeNearDuplicates?: boolean;
  similarityThreshold?: number;
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
}

export class LccOptimizer extends LccCompressor {}

export function compressContext(text: string, options?: LccOptions): CompressionResult;
export function estimateTokens(text: string, model?: string): number;
