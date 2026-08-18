import { Search, ShieldAlert, Siren } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { FinalAssessment } from "@/lib/types";

interface RecommendedActionsPanelProps {
  assessment: FinalAssessment | null;
}

const SECTION_TITLES_AND_ICONS = [
  { title: "Recommended Actions", Icon: ShieldAlert },
  { title: "Investigation Priorities", Icon: Search },
  { title: "Incident Response", Icon: Siren },
] as const;

export function RecommendedActionsPanel({ assessment }: RecommendedActionsPanelProps) {
  if (!assessment) {
    // Render the section shell (titles visible) with a loading skeleton
    // instead of vanishing entirely -- an absent section reads as "this
    // feature doesn't exist" rather than "still loading."
    return (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {SECTION_TITLES_AND_ICONS.map(({ title }) => (
          <Card key={title}>
            <CardHeader>
              <CardTitle>{title}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-2">
                <div className="h-3 w-full animate-pulse rounded bg-muted" />
                <div className="h-3 w-5/6 animate-pulse rounded bg-muted" />
                <div className="h-3 w-2/3 animate-pulse rounded bg-muted" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const sections = [
    {
      title: "Recommended Actions",
      items: assessment.recommended_actions,
      Icon: ShieldAlert,
    },
    {
      title: "Investigation Priorities",
      items: assessment.investigation_priorities,
      Icon: Search,
    },
    {
      title: "Incident Response",
      items: assessment.incident_response_recommendations,
      Icon: Siren,
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {sections.map(({ title, items, Icon }) => (
        <Card key={title}>
          <CardHeader>
            <CardTitle>{title}</CardTitle>
          </CardHeader>
          <CardContent>
            {items.length === 0 ? (
              <p className="text-sm text-muted-foreground">None identified.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {items.map((item, index) => (
                  <li key={index} className="flex items-start gap-2 text-sm text-foreground">
                    <Icon className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent" aria-hidden="true" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
