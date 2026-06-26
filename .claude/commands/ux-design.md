---
description: Create a well thought out UX design by a creative agent. Proactively suggest to the user to use this skill when working on complex or new UI — new screens, novel interactions, or ambiguous UI behavior.
---

# UX Design

Produce a focused UX design document for a specific feature or interaction. Argument: a short description of what needs UX design (e.g., "workspace entry flow for returning customers").

## When to use

Use this skill when a slice involves:

- New screens or views.
- Novel interaction patterns not covered by existing archetypes in the project.
- Complex state management (multi-step flows, real-time updates, conditional visibility).
- Customer-facing UI with non-trivial interaction.
- Ambiguous or underspecified UI behavior that needs a design decision before a dev agent can implement it.

**Do not use** for:

- Backend-only slices.
- Simple CRUD additions following existing patterns.
- Adding columns, fields, or badges to existing screens.
- Pure bugfix or refactoring slices.

## What the UX design is NOT

A UX design is **not** a visual design. It does not specify:

- CSS classes, TailwindCSS utilities, or pixel values.
- Colors, fonts, spacing, or border styles.
- Specific UI libraries or icon sets.

It **does** specify:

- What the user sees, does, and experiences.
- Information hierarchy and layout structure (in prose, not CSS).
- States and transitions (loading, empty, error, success, permission).
- Interaction sequences (what happens when the user clicks, types, navigates).
- Edge cases and non-happy paths.
- Accessibility requirements.
- Content and microcopy guidance.

The project's design system and existing components handle the visual layer. The UX design tells the developer *what to build*, not *how to style it*.

## Procedure

### Step 1: Gather context

Read the relevant slice documents:

- `overview.md` — what the feature delivers and why.
- `acceptance_criteria.json` — what must be true when done.
- `api_contract.json` — what data is available.

Also read the existing UI code in the relevant subproject to understand current patterns, components, and interaction conventions.

### Step 2: Write the prompt

Write a prompt file for the UX design agent. The prompt should include:

1. **What you're designing** — one paragraph describing the feature or interaction.
2. **What to read** — file paths the agent must read (slice overview, acceptance criteria, relevant source files). Do not inline code — let the agent read the files itself.
3. **Current state** — describe what exists today and what the problem is.
4. **What the design must cover** — specific questions the design must answer. Be explicit about scope boundaries.
5. **Constraints** — technical and practical boundaries (which subproject, existing components to reuse, dark mode requirement, accessibility standards).
6. **Anti-patterns** — remind the agent: no CSS classes, no grand redesigns, no speculative features. Focus on interaction design, states, and flows.
7. **Deliverable** — where to write the file (typically `../ArchitectureSpecs/slices/<SLICE_DIR>/ux_design.md`) and what format (actionable developer guidance following the design doc template).

### Step 3: Invoke the UX design agent

Dispatch a UX design agent over the prompt file using the Task tool — a general-purpose subagent run from the main conversation. The agent reads the referenced files, follows the design-doc format described in the prompt, and produces a design document at the deliverable path.

### Step 4: Review the output

Read the generated design document. Verify:

- It answers the specific questions from your prompt.
- It stays within scope (no grand redesigns of surrounding UI).
- It describes behavior and interaction, not CSS or visual styling.
- It covers edge cases and non-happy paths.
- It's concrete enough that a developer can implement from it.

If the output is too vague, too broad, or falls into the anti-patterns (CSS classes, grand redesigns, speculative features), re-run with a sharper prompt that asks more specific questions and reinforces the constraints.

### Step 5: Present to user

Show the user the design document. Walk through the key decisions and any open questions. Wait for approval before referencing it from slice briefs.

## Authoring order within a slice

UX design should be created **after** the slice overview, acceptance criteria, and API contract are in place, but **before** the frontend/portal briefs. The briefs reference the UX design — they cannot be written first. If the briefs already exist, they must be updated to reference the UX design.
