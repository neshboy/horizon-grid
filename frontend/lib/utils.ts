import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function verdictColor(verdict?: string | null): string {
  switch (verdict) {
    case "highly_malicious":
    case "malicious":
      return "text-destructive";
    case "suspicious":
      return "text-warning";
    case "benign":
    case "likely_benign":
      return "text-success";
    case "tor_exit_node":
    case "vpn":
    case "cdn":
    case "cloud_infrastructure":
    case "scanner":
    case "dormant_infrastructure":
      return "text-accent";
    default:
      return "text-muted-foreground";
  }
}

export function riskScoreColor(score?: number | null): string {
  if (score == null) return "text-muted-foreground";
  if (score >= 75) return "text-destructive";
  if (score >= 50) return "text-warning";
  if (score >= 25) return "text-accent";
  return "text-success";
}
