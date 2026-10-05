# Ember — Team Handoff Brief

**How to use this:** paste this whole file into a new Claude conversation as your first message. Claude will then have the full project context and can guide you the same way it has been guiding the team lead. Add your own question at the end.

---

## Instruction to Claude

You are acting as an experienced solution architect advising a four-person team building a hackathon project. You have social-media-industry background (YouTube, Meta). Be direct, push back when something is a bad idea, flag risks early, and give concrete next actions rather than general advice. The team is time-boxed and some members are new to Google Cloud, so be specific with commands and console navigation. Everything below is established context — do not re-litigate settled decisions unless you spot a real problem.

---

## 1. The competition

- **Google AI Builder Cup 2026**
- **Theme:** Media, Content & Digital Experiences
- **Submission: 19 October 2026** (team submits 18 Oct — never on deadline day)
- **Team size:** 4 — Backend/GCP, ML/Data, Frontend, Design/Pitch

**Judging criteria**
| Weight | Criterion |
|---|---|
| 40% | Technical Merit & Gen AI Implementation — explicitly penalises "basic or superficial" Gen AI use |
| 25% | Problem Alignment & Impact |
| 25% | Innovation & Creativity |
| 10% | User Experience & Solution Design |

**Mandatory:** a Google model (Gemini/Gemma), an agentic platform (Agent Platform / ADK), deployment on Cloud Run or Firebase, a proposal deck, a functional prototype, and a 3-minute demo video. All materials in English.

---

## 2. The product

**Ember — turns what your kids watch into what your family does.**

### Problem
Children watch hours of video daily. Much of it is genuinely good — craft, science, cooking, construction. But consumption is where it stops. Parents can see *how many hours*; nothing tells them what it means or what to do about it. Screen-time tools **restrict**. Platform recommenders optimise for **retention** — their best outcome is another video.

Ember's position: attention a child already gave something is a signal, not a problem. The job is to **redirect** it.

### The loop
```
Connect → Understand → Map → Act → feedback → back to Map
```
1. **Connect** — guardian authorises access to the child's YouTube signal
2. **Understand** — Gemini analyses *the videos themselves*, not titles
3. **Map** — builds a **Curiosity Graph** of inferred themes per child
4. **Act** — proposes one grounded, doable activity each week

### Five differentiators
1. **Video understanding, not metadata.** Titles cannot distinguish a survival documentary from a survival game stream.
2. **Themes, not tags.** Every theme carries reasoning and cited evidence. A theme without reasoning is a tag.
3. **Every output ends offscreen.** Design constraint: you don't solve a screen-time problem by adding a screen. Outputs terminate in a printable Quest Card.
4. **Common Ground.** Intersect two siblings' graphs at theme level → an activity neither profile produces alone.
5. **Household-scoped.** Data never leaves the family tenant. Outsiders get a generated PDF, never an account. *Share by artifact, not by access.*

---

## 3. Decisions already made — do not revisit

| Decision | Why |
|---|---|
| Household is the tenant, not the individual | Enables Common Ground; matches how families work; legible subscription model |
| Guardians only, no extended family | An aunt with her own kids has no stake in this child's development |
| Video understanding, not metadata | The foundation of everything above it |
| AI proposes the activity, guardian edits | Handing synthesis back to the user signals the model does analysis but not reasoning |
| Weekly, not monthly | Monthly is too slow to build a habit and too slow to demo |
| Four agents, one Cloud Run service | Agentic architecture, one deployment to debug under pressure |
| Separate web app, NOT inside YouTube | No surface to build on; would contradict the thesis; wrong moment |
| Screen 8 ("This week") is home, not the graph | Putting the graph first turns Ember into an analytics dashboard |
| Saves are an input to the graph, never the source | A product built on guardian saves can only reflect what the guardian already believed |
| Three input tiers, tier 1 as default | Takeout as the front door would lose non-technical households |
| Synthetic histories, real videos | Deterministic demo with genuine model work |

### Positioning discipline
**Ember redirects, it does not restrict.** Never describe it as a parental control app — in code comments, UI copy, the deck, or on stage. The moment it's filed mentally as "another screen-time app," the differentiation is gone.

---

## 4. Where the data comes from

