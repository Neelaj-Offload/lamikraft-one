# Lamikraft One — concept and build package

Prepared 12 October 2026 for Crown / Lamikraft.

## What is included

- `LAMIKRAFT_ONE_CONCEPT.md` — the proposed product, daily briefings, role-specific agents, new capabilities, legacy preservation and release sequence.
- `OPUS_5_5_BUILD_PROMPT.md` — the complete implementation prompt, including design, business rules, permissions, voice, WhatsApp, migration and acceptance scenarios.
- `LAMIKRAFT_ONE_DAILY_BRIEFING.png` — the daily home-screen concept incorporating the personalised summary requirement.
- `LAMIKRAFT_ONE_WORKSPACE.png` — the broader workspace and WhatsApp interaction concept.
- `CURRENT_STATE_SPEC.md` — an unchanged copy of the supplied old-system specification, used as the feature baseline.
- `IMAGE_PROMPTS.md` — the prompts used with the built-in image generation tool.

## Use it in a coding environment

1. Select Claude Opus 5.5 in your coding environment, with medium effort as the starting setting.
2. Put this package's files in the project, or attach the concept, build prompt, old specification and images.
3. Paste the contents of `OPUS_5_5_BUILD_PROMPT.md` as the build instruction. Alternatively, instruct the coding agent to read that file and execute it, with the other files as supporting references.
4. Let the agent implement and verify successive slices. At a session boundary, tell it to resume from `docs/BUILD_STATE.md` and complete the next unblocked work. Inspect its coverage and test evidence before using live company data or enabling external actions.

The model name in a text prompt does not select the model. Integration credentials must be configured separately; do not paste secrets into project documents. Missing live credentials should leave working local/sandbox flows with clear labels.

## Product decisions in this proposal

The daily briefing is the main home screen. Each employee gets relevant tasks, changes, suggested actions, reasons and source links. One personal assistant coordinates specialist capabilities; permissions remain enforced by the application. Voice, typing, direct controls and WhatsApp operate on the same records.

The implementation includes complete legacy feature parity and a connected operational ERP roadmap. A chosen accounting-system adapter is the initial statutory accounting approach. Full native accounting, payroll and HR are separately scoped expansions. All names, quantities and events in the visual concepts are illustrative demo content.

The written requirements are authoritative for implementation. Image-generated text, status counts, layout details and decorative metrics are inspiration only. Recreate the intended design using real components and verified application data.

## Verified external references

- [Anthropic's Opus 5.5 prompting guide](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5) — model-specific effort, progress and design guidance.
- [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/) — channel consent, template/window and escalation requirements.

This is a product design and implementation-prompt package. It does not contain a built ERP application.
