export interface FunctionComplexity {
  name: string;
  line: number;
  complexity: number;
}

export interface FileResult {
  file: string;
  language: "python" | "typescript";
  functions: FunctionComplexity[];
}