**The YouTube Data API cannot return watch history.** `relatedPlaylists.watchHistory` was deprecated in 2016 and returns the placeholder `HL`. No OAuth scope for history exists. `favorites` is also deprecated. Only `likes`, `uploads` and `subscriptions` remain usable. *Do not waste time rediscovering this.*

| Tier | Source | Friction | Status |
|---|---|---|---|
| 0 | Guardian saves a video | none | not built |
| **1** | Child's likes + subscriptions via one OAuth tap | one tap | **VALIDATED** |
| 2 | Full watch history — Takeout JSON or Data Portability API | high | not built |

Tier 1 reads `contentDetails.relatedPlaylists.likes` from `channels.list`, then `playlistItems.list`, plus `subscriptions.list`. Scope: `youtube.readonly`.

**Consent chain:** Family Link establishes that a parent may access and export their child's Google data. Ember exercises that existing right with explicit authorisation.

**Gotcha found the hard way:** the likes playlist only exists once the account has a YouTube channel. If `channels.list` returns no items, there is nothing to read. Ember must detect and handle this in onboarding.

---

## 5. Architecture — Google Cloud only

```
signal in
   ↓
[Content Sense]    Gemini Flash — native video understanding
   ↓
[Curiosity Graph]  Gemini Pro — themes + reasoning + evidence
   ↓
[Quest Planner]    Gemini Pro + Search grounding — real local options
   ↓
[Guardian]         Gemini Flash — safety and age gate
   ↓
parent digest + printable Quest Card → feedback → back to the graph
```

| Layer | Services |
|---|---|
| Presentation | Firebase Hosting, Firebase Auth, App Check |
| Orchestration | Cloud Run, Agent Development Kit, Cloud Tasks, Cloud Scheduler |
| Intelligence | Agent Platform — Gemini Flash + Pro, Search grounding, Embeddings, Imagen |
| Data | Firestore, Cloud Storage, Secret Manager |
| Ops | Cloud Build, Artifact Registry, Cloud Logging |

**Naming note:** Vertex AI was renamed to the **Gemini Enterprise Agent Platform**; it no longer appears in the Cloud Console as "Vertex AI" (cutover 21 May 2026). Look for **Agent Platform**. The API service name is unchanged — search `aiplatform` in the API Library, not "Vertex AI". ADK is unaffected.

**Why the video cache sits outside the tenant:** a video's content is a property of the video, not the child. Cached globally by video ID, contains no personal data, and cache hit rate climbs with adoption — the thousandth household costs less to serve than the first. This is the unit-economics argument in the pitch.

---

## 6. Current state

### Done
- GCP project `ember-hackathon-google-2026`, billing linked, IAM for all four members
- YouTube Data API v3 enabled, OAuth consent screen in Testing mode
- Test account **Llamie** (`llamie12345678910@gmail.com`) — a fake child, 17 liked videos, 4 subscriptions, has a YouTube channel
- `test_youtube_signals.py` — tier 1 validation, **working**
- `content_sense.py` — stage 1 of the pipeline, **working**
- Solution design document v1.2 (21 pages)
- GitHub repo created

### GATE 0 — PASSED
Fed Llamie's liked videos to Gemini and asked for underlying themes. Returned four genuine behavioural themes, not tags:
1. Subverting the mundane — re-engineering everyday staples
2. Accessing the restricted — behind-the-scenes and hidden systems
3. The gamification of rarity, loot tiers and values
4. Mechanical choreography and "oddly satisfying" optimisation

**The key finding.** The team lead expected *"likes Japanese food → take a trip to Japan."* Gemini found the food was incidental — the real draw was **things being made with precision, and systems working beautifully**. That also explains an ocean-cleaning robot video sitting in the same set, which no tag-based system would ever connect to ramen.

Two consequences:
- **This is the demo beat.** Show the wrong answer first, then the real one.
- **A child's history looks random because topics change, but what draws them doesn't.** YouTube's algorithm scattering them across topics is an *asset* — more angles on the same underlying interest.

Also learned: theme 3 (rarity/loot tiers) is a real interest that **does not transfer** to an offline activity. The schema has a `transferable` flag for exactly this. Don't discard those themes; mark them low-transferability.

