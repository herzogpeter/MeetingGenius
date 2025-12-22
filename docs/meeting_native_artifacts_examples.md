# Meeting-Native Artifacts: Verification Examples

These transcript snippets are used for manual sanity-checking that MeetingGenius produces meeting-native artifacts (no external research required) and updates stable list cards instead of creating new ones.

## Standup (actions + blockers)

- "Yesterday I fixed the flaky CI test. Today I'll pair with Alex on the login bug. I'm blocked on a backend token issue."
- "Alex, can you take the token refresh fix by EOD Friday?"

Expected meeting-native cards updated/created:
- `list-actions`: "Owner: Alex — Fix token refresh (Due: EOD Friday)"; "Owner: <speaker> — Pair with Alex on login bug"
- `list-risks`: "Blocked: backend token issue"

## Sales Call (next steps + questions + decisions)

- "If you can send the security questionnaire, we’ll review it this week."
- "Can your team support SSO via SAML on the Enterprise plan?"
- "Let’s proceed with a pilot for 50 seats starting next month."

Expected meeting-native cards updated/created:
- `list-next-steps`: "Send security questionnaire"; "Review questionnaire this week"
- `list-questions`: "SSO via SAML on Enterprise plan?"
- `list-decisions`: "Proceed with a 50-seat pilot starting next month"

## Planning (decisions + risks + action items)

- "Decision: we’re shipping scope A in sprint 12 and pushing scope B to sprint 13."
- "Risk: infra capacity might not handle the launch spike."
- "Jamie will draft the rollout plan by Monday."

Expected meeting-native cards updated/created:
- `list-decisions`: "Ship scope A in sprint 12; push scope B to sprint 13"
- `list-risks`: "Infra capacity may not handle launch spike"
- `list-actions`: "Owner: Jamie — Draft rollout plan (Due: Monday)"
