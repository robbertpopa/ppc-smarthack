# PPC theme and scoring criteria

Source: the document "Smarthack XI 2026: PPC theme" and the "AI awareness briefing / Meet PPC" presentation.

## Theme
**"24h to Power PPC: AI in energy, from data to action"**

We build an **AI agent** that, based on an **ML model trained by us**, makes decisions and acts on a real energy problem. The team picks the challenge after PPC's presentation on day one.

An agent, in the sense of the theme, is not just a chatbot: it **perceives** (data), **estimates** (ML models trained by the team), **decides** (based on estimates and real constraints) and **acts** (prioritises, recommends, generates, alerts, schedules). Every decision must be traceable back to the model's prediction.

## Mandatory requirements
- At least one ML model trained or fine-tuned by the team, evaluated on a **separate test set** and compared with a **simple baseline**. The training code is in the repository and the model runs in our own code, **not through an external API**.
- An LLM is not enough. It may coordinate the agent or provide the interface, but the agent must rely on our model.
- The agent must **execute actions**, not just converse.
- Data: only public, synthetic, or collected and annotated by the team, **with sources stated**.
- Code in a **public repository**, with **commits made during the 24 hours**.

## What a "complete project" means
1. Data prepared by the team (justified sources, cleaned, features with a reason; synthetic only if "realistic").
2. A model trained and evaluated properly: separate test set, baseline, **error analysis**.
3. A **justified decision layer**: thresholds chosen with a reason, real constraints (e.g. how many cases a crew can check per day), confidence level.
4. Concrete actions: priority list, alert, report, scheduled intervention.
5. Difficult situations: missing data, rare cases, wrong data, uncertainty. The agent must be able to say **"I am not sure"** and send the case to a human.
6. Explainability: why a decision was made.
7. Reproducibility: the jury runs the project from the README, and the results in the presentation come from our evaluation script.

## Scoring (100 points)
| Criterion | Points |
|---|---|
| Idea and relevance for PPC | 25 |
| ML quality | 25 |
| Robustness | 10 |
| The agent (full flow, decision layer) | 25 |
| Explainability | 10 |
| Demo and repository | 5 |

"The winner is the team with the best idea for PPC that implements it best. One without the other is not enough."

## Deliverables
- A working project in a public GitHub repository, plus presentation materials.
- Live demo, followed by technical questions.

## What this means for us
- **Code:** the requirement of commits during the 24 hours means we **do not commit code before the hackathon**. For now we version only documentation. To clarify with the organisers: how much preparation work (research, local exploration) is acceptable.
- **Live demo ≠ real flight/hardware:** simulation is acceptable, but the decision part must run live, and synthetic data must be justified as realistic.
- **The model must be trained by us** (not a pretrained model used as is) and run in our own code.
- Points are split almost equally between idea (25), ML (25) and agent (25). A good model without action, or a good idea without a model, is not enough.