### Not yet validated
- Tier 1 on a **supervised** child account (only tested on a standard account)
- Whether YouTube Kids viewing appears in Takeout
- Whether the Quest Planner produces good activities from themes

---

## 7. The pipeline — build locally first

```
ember_signals.json         ← test_youtube_signals.py   DONE
   ↓
video_records.json         ← content_sense.py          WORKING
   ↓
themes.json                ← curiosity_graph.py        NEXT
   ↓
quest.json                 ← quest_planner.py          after that
   ↓
Firestore → Cloud Run → frontend
```

**Build the intelligence as local scripts writing JSON before touching infrastructure.** The Content Sense prompt will need ~20 revisions; locally that's a 2-second run, deployed it's a 4-minute container rebuild. Teams lose days to this.

### The schema that matters
Per video, Content Sense extracts: `surface_topic`, `underlying_draw`, `concepts`, `modality` (procedural/narrative/passive/reactive), `vocabulary_band`, `affect`, `latent_skill`, `transferable`, `evidence`.

**`surface_topic` vs `underlying_draw` is the whole product.** Surface is what a title-based system would say ("Japanese gourmet sandwiches"). Underlying is the actual pattern of appeal ("humble everyday foods deconstructed and rebuilt"). If those two columns read the same, the prompt has failed.

---

## 8. Next steps by role

### ML / Data
- [ ] Complete the `content_sense.py` run on all 17 videos
- [ ] Review surface vs underlying across all of them — do several *unrelated* surfaces share an underlying draw? That's what the graph needs.
- [ ] Build `curiosity_graph.py` — synthesise records into 3–6 named themes with reasoning, evidence, confidence, trajectory
- [ ] **Name themes in plain parent language.** Gate 0 returned things like "Subverting the Mundane: Re-Engineering Everyday Staples" — right insight, wrong register. Should be "Taking ordinary things apart." Under six words, no colons, no jargon.
- [ ] Build `quest_planner.py` — themes → one weekend activity, with per-child ownership split

### Backend / GCP
- [ ] Enable Agent Platform API (search `aiplatform`, not "Vertex AI")
- [ ] Budget alert: $50, alerts at 50/90/100% to all four
- [ ] Firestore schema + `familyId` security rules
- [ ] Takeout `.zip` parser — accept the whole archive, locate the history file, filter Music/ads/non-video, extract video IDs, dedupe with a rewatch count, bound to 90 days
- [ ] Containerise the pipeline → Cloud Run
- [ ] Switch from the AI Studio API key to Agent Platform auth

### Frontend
- [ ] **Screen 8 "This week" first** — simpler, what a real guardian sees 95% of the time, and it guarantees something demoable if the graph runs late
- [ ] Then screen 11, the Curiosity Graph — on camera for ~50 seconds, so it must not be rushed
- [ ] **No live physics simulation** for the graph. Compute the layout once, seed deterministically, animate into fixed positions over ~800ms. A force layout looks great until a node lands badly on the take you're filming.
- [ ] Quest Card print stylesheet
- [ ] Firebase Hosting

### Design / Pitch
- [ ] Write two child personas **as characters first**, then work backwards to the histories
- [ ] **Surfaces scattered across 4–5 unrelated categories, themes coherent underneath.** A real history looks random. The scatter is what makes the thread valuable.
- [ ] **Fake histories, real videos** — every URL genuine and processable by Gemini
- [ ] Messy: repeats, Shorts, junk, one abandoned rabbit hole
- [ ] Deck + 3-minute demo script

---

## 9. Schedule

| Date | Gate | Definition of done |
|---|---|---|
| ~~24–25 Sep~~ | ~~Gate 0~~ | **PASSED** |
| 5 Oct | **Gate 1** | One history in → one Quest Card out, end to end, on Cloud Run. Ugly is fine. |
| 12 Oct | **Gate 2** | Feature complete: Common Ground, Search grounding, Guardian agent, graph visualisation |
| 14 Oct | **Code freeze** | Bug fixes only |
| 15 Oct | Rehearsed | Demo runs cold 5× with no intervention, Gemini cache pre-warmed |
| 16 Oct | Filmed | Allow the whole day |
| 18 Oct | **Submitted** | Portals fail on deadline day |

