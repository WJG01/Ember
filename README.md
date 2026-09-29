# Ember

**Turns what your kids watch into what your family does.**

Built for the [Google AI Builder Cup 2026](https://aibuildercup.com) — theme: *Media, Content & Digital Experiences*.

---

## The problem

Children spend hours a day watching video. A lot of it is genuinely good — craft, science, construction, cooking, survival technique. But consumption is where it stops. Almost none of it turns into an attempt, a skill, or a shared afternoon.

Parents can already see *how many hours*. Nothing tells them what it means, or what to do about it.

Screen-time tools **restrict**. Platform recommenders optimise for **retention** — their idea of a good outcome is another video. Educational apps ignore the child's actual interests and start from a curriculum.

Ember takes a different position: attention a child has already given something is a signal, not a problem. Our job is to redirect it.

## What it does

1. **Connect** — a guardian authorises access to their child's YouTube signal
2. **Understand** — Gemini analyses the *videos themselves*, not the titles
3. **Map** — builds a **Curiosity Graph** of inferred themes per child
4. **Act** — proposes one concrete, grounded activity each week

Completion feedback flows back into the graph, so it sharpens over time.

## What makes it different

**We analyse the content, not the metadata.** Gemini ingests each video by URL and extracts concepts, modality (procedural vs passive), vocabulary band and latent real-world skill. A title cannot tell you whether a survival video is a documentary or a game stream. Video understanding can.

**Themes, not tags.** A tag-based system returns *"Survival · Gaming · DIY"* — which the parent already knew. Ember returns:

> **Improvisation under constraint.** Across 38 videos Aiden skips the entertainment framing and rewatches the segments where something functional is built from nothing. He has never searched for this.

Every theme carries reasoning and cited evidence. A theme without reasoning is just a tag.

**Common Ground.** With two children, Ember intersects their graphs at *theme level* and generates an activity neither profile would produce alone. Survival content and baking shorts share *making things work with limited ingredients* → cooking over a fire you build. Nothing at the tag level would ever connect those.

**Every output ends offscreen.** A design constraint, not a feature. You don't solve a screen-time problem by adding a screen. Each generation terminates in a printable Quest Card and a physical activity.

**Household-scoped.** Data never leaves the family tenant. Outsiders — teachers, grandparents — never get accounts. A guardian generates a PDF report and hands it over. Share by artifact, not by access.

## Where the data comes from

The YouTube Data API **cannot** return watch history. `relatedPlaylists.watchHistory` was deprecated in 2016 and returns the placeholder `HL`; no OAuth scope for history exists. So we offer three tiers, increasing in depth and friction.

| Tier | Source | Friction | Notes |
|---|---|---|---|
| **0** | Guardian saves a video | None | Share-sheet target. Declared intent — solves cold start, can't produce insight alone |
| **1** | Child's likes + subscriptions | One tap | **Default.** Single OAuth consent, `youtube.readonly`. Real child signal, no file handling |
| **2** | Full watch history | High | Takeout JSON upload or Data Portability API. Richest signal, offered as "go deeper" |

Tier 1 reads `contentDetails.relatedPlaylists.likes` via `channels.list`, then `playlistItems.list` against that playlist, plus `subscriptions.list`.

### Consent model

Ember requests no access a guardian doesn't already hold. Where a child has a Google Account, Family Link establishes the parent's right to access and export that child's data. We exercise that existing right, with explicit authorisation, and make the result useful.

- Parent-initiated and consent-gated, always
- No cross-household features, no social layer, no peer benchmarking
- No developmental scoring, ranking or diagnosis
- No behavioural advertising, no data sale, ever
- Revoking consent deletes records, not just a flag

## Architecture

Google Cloud exclusively.

```
Takeout / DPA / OAuth signal
        ↓
[Content Sense]   Gemini Flash — native video understanding
        ↓
[Curiosity Graph] Gemini Pro — themes + reasoning + evidence
        ↓
[Quest Planner]   Gemini Pro + Search grounding — real local options
        ↓
[Guardian]        Gemini Flash — safety and age-appropriateness gate
        ↓
Parent digest + printable Quest Card → feedback → back to the graph
```

Four agents, one Cloud Run service. The agent graph is defined in ADK and deployed as a single container — the agentic architecture, with one deployment and one log stream to debug.

| Layer | Services |
|---|---|
| Presentation | Firebase Hosting, Firebase Auth, App Check |
| Orchestration | Cloud Run, Agent Development Kit, Cloud Tasks, Cloud Scheduler |
| Intelligence | Vertex AI (Gemini Flash + Pro), Grounding with Google Search, Embeddings, Imagen |
| Data | Firestore, Cloud Storage, Secret Manager |
| Ops | Cloud Build, Artifact Registry, Cloud Logging |

### Why the video cache sits outside the tenant

A video's content is a property of the video, not of the child who watched it. Analysis is cached globally by video ID in a non-tenanted collection containing no personal data. Children's viewing concentrates heavily in popular content, so cache hit rate climbs with adoption — **the thousandth household costs less to serve than the first.**

## Repository layout

```
├── scripts/            # validation and one-off tooling
│   └── test_youtube_signals.py
├── services/           # Cloud Run service (ADK agents + API)
├── web/                # Firebase Hosting client
├── data/               # synthetic personas and fixtures (no real user data)
└── docs/
    └── Ember_Solution_Design.pdf
```

## Getting started

### Prerequisites

- Python 3.11+
- A GCP project with **YouTube Data API v3** enabled
- OAuth client (Desktop app) in **Testing** mode, with your test account added as a test user
- Scope: `https://www.googleapis.com/auth/youtube.readonly`

### Validate the tier 1 signal

```bash
cd scripts
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install google-auth-oauthlib google-api-python-client
python test_youtube_signals.py
```

Sign in **as the test account**. Click through the unverified-app warning — expected in Testing mode. Results are written to `ember_signals.json`.

> **Note:** the likes playlist only exists once the account has a YouTube channel. If `channels.list` returns no items, create a channel on that account, re-like the videos, and rerun.

### Never commit

`client_secret.json`, `token.json`, `ember_signals.json`, `venv/`. Add `.gitignore` **before** the first commit — deleting a secret in a later commit doesn't remove it from history. If one slips through, delete the OAuth client in GCP and create a new one.

## Status

| | |
|---|---|
| Gate 0 — does Gemini return non-obvious themes? | in progress |
| Tier 1 signal validation | in progress |
| Tier 1 on a **supervised** child account | **not yet validated** |
| Takeout parser | not started |
| Curiosity Graph synthesis | not started |
| Common Ground intersection | not started |
| Quest Card + print view | not started |

### Known open items

- **Supervised-account API access.** Tier 1 is confirmed against the public API surface but not against a supervised child account, where Google may restrict access. Tier 2 is the fallback.
- **YouTube Kids.** Kids-profile viewing may not appear in the Takeout history file. Unconfirmed. Ember targets supervised YouTube.
- **Likes sparsity.** A child may like few videos. Subscriptions compensate, but if both are thin the guardian is prompted to add tier 2.

## Demo data

Sibling histories are **authored**; every video in them is **real** and genuinely processed by Gemini. The watch log is synthetic, the content understanding is not. This is stated up front in the demo video — an honest synthetic setup is more credible than a suspiciously flawless live demo.

## Team

Four members. Backend/GCP · ML/Data · Frontend · Design/Pitch.

## License

TBD — hackathon submission.
