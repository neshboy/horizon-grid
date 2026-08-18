"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { Check, Copy } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { DetectionRule } from "@/lib/types";

// Preferred left-to-right tab order when these formats are present; anything
// outside this list still renders, appended in first-seen order.
const FORMAT_ORDER = [
  "Sigma",
  "YARA",
  "Splunk SPL",
  "Sentinel KQL",
  "Elastic",
  "QRadar AQL",
  "Suricata",
  "Snort",
  "Zeek",
];

interface DetectionRulesPanelProps {
  detectionRules: DetectionRule[];
  loading?: boolean;
}

export function DetectionRulesPanel({ detectionRules, loading = false }: DetectionRulesPanelProps) {
  const formats = React.useMemo(() => {
    const present = new Set(detectionRules.map((rule) => rule.format));
    const ordered = FORMAT_ORDER.filter((format) => present.has(format));
    const extras = [...present].filter((format) => !FORMAT_ORDER.includes(format));
    return [...ordered, ...extras];
  }, [detectionRules]);

  const [copiedKey, setCopiedKey] = React.useState<string | null>(null);
  const copyTimeout = React.useRef<ReturnType<typeof setTimeout>>();

  const handleCopy = React.useCallback((text: string, key: string) => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopiedKey(key);
        if (copyTimeout.current) clearTimeout(copyTimeout.current);
        copyTimeout.current = setTimeout(() => setCopiedKey(null), 1500);
      })
      .catch(() => {
        /* clipboard access denied or unavailable -- silently ignore */
      });
  }, []);

  React.useEffect(() => {
    return () => {
      if (copyTimeout.current) clearTimeout(copyTimeout.current);
    };
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Detection Rules</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
            <div className="h-8 w-8 animate-pulse rounded-full bg-primary/40" />
            <p className="animate-pulse text-sm text-muted-foreground">Waiting for the final assessment...</p>
          </div>
        ) : detectionRules.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No detection logic generated for this IOC type.
          </p>
        ) : (
          <TabsPrimitive.Root defaultValue={formats[0]} className="flex flex-col gap-4">
            <TabsPrimitive.List className="flex flex-wrap gap-1 border-b border-border pb-2">
              {formats.map((format) => (
                <TabsPrimitive.Trigger
                  key={format}
                  value={format}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors",
                    "hover:bg-muted hover:text-foreground",
                    "data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
                  )}
                >
                  {format}
                </TabsPrimitive.Trigger>
              ))}
            </TabsPrimitive.List>

            {formats.map((format) => (
              <TabsPrimitive.Content key={format} value={format} className="flex flex-col gap-4">
                {detectionRules
                  .filter((rule) => rule.format === format)
                  .map((rule, index) => {
                    const key = `${format}-${index}`;
                    const isCopied = copiedKey === key;
                    return (
                      <div key={key} className="flex flex-col gap-2">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-sm font-medium text-foreground">{rule.title}</p>
                          <button
                            type="button"
                            onClick={() => handleCopy(rule.rule, key)}
                            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          >
                            {isCopied ? (
                              <>
                                <Check className="h-3 w-3 text-success" />
                                Copied
                              </>
                            ) : (
                              <>
                                <Copy className="h-3 w-3" />
                                Copy
                              </>
                            )}
                          </button>
                        </div>
                        <pre className="overflow-x-auto rounded-md border border-border bg-background p-3 text-xs">
                          <code className="font-mono text-foreground">{rule.rule}</code>
                        </pre>
                      </div>
                    );
                  })}
              </TabsPrimitive.Content>
            ))}
          </TabsPrimitive.Root>
        )}
      </CardContent>
    </Card>
  );
}