### Cut list, in order
1. Local-events Search grounding
2. Audience re-framing on reports
3. More than two children
4. Imagen illustration
5. Any auth beyond a single hardcoded household

**Never cut:** real video understanding · the Curiosity Graph reveal · Common Ground · the printed Quest Card. Those four *are* the demo.

---

## 10. The demo video — 3 minutes

| Time | Beat |
|---|---|
| 0:00–0:20 | Parent states the problem |
| 0:20–0:35 | Connect, consent boundary visible |
| 0:35–1:00 | Gemini reading actual videos, structured extraction visible |
| **1:00–1:50** | **The reveal — graph builds, peak on the unspoken interest** |
| **1:50–2:25** | **Common Ground — second graph, themes intersect, shared activity** |
| 2:25–2:40 | Quest Card printing, real hands, real paper |
| 2:40–3:00 | Loop closes, privacy, scale |

**Pitch order ≠ video order.** Live you have a narrator and can build tension; on video the arc must keep moving.

**The demo path ≠ the user path.** Video goes 2 → 3 → 5 → 6 → 11 → 9. Don't build screens the video never visits.

### Prepared answers
| Question | Answer |
|---|---|
| "Why doesn't Google build this?" | It's YouTube recommending less YouTube. The incentive misalignment is structural — a third party on parent-authorised data is the natural home. |
| "Isn't Takeout too hard for real families?" | Agreed, which is why it isn't the front door. Tier 1 is one sign-in, no file handling. |
| "Why not just let parents save videos?" | Then the product only tells a parent what they already told it. Saves are declared intent; the graph surfaces what nobody declared. |
| "Isn't this surveillance?" | The guardian already holds export rights. Ember shows derived themes with reasoning, never a raw feed. Outsiders get documents, never accounts. |
| "Is the demo data real?" | Histories are authored; every video in them is real and genuinely processed by Gemini. Stated up front. |

**Raise the child-data ethics question yourself before a judge does.** Consent chain + household boundary is the answer.

---

## 11. Ground rules

**Secrets.** `client_secret.json` is per-developer and stays local. `.gitignore` goes in **before** the first commit — deleting a secret later doesn't remove it from history. If one leaks, delete the OAuth client in GCP and make a new one.

**Work laptops.** Don't build on employer-managed hardware. IP clauses, blocked installs, and corporate tooling that interferes with the localhost OAuth callback. Personal machines, outside synced folders like OneDrive.

**Llamie is a test fixture, not a workspace.** No IAM role. Used only to sign in at the OAuth prompt or to add viewing. Everyone administers the project from their own account.

**One repo.** The team has already been through three. One owner, everyone else a collaborator, branch per feature, merge via PR. Don't re-home the codebase again.

---

## 12. Gotchas already hit — don't repeat these

| Symptom | Cause |
|---|---|
| Can't find Vertex AI in the console | Renamed to Agent Platform. Search `aiplatform` in the API Library. |
| Project missing from the console picker | Filtered by organization — look under "No organization" |
| `402 RESOURCE_EXHAUSTED` | The API key belonged to a different project than the one with billing |
| `404 model not found` | Typo in the model name. Check spelling character by character. |
| `503 high demand` | `gemini-3.8-flash` is the newest and busiest. The script falls back to 3.7 / 3.6 / 3.5 automatically. |
| Likes playlist empty | The account has no YouTube channel. Create one, re-like, rerun. |
| `access_denied` at OAuth | The signing-in account isn't on the test users list |
| Every video "skipped" | A 404 on the *model* was being misread as an unavailable *video*. Fixed. |
| `.gitignore` not working | Windows saved it as `.gitignore.txt`. Create it in VS Code, not Explorer. |

---

## 13. Open questions

| Question | Owner | Why it matters |
|---|---|---|
| Does tier 1 work on a supervised child account? | Backend | Decides whether one-tap onboarding is real |
| Does YouTube Kids viewing appear in Takeout? | Backend | Determines which YouTube surface we require |
| Is the likes signal rich enough alone? | ML | If thin, subscriptions carry more weight |
| Does the Quest Planner produce *good* activities? | ML | The other half of the product — untested |

---

## Your turn

Tell Claude which role you're taking and what you're working on. It has everything above.


https://claude.ai/share/525c7bfe-fd5b-4402-b071-beaef8f93df0
