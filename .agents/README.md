# Repository agent conventions

[Root AGENTS.md](../AGENTS.md) is the automatically discovered repository entry
point. Keep it concise: durable constraints, useful commands, and pointers to
task-specific documentation. Add nested `AGENTS.md` files only where a directory
has distinct instructions; keep changing release status in the dated audits.

[The repository constitution](spec/constitution.md) is Countscape's durable
product contract. It is ordinary referenced documentation, read for behavior and
invariant changes; `.agents/spec` has no special Codex discovery behavior.
Keep its ownership and concurrency rules consistent with the
[security model](../docs/security-model.md) and
[lifecycle guide](../docs/lifecycle.md).

Codex discovers repository skills in `.agents/skills/<name>/SKILL.md`. Add one
when a recurring task benefits from its own workflow, using a short description
with a specific trigger and loading supporting references only when needed.
The current verification scripts and release checklist remain their canonical
sources; no additional skill is required to run them.

This organization follows official guidance reviewed on 2026-10-29:

- [AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Skills and local discovery](https://learn.chatgpt.com/docs/build-skills)
- [Keeping instructions focused](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)
